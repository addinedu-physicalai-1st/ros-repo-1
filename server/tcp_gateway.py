"""TCP server: length-prefixed frames with external TCP_MAGIC + TcpPacket."""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Optional

from connection_manager import TCP_MAGIC, ConnectionManager, RobotSession
from robotcafe.db.v1 import robotcafe_pb2 as pb

logger = logging.getLogger(__name__)


class _TcpBuffer:
    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def extract_packets(self) -> list[pb.TcpPacket]:
        out: list[pb.TcpPacket] = []
        while True:
            if len(self._buf) < 4:
                break
            (length,) = struct.unpack_from("!I", self._buf, 0)
            if length > 16 * 1024 * 1024:
                raise ValueError(f"TCP frame too large: {length}")
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


async def _client_loop(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    manager: ConnectionManager,
) -> None:
    addr = writer.get_extra_info("peername")
    buf = _TcpBuffer()
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
) -> asyncio.AbstractServer:
    async def _cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _client_loop(reader, writer, manager)

    server = await asyncio.start_server(_cb, host=host, port=port)
    logger.info("TCP gateway listening on %s:%s", host, port)
    return server
