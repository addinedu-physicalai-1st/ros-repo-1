"""Interactive matplotlib visualization for the path planning demo.

Usage:
    * Left click anywhere inside the map (and outside an obstacle) to
      set the START point. The click coordinate is used as-is - it does
      NOT snap to a waypoint.
    * Left click again to set the GOAL waypoint (this click DOES snap
      to the nearest waypoint, since goals in the buffet are
      well-defined service locations). A* runs immediately and the
      planned path is drawn from the free start point to the goal.
    * Left click a third time to start a new query.
    * Right click to drop a DYNAMIC OBSTACLE (e.g. another robot
      blocking the corridor) at that point. The planner re-runs
      automatically and the new path routes around the obstacle.
    * Press ``r`` to reset the start/goal selection, ``c`` to clear all
      dynamic obstacles, ``q`` to quit.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.backend_bases import KeyEvent, MouseEvent

from astar_planner import (
    FreeStartPlan,
    plan_path_from_point,
)
from map_data import (
    BuffetMap,
    DynamicObstacle,
    circle_contains_point,
)


class PathPlanningVisualizer:
    """Interactive demo: free start point + waypoint goal -> A* path."""

    def __init__(
        self,
        buffet_map: BuffetMap,
        dynamic_radius: Optional[float] = None,
    ) -> None:
        self.buffet_map = buffet_map
        self.graph = buffet_map.graph
        # Pick up per-map default from the loaded YAML unless the
        # caller explicitly overrode it.
        self.dynamic_radius = (
            dynamic_radius
            if dynamic_radius is not None
            else buffet_map.defaults.dynamic_radius
        )

        self.start_xy: Optional[Tuple[float, float]] = None
        self.goal_id: Optional[int] = None
        self.plan: Optional[FreeStartPlan] = None
        self.plan_failed: bool = False

        self.dynamic_obstacles: List[DynamicObstacle] = []
        self._next_dyn_id: int = 1

        # Scale figure to the map's aspect ratio so non-default maps
        # render with sensible proportions.
        fig_w = 11.0
        fig_h = fig_w * (buffet_map.height_m / max(buffet_map.width_m, 1.0))
        fig_h = max(5.5, min(fig_h + 1.0, 12.0))  # +1 for title space
        self.fig, self.ax = plt.subplots(figsize=(fig_w, fig_h))
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        self._redraw()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        self.ax.clear()
        bm = self.buffet_map
        self.ax.set_xlim(bm.origin_x, bm.origin_x + bm.width_m)
        self.ax.set_ylim(bm.origin_y, bm.origin_y + bm.height_m)
        self.ax.set_aspect("equal")
        self.ax.set_xlabel("x [m]")
        self.ax.set_ylabel("y [m]")
        self.ax.grid(True, linestyle=":", alpha=0.4)

        self._draw_static_env()
        self._draw_walls()
        self._draw_edges()
        self._draw_waypoints()
        self._draw_dynamic_obstacles()
        self._draw_path()
        self._draw_selection()
        self._draw_title()

        self.fig.canvas.draw_idle()

    def _draw_static_env(self) -> None:
        # Delegate background rendering to the StaticEnv subclass
        # (rectangles for the rect format, imshow for occupancy grids).
        self.buffet_map.static_env.draw_on(self.ax)

    def _draw_walls(self) -> None:
        bm = self.buffet_map
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
        bridges = self.buffet_map.bridges
        seen = set()
        for wp_id, neighbors in self.graph.adjacency.items():
            for nb in neighbors:
                key = (min(wp_id, nb), max(wp_id, nb))
                if key in seen:
                    continue
                seen.add(key)
                a = self.graph.waypoints[wp_id]
                b = self.graph.waypoints[nb]
                is_bridge = frozenset(key) in bridges
                self.ax.plot(
                    [a.x, b.x],
                    [a.y, b.y],
                    color="#c8342a" if is_bridge else "#7aa6c2",
                    linewidth=2.0 if is_bridge else 1.4,
                    linestyle="--" if is_bridge else "-",
                    alpha=0.85 if is_bridge else 0.7,
                    zorder=1,
                )

    def _draw_waypoints(self) -> None:
        cut_vertices = self.buffet_map.cut_vertices
        # Label offset and yaw-arrow length scale with map size so
        # small maps still get a readable annotation and large maps
        # don't over-space labels/arrows.
        lbl_off = max(
            0.03, min(0.25, self.buffet_map.width_m * 0.02)
        )
        yaw_arrow_len = max(
            0.08, min(1.0, self.buffet_map.width_m * 0.05)
        )
        for wp in self.graph.waypoints.values():
            if wp.wp_id in cut_vertices:
                # Red hollow ring behind the waypoint disc, signalling
                # "if a robot parks here, something else gets cut off".
                self.ax.plot(
                    wp.x,
                    wp.y,
                    marker="o",
                    markersize=14,
                    markerfacecolor="none",
                    markeredgecolor="#c8342a",
                    markeredgewidth=1.6,
                    zorder=2.9,
                )
            self.ax.plot(
                wp.x,
                wp.y,
                marker="o",
                markersize=8,
                color="#1f77b4",
                markeredgecolor="white",
                zorder=3,
            )
            # Yaw arrow: small arrow showing the required arrival
            # heading. Only drawn for waypoints that declared a yaw.
            if wp.yaw is not None:
                dx = math.cos(wp.yaw) * yaw_arrow_len
                dy = math.sin(wp.yaw) * yaw_arrow_len
                self.ax.annotate(
                    "",
                    xy=(wp.x + dx, wp.y + dy),
                    xytext=(wp.x, wp.y),
                    arrowprops=dict(
                        arrowstyle="->",
                        color="#1f77b4",
                        lw=1.6,
                    ),
                    zorder=3.5,
                )
            if wp.label:
                self.ax.text(
                    wp.x + lbl_off,
                    wp.y + lbl_off,
                    wp.label,
                    fontsize=7,
                    color="#102030",
                    zorder=4,
                )

    def _draw_dynamic_obstacles(self) -> None:
        for obs in self.dynamic_obstacles:
            disc = mpatches.Circle(
                (obs.x, obs.y),
                obs.radius,
                facecolor="#ff6b6b",
                edgecolor="#8b0000",
                linewidth=1.2,
                alpha=0.75,
                zorder=2.5,
            )
            self.ax.add_patch(disc)
            self.ax.text(
                obs.x,
                obs.y,
                obs.label,
                ha="center",
                va="center",
                fontsize=8,
                color="white",
                fontweight="bold",
                zorder=2.6,
            )

    def _draw_selection(self) -> None:
        if self.start_xy is not None:
            sx, sy = self.start_xy
            self.ax.plot(
                sx,
                sy,
                marker="*",
                markersize=22,
                color="#2ca02c",
                markeredgecolor="black",
                linestyle="none",
                zorder=5,
            )
        if self.goal_id is not None:
            wp = self.graph.waypoints[self.goal_id]
            self.ax.plot(
                wp.x,
                wp.y,
                marker="X",
                markersize=18,
                color="#d62728",
                markeredgecolor="black",
                linestyle="none",
                zorder=5,
            )
            # If a plan has been computed and the goal has a required
            # yaw, draw a prominent red arrow showing the arrival
            # orientation - this is what the local planner must reach.
            goal_yaw = None
            if self.plan is not None and self.plan.goal_yaw is not None:
                goal_yaw = self.plan.goal_yaw
            elif wp.yaw is not None:
                goal_yaw = wp.yaw
            if goal_yaw is not None:
                arrow_len = max(
                    0.15, min(1.5, self.buffet_map.width_m * 0.08)
                )
                dx = math.cos(goal_yaw) * arrow_len
                dy = math.sin(goal_yaw) * arrow_len
                self.ax.annotate(
                    "",
                    xy=(wp.x + dx, wp.y + dy),
                    xytext=(wp.x, wp.y),
                    arrowprops=dict(
                        arrowstyle="->",
                        color="#d62728",
                        lw=2.5,
                    ),
                    zorder=5.1,
                )

    def _draw_path(self) -> None:
        if self.plan is None:
            return
        sx, sy = self.plan.start_xy
        xs = [sx] + [self.graph.waypoints[i].x for i in self.plan.waypoints]
        ys = [sy] + [self.graph.waypoints[i].y for i in self.plan.waypoints]
        self.ax.plot(
            xs,
            ys,
            color="#ff7f0e",
            linewidth=4.0,
            alpha=0.9,
            zorder=2,
        )

    def _draw_title(self) -> None:
        if self.start_xy is None:
            status = "Click anywhere on the map to choose the START point"
        elif self.goal_id is None:
            status = "Click on the map to choose the GOAL waypoint"
        elif self.plan is None:
            status = (
                "No path found "
                "(start may be unreachable from any waypoint)"
            )
        else:
            status = (
                f"Path found: {len(self.plan.waypoints)} waypoints, "
                f"entry={self.plan.entry_distance:.2f} m + "
                f"corridor={self.plan.waypoint_cost:.2f} m, "
                f"total={self.plan.total_cost:.2f} m"
            )
        n_dyn = len(self.dynamic_obstacles)
        dyn_note = (
            f"  |  dynamic obstacles: {n_dyn}" if n_dyn else ""
        )
        n_cv = len(self.buffet_map.cut_vertices)
        n_br = len(self.buffet_map.bridges)
        bottleneck_note = (
            f"  |  bottlenecks: {n_cv} cut-vertex(s), {n_br} bridge(s) (red)"
            if (n_cv or n_br)
            else ""
        )
        map_name = self.buffet_map.name or "Buffet Demo"
        self.ax.set_title(
            f"Waypoint-based A* Global Path Planner - {map_name}"
            f"{dyn_note}{bottleneck_note}\n"
            f"{status}\n"
            "[left] start/goal    [right] add dyn-obs    "
            "[r] reset    [c] clear dyn    [q] quit",
            fontsize=11,
        )

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _on_click(self, event: MouseEvent) -> None:
        if event.inaxes is not self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        x, y = float(event.xdata), float(event.ydata)

        # Right click drops a dynamic obstacle and re-plans.
        if event.button == 3:
            self._add_dynamic_obstacle(x, y)
            return

        # Left click flow: start -> goal -> (next click resets).
        already_complete = (
            self.start_xy is not None and self.goal_id is not None
        )
        if self.start_xy is None or already_complete:
            self._set_start(x, y)
        else:
            self._set_goal(x, y)

        self._redraw()

    def _add_dynamic_obstacle(self, x: float, y: float) -> None:
        if not self.buffet_map.is_in_bounds(x, y):
            print(
                f"[demo] cannot place dynamic obstacle: "
                f"({x:.2f}, {y:.2f}) out of map bounds"
            )
            return
        if self.buffet_map.static_env.contains_xy(x, y):
            print(
                f"[demo] cannot place dynamic obstacle inside a static "
                f"obstacle: ({x:.2f}, {y:.2f})"
            )
            return
        if self.start_xy is not None and circle_contains_point(
            x, y, self.dynamic_radius, *self.start_xy
        ):
            print(
                "[demo] cannot place dynamic obstacle on top of the "
                "current start point"
            )
            return

        obs = DynamicObstacle(
            obs_id=self._next_dyn_id,
            x=x,
            y=y,
            radius=self.dynamic_radius,
            label=f"R{self._next_dyn_id}",
        )
        self._next_dyn_id += 1
        self.dynamic_obstacles.append(obs)
        print(
            f"[demo] added dynamic obstacle {obs.label} at "
            f"({x:.2f}, {y:.2f}) r={obs.radius:.2f} m"
        )
        if self.start_xy is not None and self.goal_id is not None:
            self._plan()
        self._redraw()

    def _clear_dynamic_obstacles(self) -> None:
        if not self.dynamic_obstacles:
            return
        n = len(self.dynamic_obstacles)
        self.dynamic_obstacles.clear()
        self._next_dyn_id = 1
        print(f"[demo] cleared {n} dynamic obstacle(s)")
        if self.start_xy is not None and self.goal_id is not None:
            self._plan()
        self._redraw()

    def _set_start(self, x: float, y: float) -> None:
        self._reset_selection()
        if not self.buffet_map.is_in_bounds(x, y):
            print(f"[demo] start ({x:.2f}, {y:.2f}) is out of map bounds")
            return
        if self.buffet_map.static_env.contains_xy(x, y):
            print(
                f"[demo] start ({x:.2f}, {y:.2f}) is inside an obstacle, "
                "click somewhere in a corridor"
            )
            return
        self.start_xy = (x, y)
        print(f"[demo] start = ({x:.2f}, {y:.2f})  (free point)")

    def _set_goal(self, x: float, y: float) -> None:
        nearest = self._nearest_waypoint(x, y)
        if nearest is None:
            return
        self.goal_id = nearest
        print(f"[demo] goal  = {self._describe(nearest)}  (snapped)")
        self._plan()

    def _on_key(self, event: KeyEvent) -> None:
        if event.key == "r":
            self._reset_selection()
            self._redraw()
        elif event.key == "c":
            self._clear_dynamic_obstacles()
        elif event.key == "q":
            plt.close(self.fig)

    def _reset_selection(self) -> None:
        self.start_xy = None
        self.goal_id = None
        self.plan = None
        self.plan_failed = False

    def _plan(self) -> None:
        assert self.start_xy is not None and self.goal_id is not None
        plan = plan_path_from_point(
            self.buffet_map,
            self.start_xy,
            self.goal_id,
            dynamic_obstacles=self.dynamic_obstacles,
        )
        self.plan = plan
        self.plan_failed = plan is None
        if plan is None:
            print("[demo] no path found")
            return
        labels = [self._describe(i) for i in plan.waypoints]
        sx, sy = plan.start_xy
        print(
            f"[demo] path ({len(plan.waypoints)} wps, "
            f"entry={plan.entry_distance:.2f} m + "
            f"corridor={plan.waypoint_cost:.2f} m = "
            f"{plan.total_cost:.2f} m): "
            f"({sx:.2f},{sy:.2f}) -> " + " -> ".join(labels)
        )

    def _nearest_waypoint(self, x: float, y: float) -> Optional[int]:
        best_id: Optional[int] = None
        best_dist = math.inf
        for wp in self.graph.waypoints.values():
            d = math.hypot(wp.x - x, wp.y - y)
            if d < best_dist:
                best_dist = d
                best_id = wp.wp_id
        return best_id

    def _describe(self, wp_id: int) -> str:
        wp = self.graph.waypoints[wp_id]
        if wp.label:
            return f"#{wp_id}({wp.label})"
        return f"#{wp_id}({wp.x},{wp.y})"

    def show(self) -> None:
        plt.show()
