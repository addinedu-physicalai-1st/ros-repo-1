"""TCP server: length-prefixed frames with external TCP_MAGIC + TcpPacket."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import struct
from typing import Optional

from auth import hash_api_key
from connection_manager import TCP_MAGIC, ConnectionManager, RobotSession
from robotcafe.db.v1 import robotcafe_pb2 as pb

logger = logging.getLogger(__name__)

# Hard ceiling (bytes) for length-prefix field; configurable default via MRTA_MAX_TCP_FRAME_BYTES.
_TCP_LENGTH_ABS_MAX = 16 * 1024 * 1024
_TCP_LENGTH_MIN = 4096


def _effective_max_tcp_frame_bytes(requested: int) -> int:
    return max(_TCP_LENGTH_MIN, min(int(requested), _TCP_LENGTH_ABS_MAX))


class _TcpBuffer:
    def __init__(self, max_frame_bytes: int) -> None:
        self._buf = bytearray()
        self._max_frame_bytes = max_frame_bytes

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def extract_packets(self) -> list[pb.TcpPacket]:
        out: list[pb.TcpPacket] = []
        while True:
            if len(self._buf) < 4:
                break
            (length,) = struct.unpack_from("!I", self._buf, 0)
            if length > self._max_frame_bytes:
                raise ValueError(f"TCP frame too large: {length} (max {self._max_frame_bytes})")
            if len(self._buf) < 4 + length:
                break
            payload = memoryview(self._buf)[4 : 4 + length]
            del self._buf[: 4 + length]
            if length < 4:
                raise ValueError("TCP payload too short for magic")
            magic = int.from_bytes(payload[:4], "big", signed=False)
            if magic != TCP_MAGIC:
                raise ValueError(f"Bad TCP magic: {magic:#x}")
            pkt = pb.TcpPacket()
            pkt.ParseFromString(payload[4:].tobytes())
            out.append(pkt)
        return out


def _extract_robot_id(packet: pb.TcpPacket) -> str:
    if packet.HasField("heartbeat"):
        return packet.heartbeat.robot_id or packet.robot_id
    if packet.HasField("status_payload"):
        return packet.status_payload.robot_id or packet.robot_id
    return packet.robot_id


async def _verify_robot_connection_token(
    manager: ConnectionManager,
    robot_id: str,
    packet: pb.TcpPacket,
    peer: object,
) -> bool:
    if os.environ.get("MRTA_REQUIRE_ROBOT_TOKEN", "").strip() != "1":
        return True
    if packet.HasField("status_payload"):
        logger.warning(
            "MRTA_REQUIRE_ROBOT_TOKEN: first packet must be Heartbeat with connection_token (not StatusReport) from %s",
            peer,
        )
        return False
    if not packet.HasField("heartbeat"):
        return False
    token = (packet.heartbeat.connection_token or "").strip()
    if not token:
        logger.warning("Missing connection_token in Heartbeat from %s robot_id=%s", peer, robot_id)
        return False
    async with manager._db_lock:
        conn = await manager._get_conn()
        stored = await manager._db.get_robot_connection_token_hash(conn, robot_id)
    if not stored:
        logger.warning("No connection_token_hash configured for robot_id=%s — refusing TCP", robot_id)
        return False
    return secrets.compare_digest(hash_api_key(token), stored)


async def _client_loop(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    manager: ConnectionManager,
    *,
    max_frame_bytes: int,
) -> None:
    addr = writer.get_extra_info("peername")
    buf = _TcpBuffer(max_frame_bytes=max_frame_bytes)
    session: Optional[RobotSession] = None
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            buf.feed(chunk)
            try:
                packets = buf.extract_packets()
            except Exception as e:  # noqa: BLE001
                logger.error("TCP framing error from %s: %s", addr, e)
                break
            for packet in packets:
                rid = _extract_robot_id(packet)
                if session is None:
                    if not (packet.HasField("heartbeat") or packet.HasField("status_payload")):
                        logger.warning("First TCP message must be Heartbeat or StatusReport from %s", addr)
                        return
                    if not rid:
                        logger.warning("Missing robot_id on first message from %s", addr)
                        return
                    if not await _verify_robot_connection_token(manager, rid, packet, addr):
                        logger.warning("TCP session rejected (auth) robot_id=%s peer=%s", rid, addr)
                        try:
                            writer.close()
                            await writer.wait_closed()
                        except Exception as e:  # noqa: BLE001
                            logger.debug("close after auth reject: %s", e)
                        return
                    session = await manager.register_session(rid, writer)
                assert session is not None
                await manager.handle_tcp_packet(packet, session)
    finally:
        if session is not None:
            await manager.unregister_session(session.robot_id, writer)  # type: ignore[attr-defined]
        try:
            writer.close()
            await writer.wait_closed()
        except Exception as e:  # noqa: BLE001
            logger.debug("client close: %s", e)
        logger.info("TCP client disconnected %s", addr)


async def start_tcp_server(
    host: str,
    port: int,
    manager: ConnectionManager,
    *,
    max_frame_bytes: int = 2 * 1024 * 1024,
) -> asyncio.AbstractServer:
    cap = _effective_max_tcp_frame_bytes(max_frame_bytes)

    async def _cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _client_loop(reader, writer, manager, max_frame_bytes=cap)

    server = await asyncio.start_server(_cb, host=host, port=port)
    logger.info("TCP gateway listening on %s:%s", host, port)
    return server
