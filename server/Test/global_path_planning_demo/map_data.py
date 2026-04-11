"""Buffet test map for the global path planning demo.

The demo supports two map file formats. Both are loaded through the
single :func:`load_buffet_map` entry point and exposed to the rest of
the code as a :class:`BuffetMap` containing:

* a :class:`StaticEnv` (collision queries against the static map)
* a :class:`WaypointGraph` (the corridor graph the planner searches)
* the world-frame extent (``origin_x/y``, ``width_m``, ``height_m``)

Format 1 - "rect" YAML
----------------------
A self-contained YAML file with axis-aligned rectangular obstacles and
hand-placed integer waypoints. Cells are 1 m on a side. This is the
fast-iteration / unit-test format. See ``maps/buffet_default.yaml``.

Format 2 - Nav2 map_server YAML + PGM
-------------------------------------
A standard Nav2 map_server file (``image:``, ``resolution:``,
``origin:``, ``negate:``, ``occupied_thresh:``, ``free_thresh:``,
``mode:``) extended with the demo's own ``waypoints:`` (and optional
``name:``) keys. Nav2's map_server ignores unknown keys, so the same
file can be served to Nav2's costmap **and** to this demo without
duplication.

The format is auto-detected at load time: presence of an ``image:``
key picks the Nav2 loader, presence of an ``obstacles:`` key picks the
rect loader.

Edges are auto-built: every consecutive pair of waypoints on the same
row or column is connected if the connecting axis-aligned segment is
clear of static obstacles. This enforces the straight + 90-degree-turn
motion the project wants for the pinky-pro robots.
"""

from __future__ import annotations

import io
import math
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
    Union,
)

import numpy as np
import yaml


# Default YAML map shipped with the demo.
DEFAULT_MAP_PATH: Path = (
    Path(__file__).parent / "maps" / "buffet_default.yaml"
)

# Pinky-pro physical dimensions (derived from the URDF and the Nav2
# costmap config in ``pinky_navigation/params/nav2_params.yaml``):
#
#   base_link inertia box  : 0.09 x 0.08 x 0.086 m
#   Nav2 footprint (square): 0.12 x 0.12 m (half-extent 0.06)
#   Nav2 footprint_padding : 0.03 m
#
# The inscribed radius of the 12 cm square is 0.06 m; adding the
# 0.03 m footprint_padding gives 0.09 m, which matches what Nav2's
# local costmap effectively uses as the robot radius for the inflation
# layer. The circumscribed radius (sqrt(2) * 0.06 + 0.03 ~= 0.115 m)
# would be even more conservative but leaves almost no free space
# inside the tight 2 m x 1.6 m buffet; we match Nav2 and use the
# inscribed value.
PINKY_PRO_RADIUS: float = 0.09

# Circular footprint (in metres) used for a dynamic obstacle when no
# per-map default is provided. Sized to cover another pinky-pro disc.
# Large test maps (buffet_default) explicitly override this via their
# ``defaults:`` block.
DEFAULT_DYNAMIC_RADIUS: float = 0.12

# Maximum allowed straight-line distance from a free start point to its
# entry waypoint. Small-space default appropriate for the pinky-pro
# deployment scale. Large maps override via ``defaults:``.
DEFAULT_ENTRY_RADIUS: float = 0.40

# Default inflation of static obstacles (in metres). Matches the
# pinky-pro inscribed radius + Nav2 padding so the global planner by
# default plans safely for the real robot.
DEFAULT_INFLATION_RADIUS: float = PINKY_PRO_RADIUS

# Sampling step (m) used for line-of-sight / segment-clear checks. Small
# enough for the demo's 1 m grid and the typical 0.05 m SLAM resolution.
DEFAULT_SEGMENT_SAMPLE_STEP: float = 0.1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Waypoint:
    """A node in the waypoint graph (world-frame coordinates, metres)."""

    wp_id: int
    x: float
    y: float
    label: str = ""


@dataclass(frozen=True)
class Obstacle:
    """Inclusive axis-aligned rectangular obstacle (rect format only).

    The integer ``[x_min..x_max] x [y_min..y_max]`` range is interpreted
    as cells, each visually a 1 m square centred on its integer
    coordinate. The visual footprint of the obstacle is therefore
    ``[x_min - 0.5, x_max + 0.5] x [y_min - 0.5, y_max + 0.5]``.
    """

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

    def contains_xy(self, x: float, y: float) -> bool:
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


# ---------------------------------------------------------------------------
# Graph topology analysis: cut vertices and bridges (Tarjan)
# ---------------------------------------------------------------------------


def find_cut_vertices_and_bridges(
    graph: WaypointGraph,
) -> Tuple[Set[int], Set[FrozenSet[int]]]:
    """Find articulation points and bridges in the waypoint graph.

    Returns ``(cut_vertices, bridges)`` where:

    * ``cut_vertices`` is the set of waypoint ids whose removal would
      split the graph into additional connected components. Parking a
      robot on a cut vertex disconnects the map.
    * ``bridges`` is the set of edges (as ``frozenset({a, b})``) whose
      removal disconnects the graph.

    Implemented with the standard single-pass Tarjan DFS
    (O(V + E)). On the demo's 12-waypoint / 13-edge graph this runs in
    microseconds, so we recompute eagerly at map load time.
    """
    cut_vertices: Set[int] = set()
    bridges: Set[FrozenSet[int]] = set()

    disc: Dict[int, int] = {}
    low: Dict[int, int] = {}
    parent: Dict[int, Optional[int]] = {}
    timer = 0

    def dfs(u: int) -> None:
        nonlocal timer
        disc[u] = low[u] = timer
        timer += 1
        children = 0
        for v in graph.neighbors(u):
            if v not in disc:
                parent[v] = u
                children += 1
                dfs(v)
                low[u] = min(low[u], low[v])
                if low[v] > disc[u]:
                    bridges.add(frozenset((u, v)))
                if parent[u] is not None and low[v] >= disc[u]:
                    cut_vertices.add(u)
            elif v != parent.get(u):
                low[u] = min(low[u], disc[v])
        if parent[u] is None and children > 1:
            cut_vertices.add(u)

    for wp_id in graph.waypoints:
        if wp_id not in disc:
            parent[wp_id] = None
            dfs(wp_id)

    return cut_vertices, bridges


def components_after_removing(
    graph: WaypointGraph, removed: int
) -> List[Set[int]]:
    """List connected components of the graph after removing ``removed``.

    The removed waypoint itself is not included in any of the returned
    components. Used by HQ-level policy: "if I park Robot A at
    waypoint X, which other waypoints become unreachable?"
    """
    if removed not in graph.waypoints:
        raise KeyError(f"Unknown waypoint id {removed}")
    visited: Set[int] = {removed}
    components: List[Set[int]] = []
    for wp_id in graph.waypoints:
        if wp_id in visited:
            continue
        comp: Set[int] = set()
        stack = [wp_id]
        while stack:
            u = stack.pop()
            if u in visited:
                continue
            visited.add(u)
            comp.add(u)
            for v in graph.neighbors(u):
                if v == removed or v in visited:
                    continue
                stack.append(v)
        components.append(comp)
    return components


@dataclass
class MapDefaults:
    """Per-map default values for the planner and visualizer.

    These scale with the physical size of the map so a tiny 2 m x 1.6 m
    deployment and a 20 m x 15 m test hall can share the same code. They
    are populated from the optional ``defaults:`` block in the YAML
    file; missing fields fall back to the module-level globals.
    """

    entry_radius: float = DEFAULT_ENTRY_RADIUS
    dynamic_radius: float = DEFAULT_DYNAMIC_RADIUS
    inflation_radius: float = DEFAULT_INFLATION_RADIUS


@dataclass
class DynamicObstacle:
    """Quasi-static circular obstacle (e.g. another robot parked or
    momentarily stopped in a corridor).

    Treated as an immovable disc by the planner at the moment ``plan_*``
    is called. Real motion of other robots is handled outside this
    module by re-running the planner with an updated snapshot - this
    matches the standard Nav2-style architecture in which a Local
    Planner takes care of the actual avoidance.
    """

    obs_id: int
    x: float
    y: float
    radius: float = DEFAULT_DYNAMIC_RADIUS
    label: str = ""


# ---------------------------------------------------------------------------
# Static environment abstraction
# ---------------------------------------------------------------------------


class StaticEnv(ABC):
    """Abstract collision interface against the static map.

    Implementations only need to answer two geometric questions in
    world-frame metres. The planner and visualizer dispatch all
    static-collision queries through this interface, so they work
    identically for hand-authored rectangle maps and for SLAM-derived
    occupancy grids.
    """

    @abstractmethod
    def contains_xy(self, x: float, y: float) -> bool:
        """True if the continuous point (x, y) lies inside any obstacle."""

    @abstractmethod
    def is_segment_clear(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> bool:
        """True if the segment from (x1, y1) to (x2, y2) is clear."""

    def draw_on(self, ax) -> None:  # pragma: no cover - visual
        """Draw this environment as background on a matplotlib axes.

        Default no-op; concrete implementations override.
        """
        return None


class RectangleEnv(StaticEnv):
    """Static environment composed of axis-aligned rectangular obstacles.

    Supports static inflation: a point is considered "inside" an
    obstacle if the distance from the point to the rectangle's visual
    footprint is at most ``inflation_radius``. This effectively grows
    every obstacle outward by ``inflation_radius`` in all directions,
    letting the planner keep a safety margin for the ego robot's
    footprint without having to re-author the map.
    """

    def __init__(
        self,
        obstacles: Iterable[Obstacle],
        sample_step: float = DEFAULT_SEGMENT_SAMPLE_STEP,
        inflation_radius: float = 0.0,
    ) -> None:
        if inflation_radius < 0.0:
            raise ValueError("inflation_radius must be non-negative")
        self.obstacles: List[Obstacle] = list(obstacles)
        self.sample_step = sample_step
        self.inflation_radius = inflation_radius

    @staticmethod
    def _dist_point_to_rect(
        obs: Obstacle, x: float, y: float
    ) -> float:
        # Distance from a continuous point to an obstacle's visual
        # footprint (0 if the point is inside).
        dx = max(obs.x_min - 0.5 - x, x - (obs.x_max + 0.5), 0.0)
        dy = max(obs.y_min - 0.5 - y, y - (obs.y_max + 0.5), 0.0)
        return math.hypot(dx, dy)

    def contains_xy(self, x: float, y: float) -> bool:
        if self.inflation_radius == 0.0:
            return any(o.contains_xy(x, y) for o in self.obstacles)
        for o in self.obstacles:
            if self._dist_point_to_rect(o, x, y) <= self.inflation_radius:
                return True
        return False

    def is_segment_clear(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> bool:
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length == 0.0:
            return not self.contains_xy(x1, y1)
        samples = max(2, int(math.ceil(length / self.sample_step)) + 1)
        for i in range(samples):
            t = i / (samples - 1)
            if self.contains_xy(x1 + t * dx, y1 + t * dy):
                return False
        return True

    def draw_on(self, ax) -> None:  # pragma: no cover - visual
        import matplotlib.patches as mpatches

        for obs in self.obstacles:
            # Inflation band (if any), drawn first so the original
            # obstacle sits on top as the primary visual.
            if self.inflation_radius > 0.0:
                band = mpatches.Rectangle(
                    (
                        obs.x_min - 0.5 - self.inflation_radius,
                        obs.y_min - 0.5 - self.inflation_radius,
                    ),
                    obs.width + 2 * self.inflation_radius,
                    obs.height + 2 * self.inflation_radius,
                    facecolor="#d62728",
                    edgecolor="#a0171c",
                    linewidth=0.8,
                    alpha=0.15,
                    linestyle="--",
                )
                ax.add_patch(band)
            rect = mpatches.Rectangle(
                (obs.x_min - 0.5, obs.y_min - 0.5),
                obs.width,
                obs.height,
                facecolor="#b0b0b0",
                edgecolor="#404040",
                linewidth=1.0,
                alpha=0.85,
            )
            ax.add_patch(rect)
            cx = (obs.x_min + obs.x_max) / 2.0
            cy = (obs.y_min + obs.y_max) / 2.0
            ax.text(
                cx,
                cy,
                obs.name,
                ha="center",
                va="center",
                fontsize=8,
                color="#202020",
            )


def _dilate_mask_disc(mask: np.ndarray, radius_px: int) -> np.ndarray:
    """Morphological dilation of ``mask`` with a disc of ``radius_px``.

    Pure numpy (no scipy). For each offset inside the disc kernel,
    shift the original mask and OR it into the result. With a 40x32
    grid and radius ~4 px this is ~50 whole-mask ORs, trivially fast.
    """
    if radius_px <= 0:
        return mask.astype(bool, copy=True)
    rows, cols = mask.shape
    padded = np.zeros(
        (rows + 2 * radius_px, cols + 2 * radius_px), dtype=bool
    )
    padded[
        radius_px : radius_px + rows,
        radius_px : radius_px + cols,
    ] = mask
    result = np.zeros_like(mask, dtype=bool)
    r2 = radius_px * radius_px
    for dy in range(-radius_px, radius_px + 1):
        for dx in range(-radius_px, radius_px + 1):
            if dx * dx + dy * dy > r2:
                continue
            result |= padded[
                radius_px + dy : radius_px + dy + rows,
                radius_px + dx : radius_px + dx + cols,
            ]
    return result


class OccupancyGridEnv(StaticEnv):
    """Static environment backed by a Nav2-style occupancy grid.

    ``occupied`` is a boolean ``numpy.ndarray`` of shape (rows, cols)
    where ``True`` means "obstacle (or unknown, treated as obstacle)".
    Row 0 is the bottom of the grid in world coordinates (i.e. the
    array has already been ``flipud``-ed compared to a raw PGM, where
    row 0 is the top of the image).

    World <-> pixel:
        col = floor((x - origin_x) / resolution)
        row = floor((y - origin_y) / resolution)
    Cells outside the grid bounds count as occupied (acts like an
    implicit outer wall).

    If ``inflation_radius > 0`` the grid is dilated by an equivalent
    number of pixels at construction time, so the stored ``occupied``
    mask already reflects the robot's safety margin.
    """

    def __init__(
        self,
        occupied: np.ndarray,
        resolution: float,
        origin_x: float,
        origin_y: float,
        sample_step: Optional[float] = None,
        inflation_radius: float = 0.0,
    ) -> None:
        if occupied.ndim != 2:
            raise ValueError("occupancy grid must be a 2D array")
        if resolution <= 0.0:
            raise ValueError("resolution must be positive")
        if inflation_radius < 0.0:
            raise ValueError("inflation_radius must be non-negative")
        base = occupied.astype(bool, copy=False)
        self.original_occupied: np.ndarray = base
        self.inflation_radius: float = float(inflation_radius)
        if inflation_radius > 0.0:
            radius_px = int(math.ceil(inflation_radius / resolution))
            self.occupied: np.ndarray = _dilate_mask_disc(base, radius_px)
        else:
            self.occupied = base
        self.resolution: float = float(resolution)
        self.origin_x: float = float(origin_x)
        self.origin_y: float = float(origin_y)
        self.rows: int = self.occupied.shape[0]
        self.cols: int = self.occupied.shape[1]
        # Sample step defaults to half the cell size so we never skip a
        # whole cell on a diagonal segment.
        self.sample_step: float = (
            sample_step if sample_step is not None else self.resolution * 0.5
        )

    @property
    def width_m(self) -> float:
        return self.cols * self.resolution

    @property
    def height_m(self) -> float:
        return self.rows * self.resolution

    def world_to_pixel(self, x: float, y: float) -> Tuple[int, int]:
        col = int(math.floor((x - self.origin_x) / self.resolution))
        row = int(math.floor((y - self.origin_y) / self.resolution))
        return col, row

    def contains_xy(self, x: float, y: float) -> bool:
        col, row = self.world_to_pixel(x, y)
        if col < 0 or row < 0 or col >= self.cols or row >= self.rows:
            return True
        return bool(self.occupied[row, col])

    def is_segment_clear(
        self, x1: float, y1: float, x2: float, y2: float
    ) -> bool:
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length == 0.0:
            return not self.contains_xy(x1, y1)
        samples = max(2, int(math.ceil(length / self.sample_step)) + 1)
        for i in range(samples):
            t = i / (samples - 1)
            if self.contains_xy(x1 + t * dx, y1 + t * dy):
                return False
        return True

    def draw_on(self, ax) -> None:  # pragma: no cover - visual
        # imshow draws array[0,0] at the top by default; flip vertically
        # so that row 0 (world bottom) is rendered at the bottom of the
        # axes. The primary layer is the original (non-inflated) map so
        # operators still see their SLAM scan; an optional overlay
        # highlights the inflation band.
        base = np.where(self.original_occupied, 0, 255).astype(np.uint8)
        extent = (
            self.origin_x,
            self.origin_x + self.width_m,
            self.origin_y,
            self.origin_y + self.height_m,
        )
        ax.imshow(
            np.flipud(base),
            cmap="gray",
            vmin=0,
            vmax=255,
            extent=extent,
            interpolation="nearest",
            zorder=0,
        )
        if self.inflation_radius > 0.0:
            band = self.occupied & ~self.original_occupied
            if band.any():
                rgba = np.zeros((*band.shape, 4), dtype=np.float32)
                rgba[band] = (0.839, 0.153, 0.157, 0.30)  # #d62728 @ 30%
                ax.imshow(
                    np.flipud(rgba),
                    extent=extent,
                    interpolation="nearest",
                    zorder=0.5,
                )


# ---------------------------------------------------------------------------
# BuffetMap bundle
# ---------------------------------------------------------------------------


@dataclass
class BuffetMap:
    """Bundle of static environment + waypoint graph + world extent."""

    static_env: StaticEnv
    graph: WaypointGraph
    origin_x: float
    origin_y: float
    width_m: float
    height_m: float
    name: str = ""
    # Per-map default values for entry_radius / dynamic_radius /
    # inflation_radius. Pulled from the optional `defaults:` block in
    # the YAML file.
    defaults: MapDefaults = field(default_factory=MapDefaults)
    # Optional: original obstacle list for the rect format. Kept around
    # so callers that want to inspect named regions still can.
    rect_obstacles: Optional[List[Obstacle]] = None
    # Topology analysis results, computed once in __post_init__.
    # cut_vertices : waypoint ids whose removal disconnects the graph
    # bridges      : edges (as frozensets of two ids) whose removal
    #                disconnects the graph
    cut_vertices: Set[int] = field(default_factory=set)
    bridges: Set[FrozenSet[int]] = field(default_factory=set)

    def __post_init__(self) -> None:
        # Compute bottleneck information once per map load. Cheap on
        # the demo's small graphs (microseconds).
        if self.graph.waypoints and not self.cut_vertices and not self.bridges:
            cv, br = find_cut_vertices_and_bridges(self.graph)
            self.cut_vertices = cv
            self.bridges = br

    def is_in_bounds(self, x: float, y: float) -> bool:
        return (
            self.origin_x <= x <= self.origin_x + self.width_m
            and self.origin_y <= y <= self.origin_y + self.height_m
        )

    def is_cut_vertex(self, wp_id: int) -> bool:
        return wp_id in self.cut_vertices

    def is_bridge(self, a: int, b: int) -> bool:
        return frozenset((a, b)) in self.bridges

    def components_after_removing(
        self, wp_id: int
    ) -> List[Set[int]]:
        """Return connected components of the graph after removing
        ``wp_id``. Used by HQ Service multi-robot policy to check what
        regions become unreachable if a robot parks on ``wp_id``.
        """
        return components_after_removing(self.graph, wp_id)


# ---------------------------------------------------------------------------
# Geometry helpers (point/disc primitives reused by the planner)
# ---------------------------------------------------------------------------


def circle_contains_point(
    cx: float, cy: float, radius: float, x: float, y: float
) -> bool:
    """True if (x, y) lies inside the closed disc centred at (cx, cy)."""
    return math.hypot(cx - x, cy - y) <= radius


def circle_intersects_segment(
    cx: float,
    cy: float,
    radius: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> bool:
    """True if the closed disc intersects the segment (x1,y1)->(x2,y2).

    Computes the closest point on the segment to the disc centre using
    the standard parametric projection clamped to ``[0, 1]``, then
    compares its distance to ``radius``.
    """
    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return math.hypot(cx - x1, cy - y1) <= radius
    t = ((cx - x1) * dx + (cy - y1) * dy) / seg_len_sq
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    return math.hypot(cx - closest_x, cy - closest_y) <= radius


# ---------------------------------------------------------------------------
# Edge auto-building
# ---------------------------------------------------------------------------


def _connect_neighbors(
    graph: WaypointGraph, static_env: StaticEnv
) -> None:
    """Connect each waypoint to its nearest free neighbour on the same axis.

    For every pair of consecutive waypoints sharing a row (same y) or a
    column (same x), the connecting axis-aligned segment is checked
    against the static environment; if clear, an edge is added.
    """
    by_row: Dict[float, List[Waypoint]] = defaultdict(list)
    by_col: Dict[float, List[Waypoint]] = defaultdict(list)
    for wp in graph.waypoints.values():
        by_row[wp.y].append(wp)
        by_col[wp.x].append(wp)

    for row in by_row.values():
        row.sort(key=lambda w: w.x)
        for a, b in zip(row, row[1:]):
            if static_env.is_segment_clear(a.x, a.y, b.x, b.y):
                graph.connect(a.wp_id, b.wp_id)

    for col in by_col.values():
        col.sort(key=lambda w: w.y)
        for a, b in zip(col, col[1:]):
            if static_env.is_segment_clear(a.x, a.y, b.x, b.y):
                graph.connect(a.wp_id, b.wp_id)


# ---------------------------------------------------------------------------
# YAML loading - shared helpers
# ---------------------------------------------------------------------------


def _require_keys(
    section: str, data: Mapping[str, Any], required: Iterable[str]
) -> None:
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(
            f"map: section {section!r} is missing required key(s): "
            f"{', '.join(missing)}"
        )


def _require_int(section: str, key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"map: {section}.{key} must be an integer, got "
            f"{type(value).__name__}: {value!r}"
        )
    return value


def _require_number(section: str, key: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"map: {section}.{key} must be a number, got "
            f"{type(value).__name__}: {value!r}"
        )
    return float(value)


def _parse_defaults(raw: Any) -> MapDefaults:
    """Parse the optional top-level ``defaults:`` block."""
    if raw is None:
        return MapDefaults()
    if not isinstance(raw, Mapping):
        raise ValueError("map: 'defaults' must be a mapping")
    result = MapDefaults()
    allowed = ("entry_radius", "dynamic_radius", "inflation_radius")
    for key, value in raw.items():
        if key not in allowed:
            raise ValueError(
                f"map: defaults has unknown key {key!r}; "
                f"expected one of {allowed}"
            )
        num = _require_number(f"defaults", key, value)
        if num < 0.0:
            raise ValueError(
                f"map: defaults.{key} must be non-negative, got {num}"
            )
        if key == "entry_radius" and num == 0.0:
            raise ValueError(
                "map: defaults.entry_radius must be positive"
            )
        if key == "dynamic_radius" and num == 0.0:
            raise ValueError(
                "map: defaults.dynamic_radius must be positive"
            )
        setattr(result, key, num)
    return result


def _parse_waypoint_entries(
    raw: Any,
    static_env: StaticEnv,
    bounds: Tuple[float, float, float, float],
) -> List[Waypoint]:
    """Parse a 'waypoints:' YAML list and return Waypoint objects.

    ``bounds`` is ``(x_min, x_max, y_min, y_max)`` in world metres.
    Coordinates may be int or float; integer-grid maps still validate
    correctly because Python compares int/float numerically.
    """
    if not isinstance(raw, list):
        raise ValueError("map: 'waypoints' must be a list")
    if not raw:
        raise ValueError("map: 'waypoints' is empty")

    x_min, x_max, y_min, y_max = bounds
    waypoints: List[Waypoint] = []
    seen_xy: Dict[Tuple[float, float], int] = {}
    seen_labels: Dict[str, int] = {}
    for i, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise ValueError(f"map: waypoint #{i} must be a mapping")
        section = f"waypoints[{i}]"
        _require_keys(section, entry, ("x", "y"))
        x = _require_number(section, "x", entry["x"])
        y = _require_number(section, "y", entry["y"])
        label = entry.get("label", "") or ""
        if not isinstance(label, str):
            raise ValueError(f"map: {section}.label must be a string")
        if not (x_min <= x <= x_max and y_min <= y <= y_max):
            raise ValueError(
                f"map: {section} ({x},{y}) is outside the map "
                f"[{x_min},{x_max}] x [{y_min},{y_max}]"
            )
        if static_env.contains_xy(x, y):
            raise ValueError(
                f"map: {section} ({x},{y}) lies inside a static obstacle"
            )
        if (x, y) in seen_xy:
            raise ValueError(
                f"map: {section} ({x},{y}) duplicates waypoint #"
                f"{seen_xy[(x, y)]}"
            )
        seen_xy[(x, y)] = i
        if label:
            if label in seen_labels:
                raise ValueError(
                    f"map: {section}.label {label!r} duplicates waypoint #"
                    f"{seen_labels[label]}"
                )
            seen_labels[label] = i
        waypoints.append(Waypoint(wp_id=i, x=x, y=y, label=label))
    return waypoints


# ---------------------------------------------------------------------------
# Rect format loader
# ---------------------------------------------------------------------------


def _parse_rect_obstacles(
    raw: Any, width: int, height: int
) -> List[Obstacle]:
    if not isinstance(raw, list):
        raise ValueError("map: 'obstacles' must be a list")
    obstacles: List[Obstacle] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise ValueError(f"map: obstacle #{i} must be a mapping")
        section = f"obstacles[{i}]"
        _require_keys(
            section, entry, ("name", "x_min", "y_min", "x_max", "y_max")
        )
        x_min = _require_int(section, "x_min", entry["x_min"])
        y_min = _require_int(section, "y_min", entry["y_min"])
        x_max = _require_int(section, "x_max", entry["x_max"])
        y_max = _require_int(section, "y_max", entry["y_max"])
        if x_min > x_max or y_min > y_max:
            raise ValueError(
                f"map: {section} has inverted bounds "
                f"({x_min},{y_min})-({x_max},{y_max})"
            )
        if (
            x_min < 0
            or y_min < 0
            or x_max > width - 1
            or y_max > height - 1
        ):
            raise ValueError(
                f"map: {section} extends outside the map "
                f"(width={width}, height={height})"
            )
        name = entry["name"]
        if not isinstance(name, str) or not name:
            raise ValueError(f"map: {section}.name must be a non-empty string")
        obstacles.append(
            Obstacle(
                name=name,
                x_min=x_min,
                y_min=y_min,
                x_max=x_max,
                y_max=y_max,
            )
        )
    return obstacles


def _load_rect_map(raw: Mapping[str, Any], yaml_path: Path) -> BuffetMap:
    _require_keys("<root>", raw, ("size", "obstacles", "waypoints"))
    size = raw["size"]
    if not isinstance(size, Mapping):
        raise ValueError("map: 'size' must be a mapping with width/height")
    _require_keys("size", size, ("width", "height"))
    width = _require_int("size", "width", size["width"])
    height = _require_int("size", "height", size["height"])
    if width <= 0 or height <= 0:
        raise ValueError(
            f"map: size must be positive, got width={width}, height={height}"
        )

    name_value = raw.get("name", "") or ""
    if not isinstance(name_value, str):
        raise ValueError("map: 'name' must be a string")

    defaults = _parse_defaults(raw.get("defaults"))

    obstacles = _parse_rect_obstacles(raw["obstacles"], width, height)
    static_env = RectangleEnv(
        obstacles, inflation_radius=defaults.inflation_radius
    )
    bounds = (-0.5, width - 0.5, -0.5, height - 0.5)
    waypoints = _parse_waypoint_entries(raw["waypoints"], static_env, bounds)

    graph = WaypointGraph()
    for wp in waypoints:
        graph.add_waypoint(wp)
    _connect_neighbors(graph, static_env)

    return BuffetMap(
        static_env=static_env,
        graph=graph,
        origin_x=-0.5,
        origin_y=-0.5,
        width_m=float(width),
        height_m=float(height),
        name=name_value,
        defaults=defaults,
        rect_obstacles=obstacles,
    )


# ---------------------------------------------------------------------------
# Nav2 (PGM + YAML) format loader
# ---------------------------------------------------------------------------


def _read_pgm_p5(path: Path) -> np.ndarray:
    """Minimal P5 (binary grayscale) PGM reader.

    Returns a ``numpy.uint8`` array of shape (height, width) where row 0
    is the *top* of the image (raw PGM convention; the caller flips it
    when needed).
    """
    with path.open("rb") as fh:
        data = fh.read()
    stream = io.BytesIO(data)

    def _next_token() -> bytes:
        # Skip whitespace and comments.
        while True:
            ch = stream.read(1)
            if not ch:
                raise ValueError(f"PGM {path}: unexpected EOF in header")
            if ch in (b" ", b"\t", b"\r", b"\n"):
                continue
            if ch == b"#":
                stream.readline()
                continue
            break
        token = ch
        while True:
            ch = stream.read(1)
            if not ch or ch in (b" ", b"\t", b"\r", b"\n"):
                break
            token += ch
        return token

    magic = _next_token()
    if magic != b"P5":
        raise ValueError(
            f"PGM {path}: expected P5 magic, got {magic!r}"
        )
    width = int(_next_token())
    height = int(_next_token())
    maxval = int(_next_token())
    if maxval <= 0 or maxval > 65535:
        raise ValueError(
            f"PGM {path}: invalid maxval {maxval}"
        )

    expected_bytes = width * height * (1 if maxval < 256 else 2)
    pixel_data = stream.read(expected_bytes)
    if len(pixel_data) != expected_bytes:
        raise ValueError(
            f"PGM {path}: expected {expected_bytes} pixel bytes, "
            f"got {len(pixel_data)}"
        )

    if maxval < 256:
        arr = np.frombuffer(pixel_data, dtype=np.uint8)
    else:
        arr = np.frombuffer(pixel_data, dtype=">u2").astype(np.uint16)
        arr = (arr.astype(np.float32) * 255.0 / maxval).astype(np.uint8)
    return arr.reshape((height, width))


def _pgm_to_occupancy(
    pgm: np.ndarray,
    negate: int,
    occupied_thresh: float,
    free_thresh: float,
    mode: str,
) -> np.ndarray:
    """Convert a raw PGM array to a boolean occupancy mask.

    Follows the Nav2 map_server convention. ``True`` means "occupied or
    unknown" - the planner treats unknown cells as obstacles for safety.
    """
    if negate not in (0, 1):
        raise ValueError(f"map: 'negate' must be 0 or 1, got {negate}")
    if mode not in ("trinary", "scale", "raw"):
        raise ValueError(
            f"map: unsupported mode {mode!r}, expected one of "
            "'trinary', 'scale', 'raw'"
        )
    if negate == 1:
        prob = pgm.astype(np.float32) / 255.0
    else:
        prob = (255.0 - pgm.astype(np.float32)) / 255.0
    if mode == "raw":
        # Raw mode: any non-fully-free cell is an obstacle.
        return prob > 0.0
    # Trinary / scale: anything not clearly free is treated as obstacle.
    return prob >= free_thresh


def _load_nav2_map(raw: Mapping[str, Any], yaml_path: Path) -> BuffetMap:
    _require_keys(
        "<root>",
        raw,
        ("image", "resolution", "origin"),
    )
    image_field = raw["image"]
    if not isinstance(image_field, str) or not image_field:
        raise ValueError("map: 'image' must be a non-empty string")
    image_path = (yaml_path.parent / image_field).resolve()
    if not image_path.exists():
        raise FileNotFoundError(
            f"PGM image not found for map {yaml_path}: {image_path}"
        )

    resolution = _require_number("<root>", "resolution", raw["resolution"])
    if resolution <= 0.0:
        raise ValueError(
            f"map: resolution must be positive, got {resolution}"
        )

    origin = raw["origin"]
    if not isinstance(origin, list) or len(origin) < 2:
        raise ValueError(
            "map: 'origin' must be a list of [x, y] (yaw optional)"
        )
    origin_x = _require_number("origin", "[0]", origin[0])
    origin_y = _require_number("origin", "[1]", origin[1])
    # Yaw (origin[2]) is read but not applied; SLAM almost always emits 0.

    negate = int(raw.get("negate", 0) or 0)
    occupied_thresh = float(raw.get("occupied_thresh", 0.65))
    free_thresh = float(raw.get("free_thresh", 0.196))
    mode = raw.get("mode", "trinary") or "trinary"

    pgm = _read_pgm_p5(image_path)
    pgm_world = np.flipud(pgm)  # row 0 = world bottom
    occupancy = _pgm_to_occupancy(
        pgm_world,
        negate=negate,
        occupied_thresh=occupied_thresh,
        free_thresh=free_thresh,
        mode=mode,
    )

    defaults = _parse_defaults(raw.get("defaults"))

    static_env = OccupancyGridEnv(
        occupied=occupancy,
        resolution=resolution,
        origin_x=origin_x,
        origin_y=origin_y,
        inflation_radius=defaults.inflation_radius,
    )

    name_value = raw.get("name", "") or ""
    if not isinstance(name_value, str):
        raise ValueError("map: 'name' must be a string")

    bounds = (
        origin_x,
        origin_x + static_env.width_m,
        origin_y,
        origin_y + static_env.height_m,
    )

    raw_waypoints = raw.get("waypoints")
    if raw_waypoints is None:
        raise ValueError(
            f"map {yaml_path}: Nav2 map has no 'waypoints:' key. The "
            "demo extends the Nav2 schema with a top-level "
            "'waypoints:' list (Nav2 map_server ignores unknown keys), "
            "and at least one waypoint is required."
        )
    waypoints = _parse_waypoint_entries(raw_waypoints, static_env, bounds)

    graph = WaypointGraph()
    for wp in waypoints:
        graph.add_waypoint(wp)
    _connect_neighbors(graph, static_env)

    return BuffetMap(
        static_env=static_env,
        graph=graph,
        origin_x=origin_x,
        origin_y=origin_y,
        width_m=static_env.width_m,
        height_m=static_env.height_m,
        name=name_value,
        defaults=defaults,
        rect_obstacles=None,
    )


# ---------------------------------------------------------------------------
# Public load entry point + format auto-detection
# ---------------------------------------------------------------------------


def load_buffet_map(path: Union[str, Path]) -> BuffetMap:
    """Load a buffet map from YAML, auto-detecting the format.

    * If the YAML has an ``image:`` key, it is treated as a Nav2
      map_server file (PGM + metadata, possibly extended with a
      ``waypoints:`` key).
    * Otherwise, if it has an ``obstacles:`` key, it is treated as the
      demo's rect format.

    Raises ``ValueError`` (or ``FileNotFoundError`` /
    ``yaml.YAMLError``) with a clear message when the input is
    malformed.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"map file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"map file {path}: top level must be a YAML mapping"
        )

    if "image" in raw:
        return _load_nav2_map(raw, path)
    if "obstacles" in raw:
        return _load_rect_map(raw, path)
    raise ValueError(
        f"map file {path}: cannot determine format. Expected either an "
        "'image:' key (Nav2 PGM map) or an 'obstacles:' key (rect map)."
    )


def build_buffet_map() -> BuffetMap:
    """Load the default buffet test map shipped with the demo."""
    return load_buffet_map(DEFAULT_MAP_PATH)
