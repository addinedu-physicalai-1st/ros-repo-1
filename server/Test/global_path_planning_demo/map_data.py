"""Static buffet test map for the global path planning demo.

The map intentionally uses a simple integer grid: each cell is 1 m on a
side. Obstacles are buffet stations, the kitchen, the dish-return area
and the outer wall. Waypoints are placed by hand at corridor junctions
and at strategic service stops (entrance, charging stations, kitchen,
return area, in front of buffet tables).

Edges connect waypoints that lie on the same row or column with no
obstacle between them. This enforces the straight + 90-degree-turn
motion the project wants for the pinky-pro robots, while still letting
the planner pick the shortest sequence of corridor segments.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple


# Map size in cells (1 cell == 1 m).
MAP_WIDTH: int = 20
MAP_HEIGHT: int = 15


@dataclass(frozen=True)
class Waypoint:
    """A node in the waypoint graph."""

    wp_id: int
    x: int
    y: int
    label: str = ""


@dataclass(frozen=True)
class Obstacle:
    """Inclusive axis-aligned rectangular obstacle."""

    name: str
    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def width(self) -> int:
        return self.x_max - self.x_min + 1

    @property
    def height(self) -> int:
        return self.y_max - self.y_min + 1

    def contains_point(self, x: int, y: int) -> bool:
        return (
            self.x_min <= x <= self.x_max
            and self.y_min <= y <= self.y_max
        )

    def contains_xy(self, x: float, y: float) -> bool:
        """Visual containment check for a continuous (float) point.

        Each integer cell is treated as a 1m x 1m square centred on its
        integer coordinates, so the visual footprint of the obstacle is
        ``[x_min - 0.5, x_max + 0.5] x [y_min - 0.5, y_max + 0.5]``.
        """
        return (
            self.x_min - 0.5 <= x <= self.x_max + 0.5
            and self.y_min - 0.5 <= y <= self.y_max + 0.5
        )


@dataclass
class WaypointGraph:
    """Undirected graph of waypoints connected by orthogonal corridors."""

    waypoints: Dict[int, Waypoint] = field(default_factory=dict)
    adjacency: Dict[int, List[int]] = field(default_factory=dict)

    def add_waypoint(self, wp: Waypoint) -> None:
        self.waypoints[wp.wp_id] = wp
        self.adjacency.setdefault(wp.wp_id, [])

    def connect(self, a: int, b: int) -> None:
        if b not in self.adjacency[a]:
            self.adjacency[a].append(b)
        if a not in self.adjacency[b]:
            self.adjacency[b].append(a)

    def neighbors(self, wp_id: int) -> List[int]:
        return self.adjacency.get(wp_id, [])

    def find_by_label(self, label: str) -> int:
        for wp in self.waypoints.values():
            if wp.label == label:
                return wp.wp_id
        raise KeyError(f"No waypoint with label {label!r}")


@dataclass
class BuffetMap:
    """Bundle of obstacles + waypoint graph for the buffet test scene."""

    obstacles: List[Obstacle]
    graph: WaypointGraph


# ---------------------------------------------------------------------------
# Static map definition
# ---------------------------------------------------------------------------


_OBSTACLE_DEFS: List[Obstacle] = [
    Obstacle("Buffet A1", 2, 2, 6, 5),
    Obstacle("Buffet A2", 8, 2, 12, 5),
    Obstacle("Buffet A3", 14, 2, 17, 5),
    Obstacle("Buffet B1", 2, 7, 6, 9),
    Obstacle("Buffet B2", 8, 7, 12, 9),
    Obstacle("Buffet B3", 14, 7, 17, 9),
    Obstacle("Kitchen", 2, 13, 7, 14),
    Obstacle("Return", 12, 13, 18, 14),
]


# (x, y, label) tuples. Empty label == anonymous junction waypoint.
_WAYPOINT_DEFS: List[Tuple[int, int, str]] = [
    # South corridor (entrance side).
    (1, 1, "CS-Left"),
    (4, 1, "A1-S"),
    (7, 1, ""),
    (10, 1, "Entrance"),
    (13, 1, ""),
    (15, 1, "A3-S"),
    (18, 1, "CS-Right"),
    # Mid corridor between buffet row A and row B.
    (1, 6, ""),
    (4, 6, "A1-N/B1-S"),
    (7, 6, ""),
    (10, 6, "A2-N/B2-S"),
    (13, 6, ""),
    (15, 6, "A3-N/B3-S"),
    (18, 6, ""),
    # Mid corridor north of buffet row B.
    (1, 10, ""),
    (4, 10, "B1-N"),
    (7, 10, ""),
    (10, 10, "B2-N"),
    (13, 10, ""),
    (15, 10, "B3-N"),
    (18, 10, ""),
    # Top corridor in front of kitchen / return area.
    (1, 12, ""),
    (4, 12, "Kitchen"),
    (7, 12, ""),
    (13, 12, ""),
    (15, 12, "Return"),
    (18, 12, ""),
]


def _segment_blocked(
    a: Waypoint, b: Waypoint, obstacles: List[Obstacle]
) -> bool:
    """Return True if the axis-aligned segment a->b crosses any obstacle."""
    if a.x == b.x:
        x = a.x
        y_lo, y_hi = sorted((a.y, b.y))
        for y in range(y_lo, y_hi + 1):
            if any(o.contains_point(x, y) for o in obstacles):
                return True
        return False
    if a.y == b.y:
        y = a.y
        x_lo, x_hi = sorted((a.x, b.x))
        for x in range(x_lo, x_hi + 1):
            if any(o.contains_point(x, y) for o in obstacles):
                return True
        return False
    raise ValueError("Only axis-aligned segments are supported.")


def _connect_neighbors(
    graph: WaypointGraph, obstacles: List[Obstacle]
) -> None:
    """Connect each waypoint to its nearest free neighbor on the same axis.

    Only the immediate next waypoint along +x / +y is considered. The
    connection is added when the segment is fully clear of obstacles,
    which guarantees the resulting graph encodes straight corridor
    segments joined by 90-degree turns.
    """
    by_row: Dict[int, List[Waypoint]] = defaultdict(list)
    by_col: Dict[int, List[Waypoint]] = defaultdict(list)
    for wp in graph.waypoints.values():
        by_row[wp.y].append(wp)
        by_col[wp.x].append(wp)

    for row in by_row.values():
        row.sort(key=lambda w: w.x)
        for a, b in zip(row, row[1:]):
            if not _segment_blocked(a, b, obstacles):
                graph.connect(a.wp_id, b.wp_id)

    for col in by_col.values():
        col.sort(key=lambda w: w.y)
        for a, b in zip(col, col[1:]):
            if not _segment_blocked(a, b, obstacles):
                graph.connect(a.wp_id, b.wp_id)


def is_inside_any_obstacle(
    x: float, y: float, obstacles: Iterable[Obstacle]
) -> bool:
    """True if the continuous point (x, y) lies inside any obstacle."""
    return any(o.contains_xy(x, y) for o in obstacles)


def is_in_map_bounds(x: float, y: float) -> bool:
    """True if the continuous point lies inside the outer wall."""
    return (
        -0.5 <= x <= MAP_WIDTH - 0.5
        and -0.5 <= y <= MAP_HEIGHT - 0.5
    )


def is_line_clear(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    obstacles: Iterable[Obstacle],
    step: float = 0.1,
) -> bool:
    """Sample-based line-of-sight check between two continuous points.

    The segment is sampled every ``step`` metres; if any sample lies
    inside an obstacle, the segment is reported as blocked. ``step``
    is small enough (10 cm) for the demo's 1 m grid.
    """
    obstacles = list(obstacles)
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0.0:
        return not is_inside_any_obstacle(x1, y1, obstacles)
    samples = max(2, int(math.ceil(length / step)) + 1)
    for i in range(samples):
        t = i / (samples - 1)
        x = x1 + t * dx
        y = y1 + t * dy
        if is_inside_any_obstacle(x, y, obstacles):
            return False
    return True


def build_buffet_map() -> BuffetMap:
    """Build the static buffet test map used by the demo."""
    obstacles = list(_OBSTACLE_DEFS)
    graph = WaypointGraph()
    for wp_id, (x, y, label) in enumerate(_WAYPOINT_DEFS):
        graph.add_waypoint(Waypoint(wp_id=wp_id, x=x, y=y, label=label))
    _connect_neighbors(graph, obstacles)
    return BuffetMap(obstacles=obstacles, graph=graph)
