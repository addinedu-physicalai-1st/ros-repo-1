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
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.parameter import Parameter
from rclpy.qos import (
    QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy,
)

from action_msgs.msg import GoalStatus
from nav_msgs.msg import Path as NavPath
from nav2_msgs.action import FollowPath, Spin
from std_msgs.msg import String

from tf2_ros import Buffer, TransformListener

# Local planner import.
DEMO_DIR = _Path(__file__).parent
sys.path.insert(0, str(DEMO_DIR))

from map_data import (  # noqa: E402
    DEFAULT_MAP_PATH, BuffetMap, load_buffet_map,
)
from nav2_bridge import plan_to_path  # noqa: E402


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
        self.status: str = "Click any waypoint to navigate"

        # FollowPath action client for interactive goal dispatch.
        self.nav_client = ActionClient(self, FollowPath, "follow_path")
        # Spin action for clean final rotation (avoids RPP jitter).
        self.spin_client = ActionClient(self, Spin, "spin")
        self.nav_busy = False
        self._pending_goal_yaw: Optional[float] = None

        # Proximity-preempt state (see CLI bridge for rationale).
        self._active_goal_handle = None
        self._goal_xy: Optional[Tuple[float, float]] = None
        self._near_since: Optional[float] = None
        self._preempted = False

        self._build_figure()

        # Refresh timer.
        self.create_timer(1.0 / REFRESH_HZ, self._tick)
        self.get_logger().info(
            "Monitor running. Click a waypoint to send the robot."
        )

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

    # ----- click → navigate -----

    def _on_click(self, event) -> None:
        if event.inaxes is not self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        if self.nav_busy:
            self.status = "busy — wait for current task to finish"
            return
        x, y = float(event.xdata), float(event.ydata)
        # Snap to nearest waypoint.
        best_id, best_d = None, math.inf
        for wp in self.graph.waypoints.values():
            d = math.hypot(wp.x - x, wp.y - y)
            if d < best_d:
                best_d = d
                best_id = wp.wp_id
        if best_id is None:
            return
        wp = self.graph.waypoints[best_id]
        label = wp.label or f"({wp.x:.2f},{wp.y:.2f})"
        self.get_logger().info(
            f"Click -> waypoint #{best_id} {label} "
            f"(click dist {best_d:.2f} m)"
        )
        self._start_navigation(best_id, label)

    def _start_navigation(self, goal_id: int, label: str) -> None:
        if self.robot_xy is None:
            self.status = "no robot pose yet — wait for TF"
            return
        if not self.nav_client.server_is_ready():
            self.status = "Nav2 FollowPath server not available"
            return

        # Plan using goal_id directly (labels may be empty for
        # junction waypoints).
        path_msg, plan = plan_to_path(self.bm, self.robot_xy, goal_id)
        if path_msg is None or plan is None:
            self.status = f"No path to {label}"
            return

        self.path_pts = [
            (p.pose.position.x, p.pose.position.y) for p in path_msg.poses
        ]
        self.trail.clear()
        self.status = f"-> {label}: navigating..."
        self.nav_busy = True
        self._current_goal_label = label
        # Remember declared yaw so we can spin to it after path is done.
        self._pending_goal_yaw = plan.goal_yaw
        # Proximity-preempt target = last pose of the path.
        final = path_msg.poses[-1].pose.position
        self._goal_xy = (final.x, final.y)
        self._near_since = None
        self._preempted = False

        goal_msg = FollowPath.Goal()
        goal_msg.path = path_msg
        goal_msg.controller_id = "FollowPath"
        goal_msg.goal_checker_id = "general_goal_checker"

        send_future = self.nav_client.send_goal_async(goal_msg)
        send_future.add_done_callback(self._goal_accepted_cb)

    def _goal_accepted_cb(self, future) -> None:
        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.status = "Goal rejected"
            self.nav_busy = False
            self._active_goal_handle = None
            self._goal_xy = None
            return
        self._active_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._goal_result_cb)

    def _goal_result_cb(self, future) -> None:
        status = future.result().status
        label = getattr(self, "_current_goal_label", "goal")
        # Clear preempt tracking regardless of outcome.
        self._active_goal_handle = None
        self._goal_xy = None
        self._near_since = None
        succeeded = (
            status == GoalStatus.STATUS_SUCCEEDED or self._preempted
        )
        if not succeeded:
            self.status = f"FAILED at {label} (status {status})"
            self.get_logger().warn(f"Nav ended with status {status}")
            self.path_pts = []
            self.nav_busy = False
            return

        # Path arrived. If goal_yaw was declared, spin in place to it.
        if self._pending_goal_yaw is None:
            self.status = f"arrived at {label}!"
            self.get_logger().info(f"Arrived at {label}")
            self.path_pts = []
            self.nav_busy = False
            return

        # Compute relative yaw rotation needed.
        delta = self._pending_goal_yaw - self.robot_yaw
        # Normalise to [-pi, pi].
        while delta > math.pi:
            delta -= 2 * math.pi
        while delta < -math.pi:
            delta += 2 * math.pi
        self.get_logger().info(
            f"Spinning {math.degrees(delta):+.0f}° to face goal yaw"
        )
        self.status = f"-> {label}: aligning yaw..."
        self.path_pts = []

        if not self.spin_client.server_is_ready():
            self.get_logger().warn("Spin server not ready, skipping rotation")
            self.status = f"arrived at {label} (no spin)!"
            self.nav_busy = False
            return

        spin_goal = Spin.Goal()
        spin_goal.target_yaw = float(delta)
        spin_future = self.spin_client.send_goal_async(spin_goal)
        spin_future.add_done_callback(self._spin_accepted_cb)

    def _spin_accepted_cb(self, future) -> None:
        gh = future.result()
        if gh is None or not gh.accepted:
            self.status = "Spin rejected"
            self.nav_busy = False
            return
        gh.get_result_async().add_done_callback(self._spin_result_cb)

    def _spin_result_cb(self, future) -> None:
        status = future.result().status
        label = getattr(self, "_current_goal_label", "goal")
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.status = f"arrived at {label} (yaw aligned)!"
            self.get_logger().info(f"Yaw alignment complete at {label}")
        else:
            self.status = f"arrived at {label} (spin status {status})"
            self.get_logger().warn(f"Spin status {status}")
        self.nav_busy = False

    # ----- per-tick update -----

    ARRIVAL_RADIUS = 0.10
    ARRIVAL_DWELL = 1.5

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

        self._check_proximity_preempt()
        self._update_artists()

    def _check_proximity_preempt(self) -> None:
        if (
            self._active_goal_handle is None
            or self._goal_xy is None
            or self.robot_xy is None
            or self._preempted
        ):
            return
        dx = self.robot_xy[0] - self._goal_xy[0]
        dy = self.robot_xy[1] - self._goal_xy[1]
        dist = math.hypot(dx, dy)
        now = self.get_clock().now().nanoseconds * 1e-9
        if dist <= self.ARRIVAL_RADIUS:
            if self._near_since is None:
                self._near_since = now
            elif now - self._near_since >= self.ARRIVAL_DWELL:
                self.get_logger().info(
                    f"Within {self.ARRIVAL_RADIUS:.2f} m for "
                    f"{self.ARRIVAL_DWELL:.1f} s — preempting FollowPath."
                )
                self._preempted = True
                self._active_goal_handle.cancel_goal_async()
        else:
            self._near_since = None

    # ----- drawing -----

    def _build_figure(self) -> None:
        bm = self.bm
        plt.ion()
        fig_w = 10.0
        fig_h = fig_w * (bm.height_m / max(bm.width_m, 1.0))
        fig_h = max(5.0, min(fig_h + 1.5, 12.0))
        self.fig, self.ax = plt.subplots(figsize=(fig_w, fig_h))
        self.fig.canvas.mpl_connect("button_press_event", self._on_click)

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
