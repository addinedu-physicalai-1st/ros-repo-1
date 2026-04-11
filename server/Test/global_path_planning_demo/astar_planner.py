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
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from map_data import (
    Obstacle,
    WaypointGraph,
    is_inside_any_obstacle,
    is_line_clear,
)


def _euclidean(graph: WaypointGraph, a: int, b: int) -> float:
    wa = graph.waypoints[a]
    wb = graph.waypoints[b]
    return math.hypot(wa.x - wb.x, wa.y - wb.y)


def _manhattan(graph: WaypointGraph, a: int, b: int) -> float:
    wa = graph.waypoints[a]
    wb = graph.waypoints[b]
    return abs(wa.x - wb.x) + abs(wa.y - wb.y)


def _astar_multi_source(
    graph: WaypointGraph,
    seeds: Dict[int, float],
    goal: int,
) -> Tuple[Optional[List[int]], float]:
    """Run A* with one or more seeded start nodes.

    ``seeds`` maps a waypoint id to its initial g-score (the cost paid to
    reach that node from outside the graph). The returned path always
    starts at whichever seeded node A* found cheapest, and the returned
    cost includes the seed cost.
    """
    if goal not in graph.waypoints:
        raise KeyError("Unknown goal waypoint id passed to A*")
    if not seeds:
        return None, math.inf

    counter = 0
    open_heap: List[Tuple[float, int, int]] = []
    came_from: Dict[int, int] = {}
    g_score: Dict[int, float] = {}

    for wp_id, init in seeds.items():
        if wp_id not in graph.waypoints:
            raise KeyError(f"Unknown seed waypoint id {wp_id}")
        if init < g_score.get(wp_id, math.inf):
            g_score[wp_id] = init
            f = init + _manhattan(graph, wp_id, goal)
            heapq.heappush(open_heap, (f, counter, wp_id))
            counter += 1

    closed: set = set()
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
    graph: WaypointGraph, start: int, goal: int
) -> Tuple[Optional[List[int]], float]:
    """Compute the shortest waypoint sequence from ``start`` to ``goal``.

    Returns ``(path, cost)``. ``path`` is the list of waypoint ids that
    starts with ``start`` and ends with ``goal``. If no path exists,
    returns ``(None, math.inf)``.
    """
    if start not in graph.waypoints:
        raise KeyError(f"Unknown start waypoint id {start}")
    if start == goal:
        return [start], 0.0
    return _astar_multi_source(graph, {start: 0.0}, goal)


@dataclass
class FreeStartPlan:
    """Result of planning from an arbitrary start point.

    ``waypoints`` is the waypoint id sequence from the chosen entry node
    to the goal. ``entry_distance`` is the straight-line distance from
    the user-provided ``start_xy`` to ``waypoints[0]``. ``waypoint_cost``
    is the cost of the waypoint chain itself.
    """

    start_xy: Tuple[float, float]
    waypoints: List[int]
    entry_distance: float
    waypoint_cost: float

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
) -> Optional[FreeStartPlan]:
    """Plan a path from a continuous (x, y) start point to ``goal``.

    The start point is connected to every waypoint that is reachable in
    a straight line (no obstacle in between). Each candidate is seeded
    into A* with its straight-line distance as the initial cost, so the
    search picks the entry waypoint that minimises the total path
    length, not just the nearest one.

    Returns ``None`` if the start point is inside an obstacle, has no
    line-of-sight reachable waypoint, or no path to the goal exists.
    """
    if goal not in graph.waypoints:
        raise KeyError(f"Unknown goal waypoint id {goal}")

    obstacles = list(obstacles)
    sx, sy = start_xy
    if is_inside_any_obstacle(sx, sy, obstacles):
        return None

    seeds: Dict[int, float] = {}
    for wp in graph.waypoints.values():
        if not is_line_clear(sx, sy, wp.x, wp.y, obstacles):
            continue
        seeds[wp.wp_id] = math.hypot(sx - wp.x, sy - wp.y)

    if not seeds:
        return None

    path, total_cost = _astar_multi_source(graph, seeds, goal)
    if path is None:
        return None

    entry_distance = seeds[path[0]]
    return FreeStartPlan(
        start_xy=(sx, sy),
        waypoints=path,
        entry_distance=entry_distance,
        waypoint_cost=total_cost - entry_distance,
    )


def _reconstruct(came_from: Dict[int, int], current: int) -> List[int]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
