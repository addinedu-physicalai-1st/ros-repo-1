#!/usr/bin/env python3
"""Bridge between the waypoint-based A* planner and Nav2.

Each invocation handles ONE task (= one goal).  Reads robot pose
from TF (AMCL → map frame), runs the demo planner, sends the
resulting path directly to Nav2's ``FollowPath`` action (RPP).

The bridge does NOT open a visualization window.  Instead it
publishes:
  - /demo/planned_path  (nav_msgs/Path)
  - /demo/status        (std_msgs/String)

Run ``monitor.py`` separately (long-running) to see the live map.

Usage::

    python3 nav2_bridge.py --goal Kitchen
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def _env_use_sim_time() -> bool:
    """Return True iff DEMO_USE_SIM_TIME env var is set to a truthy value.

    Defaults to True (the demo's primary workflow is Gazebo). Set
    ``DEMO_USE_SIM_TIME=false`` when running against a real robot so
    the ROS node uses wall time and TF lookups succeed.
    """
    return os.environ.get("DEMO_USE_SIM_TIME", "true").lower() in (
        "1", "true", "yes", "on",
    )

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.parameter import Parameter
from rclpy.qos import (
    QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy,
)

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Quaternion
from nav_msgs.msg import Path as NavPath
from nav2_msgs.action import FollowPath
from std_msgs.msg import String

from tf2_ros import Buffer, TransformListener

# Library import — pure-Python path planning lives in server/lib/.
DEMO_DIR = Path(__file__).parent
_LIB_DIR = str(DEMO_DIR.resolve().parents[1] / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from path_planning.planner import (  # noqa: E402
    FreeStartPlan,
    plan_path as wp_plan_path,
    plan_path_from_point,
)
from path_planning.map_data import (  # noqa: E402
    BuffetMap,
    load_buffet_map,
)
from path_planning.densify import densify_path as _densify_path  # noqa: E402

# Demo-local default map path.
DEFAULT_MAP_PATH = DEMO_DIR / "maps" / "buffet_sim.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def yaw_to_quaternion(yaw: float) -> Quaternion:
    q = Quaternion()
    q.z = math.sin(yaw / 2.0)
    q.w = math.cos(yaw / 2.0)
    return q


# _densify_path is now imported from path_planning.densify (see top).


def plan_to_path(
    buffet_map: BuffetMap,
    start_xy: Tuple[float, float],
    goal: "int | str",
    frame_id: str = "map",
) -> Tuple[Optional[NavPath], Optional[FreeStartPlan]]:
    """Plan and return (nav_msgs/Path, plan_object).

    ``goal`` may be either a waypoint label (str) or waypoint id (int).
    Final orientation is handled by a separate ``Spin`` action after
    FollowPath succeeds; this function does not set the last pose's
    yaw to ``plan.goal_yaw`` because RPP's in-place final rotation is
    unstable in tight spaces.
    """
    graph = buffet_map.graph
    if isinstance(goal, int):
        goal_id = goal
        if goal_id not in graph.waypoints:
            print(f"[bridge] unknown goal id: {goal_id}")
            return None, None
    else:
        try:
            goal_id = graph.find_by_label(goal)
        except KeyError:
            print(f"[bridge] unknown goal label: {goal!r}")
            return None, None

    # Always plan corridor-only (nearest waypoint -> goal). Nav2's own
    # NavfnPlanner is bypassed entirely (we send to FollowPath
    # directly), so the path here is what the robot literally follows.
    best_wp, best_d = None, math.inf
    for wp in graph.waypoints.values():
        d = math.hypot(wp.x - start_xy[0], wp.y - start_xy[1])
        if d < best_d:
            best_d = d
            best_wp = wp.wp_id

    plan = None
    if best_wp is not None:
        path, cost = wp_plan_path(buffet_map, best_wp, goal_id)
        if path is not None:
            plan = FreeStartPlan(
                start_xy=start_xy, waypoints=path,
                entry_distance=best_d, waypoint_cost=cost,
                goal_yaw=graph.waypoints[goal_id].yaw,
            )
    if plan is None:
        print(f"[bridge] no path to {goal!r}")
        return None, None

    print(
        f"[bridge] planned {len(plan.waypoints)} wps, "
        f"{plan.total_cost:.2f} m"
    )

    points = _densify_path(graph, plan.waypoints, step=0.05)

    path_msg = NavPath()
    path_msg.header.frame_id = frame_id
    poses: List[PoseStamped] = []
    for i, (x, y) in enumerate(points):
        ps = PoseStamped()
        ps.header.frame_id = frame_id
        ps.pose.position.x = x
        ps.pose.position.y = y
        if i < len(points) - 1:
            nx, ny = points[i + 1]
            yaw = math.atan2(ny - y, nx - x)
        elif i > 0:
            px, py = points[i - 1]
            yaw = math.atan2(y - py, x - px)
        else:
            yaw = 0.0
        ps.pose.orientation = yaw_to_quaternion(yaw)
        poses.append(ps)

    path_msg.poses = poses

    labels = []
    for wp_id in plan.waypoints:
        wp = graph.waypoints[wp_id]
        labels.append(wp.label or f"({wp.x:g},{wp.y:g})")
    print(f"[bridge] path: {' -> '.join(labels)} ({len(points)} pts)")

    return path_msg, plan


# ---------------------------------------------------------------------------
# Bridge node
# ---------------------------------------------------------------------------


class PlannerBridge(Node):

    def __init__(self, buffet_map: BuffetMap, goal_label: str) -> None:
        super().__init__("planner_bridge")
        # Clock domain: sim uses Gazebo's /clock; real robot uses wall
        # time. Controlled by DEMO_USE_SIM_TIME env var (default true).
        use_sim_time = _env_use_sim_time()
        self.set_parameters([Parameter("use_sim_time", value=use_sim_time)])
        self.get_logger().info(
            f"use_sim_time={use_sim_time} "
            f"(DEMO_USE_SIM_TIME={os.environ.get('DEMO_USE_SIM_TIME', '<unset>')})"
        )

        self.buffet_map = buffet_map
        self.goal_label = goal_label

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # Latched publishers so monitor (which may start later) sees
        # the most recent path / status.
        latched_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.path_pub = self.create_publisher(
            NavPath, "/demo/planned_path", latched_qos,
        )
        self.status_pub = self.create_publisher(
            String, "/demo/status", latched_qos,
        )

        self.nav_client = ActionClient(
            self, FollowPath, "follow_path"
        )
        self.get_logger().info("Waiting for Nav2 FollowPath server...")

    def _publish_status(self, text: str) -> None:
        msg = String()
        msg.data = text
        self.status_pub.publish(msg)

    def _publish_path(self, path: NavPath) -> None:
        self.path_pub.publish(path)

    def _publish_empty_path(self) -> None:
        self.path_pub.publish(NavPath(header=NavPath().header))

    def get_robot_pose(self) -> Optional[Tuple[float, float, float]]:
        try:
            t = self.tf_buffer.lookup_transform(
                "map", "base_footprint", rclpy.time.Time(),
                timeout=Duration(seconds=2.0),
            )
            x = t.transform.translation.x
            y = t.transform.translation.y
            q = t.transform.rotation
            yaw = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            return (x, y, yaw)
        except Exception as e:
            self.get_logger().warn(f"TF: {e}", throttle_duration_sec=5.0)
            return None

    def run(self) -> None:
        if not self.nav_client.wait_for_server(timeout_sec=10.0):
            self.get_logger().error("Nav2 not available")
            self._publish_status("ERROR: Nav2 not available")
            return
        self.get_logger().info("Nav2 connected.")

        goal = self.goal_label
        self.get_logger().info(f"--- Goal: {goal} ---")
        self._publish_status(f"-> {goal}: getting pose...")

        # Get pose.
        pose = None
        for attempt in range(60):
            rclpy.spin_once(self, timeout_sec=0.5)
            pose = self.get_robot_pose()
            if pose:
                break
            if attempt % 5 == 0:
                self.get_logger().info(f"Waiting for pose... ({attempt + 1})")

        if pose is None:
            self.get_logger().error("No robot pose.")
            self._publish_status(f"-> {goal}: ERROR no pose")
            return

        x, y, yaw = pose
        self.get_logger().info(
            f"Robot at ({x:.3f}, {y:.3f}), yaw={math.degrees(yaw):.0f} deg"
        )

        # Plan.
        self._publish_status(f"-> {goal}: planning...")
        path_msg, plan = plan_to_path(self.buffet_map, (x, y), goal)
        if path_msg is None or plan is None:
            self.get_logger().error(f"Planning failed: {goal}")
            self._publish_status(f"-> {goal}: ERROR no path")
            return

        self._publish_path(path_msg)
        self._publish_status(f"-> {goal}: navigating...")

        success = self._navigate(path_msg)
        self._publish_empty_path()
        if not success:
            self.get_logger().error(f"Navigation failed: {goal}")
            self._publish_status(f"-> {goal}: FAILED")
            return

        self._publish_status(f"arrived at {goal}!")
        self.get_logger().info(f"Arrived at {goal}")

    def _navigate(self, path_msg: NavPath) -> bool:
        goal_msg = FollowPath.Goal()
        goal_msg.path = path_msg
        goal_msg.controller_id = "FollowPath"
        goal_msg.goal_checker_id = "general_goal_checker"

        # Proximity fallback: RPP's goal_checker sometimes settles just
        # outside its xy tolerance and never declares success, leaving
        # the action stuck in RUNNING forever. If the robot stays within
        # ARRIVAL_RADIUS of the final path pose for ARRIVAL_DWELL
        # seconds, we cancel the action and treat it as arrived.
        final = path_msg.poses[-1].pose.position
        goal_xy = (final.x, final.y)
        ARRIVAL_RADIUS = 0.10
        ARRIVAL_DWELL = 1.5

        self.get_logger().info(
            f"Sending Path with {len(path_msg.poses)} poses to RPP..."
        )
        future = self.nav_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error("Goal rejected")
            return False

        self.get_logger().info("Goal accepted.")
        result_future = goal_handle.get_result_async()

        near_since: Optional[float] = None
        preempted = False
        while not result_future.done():
            rclpy.spin_once(self, timeout_sec=0.1)
            pose = self.get_robot_pose()
            if pose is None:
                continue
            dist = math.hypot(pose[0] - goal_xy[0], pose[1] - goal_xy[1])
            now = self.get_clock().now().nanoseconds * 1e-9
            if dist <= ARRIVAL_RADIUS:
                if near_since is None:
                    near_since = now
                elif now - near_since >= ARRIVAL_DWELL:
                    self.get_logger().info(
                        f"Within {ARRIVAL_RADIUS:.2f} m for "
                        f"{ARRIVAL_DWELL:.1f} s — preempting FollowPath."
                    )
                    preempted = True
                    cancel_future = goal_handle.cancel_goal_async()
                    rclpy.spin_until_future_complete(
                        self, cancel_future, timeout_sec=5.0,
                    )
                    while not result_future.done():
                        rclpy.spin_once(self, timeout_sec=0.1)
                    break
            else:
                near_since = None

        status = result_future.result().status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info("Navigation succeeded!")
            return True
        if preempted:
            self.get_logger().info(
                "Treated as arrived (proximity preempt)."
            )
            return True
        self.get_logger().warn(f"Nav ended with status {status}")
        return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bridge: planner -> Nav2 (single task)"
    )
    parser.add_argument(
        "--goal", required=True, metavar="LABEL",
        help="Goal waypoint label (e.g. Kitchen)",
    )
    parser.add_argument(
        "--map", type=Path, default=DEFAULT_MAP_PATH,
        help=f"Planner map YAML (default: {DEFAULT_MAP_PATH.name})",
    )
    argv = sys.argv[1:]
    if "--ros-args" in argv:
        argv = argv[: argv.index("--ros-args")]
    args = parser.parse_args(argv)

    buffet_map = load_buffet_map(args.map)
    print(
        f"Loaded: {buffet_map.name}, "
        f"{len(buffet_map.graph.waypoints)} waypoints"
    )
    print(f"Goal: {args.goal}")

    try:
        buffet_map.graph.find_by_label(args.goal)
    except KeyError:
        available = sorted(
            wp.label for wp in buffet_map.graph.waypoints.values()
            if wp.label
        )
        print(f"Unknown: {args.goal!r}. Available: {', '.join(available)}",
              file=sys.stderr)
        sys.exit(1)

    rclpy.init(args=sys.argv)
    node = PlannerBridge(buffet_map, args.goal)
    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
