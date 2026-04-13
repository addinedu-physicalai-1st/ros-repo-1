"""WebSocket broker: fan-out telemetry/status events to connected web-server clients."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSBroker:
    """Thread-safe fan-out broadcaster for server-sent real-time events.

    Designed for a small number of internal subscribers (typically one: the
    web server's relay task).  Each connected WebSocket receives every message
    published via :meth:`broadcast`.
    """

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.append(ws)
        logger.info("WSBroker: client connected (%d total)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients = [c for c in self._clients if c is not ws]
        logger.info("WSBroker: client disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, data: dict[str, Any]) -> None:
        text = json.dumps(data, ensure_ascii=False)
        async with self._lock:
            clients = list(self._clients)
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(text)
            except Exception as e:  # noqa: BLE001
                logger.debug("WSBroker send failed: %s", e)
                dead.append(ws)
        if dead:
            async with self._lock:
                self._clients = [c for c in self._clients if c not in dead]
