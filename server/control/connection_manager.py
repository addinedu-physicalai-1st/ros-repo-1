"""Robot TCP sessions, telemetry cache (memory only), heartbeat bookkeeping."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import aiosqlite

from db import Database, _ts_now_ms
from robotcafe.db.v1 import robotcafe_pb2 as pb
from ws_broker import WSBroker

logger = logging.getLogger(__name__)

TCP_MAGIC = 0xAABBCCDD
UDP_MAGIC = 0xDDCCBBAA


def encode_tcp_frame(packet: pb.TcpPacket) -> bytes:
    body = packet.SerializeToString()
    payload = TCP_MAGIC.to_bytes(4, "big", signed=False) + body
    length = len(payload)
    return length.to_bytes(4, "big", signed=False) + payload


@dataclass
class RobotSession:
    robot_id: str
    writer: asyncio.StreamWriter
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    seq: int = 0
    last_heartbeat_mono: float = field(default_factory=time.monotonic)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


class TelemetryCache:
    """Latest-only pose/state per robot_id with monotonic merge."""

    def __init__(self) -> None:
        self._pose: dict[str, pb.TelemetryPose] = {}
        self._state: dict[str, pb.TelemetryState] = {}
        self._lock = asyncio.Lock()

    def _pose_ts_ms(self, p: pb.TelemetryPose) -> int:
        return int(p.timestamp.ToMilliseconds())

    def _state_ts_ms(self, s: pb.TelemetryState) -> int:
        return int(s.timestamp.ToMilliseconds())

    async def apply_udp_packet(self, pkt: pb.UdpTelemetryPacket) -> None:
        rid = pkt.robot_id
        async with self._lock:
            which = pkt.WhichOneof("telemetry")
            if which == "pose":
                pose = pkt.pose
                cur = self._pose.get(rid)
                if cur is None:
                    self._pose[rid] = pose
                    return
                if pose.seq > cur.seq:
                    self._pose[rid] = pose
                    return
                if pose.seq == cur.seq and self._pose_ts_ms(pose) > self._pose_ts_ms(cur):
                    self._pose[rid] = pose
                    return
            elif which == "state":
                st = pkt.state
                cur_s = self._state.get(rid)
                if cur_s is None:
                    self._state[rid] = st
                    return
                if self._state_ts_ms(st) > self._state_ts_ms(cur_s):
                    self._state[rid] = st

    async def get_pose(self, robot_id: str) -> Optional[pb.TelemetryPose]:
        async with self._lock:
            p = self._pose.get(robot_id)
            return p

    async def snapshot_poses(self) -> dict[str, pb.TelemetryPose]:
        async with self._lock:
            return dict(self._pose)


class ConnectionManager:
    def __init__(
        self,
        db: Database,
        get_conn: Callable[[], Awaitable[aiosqlite.Connection]],
        db_lock: asyncio.Lock,
        broker: Optional[WSBroker] = None,
    ) -> None:
        self._db = db
        self._get_conn = get_conn
        self._db_lock = db_lock
        self._broker = broker
        self._sessions: dict[str, RobotSession] = {}
        self._sessions_lock = asyncio.Lock()
        self.telemetry = TelemetryCache()

    async def register_session(self, robot_id: str, writer: asyncio.StreamWriter) -> RobotSession:
        async with self._sessions_lock:
            old = self._sessions.pop(robot_id, None)
            if old and not old.writer.is_closing():
                old.writer.close()
                try:
                    await old.writer.wait_closed()
                except Exception as e:  # noqa: BLE001
                    logger.debug("wait_closed old writer: %s", e)
            sess = RobotSession(robot_id=robot_id, writer=writer)
            sess.last_heartbeat_mono = time.monotonic()
            self._sessions[robot_id] = sess
            logger.info("Registered TCP session for %s", robot_id)
            return sess

    async def unregister_session(self, robot_id: str, writer: asyncio.StreamWriter) -> None:
        async with self._sessions_lock:
            cur = self._sessions.get(robot_id)
            if cur and cur.writer is writer:
                self._sessions.pop(robot_id, None)
                logger.info("Unregistered TCP session for %s", robot_id)

    async def get_session(self, robot_id: str) -> Optional[RobotSession]:
        async with self._sessions_lock:
            return self._sessions.get(robot_id)

    async def get_all_session_ids(self) -> list[str]:
        async with self._sessions_lock:
            return list(self._sessions.keys())

    async def touch_heartbeat(self, robot_id: str) -> None:
        async with self._sessions_lock:
            s = self._sessions.get(robot_id)
            if s:
                s.last_heartbeat_mono = time.monotonic()

    async def send_command_packet(self, robot_id: str, packet: pb.TcpPacket) -> None:
        sess = await self.get_session(robot_id)
        if sess is None:
            raise RuntimeError(f"robot {robot_id} not connected")
        data = encode_tcp_frame(packet)
        async with sess.write_lock:
            sess.writer.write(data)
            await sess.writer.drain()

    async def handle_tcp_packet(self, packet: pb.TcpPacket, session: RobotSession) -> None:
        rid = packet.robot_id or session.robot_id
        now_ms = _ts_now_ms()

        if packet.HasField("heartbeat"):
            hb = packet.heartbeat
            async with self._db_lock:
                conn = await self._get_conn()
                await self._db.upsert_robot_heartbeat(conn, robot_id=hb.robot_id or rid, last_seen_ms=now_ms)
            if self._broker:
                await self._broker.broadcast({
                    "event": "heartbeat",
                    "robot_id": hb.robot_id or rid,
                    "timestamp_ms": now_ms,
                })
        elif packet.HasField("status_payload"):
            sr = packet.status_payload
            async with self._db_lock:
                conn = await self._get_conn()
                await self._db.upsert_robot_from_status(
                    conn,
                    robot_id=sr.robot_id or rid,
                    status=int(sr.robot_status),
                    battery=sr.battery,
                    last_seen_ms=now_ms,
                    current_task_id=sr.current_task,
                    fsm_state=int(sr.fsm_state),
                )
            if self._broker:
                await self._broker.broadcast({
                    "event": "status",
                    "robot_id": sr.robot_id or rid,
                    "robot_status": int(sr.robot_status),
                    "fsm_state": int(sr.fsm_state),
                    "current_task": sr.current_task,
                    "battery": sr.battery,
                    "timestamp_ms": now_ms,
                })
        elif packet.HasField("ack_payload"):
            await self._handle_command_ack(packet.ack_payload)
        elif packet.HasField("cmd_payload"):
            logger.warning("Ignoring unexpected cmd_payload from robot %s", rid)

        await self.touch_heartbeat(session.robot_id)

    async def _handle_command_ack(self, ack: pb.CommandAck) -> None:
        now_ms = _ts_now_ms()
        async with self._db_lock:
            conn = await self._get_conn()  # type: ignore[misc]
            row = await self._db.get_command(conn, ack.cmd_id)
            if row is None:
                logger.warning("CommandAck for unknown cmd_id=%s", ack.cmd_id)
                return
            task_id = str(row["task_id"])
            st = int(ack.status)
            if st == int(pb.AckStatus.ACCEPTED):
                await self._db.update_command_status(
                    conn, cmd_id=ack.cmd_id, status=int(pb.CommandStatus.ACKED), acked_at_ms=now_ms
                )
            elif st == int(pb.AckStatus.REJECTED):
                await self._db.update_command_status(
                    conn, cmd_id=ack.cmd_id, status=int(pb.CommandStatus.CMD_FAILED), acked_at_ms=now_ms
                )
            elif st == int(pb.AckStatus.EXECUTED):
                await self._db.update_command_status(
                    conn, cmd_id=ack.cmd_id, status=int(pb.CommandStatus.ACKED), acked_at_ms=now_ms
                )
                await self._db.update_task_status(
                    conn, task_id=task_id, status=int(pb.TaskStatus.COMPLETED), completed=True
                )
            elif st in (int(pb.AckStatus.ACK_FAILED),):
                await self._db.update_command_status(
                    conn, cmd_id=ack.cmd_id, status=int(pb.CommandStatus.CMD_FAILED), acked_at_ms=now_ms
                )
                await self._db.update_task_status(
                    conn, task_id=task_id, status=int(pb.TaskStatus.FAILED), completed=True
                )
        if self._broker:
            await self._broker.broadcast({
                "event": "command_ack",
                "cmd_id": ack.cmd_id,
                "robot_id": ack.robot_id,
                "ack_status": int(ack.status),
                "task_id": task_id,
                "timestamp_ms": now_ms,
            })

    async def heartbeat_watchdog(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(1.0)
            now = time.monotonic()
            async with self._sessions_lock:
                items = list(self._sessions.items())
            for rid, sess in items:
                if now - sess.last_heartbeat_mono > 5.0:
                    logger.warning("Heartbeat timeout for %s — marking OFFLINE", rid)
                    async with self._db_lock:
                        conn = await self._get_conn()
                        await self._db.mark_robot_offline(conn, rid)
                    await self.unregister_session(rid, sess.writer)
                    try:
                        sess.writer.close()
                        await sess.writer.wait_closed()
                    except Exception as e:  # noqa: BLE001
                        logger.debug("close timed-out session: %s", e)
