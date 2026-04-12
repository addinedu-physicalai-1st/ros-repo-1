"""FastAPI entrypoint: REST + lifespan TCP/UDP + SQLite + RBAC.

Role-based access matrix
──────────────────────────────────────────────────────────────────
Endpoint                        CUSTOMER  STAFF_K  STAFF_F  ADMIN
POST   /tasks                      ✓        ✓        ✓       ✓
GET    /tasks                      own      all      all     all
GET    /tasks/{id}                 own      ✓        ✓       ✓
GET    /robots                     —        —        ✓       ✓
GET    /telemetry/pose/{id}        —        —        ✓       ✓
POST   /commands/send              —        —        —       ✓
GET    /users                      —        —        —       ✓
POST   /users                      —        —        —       ✓
PATCH  /users/{id}/deactivate      —        —        —       ✓
GET    /places                     ✓        ✓        ✓       ✓
GET    /places/{id}                ✓        ✓        ✓       ✓
PATCH  /places/{id}                —        —        —       ✓
GET    /places/{id}/waypoints      ✓        ✓        ✓       ✓
PUT    /places/{id}/waypoints      —        —        —       ✓
GET    /menu-items                 ✓        ✓        ✓       ✓
PATCH  /menu-items/{id}            —        —        —       ✓
GET    /health                     ✓        ✓        ✓       ✓
──────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import aiosqlite
from fastapi import Depends, FastAPI, HTTPException, Request, status
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, Field

from auth import CurrentUser, Permission, generate_api_key, hash_api_key, require
from connection_manager import ConnectionManager
from db import Database, _ts_now_ms
from robotcafe.db.v1 import robotcafe_pb2 as pb
from tcp_gateway import start_tcp_server
from udp_receiver import start_udp_receiver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _pb_to_json(msg: Any) -> dict[str, Any]:
    return MessageToDict(msg, preserving_proto_field_name=True)


def _get_db(request: Request) -> Database:
    return request.app.state.db


def _get_conn(request: Request) -> aiosqlite.Connection:
    return request.app.state.conn


def _get_lock(request: Request) -> asyncio.Lock:
    return request.app.state.db_lock


def _get_manager(request: Request) -> ConnectionManager:
    return request.app.state.manager


# ──────────────────────────────────────────────────────────────────
# Pydantic request models
# ──────────────────────────────────────────────────────────────────

class CreateTaskBody(BaseModel):
    requester_id: str = ""
    task_type: int = Field(default=0, ge=0, description="TaskType enum value")
    dest_id: str
    priority: int = Field(default=int(pb.TaskPriority.NORMAL), ge=0)


class SendCommandBody(BaseModel):
    robot_id: str
    task_id: str
    command: int = Field(ge=0, description="CommandType enum value")
    target_id: str = ""


class CreateUserBody(BaseModel):
    prefix: str = ""
    name: str
    role: int = Field(default=int(pb.UserRole.CUSTOMER), ge=1, le=4)


class PatchPlaceBody(BaseModel):
    name: Optional[str] = None
    zone: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    theta: Optional[float] = None
    max_speed: Optional[float] = None
    is_active: Optional[int] = Field(default=None, ge=0, le=1)
    sort_order: Optional[int] = None


class WaypointIn(BaseModel):
    seq: int = Field(ge=0)
    label: str = ""
    x: Optional[float] = None
    y: Optional[float] = None
    theta: Optional[float] = None


class PatchMenuItemBody(BaseModel):
    name: Optional[str] = None
    place_id: Optional[str] = None
    is_available: Optional[int] = Field(default=None, ge=0, le=1)
    sort_order: Optional[int] = None


# ──────────────────────────────────────────────────────────────────
# Lifespan
# ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_path   = os.environ.get("MRTA_DB_PATH",  "mrta.db")
    tcp_host  = os.environ.get("MRTA_TCP_HOST", "0.0.0.0")
    tcp_port  = int(os.environ.get("MRTA_TCP_PORT", "9000"))
    udp_host  = os.environ.get("MRTA_UDP_HOST", "0.0.0.0")
    udp_port  = int(os.environ.get("MRTA_UDP_PORT", "9001"))

    database = Database(db_path)
    conn = await database.connect()
    await database.init_schema(conn)
    db_lock = asyncio.Lock()

    manager = ConnectionManager(database, get_conn=lambda: conn, db_lock=db_lock)
    stop_watchdog = asyncio.Event()

    # ── seed places / menu-items (idempotent) ────────────────────
    async with db_lock:
        await database.seed_places(conn)

    # ── seed initial admin if none exist ─────────────────────────
    async with db_lock:
        if not await database.any_admin_exists(conn):
            raw_key = generate_api_key()
            admin_id = str(uuid.uuid4())
            await database.create_user(
                conn,
                user_id=admin_id,
                prefix="",
                name="admin",
                role=int(pb.UserRole.ADMIN),
                api_key_hash=hash_api_key(raw_key),
            )
            logger.info("=" * 60)
            logger.info("  INITIAL ADMIN CREATED")
            logger.info("  user_id : %s", admin_id)
            logger.info("  api_key : %s", raw_key)
            logger.info("  Keep this key — it will not be shown again.")
            logger.info("=" * 60)

    # ── background tasks ─────────────────────────────────────────
    async def tcp_runner() -> None:
        srv = await start_tcp_server(tcp_host, tcp_port, manager)
        async with srv:
            await srv.serve_forever()

    tcp_task = asyncio.create_task(tcp_runner(), name="mrta-tcp")
    udp_transport = await start_udp_receiver(udp_host, udp_port, manager)
    watchdog_task = asyncio.create_task(
        manager.heartbeat_watchdog(stop_watchdog), name="mrta-watchdog"
    )

    app.state.db          = database
    app.state.conn        = conn
    app.state.db_lock     = db_lock
    app.state.manager     = manager
    app.state.tcp_task    = tcp_task
    app.state.udp_transport = udp_transport
    app.state.watchdog_task = watchdog_task

    yield

    stop_watchdog.set()
    for t in (watchdog_task, tcp_task):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    udp_transport.close()
    await conn.close()
    logger.info("Shutdown complete")


app = FastAPI(title="MRTA Server", version="1.0.0", lifespan=lifespan)


# ──────────────────────────────────────────────────────────────────
# Tasks
# ──────────────────────────────────────────────────────────────────

@app.post("/tasks", summary="Create a new task")
async def create_task(
    body: CreateTaskBody,
    request: Request,
    user: CurrentUser = Depends(require(Permission.TASK_CREATE)),
) -> dict[str, Any]:
    # CUSTOMER's requester_id is always their own user_id
    requester_id = (
        user.user_id
        if user.has(Permission.TASK_READ_OWN) and not user.has(Permission.TASK_READ_ALL)
        else (body.requester_id or user.user_id)
    )
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        if not await db.place_exists_active(conn, body.dest_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"dest_id '{body.dest_id}' is not a valid active place",
            )
        task = await db.create_task(
            conn,
            requester_id=requester_id,
            task_type=body.task_type,
            dest_id=body.dest_id,
            priority=body.priority,
        )
    resp = pb.CreateTaskResponse(
        task_id=task.task_id,
        status=task.status,
        robot_id=task.robot_id,
        message="created",
    )
    logger.info("Task created %s by %s", task.task_id, user)
    return _pb_to_json(resp)


@app.get("/tasks", summary="List tasks")
async def list_tasks(
    request: Request,
    status: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    user: CurrentUser = Depends(require(Permission.TASK_CREATE)),  # min role = any
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    # CUSTOMER can only see own tasks
    requester_filter: Optional[str] = None
    if user.has(Permission.TASK_READ_OWN) and not user.has(Permission.TASK_READ_ALL):
        requester_filter = user.user_id
    async with lock:
        tasks, total = await db.list_tasks(
            conn,
            status=status,
            requester_id=requester_filter,
            limit=min(limit, 200),
            offset=offset,
        )
    return _pb_to_json(pb.ListTasksResponse(tasks=tasks, total=total))


@app.get("/tasks/{task_id}", summary="Get task by ID")
async def get_task(
    task_id: str,
    request: Request,
    user: CurrentUser = Depends(require(Permission.TASK_CREATE)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        task = await db.get_task(conn, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    # CUSTOMER may only read own tasks
    if user.has(Permission.TASK_READ_OWN) and not user.has(Permission.TASK_READ_ALL):
        if task.requester_id != user.user_id:
            raise HTTPException(status_code=403, detail="Not your task")
    return _pb_to_json(pb.GetTaskResponse(task=task))


# ──────────────────────────────────────────────────────────────────
# Robots & Telemetry  (STAFF_FLOOR+ only)
# ──────────────────────────────────────────────────────────────────

@app.get("/robots", summary="List all robots")
async def list_robots(
    request: Request,
    user: CurrentUser = Depends(require(Permission.ROBOT_READ)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        robots = await db.list_robots(conn)
    return _pb_to_json(pb.ListRobotsResponse(robots=robots))


@app.get("/telemetry/pose/{robot_id}", summary="Latest pose for a robot")
async def get_pose(
    robot_id: str,
    request: Request,
    user: CurrentUser = Depends(require(Permission.TELEMETRY_READ)),
) -> dict[str, Any]:
    manager = _get_manager(request)
    pose = await manager.telemetry.get_pose(robot_id)
    if pose is None:
        raise HTTPException(status_code=404, detail="no pose cached for robot")
    return _pb_to_json(pb.GetPoseResponse(latest_pose=pose))


# ──────────────────────────────────────────────────────────────────
# Commands  (ADMIN only)
# ──────────────────────────────────────────────────────────────────

@app.post("/commands/send", summary="Send a command to a robot (ADMIN only)")
async def send_command(
    body: SendCommandBody,
    request: Request,
    user: CurrentUser = Depends(require(Permission.ROBOT_COMMAND)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    manager = _get_manager(request)

    cmd_id  = str(uuid.uuid4())
    now_ms  = _ts_now_ms()

    cmd_pb = pb.Command(
        cmd_id=cmd_id,
        task_id=body.task_id,
        robot_id=body.robot_id,
        command=body.command,
        target_id=body.target_id,
        status=pb.CommandStatus.SENT,
    )
    cmd_pb.sent_at.FromMilliseconds(now_ms)

    async with lock:
        await db.insert_command(
            conn,
            cmd_id=cmd_id,
            task_id=body.task_id,
            robot_id=body.robot_id,
            command=body.command,
            target_id=body.target_id,
            status=int(pb.CommandStatus.SENT),
            sent_at_ms=now_ms,
        )

    sess = await manager.get_session(body.robot_id)
    if sess is None:
        async with lock:
            await db.update_command_status(conn, cmd_id=cmd_id, status=int(pb.CommandStatus.CMD_FAILED))
        raise HTTPException(status_code=503, detail="robot not connected")

    pkt = pb.TcpPacket(robot_id=body.robot_id, seq=sess.next_seq(), cmd_payload=cmd_pb)
    try:
        await manager.send_command_packet(body.robot_id, pkt)
    except Exception as e:
        logger.exception("send_command failed: %s", e)
        async with lock:
            await db.update_command_status(conn, cmd_id=cmd_id, status=int(pb.CommandStatus.CMD_FAILED))
        raise HTTPException(status_code=500, detail=str(e)) from e

    logger.info("Command %s → robot %s by %s", cmd_id, body.robot_id, user)
    return _pb_to_json(pb.SendCommandResponse(cmd_id=cmd_id, status=pb.CommandStatus.SENT))


# ──────────────────────────────────────────────────────────────────
# User management  (ADMIN only)
# ──────────────────────────────────────────────────────────────────

@app.post("/users", summary="Create a new user (ADMIN only)")
async def create_user(
    body: CreateUserBody,
    request: Request,
    user: CurrentUser = Depends(require(Permission.USER_MANAGE)),
) -> dict[str, Any]:
    raw_key = generate_api_key()
    new_id  = str(uuid.uuid4())
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        await db.create_user(
            conn,
            user_id=new_id,
            prefix=body.prefix,
            name=body.name,
            role=body.role,
            api_key_hash=hash_api_key(raw_key),
        )
    logger.info("User created %s role=%s by %s", new_id, body.role, user)
    return {
        "user_id": new_id,
        "name":    body.name,
        "role":    body.role,
        "api_key": raw_key,   # shown only once
    }


@app.get("/users", summary="List all users (ADMIN only)")
async def list_users(
    request: Request,
    user: CurrentUser = Depends(require(Permission.USER_MANAGE)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        rows = await db.list_users(conn)
    return {"users": rows, "total": len(rows)}


@app.patch("/users/{user_id}/deactivate", summary="Deactivate a user (ADMIN only)")
async def deactivate_user(
    user_id: str,
    request: Request,
    user: CurrentUser = Depends(require(Permission.USER_MANAGE)),
) -> dict[str, Any]:
    if user_id == user.user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        row = await db.get_user(conn, user_id)
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        await db.set_user_active(conn, user_id, active=False)
    logger.info("User %s deactivated by %s", user_id, user)
    return {"user_id": user_id, "is_active": False}


# ──────────────────────────────────────────────────────────────────
# Places  (READ: all roles  /  MANAGE: ADMIN only)
# ──────────────────────────────────────────────────────────────────

@app.get("/places", summary="List all places")
async def list_places(
    request: Request,
    active_only: bool = False,
    user: CurrentUser = Depends(require(Permission.PLACE_READ)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        rows = await db.list_places(conn, active_only=active_only)
    return {"places": rows, "total": len(rows)}


@app.get("/places/{place_id}", summary="Get a single place")
async def get_place(
    place_id: str,
    request: Request,
    user: CurrentUser = Depends(require(Permission.PLACE_READ)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        row = await db.get_place(conn, place_id)
    if row is None:
        raise HTTPException(status_code=404, detail="place not found")
    return row


@app.patch("/places/{place_id}", summary="Update place metadata / coordinates (ADMIN only)")
async def patch_place(
    place_id: str,
    body: PatchPlaceBody,
    request: Request,
    user: CurrentUser = Depends(require(Permission.PLACE_MANAGE)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    fields = body.model_dump(exclude_none=True)
    async with lock:
        updated = await db.patch_place(conn, place_id, fields=fields)
    if not updated:
        raise HTTPException(status_code=404, detail="place not found or nothing to update")
    async with lock:
        row = await db.get_place(conn, place_id)
    logger.info("Place %s patched by %s: %s", place_id, user, list(fields.keys()))
    return row or {}


# ──────────────────────────────────────────────────────────────────
# Place Waypoints  (READ: all roles  /  WRITE: ADMIN only)
# ──────────────────────────────────────────────────────────────────

@app.get("/places/{place_id}/waypoints", summary="Get waypoints for a place")
async def get_place_waypoints(
    place_id: str,
    request: Request,
    user: CurrentUser = Depends(require(Permission.PLACE_READ)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        place = await db.get_place(conn, place_id)
        if place is None:
            raise HTTPException(status_code=404, detail="place not found")
        wps = await db.list_place_waypoints(conn, place_id)
    return {"place_id": place_id, "waypoints": wps, "total": len(wps)}


@app.put(
    "/places/{place_id}/waypoints",
    summary="Replace all waypoints for a place (ADMIN only)",
)
async def put_place_waypoints(
    place_id: str,
    waypoints: list[WaypointIn],
    request: Request,
    user: CurrentUser = Depends(require(Permission.PLACE_MANAGE)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        if await db.get_place(conn, place_id) is None:
            raise HTTPException(status_code=404, detail="place not found")
        wp_dicts = [w.model_dump() for w in waypoints]
        await db.put_place_waypoints(conn, place_id, wp_dicts)
    logger.info("Waypoints updated for place %s (%d pts) by %s", place_id, len(waypoints), user)
    return {"place_id": place_id, "total": len(waypoints)}


# ──────────────────────────────────────────────────────────────────
# Menu Items  (READ: all roles  /  MANAGE: ADMIN only)
# ──────────────────────────────────────────────────────────────────

@app.get("/menu-items", summary="List all menu items with mapped display place")
async def list_menu_items(
    request: Request,
    user: CurrentUser = Depends(require(Permission.PLACE_READ)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        rows = await db.list_menu_items(conn)
    return {"menu_items": rows, "total": len(rows)}


@app.patch("/menu-items/{menu_id}", summary="Update a menu item (ADMIN only)")
async def patch_menu_item(
    menu_id: int,
    body: PatchMenuItemBody,
    request: Request,
    user: CurrentUser = Depends(require(Permission.PLACE_MANAGE)),
) -> dict[str, Any]:
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    fields = body.model_dump(exclude_none=True)
    # Validate new place_id if provided
    if "place_id" in fields:
        async with lock:
            if await db.get_place(conn, fields["place_id"]) is None:
                raise HTTPException(status_code=422, detail="place_id not found")
    async with lock:
        updated = await db.patch_menu_item(conn, menu_id, fields=fields)
    if not updated:
        raise HTTPException(status_code=404, detail="menu item not found or nothing to update")
    logger.info("MenuItem %s patched by %s: %s", menu_id, user, list(fields.keys()))
    async with lock:
        rows = await db.list_menu_items(conn)
    item = next((r for r in rows if r["menu_id"] == menu_id), None)
    return item or {}


# ──────────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────────

@app.get("/health", summary="Server health check (no auth required)")
async def health(request: Request) -> dict[str, Any]:
    manager = _get_manager(request)
    sessions = await manager.get_all_session_ids()
    return {"status": "ok", "connected_robots": sessions}
