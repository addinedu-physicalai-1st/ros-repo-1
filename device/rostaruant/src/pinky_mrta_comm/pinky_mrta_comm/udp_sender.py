"""UDP sender: [UDP_MAGIC][UdpTelemetryPacket] datagrams."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pinky_mrta_comm.robotcafe.db.v1 import robotcafe_pb2 as pb

logger = logging.getLogger(__name__)

UDP_MAGIC = 0xDDCCBBAA


class UdpSender:
    """Connected-mode UDP socket to a fixed remote (host, port)."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=(self._host, self._port),
        )
        logger.info("UDP endpoint ready toward %s:%s", self._host, self._port)

    async def send_packet(self, packet: pb.UdpTelemetryPacket) -> None:
        data = UDP_MAGIC.to_bytes(4, "big", signed=False) + packet.SerializeToString()
        async with self._lock:
            if self._transport is None:
                raise RuntimeError("UDP not started")
            self._transport.sendto(data)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
