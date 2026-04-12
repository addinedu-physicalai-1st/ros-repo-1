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
    DEFAULT_ENTRY_PENALTY_FACTOR,
    BuffetMap,
    DynamicObstacle,
    StaticEnv,
    WaypointGraph,
    circle_contains_point,
    circle_intersects_segment,
)


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
    reserved_paths: Optional[Iterable[Iterable[int]]] = None,
) -> _Blockage:
    """Pre-compute waypoints and edges that are blocked.

    Blocked sources:

    1. **Dynamic obstacles** - circular discs that physically overlap
       waypoints or edges (existing behaviour).
    2. **Reserved paths** - sequences of waypoint ids that another robot
       has already claimed. Every waypoint *and* every consecutive edge
       in a reserved path is added to the blockage set so the planner
       routes around the other robot's planned trajectory.

    ``reserved_paths`` is designed for 2-robot (or N-robot) scenarios
    where Robot A's plan is computed first, then Robot B plans with A's
    path reserved. The planner itself is unchanged; only the blockage
    input grows.
    """
    blockage = _Blockage()

    # --- dynamic obstacles (disc geometry) ---
    obs_list = list(dynamic_obstacles) if dynamic_obstacles else []
    if obs_list:
        for wp in graph.waypoints.values():
            for d in obs_list:
                if circle_contains_point(d.x, d.y, d.radius, wp.x, wp.y):
                    blockage.waypoints.add(wp.wp_id)
                    break

    # --- reserved paths (waypoint + edge reservation) ---
    if reserved_paths:
        for rpath in reserved_paths:
            ids = list(rpath)
            for wp_id in ids:
                if wp_id in graph.waypoints:
                    blockage.waypoints.add(wp_id)
            for i in range(len(ids) - 1):
                blockage.edges.add(frozenset((ids[i], ids[i + 1])))

    # --- edge blockage from dynamic obstacles ---
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
            if not obs_list:
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
    buffet_map: BuffetMap,
    start: int,
    goal: int,
    *,
    dynamic_obstacles: Optional[Iterable[DynamicObstacle]] = None,
    reserved_paths: Optional[Iterable[Iterable[int]]] = None,
) -> Tuple[Optional[List[int]], float]:
    """Compute the shortest waypoint sequence from ``start`` to ``goal``.

    Returns ``(path, cost)``. ``path`` is the list of waypoint ids that
    starts with ``start`` and ends with ``goal``. If no path exists,
    returns ``(None, math.inf)``.

    ``dynamic_obstacles`` (optional) is a list of circular obstacles
    that block waypoints/edges they touch. The static graph is not
    modified - the planner just skips the affected nodes for this call.

    ``reserved_paths`` (optional) is a list of waypoint-id sequences
    already claimed by other robots. The planner treats every waypoint
    and edge on a reserved path as blocked.
    """
    graph = buffet_map.graph
    if start not in graph.waypoints:
        raise KeyError(f"Unknown start waypoint id {start}")
    if start == goal:
        return [start], 0.0
    blockage = _compute_blockage(graph, dynamic_obstacles, reserved_paths)
    if start in blockage.waypoints:
        return None, math.inf
    return _astar_multi_source(graph, {start: 0.0}, goal, blockage)


@dataclass
class FreeStartPlan:
    """Result of planning from an arbitrary start point.

    ``waypoints`` is the waypoint id sequence from the chosen entry node
    to the goal. ``entry_distance`` is the straight-line distance from
    the user-provided ``start_xy`` to ``waypoints[0]``. ``waypoint_cost``
    is the cost of the waypoint chain itself.

    ``goal_yaw`` is the orientation (radians) the robot should hold
    upon arriving at the goal, if one was declared. Pulled from the
    goal waypoint's ``yaw`` attribute (or an explicit override passed
    to :func:`plan_path_from_point`). ``None`` means no orientation
    constraint.
    """

    start_xy: Tuple[float, float]
    waypoints: List[int]
    entry_distance: float
    waypoint_cost: float
    goal_yaw: Optional[float] = None

    @property
    def entry_wp_id(self) -> int:
        return self.waypoints[0]

    @property
    def total_cost(self) -> float:
        return self.entry_distance + self.waypoint_cost


def plan_path_from_point(
    buffet_map: BuffetMap,
    start_xy: Tuple[float, float],
    goal: int,
    *,
    dynamic_obstacles: Optional[Iterable[DynamicObstacle]] = None,
    reserved_paths: Optional[Iterable[Iterable[int]]] = None,
    goal_yaw: Optional[float] = None,
    entry_penalty_factor: float = DEFAULT_ENTRY_PENALTY_FACTOR,
) -> Optional[FreeStartPlan]:
    """Plan a path from a continuous (x, y) start point to ``goal``.

    The start point is seeded into A* with every line-of-sight
    reachable waypoint (no artificial radius cap). Each candidate's
    straight-line distance is multiplied by ``entry_penalty_factor``
    to get its initial g-score, which softly biases A* toward
    entering the corridor network through nearby waypoints instead of
    taking long diagonals through open space. With the default factor
    of 1.2, a far-away seed only wins if its corridor savings exceed
    20% of the entry-distance difference - enough to suppress marginal
    shortcuts while still allowing meaningful ones.

    ``dynamic_obstacles`` (optional) is a list of circular obstacles
    that block waypoints/edges they touch and that the entry segment
    must also clear. The start point itself must not be inside any
    dynamic obstacle disc.

    ``reserved_paths`` (optional) is a list of waypoint-id sequences
    already claimed by other robots. The planner treats every waypoint
    and edge on a reserved path as blocked, routing around the other
    robot's planned trajectory.

    ``goal_yaw`` (optional) overrides the goal waypoint's declared
    yaw. If both the parameter and the waypoint are ``None``, the
    resulting plan has ``goal_yaw = None`` (no orientation constraint).

    Returns ``None`` if the start point is inside a static obstacle or
    a dynamic obstacle, has no line-of-sight reachable waypoint at
    all, or no path to the goal exists.
    """
    if entry_penalty_factor < 1.0:
        raise ValueError("entry_penalty_factor must be >= 1.0")

    graph = buffet_map.graph
    static_env: StaticEnv = buffet_map.static_env

    if goal not in graph.waypoints:
        raise KeyError(f"Unknown goal waypoint id {goal}")

    dyn_list: List[DynamicObstacle] = (
        list(dynamic_obstacles) if dynamic_obstacles else []
    )

    sx, sy = start_xy
    if static_env.contains_xy(sx, sy):
        return None
    for d in dyn_list:
        if circle_contains_point(d.x, d.y, d.radius, sx, sy):
            return None

    blockage = _compute_blockage(graph, dyn_list, reserved_paths)
    if goal in blockage.waypoints:
        return None

    # Collect every line-of-sight reachable waypoint. ``actual_entry``
    # stores the physical straight-line distance (what we report to
    # the caller); ``penalized_seeds`` multiplies that by the penalty
    # factor and is what A* actually uses as initial g-score.
    actual_entry: Dict[int, float] = {}
    for wp in graph.waypoints.values():
        if wp.wp_id in blockage.waypoints:
            continue
        if not static_env.is_segment_clear(sx, sy, wp.x, wp.y):
            continue
        if any(
            circle_intersects_segment(
                d.x, d.y, d.radius, sx, sy, wp.x, wp.y
            )
            for d in dyn_list
        ):
            continue
        actual_entry[wp.wp_id] = math.hypot(sx - wp.x, sy - wp.y)

    if not actual_entry:
        return None

    penalized_seeds: Dict[int, float] = {
        wp_id: d * entry_penalty_factor
        for wp_id, d in actual_entry.items()
    }

    path, total_cost_penalized = _astar_multi_source(
        graph, penalized_seeds, goal, blockage
    )
    if path is None:
        return None

    # Report actual (un-penalized) distances back to the caller.
    entry_distance = actual_entry[path[0]]
    waypoint_cost = total_cost_penalized - penalized_seeds[path[0]]

    # Resolve the required arrival yaw: explicit override wins over
    # the waypoint's declared yaw. None means "no constraint".
    effective_goal_yaw = (
        goal_yaw if goal_yaw is not None else graph.waypoints[goal].yaw
    )
    return FreeStartPlan(
        start_xy=(sx, sy),
        waypoints=path,
        entry_distance=entry_distance,
        waypoint_cost=waypoint_cost,
        goal_yaw=effective_goal_yaw,
    )


def _reconstruct(came_from: Dict[int, int], current: int) -> List[int]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
