"""Entry point for the waypoint-based A* global path planner demo.

Examples
--------
Run interactively with the default map (opens a matplotlib window):

    python3 main.py

Run a few canned scenarios without opening a window:

    python3 main.py --headless

Use a custom YAML map file:

    python3 main.py --map maps/my_map.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

from astar_planner import plan_path, plan_path_from_point
from map_data import (
    BuffetMap,
    DEFAULT_DYNAMIC_RADIUS,
    DEFAULT_MAP_PATH,
    DynamicObstacle,
    load_buffet_map,
)


# Headless scenarios cover BOTH the large algorithm-test maps
# (buffet_default / buffet_small) and the realistic-scale map
# (buffet_realistic, ~2 m x 1.6 m). Scenarios whose labels do not
# exist in the currently-loaded map are skipped gracefully so the
# same file works for every --map value.
_HEADLESS_SCENARIOS: List[Tuple[str, str]] = [
    # Large test hall (buffet_default).
    ("Entrance", "Kitchen"),
    ("Kitchen", "A3-S"),
    ("CS-Left", "Return"),
    ("Entrance", "B2-N"),
    ("Return", "CS-Right"),
    # Realistic 2 m x 1.6 m buffet.
    ("Charging", "Kitchen"),
    ("Charging", "Table"),
    ("Kitchen", "Return"),
    ("Table", "Return"),
]


# Free-start (x, y) -> goal label scenarios. The start is an arbitrary
# point in a corridor, not aligned with any waypoint.
_FREE_START_SCENARIOS: List[Tuple[Tuple[float, float], str]] = [
    # Large test hall.
    ((10.4, 0.6), "Kitchen"),
    ((8.5, 6.0), "Return"),
    ((1.7, 11.4), "A3-S"),
    ((17.2, 9.8), "Entrance"),
    # Previously degenerated into a long diagonal entry; should now
    # snap to the nearest corridor waypoint and follow the grid.
    ((19.0, 10.2), "Kitchen"),
    # Realistic 2 m x 1.6 m buffet. Free start in the bottom-right
    # corner, somewhere between the station and the wall.
    ((1.55, 0.40), "Kitchen"),
    ((0.55, 0.40), "Return"),
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
    # Realistic 2 m x 1.6 m buffet scenarios (radii scaled down).
    (
        "Realistic: another pinky-pro (R1) parked at the (0.40, 0.80) "
        "mid-left junction forces A* through the right side",
        "Charging",
        "Kitchen",
        [(0.40, 0.80, 0.25)],
    ),
    (
        "Realistic: R1 sits between Kitchen and Table on the top row, "
        "blocking the direct 0.6 m edge so A* must detour all the way "
        "around the serving station",
        "Kitchen",
        "Table",
        [(1.30, 1.25, 0.25)],
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
    # Realistic 2 m x 1.6 m buffet: free start in the bottom corridor
    # with another pinky-pro (R1) sitting on the Charging waypoint. The
    # start is deliberately outside R1's disc (distance 0.35 m > 0.25 m
    # radius) so the planner is reachable and must pick a different
    # in-radius entry.
    (
        "Realistic: free start (0.75, 0.35) -> Kitchen with R1 on the "
        "Charging waypoint (0.40, 0.35); A* should enter via (1.0, "
        "0.35) instead",
        (0.75, 0.35),
        "Kitchen",
        [(0.40, 0.35, 0.25)],
    ),
]


def _print_scenario(
    buffet_map: BuffetMap, start_label: str, goal_label: str
) -> None:
    graph = buffet_map.graph
    try:
        start = graph.find_by_label(start_label)
        goal = graph.find_by_label(goal_label)
    except KeyError as exc:
        print(
            f"\n[scenario] {start_label} -> {goal_label}: skipped "
            f"({exc})"
        )
        return
    path, cost = plan_path(buffet_map, start, goal)
    print(f"\n[scenario] {start_label} -> {goal_label}")
    if path is None:
        print("  no path found")
        return
    print(f"  cost = {cost:.2f} m, {len(path)} waypoints")
    pretty = []
    for wp_id in path:
        wp = graph.waypoints[wp_id]
        pretty.append(wp.label or f"({wp.x:g},{wp.y:g})")
    print("  path: " + " -> ".join(pretty))


def _print_free_scenario(
    buffet_map: BuffetMap,
    start_xy: Tuple[float, float],
    goal_label: str,
) -> None:
    graph = buffet_map.graph
    sx, sy = start_xy
    try:
        goal = graph.find_by_label(goal_label)
    except KeyError as exc:
        print(
            f"\n[free-start] ({sx:.2f}, {sy:.2f}) -> {goal_label}: "
            f"skipped ({exc})"
        )
        return
    plan = plan_path_from_point(
        buffet_map,
        start_xy,
        goal,
        entry_radius=buffet_map.defaults.entry_radius,
    )
    print(f"\n[free-start] ({sx:.2f}, {sy:.2f}) -> {goal_label}")
    if plan is None:
        print("  no path found (start unreachable or inside obstacle)")
        return
    entry_wp = graph.waypoints[plan.entry_wp_id]
    entry_label = entry_wp.label or f"({entry_wp.x:g},{entry_wp.y:g})"
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
        pretty.append(wp.label or f"({wp.x:g},{wp.y:g})")
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
        pretty.append(wp.label or f"({wp.x:g},{wp.y:g})")
    return " -> ".join(pretty)


def _print_dynamic_scenario(
    buffet_map: BuffetMap,
    description: str,
    start_label: str,
    goal_label: str,
    raw_obstacles: List[Tuple[float, float, float]],
) -> None:
    graph = buffet_map.graph
    try:
        start = graph.find_by_label(start_label)
        goal = graph.find_by_label(goal_label)
    except KeyError as exc:
        print(
            f"\n[dyn] {start_label} -> {goal_label}: skipped ({exc})"
        )
        return
    dyn = _build_dyn_obstacles(raw_obstacles)

    print(f"\n[dyn] {start_label} -> {goal_label}")
    print(f"  scenario: {description}")
    obs_desc = ", ".join(
        f"{d.label}@({d.x:g},{d.y:g}) r={d.radius:g}" for d in dyn
    )
    print(f"  obstacles: {obs_desc}")

    base_path, base_cost = plan_path(buffet_map, start, goal)
    if base_path is None:
        print("  baseline (no dyn): no path found")
    else:
        print(
            f"  baseline (no dyn): cost={base_cost:.2f} m, "
            f"{len(base_path)} wps"
        )
        print(f"    path: {_format_path(buffet_map, base_path)}")

    blocked_path, blocked_cost = plan_path(
        buffet_map, start, goal, dynamic_obstacles=dyn
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
    sx, sy = start_xy
    try:
        goal = graph.find_by_label(goal_label)
    except KeyError as exc:
        print(
            f"\n[dyn-free] ({sx:.2f}, {sy:.2f}) -> {goal_label}: "
            f"skipped ({exc})"
        )
        return
    dyn = _build_dyn_obstacles(raw_obstacles)

    print(f"\n[dyn-free] ({sx:.2f}, {sy:.2f}) -> {goal_label}")
    print(f"  scenario: {description}")
    obs_desc = ", ".join(
        f"{d.label}@({d.x:g},{d.y:g}) r={d.radius:g}" for d in dyn
    )
    print(f"  obstacles: {obs_desc}")

    base = plan_path_from_point(
        buffet_map,
        start_xy,
        goal,
        entry_radius=buffet_map.defaults.entry_radius,
    )
    if base is None:
        print("  baseline (no dyn): no path")
    else:
        base_wp = graph.waypoints[base.entry_wp_id]
        base_entry = base_wp.label or f"({base_wp.x:g},{base_wp.y:g})"
        print(
            f"  baseline (no dyn): entry={base_entry} "
            f"({base.entry_distance:.2f} m), total={base.total_cost:.2f} m"
        )

    plan = plan_path_from_point(
        buffet_map,
        start_xy,
        goal,
        entry_radius=buffet_map.defaults.entry_radius,
        dynamic_obstacles=dyn,
    )
    if plan is None:
        print("  with dyn:          NO PATH FOUND")
        return
    new_entry_wp = graph.waypoints[plan.entry_wp_id]
    new_entry = (
        new_entry_wp.label or f"({new_entry_wp.x:g},{new_entry_wp.y:g})"
    )
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
    parser.add_argument(
        "--map",
        type=Path,
        default=DEFAULT_MAP_PATH,
        metavar="PATH",
        help=(
            "YAML map file to load "
            f"(default: {DEFAULT_MAP_PATH.name})"
        ),
    )
    args = parser.parse_args()

    try:
        buffet_map = load_buffet_map(args.map)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Failed to load map {args.map}: {exc}", file=sys.stderr)
        sys.exit(1)

    edge_count = sum(
        len(v) for v in buffet_map.graph.adjacency.values()
    ) // 2
    name_part = f" '{buffet_map.name}'" if buffet_map.name else ""
    if buffet_map.rect_obstacles is not None:
        env_desc = f"rect ({len(buffet_map.rect_obstacles)} obstacles)"
    else:
        from map_data import OccupancyGridEnv

        env = buffet_map.static_env
        if isinstance(env, OccupancyGridEnv):
            env_desc = (
                f"occupancy grid {env.cols}x{env.rows} px @ "
                f"{env.resolution:g} m/px"
            )
        else:
            env_desc = type(env).__name__
    d = buffet_map.defaults
    print(
        f"Loaded buffet map{name_part} from {args.map}: "
        f"{buffet_map.width_m:g}x{buffet_map.height_m:g} m, "
        f"{env_desc}, "
        f"{len(buffet_map.graph.waypoints)} waypoints, "
        f"{edge_count} edges."
    )
    print(
        f"  defaults: entry_radius={d.entry_radius:g} m, "
        f"dynamic_radius={d.dynamic_radius:g} m, "
        f"inflation_radius={d.inflation_radius:g} m"
    )

    if args.headless:
        _run_headless(buffet_map)
    else:
        _run_interactive(buffet_map)


if __name__ == "__main__":
    main()
