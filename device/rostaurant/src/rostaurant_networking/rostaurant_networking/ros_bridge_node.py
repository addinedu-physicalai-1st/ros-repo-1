"""rostaurant_comm_node: ROS2 executor (daemon thread) + asyncio TCP/UDP on main thread."""

from __future__ import annotations

import asyncio
import logging
import math
import queue
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
from rostaurant_networking.robotcafe.db.v1 import robotcafe_pb2 as pb

from rostaurant_networking.tcp_client import TcpClient
from rostaurant_networking.udp_sender import UdpSender

logger = logging.getLogger(__name__)


def _yaw_from_quat(q: Quaternion) -> float:
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


class RostaurantCommNode(Node):
    """ROS subscriptions in executor thread; schedule UDP/TCP coroutines on asyncio loop."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__("rostaurant_comm_node")
        self._loop = loop

        self.declare_parameter("robot_id", "PNK01")
        self.declare_parameter("server_host", "127.0.0.1")
        self.declare_parameter("tcp_port", 9000)
        self.declare_parameter("udp_port", 9001)
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("battery_topic", "/battery")
        self.declare_parameter("task_status_topic", "/task_status")
        self.declare_parameter("robot_command_topic", "/robot_command")

        self._robot_id = self.get_parameter("robot_id").get_parameter_value().string_value
        host = self.get_parameter("server_host").get_parameter_value().string_value
        tcp_port = int(self.get_parameter("tcp_port").get_parameter_value().integer_value)
        udp_port = int(self.get_parameter("udp_port").get_parameter_value().integer_value)

        self._udp = UdpSender(host, udp_port)
        self._tcp = TcpClient(host, tcp_port)

        self._pose_seq = 0
        self._last_pose_wall = 0.0
        self._last_battery_wall = 0.0
        self._tcp_seq = 0

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
        now = time.monotonic()
        if now - self._last_battery_wall < 0.95:
            return
        self._last_battery_wall = now
        st = pb.TelemetryState(
            robot_id=self._robot_id,
            battery_percent=int(round(float(msg.data))),
            current_state=pb.RobotStatus.IDLE,
            current_fsm=pb.FsmState.FSM_IDLE,
            current_step="",
            task_id="",
        )
        st.timestamp.FromMilliseconds(int(time.time() * 1000))
        pkt = pb.UdpTelemetryPacket(robot_id=self._robot_id, state=st)
        self._schedule(self._udp.send_packet(pkt))

    def _on_task_status(self, msg: RobotTaskStatus) -> None:
        sr = pb.StatusReport(
            robot_id=msg.robot_id or self._robot_id,
            robot_status=int(msg.robot_status),
            fsm_state=int(msg.fsm_state),
            current_task=msg.current_task,
            battery=int(msg.battery),
            last_error=int(msg.last_error),
        )
        sr.reported_at.FromMilliseconds(int(time.time() * 1000))

        async def _send() -> None:
            self._tcp_seq += 1
            pkt = pb.TcpPacket(robot_id=self._robot_id, seq=self._tcp_seq, status_payload=sr)
            await self._tcp.send_packet(pkt)

        self._schedule(_send())

    def enqueue_command(self, cmd: pb.Command) -> None:
        ros_cmd = RobotCommand(
            cmd_id=cmd.cmd_id,
            task_id=cmd.task_id,
            robot_id=cmd.robot_id,
            command=int(cmd.command),
            target_id=cmd.target_id,
        )
        try:
            self._cmd_queue.put_nowait(ros_cmd)
        except queue.Full:
            logger.error("Command queue full; dropping cmd_id=%s", cmd.cmd_id)


async def _network_loop(node: RostaurantCommNode) -> None:
    udp = node._udp
    tcp = node._tcp
    robot_id = node._robot_id

    await udp.start()

    async def on_connected(_: TcpClient) -> None:
        node._tcp_seq += 1
        pkt = pb.TcpPacket(
            robot_id=robot_id,
            seq=node._tcp_seq,
            heartbeat=pb.Heartbeat(robot_id=robot_id, timestamp=time.time_ns()),
        )
        await tcp.send_packet(pkt)

    async def on_packet(pkt: pb.TcpPacket) -> None:
        if pkt.HasField("cmd_payload"):
            node.enqueue_command(pkt.cmd_payload)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(2.0)
            if not tcp.connected:
                continue
            node._tcp_seq += 1
            hb = pb.Heartbeat(robot_id=robot_id, timestamp=time.time_ns())
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
