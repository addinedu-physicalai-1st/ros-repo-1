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


# Headless scenarios target the real-scale maps (buffet_sim and
# buffet_realistic). Labels that do not exist in the currently-loaded
# map are skipped gracefully so the same file works for every
# ``--map`` value.
_HEADLESS_SCENARIOS: List[Tuple[str, str]] = [
    # Shared between buffet_sim and buffet_realistic.
    ("Charging", "Kitchen"),
    ("Kitchen", "Return"),
    ("Charging", "Return"),
    # buffet_sim only (real SLAM map has these extra service points).
    ("Entrance", "Kitchen"),
    ("Entrance", "Table-N"),
    ("Table-S", "Kitchen"),
    # buffet_realistic only (ring map has a Table label).
    ("Charging", "Table"),
    ("Table", "Return"),
]


# Free-start (x, y) -> goal label scenarios. The start is an arbitrary
# point in a corridor, not aligned with any waypoint.
_FREE_START_SCENARIOS: List[Tuple[Tuple[float, float], str]] = [
    # buffet_sim: middle-right area (the earlier U-turn bug case;
    # after dropping the entry-radius cap, A* picks the nearest
    # total-optimal entry instead of the nearest raw entry).
    ((1.27, -0.56), "Charging"),
    # buffet_sim: top of the left column, goal = Return.
    ((0.00, -0.20), "Return"),
    # buffet_realistic: bottom-right area, goal = Kitchen.
    ((1.55, 0.40), "Kitchen"),
    # buffet_realistic: bottom-left area, goal = Return.
    ((0.55, 0.40), "Return"),
]


# Dynamic-obstacle scenarios. Each entry is:
#   (description, start_label, goal_label, [(ox, oy, radius), ...])
# Each scenario is run twice (no obstacles vs with obstacles) so the
# detour can be compared against the baseline cost / path.
_DYNAMIC_SCENARIOS: List[
    Tuple[str, str, str, List[Tuple[float, float, float]]]
] = [
    # buffet_sim: block the middle column bridge so A* must re-route
    # via the top corridor.
    (
        "R1 parked at Table-N (0.84, -0.566) blocks the mid-right "
        "bridge; A* reroutes via the top corridor",
        "Entrance",
        "Kitchen",
        [(0.84, -0.566, DEFAULT_DYNAMIC_RADIUS)],
    ),
    # buffet_sim: block the goal (Kitchen) directly.
    (
        "R1 sits on the goal Kitchen - planner must report no path",
        "Entrance",
        "Kitchen",
        [(1.50, 0.05, DEFAULT_DYNAMIC_RADIUS)],
    ),
    # buffet_realistic: block the mid-left junction so A* must go
    # through the right side.
    (
        "Realistic: R1 parked at the (0.40, 0.80) mid-left junction "
        "forces A* through the right side",
        "Charging",
        "Kitchen",
        [(0.40, 0.80, DEFAULT_DYNAMIC_RADIUS)],
    ),
    # buffet_realistic: big detour when the direct Kitchen<->Table
    # edge is blocked.
    (
        "Realistic: R1 sits between Kitchen and Table on the top row, "
        "blocking the direct 0.6 m edge so A* must detour all the way "
        "around the serving station",
        "Kitchen",
        "Table",
        [(1.30, 1.25, DEFAULT_DYNAMIC_RADIUS)],
    ),
]


# Free-start dynamic-obstacle scenarios:
#   (description, start_xy, goal_label, [(ox, oy, radius), ...])
_DYNAMIC_FREE_SCENARIOS: List[
    Tuple[str, Tuple[float, float], str, List[Tuple[float, float, float]]]
] = [
    # buffet_sim: the user's original U-turn case. Without any dyn
    # obstacles, A* correctly picks Table-N as the entry (multi-source
    # wins). With R1 on Table-N, the entry must fall back to
    # (1.5,-0.566) and the route takes the right side + top corridor.
    (
        "Free start (1.27, -0.56) -> Charging with R1 on Table-N; A* "
        "re-selects entry waypoint and routes via right column",
        (1.27, -0.56),
        "Charging",
        [(0.84, -0.566, DEFAULT_DYNAMIC_RADIUS)],
    ),
    # buffet_realistic: the earlier case that exercises in-radius
    # multi-source optimality.
    (
        "Realistic: free start (0.75, 0.35) -> Kitchen with R1 on the "
        "Charging waypoint (0.40, 0.35)",
        (0.75, 0.35),
        "Kitchen",
        [(0.40, 0.35, DEFAULT_DYNAMIC_RADIUS)],
    ),
]


# Two-robot scenarios using reserved_paths. Each entry is:
#   (description, r1_start, r1_goal, r2_start, r2_goal)
# Robot 1 plans first (no reservation). Robot 2 plans with R1's
# entire path reserved. We then compare R2's baseline (alone) vs
# R2 with reservation, showing how reservation forces detours or
# reports conflicts.
#
# The buffet_sim graph has 12 waypoints, 13 edges, and only 4
# cross-column bridges. In a 2.0 x 1.6 m space two robots can
# rarely find non-overlapping paths. The scenarios below are
# designed to demonstrate:
#   A - true non-conflict (paths on different sides)
#   B - reroute (R1 takes mid bridges, R2 forced to top corridor)
#   C - same-goal conflict (impossible)
#   D - head-on conflict (impossible)
_TWO_ROBOT_SCENARIOS: List[
    Tuple[str, str, str, str, str]
] = [
    # Case A: true non-conflict — R1 left/bottom, R2 right only.
    (
        "Non-conflict: R1 left column (Entrance->Charging), R2 right "
        "column (Kitchen->Return). Completely disjoint corridors",
        "Entrance", "Charging",
        "Kitchen", "Return",
    ),
    # Case B: reroute — R1 takes the mid/low bridges, forcing R2
    # to detour via the top corridor + right column instead.
    (
        "Reroute: R1 uses mid bridges (Table-S->Return), blocking "
        "the usual mid-column shortcut. R2 (Entrance->Kitchen) must "
        "detour via the left column + top corridor",
        "Table-S", "Return",
        "Entrance", "Kitchen",
    ),
    # Case C: same goal — both robots heading to Kitchen.
    (
        "Same goal conflict: both robots want Kitchen. R1 reserves "
        "it first, R2 cannot reach the goal",
        "Entrance", "Kitchen",
        "Return", "Kitchen",
    ),
    # Case D: head-on in middle column.
    (
        "Head-on conflict: R1 Table-S->Table-N (up), R2 "
        "Table-N->Table-S (down). Both endpoints reserved, R2 has "
        "no alternative in this 2-node corridor",
        "Table-S", "Table-N",
        "Table-N", "Table-S",
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
    plan = plan_path_from_point(buffet_map, start_xy, goal)
    print(f"\n[free-start] ({sx:.2f}, {sy:.2f}) -> {goal_label}")
    if plan is None:
        print("  no path found (start unreachable or inside obstacle)")
        return
    entry_wp = graph.waypoints[plan.entry_wp_id]
    entry_label = entry_wp.label or f"({entry_wp.x:g},{entry_wp.y:g})"
    print(
        f"  entry waypoint = {entry_label} "
        f"(distance {plan.entry_distance:.2f} m)"
    )
    print(
        f"  total cost = {plan.total_cost:.2f} m "
        f"({len(plan.waypoints)} waypoints)"
    )
    if plan.goal_yaw is not None:
        import math
        print(
            f"  goal yaw   = {math.degrees(plan.goal_yaw):.0f} deg "
            "(robot must arrive facing this direction)"
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

    base = plan_path_from_point(buffet_map, start_xy, goal)
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


def _print_two_robot_scenario(
    buffet_map: BuffetMap,
    description: str,
    r1_start_label: str,
    r1_goal_label: str,
    r2_start_label: str,
    r2_goal_label: str,
) -> None:
    graph = buffet_map.graph
    try:
        r1_start = graph.find_by_label(r1_start_label)
        r1_goal = graph.find_by_label(r1_goal_label)
        r2_start = graph.find_by_label(r2_start_label)
        r2_goal = graph.find_by_label(r2_goal_label)
    except KeyError as exc:
        print(
            f"\n[2-robot] R1: {r1_start_label}->{r1_goal_label}, "
            f"R2: {r2_start_label}->{r2_goal_label}: skipped ({exc})"
        )
        return

    print(
        f"\n[2-robot] R1: {r1_start_label} -> {r1_goal_label}, "
        f"R2: {r2_start_label} -> {r2_goal_label}"
    )
    print(f"  scenario: {description}")

    # --- R1 plans alone (priority robot) ---
    r1_path, r1_cost = plan_path(buffet_map, r1_start, r1_goal)
    if r1_path is None:
        print("  R1 alone:  NO PATH FOUND")
        print("  (cannot proceed with R2 reservation)")
        return
    print(
        f"  R1 alone:  cost={r1_cost:.2f} m, {len(r1_path)} wps"
    )
    print(f"    path: {_format_path(buffet_map, r1_path)}")

    # --- R2 baseline (alone, no reservation) ---
    r2_base_path, r2_base_cost = plan_path(
        buffet_map, r2_start, r2_goal
    )
    if r2_base_path is None:
        print("  R2 alone:  NO PATH FOUND")
    else:
        print(
            f"  R2 alone:  cost={r2_base_cost:.2f} m, "
            f"{len(r2_base_path)} wps"
        )
        print(f"    path: {_format_path(buffet_map, r2_base_path)}")

    # --- R2 with R1's path reserved ---
    r2_res_path, r2_res_cost = plan_path(
        buffet_map, r2_start, r2_goal, reserved_paths=[r1_path]
    )
    if r2_res_path is None:
        print("  R2 with R1 reserved: NO PATH FOUND (conflict!)")
        # Show which waypoints are shared to explain the conflict.
        if r2_base_path is not None:
            shared = set(r1_path) & set(r2_base_path)
            if shared:
                shared_labels = sorted(
                    _describe_waypoint(buffet_map, wp_id)
                    for wp_id in shared
                )
                print(
                    f"    shared waypoints (cause of conflict): "
                    f"{', '.join(shared_labels)}"
                )
    else:
        print(
            f"  R2 with R1 reserved: cost={r2_res_cost:.2f} m, "
            f"{len(r2_res_path)} wps"
        )
        print(f"    path: {_format_path(buffet_map, r2_res_path)}")
        if r2_base_path is not None:
            detour = r2_res_cost - r2_base_cost
            rerouted = r2_res_path != r2_base_path
            if abs(detour) < 0.005 and not rerouted:
                print("    detour: none (reservation had no effect)")
            elif abs(detour) < 0.005 and rerouted:
                print(
                    "    detour: rerouted (different path, same cost "
                    f"{r2_res_cost:.2f} m)"
                )
            else:
                print(f"    detour: +{detour:.2f} m vs R2 alone")


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
    print("\n--- Two-robot scenarios (reserved paths) ---")
    for desc, r1s, r1g, r2s, r2g in _TWO_ROBOT_SCENARIOS:
        _print_two_robot_scenario(
            buffet_map, desc, r1s, r1g, r2s, r2g
        )


def _describe_waypoint(buffet_map: BuffetMap, wp_id: int) -> str:
    wp = buffet_map.graph.waypoints[wp_id]
    return wp.label or f"({wp.x:g},{wp.y:g})"


def _print_bottleneck_summary(buffet_map: BuffetMap) -> None:
    """Print the cut-vertex / bridge analysis for the loaded map.

    This info is also available via ``BuffetMap.cut_vertices`` and
    ``BuffetMap.bridges`` for downstream HQ Service policy.
    """
    cv = buffet_map.cut_vertices
    br = buffet_map.bridges
    if not cv and not br:
        print(
            "  bottlenecks: none (graph is fully 2-connected; no single "
            "waypoint or edge can disconnect it)"
        )
        return
    print(
        f"  bottlenecks: {len(cv)} cut vertex(s), {len(br)} bridge(s)"
    )
    for cv_id in sorted(cv):
        label = _describe_waypoint(buffet_map, cv_id)
        comps = buffet_map.components_after_removing(cv_id)
        comps_sorted = sorted(comps, key=len)
        # Describe every component EXCEPT the largest remainder.
        isolated_parts = []
        for comp in comps_sorted[:-1]:
            comp_labels = sorted(_describe_waypoint(buffet_map, i) for i in comp)
            if len(comp_labels) <= 3:
                isolated_parts.append("{" + ", ".join(comp_labels) + "}")
            else:
                isolated_parts.append(
                    "{" + ", ".join(comp_labels[:3]) + f", +{len(comp_labels)-3} more" + "}"
                )
        largest = comps_sorted[-1]
        print(
            f"    #{cv_id} {label}: removal isolates "
            f"{' and '.join(isolated_parts)} "
            f"(remaining component has {len(largest)} wps)"
        )
    for bridge in sorted(br, key=sorted):
        ids = sorted(bridge)
        a_lbl = _describe_waypoint(buffet_map, ids[0])
        b_lbl = _describe_waypoint(buffet_map, ids[1])
        print(f"    bridge #{ids[0]}-#{ids[1]}: {a_lbl} <-> {b_lbl}")


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
        f"  defaults: dynamic_radius={d.dynamic_radius:g} m, "
        f"inflation_radius={d.inflation_radius:g} m"
    )
    _print_bottleneck_summary(buffet_map)

    if args.headless:
        _run_headless(buffet_map)
    else:
        _run_interactive(buffet_map)


if __name__ == "__main__":
    main()
