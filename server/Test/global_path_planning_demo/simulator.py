"""Two-robot path planning simulation with animated visualization.

Demonstrates the quasi-static re-planning model:
  1. Robot 1 (priority) plans first and starts moving.
  2. Robot 2 plans with R1's remaining path reserved.
     - If R2's route is blocked, it waits.
     - Each time R1 reaches a waypoint (freeing it), R2 re-plans.
     - When R2 finds a clear route, it moves.
  3. Both robots complete their missions.

Usage (via main.py)::

    python3 main.py --sim                # default scenario
    python3 main.py --sim --scenario 2   # scenario 2
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.backend_bases import KeyEvent

from astar_planner import plan_path, plan_path_from_point
from map_data import BuffetMap, DynamicObstacle

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------

ROBOT_SPEED: float = 0.15  # m/s (pinky-pro max ~0.2)
FRAME_MS: int = 50  # millisecond per animation frame
DT: float = FRAME_MS / 1000.0  # seconds per frame


# ---------------------------------------------------------------------------
# Pre-defined scenarios
# ---------------------------------------------------------------------------

# Each scenario is:
#   (description, r1_mission_labels, r2_mission_labels)
# where mission_labels is a list of waypoint labels: [start, goal1, goal2, ...]
# A robot with [A, B, C] goes A→B (leg 1), then B→C (leg 2).
SCENARIOS: List[Tuple[str, List[str], List[str]]] = [
    (
        "Pickup relay: R1 Entrance→Kitchen→Table-S (pickup & serve). "
        "R2 Charging→Kitchen (next pickup). R2 waits until R1 "
        "leaves Kitchen, then proceeds.",
        ["Entrance", "Kitchen", "Table-S"],
        ["Charging", "Kitchen"],
    ),
    (
        "Non-conflict: R1 left column (Entrance→Charging), "
        "R2 right column (Kitchen→Return). Both move "
        "simultaneously without interference.",
        ["Entrance", "Charging"],
        ["Kitchen", "Return"],
    ),
    (
        "Cross traffic: R1 Entrance→Kitchen→Return (full trip). "
        "R2 Table-S→Charging (go charge). R2 waits for R1 to "
        "clear the junction, then takes the freed corridor.",
        ["Entrance", "Kitchen", "Return"],
        ["Table-S", "Charging"],
    ),
]


# ---------------------------------------------------------------------------
# Robot state
# ---------------------------------------------------------------------------


@dataclass
class SimRobot:
    """State of one robot in the simulation."""

    robot_id: str
    color: str
    mission: List[int]  # [start_wp, goal1, goal2, ...] multi-leg
    position: Tuple[float, float] = (0.0, 0.0)
    current_leg: int = 0  # index into mission (0 = at start, 1 = heading to goal1, ...)
    path: Optional[List[int]] = None
    path_index: int = 0  # index of NEXT waypoint to reach in current path
    status: str = "planning"  # planning | moving | waiting | done
    trail: List[Tuple[float, float]] = field(default_factory=list)
    wait_reason: str = ""

    @property
    def current_goal(self) -> Optional[int]:
        if self.current_leg < len(self.mission) - 1:
            return self.mission[self.current_leg + 1]
        return None

    @property
    def mission_done(self) -> bool:
        return self.current_leg >= len(self.mission) - 1

    def remaining_path(self) -> List[int]:
        """Waypoints this robot still intends to visit."""
        if self.path is None or self.status == "done":
            return []
        if self.path_index >= len(self.path):
            return []
        return list(self.path[self.path_index :])


# ---------------------------------------------------------------------------
# Simulator core
# ---------------------------------------------------------------------------


class TwoRobotSimulator:
    """Runs the step-by-step two-robot simulation."""

    def __init__(
        self,
        buffet_map: BuffetMap,
        r1_start: Union[Tuple[float, float], List[Union[str, int]]],
        r1_goal: Union[int, None] = None,
        r2_start: Union[Tuple[float, float], List[Union[str, int]], None] = None,
        r2_goal: Union[int, None] = None,
    ) -> None:
        """Create a two-robot simulator.

        Two calling conventions:

        1. **Interactive** (free start + waypoint goal)::

               TwoRobotSimulator(m, (x1,y1), goal1, (x2,y2), goal2)

        2. **Scenario** (label/id list for multi-leg missions)::

               TwoRobotSimulator(m, ["Entrance","Kitchen"], ["Charging","Return"])
        """
        self.bm = buffet_map
        self.graph = buffet_map.graph

        # Normalise the two calling conventions.
        if isinstance(r1_start, list):
            # Scenario mode: r1_start is mission list, r1_goal is r2 mission
            r1_mission = r1_start
            r2_mission = r1_goal  # type: ignore[assignment]
            r1_ids = [
                self.graph.find_by_label(m) if isinstance(m, str) else m
                for m in r1_mission
            ]
            r2_ids = [
                self.graph.find_by_label(m) if isinstance(m, str) else m
                for m in r2_mission
            ]
            r1_pos = self._wp_pos(r1_ids[0])
            r2_pos = self._wp_pos(r2_ids[0])
        else:
            # Interactive mode: free-start (x,y) + waypoint goal
            assert r2_start is not None and r1_goal is not None and r2_goal is not None
            r1_near = self._nearest_wp(r1_start)
            r2_near = self._nearest_wp(r2_start)
            r1_ids = [r1_near, r1_goal]
            r2_ids = [r2_near, r2_goal]
            r1_pos = r1_start
            r2_pos = r2_start

        self.r1 = SimRobot("R1", "#1f77b4", r1_ids, r1_pos)
        self.r2 = SimRobot("R2", "#2ca02c", r2_ids, r2_pos)

        self.sim_time: float = 0.0
        self.frame_count: int = 0
        self.events: List[str] = []

        r1_labels = [self._wp_label(i) for i in r1_ids]
        r2_labels = [self._wp_label(i) for i in r2_ids]
        self._log(f"R1 mission: {' → '.join(r1_labels)}")
        self._log(f"R2 mission: {' → '.join(r2_labels)}")

        # Initial planning.
        self._plan_robot(self.r1, self.r2)
        self._plan_robot(self.r2, self.r1)

    def _wp_pos(self, wp_id: int) -> Tuple[float, float]:
        wp = self.graph.waypoints[wp_id]
        return (wp.x, wp.y)

    # ----- planning -----

    def _plan_robot(self, robot: SimRobot, other: SimRobot) -> None:
        """Plan the current leg for *robot*, avoiding *other*."""
        goal = robot.current_goal
        if goal is None:
            robot.status = "done"
            return

        current_wp = self._nearest_wp(robot.position)

        # Other robot as dynamic obstacle (unless done).
        dyn_obs: List[DynamicObstacle] = []
        if other.status != "done":
            dyn_obs = [
                DynamicObstacle(
                    2 if other.robot_id == "R2" else 1,
                    other.position[0], other.position[1],
                    0.12, other.robot_id,
                )
            ]

        # Reserve the other robot's remaining path, excluding our
        # current waypoint (we're already there).
        other_remaining = other.remaining_path()
        reserved = [wp for wp in other_remaining if wp != current_wp]

        # Use plan_path_from_point so robots can start from free
        # (x, y) positions — not just on waypoints.
        plan = plan_path_from_point(
            self.bm, robot.position, goal,
            dynamic_obstacles=dyn_obs,
            reserved_paths=[reserved] if reserved else None,
        )
        if plan is not None:
            robot.path = plan.waypoints
            robot.path_index = 0
            robot.status = "moving"
            robot.wait_reason = ""
            goal_label = self._wp_label(goal)
            self._log(
                f"{robot.robot_id} leg {robot.current_leg + 1} "
                f"→ {goal_label} ({plan.total_cost:.2f} m): "
                f"{self._path_str(plan.waypoints)}"
            )
        else:
            robot.path = None
            robot.status = "waiting"
            robot.wait_reason = f"{other.robot_id} blocks route"

    # ----- step -----

    _REPLAN_INTERVAL: int = 5  # re-plan waiting robots every N frames

    def step(self) -> None:
        if self.done:
            return
        self.frame_count += 1
        self.sim_time += DT

        self._advance(self.r1)
        self._advance(self.r2)

        # Re-plan waiting robots frequently — the other robot's
        # physical position changes every frame, so a blocked path
        # may open up as soon as the obstacle clears the waypoint
        # (not only when it reaches the next one).
        if self.frame_count % self._REPLAN_INTERVAL == 0:
            if self.r2.status == "waiting":
                self._plan_robot(self.r2, self.r1)
            if self.r1.status == "waiting":
                self._plan_robot(self.r1, self.r2)

    def _advance(self, robot: SimRobot) -> bool:
        """Move *robot* for one frame. Returns True if it reached a wp."""
        if robot.status != "moving" or robot.path is None:
            return False
        if robot.path_index >= len(robot.path):
            # Current leg complete — advance to next leg.
            return self._advance_leg(robot)

        target = self.graph.waypoints[robot.path[robot.path_index]]
        cx, cy = robot.position
        dx, dy = target.x - cx, target.y - cy
        dist = math.hypot(dx, dy)
        step_dist = ROBOT_SPEED * DT

        robot.trail.append(robot.position)

        if step_dist >= dist:
            robot.position = (target.x, target.y)
            robot.path_index += 1
            if robot.path_index >= len(robot.path):
                return self._advance_leg(robot)
            return True
        else:
            ratio = step_dist / dist
            robot.position = (cx + dx * ratio, cy + dy * ratio)
            return False

    def _advance_leg(self, robot: SimRobot) -> bool:
        """Advance to the next mission leg, or mark done."""
        robot.current_leg += 1
        goal_label = self._wp_label(robot.mission[robot.current_leg])
        if robot.mission_done:
            robot.status = "done"
            self._log(f"{robot.robot_id} mission complete at {goal_label}!")
            return True
        # Plan next leg.
        self._log(
            f"{robot.robot_id} reached {goal_label}, "
            f"starting leg {robot.current_leg + 1}"
        )
        other = self.r2 if robot is self.r1 else self.r1
        self._plan_robot(robot, other)
        return True

    @property
    def done(self) -> bool:
        return self.r1.status == "done" and self.r2.status == "done"

    # ----- helpers -----

    def _nearest_wp(self, pos: Tuple[float, float]) -> int:
        best_id = -1
        best_d = math.inf
        for wp in self.graph.waypoints.values():
            d = math.hypot(wp.x - pos[0], wp.y - pos[1])
            if d < best_d:
                best_d = d
                best_id = wp.wp_id
        return best_id

    def _wp_label(self, wp_id: int) -> str:
        wp = self.graph.waypoints[wp_id]
        return wp.label or f"({wp.x:.2f},{wp.y:.2f})"

    def _path_str(self, path: List[int]) -> str:
        return " → ".join(self._wp_label(i) for i in path)

    def _log(self, msg: str) -> None:
        entry = f"[t={self.sim_time:.1f}s] {msg}"
        self.events.append(entry)
        print(entry)


# ---------------------------------------------------------------------------
# Animated visualizer
# ---------------------------------------------------------------------------


class SimVisualizer:
    """Matplotlib animation of the two-robot simulation."""

    def __init__(self, sim: TwoRobotSimulator, description: str) -> None:
        self.sim = sim
        self.description = description
        self.paused = False
        self.speed_mult = 1.0

        bm = sim.bm
        fig_w = 11.0
        fig_h = fig_w * (bm.height_m / max(bm.width_m, 1.0))
        fig_h = max(5.5, min(fig_h + 2.0, 13.0))
        self.fig, self.ax = plt.subplots(figsize=(fig_w, fig_h))
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        self._draw()

        self.anim = FuncAnimation(
            self.fig,
            self._tick,
            interval=FRAME_MS,
            blit=False,
            cache_frame_data=False,
        )

    def _tick(self, _frame: int) -> None:
        if self.paused:
            return
        steps = max(1, int(self.speed_mult))
        for _ in range(steps):
            if not self.sim.done:
                self.sim.step()
        self._draw()

    def _on_key(self, event: KeyEvent) -> None:
        if event.key == " ":
            self.paused = not self.paused
            state = "PAUSED" if self.paused else "RUNNING"
            print(f"[sim] {state}")
            if self.paused:
                self._draw()  # redraw to show paused state in title
        elif event.key == "up":
            self.speed_mult = min(self.speed_mult * 2, 16)
            print(f"[sim] speed x{self.speed_mult:.0f}")
        elif event.key == "down":
            self.speed_mult = max(self.speed_mult / 2, 0.5)
            print(f"[sim] speed x{self.speed_mult:.1f}")
        elif event.key == "q":
            plt.close(self.fig)

    # ----- drawing -----

    def _draw(self) -> None:
        ax = self.ax
        ax.clear()
        bm = self.sim.bm

        ax.set_xlim(bm.origin_x, bm.origin_x + bm.width_m)
        ax.set_ylim(bm.origin_y, bm.origin_y + bm.height_m)
        ax.set_aspect("equal")
        ax.set_xlabel("x [m]")
        ax.set_ylabel("y [m]")
        ax.grid(True, linestyle=":", alpha=0.4)

        bm.static_env.draw_on(ax)
        self._draw_walls()
        self._draw_edges()
        self._draw_waypoints()
        self._draw_trails()
        self._draw_planned_paths()
        self._draw_goals()
        self._draw_robots()
        self._draw_title()
        self.fig.canvas.draw_idle()

    def _draw_walls(self) -> None:
        bm = self.sim.bm
        wall = mpatches.Rectangle(
            (bm.origin_x, bm.origin_y),
            bm.width_m,
            bm.height_m,
            facecolor="none",
            edgecolor="black",
            linewidth=2.0,
        )
        self.ax.add_patch(wall)

    def _draw_edges(self) -> None:
        graph = self.sim.graph
        bridges = self.sim.bm.bridges
        seen: set = set()
        for wp_id, neighbors in graph.adjacency.items():
            for nb in neighbors:
                key = (min(wp_id, nb), max(wp_id, nb))
                if key in seen:
                    continue
                seen.add(key)
                a = graph.waypoints[wp_id]
                b = graph.waypoints[nb]
                is_bridge = frozenset(key) in bridges
                self.ax.plot(
                    [a.x, b.x],
                    [a.y, b.y],
                    color="#c8342a" if is_bridge else "#7aa6c2",
                    linewidth=2.0 if is_bridge else 1.4,
                    linestyle="--" if is_bridge else "-",
                    alpha=0.6,
                    zorder=1,
                )

    def _draw_waypoints(self) -> None:
        graph = self.sim.graph
        lbl_off = max(0.03, min(0.25, self.sim.bm.width_m * 0.02))
        for wp in graph.waypoints.values():
            self.ax.plot(
                wp.x, wp.y, marker="o", markersize=6,
                color="#1f77b4", markeredgecolor="white",
                alpha=0.5, zorder=3,
            )
            if wp.label:
                self.ax.text(
                    wp.x + lbl_off, wp.y + lbl_off, wp.label,
                    fontsize=6, color="#555555", zorder=4,
                )

    def _draw_trails(self) -> None:
        for robot in (self.sim.r1, self.sim.r2):
            if len(robot.trail) < 2:
                continue
            xs = [p[0] for p in robot.trail]
            ys = [p[1] for p in robot.trail]
            self.ax.plot(
                xs, ys, color=robot.color, linewidth=3,
                alpha=0.25, zorder=2, solid_capstyle="round",
            )

    def _draw_planned_paths(self) -> None:
        for robot in (self.sim.r1, self.sim.r2):
            if robot.path is None or robot.status in ("done", "waiting"):
                continue
            idx = max(0, robot.path_index - 1)
            remaining = robot.path[idx:]
            if not remaining:
                continue
            graph = self.sim.graph
            xs = [robot.position[0]] + [
                graph.waypoints[i].x for i in remaining
            ]
            ys = [robot.position[1]] + [
                graph.waypoints[i].y for i in remaining
            ]
            ls = "--" if robot.robot_id == "R2" else "-"
            self.ax.plot(
                xs, ys, color=robot.color, linewidth=2.5,
                alpha=0.4, linestyle=ls, zorder=2.5,
            )

    def _draw_goals(self) -> None:
        graph = self.sim.graph
        for robot in (self.sim.r1, self.sim.r2):
            # Draw all remaining mission goals.
            for i in range(robot.current_leg + 1, len(robot.mission)):
                gwp = graph.waypoints[robot.mission[i]]
                # Current goal is brighter, future goals are dimmer.
                is_current = i == robot.current_leg + 1
                self.ax.plot(
                    gwp.x, gwp.y, marker="X",
                    markersize=14 if is_current else 10,
                    color=robot.color, markeredgecolor="black",
                    markeredgewidth=1.5 if is_current else 1.0,
                    alpha=0.7 if is_current else 0.3, zorder=5,
                )

    def _draw_robots(self) -> None:
        for robot in (self.sim.r1, self.sim.r2):
            edge = "black"
            if robot.status == "waiting":
                edge = "#d62728"
            elif robot.status == "done":
                edge = "#FFD700"

            # Robot body (square like pinky-pro).
            self.ax.plot(
                robot.position[0], robot.position[1],
                marker="s", markersize=14,
                color=robot.color, markeredgecolor=edge,
                markeredgewidth=2.5, zorder=10,
            )
            # Label above.
            self.ax.text(
                robot.position[0], robot.position[1] + 0.07,
                robot.robot_id,
                ha="center", va="bottom", fontsize=9,
                fontweight="bold", color=robot.color, zorder=11,
            )
            # Status indicator below.
            status_text = {
                "moving": "",
                "waiting": "WAIT",
                "done": "DONE",
                "planning": "...",
            }.get(robot.status, "")
            if status_text:
                self.ax.text(
                    robot.position[0], robot.position[1] - 0.07,
                    status_text,
                    ha="center", va="top", fontsize=7,
                    fontweight="bold",
                    color="#d62728" if robot.status == "waiting" else "#555",
                    zorder=11,
                )

    def _draw_title(self) -> None:
        r1s = self._status_str(self.sim.r1)
        r2s = self._status_str(self.sim.r2)
        pause_tag = "  [PAUSED]" if self.paused else ""
        speed_tag = (
            f"  (x{self.speed_mult:.0f})"
            if self.speed_mult != 1.0
            else ""
        )
        self.ax.set_title(
            f"2-Robot Simulation  |  t = {self.sim.sim_time:.1f}s"
            f"{pause_tag}{speed_tag}\n"
            f"R1: {r1s}  |  R2: {r2s}\n"
            "[space] pause/resume    "
            "[\u2191\u2193] speed    "
            "[q] quit",
            fontsize=10,
        )

    def _status_str(self, robot: SimRobot) -> str:
        if robot.status == "done":
            final = self.sim._wp_label(robot.mission[-1])
            return f"mission complete at {final}"
        goal = robot.current_goal
        goal_label = self.sim._wp_label(goal) if goal else "?"
        leg = f"leg {robot.current_leg + 1}/{len(robot.mission) - 1}"
        if robot.status == "waiting":
            return f"waiting ({robot.wait_reason}) [{leg}]"
        if robot.status == "moving":
            return f"-> {goal_label} [{leg}]"
        return robot.status

    def show(self) -> None:
        plt.show()


# ---------------------------------------------------------------------------
# Entry point (called from main.py)
# ---------------------------------------------------------------------------


def run_simulation(
    buffet_map: BuffetMap,
    scenario_index: int = 0,
) -> None:
    """Launch the two-robot simulation with the given scenario."""
    if scenario_index < 0 or scenario_index >= len(SCENARIOS):
        print(
            f"Invalid scenario index {scenario_index}. "
            f"Valid range: 0..{len(SCENARIOS) - 1}"
        )
        print("Available scenarios:")
        for i, (desc, *_) in enumerate(SCENARIOS):
            print(f"  {i + 1}. {desc}")
        return

    desc, r1_labels, r2_labels = SCENARIOS[scenario_index]
    print(f"Scenario {scenario_index + 1}: {desc}")
    print(f"  R1: {' -> '.join(r1_labels)}")
    print(f"  R2: {' -> '.join(r2_labels)}")
    print()

    sim = TwoRobotSimulator(buffet_map, r1_labels, r2_labels)
    viz = SimVisualizer(sim, desc)
    viz.show()
