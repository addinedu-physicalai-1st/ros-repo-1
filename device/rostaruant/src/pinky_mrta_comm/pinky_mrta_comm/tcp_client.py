"""TCP client: length-prefixed [magic|TcpPacket], reconnect with exponential backoff."""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Awaitable, Callable, Optional

from pinky_mrta_comm.robotcafe.db.v1 import robotcafe_pb2 as pb

logger = logging.getLogger(__name__)

TCP_MAGIC = 0xAABBCCDD


class TcpClient:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._writer: Optional[asyncio.StreamWriter] = None
        self._write_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        w = self._writer
        return w is not None and not w.is_closing()

    async def send_packet(self, packet: pb.TcpPacket) -> None:
        body = packet.SerializeToString()
        payload = TCP_MAGIC.to_bytes(4, "big", signed=False) + body
        frame = len(payload).to_bytes(4, "big", signed=False) + payload
        async with self._write_lock:
            if self._writer is None or self._writer.is_closing():
                raise RuntimeError("TCP not connected")
            self._writer.write(frame)
            await self._writer.drain()

    async def run(
        self,
        on_packet: Callable[[pb.TcpPacket], Awaitable[None]],
        on_connected: Callable[["TcpClient"], Awaitable[None]],
    ) -> None:
        delay = 1.0
        while True:
            writer: Optional[asyncio.StreamWriter] = None
            try:
                reader, writer = await asyncio.open_connection(self._host, self._port)
                self._writer = writer
                delay = 1.0
                logger.info("TCP connected to %s:%s", self._host, self._port)
                await on_connected(self)
                await self._read_loop(reader, on_packet)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("TCP session error: %s", e)
            finally:
                self._writer = None
                w = writer
                if w is not None and not w.is_closing():
                    w.close()
                    try:
                        await w.wait_closed()
                    except Exception as e:  # noqa: BLE001
                        logger.debug("wait_closed: %s", e)
            logger.info("TCP reconnect in %.1fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2.0, 30.0)

    async def _read_loop(
        self,
        reader: asyncio.StreamReader,
        on_packet: Callable[[pb.TcpPacket], Awaitable[None]],
    ) -> None:
        buf = bytearray()
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                return
            buf.extend(chunk)
            while len(buf) >= 4:
                (length,) = struct.unpack_from("!I", buf, 0)
                if length > 16 * 1024 * 1024:
                    raise ValueError(f"frame too large: {length}")
                if len(buf) < 4 + length:
                    break
                payload = bytes(memoryview(buf)[4 : 4 + length])
                del buf[: 4 + length]
                if length < 4:
                    raise ValueError("payload too short")
                magic = int.from_bytes(payload[:4], "big", signed=False)
                if magic != TCP_MAGIC:
                    raise ValueError(f"bad TCP magic {magic:#x}")
                pkt = pb.TcpPacket()
                pkt.ParseFromString(payload[4:])
                await on_packet(pkt)
