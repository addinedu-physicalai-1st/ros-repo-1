"""Entry point for the waypoint-based A* global path planner demo.

Examples
--------
Run interactively (default; opens a matplotlib window):

    python3 main.py

Run a few canned scenarios without opening a window:

    python3 main.py --headless
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Tuple

from astar_planner import plan_path, plan_path_from_point
from map_data import (
    BuffetMap,
    DEFAULT_DYNAMIC_RADIUS,
    DynamicObstacle,
    build_buffet_map,
)


_HEADLESS_SCENARIOS: List[Tuple[str, str]] = [
    ("Entrance", "Kitchen"),
    ("Kitchen", "A3-S"),
    ("CS-Left", "Return"),
    ("Entrance", "B2-N"),
    ("Return", "CS-Right"),
]


# Free-start (x, y) -> goal label scenarios. The start is an arbitrary
# point in a corridor, not aligned with any waypoint.
_FREE_START_SCENARIOS: List[Tuple[Tuple[float, float], str]] = [
    ((10.4, 0.6), "Kitchen"),
    ((8.5, 6.0), "Return"),
    ((1.7, 11.4), "A3-S"),
    ((17.2, 9.8), "Entrance"),
    # Previously degenerated into a long diagonal entry; should now
    # snap to the nearest corridor waypoint and follow the grid.
    ((19.0, 10.2), "Kitchen"),
]


# Dynamic-obstacle scenarios. Each entry is:
#   (description, start_label, goal_label, [(ox, oy, radius), ...])
# Each scenario is run twice (no obstacles vs with obstacles) so the
# detour can be compared against the baseline cost / path.
_DYNAMIC_SCENARIOS: List[
    Tuple[str, str, str, List[Tuple[float, float, float]]]
] = [
    (
        "R1 parked at junction (7,6) blocks the central north-south "
        "corridor through column x=7",
        "Entrance",
        "Kitchen",
        [(7.0, 6.0, DEFAULT_DYNAMIC_RADIUS)],
    ),
    (
        "R1 stopped on edge (13,1)->(13,6); A* should find an "
        "alternative column",
        "Entrance",
        "Return",
        [(13.0, 3.5, DEFAULT_DYNAMIC_RADIUS)],
    ),
    (
        "Two robots block both shortcuts (7,6) and (13,6); only the "
        "outer columns x=1 and x=18 remain",
        "Entrance",
        "Kitchen",
        [
            (7.0, 6.0, DEFAULT_DYNAMIC_RADIUS),
            (13.0, 6.0, DEFAULT_DYNAMIC_RADIUS),
        ],
    ),
    (
        "R1 sits exactly on the goal Kitchen - planner must report no "
        "path",
        "Entrance",
        "Kitchen",
        [(4.0, 12.0, DEFAULT_DYNAMIC_RADIUS)],
    ),
]


# Free-start dynamic-obstacle scenarios:
#   (description, start_xy, goal_label, [(ox, oy, radius), ...])
_DYNAMIC_FREE_SCENARIOS: List[
    Tuple[str, Tuple[float, float], str, List[Tuple[float, float, float]]]
] = [
    (
        "Free start (11.0, 0.5) -> Kitchen with R1 sitting on the "
        "preferred entry waypoint (10,1); A* must pick a different "
        "in-radius entry",
        (11.0, 0.5),
        "Kitchen",
        [(10.0, 1.0, DEFAULT_DYNAMIC_RADIUS)],
    ),
    (
        "Free start (19.0, 10.2) -> Kitchen with R1 blocking the entry "
        "waypoint (18,12)",
        (19.0, 10.2),
        "Kitchen",
        [(18.0, 12.0, DEFAULT_DYNAMIC_RADIUS)],
    ),
]


def _print_scenario(
    buffet_map: BuffetMap, start_label: str, goal_label: str
) -> None:
    graph = buffet_map.graph
    start = graph.find_by_label(start_label)
    goal = graph.find_by_label(goal_label)
    path, cost = plan_path(graph, start, goal)
    print(f"\n[scenario] {start_label} -> {goal_label}")
    if path is None:
        print("  no path found")
        return
    print(f"  cost = {cost:.2f} m, {len(path)} waypoints")
    pretty = []
    for wp_id in path:
        wp = graph.waypoints[wp_id]
        pretty.append(wp.label or f"({wp.x},{wp.y})")
    print("  path: " + " -> ".join(pretty))


def _print_free_scenario(
    buffet_map: BuffetMap,
    start_xy: Tuple[float, float],
    goal_label: str,
) -> None:
    graph = buffet_map.graph
    goal = graph.find_by_label(goal_label)
    plan = plan_path_from_point(
        graph, start_xy, goal, buffet_map.obstacles
    )
    sx, sy = start_xy
    print(f"\n[free-start] ({sx:.2f}, {sy:.2f}) -> {goal_label}")
    if plan is None:
        print("  no path found (start unreachable or inside obstacle)")
        return
    entry_wp = graph.waypoints[plan.entry_wp_id]
    entry_label = entry_wp.label or f"({entry_wp.x},{entry_wp.y})"
    fallback_note = (
        "  [radius fallback]" if plan.entry_radius_fallback else ""
    )
    print(
        f"  entry waypoint = {entry_label} "
        f"(distance {plan.entry_distance:.2f} m, "
        f"radius {plan.entry_radius:.1f} m){fallback_note}"
    )
    print(
        f"  total cost = {plan.total_cost:.2f} m "
        f"({len(plan.waypoints)} waypoints)"
    )
    pretty = [f"({sx:.2f},{sy:.2f})"]
    for wp_id in plan.waypoints:
        wp = graph.waypoints[wp_id]
        pretty.append(wp.label or f"({wp.x},{wp.y})")
    print("  path: " + " -> ".join(pretty))


def _build_dyn_obstacles(
    raw: List[Tuple[float, float, float]],
) -> List[DynamicObstacle]:
    return [
        DynamicObstacle(obs_id=i + 1, x=x, y=y, radius=r, label=f"R{i + 1}")
        for i, (x, y, r) in enumerate(raw)
    ]


def _format_path(buffet_map: BuffetMap, path: List[int]) -> str:
    pretty = []
    for wp_id in path:
        wp = buffet_map.graph.waypoints[wp_id]
        pretty.append(wp.label or f"({wp.x},{wp.y})")
    return " -> ".join(pretty)


def _print_dynamic_scenario(
    buffet_map: BuffetMap,
    description: str,
    start_label: str,
    goal_label: str,
    raw_obstacles: List[Tuple[float, float, float]],
) -> None:
    graph = buffet_map.graph
    start = graph.find_by_label(start_label)
    goal = graph.find_by_label(goal_label)
    dyn = _build_dyn_obstacles(raw_obstacles)

    print(f"\n[dyn] {start_label} -> {goal_label}")
    print(f"  scenario: {description}")
    obs_desc = ", ".join(
        f"{d.label}@({d.x:g},{d.y:g}) r={d.radius:g}" for d in dyn
    )
    print(f"  obstacles: {obs_desc}")

    base_path, base_cost = plan_path(graph, start, goal)
    if base_path is None:
        print("  baseline (no dyn): no path found")
    else:
        print(
            f"  baseline (no dyn): cost={base_cost:.2f} m, "
            f"{len(base_path)} wps"
        )
        print(f"    path: {_format_path(buffet_map, base_path)}")

    blocked_path, blocked_cost = plan_path(
        graph, start, goal, dynamic_obstacles=dyn
    )
    if blocked_path is None:
        print("  with dyn:          NO PATH FOUND")
        return
    print(
        f"  with dyn:          cost={blocked_cost:.2f} m, "
        f"{len(blocked_path)} wps"
    )
    print(f"    path: {_format_path(buffet_map, blocked_path)}")
    detour = blocked_cost - (base_cost if base_path is not None else 0.0)
    if base_path is not None:
        print(f"    detour: +{detour:.2f} m vs baseline")


def _print_dynamic_free_scenario(
    buffet_map: BuffetMap,
    description: str,
    start_xy: Tuple[float, float],
    goal_label: str,
    raw_obstacles: List[Tuple[float, float, float]],
) -> None:
    graph = buffet_map.graph
    goal = graph.find_by_label(goal_label)
    dyn = _build_dyn_obstacles(raw_obstacles)
    sx, sy = start_xy

    print(f"\n[dyn-free] ({sx:.2f}, {sy:.2f}) -> {goal_label}")
    print(f"  scenario: {description}")
    obs_desc = ", ".join(
        f"{d.label}@({d.x:g},{d.y:g}) r={d.radius:g}" for d in dyn
    )
    print(f"  obstacles: {obs_desc}")

    base = plan_path_from_point(
        graph, start_xy, goal, buffet_map.obstacles
    )
    if base is None:
        print("  baseline (no dyn): no path")
    else:
        base_entry = (
            graph.waypoints[base.entry_wp_id].label
            or f"({graph.waypoints[base.entry_wp_id].x},"
            f"{graph.waypoints[base.entry_wp_id].y})"
        )
        print(
            f"  baseline (no dyn): entry={base_entry} "
            f"({base.entry_distance:.2f} m), total={base.total_cost:.2f} m"
        )

    plan = plan_path_from_point(
        graph,
        start_xy,
        goal,
        buffet_map.obstacles,
        dynamic_obstacles=dyn,
    )
    if plan is None:
        print("  with dyn:          NO PATH FOUND")
        return
    new_entry_wp = graph.waypoints[plan.entry_wp_id]
    new_entry = new_entry_wp.label or f"({new_entry_wp.x},{new_entry_wp.y})"
    print(
        f"  with dyn:          entry={new_entry} "
        f"({plan.entry_distance:.2f} m), total={plan.total_cost:.2f} m"
    )
    print(f"    path: ({sx:.2f},{sy:.2f}) -> "
          f"{_format_path(buffet_map, plan.waypoints)}")


def _run_headless(buffet_map: BuffetMap) -> None:
    print("Running headless A* scenarios on the buffet test map.")
    print("\n--- Waypoint -> Waypoint ---")
    for start_label, goal_label in _HEADLESS_SCENARIOS:
        _print_scenario(buffet_map, start_label, goal_label)
    print("\n--- Free start point -> Waypoint ---")
    for start_xy, goal_label in _FREE_START_SCENARIOS:
        _print_free_scenario(buffet_map, start_xy, goal_label)
    print("\n--- Dynamic obstacles (waypoint -> waypoint) ---")
    for desc, sl, gl, obs in _DYNAMIC_SCENARIOS:
        _print_dynamic_scenario(buffet_map, desc, sl, gl, obs)
    print("\n--- Dynamic obstacles (free start) ---")
    for desc, sxy, gl, obs in _DYNAMIC_FREE_SCENARIOS:
        _print_dynamic_free_scenario(buffet_map, desc, sxy, gl, obs)


def _run_interactive(buffet_map: BuffetMap) -> None:
    try:
        from visualizer import PathPlanningVisualizer
    except ImportError as exc:
        print(
            f"Failed to import the visualizer ({exc}). "
            "Install matplotlib (e.g. `sudo apt install python3-matplotlib`) "
            "or rerun with --headless.",
            file=sys.stderr,
        )
        sys.exit(1)

    viz = PathPlanningVisualizer(buffet_map)
    viz.show()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Waypoint-based A* global path planner demo."
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run a few canned scenarios without opening a window",
    )
    args = parser.parse_args()

    buffet_map = build_buffet_map()
    edge_count = sum(
        len(v) for v in buffet_map.graph.adjacency.values()
    ) // 2
    print(
        f"Loaded buffet test map: "
        f"{len(buffet_map.graph.waypoints)} waypoints, "
        f"{edge_count} edges, "
        f"{len(buffet_map.obstacles)} obstacles."
    )

    if args.headless:
        _run_headless(buffet_map)
    else:
        _run_interactive(buffet_map)


if __name__ == "__main__":
    main()
