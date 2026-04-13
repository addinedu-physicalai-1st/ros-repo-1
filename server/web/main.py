"""Web server: serves static UI pages and proxies REST/WebSocket to the control server.

Architecture
────────────
  Browser → [POST /api/*]           → web server → control REST (Bearer)
  Browser ← [GET  /ws]    WebSocket ← web server ← control /ws/stream

Environment variables
─────────────────────
  CONTROL_BASE_URL      HTTP base URL of the control server  (default: http://localhost:8000)
  CONTROL_WS_URL        WS  URL for the /ws/stream endpoint  (default: ws://localhost:8000/ws/stream)
  CONTROL_SERVICE_KEY   API key (ADMIN) used to call the control server
  WEB_PORT              Port this server listens on          (default: 3000)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

CONTROL_BASE_URL = os.environ.get("CONTROL_BASE_URL", "http://localhost:8000").rstrip("/")
CONTROL_WS_URL   = os.environ.get("CONTROL_WS_URL",   "ws://localhost:8000/ws/stream")
SERVICE_KEY      = os.environ.get("CONTROL_SERVICE_KEY", "")

# ── WebSocket fan-out to browser clients ─────────────────────────────────────

_browser_clients: list[WebSocket] = []
_browser_lock = asyncio.Lock()


async def _add_browser(ws: WebSocket) -> None:
    await ws.accept()
    async with _browser_lock:
        _browser_clients.append(ws)
    logger.info("Browser WS connected (%d total)", len(_browser_clients))


async def _remove_browser(ws: WebSocket) -> None:
    async with _browser_lock:
        _browser_clients[:] = [c for c in _browser_clients if c is not ws]
    logger.info("Browser WS disconnected (%d remaining)", len(_browser_clients))


async def _broadcast_to_browsers(text: str) -> None:
    async with _browser_lock:
        clients = list(_browser_clients)
    dead: list[WebSocket] = []
    for ws in clients:
        try:
            await ws.send_text(text)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    if dead:
        async with _browser_lock:
            _browser_clients[:] = [c for c in _browser_clients if c not in dead]


# ── Control server WebSocket relay task ──────────────────────────────────────

async def _control_relay_loop() -> None:
    """Connects to control /ws/stream and relays messages to browser clients."""
    ws_url = CONTROL_WS_URL
    if SERVICE_KEY:
        ws_url = f"{ws_url}?token={SERVICE_KEY}"

    retry_delay = 2.0
    while True:
        try:
            logger.info("Connecting to control WS: %s", CONTROL_WS_URL)
            async with websockets.connect(ws_url) as ws:
                retry_delay = 2.0
                logger.info("Control WS relay established")
                async for message in ws:
                    if isinstance(message, bytes):
                        message = message.decode()
                    await _broadcast_to_browsers(message)
        except asyncio.CancelledError:
            logger.info("Control WS relay task cancelled")
            return
        except Exception as e:  # noqa: BLE001
            logger.warning("Control WS relay lost (%s), retry in %.1fs", e, retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5, 30.0)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    relay_task = asyncio.create_task(_control_relay_loop(), name="web-control-relay")
    app.state.relay_task = relay_task
    yield
    relay_task.cancel()
    try:
        await relay_task
    except asyncio.CancelledError:
        pass
    logger.info("Web server shutdown complete")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Rostaurant Web Server", version="1.0.0", lifespan=lifespan)

# Serve static UI files
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# ── Browser WebSocket ─────────────────────────────────────────────────────────

@app.websocket("/ws")
async def browser_ws(websocket: WebSocket) -> None:
    """Real-time event stream to browser clients (relay from control server)."""
    await _add_browser(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await _remove_browser(websocket)


# ── Helpers for control REST proxy ────────────────────────────────────────────

def _control_headers() -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if SERVICE_KEY:
        headers["Authorization"] = f"Bearer {SERVICE_KEY}"
    return headers


async def _control_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{CONTROL_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, headers=_control_headers())
    if not resp.is_success:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/checkout")
async def api_checkout(request: Request) -> JSONResponse:
    """Kiosk: payment completed → create KIOSK_TO_TABLE task on control server."""
    body: dict[str, Any] = await request.json()
    table: str = body.get("table", "")
    if not table:
        raise HTTPException(status_code=422, detail="table is required")

    payload = {
        "task_type": 1,        # KIOSK_TO_TABLE
        "dest_id":   table,
        "priority":  2,        # NORMAL
        "requester_id": "",
    }
    result = await _control_post("/tasks", payload)
    logger.info("Checkout: table=%s → task %s", table, result.get("task_id"))
    return JSONResponse({"ok": True, "task_id": result.get("task_id"), "table": table})


_KITCHEN_TYPE_MAP: dict[str, int] = {
    "menuReady":    1,   # MOVE_TO (kitchen → table)
    "robotArrived": 0,   # status-only, no command needed
    "robotLoaded":  0,
}


@app.post("/api/kitchen")
async def api_kitchen(request: Request) -> JSONResponse:
    """Kitchen panel: menu ready / robot arrived / loaded events."""
    body: dict[str, Any] = await request.json()
    event_type: str = body.get("type", "")
    logger.info("Kitchen event: %s %s", event_type, body)
    # For now acknowledge — command dispatch requires robot_id which kitchen panel
    # does not yet provide; logged for control operator awareness.
    return JSONResponse({"ok": True, "received": event_type})


_TABLE_TASK_MAP: dict[str, int] = {
    "toilet":     6,   # ESCORT_SERVICE
    "robotSwap":  5,   # ROBOT_SWAP
    "dishDone":   4,   # DISH_PICKUP
    "dishPickup": 4,   # DISH_PICKUP
    "escort":     6,   # ESCORT_SERVICE
    "staff":      0,   # no robot task; notify only
}


@app.post("/api/request")
async def api_request(request: Request) -> JSONResponse:
    """Table UI: send a service request from a table."""
    body: dict[str, Any] = await request.json()
    table: str = str(body.get("table", ""))
    req_type: str = body.get("type", "")

    if req_type.startswith("menu:"):
        task_type = 3          # TABLE_TO_DISPLAY
    else:
        task_type = _TABLE_TASK_MAP.get(req_type, 0)

    logger.info("Table request: table=%s type=%s task_type=%d", table, req_type, task_type)

    if task_type == 0:
        # Staff call or unknown — acknowledge without creating a robot task
        return JSONResponse({"ok": True, "task_id": None, "note": "staff notified"})

    dest_id = f"TBL_{table.zfill(2)}" if table.isdigit() else table
    payload = {
        "task_type":    task_type,
        "dest_id":      dest_id,
        "priority":     2,
        "requester_id": "",
    }
    try:
        result = await _control_post("/tasks", payload)
        return JSONResponse({"ok": True, "task_id": result.get("task_id")})
    except HTTPException as exc:
        logger.warning("Table request failed: %s", exc.detail)
        return JSONResponse({"ok": False, "detail": exc.detail}, status_code=exc.status_code)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
