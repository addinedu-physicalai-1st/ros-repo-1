"""UDP telemetry receiver (asyncio DatagramProtocol, non-blocking)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from connection_manager import UDP_MAGIC, ConnectionManager
from robotcafe.db.v1 import robotcafe_pb2 as pb

logger = logging.getLogger(__name__)


class UdpTelemetryProtocol(asyncio.DatagramProtocol):
    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager
        self.transport: Optional[asyncio.DatagramTransport] = None
        self._require_tcp_session = (
            os.environ.get("MRTA_UDP_REQUIRE_ACTIVE_SESSION", "").strip() == "1"
        )

    def connection_made(self, transport: asyncio.BaseTransport) -> None:  # type: ignore[override]
        self.transport = transport  # type: ignore[assignment]
        logger.info("UDP telemetry endpoint ready")

    def datagram_received(self, data: bytes, addr: tuple[str | object, int]) -> None:  # type: ignore[override]
        asyncio.create_task(self._handle_datagram(data, addr))

    async def _handle_datagram(self, data: bytes, addr: tuple[str | object, int]) -> None:
        if len(data) < 4:
            logger.debug("Short UDP from %s", addr)
            return
        magic = int.from_bytes(data[:4], "big", signed=False)
        if magic != UDP_MAGIC:
            logger.debug("Bad UDP magic from %s: %#x", addr, magic)
            return
        pkt = pb.UdpTelemetryPacket()
        try:
            pkt.ParseFromString(data[4:])
        except Exception as e:  # noqa: BLE001
            logger.warning("UDP parse error from %s: %s", addr, e)
            return
        if self._require_tcp_session:
            rid = pkt.robot_id
            if await self._manager.get_session(rid) is None:
                logger.debug("UDP dropped from %s: no active TCP session for %s", addr, rid)
                return
        await self._manager.telemetry.apply_udp_packet(pkt)

    def error_received(self, exc: Exception) -> None:  # type: ignore[override]
        logger.error("UDP error_received: %s", exc)


async def start_udp_receiver(host: str, port: int, manager: ConnectionManager) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: UdpTelemetryProtocol(manager),
        local_addr=(host, port),
    )
    logger.info("UDP receiver bound on %s:%s", host, port)
    return transport  # type: ignore[return-value]
