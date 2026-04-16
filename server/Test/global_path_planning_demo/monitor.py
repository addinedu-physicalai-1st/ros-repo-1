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

Multi-robot mode
~~~~~~~~~~~~~~~~

Launch with ``--domain-ids`` to enable multi-robot support::

    python3 monitor.py --domain-ids 41 42

Press **m** to enter multi-robot click mode.  Click a waypoint for
each robot in turn — after all goals are set, paths are planned
(with ``reserved_paths`` for conflict avoidance) and dispatched
to each robot via per-robot background threads.

Usage::

    python3 monitor.py                        # single robot (legacy)
    python3 monitor.py --domain-ids 41 42     # 2 robots
"""

from __future__ import annotations

import math
import os
import sys
import threading
from pathlib import Path as _Path
from typing import List, Optional, Tuple

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
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
from nav2_bridge import plan_to_path, yaw_to_quaternion, _densify_path  # noqa: E402
from astar_planner import plan_path_from_point  # noqa: E402


REFRESH_HZ = 10.0
_POSE_COLORS = ["#e377c2", "#17becf", "#bcbd22", "#9467bd"]
# Per-robot display colours (up to 4 robots).
_ROBOT_COLORS = ["#2ca02c", "#d62728", "#9467bd", "#17becf"]


# -----------------------------------------------------------------------
# Satellite thread — one per robot in multi-robot mode
# -----------------------------------------------------------------------


class _RobotSatellite(threading.Thread):
    """Background thread for one robot: TF reading + Nav2 FollowPath.

    Each satellite creates its own ``rclpy.Context`` with a dedicated
    ``domain_id`` so multiple robots on different DDS domains can be
    tracked and controlled simultaneously without interfering with the
    monitor's main context.
    """

    ARRIVAL_RADIUS = 0.10
    ARRIVAL_DWELL = 1.5

    WP_PROXIMITY = 0.12  # consider a waypoint visited when this close

    def __init__(self, robot_id: int, domain_id: int,
                 graph=None) -> None:
        super().__init__(daemon=True, name=f"Sat-{robot_id}")
        self.robot_id = robot_id
        self.domain_id = domain_id
        self._graph = graph  # WaypointGraph ref for wp position lookups

        # Shared state (protected by _lock) — read from monitor thread.
        self._lock = threading.Lock()
        self._xy: Optional[Tuple[float, float]] = None
        self._yaw: float = 0.0
        self._trail: List[Tuple[float, float]] = []
        self._path_pts: List[Tuple[float, float]] = []
        self._nav_busy = False
        self._status = f"Robot-{robot_id}: connecting..."

        # Internal navigation state (satellite thread only).
        self._active_gh = None
        self._goal_xy_int: Optional[Tuple[float, float]] = None
        self._near_since: Optional[float] = None
        self._preempted = False
        self._current_label = ""
        self._node_ref: Optional[Node] = None

        # Goal queue: main thread writes, satellite thread reads.
        self._goal_queue: Optional[Tuple[NavPath, str]] = None

        # Waypoint tracking for remaining-path queries.
        self._planned_wps: List[int] = []  # full planned waypoint seq
        self._wp_visit_idx: int = 0        # next unvisited waypoint

        # Waiting state (blocked by another robot's path).
        self._waiting_goal_id: Optional[int] = None
        self._waiting_label: str = ""

        self._stop_event = threading.Event()
        self._ready = threading.Event()

    # --- Thread-safe accessors (called from monitor main thread) ---

    def get_xy(self) -> Optional[Tuple[float, float]]:
        with self._lock:
            return self._xy

    def get_yaw(self) -> float:
        with self._lock:
            return self._yaw

    def get_trail(self) -> List[Tuple[float, float]]:
        with self._lock:
            return list(self._trail)

    def get_path_pts(self) -> List[Tuple[float, float]]:
        with self._lock:
            return list(self._path_pts)

    def is_busy(self) -> bool:
        with self._lock:
            return self._nav_busy

    def is_waiting(self) -> bool:
        with self._lock:
            return self._waiting_goal_id is not None

    def get_waiting_goal(self) -> Optional[Tuple[int, str]]:
        with self._lock:
            if self._waiting_goal_id is not None:
                return (self._waiting_goal_id, self._waiting_label)
            return None

    def set_waiting(self, goal_id: int, label: str) -> None:
        with self._lock:
            self._waiting_goal_id = goal_id
            self._waiting_label = label
            self._status = f"R{self.robot_id}: waiting ({label})"

    def clear_waiting(self) -> None:
        with self._lock:
            self._waiting_goal_id = None
            self._waiting_label = ""

    def get_remaining_waypoints(self) -> List[int]:
        """Return waypoints not yet visited on the current path."""
        with self._lock:
            if self._planned_wps and self._wp_visit_idx < len(self._planned_wps):
                return list(self._planned_wps[self._wp_visit_idx:])
            return []

    def get_status(self) -> str:
        with self._lock:
            return self._status

    def clear_trail(self) -> None:
        with self._lock:
            self._trail.clear()

    def request_goal(self, path_msg: NavPath, label: str,
                     waypoints: Optional[List[int]] = None) -> None:
        """Queue a FollowPath goal (called from monitor thread)."""
        with self._lock:
            self._goal_queue = (path_msg, label)
            self._planned_wps = list(waypoints) if waypoints else []
            self._wp_visit_idx = 0
            self._waiting_goal_id = None
            self._waiting_label = ""

    def stop(self) -> None:
        self._stop_event.set()

    # --- Thread body ---

    def run(self) -> None:
        ctx = Context()
        rclpy.init(context=ctx, domain_id=self.domain_id)

        node = Node(f"monitor_sat_r{self.robot_id}", context=ctx)
        use_sim = os.environ.get(
            "DEMO_USE_SIM_TIME", "true"
        ).lower() in ("1", "true", "yes", "on")
        node.set_parameters([Parameter("use_sim_time", value=use_sim)])
        self._node_ref = node

        # Each satellite gets its own executor so it never conflicts
        # with the main monitor's executor or other satellites.
        executor = SingleThreadedExecutor(context=ctx)
        executor.add_node(node)

        tf_buf = Buffer()
        TransformListener(tf_buf, node)
        nav_client = ActionClient(node, FollowPath, "follow_path")

        with self._lock:
            self._status = f"Robot-{self.robot_id}: ready"
        self._ready.set()

        try:
            while not self._stop_event.is_set():
                try:
                    executor.spin_once(timeout_sec=0.05)
                except Exception:
                    if self._stop_event.is_set():
                        break
                    continue
                self._update_pose(tf_buf)
                self._process_goal_queue(nav_client)
                self._check_proximity()
        except Exception:
            pass
        finally:
            try:
                executor.shutdown()
                node.destroy_node()
                rclpy.shutdown(context=ctx)
            except Exception:
                pass

    def _update_pose(self, tf_buf) -> None:
        try:
            t = tf_buf.lookup_transform(
                "map", "base_footprint", rclpy.time.Time(),
                timeout=Duration(seconds=0.05),
            )
            x = t.transform.translation.x
            y = t.transform.translation.y
            q = t.transform.rotation
            yaw = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            with self._lock:
                self._xy = (x, y)
                self._yaw = yaw
                self._trail.append((x, y))
                # Track waypoint visitation.
                self._update_wp_progress(x, y)
        except Exception:
            pass

    def _update_wp_progress(self, x: float, y: float) -> None:
        """Advance waypoint visit index if robot is near the next wp."""
        if (not self._planned_wps or self._graph is None
                or self._wp_visit_idx >= len(self._planned_wps)):
            return
        wp_id = self._planned_wps[self._wp_visit_idx]
        wp = self._graph.waypoints.get(wp_id)
        if wp is None:
            return
        if math.hypot(x - wp.x, y - wp.y) <= self.WP_PROXIMITY:
            self._wp_visit_idx += 1

    def _process_goal_queue(self, nav_client) -> None:
        with self._lock:
            pending = self._goal_queue
            self._goal_queue = None

        if pending is None or self._active_gh is not None:
            return

        path_msg, label = pending
        self._current_label = label

        with self._lock:
            self._nav_busy = True
            self._status = f"-> {label}: waiting Nav2..."
            self._path_pts = [
                (p.pose.position.x, p.pose.position.y)
                for p in path_msg.poses
            ]
            self._trail.clear()

        if not nav_client.wait_for_server(timeout_sec=10.0):
            with self._lock:
                self._status = f"-> {label}: Nav2 not available"
                self._nav_busy = False
                self._path_pts = []
            return

        goal_msg = FollowPath.Goal()
        goal_msg.path = path_msg
        goal_msg.controller_id = "FollowPath"
        goal_msg.goal_checker_id = "general_goal_checker"

        with self._lock:
            self._status = f"-> {label}: navigating..."

        final = path_msg.poses[-1].pose.position
        self._goal_xy_int = (final.x, final.y)
        self._near_since = None
        self._preempted = False

        future = nav_client.send_goal_async(goal_msg)
        future.add_done_callback(self._on_goal_response)

    def _on_goal_response(self, future) -> None:
        gh = future.result()
        if gh is None or not gh.accepted:
            with self._lock:
                self._status = f"-> {self._current_label}: rejected"
                self._nav_busy = False
                self._path_pts = []
            return
        self._active_gh = gh
        result_future = gh.get_result_async()
        result_future.add_done_callback(self._on_result)

    def _on_result(self, future) -> None:
        status = future.result().status
        label = self._current_label
        self._active_gh = None
        self._goal_xy_int = None

        ok = status == GoalStatus.STATUS_SUCCEEDED or self._preempted
        with self._lock:
            self._status = (
                f"arrived at {label}!" if ok
                else f"FAILED {label} (status {status})"
            )
            self._path_pts = []
            self._nav_busy = False

    def _check_proximity(self) -> None:
        if (
            self._active_gh is None
            or self._goal_xy_int is None
            or self._preempted
            or self._node_ref is None
        ):
            return
        with self._lock:
            xy = self._xy
        if xy is None:
            return

        dist = math.hypot(
            xy[0] - self._goal_xy_int[0],
            xy[1] - self._goal_xy_int[1],
        )
        now = self._node_ref.get_clock().now().nanoseconds * 1e-9
        if dist <= self.ARRIVAL_RADIUS:
            if self._near_since is None:
                self._near_since = now
            elif now - self._near_since >= self.ARRIVAL_DWELL:
                self._preempted = True
                self._active_gh.cancel_goal_async()
        else:
            self._near_since = None


# -----------------------------------------------------------------------
# Monitor node
# -----------------------------------------------------------------------


class Monitor(Node):
    def __init__(
        self,
        buffet_map: BuffetMap,
        domain_ids: Optional[List[int]] = None,
    ) -> None:
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

        # --- Multi-robot mode ---
        self._domain_ids = domain_ids or []
        self._n_robots = len(self._domain_ids)
        self._multi_mode = self._n_robots >= 2
        self._satellites: List[_RobotSatellite] = []

        # Multi-robot click state: collect one goal per robot.
        self._multi_click_goals: List[int] = []  # waypoint IDs
        self._multi_goal_markers = []  # matplotlib artists for click feedback

        if self._n_robots >= 2:
            for i, did in enumerate(self._domain_ids):
                sat = _RobotSatellite(
                    robot_id=i, domain_id=did, graph=self.graph,
                )
                sat.start()
                self._satellites.append(sat)
            self.get_logger().info(
                f"Multi-robot mode: {self._n_robots} satellites "
                f"(domains {self._domain_ids})"
            )

        self._build_figure()

        # Refresh timer.
        self.create_timer(1.0 / REFRESH_HZ, self._tick)

        if self._multi_mode:
            self.get_logger().info(
                "Monitor running (multi-robot). "
                "Click waypoints to set goals for each robot."
            )
        else:
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
        if not self._multi_mode:
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

        # --- Multi-robot mode ---
        if self._multi_mode:
            self._on_click_multi(x, y)
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

    # ----- multi-robot click handling -----

    def _on_click_multi(self, x: float, y: float) -> None:
        """Handle click in multi-robot mode: immediate dispatch."""
        # Find next available (idle, not busy, not waiting) robot.
        target_idx = None
        for i, sat in enumerate(self._satellites):
            if not sat.is_busy() and not sat.is_waiting():
                target_idx = i
                break
        if target_idx is None:
            self.status = "All robots busy or waiting"
            return

        # Snap to nearest waypoint (with max distance check).
        best_id, best_d = None, math.inf
        for wp in self.graph.waypoints.values():
            d = math.hypot(wp.x - x, wp.y - y)
            if d < best_d:
                best_d = d
                best_id = wp.wp_id
        max_snap = max(0.15, self.bm.width_m * 0.08)
        if best_id is None or best_d > max_snap:
            return

        wp = self.graph.waypoints[best_id]
        label = wp.label or f"({wp.x:.2f},{wp.y:.2f})"
        self.get_logger().info(
            f"Robot-{target_idx} goal: #{best_id} {label}"
        )

        self._plan_and_dispatch(target_idx, best_id, label)

    def _plan_and_dispatch(self, robot_idx: int, goal_id: int,
                           label: str) -> None:
        """Plan for one robot, reserving active robots' remaining paths."""
        sat = self._satellites[robot_idx]
        xy = sat.get_xy()
        if xy is None:
            self.status = f"R{robot_idx}: no pose"
            return

        # Gather reserved paths from OTHER robots that are moving.
        reserved: List[List[int]] = []
        for i, other in enumerate(self._satellites):
            if i == robot_idx:
                continue
            remaining = other.get_remaining_waypoints()
            if remaining:
                reserved.append(remaining)

        plan = plan_path_from_point(
            self.bm, xy, goal_id,
            reserved_paths=reserved if reserved else None,
        )

        if plan is None and reserved:
            # Path blocked by moving robot — set waiting, re-plan later.
            sat.set_waiting(goal_id, label)
            self.status = (
                f"R{robot_idx}: waiting for clear path to {label}"
            )
            self.get_logger().info(
                f"Robot-{robot_idx}: blocked to {label}, waiting..."
            )
            return

        if plan is None:
            self.status = f"R{robot_idx}: no path to {label}"
            self.get_logger().error(
                f"Robot-{robot_idx}: no path to {label}"
            )
            return

        # Build nav_msgs/Path.
        from geometry_msgs.msg import PoseStamped
        points = _densify_path(self.graph, plan.waypoints, step=0.05)
        path_msg = NavPath()
        path_msg.header.frame_id = "map"
        for j, (px, py) in enumerate(points):
            ps = PoseStamped()
            ps.header.frame_id = "map"
            ps.pose.position.x = px
            ps.pose.position.y = py
            if j < len(points) - 1:
                nx, ny = points[j + 1]
                yaw = math.atan2(ny - py, nx - px)
            elif j > 0:
                ppx, ppy = points[j - 1]
                yaw = math.atan2(py - ppy, px - ppx)
            else:
                yaw = 0.0
            ps.pose.orientation = yaw_to_quaternion(yaw)
            path_msg.poses.append(ps)

        wp_labels = []
        for wp_id in plan.waypoints:
            w = self.graph.waypoints[wp_id]
            wp_labels.append(w.label or f"({w.x:g},{w.y:g})")
        self.get_logger().info(
            f"Robot-{robot_idx} -> {label}: "
            f"{' -> '.join(wp_labels)} ({plan.total_cost:.2f} m)"
        )

        sat.clear_trail()
        sat.request_goal(path_msg, label, waypoints=plan.waypoints)
        self.status = f"R{robot_idx} -> {label}: navigating"

    # ----- single-robot navigation (unchanged) -----

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
            f"Spinning {math.degrees(delta):+.0f}\u00b0 to face goal yaw"
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
        # Update robot pose from TF (single-robot / legacy).
        if not self._multi_mode:
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

        # Multi-robot: re-plan waiting robots + update status.
        if self._multi_mode and self._satellites:
            self._replan_tick_counter = getattr(
                self, "_replan_tick_counter", 0) + 1

            # Re-plan waiting robots every ~2 seconds (20 ticks at 10Hz).
            if self._replan_tick_counter % 20 == 0:
                for i, sat in enumerate(self._satellites):
                    wg = sat.get_waiting_goal()
                    if wg is not None:
                        goal_id, label = wg
                        self.get_logger().info(
                            f"Robot-{i}: re-planning to {label}..."
                        )
                        self._plan_and_dispatch(i, goal_id, label)

            # Build status line.
            parts = []
            any_active = False
            for i, s in enumerate(self._satellites):
                if s.is_busy():
                    parts.append(f"R{i}: {s.get_status()}")
                    any_active = True
                elif s.is_waiting():
                    wg = s.get_waiting_goal()
                    label = wg[1] if wg else "?"
                    parts.append(f"R{i}: waiting ({label})")
                    any_active = True
                else:
                    st = s.get_status()
                    if "arrived" in st:
                        parts.append(f"R{i}: {st}")
            if parts:
                self.status = " | ".join(parts)
            if not any_active and not parts:
                # Find next idle robot for click prompt.
                next_idle = None
                for i, s in enumerate(self._satellites):
                    if not s.is_busy() and not s.is_waiting():
                        next_idle = i
                        break
                if next_idle is not None:
                    self.status = (
                        f"Click goal for Robot-{next_idle}  "
                        f"({self._n_robots} robots)"
                    )

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
                    f"{self.ARRIVAL_DWELL:.1f} s \u2014 preempting FollowPath."
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

        ax = self.ax

        if self._multi_mode:
            # Per-robot dynamic artists.
            self._multi_dots = []
            self._multi_labels = []
            self._multi_arrows = []
            self._multi_trails = []
            self._multi_paths = []

            for i in range(self._n_robots):
                c = _ROBOT_COLORS[i % len(_ROBOT_COLORS)]
                dot, = ax.plot([], [], "s", ms=14, color=c,
                               mec="black", mew=2, zorder=10)
                lbl = ax.text(0, 0, "", ha="center", va="bottom",
                              fontsize=8, fontweight="bold",
                              color=c, zorder=11)
                trail, = ax.plot([], [], color=c, lw=2,
                                 alpha=0.3, zorder=2)
                path, = ax.plot([], [], color=c, lw=3,
                                alpha=0.6, zorder=2, linestyle="--")
                self._multi_dots.append(dot)
                self._multi_labels.append(lbl)
                self._multi_arrows.append(None)
                self._multi_trails.append(trail)
                self._multi_paths.append(path)
        else:
            # Single-robot dynamic artists (legacy).
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

        if self._multi_mode:
            self._multi_dots = []
            self._multi_labels = []
            self._multi_arrows = []
            self._multi_trails = []
            self._multi_paths = []
            for i in range(self._n_robots):
                c = _ROBOT_COLORS[i % len(_ROBOT_COLORS)]
                dot, = ax.plot([], [], "s", ms=14, color=c,
                               mec="black", mew=2, zorder=10)
                lbl = ax.text(0, 0, "", ha="center", va="bottom",
                              fontsize=8, fontweight="bold",
                              color=c, zorder=11)
                trail, = ax.plot([], [], color=c, lw=2,
                                 alpha=0.3, zorder=2)
                path, = ax.plot([], [], color=c, lw=3,
                                alpha=0.6, zorder=2, linestyle="--")
                self._multi_dots.append(dot)
                self._multi_labels.append(lbl)
                self._multi_arrows.append(None)
                self._multi_trails.append(trail)
                self._multi_paths.append(path)
        else:
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
                "EDIT MODE ON \u2014 drag waypoints, 'p' add/edit pose, "
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
        if event.key == "m" and self._n_robots >= 2:
            # Cancel all waiting robots.
            for sat in self._satellites:
                sat.clear_waiting()
            for mk in self._multi_goal_markers:
                mk.remove()
            self._multi_goal_markers.clear()
            next_idle = None
            for i, s in enumerate(self._satellites):
                if not s.is_busy() and not s.is_waiting():
                    next_idle = i
                    break
            self.status = (
                f"Reset. Click goal for Robot-{next_idle or 0}  "
                f"({self._n_robots} robots)"
            )
            self.get_logger().info("Goal selection reset")
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
                    f"{math.degrees(yaw):.0f}\u00b0")
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
        if self._multi_mode:
            self._update_artists_multi()
        else:
            self._update_artists_single()

        self.fig.canvas.draw_idle()
        self.fig.canvas.flush_events()

    def _update_artists_single(self) -> None:
        """Update single-robot artists (legacy path)."""
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

    def _update_artists_multi(self) -> None:
        """Update per-robot artists from satellite state."""
        for i, sat in enumerate(self._satellites):
            c = _ROBOT_COLORS[i % len(_ROBOT_COLORS)]
            xy = sat.get_xy()

            # Robot dot + label.
            if xy is not None:
                rx, ry = xy
                self._multi_dots[i].set_data([rx], [ry])
                self._multi_labels[i].set_position((rx, ry + 0.08))
                self._multi_labels[i].set_text(f"R{i}")
                # Yaw arrow.
                if self._multi_arrows[i] is not None:
                    self._multi_arrows[i].remove()
                yaw = sat.get_yaw()
                dx = math.cos(yaw) * 0.1
                dy = math.sin(yaw) * 0.1
                self._multi_arrows[i] = self.ax.annotate(
                    "", xy=(rx + dx, ry + dy), xytext=(rx, ry),
                    arrowprops=dict(arrowstyle="->", color=c, lw=2),
                    zorder=11,
                )
            else:
                self._multi_dots[i].set_data([], [])
                self._multi_labels[i].set_text("")

            # Trail.
            trail = sat.get_trail()
            if len(trail) > 1:
                self._multi_trails[i].set_data(
                    [p[0] for p in trail],
                    [p[1] for p in trail],
                )
            else:
                self._multi_trails[i].set_data([], [])

            # Path.
            path_pts = sat.get_path_pts()
            if path_pts:
                self._multi_paths[i].set_data(
                    [p[0] for p in path_pts],
                    [p[1] for p in path_pts],
                )
            else:
                self._multi_paths[i].set_data([], [])

        # Title.
        n_goals = len(self._multi_click_goals)
        if n_goals > 0 and n_goals < self._n_robots:
            click_info = (
                f"Goals set: {n_goals}/{self._n_robots} | "
                f"Click goal for Robot-{n_goals}"
            )
        else:
            click_info = self.status

        self._title.set_text(
            f"Nav2 Bridge Monitor \u2014 {self.bm.name} "
            f"[{self._n_robots} robots]\n"
            f"{click_info}\n"
            "[click] set goal  [m] reset  [e] edit mode"
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Nav2 bridge monitor with optional multi-robot support",
    )
    parser.add_argument(
        "--domain-ids", nargs="+", type=int, default=None,
        metavar="ID",
        help="ROS_DOMAIN_ID per robot for multi-robot mode "
             "(e.g. --domain-ids 41 42)",
    )
    parser.add_argument(
        "--map", type=_Path, default=DEFAULT_MAP_PATH,
        help=f"Planner map YAML (default: {DEFAULT_MAP_PATH.name})",
    )

    argv = sys.argv[1:]
    if "--ros-args" in argv:
        argv = argv[: argv.index("--ros-args")]
    args = parser.parse_args(argv)

    buffet_map = load_buffet_map(args.map)
    rclpy.init()
    node = Monitor(buffet_map, domain_ids=args.domain_ids)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, Exception):
        pass
    finally:
        # Stop all satellites.
        for sat in node._satellites:
            sat.stop()
        for sat in node._satellites:
            sat.join(timeout=3.0)
        try:
            node.destroy_node()
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
