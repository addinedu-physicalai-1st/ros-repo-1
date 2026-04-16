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
import os
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
    DEFAULT_MAP_PATH, BuffetMap, RobotStartPose, load_buffet_map,
)
from nav2_bridge import plan_to_path  # noqa: E402


REFRESH_HZ = 10.0
_POSE_COLORS = ["#e377c2", "#17becf", "#bcbd22", "#9467bd"]


class Monitor(Node):
    def __init__(self, buffet_map: BuffetMap) -> None:
        super().__init__("planner_monitor")
        # Sim uses Gazebo's /clock; real robot uses wall time.
        use_sim_time = os.environ.get(
            "DEMO_USE_SIM_TIME", "true"
        ).lower() in ("1", "true", "yes", "on")
        self.set_parameters([Parameter("use_sim_time", value=use_sim_time)])
        self.get_logger().info(
            f"use_sim_time={use_sim_time} "
            f"(DEMO_USE_SIM_TIME="
            f"{os.environ.get('DEMO_USE_SIM_TIME', '<unset>')})"
        )
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

        # --- Edit mode state ---
        self.edit_mode: bool = False
        self._dragging_wp: Optional[int] = None
        self._hover_wp: Optional[int] = None
        self._pose_edit_step: int = 0   # 0=idle, 1=placing, 2=yaw drag
        self._pose_edit_idx: int = -1

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
        x, y = float(event.xdata), float(event.ydata)

        # --- Edit mode clicks ---
        if self.edit_mode:
            self._on_click_edit(x, y, event.button)
            return

        if self.nav_busy:
            self.status = "busy — wait for current task to finish"
            return
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

    def _on_click_edit(self, x: float, y: float, button: int) -> None:
        # Pose placement step 1: set position
        if self._pose_edit_step == 1:
            if not self.bm.is_in_bounds(x, y):
                self.get_logger().info(f"({x:.2f}, {y:.2f}) out of bounds")
                return
            if self.bm.static_env.contains_xy(x, y):
                self.get_logger().info(f"({x:.2f}, {y:.2f}) inside obstacle")
                return
            idx = self._pose_edit_idx
            if idx < len(self.bm.robot_start_poses):
                old = self.bm.robot_start_poses[idx]
                self.bm.robot_start_poses[idx] = RobotStartPose(
                    x=x, y=y, yaw=old.yaw)
            else:
                self.bm.robot_start_poses.append(
                    RobotStartPose(x=x, y=y, yaw=0.0))
            self._pose_edit_step = 2
            self.get_logger().info(
                f"Robot{idx+1} at ({x:.3f}, {y:.3f}). "
                "Drag to set yaw, release.")
            self._redraw_full()
            return

        # Left click: grab a waypoint for dragging
        if button == 1:
            nearest = self._nearest_wp(x, y)
            if nearest is not None:
                wp = self.graph.waypoints[nearest]
                dist = math.hypot(wp.x - x, wp.y - y)
                grab_r = max(0.06, self.bm.width_m * 0.03)
                if dist <= grab_r:
                    self._dragging_wp = nearest
                    lbl = wp.label or f"#{nearest}"
                    self.get_logger().info(f"Grabbed {lbl} — drag to move")

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
        self.fig.canvas.mpl_connect("button_release_event", self._on_release)
        self.fig.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)

        self._draw_static()

        # Dynamic artists.
        ax = self.ax
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

    def _draw_static(self) -> None:
        """Draw (or redraw) the static map elements: env, walls, edges,
        waypoints, and robot start poses."""
        bm = self.bm
        ax = self.ax
        ax.clear()
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

        # Robot start poses.
        arrow_len = max(0.08, min(0.8, bm.width_m * 0.05))
        for i, pose in enumerate(bm.robot_start_poses):
            c = _POSE_COLORS[i % len(_POSE_COLORS)]
            ax.plot(pose.x, pose.y, marker="D", ms=12,
                    color=c, mec="black", mew=1.5, zorder=6)
            dx = math.cos(pose.yaw) * arrow_len
            dy = math.sin(pose.yaw) * arrow_len
            ax.annotate("", xy=(pose.x + dx, pose.y + dy),
                        xytext=(pose.x, pose.y),
                        arrowprops=dict(arrowstyle="->", color=c, lw=2),
                        zorder=6.1)
            ax.text(pose.x, pose.y - 0.04, f"Robot{i+1}",
                    ha="center", va="top", fontsize=6,
                    fontweight="bold", color=c, zorder=6.2)

        # Edit mode overlay.
        if self.edit_mode:
            self._draw_edit_overlay()

    # ----- edit mode -----

    def _draw_edit_overlay(self) -> None:
        ax = self.ax
        # Banner
        ax.text(
            0.5, 0.97, "EDIT MODE",
            transform=ax.transAxes,
            ha="center", va="top", fontsize=16, fontweight="bold",
            color="#ff7f0e", alpha=0.8, zorder=100,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#fff3e0",
                      edgecolor="#ff7f0e", alpha=0.85, linewidth=2),
        )
        # Orange rings on all waypoints to indicate draggable
        for wp in self.graph.waypoints.values():
            is_hov = wp.wp_id == self._hover_wp
            ax.plot(wp.x, wp.y, "o",
                    ms=16 if is_hov else 12,
                    mfc="none",
                    mec="#ff7f0e",
                    mew=3.0 if is_hov else 1.5,
                    alpha=1.0 if is_hov else 0.5,
                    zorder=4.5)
        # Dashed rings on robot poses
        for i, pose in enumerate(self.bm.robot_start_poses):
            c = _POSE_COLORS[i % len(_POSE_COLORS)]
            ax.plot(pose.x, pose.y, "D", ms=18,
                    mfc="none", mec=c, mew=1.5, alpha=0.5, zorder=5.9)

    def _redraw_full(self) -> None:
        """Full redraw: static map + edit overlay + recreate dynamic
        artists so the robot/trail/path keep rendering."""
        self._draw_static()
        ax = self.ax
        self._robot_dot, = ax.plot([], [], "s", ms=14, color="#2ca02c",
                                   mec="black", mew=2, zorder=10)
        self._robot_label = ax.text(
            0, 0, "", ha="center", va="bottom", fontsize=8,
            fontweight="bold", color="#2ca02c", zorder=11)
        self._robot_arrow = None
        self._trail_line, = ax.plot([], [], color="#2ca02c", lw=2,
                                    alpha=0.3, zorder=2)
        self._path_line, = ax.plot([], [], color="#ff7f0e", lw=3,
                                   alpha=0.6, zorder=2)
        self._title = ax.set_title("", fontsize=10)
        self.fig.canvas.draw_idle()

    def _toggle_edit_mode(self) -> None:
        self.edit_mode = not self.edit_mode
        if self.edit_mode:
            self._dragging_wp = None
            self._hover_wp = None
            self._pose_edit_step = 0
            self.get_logger().info(
                "EDIT MODE ON — drag waypoints, 'p' add/edit pose, "
                "'d' delete pose, 's' save, 'e' exit edit"
            )
        else:
            self._dragging_wp = None
            self._hover_wp = None
            self._pose_edit_step = 0
            self.bm._rebuild_edges()
            self.get_logger().info("EDIT MODE OFF")
        self._redraw_full()

    def _on_key(self, event) -> None:
        if event.key == "e":
            self._toggle_edit_mode()
            return
        if not self.edit_mode:
            return
        if event.key == "s":
            self._save_map()
        elif event.key == "p":
            self._start_pose_edit()
        elif event.key == "d":
            self._delete_last_pose()
        elif event.key == "escape":
            if self._pose_edit_step > 0:
                self._pose_edit_step = 0
                self.get_logger().info("Pose edit cancelled")
                self._redraw_full()

    def _on_release(self, event) -> None:
        if not self.edit_mode:
            return
        if self._dragging_wp is not None:
            wp_id = self._dragging_wp
            self._dragging_wp = None
            if event.inaxes is self.ax and event.xdata is not None:
                x, y = float(event.xdata), float(event.ydata)
                if (self.bm.is_in_bounds(x, y)
                        and not self.bm.static_env.contains_xy(x, y)):
                    # move_waypoint: position only, no edge rebuild.
                    # Edges are rebuilt on save ('s') or exit edit ('e').
                    self.bm.move_waypoint(wp_id, x, y)
                    wp = self.graph.waypoints[wp_id]
                    lbl = wp.label or f"#{wp_id}"
                    self.get_logger().info(
                        f"Moved {lbl} to ({x:.3f}, {y:.3f})")
            self._redraw_full()
        if self._pose_edit_step == 2:
            if event.inaxes is self.ax and event.xdata is not None:
                x, y = float(event.xdata), float(event.ydata)
                pose = self.bm.robot_start_poses[self._pose_edit_idx]
                yaw = math.atan2(y - pose.y, x - pose.x)
                self.bm.robot_start_poses[self._pose_edit_idx] = (
                    RobotStartPose(x=pose.x, y=pose.y, yaw=yaw))
                self.get_logger().info(
                    f"Robot{self._pose_edit_idx+1} yaw="
                    f"{math.degrees(yaw):.0f}°")
            self._pose_edit_step = 0
            self._redraw_full()

    def _on_motion(self, event) -> None:
        if not self.edit_mode:
            return
        if event.inaxes is not self.ax:
            return
        if event.xdata is None:
            return
        x, y = float(event.xdata), float(event.ydata)
        if self._dragging_wp is not None:
            old = self.graph.waypoints[self._dragging_wp]
            from map_data import Waypoint
            self.graph.waypoints[self._dragging_wp] = Waypoint(
                wp_id=old.wp_id, x=x, y=y, label=old.label, yaw=old.yaw)
            self._redraw_full()
            return
        # Hover detection
        nearest = self._nearest_wp(x, y)
        if nearest is not None:
            wp = self.graph.waypoints[nearest]
            dist = math.hypot(wp.x - x, wp.y - y)
            grab_r = max(0.06, self.bm.width_m * 0.03)
            if dist <= grab_r:
                if self._hover_wp != nearest:
                    self._hover_wp = nearest
                    self._redraw_full()
                return
        if self._hover_wp is not None:
            self._hover_wp = None
            self._redraw_full()

    def _nearest_wp(self, x: float, y: float) -> Optional[int]:
        best_id, best_d = None, math.inf
        for wp in self.graph.waypoints.values():
            d = math.hypot(wp.x - x, wp.y - y)
            if d < best_d:
                best_d = d
                best_id = wp.wp_id
        return best_id

    def _start_pose_edit(self) -> None:
        n = len(self.bm.robot_start_poses)
        self._pose_edit_idx = n
        self._pose_edit_step = 1
        self.get_logger().info(
            f"Click to place Robot{n+1} position (Escape to cancel)")
        self._redraw_full()

    def _delete_last_pose(self) -> None:
        if not self.bm.robot_start_poses:
            self.get_logger().info("No robot poses to delete")
            return
        removed = self.bm.robot_start_poses.pop()
        n = len(self.bm.robot_start_poses)
        self.get_logger().info(
            f"Deleted Robot{n+1} pose ({removed.x:.3f}, {removed.y:.3f})")
        self._redraw_full()

    def _save_map(self) -> None:
        self.bm._rebuild_edges()
        try:
            self.bm.save_to_yaml()
            self.get_logger().info(f"Saved to {self.bm.yaml_path}")
        except RuntimeError as exc:
            self.get_logger().error(f"Save failed: {exc}")

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
        if self.edit_mode:
            if self._pose_edit_step == 1:
                edit_status = (
                    f"EDIT: Click to place Robot{self._pose_edit_idx+1} "
                    "position")
            elif self._pose_edit_step == 2:
                edit_status = (
                    f"EDIT: Drag to set Robot{self._pose_edit_idx+1} "
                    "yaw, release")
            elif self._dragging_wp is not None:
                wp = self.graph.waypoints[self._dragging_wp]
                lbl = wp.label or f"#{self._dragging_wp}"
                edit_status = f"EDIT: Dragging {lbl}"
            else:
                n_wp = len(self.graph.waypoints)
                n_pose = len(self.bm.robot_start_poses)
                edit_status = (
                    f"EDIT MODE | {n_wp} waypoints | "
                    f"{n_pose} robot pose(s)")
            self._title.set_text(
                f"Nav2 Bridge Monitor \u2014 {self.bm.name}\n"
                f"{edit_status}\n"
                "[drag] move wp  [p] add pose  [d] del pose  "
                "[s] save  [e] exit edit")
        else:
            self._title.set_text(
                f"Nav2 Bridge Monitor \u2014 {self.bm.name}\n"
                f"{self.status}\n"
                "[click] navigate  [e] edit mode"
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
