"""rostaurant_comm_node: ROS2 executor (daemon thread) + asyncio TCP/UDP on main thread."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import queue
import socket
import threading
import time
from typing import Coroutine, Optional

import rclpy
from geometry_msgs.msg import Quaternion
from nav_msgs.msg import Odometry
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from std_msgs.msg import Float32

from pinky_interfaces.msg import RobotCommand, RobotTaskStatus
from rostaurant_networking.ack_logic import _BATTERY_INIT, _decide_ack
from rostaurant_networking.robotcafe.db.v1 import robotcafe_pb2 as pb

from rostaurant_networking.tcp_client import TcpClient
from rostaurant_networking.udp_sender import UdpSender

logger = logging.getLogger(__name__)


def _resolve_robot_id() -> str:
    """Determine robot_id without any command-line arguments.

    Priority:
      1. ``ROBOT_ID`` environment variable  — useful for CI, overrides, or
         simulation where multiple nodes run on the same host.
      2. System hostname  — set once per physical device with
         ``sudo hostnamectl set-hostname pnk01``.
      3. Hard-coded fallback ``"PNK01"``.

    The returned value is always upper-cased (e.g. ``pnk02`` → ``PNK02``).
    """
    env_id = os.environ.get("ROBOT_ID", "").strip()
    if env_id:
        return env_id.upper()

    hostname = socket.gethostname().strip()
    if hostname:
        upper = hostname.upper()
        if not upper.startswith("PNK"):
            logger.warning(
                "Hostname '%s' does not start with 'pnk'. "
                "Using it as robot_id anyway. "
                "Set ROBOT_ID env var or run: sudo hostnamectl set-hostname pnkXX",
                hostname,
            )
        return upper

    logger.warning("Could not determine robot_id; falling back to 'PNK01'.")
    return "PNK01"


def _yaw_from_quat(q: Quaternion) -> float:
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


class RostaurantCommNode(Node):
    """ROS subscriptions in executor thread; schedule UDP/TCP coroutines on asyncio loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        _robot_id_default = _resolve_robot_id()
        super().__init__(f"rostaurant_comm_{_robot_id_default.lower()}")
        self._loop = loop

        self.declare_parameter("robot_id", _robot_id_default)
        self.declare_parameter("server_host", "127.0.0.1")
        self.declare_parameter("tcp_port", 9000)
        self.declare_parameter("udp_port", 9001)
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("battery_topic", "/battery")
        self.declare_parameter("task_status_topic", "/task_status")
        self.declare_parameter("robot_command_topic", "/hq/command")
        self.declare_parameter("connection_token", "")

        self._robot_id = self.get_parameter("robot_id").get_parameter_value().string_value
        self._connection_token = (
            self.get_parameter("connection_token").get_parameter_value().string_value
        )
        host = self.get_parameter("server_host").get_parameter_value().string_value
        tcp_port = int(self.get_parameter("tcp_port").get_parameter_value().integer_value)
        udp_port = int(self.get_parameter("udp_port").get_parameter_value().integer_value)

        self._udp = UdpSender(host, udp_port)
        self._tcp = TcpClient(host, tcp_port)

        self._pose_seq = 0
        self._last_pose_wall = 0.0
        self._last_battery_wall = 0.0
        self._tcp_seq = 0
        self._pending_cmd_id: str = ""       # 마지막으로 받은 Command의 cmd_id (ACK 전 보관)
        self._pending_cmd_type: int = 0      # 마지막 커맨드의 CommandType 값
        self._pending_task_action: int = 0   # 마지막 태스크별 액션 값
        self._latest_battery: int = _BATTERY_INIT

        self._cmd_queue: queue.Queue[RobotCommand] = queue.Queue(maxsize=200)

        qos_cmd = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST)
        cmd_topic = self.get_parameter("robot_command_topic").get_parameter_value().string_value
        self._cmd_pub = self.create_publisher(RobotCommand, cmd_topic, qos_cmd)

        odom_topic = self.get_parameter("odom_topic").get_parameter_value().string_value
        battery_topic = self.get_parameter("battery_topic").get_parameter_value().string_value
        task_topic = self.get_parameter("task_status_topic").get_parameter_value().string_value

        self.create_subscription(Odometry, odom_topic, self._on_odom, qos_profile_sensor_data)
        self.create_subscription(Float32, battery_topic, self._on_battery, qos_profile_sensor_data)
        self.create_subscription(RobotTaskStatus, task_topic, self._on_task_status, qos_cmd)

        self.create_timer(0.05, self._drain_command_queue)

        logger.info(
            "RostaurantCommNode robot_id=%s server=%s tcp=%s udp=%s",
            self._robot_id,
            host,
            tcp_port,
            udp_port,
        )

    def _schedule(self, coro: Coroutine[object, object, object]) -> None:
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _drain_command_queue(self) -> None:
        while True:
            try:
                msg = self._cmd_queue.get_nowait()
            except queue.Empty:
                return
            self._cmd_pub.publish(msg)

    def _on_odom(self, msg: Odometry) -> None:
        now = time.monotonic()
        if now - self._last_pose_wall < 0.09:
            return
        self._last_pose_wall = now
        self._pose_seq = (self._pose_seq + 1) % (2**32)
        pose = pb.TelemetryPose(
            robot_id=self._robot_id,
            seq=self._pose_seq,
            x=msg.pose.pose.position.x,
            y=msg.pose.pose.position.y,
            theta=_yaw_from_quat(msg.pose.pose.orientation),
            linear_x=msg.twist.twist.linear.x,
            angular_z=msg.twist.twist.angular.z,
        )
        pose.timestamp.FromMilliseconds(int(time.time() * 1000))
        pkt = pb.UdpTelemetryPacket(robot_id=self._robot_id, pose=pose)
        self._schedule(self._udp.send_packet(pkt))

    def _on_battery(self, msg: Float32) -> None:
        self._latest_battery = int(round(float(msg.data)))
        now = time.monotonic()
        if now - self._last_battery_wall < 0.95:
            return
        self._last_battery_wall = now
        st = pb.TelemetryState(
            robot_id=self._robot_id,
            battery_percent=self._latest_battery,
        )
        st.timestamp.FromMilliseconds(int(time.time() * 1000))
        pkt = pb.UdpTelemetryPacket(robot_id=self._robot_id, state=st)
        self._schedule(self._udp.send_packet(pkt))

    def _on_task_status(self, msg: RobotTaskStatus) -> None:
        fsm = int(msg.fsm_state)

        # ── 1. StatusReport 전송 ────────────────────────────────────
        sr = pb.StatusReport(
            robot_id=msg.robot_id or self._robot_id,
            robot_status=int(msg.robot_status),
            fsm_state=fsm,
            current_task=msg.current_task,
            battery=self._latest_battery,
            last_error=int(msg.last_error),
        )
        sr.reported_at.FromMilliseconds(int(time.time() * 1000))

        async def _send_status() -> None:
            self._tcp_seq += 1
            pkt = pb.TcpPacket(robot_id=self._robot_id, seq=self._tcp_seq, status_payload=sr)
            await self._tcp.send_packet(pkt)

        self._schedule(_send_status())

        # ── 2. TaskEvent 전송 (도착/특수 이벤트) ────────────────────
        event_val = _decide_task_event(
            fsm_state=fsm,
            cmd_type=self._pending_cmd_type,
            task_action=self._pending_task_action,
            event_type_override=int(msg.event_type),
        )
        if event_val is not None:
            task_id = msg.current_task
            ev_val = event_val

            async def _send_event(tid: str = task_id, ev: int = ev_val) -> None:
                event = pb.TaskEvent(
                    robot_id=self._robot_id,
                    task_id=tid,
                    event_type=ev,
                )
                event.occurred_at.FromMilliseconds(int(time.time() * 1000))
                self._tcp_seq += 1
                pkt = pb.TcpPacket(robot_id=self._robot_id, seq=self._tcp_seq, task_event=event)
                await self._tcp.send_packet(pkt)
                logger.info(
                    "TaskEvent sent event=%s task=%s",
                    pb.TaskEventType.Name(ev),
                    tid,
                )

            self._schedule(_send_event())

        # ── 3. CommandAck 전송 (FSM_ARRIVED / FSM_NAV_FAILED) ───────
        ack_status = _decide_ack(fsm, self._pending_cmd_id)
        if ack_status is not None:
            cmd_id = self._pending_cmd_id
            self._pending_cmd_id = ""
            self._pending_cmd_type = 0
            self._pending_task_action = 0

            async def _send_ack(cid: str = cmd_id, ast: int = ack_status) -> None:
                ack = pb.CommandAck(
                    cmd_id=cid,
                    robot_id=self._robot_id,
                    status=ast,
                )
                ack.acked_at.FromMilliseconds(int(time.time() * 1000))
                self._tcp_seq += 1
                pkt = pb.TcpPacket(robot_id=self._robot_id, seq=self._tcp_seq, ack_payload=ack)
                await self._tcp.send_packet(pkt)
                logger.info("CommandAck status=%s cmd_id=%s", pb.AckStatus.Name(ast), cid)

            self._schedule(_send_ack())

    # ── 커맨드 큐 진입점 ─────────────────────────────────────────────

    def enqueue_command(self, cmd: pb.Command) -> None:
        """일반 Command (MOVE_TO / CANCEL 등) 처리."""
        self._pending_cmd_id = cmd.cmd_id
        self._pending_cmd_type = int(cmd.command)
        self._pending_task_action = 0
        self._send_accepted_ack(cmd.cmd_id)

        # cmd.target_id に string command 이름을 담아서 전달
        # (예: "MoveToKitchen", "FollowRequest", "CollectRequest", "MoveToRequester")
        ros_cmd = RobotCommand(
            cmd_id=cmd.cmd_id,
            task_id=cmd.task_id,
            robot_id=cmd.robot_id,
            command=int(cmd.command),
            target_id=cmd.target_id,
            target_x=cmd.target_x,
            target_y=cmd.target_y,
            target_theta=cmd.target_theta,
        )
        try:
            self._cmd_queue.put_nowait(ros_cmd)
        except queue.Full:
            logger.error("Command queue full; dropping cmd_id=%s", ros_cmd.cmd_id)


async def _network_loop(node: RostaurantCommNode) -> None:
    udp = node._udp
    tcp = node._tcp
    robot_id = node._robot_id

    await udp.start()

    async def on_connected(_: TcpClient) -> None:
        node._tcp_seq += 1
        hb = pb.Heartbeat(robot_id=robot_id, timestamp=time.time_ns())
        tok = (node._connection_token or "").strip()
        if tok:
            hb.connection_token = tok
        pkt = pb.TcpPacket(
            robot_id=robot_id,
            seq=node._tcp_seq,
            heartbeat=hb,
        )
        await tcp.send_packet(pkt)

    async def on_packet(pkt: pb.TcpPacket) -> None:
        if pkt.HasField("cmd_payload"):
            node.enqueue_command(pkt.cmd_payload)
        elif pkt.HasField("follow_cmd"):
            node.enqueue_follow_command(pkt.follow_cmd)
        elif pkt.HasField("collect_cmd"):
            node.enqueue_collect_command(pkt.collect_cmd)
        elif pkt.HasField("delivery_cmd"):
            node.enqueue_delivery_command(pkt.delivery_cmd)
        elif pkt.HasField("guidance_cmd"):
            node.enqueue_guidance_command(pkt.guidance_cmd)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(2.0)
            if not tcp.connected:
                continue
            node._tcp_seq += 1
            hb = pb.Heartbeat(robot_id=robot_id, timestamp=time.time_ns())
            tok = (node._connection_token or "").strip()
            if tok:
                hb.connection_token = tok
            pkt = pb.TcpPacket(robot_id=robot_id, seq=node._tcp_seq, heartbeat=hb)
            try:
                await tcp.send_packet(pkt)
            except Exception as e:  # noqa: BLE001
                logger.debug("heartbeat send: %s", e)

    hb_task = asyncio.create_task(heartbeat(), name="mrta-heartbeat")
    try:
        await asyncio.gather(tcp.run(on_packet, on_connected), hb_task)
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except asyncio.CancelledError:
            pass
        udp.close()


def main(args: Optional[list[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO)
    rclpy.init(args=args)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    holder: dict[str, RostaurantCommNode] = {}

    def ros_thread() -> None:
        node = RostaurantCommNode(loop)
        holder["node"] = node
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        try:
            executor.spin()
        finally:
            executor.shutdown()
            node.destroy_node()

    th = threading.Thread(target=ros_thread, daemon=True, name="ros-exec")
    th.start()
    while "node" not in holder:
        time.sleep(0.01)
    node = holder["node"]

    try:
        loop.run_until_complete(_network_loop(node))
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        node._udp.close()
        rclpy.shutdown()
        th.join(timeout=3.0)


if __name__ == "__main__":
    main()
