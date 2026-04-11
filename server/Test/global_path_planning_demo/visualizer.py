"""Interactive matplotlib visualization for the path planning demo.

Usage:
    * Click anywhere on the map to set the START waypoint (the click is
      snapped to the nearest waypoint).
    * Click again to set the GOAL waypoint; A* runs immediately and the
      planned path is drawn.
    * Click a third time to start a new query.
    * Press ``r`` to reset the current selection, ``q`` to quit.
"""

from __future__ import annotations

import math
from typing import List, Optional

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.backend_bases import KeyEvent, MouseEvent

from astar_planner import plan_path
from map_data import MAP_HEIGHT, MAP_WIDTH, BuffetMap


class PathPlanningVisualizer:
    """Click two waypoints on the buffet map to plan an A* path."""

    def __init__(self, buffet_map: BuffetMap) -> None:
        self.buffet_map = buffet_map
        self.graph = buffet_map.graph

        self.start_id: Optional[int] = None
        self.goal_id: Optional[int] = None
        self.path: Optional[List[int]] = None
        self.path_cost: float = 0.0

        self.fig, self.ax = plt.subplots(figsize=(11, 8.5))
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        self._redraw()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        self.ax.clear()
        self.ax.set_xlim(-0.5, MAP_WIDTH - 0.5)
        self.ax.set_ylim(-0.5, MAP_HEIGHT - 0.5)
        self.ax.set_aspect("equal")
        self.ax.set_xlabel("x [m]")
        self.ax.set_ylabel("y [m]")
        self.ax.grid(True, linestyle=":", alpha=0.4)

        self._draw_walls()
        self._draw_obstacles()
        self._draw_edges()
        self._draw_waypoints()
        self._draw_selection()
        self._draw_path()
        self._draw_title()

        self.fig.canvas.draw_idle()

    def _draw_walls(self) -> None:
        wall = mpatches.Rectangle(
            (-0.5, -0.5),
            MAP_WIDTH,
            MAP_HEIGHT,
            facecolor="none",
            edgecolor="black",
            linewidth=2.0,
        )
        self.ax.add_patch(wall)

    def _draw_obstacles(self) -> None:
        for obs in self.buffet_map.obstacles:
            rect = mpatches.Rectangle(
                (obs.x_min - 0.5, obs.y_min - 0.5),
                obs.width,
                obs.height,
                facecolor="#b0b0b0",
                edgecolor="#404040",
                linewidth=1.0,
                alpha=0.85,
            )
            self.ax.add_patch(rect)
            cx = (obs.x_min + obs.x_max) / 2.0
            cy = (obs.y_min + obs.y_max) / 2.0
            self.ax.text(
                cx,
                cy,
                obs.name,
                ha="center",
                va="center",
                fontsize=8,
                color="#202020",
            )

    def _draw_edges(self) -> None:
        seen = set()
        for wp_id, neighbors in self.graph.adjacency.items():
            for nb in neighbors:
                key = (min(wp_id, nb), max(wp_id, nb))
                if key in seen:
                    continue
                seen.add(key)
                a = self.graph.waypoints[wp_id]
                b = self.graph.waypoints[nb]
                self.ax.plot(
                    [a.x, b.x],
                    [a.y, b.y],
                    color="#7aa6c2",
                    linewidth=1.4,
                    alpha=0.7,
                    zorder=1,
                )

    def _draw_waypoints(self) -> None:
        for wp in self.graph.waypoints.values():
            self.ax.plot(
                wp.x,
                wp.y,
                marker="o",
                markersize=8,
                color="#1f77b4",
                markeredgecolor="white",
                zorder=3,
            )
            if wp.label:
                self.ax.text(
                    wp.x + 0.25,
                    wp.y + 0.25,
                    wp.label,
                    fontsize=7,
                    color="#102030",
                    zorder=4,
                )

    def _draw_selection(self) -> None:
        if self.start_id is not None:
            wp = self.graph.waypoints[self.start_id]
            self.ax.plot(
                wp.x,
                wp.y,
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

    def _draw_path(self) -> None:
        if not self.path:
            return
        xs = [self.graph.waypoints[i].x for i in self.path]
        ys = [self.graph.waypoints[i].y for i in self.path]
        self.ax.plot(
            xs,
            ys,
            color="#ff7f0e",
            linewidth=4.0,
            alpha=0.9,
            zorder=2,
        )

    def _draw_title(self) -> None:
        if self.start_id is None:
            status = "Click on the map to choose the START waypoint"
        elif self.goal_id is None:
            status = "Click on the map to choose the GOAL waypoint"
        elif self.path is None:
            status = "No path found between selected waypoints"
        else:
            status = (
                f"Path found: {len(self.path)} waypoints, "
                f"cost = {self.path_cost:.2f} m"
            )
        self.ax.set_title(
            "Waypoint-based A* Global Path Planner - Buffet Demo\n"
            f"{status}\n"
            "[r] reset    [q] quit",
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
        nearest = self._nearest_waypoint(event.xdata, event.ydata)
        if nearest is None:
            return

        if self.start_id is None or (
            self.start_id is not None and self.goal_id is not None
        ):
            self._reset_selection()
            self.start_id = nearest
            print(f"[demo] start = {self._describe(nearest)}")
        elif self.goal_id is None:
            if nearest == self.start_id:
                print("[demo] start and goal are identical, ignored")
                return
            self.goal_id = nearest
            print(f"[demo] goal  = {self._describe(nearest)}")
            self._plan()

        self._redraw()

    def _on_key(self, event: KeyEvent) -> None:
        if event.key == "r":
            self._reset_selection()
            self._redraw()
        elif event.key == "q":
            plt.close(self.fig)

    def _reset_selection(self) -> None:
        self.start_id = None
        self.goal_id = None
        self.path = None
        self.path_cost = 0.0

    def _plan(self) -> None:
        assert self.start_id is not None and self.goal_id is not None
        path, cost = plan_path(self.graph, self.start_id, self.goal_id)
        self.path = path
        self.path_cost = cost
        if path is None:
            print("[demo] no path found")
        else:
            labels = [self._describe(i) for i in path]
            print(
                f"[demo] path ({len(path)} wps, {cost:.2f} m): "
                + " -> ".join(labels)
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
