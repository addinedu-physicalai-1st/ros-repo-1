"""A* search over the buffet waypoint graph.

The graph is built so every edge is axis-aligned (horizontal or vertical),
which means the Manhattan-distance heuristic is admissible: it never
overestimates the true (Euclidean == Manhattan) cost of remaining edges.

Two entry points are provided:

* :func:`plan_path`            - waypoint id -> waypoint id (single source)
* :func:`plan_path_from_point` - free (x, y) start -> waypoint id (the
  start point is connected to every line-of-sight reachable waypoint and
  A* picks the best entry).
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from map_data import (
    DynamicObstacle,
    Obstacle,
    WaypointGraph,
    circle_contains_point,
    circle_intersects_segment,
    is_inside_any_obstacle,
    is_line_clear,
)


# Maximum allowed straight-line distance from a free start point to its
# entry waypoint (in metres). The cap forces the global path to enter the
# corridor network through a nearby waypoint instead of running long
# diagonals across open space, which keeps the resulting motion close to
# the project's "straight + 90-degree turns" constraint.
DEFAULT_ENTRY_RADIUS: float = 2.5


def _euclidean(graph: WaypointGraph, a: int, b: int) -> float:
    wa = graph.waypoints[a]
    wb = graph.waypoints[b]
    return math.hypot(wa.x - wb.x, wa.y - wb.y)


def _manhattan(graph: WaypointGraph, a: int, b: int) -> float:
    wa = graph.waypoints[a]
    wb = graph.waypoints[b]
    return abs(wa.x - wb.x) + abs(wa.y - wb.y)


@dataclass
class _Blockage:
    """Set of waypoint ids and edges blocked by dynamic obstacles."""

    waypoints: Set[int] = field(default_factory=set)
    edges: Set[FrozenSet[int]] = field(default_factory=set)


def _compute_blockage(
    graph: WaypointGraph,
    dynamic_obstacles: Optional[Iterable[DynamicObstacle]],
) -> _Blockage:
    """Pre-compute waypoints and edges that any dynamic obstacle blocks."""
    blockage = _Blockage()
    if not dynamic_obstacles:
        return blockage
    obs_list = list(dynamic_obstacles)
    if not obs_list:
        return blockage

    for wp in graph.waypoints.values():
        for d in obs_list:
            if circle_contains_point(d.x, d.y, d.radius, wp.x, wp.y):
                blockage.waypoints.add(wp.wp_id)
                break

    seen: Set[FrozenSet[int]] = set()
    for wp_id, neighbors in graph.adjacency.items():
        a = graph.waypoints[wp_id]
        for nb in neighbors:
            key = frozenset((wp_id, nb))
            if key in seen:
                continue
            seen.add(key)
            if wp_id in blockage.waypoints or nb in blockage.waypoints:
                blockage.edges.add(key)
                continue
            b = graph.waypoints[nb]
            for d in obs_list:
                if circle_intersects_segment(
                    d.x, d.y, d.radius, a.x, a.y, b.x, b.y
                ):
                    blockage.edges.add(key)
                    break

    return blockage


def _astar_multi_source(
    graph: WaypointGraph,
    seeds: Dict[int, float],
    goal: int,
    blockage: Optional[_Blockage] = None,
) -> Tuple[Optional[List[int]], float]:
    """Run A* with one or more seeded start nodes.

    ``seeds`` maps a waypoint id to its initial g-score (the cost paid to
    reach that node from outside the graph). The returned path always
    starts at whichever seeded node A* found cheapest, and the returned
    cost includes the seed cost.

    ``blockage`` (optional) lists waypoint ids and edges that are
    blocked by dynamic obstacles and must be skipped.
    """
    if goal not in graph.waypoints:
        raise KeyError("Unknown goal waypoint id passed to A*")
    if not seeds:
        return None, math.inf

    blocked_wp: Set[int] = blockage.waypoints if blockage else set()
    blocked_edges: Set[FrozenSet[int]] = (
        blockage.edges if blockage else set()
    )

    if goal in blocked_wp:
        return None, math.inf

    counter = 0
    open_heap: List[Tuple[float, int, int]] = []
    came_from: Dict[int, int] = {}
    g_score: Dict[int, float] = {}

    for wp_id, init in seeds.items():
        if wp_id not in graph.waypoints:
            raise KeyError(f"Unknown seed waypoint id {wp_id}")
        if wp_id in blocked_wp:
            continue
        if init < g_score.get(wp_id, math.inf):
            g_score[wp_id] = init
            f = init + _manhattan(graph, wp_id, goal)
            heapq.heappush(open_heap, (f, counter, wp_id))
            counter += 1

    if not g_score:
        return None, math.inf

    closed: Set[int] = set()
    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            return _reconstruct(came_from, current), g_score[current]
        closed.add(current)

        for neighbor in graph.neighbors(current):
            if neighbor in closed:
                continue
            if neighbor in blocked_wp:
                continue
            if frozenset((current, neighbor)) in blocked_edges:
                continue
            tentative_g = g_score[current] + _euclidean(
                graph, current, neighbor
            )
            if tentative_g < g_score.get(neighbor, math.inf):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + _manhattan(graph, neighbor, goal)
                counter += 1
                heapq.heappush(open_heap, (f, counter, neighbor))

    return None, math.inf


def plan_path(
    graph: WaypointGraph,
    start: int,
    goal: int,
    *,
    dynamic_obstacles: Optional[Iterable[DynamicObstacle]] = None,
) -> Tuple[Optional[List[int]], float]:
    """Compute the shortest waypoint sequence from ``start`` to ``goal``.

    Returns ``(path, cost)``. ``path`` is the list of waypoint ids that
    starts with ``start`` and ends with ``goal``. If no path exists,
    returns ``(None, math.inf)``.

    ``dynamic_obstacles`` (optional) is a list of circular obstacles
    that block waypoints/edges they touch. The static graph is not
    modified - the planner just skips the affected nodes for this call.
    """
    if start not in graph.waypoints:
        raise KeyError(f"Unknown start waypoint id {start}")
    if start == goal:
        return [start], 0.0
    blockage = _compute_blockage(graph, dynamic_obstacles)
    if start in blockage.waypoints:
        return None, math.inf
    return _astar_multi_source(graph, {start: 0.0}, goal, blockage)


@dataclass
class FreeStartPlan:
    """Result of planning from an arbitrary start point.

    ``waypoints`` is the waypoint id sequence from the chosen entry node
    to the goal. ``entry_distance`` is the straight-line distance from
    the user-provided ``start_xy`` to ``waypoints[0]``. ``waypoint_cost``
    is the cost of the waypoint chain itself. ``entry_radius`` is the
    radius that was used to filter entry candidates, and
    ``entry_radius_fallback`` is True if no waypoint was reachable inside
    that radius and the planner had to relax the constraint and fall
    back to the single nearest reachable waypoint.
    """

    start_xy: Tuple[float, float]
    waypoints: List[int]
    entry_distance: float
    waypoint_cost: float
    entry_radius: float
    entry_radius_fallback: bool = False

    @property
    def entry_wp_id(self) -> int:
        return self.waypoints[0]

    @property
    def total_cost(self) -> float:
        return self.entry_distance + self.waypoint_cost


def plan_path_from_point(
    graph: WaypointGraph,
    start_xy: Tuple[float, float],
    goal: int,
    obstacles: Iterable[Obstacle],
    entry_radius: float = DEFAULT_ENTRY_RADIUS,
    *,
    dynamic_obstacles: Optional[Iterable[DynamicObstacle]] = None,
) -> Optional[FreeStartPlan]:
    """Plan a path from a continuous (x, y) start point to ``goal``.

    The start point is connected only to line-of-sight reachable
    waypoints whose straight-line distance is at most ``entry_radius``,
    so the entry segment stays short and the bulk of the trip happens on
    the corridor graph (straight + 90-degree turns). Among the
    candidates inside the radius, A* picks the one that minimises the
    total path length, not just the geometrically nearest one.

    If no waypoint is reachable inside ``entry_radius`` (e.g. the user
    clicked far from the corridor network), the planner falls back to
    the single nearest line-of-sight reachable waypoint and sets
    :attr:`FreeStartPlan.entry_radius_fallback` to ``True`` so the
    caller can warn about the relaxed constraint.

    ``dynamic_obstacles`` (optional) is a list of circular obstacles
    that block waypoints/edges they touch and that the entry segment
    must also clear. The start point itself must not be inside any
    dynamic obstacle disc.

    Returns ``None`` if the start point is inside an obstacle, has no
    line-of-sight reachable waypoint at all, or no path to the goal
    exists.
    """
    if goal not in graph.waypoints:
        raise KeyError(f"Unknown goal waypoint id {goal}")
    if entry_radius <= 0.0:
        raise ValueError("entry_radius must be positive")

    obstacles = list(obstacles)
    dyn_list: List[DynamicObstacle] = (
        list(dynamic_obstacles) if dynamic_obstacles else []
    )

    sx, sy = start_xy
    if is_inside_any_obstacle(sx, sy, obstacles):
        return None
    for d in dyn_list:
        if circle_contains_point(d.x, d.y, d.radius, sx, sy):
            return None

    blockage = _compute_blockage(graph, dyn_list)
    if goal in blockage.waypoints:
        return None

    seeds: Dict[int, float] = {}
    nearest_id: Optional[int] = None
    nearest_dist: float = math.inf
    for wp in graph.waypoints.values():
        if wp.wp_id in blockage.waypoints:
            continue
        if not is_line_clear(sx, sy, wp.x, wp.y, obstacles):
            continue
        if any(
            circle_intersects_segment(
                d.x, d.y, d.radius, sx, sy, wp.x, wp.y
            )
            for d in dyn_list
        ):
            continue
        d_dist = math.hypot(sx - wp.x, sy - wp.y)
        if d_dist < nearest_dist:
            nearest_dist = d_dist
            nearest_id = wp.wp_id
        if d_dist <= entry_radius:
            seeds[wp.wp_id] = d_dist

    fallback = False
    if not seeds:
        if nearest_id is None:
            return None
        seeds[nearest_id] = nearest_dist
        fallback = True

    path, total_cost = _astar_multi_source(graph, seeds, goal, blockage)
    if path is None:
        return None

    entry_distance = seeds[path[0]]
    return FreeStartPlan(
        start_xy=(sx, sy),
        waypoints=path,
        entry_distance=entry_distance,
        waypoint_cost=total_cost - entry_distance,
        entry_radius=entry_radius,
        entry_radius_fallback=fallback,
    )


def _reconstruct(came_from: Dict[int, int], current: int) -> List[int]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
