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
from map_data import BuffetMap, build_buffet_map


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


def _run_headless(buffet_map: BuffetMap) -> None:
    print("Running headless A* scenarios on the buffet test map.")
    print("\n--- Waypoint -> Waypoint ---")
    for start_label, goal_label in _HEADLESS_SCENARIOS:
        _print_scenario(buffet_map, start_label, goal_label)
    print("\n--- Free start point -> Waypoint ---")
    for start_xy, goal_label in _FREE_START_SCENARIOS:
        _print_free_scenario(buffet_map, start_xy, goal_label)


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
