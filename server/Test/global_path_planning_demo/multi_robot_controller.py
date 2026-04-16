#!/usr/bin/env python3
"""Multi-robot controller — central server with per-robot threads.

Main thread computes paths (with reserved_paths for conflict avoidance),
then dispatches each path to a dedicated RobotThread that drives one
robot via Nav2 FollowPath.

Each thread gets its own rclpy Context so the ROS 2 nodes are fully
independent. Robots are distinguished by ROS_DOMAIN_ID (set per-thread
via the node's remappings) or by namespace.

Usage::

    # 2 robots, each going to a different goal
    python3 multi_robot_controller.py \\
        --goals Kitchen Return \\
        --domain-ids 41 42

    # Same domain, namespace separation
    python3 multi_robot_controller.py \\
        --goals Kitchen Return \\
        --namespaces /robot1 /robot2
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ROS 2 imports
import rclpy
from rclpy.context import Context
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.parameter import Parameter
from rclpy.qos import (
    QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy,
)

from action_msgs.msg import GoalStatus
from nav_msgs.msg import Path as NavPath
from nav2_msgs.action import FollowPath
from std_msgs.msg import String

from tf2_ros import Buffer, TransformListener

# Local planner imports
DEMO_DIR = Path(__file__).parent
sys.path.insert(0, str(DEMO_DIR))

from astar_planner import plan_path as wp_plan_path, FreeStartPlan  # noqa: E402
from map_data import DEFAULT_MAP_PATH, BuffetMap, load_buffet_map  # noqa: E402
from nav2_bridge import (  # noqa: E402
    plan_to_path,
    yaw_to_quaternion,
    _env_use_sim_time,
)


# ---------------------------------------------------------------------------
# Per-robot thread
# ---------------------------------------------------------------------------


class RobotThread(threading.Thread):
    """Thread that drives one robot through Nav2 FollowPath.

    Each thread creates its own rclpy Context → Node, so multiple
    threads can coexist without sharing executor state.
    """

    def __init__(
        self,
        robot_id: int,
        buffet_map: BuffetMap,
        path_msg: NavPath,
        plan: FreeStartPlan,
        goal_label: str,
        *,
        domain_id: Optional[int] = None,
        namespace: str = "",
        tf_prefix: str = "",
    ) -> None:
        super().__init__(name=f"Robot-{robot_id}", daemon=True)
        self.robot_id = robot_id
        self.buffet_map = buffet_map
        self.path_msg = path_msg
        self.plan = plan
        self.goal_label = goal_label
        self.domain_id = domain_id
        self.namespace = namespace
        self.tf_prefix = tf_prefix

        # Result — set after run() completes.
        self.success: Optional[bool] = None
        self.error_msg: str = ""

    def run(self) -> None:
        tag = f"[Robot-{self.robot_id}]"
        try:
            # Each thread gets its own rclpy context.
            ctx = Context()
            args: List[str] = []
            if self.domain_id is not None:
                os.environ[f"_R{self.robot_id}_DOMAIN"] = str(self.domain_id)
                args = [
                    "--ros-args",
                    "-r", f"__ns:={self.namespace}" if self.namespace else "__ns:=/",
                ]
            rclpy.init(args=args, context=ctx, domain_id=self.domain_id)

            node_name = f"multi_bridge_r{self.robot_id}"
            node = _RobotBridgeNode(
                node_name=node_name,
                robot_id=self.robot_id,
                path_msg=self.path_msg,
                goal_label=self.goal_label,
                namespace=self.namespace,
                tf_prefix=self.tf_prefix,
                context=ctx,
            )

            try:
                node.get_logger().info(
                    f"{tag} started  domain_id={self.domain_id}  "
                    f"ns={self.namespace or '/'}"
                )
                self.success = node.execute()
                if not self.success:
                    self.error_msg = "navigation failed"
            except Exception as exc:
                node.get_logger().error(f"{tag} exception: {exc}")
                self.success = False
                self.error_msg = str(exc)
            finally:
                node.destroy_node()
                rclpy.shutdown(context=ctx)

        except Exception as exc:
            print(f"{tag} init error: {exc}")
            self.success = False
            self.error_msg = str(exc)


class _RobotBridgeNode(Node):
    """Lightweight Nav2 bridge node that runs inside a RobotThread."""

    ARRIVAL_RADIUS = 0.10
    ARRIVAL_DWELL = 1.5

    def __init__(
        self,
        node_name: str,
        robot_id: int,
        path_msg: NavPath,
        goal_label: str,
        namespace: str,
        tf_prefix: str,
        context: Context,
    ) -> None:
        super().__init__(
            node_name,
            namespace=namespace,
            context=context,
        )
        self.robot_id = robot_id
        self.path_msg = path_msg
        self.goal_label = goal_label
        self._tf_prefix = tf_prefix
        self._tag = f"[Robot-{robot_id}]"

        use_sim_time = _env_use_sim_time()
        self.set_parameters([Parameter("use_sim_time", value=use_sim_time)])

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        latched_qos = QoSProfile(
            depth=1,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.status_pub = self.create_publisher(
            String, f"/demo/robot{robot_id}/status", latched_qos,
        )
        self.path_pub = self.create_publisher(
            NavPath, f"/demo/robot{robot_id}/planned_path", latched_qos,
        )

        self.nav_client = ActionClient(self, FollowPath, "follow_path")

    def _publish_status(self, text: str) -> None:
        msg = String()
        msg.data = text
        self.status_pub.publish(msg)
        self.get_logger().info(f"{self._tag} {text}")

    def _get_robot_pose(self) -> Optional[Tuple[float, float, float]]:
        base_frame = f"{self._tf_prefix}base_footprint" if self._tf_prefix else "base_footprint"
        try:
            t = self.tf_buffer.lookup_transform(
                "map", base_frame, rclpy.time.Time(),
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
            self.get_logger().warn(
                f"{self._tag} TF: {e}", throttle_duration_sec=5.0,
            )
            return None

    def execute(self) -> bool:
        """Wait for Nav2 and send the pre-computed path. Blocking."""
        self._publish_status(f"-> {self.goal_label}: waiting for Nav2...")

        if not self.nav_client.wait_for_server(timeout_sec=15.0):
            self._publish_status(f"-> {self.goal_label}: ERROR Nav2 not available")
            return False

        self._publish_status(f"-> {self.goal_label}: navigating...")
        self.path_pub.publish(self.path_msg)

        return self._navigate(self.path_msg)

    def _navigate(self, path_msg: NavPath) -> bool:
        goal_msg = FollowPath.Goal()
        goal_msg.path = path_msg
        goal_msg.controller_id = "FollowPath"
        goal_msg.goal_checker_id = "general_goal_checker"

        final = path_msg.poses[-1].pose.position
        goal_xy = (final.x, final.y)

        self.get_logger().info(
            f"{self._tag} Sending {len(path_msg.poses)} poses to FollowPath..."
        )
        future = self.nav_client.send_goal_async(goal_msg)
        rclpy.spin_until_future_complete(self, future, timeout_sec=10.0)

        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            self._publish_status(f"-> {self.goal_label}: goal rejected")
            return False

        self.get_logger().info(f"{self._tag} Goal accepted.")
        result_future = goal_handle.get_result_async()

        near_since: Optional[float] = None
        preempted = False

        while not result_future.done():
            rclpy.spin_once(self, timeout_sec=0.1)
            pose = self._get_robot_pose()
            if pose is None:
                continue
            dist = math.hypot(pose[0] - goal_xy[0], pose[1] - goal_xy[1])
            now = self.get_clock().now().nanoseconds * 1e-9

            if dist <= self.ARRIVAL_RADIUS:
                if near_since is None:
                    near_since = now
                elif now - near_since >= self.ARRIVAL_DWELL:
                    self.get_logger().info(
                        f"{self._tag} Within {self.ARRIVAL_RADIUS:.2f} m for "
                        f"{self.ARRIVAL_DWELL:.1f} s — preempting."
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
            self._publish_status(f"arrived at {self.goal_label}!")
            return True
        if preempted:
            self._publish_status(f"arrived at {self.goal_label} (proximity)!")
            return True

        self._publish_status(f"-> {self.goal_label}: FAILED (status {status})")
        return False


# ---------------------------------------------------------------------------
# Main thread — path planning + dispatch
# ---------------------------------------------------------------------------


def _get_robot_pose_blocking(
    domain_id: Optional[int],
    namespace: str,
    tf_prefix: str,
    robot_id: int,
    timeout: float = 30.0,
) -> Optional[Tuple[float, float, float]]:
    """Spin up a temporary node to read one TF pose, then tear down."""
    ctx = Context()
    rclpy.init(context=ctx, domain_id=domain_id)
    node = Node(
        f"_pose_reader_r{robot_id}",
        namespace=namespace,
        context=ctx,
    )
    use_sim_time = _env_use_sim_time()
    node.set_parameters([Parameter("use_sim_time", value=use_sim_time)])

    tf_buf = Buffer()
    tf_lis = TransformListener(tf_buf, node)

    base_frame = f"{tf_prefix}base_footprint" if tf_prefix else "base_footprint"
    result = None
    deadline = time.monotonic() + timeout

    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.5)
            try:
                t = tf_buf.lookup_transform(
                    "map", base_frame, rclpy.time.Time(),
                    timeout=Duration(seconds=1.0),
                )
                x = t.transform.translation.x
                y = t.transform.translation.y
                q = t.transform.rotation
                yaw = math.atan2(
                    2.0 * (q.w * q.z + q.x * q.y),
                    1.0 - 2.0 * (q.y * q.y + q.z * q.z),
                )
                result = (x, y, yaw)
                break
            except Exception:
                pass
    finally:
        node.destroy_node()
        rclpy.shutdown(context=ctx)

    return result


def run_multi(
    buffet_map: BuffetMap,
    goals: List[str],
    domain_ids: List[Optional[int]],
    namespaces: List[str],
    tf_prefixes: List[str],
) -> bool:
    """Plan paths for all robots, then dispatch them in parallel threads."""
    n = len(goals)
    print(f"\n{'='*60}")
    print(f"  Multi-robot controller — {n} robot(s)")
    print(f"{'='*60}")

    # ------------------------------------------------------------------
    # Phase 1: Get each robot's current pose (sequential — each needs
    #          its own rclpy context).
    # ------------------------------------------------------------------
    poses: List[Tuple[float, float, float]] = []
    for i in range(n):
        print(f"\n[main] Robot-{i}: reading pose  "
              f"(domain_id={domain_ids[i]}, ns={namespaces[i] or '/'})")
        pose = _get_robot_pose_blocking(
            domain_id=domain_ids[i],
            namespace=namespaces[i],
            tf_prefix=tf_prefixes[i],
            robot_id=i,
        )
        if pose is None:
            print(f"[main] ERROR: Robot-{i} pose not available")
            return False
        poses.append(pose)
        print(f"[main] Robot-{i} at ({pose[0]:.3f}, {pose[1]:.3f}), "
              f"yaw={math.degrees(pose[2]):.0f} deg")

    # ------------------------------------------------------------------
    # Phase 2: Plan paths sequentially, each subsequent robot reserves
    #          the paths of all previous robots.
    # ------------------------------------------------------------------
    print(f"\n[main] Planning paths...")
    plans: List[Tuple[NavPath, FreeStartPlan]] = []
    reserved: List[List[int]] = []  # waypoint sequences from prior robots

    for i in range(n):
        goal_label = goals[i]

        # Resolve goal id
        try:
            goal_id = buffet_map.graph.find_by_label(goal_label)
        except KeyError:
            print(f"[main] ERROR: unknown goal '{goal_label}'")
            return False

        # Use plan_to_path but with reserved_paths support.
        # plan_to_path doesn't take reserved_paths, so we do it manually.
        from astar_planner import plan_path_from_point
        plan = plan_path_from_point(
            buffet_map,
            (poses[i][0], poses[i][1]),
            goal_id,
            reserved_paths=reserved if reserved else None,
        )

        if plan is None:
            print(f"[main] ERROR: no path for Robot-{i} to '{goal_label}'")
            return False

        # Build nav_msgs/Path from the plan
        from nav2_bridge import _densify_path
        points = _densify_path(buffet_map.graph, plan.waypoints, step=0.05)
        path_msg = NavPath()
        path_msg.header.frame_id = "map"
        from geometry_msgs.msg import PoseStamped
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

        plans.append((path_msg, plan))
        reserved.append(plan.waypoints)

        wp_labels = []
        for wp_id in plan.waypoints:
            wp = buffet_map.graph.waypoints[wp_id]
            wp_labels.append(wp.label or f"({wp.x:g},{wp.y:g})")
        print(f"[main] Robot-{i} -> {goal_label}: "
              f"{' -> '.join(wp_labels)} "
              f"({plan.total_cost:.2f} m, {len(points)} pts)")

    # ------------------------------------------------------------------
    # Phase 3: Launch per-robot threads in parallel.
    # ------------------------------------------------------------------
    print(f"\n[main] Dispatching {n} robot(s)...")
    threads: List[RobotThread] = []
    for i in range(n):
        path_msg, plan = plans[i]
        t = RobotThread(
            robot_id=i,
            buffet_map=buffet_map,
            path_msg=path_msg,
            plan=plan,
            goal_label=goals[i],
            domain_id=domain_ids[i],
            namespace=namespaces[i],
            tf_prefix=tf_prefixes[i],
        )
        threads.append(t)

    # Start all threads together
    for t in threads:
        t.start()

    # Wait for all to finish
    for t in threads:
        t.join()

    # ------------------------------------------------------------------
    # Phase 4: Report results.
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("  Results")
    print(f"{'='*60}")
    all_ok = True
    for t in threads:
        status = "PASS" if t.success else "FAIL"
        extra = f" ({t.error_msg})" if t.error_msg else ""
        print(f"  Robot-{t.robot_id} -> {t.goal_label}: {status}{extra}")
        if not t.success:
            all_ok = False

    print(f"{'='*60}")
    if all_ok:
        print("  All robots arrived successfully!")
    else:
        print("  Some robots failed.")
    print()
    return all_ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-robot controller: central path planning + "
                    "per-robot Nav2 dispatch threads",
    )
    parser.add_argument(
        "--goals", nargs="+", required=True, metavar="LABEL",
        help="Goal waypoint label per robot (e.g. Kitchen Return)",
    )
    parser.add_argument(
        "--domain-ids", nargs="+", type=int, default=None,
        metavar="ID",
        help="ROS_DOMAIN_ID per robot (e.g. 41 42). "
             "If omitted, all robots share the current domain.",
    )
    parser.add_argument(
        "--namespaces", nargs="+", default=None, metavar="NS",
        help="ROS namespace per robot (e.g. /robot1 /robot2). "
             "If omitted, all robots use root namespace.",
    )
    parser.add_argument(
        "--tf-prefixes", nargs="+", default=None, metavar="PFX",
        help="TF prefix per robot for base_footprint lookup "
             "(e.g. robot1/ robot2/).",
    )
    parser.add_argument(
        "--map", type=Path, default=DEFAULT_MAP_PATH,
        help=f"Planner map YAML (default: {DEFAULT_MAP_PATH.name})",
    )

    argv = sys.argv[1:]
    if "--ros-args" in argv:
        argv = argv[: argv.index("--ros-args")]
    args = parser.parse_args(argv)

    n = len(args.goals)

    # Validate and fill defaults
    if args.domain_ids is not None:
        if len(args.domain_ids) != n:
            parser.error(
                f"--domain-ids: expected {n} values, got {len(args.domain_ids)}"
            )
        domain_ids: List[Optional[int]] = list(args.domain_ids)
    else:
        domain_ids = [None] * n

    if args.namespaces is not None:
        if len(args.namespaces) != n:
            parser.error(
                f"--namespaces: expected {n} values, got {len(args.namespaces)}"
            )
        namespaces = args.namespaces
    else:
        namespaces = [""] * n

    if args.tf_prefixes is not None:
        if len(args.tf_prefixes) != n:
            parser.error(
                f"--tf-prefixes: expected {n} values, got {len(args.tf_prefixes)}"
            )
        tf_prefixes = args.tf_prefixes
    else:
        tf_prefixes = [""] * n

    # Load map
    buffet_map = load_buffet_map(args.map)
    print(f"Loaded: {buffet_map.name}, "
          f"{len(buffet_map.graph.waypoints)} waypoints")

    # Validate goals
    available = sorted(
        wp.label for wp in buffet_map.graph.waypoints.values() if wp.label
    )
    for goal in args.goals:
        try:
            buffet_map.graph.find_by_label(goal)
        except KeyError:
            print(f"Unknown goal: {goal!r}. Available: {', '.join(available)}",
                  file=sys.stderr)
            sys.exit(1)

    ok = run_multi(buffet_map, args.goals, domain_ids, namespaces, tf_prefixes)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
