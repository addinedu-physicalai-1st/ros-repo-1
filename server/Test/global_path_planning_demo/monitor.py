#!/usr/bin/env python3
"""Long-running visualization for the planner-Nav2 bridge.

Subscribes to:
  - /tf (map → base_footprint) for live robot position
  - /demo/planned_path (nav_msgs/Path) for the current planner output
  - /demo/status (std_msgs/String) for status text

This runs continuously in its own matplotlib window.  Each
``nav2_bridge.py`` invocation publishes its planned path / status to
the corresponding topics and the monitor updates without opening a
new window.

Usage::

    python3 monitor.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path as _Path
from typing import List, Optional, Tuple

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

import rclpy
from rclpy.node import Node
from rclpy.duration import Duration
from rclpy.parameter import Parameter
from rclpy.qos import (
    QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy,
)

from nav_msgs.msg import Path as NavPath
from std_msgs.msg import String

from tf2_ros import Buffer, TransformListener

# Local planner import.
DEMO_DIR = _Path(__file__).parent
sys.path.insert(0, str(DEMO_DIR))

from map_data import (  # noqa: E402
    DEFAULT_MAP_PATH, BuffetMap, load_buffet_map,
)


REFRESH_HZ = 10.0


class Monitor(Node):
    def __init__(self, buffet_map: BuffetMap) -> None:
        super().__init__("planner_monitor")
        self.set_parameters([Parameter("use_sim_time", value=True)])
        self.bm = buffet_map
        self.graph = buffet_map.graph

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # Latched QoS so that a path published before the monitor
        # subscribed is still received.
        latched_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            NavPath, "/demo/planned_path", self._on_path, latched_qos,
        )
        self.create_subscription(
            String, "/demo/status", self._on_status, latched_qos,
        )

        self.robot_xy: Optional[Tuple[float, float]] = None
        self.robot_yaw: float = 0.0
        self.trail: List[Tuple[float, float]] = []
        self.path_pts: List[Tuple[float, float]] = []
        self.status: str = "waiting for bridge..."

        self._build_figure()

        # Refresh timer.
        self.create_timer(1.0 / REFRESH_HZ, self._tick)
        self.get_logger().info("Monitor running. Waiting for bridge.")

    # ----- ROS callbacks -----

    def _on_path(self, msg: NavPath) -> None:
        self.path_pts = [
            (p.pose.position.x, p.pose.position.y) for p in msg.poses
        ]
        if not msg.poses:
            # Empty path = arrived; clear trail next time robot moves.
            self.trail.clear()

    def _on_status(self, msg: String) -> None:
        self.status = msg.data

    # ----- per-tick update -----

    def _tick(self) -> None:
        # Update robot pose from TF.
        try:
            t = self.tf_buffer.lookup_transform(
                "map", "base_footprint", rclpy.time.Time(),
                timeout=Duration(seconds=0.1),
            )
            x = t.transform.translation.x
            y = t.transform.translation.y
            q = t.transform.rotation
            yaw = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            self.robot_xy = (x, y)
            self.robot_yaw = yaw
            self.trail.append((x, y))
        except Exception:
            pass

        self._update_artists()

    # ----- drawing -----

    def _build_figure(self) -> None:
        bm = self.bm
        plt.ion()
        fig_w = 10.0
        fig_h = fig_w * (bm.height_m / max(bm.width_m, 1.0))
        fig_h = max(5.0, min(fig_h + 1.5, 12.0))
        self.fig, self.ax = plt.subplots(figsize=(fig_w, fig_h))

        ax = self.ax
        ax.set_xlim(bm.origin_x, bm.origin_x + bm.width_m)
        ax.set_ylim(bm.origin_y, bm.origin_y + bm.height_m)
        ax.set_aspect("equal")
        ax.set_xlabel("x [m]")
        ax.set_ylabel("y [m]")
        ax.grid(True, linestyle=":", alpha=0.4)

        bm.static_env.draw_on(ax)
        wall = mpatches.Rectangle(
            (bm.origin_x, bm.origin_y), bm.width_m, bm.height_m,
            facecolor="none", edgecolor="black", linewidth=2,
        )
        ax.add_patch(wall)

        seen = set()
        for wp_id, nbs in self.graph.adjacency.items():
            for nb in nbs:
                key = (min(wp_id, nb), max(wp_id, nb))
                if key in seen:
                    continue
                seen.add(key)
                a = self.graph.waypoints[wp_id]
                b = self.graph.waypoints[nb]
                ax.plot([a.x, b.x], [a.y, b.y],
                        color="#7aa6c2", lw=1.4, alpha=0.6, zorder=1)

        lbl_off = max(0.03, min(0.25, bm.width_m * 0.02))
        for wp in self.graph.waypoints.values():
            ax.plot(wp.x, wp.y, "o", ms=6, color="#1f77b4",
                    mec="white", alpha=0.5, zorder=3)
            if wp.label:
                ax.text(wp.x + lbl_off, wp.y + lbl_off, wp.label,
                        fontsize=6, color="#555", zorder=4)

        # Dynamic artists.
        self._robot_dot, = ax.plot([], [], "s", ms=14, color="#2ca02c",
                                   mec="black", mew=2, zorder=10)
        self._robot_label = ax.text(
            0, 0, "", ha="center", va="bottom", fontsize=8,
            fontweight="bold", color="#2ca02c", zorder=11,
        )
        self._robot_arrow = None
        self._trail_line, = ax.plot([], [], color="#2ca02c", lw=2,
                                    alpha=0.3, zorder=2)
        self._path_line, = ax.plot([], [], color="#ff7f0e", lw=3,
                                   alpha=0.6, zorder=2)
        self._title = ax.set_title("", fontsize=10)

        self.fig.canvas.draw()
        plt.pause(0.01)

    def _update_artists(self) -> None:
        # Robot.
        if self.robot_xy:
            rx, ry = self.robot_xy
            self._robot_dot.set_data([rx], [ry])
            self._robot_label.set_position((rx, ry + 0.08))
            self._robot_label.set_text("Robot")
            if self._robot_arrow:
                self._robot_arrow.remove()
            dx = math.cos(self.robot_yaw) * 0.1
            dy = math.sin(self.robot_yaw) * 0.1
            self._robot_arrow = self.ax.annotate(
                "", xy=(rx + dx, ry + dy), xytext=(rx, ry),
                arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=2),
                zorder=11,
            )
        # Trail.
        if len(self.trail) > 1:
            self._trail_line.set_data(
                [p[0] for p in self.trail],
                [p[1] for p in self.trail],
            )
        # Path.
        if self.path_pts:
            self._path_line.set_data(
                [p[0] for p in self.path_pts],
                [p[1] for p in self.path_pts],
            )
        else:
            self._path_line.set_data([], [])
        # Title.
        self._title.set_text(
            f"Nav2 Bridge Monitor \u2014 {self.bm.name}\n{self.status}"
        )

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()


def main() -> None:
    buffet_map = load_buffet_map(DEFAULT_MAP_PATH)
    rclpy.init()
    node = Monitor(buffet_map)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
