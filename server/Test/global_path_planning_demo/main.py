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

from astar_planner import plan_path
from map_data import BuffetMap, build_buffet_map


_HEADLESS_SCENARIOS: List[Tuple[str, str]] = [
    ("Entrance", "Kitchen"),
    ("Kitchen", "A3-S"),
    ("CS-Left", "Return"),
    ("Entrance", "B2-N"),
    ("Return", "CS-Right"),
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


def _run_headless(buffet_map: BuffetMap) -> None:
    print("Running headless A* scenarios on the buffet test map.")
    for start_label, goal_label in _HEADLESS_SCENARIOS:
        _print_scenario(buffet_map, start_label, goal_label)


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
