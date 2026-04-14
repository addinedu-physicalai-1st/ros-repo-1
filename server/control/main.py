"""FastAPI entrypoint: REST + lifespan TCP/UDP + SQLite + RBAC.

Role-based access matrix
──────────────────────────────────────────────────────────────────
Endpoint                        CUSTOMER  STAFF_K  STAFF_F  ADMIN
POST   /tasks                      ✓        ✓        ✓       ✓
GET    /tasks                      own      all      all     all
GET    /tasks/{id}                 own      ✓        ✓       ✓
GET    /robots                     —        —        ✓       ✓
POST   /robots/{id}/rotate-connection-token  —   —   —       ✓
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
GET    /health                     —        —        —       —   (no auth; status only)
GET    /health/detail              —        —        ✓       ✓   (connected_robots)
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
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, Field

from auth import CurrentUser, Permission, generate_api_key, hash_api_key, require
from connection_manager import ConnectionManager
from db import Database, _ts_now_ms
from robotcafe.db.v1 import robotcafe_pb2 as pb
from tcp_gateway import start_tcp_server
from udp_receiver import start_udp_receiver
from ws_broker import WSBroker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


def _openapi_disabled() -> bool:
    if os.environ.get("MRTA_DISABLE_OPENAPI", "").strip() == "1":
        return True
    return os.environ.get("MRTA_ENV", "").strip().lower() == "production"


def _write_initial_admin_key_file(path: str, admin_id: str, raw_key: str) -> None:
    text = f"user_id={admin_id}\napi_key={raw_key}\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _log_initial_admin_created(admin_id: str, raw_key: str) -> None:
    out = os.environ.get("MRTA_ADMIN_KEY_OUT", "").strip()
    if out:
        try:
            _write_initial_admin_key_file(out, admin_id, raw_key)
            logger.info("INITIAL ADMIN user_id=%s — api_key written to %s (mode 0600)", admin_id, out)
        except OSError as e:
            logger.error("MRTA_ADMIN_KEY_OUT write failed (%s): %s", out, e)
            logger.info("INITIAL ADMIN user_id=%s (key not written to file)", admin_id)
    suffix = raw_key[-4:] if len(raw_key) >= 4 else "****"
    logger.info(
        "INITIAL ADMIN user_id=%s api_key_suffix=...%s (full key not logged). "
        "Set MRTA_ADMIN_KEY_OUT=/secure/path to persist, or POST /users with an admin key.",
        admin_id,
        suffix,
    )


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


class TaskRespondBody(BaseModel):
    status: str                # "ok" | "retry" | "timeout"
    next_dest: str = ""        # next waypoint place_id for multi-stop guidance


# ──────────────────────────────────────────────────────────────────
# Lifespan
# ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_path   = os.environ.get("MRTA_DB_PATH",  "rostaurant.db")
    tcp_host  = os.environ.get("MRTA_TCP_HOST", "0.0.0.0")
    tcp_port  = int(os.environ.get("MRTA_TCP_PORT", "9000"))
    udp_host  = os.environ.get("MRTA_UDP_HOST", "0.0.0.0")
    udp_port  = int(os.environ.get("MRTA_UDP_PORT", "9001"))

    database = Database(db_path)
    conn = await database.connect()
    await database.init_schema(conn)
    db_lock = asyncio.Lock()

    broker = WSBroker()
    async def _get_db_conn() -> aiosqlite.Connection:
        return conn

    manager = ConnectionManager(database, get_conn=_get_db_conn, db_lock=db_lock, broker=broker)
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
            _log_initial_admin_created(admin_id, raw_key)

    # ── background tasks ─────────────────────────────────────────
    max_tcp = int(os.environ.get("MRTA_MAX_TCP_FRAME_BYTES", "2097152"))

    async def tcp_runner() -> None:
        srv = await start_tcp_server(tcp_host, tcp_port, manager, max_frame_bytes=max_tcp)
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
    app.state.broker      = broker
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


_openapi_off = _openapi_disabled()
app = FastAPI(
    title="MRTA Server",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if _openapi_off else "/docs",
    redoc_url=None if _openapi_off else "/redoc",
    openapi_url=None if _openapi_off else "/openapi.json",
)


# ──────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────

async def _dispatch_move_to(
    db: Any,
    conn: Any,
    lock: asyncio.Lock,
    manager: Any,
    *,
    task_id: str,
    robot_id: str,
    dest_id: str,
) -> None:
    """Send a MOVE_TO command to robot and update the task's robot_id."""
    cmd_id = str(uuid.uuid4())
    now_ms = _ts_now_ms()
    cmd_pb = pb.Command(
        cmd_id=cmd_id,
        task_id=task_id,
        robot_id=robot_id,
        command=pb.CommandType.MOVE_TO,
        target_id=dest_id,
        status=pb.CommandStatus.SENT,
    )
    cmd_pb.sent_at.FromMilliseconds(now_ms)

    async with lock:
        await db.insert_command(
            conn,
            cmd_id=cmd_id,
            task_id=task_id,
            robot_id=robot_id,
            command=int(pb.CommandType.MOVE_TO),
            target_id=dest_id,
            status=int(pb.CommandStatus.SENT),
            sent_at_ms=now_ms,
        )
        await db.assign_task_robot(conn, task_id, robot_id)
        await db.update_task_status(conn, task_id=task_id, status=int(pb.TaskStatus.IN_PROGRESS))

    sess = await manager.get_session(robot_id)
    if sess is None:
        logger.warning("Auto-dispatch: robot %s not connected", robot_id)
        return
    pkt = pb.TcpPacket(robot_id=robot_id, seq=sess.next_seq(), cmd_payload=cmd_pb)
    try:
        await manager.send_command_packet(robot_id, pkt)
        logger.info("Auto-dispatch MOVE_TO robot=%s task=%s dest=%s", robot_id, task_id, dest_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Auto-dispatch send failed: %s", e)


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

    # Auto-dispatch: find an IDLE robot and send MOVE_TO immediately
    manager = _get_manager(request)
    async with lock:
        idle_robot = await db.get_any_idle_robot(conn)
    if idle_robot:
        asyncio.create_task(
            _dispatch_move_to(
                db, conn, lock, manager,
                task_id=task.task_id,
                robot_id=idle_robot.robot_id,
                dest_id=body.dest_id,
            )
        )

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


@app.post("/tasks/{task_id}/respond", summary="Respond to a task arrival (ok/retry/timeout)")
async def task_respond(
    task_id: str,
    body: TaskRespondBody,
    request: Request,
    user: CurrentUser = Depends(require(Permission.TASK_CREATE)),
) -> dict[str, Any]:
    """Handle user confirmation after robot arrival.

    - ``ok`` + ``next_dest``  → send MOVE_TO to next waypoint
    - ``ok`` (no next_dest)   → send RETURN_DOCK, mark task COMPLETED
    - ``retry``               → re-send MOVE_TO to current dest
    - ``timeout``             → send RETURN_DOCK, mark task FAILED
    """
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    manager = _get_manager(request)

    async with lock:
        task = await db.get_task(conn, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if user.has(Permission.TASK_READ_OWN) and not user.has(Permission.TASK_READ_ALL):
        if task.requester_id != user.user_id:
            raise HTTPException(status_code=403, detail="Not your task")

    robot_id = task.robot_id
    if not robot_id:
        raise HTTPException(status_code=409, detail="no robot assigned to task")

    if body.status == "ok" and body.next_dest:
        # Navigate to next waypoint in multi-stop guidance
        asyncio.create_task(
            _dispatch_move_to(
                db, conn, lock, manager,
                task_id=task_id,
                robot_id=robot_id,
                dest_id=body.next_dest,
            )
        )
        return {"task_id": task_id, "action": "move_to", "dest": body.next_dest}

    elif body.status == "ok":
        # Final destination reached — return to dock and complete
        cmd_id = str(uuid.uuid4())
        now_ms = _ts_now_ms()
        cmd_pb = pb.Command(
            cmd_id=cmd_id, task_id=task_id, robot_id=robot_id,
            command=pb.CommandType.RETURN_DOCK, target_id="",
            status=pb.CommandStatus.SENT,
        )
        cmd_pb.sent_at.FromMilliseconds(now_ms)
        async with lock:
            await db.insert_command(conn, cmd_id=cmd_id, task_id=task_id,
                robot_id=robot_id, command=int(pb.CommandType.RETURN_DOCK),
                target_id="", status=int(pb.CommandStatus.SENT), sent_at_ms=now_ms)
            await db.update_task_status(conn, task_id=task_id,
                status=int(pb.TaskStatus.COMPLETED), completed=True)
        sess = await manager.get_session(robot_id)
        if sess:
            pkt = pb.TcpPacket(robot_id=robot_id, seq=sess.next_seq(), cmd_payload=cmd_pb)
            try:
                await manager.send_command_packet(robot_id, pkt)
            except Exception as e:  # noqa: BLE001
                logger.warning("RETURN_DOCK send failed: %s", e)
        return {"task_id": task_id, "action": "return_dock", "task_status": "completed"}

    elif body.status == "retry":
        # Retry current destination
        asyncio.create_task(
            _dispatch_move_to(
                db, conn, lock, manager,
                task_id=task_id,
                robot_id=robot_id,
                dest_id=task.dest_id,
            )
        )
        return {"task_id": task_id, "action": "retry", "dest": task.dest_id}

    else:  # timeout or unknown
        cmd_id = str(uuid.uuid4())
        now_ms = _ts_now_ms()
        cmd_pb = pb.Command(
            cmd_id=cmd_id, task_id=task_id, robot_id=robot_id,
            command=pb.CommandType.RETURN_DOCK, target_id="",
            status=pb.CommandStatus.SENT,
        )
        cmd_pb.sent_at.FromMilliseconds(now_ms)
        async with lock:
            await db.insert_command(conn, cmd_id=cmd_id, task_id=task_id,
                robot_id=robot_id, command=int(pb.CommandType.RETURN_DOCK),
                target_id="", status=int(pb.CommandStatus.SENT), sent_at_ms=now_ms)
            await db.update_task_status(conn, task_id=task_id,
                status=int(pb.TaskStatus.FAILED), completed=True)
        sess = await manager.get_session(robot_id)
        if sess:
            pkt = pb.TcpPacket(robot_id=robot_id, seq=sess.next_seq(), cmd_payload=cmd_pb)
            try:
                await manager.send_command_packet(robot_id, pkt)
            except Exception as e:  # noqa: BLE001
                logger.warning("RETURN_DOCK send failed: %s", e)
        return {"task_id": task_id, "action": "return_dock", "task_status": "failed"}


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


@app.post(
    "/robots/{robot_id}/rotate-connection-token",
    summary="Issue a new robot TCP connection token (ADMIN; plaintext shown once)",
)
async def rotate_robot_connection_token(
    robot_id: str,
    request: Request,
    user: CurrentUser = Depends(require(Permission.ROBOT_COMMAND)),
) -> dict[str, str]:
    raw = generate_api_key()
    db, conn, lock = _get_db(request), _get_conn(request), _get_lock(request)
    async with lock:
        await db.set_robot_connection_token_hash(
            conn, robot_id=robot_id, token_hash=hash_api_key(raw)
        )
    logger.info("Rotated connection token for robot %s by %s", robot_id, user)
    return {"robot_id": robot_id, "connection_token": raw}


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
# WebSocket stream  (Data Plane — server→web, unidirectional)
# ──────────────────────────────────────────────────────────────────

@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket) -> None:
    """Internal WebSocket endpoint for the web server to subscribe to real-time events.

    Authentication: query param ``token`` must match env ``CONTROL_SERVICE_KEY``.
    Unauthenticated connections are closed immediately with code 4001.
    """
    service_key = os.environ.get("CONTROL_SERVICE_KEY", "").strip()
    token = websocket.query_params.get("token", "")
    if service_key and token != service_key:
        await websocket.close(code=4001)
        logger.warning("WS /ws/stream rejected: invalid token from %s", websocket.client)
        return

    broker: WSBroker = websocket.app.state.broker
    await broker.connect(websocket)
    logger.info("WS /ws/stream client connected: %s", websocket.client)
    try:
        while True:
            # Keep connection alive; data flows only from server to client.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await broker.disconnect(websocket)
        logger.info("WS /ws/stream client disconnected: %s", websocket.client)


# ──────────────────────────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────────────────────────

@app.get("/health", summary="Server health check (no auth; minimal payload)")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/health/detail",
    summary="Health with connected robot IDs (STAFF_FLOOR+ / requires API key)",
)
async def health_detail(
    request: Request,
    user: CurrentUser = Depends(require(Permission.ROBOT_READ)),
) -> dict[str, Any]:
    manager = _get_manager(request)
    sessions = await manager.get_all_session_ids()
    return {"status": "ok", "connected_robots": sessions}
