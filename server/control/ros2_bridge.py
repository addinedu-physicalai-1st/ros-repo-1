#!/usr/bin/env python3
"""Bidirectional ROS 2 ↔ Control Server bridge.

**Outbound (Robot → Server):**
  - UDP telemetry (pose at ~5 Hz)
  - TCP heartbeat + StatusReport

**Inbound (Server → Robot):**
  - TCP commands (MOVE_TO, etc.) → Nav2 FollowPath action

This bridge runs on the **notebook** alongside the control server.
Each robot gets a background thread with its own rclpy Context +
domain_id.

Usage::

    source /opt/ros/jazzy/setup.bash
    source ~/Desktop/ros-repo-1/install/setup.bash

    python3 ros2_bridge.py --robot-ids pinky1 pinky2 --domain-ids 41 42
"""

from __future__ import annotations

import argparse
import math
import os
import select
import socket
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.parameter import Parameter
from tf2_ros import Buffer, TransformListener

from geometry_msgs.msg import PoseStamped, Quaternion
from nav_msgs.msg import Path as NavPath
from nav2_msgs.action import FollowPath
from action_msgs.msg import GoalStatus

# Protobuf
_CONTROL_DIR = str(Path(__file__).parent)
if _CONTROL_DIR not in sys.path:
    sys.path.insert(0, _CONTROL_DIR)
from robotcafe.db.v1 import robotcafe_pb2 as pb

# Path planning library
_LIB_DIR = str(Path(__file__).resolve().parents[1] / "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
try:
    from path_planning import load_buffet_map, densify_path, BuffetMap
    from path_planning.planner import plan_path_from_point
    _HAS_PLANNER = True
except ImportError:
    _HAS_PLANNER = False

TCP_MAGIC = 0xAABBCCDD
UDP_MAGIC = 0xDDCCBBAA

DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 9000
DEFAULT_UDP_PORT = 9001
POSE_HZ = 5.0
HEARTBEAT_HZ = 1.0
STATUS_HZ = 0.5

# Flush print immediately (important for log files)
import functools
print = functools.partial(print, flush=True)


def _encode_tcp_frame(packet: pb.TcpPacket) -> bytes:
    body = packet.SerializeToString()
    payload = TCP_MAGIC.to_bytes(4, "big") + body
    return len(payload).to_bytes(4, "big") + payload


def _encode_udp_packet(pkt: pb.UdpTelemetryPacket) -> bytes:
    return UDP_MAGIC.to_bytes(4, "big") + pkt.SerializeToString()


def _yaw_to_quaternion(yaw: float) -> Quaternion:
    q = Quaternion()
    q.z = math.sin(yaw / 2.0)
    q.w = math.cos(yaw / 2.0)
    return q


def _build_nav_path(points: List[Tuple[float, float]], frame_id: str = "map") -> NavPath:
    """Build a nav_msgs/Path from a list of (x, y) points."""
    path_msg = NavPath()
    path_msg.header.frame_id = frame_id
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
        ps.pose.orientation = _yaw_to_quaternion(yaw)
        path_msg.poses.append(ps)
    return path_msg


# Shared state across all RobotBridge instances (demo simulator pattern).
# Protected by _shared_lock.
_shared_lock = threading.Lock()
_active_paths: dict[str, List[int]] = {}  # robot_id → planned waypoint IDs
_active_path_idx: dict[str, int] = {}     # robot_id → next unvisited wp index
_robot_poses: dict[str, Tuple[float, float]] = {}  # robot_id → (x, y)


class RobotBridge(threading.Thread):
    """Bidirectional bridge for one robot."""

    ARRIVAL_RADIUS = 0.10
    ARRIVAL_DWELL = 1.5

    def __init__(
        self,
        robot_id: str,
        domain_id: int,
        server_host: str,
        tcp_port: int,
        udp_port: int,
        buffet_map: Optional[BuffetMap] = None,
    ) -> None:
        super().__init__(daemon=True, name=f"Bridge-{robot_id}")
        self.robot_id = robot_id
        self.domain_id = domain_id
        self.server_host = server_host
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self._buffet_map = buffet_map
        self._stop_event = threading.Event()

        self._pose: Optional[Tuple[float, float, float]] = None
        self._seq = 0
        self._nav_busy = False
        self._current_status = pb.RobotStatus.IDLE
        self._tcp_recv_buf = b""

    def stop(self):
        self._stop_event.set()

    def run(self) -> None:
        tag = f"[{self.robot_id}]"
        print(f"{tag} Starting bridge (domain={self.domain_id})")

        ctx = Context()
        rclpy.init(context=ctx, domain_id=self.domain_id)
        node = Node(f"bridge_{self.robot_id}", context=ctx)

        use_sim = os.environ.get(
            "DEMO_USE_SIM_TIME", "false"
        ).lower() in ("1", "true", "yes", "on")
        node.set_parameters([Parameter("use_sim_time", value=use_sim)])

        executor = SingleThreadedExecutor(context=ctx)
        executor.add_node(node)

        tf_buf = Buffer()
        TransformListener(tf_buf, node)

        # Nav2 FollowPath action client
        nav_client = ActionClient(node, FollowPath, "follow_path")

        # Sockets
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tcp_sock = self._connect_tcp(tag)
        if tcp_sock:
            tcp_sock.setblocking(False)
            self._send_heartbeat(tcp_sock, tag)

        pose_interval = 1.0 / POSE_HZ
        heartbeat_interval = 1.0 / HEARTBEAT_HZ
        status_interval = 1.0 / STATUS_HZ
        last_pose_t = last_hb_t = last_status_t = 0.0

        # Navigation state
        active_goal_handle = None
        result_future = None
        goal_xy = None
        near_since = None
        preempted = False
        pending_goal = None      # (tx, ty, tt) waiting for clear path
        pending_cmd_id = ""
        last_replan_t = 0.0

        try:
            while not self._stop_event.is_set():
                try:
                    executor.spin_once(timeout_sec=0.05)
                except Exception:
                    if self._stop_event.is_set():
                        break
                    continue

                self._update_pose(tf_buf)
                now = time.monotonic()

                # ── Outbound: UDP pose ────────────────────────
                if self._pose and now - last_pose_t >= pose_interval:
                    self._send_udp_pose(udp_sock)
                    last_pose_t = now

                # ── Outbound: TCP heartbeat ───────────────────
                if tcp_sock and now - last_hb_t >= heartbeat_interval:
                    try:
                        self._send_heartbeat(tcp_sock, tag)
                        last_hb_t = now
                    except Exception:
                        print(f"{tag} TCP heartbeat failed, reconnecting...")
                        tcp_sock = self._reconnect_tcp(tag)
                        if tcp_sock:
                            last_hb_t = now

                # ── Outbound: TCP status ──────────────────────
                if tcp_sock and now - last_status_t >= status_interval:
                    try:
                        self._send_status(tcp_sock, tag)
                        last_status_t = now
                    except Exception:
                        pass

                # ── Inbound: TCP commands from server ─────────
                # ── Inbound: TCP commands from server ─────────
                if tcp_sock:
                    cmd = self._try_recv_command(tcp_sock, tag)
                    if cmd is not None:
                        pending_goal = (
                            cmd.get("x", 0.0),
                            cmd.get("y", 0.0),
                            cmd.get("theta", 0.0),
                        )
                        pending_cmd_id = cmd.get("cmd_id", "")
                        last_replan_t = 0.0
                        print(f"{tag} CMD MOVE_TO ({pending_goal[0]:.2f}, "
                              f"{pending_goal[1]:.2f}, "
                              f"{math.degrees(pending_goal[2]):.0f}°)")

                # ── Pending goal: try to plan and dispatch ────
                if pending_goal and not self._nav_busy:
                    if now - last_replan_t >= 0.5:  # retry every 0.5s
                        last_replan_t = now
                        tx, ty, tt = pending_goal
                        path_msg = self._plan_nav_path(tx, ty, tt)
                        if path_msg and path_msg.poses:
                            if nav_client.wait_for_server(timeout_sec=3.0):
                                goal_msg = FollowPath.Goal()
                                goal_msg.path = path_msg
                                goal_msg.controller_id = "FollowPath"
                                goal_msg.goal_checker_id = "general_goal_checker"

                                future = nav_client.send_goal_async(goal_msg)
                                rclpy.spin_until_future_complete(
                                    node, future, executor=executor,
                                    timeout_sec=5.0,
                                )
                                gh = future.result()
                                if gh and gh.accepted:
                                    active_goal_handle = gh
                                    result_future = gh.get_result_async()
                                    goal_xy = (tx, ty)
                                    near_since = None
                                    preempted = False
                                    self._current_status = pb.RobotStatus.MOVING
                                    self._nav_busy = True
                                    pending_goal = None
                                    print(f"{tag} Nav2 goal accepted "
                                          f"({len(path_msg.poses)} pts)")
                                else:
                                    print(f"{tag} Nav2 goal REJECTED")
                        else:
                            print(f"{tag} Path blocked, waiting...")

                # ── Navigation monitoring ─────────────────────
                if result_future is not None:
                    if result_future.done():
                        status = result_future.result().status
                        ok = status == GoalStatus.STATUS_SUCCEEDED or preempted
                        if ok:
                            print(f"{tag} ARRIVED")
                            self._current_status = pb.RobotStatus.ARRIVED
                        else:
                            print(f"{tag} Nav failed (status {status})")
                            self._current_status = pb.RobotStatus.IDLE
                        # Send status immediately
                        if tcp_sock:
                            try:
                                self._send_status(tcp_sock, tag)
                            except Exception:
                                pass
                        # ACK the command so server marks task COMPLETED/FAILED
                        if tcp_sock and pending_cmd_id:
                            ack_status = (pb.AckStatus.EXECUTED if ok
                                          else pb.AckStatus.ACK_FAILED)
                            try:
                                self._send_command_ack(
                                    tcp_sock, tag, pending_cmd_id, ack_status)
                            except Exception:
                                pass
                            pending_cmd_id = ""
                        active_goal_handle = None
                        result_future = None
                        goal_xy = None
                        self._nav_busy = False

                        # Clear shared path reservation
                        with _shared_lock:
                            _active_paths.pop(self.robot_id, None)
                            _active_path_idx.pop(self.robot_id, None)

                        # After ARRIVED, send IDLE after a short delay
                        time.sleep(0.5)
                        self._current_status = pb.RobotStatus.IDLE
                        if tcp_sock:
                            try:
                                self._send_status(tcp_sock, tag)
                            except Exception:
                                pass

                    elif goal_xy and self._pose and not preempted:
                        # Proximity preempt — only fire once per goal
                        dist = math.hypot(
                            self._pose[0] - goal_xy[0],
                            self._pose[1] - goal_xy[1],
                        )
                        mono = time.monotonic()
                        if dist <= self.ARRIVAL_RADIUS:
                            if near_since is None:
                                near_since = mono
                            elif mono - near_since >= self.ARRIVAL_DWELL:
                                print(f"{tag} Proximity preempt")
                                preempted = True
                                active_goal_handle.cancel_goal_async()
                        else:
                            near_since = None

        except Exception as e:
            print(f"{tag} Bridge error: {e}")
        finally:
            try:
                udp_sock.close()
                if tcp_sock:
                    tcp_sock.close()
                executor.shutdown()
                node.destroy_node()
                rclpy.shutdown(context=ctx)
            except Exception:
                pass
            print(f"{tag} Bridge stopped")

    # ── TF ────────────────────────────────────────────────────────────

    WP_PROXIMITY = 0.12  # metres — consider waypoint visited

    def _update_pose(self, tf_buf) -> None:
        try:
            t = tf_buf.lookup_transform(
                "map", "base_footprint", rclpy.time.Time(),
                timeout=Duration(seconds=0.05),
            )
            x = t.transform.translation.x
            y = t.transform.translation.y
            q = t.transform.rotation
            theta = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            self._pose = (x, y, theta)

            # Update shared pose + track waypoint visitation.
            # Advance idx when either (a) close to wps[idx], or (b) closer to
            # wps[idx+1] than wps[idx] (robot has passed the current wp even
            # if Nav2 cut the corner outside WP_PROXIMITY).
            with _shared_lock:
                _robot_poses[self.robot_id] = (x, y)
                wps = _active_paths.get(self.robot_id, [])
                idx = _active_path_idx.get(self.robot_id, 0)
                graph = self._buffet_map.graph if self._buffet_map else None
                while graph and wps and idx < len(wps):
                    wp = graph.waypoints.get(wps[idx])
                    if not wp:
                        break
                    d_cur = math.hypot(x - wp.x, y - wp.y)
                    passed = False
                    if d_cur <= self.WP_PROXIMITY:
                        passed = True
                    elif idx + 1 < len(wps):
                        nxt = graph.waypoints.get(wps[idx + 1])
                        if nxt:
                            d_nxt = math.hypot(x - nxt.x, y - nxt.y)
                            if d_nxt < d_cur:
                                passed = True
                    if not passed:
                        break
                    idx += 1
                    _active_path_idx[self.robot_id] = idx
        except Exception:
            pass

    # ── Path planning (mirrors demo simulator._plan_robot) ───────────

    def _plan_nav_path(self, goal_x: float, goal_y: float,
                       goal_theta: float) -> Optional[NavPath]:
        """Plan a nav_msgs/Path using the demo's quasi-static model.

        1. Other robots' REMAINING paths are reserved (not visited wps).
        2. Other robots' current positions are added as dynamic obstacles.
        3. If blocked by reservation, return None (caller retries later).
        """
        if not (self._buffet_map and _HAS_PLANNER and self._pose):
            return None

        bm = self._buffet_map
        graph = bm.graph
        from path_planning import DynamicObstacle

        # Find nearest waypoint to goal
        best_wp, best_d = None, math.inf
        for wp in graph.waypoints.values():
            d = math.hypot(wp.x - goal_x, wp.y - goal_y)
            if d < best_d:
                best_d = d
                best_wp = wp.wp_id
        if best_wp is None:
            return None

        # Current robot's nearest waypoint (to exclude from reservation)
        current_wp = None
        nearest_d = math.inf
        for wp in graph.waypoints.values():
            d = math.hypot(wp.x - self._pose[0], wp.y - self._pose[1])
            if d < nearest_d:
                nearest_d = d
                current_wp = wp.wp_id

        with _shared_lock:
            # 1) Dynamic obstacles: ONLY other robots that are MOVING
            #    (idle robots should not block paths)
            dyn_obs = []
            for rid, pos in _robot_poses.items():
                if rid != self.robot_id and rid in _active_paths:
                    dyn_obs.append(DynamicObstacle(
                        obs_id=hash(rid) & 0xFFFF,
                        x=pos[0], y=pos[1],
                        radius=0.12,
                        label=rid,
                    ))

            # 2) Reserved paths: ONLY other robots with active paths
            reserved = []
            for rid, wps in _active_paths.items():
                if rid == self.robot_id:
                    continue
                idx = _active_path_idx.get(rid, 0)
                remaining = [w for w in wps[idx:] if w != current_wp]
                if remaining:
                    reserved.append(remaining)

        # Plan with dynamic obstacles + reserved paths
        # If robot is ON a waypoint, use wp→wp planning to avoid
        # diagonal free-start entry segments.
        from path_planning.planner import plan_path as wp_plan_path

        WP_ON_THRESHOLD = 0.08
        start_wp = None
        for wp in graph.waypoints.values():
            if math.hypot(wp.x - self._pose[0], wp.y - self._pose[1]) <= WP_ON_THRESHOLD:
                start_wp = wp.wp_id
                break

        plan_waypoints = None
        if start_wp is not None and start_wp != best_wp:
            path_wps, cost = wp_plan_path(
                bm, start_wp, best_wp,
                dynamic_obstacles=dyn_obs if dyn_obs else None,
                reserved_paths=reserved if reserved else None,
            )
            plan_waypoints = path_wps
        else:
            result = plan_path_from_point(
                bm, (self._pose[0], self._pose[1]), best_wp,
                dynamic_obstacles=dyn_obs if dyn_obs else None,
                reserved_paths=reserved if reserved else None,
            )
            plan_waypoints = result.waypoints if result else None

        if plan_waypoints is None:
            return None

        # Register planned waypoints for other robots to see
        with _shared_lock:
            _active_paths[self.robot_id] = list(plan_waypoints)
            _active_path_idx[self.robot_id] = 0

        points = densify_path(graph, plan_waypoints, step=0.05)
        # Append the actual MOVE_TO target as the final point so the robot
        # ends at the dispatched coordinates (not just the nearest YAML wp).
        # This makes DB-saved place coords (e.g. dragged/edited) the source
        # of truth for the final destination, not the static graph.
        if points:
            last_x, last_y = points[-1]
            if math.hypot(last_x - goal_x, last_y - goal_y) > 0.02:
                points.append((goal_x, goal_y))
        else:
            points = [(goal_x, goal_y)]
        wp_labels = []
        for wp_id in plan_waypoints:
            wp = graph.waypoints[wp_id]
            wp_labels.append(wp.label or f"({wp.x:.2f},{wp.y:.2f})")
        wp_labels.append(f"→({goal_x:.2f},{goal_y:.2f})")
        print(f"[{self.robot_id}] Path: {' → '.join(wp_labels)}")
        return _build_nav_path(points)

    # ── TCP connection ────────────────────────────────────────────────

    def _connect_tcp(self, tag: str) -> Optional[socket.socket]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((self.server_host, self.tcp_port))
            print(f"{tag} TCP connected to {self.server_host}:{self.tcp_port}")
            return sock
        except Exception as e:
            print(f"{tag} TCP connect failed: {e}")
            return None

    def _reconnect_tcp(self, tag: str) -> Optional[socket.socket]:
        sock = self._connect_tcp(tag)
        if sock:
            sock.setblocking(False)
            self._send_heartbeat(sock, tag)
            self._tcp_recv_buf = b""
        return sock

    # ── TCP send ──────────────────────────────────────────────────────

    def _send_heartbeat(self, sock: socket.socket, tag: str) -> None:
        hb = pb.Heartbeat(robot_id=self.robot_id, timestamp=int(time.time()))
        pkt = pb.TcpPacket(robot_id=self.robot_id, heartbeat=hb)
        self._seq += 1
        pkt.seq = self._seq
        data = _encode_tcp_frame(pkt)
        sock.setblocking(True)
        sock.sendall(data)
        sock.setblocking(False)

    def _send_status(self, sock: socket.socket, tag: str) -> None:
        sr = pb.StatusReport(
            robot_id=self.robot_id,
            robot_status=self._current_status,
            battery=100,
        )
        pkt = pb.TcpPacket(robot_id=self.robot_id, status_payload=sr)
        self._seq += 1
        pkt.seq = self._seq
        data = _encode_tcp_frame(pkt)
        sock.setblocking(True)
        sock.sendall(data)
        sock.setblocking(False)

    def _send_command_ack(self, sock: socket.socket, tag: str,
                          cmd_id: str, status) -> None:
        ack = pb.CommandAck(
            cmd_id=cmd_id, robot_id=self.robot_id, status=status,
        )
        pkt = pb.TcpPacket(robot_id=self.robot_id, ack_payload=ack)
        self._seq += 1
        pkt.seq = self._seq
        data = _encode_tcp_frame(pkt)
        sock.setblocking(True)
        sock.sendall(data)
        sock.setblocking(False)

    # ── TCP receive (non-blocking) ────────────────────────────────────

    def _try_recv_command(self, sock: socket.socket, tag: str) -> Optional[dict]:
        """Non-blocking read from TCP. Returns command dict or None."""
        try:
            ready, _, _ = select.select([sock], [], [], 0)
            if not ready:
                return None
            data = sock.recv(65536)
            if not data:
                return None
            self._tcp_recv_buf += data
        except (BlockingIOError, socket.error):
            return None

        # Parse frames from buffer
        while len(self._tcp_recv_buf) >= 4:
            frame_len = int.from_bytes(self._tcp_recv_buf[:4], "big")
            if len(self._tcp_recv_buf) < 4 + frame_len:
                break
            frame = self._tcp_recv_buf[4:4 + frame_len]
            self._tcp_recv_buf = self._tcp_recv_buf[4 + frame_len:]

            if len(frame) < 4:
                continue
            magic = int.from_bytes(frame[:4], "big")
            if magic != TCP_MAGIC:
                continue

            pkt = pb.TcpPacket()
            try:
                pkt.ParseFromString(frame[4:])
            except Exception:
                continue

            # Extract command
            cmd = self._extract_move_command(pkt)
            if cmd:
                return cmd

        return None

    def _extract_move_command(self, pkt: pb.TcpPacket) -> Optional[dict]:
        """Extract target coordinates from any command type."""
        if pkt.HasField("cmd_payload"):
            cmd = pkt.cmd_payload
            return {
                "cmd_id": cmd.cmd_id,
                "x": cmd.target_x,
                "y": cmd.target_y,
                "theta": cmd.target_theta,
            }
        if pkt.HasField("delivery_cmd"):
            cmd = pkt.delivery_cmd
            return {
                "cmd_id": cmd.cmd_id,
                "x": cmd.target_x,
                "y": cmd.target_y,
                "theta": cmd.target_theta,
            }
        if pkt.HasField("follow_cmd"):
            cmd = pkt.follow_cmd
            return {
                "cmd_id": cmd.cmd_id,
                "x": cmd.target_x,
                "y": cmd.target_y,
                "theta": cmd.target_theta,
            }
        if pkt.HasField("collect_cmd"):
            cmd = pkt.collect_cmd
            return {
                "cmd_id": cmd.cmd_id,
                "x": cmd.target_x,
                "y": cmd.target_y,
                "theta": cmd.target_theta,
            }
        if pkt.HasField("guidance_cmd"):
            cmd = pkt.guidance_cmd
            return {
                "cmd_id": cmd.cmd_id,
                "x": cmd.target_x,
                "y": cmd.target_y,
                "theta": cmd.target_theta,
            }
        return None

    # ── UDP send ──────────────────────────────────────────────────────

    def _send_udp_pose(self, sock: socket.socket) -> None:
        if not self._pose:
            return
        x, y, theta = self._pose
        pose = pb.TelemetryPose(
            robot_id=self.robot_id, seq=self._seq,
            x=x, y=y, theta=theta,
        )
        pose.timestamp.FromMilliseconds(int(time.time() * 1000))
        pkt = pb.UdpTelemetryPacket(robot_id=self.robot_id, pose=pose)
        sock.sendto(_encode_udp_packet(pkt), (self.server_host, self.udp_port))


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bidirectional ROS 2 ↔ Control Server bridge",
    )
    parser.add_argument("--robot-ids", nargs="+", required=True)
    parser.add_argument("--domain-ids", nargs="+", type=int, required=True)
    parser.add_argument("--server", default=DEFAULT_SERVER_HOST)
    parser.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT)
    parser.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT)
    parser.add_argument("--map", default=None, help="Map YAML for path planning")

    args = parser.parse_args()
    if len(args.robot_ids) != len(args.domain_ids):
        parser.error("--robot-ids and --domain-ids must have same length")

    # Load map for path planning
    buffet_map = None
    map_path = args.map or os.environ.get("MRTA_MAP_PATH", "")
    if map_path and _HAS_PLANNER:
        try:
            buffet_map = load_buffet_map(map_path)
            print(f"Path planning enabled: {buffet_map.name}")
        except Exception as e:
            print(f"Path planning disabled: {e}")

    bridges: List[RobotBridge] = []
    for rid, did in zip(args.robot_ids, args.domain_ids):
        b = RobotBridge(rid, did, args.server, args.tcp_port, args.udp_port,
                        buffet_map=buffet_map)
        b.start()
        bridges.append(b)

    print(f"ROS2 bridge running ({len(bridges)} robots). Ctrl+C to stop.")

    # Watch the map YAML so admin edits propagate without a full restart.
    last_mtime = None
    if map_path and _HAS_PLANNER and os.path.isfile(map_path):
        try:
            last_mtime = os.path.getmtime(map_path)
        except OSError:
            last_mtime = None

    try:
        while True:
            time.sleep(1)
            if map_path and _HAS_PLANNER and last_mtime is not None:
                try:
                    mt = os.path.getmtime(map_path)
                except OSError:
                    continue
                if mt != last_mtime:
                    last_mtime = mt
                    try:
                        new_map = load_buffet_map(map_path)
                        for b in bridges:
                            b._buffet_map = new_map
                        print(f"[map] reloaded {map_path} ({len(new_map.graph.waypoints)} wps)")
                    except Exception as e:
                        print(f"[map] reload failed: {e}")
    except KeyboardInterrupt:
        pass
    finally:
        for b in bridges:
            b.stop()
        for b in bridges:
            b.join(timeout=3)
        print("Bridge stopped.")


if __name__ == "__main__":
    main()
