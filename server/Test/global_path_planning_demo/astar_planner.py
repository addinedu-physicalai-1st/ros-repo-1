"""A* search over the buffet waypoint graph.

The graph is built so every edge is axis-aligned (horizontal or vertical),
which means the Manhattan-distance heuristic is admissible: it never
overestimates the true (Euclidean == Manhattan) cost of remaining edges.
"""

from __future__ import annotations

import heapq
import math
from typing import Dict, List, Optional, Tuple

from map_data import WaypointGraph


def _euclidean(graph: WaypointGraph, a: int, b: int) -> float:
    wa = graph.waypoints[a]
    wb = graph.waypoints[b]
    return math.hypot(wa.x - wb.x, wa.y - wb.y)


def _manhattan(graph: WaypointGraph, a: int, b: int) -> float:
    wa = graph.waypoints[a]
    wb = graph.waypoints[b]
    return abs(wa.x - wb.x) + abs(wa.y - wb.y)


def plan_path(
    graph: WaypointGraph, start: int, goal: int
) -> Tuple[Optional[List[int]], float]:
    """Compute the shortest waypoint sequence from ``start`` to ``goal``.

    Returns ``(path, cost)``. ``path`` is the list of waypoint ids that
    starts with ``start`` and ends with ``goal``. If no path exists,
    returns ``(None, math.inf)``.
    """
    if start not in graph.waypoints or goal not in graph.waypoints:
        raise KeyError("Unknown waypoint id passed to plan_path()")
    if start == goal:
        return [start], 0.0

    counter = 0  # tiebreaker so heap entries with equal f never compare ids
    open_heap: List[Tuple[float, int, int]] = [(0.0, counter, start)]

    came_from: Dict[int, int] = {}
    g_score: Dict[int, float] = {start: 0.0}
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


def _reconstruct(came_from: Dict[int, int], current: int) -> List[int]:
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
