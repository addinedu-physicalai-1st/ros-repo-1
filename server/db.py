"""SQLite persistence (aiosqlite). Timestamps as INTEGER Unix epoch milliseconds."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Optional

import aiosqlite
from google.protobuf.timestamp_pb2 import Timestamp

from robotcafe.db.v1 import robotcafe_pb2 as pb

logger = logging.getLogger(__name__)


def _ts_now_ms() -> int:
    return int(time.time() * 1000)


def _timestamp_from_ms(ms: Optional[int]) -> Timestamp:
    ts = Timestamp()
    if ms is not None:
        ts.FromMilliseconds(ms)
    return ts


class Database:
    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or os.environ.get("MRTA_DB_PATH", "mrta.db")

    async def connect(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self._path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.commit()
        return conn

    async def init_schema(self, conn: aiosqlite.Connection) -> None:
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT    PRIMARY KEY,
                prefix        TEXT    NOT NULL DEFAULT '',
                name          TEXT    NOT NULL DEFAULT '',
                role          INTEGER NOT NULL DEFAULT 1,
                api_key_hash  TEXT    NOT NULL UNIQUE,
                created_at_ms INTEGER NOT NULL,
                is_active     INTEGER NOT NULL DEFAULT 1
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_key_hash ON users(api_key_hash);

            CREATE TABLE IF NOT EXISTS robots (
                robot_id        TEXT    PRIMARY KEY,
                model           TEXT    NOT NULL DEFAULT '',
                status          INTEGER NOT NULL,
                battery_last    INTEGER NOT NULL DEFAULT 0,
                last_seen_ms    INTEGER,
                current_task_id TEXT    NOT NULL DEFAULT '',
                fsm_state       INTEGER NOT NULL DEFAULT 0,
                connection_token_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id        TEXT    PRIMARY KEY,
                requester_id   TEXT    NOT NULL,
                task_type      INTEGER NOT NULL,
                dest_id        TEXT    NOT NULL,
                status         INTEGER NOT NULL,
                priority       INTEGER NOT NULL,
                robot_id       TEXT    NOT NULL DEFAULT '',
                created_at_ms  INTEGER NOT NULL,
                updated_at_ms  INTEGER NOT NULL,
                completed_at_ms INTEGER
            );

            CREATE TABLE IF NOT EXISTS task_steps (
                task_id        TEXT    NOT NULL,
                step_num       INTEGER NOT NULL,
                step_name      TEXT    NOT NULL DEFAULT '',
                status         INTEGER NOT NULL,
                dest_id        TEXT    NOT NULL DEFAULT '',
                started_at_ms  INTEGER,
                completed_at_ms INTEGER,
                error_code     INTEGER NOT NULL DEFAULT 0,
                error_msg      TEXT    NOT NULL DEFAULT '',
                PRIMARY KEY (task_id, step_num),
                FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS commands (
                cmd_id      TEXT    PRIMARY KEY,
                task_id     TEXT    NOT NULL,
                robot_id    TEXT    NOT NULL,
                command     INTEGER NOT NULL,
                target_id   TEXT    NOT NULL DEFAULT '',
                status      INTEGER NOT NULL,
                sent_at_ms  INTEGER NOT NULL,
                acked_at_ms INTEGER,
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            );

            CREATE INDEX IF NOT EXISTS idx_commands_robot  ON commands(robot_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_created   ON tasks(created_at_ms);
            CREATE INDEX IF NOT EXISTS idx_tasks_requester ON tasks(requester_id);

            CREATE TABLE IF NOT EXISTS places (
                place_id      TEXT    PRIMARY KEY,
                name          TEXT    NOT NULL DEFAULT '',
                zone          INTEGER NOT NULL DEFAULT 0,
                x             REAL,
                y             REAL,
                theta         REAL,
                max_speed     REAL,
                is_active     INTEGER NOT NULL DEFAULT 1,
                sort_order    INTEGER NOT NULL DEFAULT 0,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS place_waypoints (
                wp_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                place_id TEXT    NOT NULL,
                seq      INTEGER NOT NULL,
                label    TEXT    NOT NULL DEFAULT '',
                x        REAL,
                y        REAL,
                theta    REAL,
                FOREIGN KEY (place_id) REFERENCES places(place_id) ON DELETE CASCADE,
                UNIQUE (place_id, seq)
            );

            CREATE TABLE IF NOT EXISTS menu_items (
                menu_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL DEFAULT '',
                place_id     TEXT    NOT NULL UNIQUE,
                is_available INTEGER NOT NULL DEFAULT 1,
                sort_order   INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (place_id) REFERENCES places(place_id)
            );

            CREATE INDEX IF NOT EXISTS idx_places_active    ON places(is_active);
            CREATE INDEX IF NOT EXISTS idx_places_zone      ON places(zone);
            CREATE INDEX IF NOT EXISTS idx_menu_place       ON menu_items(place_id);
            """
        )
        await conn.commit()
        await self.migrate_schema(conn)
        logger.info("Database schema ready at %s", self._path)

    async def migrate_schema(self, conn: aiosqlite.Connection) -> None:
        """Additive migrations for existing SQLite files."""
        cur = await conn.execute("PRAGMA table_info(robots)")
        cols = {str(r[1]) for r in await cur.fetchall()}
        if "connection_token_hash" not in cols:
            await conn.execute("ALTER TABLE robots ADD COLUMN connection_token_hash TEXT")
            await conn.commit()
            logger.info("migration: added column robots.connection_token_hash")

    # ──────────────────────────────────────────────────────────────
    # Places — seed data
    # ──────────────────────────────────────────────────────────────

    # (place_id, name, zone, sort_order)
    # zone values from ZoneType proto enum:
    #   ZONE_TABLE=1, ZONE_KITCHEN=2, ZONE_TOILET=3, ZONE_DISPLAY=4,
    #   ZONE_DOCK=5, ZONE_CORRIDOR=6
    _PLACE_SEEDS: list[tuple[str, str, int, int]] = [
        ("WAIT_A",    "대기 A",          6,  1),
        ("WAIT_B",    "대기 B",          6,  2),
        ("KIOSK_1",   "키오스크(출입구)", 4,  3),
        ("TBL_01",    "테이블 1",         1,  4),
        ("TBL_02",    "테이블 2",         1,  5),
        ("TBL_03",    "테이블 3",         1,  6),
        ("TBL_04",    "테이블 4",         1,  7),
        ("TBL_05",    "테이블 5",         1,  8),
        ("TOILET",    "화장실",           3,  9),
        ("EXIT_DINE", "퇴식구",           6, 10),
        ("KITCHEN",   "주방",             2, 11),
        ("DISP_01",   "진열장 1",         4, 12),
        ("DISP_02",   "진열장 2",         4, 13),
        ("DISP_03",   "진열장 3",         4, 14),
        ("DISP_04",   "진열장 4",         4, 15),
        ("DISP_05",   "진열장 5",         4, 16),
        ("DISP_06",   "진열장 6",         4, 17),
    ]

    # (name, place_id, sort_order) — 진열장 6곳과 1:1 매핑
    _MENU_SEEDS: list[tuple[str, str, int]] = [
        ("메뉴 1", "DISP_01", 1),
        ("메뉴 2", "DISP_02", 2),
        ("메뉴 3", "DISP_03", 3),
        ("메뉴 4", "DISP_04", 4),
        ("메뉴 5", "DISP_05", 5),
        ("메뉴 6", "DISP_06", 6),
    ]

    async def seed_places(self, conn: aiosqlite.Connection) -> None:
        """Insert default 17 places and 6 menu items if not already present."""
        now = _ts_now_ms()
        for place_id, name, zone, sort_order in self._PLACE_SEEDS:
            await conn.execute(
                """
                INSERT OR IGNORE INTO places
                  (place_id, name, zone, is_active, sort_order, created_at_ms, updated_at_ms)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (place_id, name, zone, sort_order, now, now),
            )
        for name, place_id, sort_order in self._MENU_SEEDS:
            await conn.execute(
                """
                INSERT OR IGNORE INTO menu_items (name, place_id, is_available, sort_order)
                VALUES (?, ?, 1, ?)
                """,
                (name, place_id, sort_order),
            )
        await conn.commit()
        logger.info("Places seed complete")

    # ──────────────────────────────────────────────────────────────
    # Places — CRUD
    # ──────────────────────────────────────────────────────────────

    async def list_places(
        self, conn: aiosqlite.Connection, *, active_only: bool = False
    ) -> list[dict[str, Any]]:
        where = "WHERE is_active = 1" if active_only else ""
        cur = await conn.execute(
            f"SELECT * FROM places {where} ORDER BY sort_order, place_id"
        )
        return [dict(r) for r in await cur.fetchall()]

    async def get_place(
        self, conn: aiosqlite.Connection, place_id: str
    ) -> Optional[dict[str, Any]]:
        cur = await conn.execute("SELECT * FROM places WHERE place_id = ?", (place_id,))
        row = await cur.fetchone()
        return dict(row) if row is not None else None

    async def patch_place(
        self,
        conn: aiosqlite.Connection,
        place_id: str,
        *,
        fields: dict[str, Any],
    ) -> bool:
        _allowed = {"name", "zone", "x", "y", "theta", "max_speed", "is_active", "sort_order"}
        updates = {k: v for k, v in fields.items() if k in _allowed}
        if not updates:
            return False
        updates["updated_at_ms"] = _ts_now_ms()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        vals: list[Any] = list(updates.values()) + [place_id]
        cur = await conn.execute(
            f"UPDATE places SET {set_clause} WHERE place_id = ?", vals
        )
        await conn.commit()
        return cur.rowcount > 0

    async def place_exists_active(
        self, conn: aiosqlite.Connection, place_id: str
    ) -> bool:
        """Return True if place_id exists and is active (used to validate dest_id)."""
        cur = await conn.execute(
            "SELECT 1 FROM places WHERE place_id = ? AND is_active = 1", (place_id,)
        )
        return await cur.fetchone() is not None

    # ──────────────────────────────────────────────────────────────
    # Place Waypoints — CRUD
    # ──────────────────────────────────────────────────────────────

    async def list_place_waypoints(
        self, conn: aiosqlite.Connection, place_id: str
    ) -> list[dict[str, Any]]:
        cur = await conn.execute(
            "SELECT * FROM place_waypoints WHERE place_id = ? ORDER BY seq", (place_id,)
        )
        return [dict(r) for r in await cur.fetchall()]

    async def put_place_waypoints(
        self,
        conn: aiosqlite.Connection,
        place_id: str,
        waypoints: list[dict[str, Any]],
    ) -> None:
        """Replace all waypoints for a place (idempotent full replace)."""
        await conn.execute(
            "DELETE FROM place_waypoints WHERE place_id = ?", (place_id,)
        )
        for wp in waypoints:
            await conn.execute(
                """
                INSERT INTO place_waypoints (place_id, seq, label, x, y, theta)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    place_id,
                    int(wp["seq"]),
                    str(wp.get("label") or ""),
                    wp.get("x"),
                    wp.get("y"),
                    wp.get("theta"),
                ),
            )
        await conn.commit()

    # ──────────────────────────────────────────────────────────────
    # Menu Items — CRUD
    # ──────────────────────────────────────────────────────────────

    async def list_menu_items(
        self, conn: aiosqlite.Connection
    ) -> list[dict[str, Any]]:
        cur = await conn.execute(
            "SELECT * FROM menu_items ORDER BY sort_order, menu_id"
        )
        return [dict(r) for r in await cur.fetchall()]

    async def patch_menu_item(
        self,
        conn: aiosqlite.Connection,
        menu_id: int,
        *,
        fields: dict[str, Any],
    ) -> bool:
        _allowed = {"name", "place_id", "is_available", "sort_order"}
        updates = {k: v for k, v in fields.items() if k in _allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        vals: list[Any] = list(updates.values()) + [menu_id]
        cur = await conn.execute(
            f"UPDATE menu_items SET {set_clause} WHERE menu_id = ?", vals
        )
        await conn.commit()
        return cur.rowcount > 0

    # ──────────────────────────────────────────────────────────────
    # Users
    # ──────────────────────────────────────────────────────────────

    async def create_user(
        self,
        conn: aiosqlite.Connection,
        *,
        user_id: str,
        prefix: str,
        name: str,
        role: int,
        api_key_hash: str,
    ) -> None:
        now = _ts_now_ms()
        await conn.execute(
            """
            INSERT INTO users (user_id, prefix, name, role, api_key_hash, created_at_ms, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (user_id, prefix, name, role, api_key_hash, now),
        )
        await conn.commit()

    async def get_user_by_key_hash(
        self, conn: aiosqlite.Connection, key_hash: str
    ) -> Optional[aiosqlite.Row]:
        cur = await conn.execute(
            "SELECT * FROM users WHERE api_key_hash = ? AND is_active = 1",
            (key_hash,),
        )
        return await cur.fetchone()

    async def get_user(self, conn: aiosqlite.Connection, user_id: str) -> Optional[aiosqlite.Row]:
        cur = await conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cur.fetchone()

    async def list_users(self, conn: aiosqlite.Connection) -> list[dict[str, Any]]:
        cur = await conn.execute(
            "SELECT user_id, prefix, name, role, created_at_ms, is_active FROM users ORDER BY created_at_ms"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def set_user_active(
        self, conn: aiosqlite.Connection, user_id: str, *, active: bool
    ) -> None:
        await conn.execute(
            "UPDATE users SET is_active = ? WHERE user_id = ?",
            (int(active), user_id),
        )
        await conn.commit()

    async def any_admin_exists(self, conn: aiosqlite.Connection) -> bool:
        cur = await conn.execute(
            "SELECT 1 FROM users WHERE role = ? AND is_active = 1 LIMIT 1",
            (int(pb.UserRole.ADMIN),),
        )
        return await cur.fetchone() is not None

    # ──────────────────────────────────────────────────────────────
    # Robots
    # ──────────────────────────────────────────────────────────────

    async def upsert_robot_from_status(
        self,
        conn: aiosqlite.Connection,
        *,
        robot_id: str,
        model: str = "",
        status: int,
        battery: int,
        last_seen_ms: int,
        current_task_id: str = "",
        fsm_state: int,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO robots (robot_id, model, status, battery_last, last_seen_ms, current_task_id, fsm_state)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(robot_id) DO UPDATE SET
                status          = excluded.status,
                battery_last    = excluded.battery_last,
                last_seen_ms    = excluded.last_seen_ms,
                current_task_id = excluded.current_task_id,
                fsm_state       = excluded.fsm_state
            """,
            (robot_id, model, status, battery, last_seen_ms, current_task_id, fsm_state),
        )
        await conn.commit()

    async def upsert_robot_heartbeat(
        self,
        conn: aiosqlite.Connection,
        *,
        robot_id: str,
        last_seen_ms: int,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO robots (robot_id, model, status, battery_last, last_seen_ms, current_task_id, fsm_state)
            VALUES (?, '', ?, 0, ?, '', 0)
            ON CONFLICT(robot_id) DO UPDATE SET last_seen_ms = excluded.last_seen_ms
            """,
            (robot_id, int(pb.RobotStatus.IDLE), last_seen_ms),
        )
        await conn.commit()

    async def mark_robot_offline(self, conn: aiosqlite.Connection, robot_id: str) -> None:
        now = _ts_now_ms()
        await conn.execute(
            "UPDATE robots SET status = ?, last_seen_ms = ? WHERE robot_id = ?",
            (int(pb.RobotStatus.OFFLINE), now, robot_id),
        )
        await conn.commit()

    async def list_robots(self, conn: aiosqlite.Connection) -> list[pb.Robot]:
        cur = await conn.execute("SELECT * FROM robots ORDER BY robot_id")
        rows = await cur.fetchall()
        return [self._row_to_robot(r) for r in rows]

    async def get_robot_connection_token_hash(
        self, conn: aiosqlite.Connection, robot_id: str
    ) -> Optional[str]:
        cur = await conn.execute(
            "SELECT connection_token_hash FROM robots WHERE robot_id = ?",
            (robot_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        v = row["connection_token_hash"]
        if v is None or v == "":
            return None
        return str(v)

    async def set_robot_connection_token_hash(
        self,
        conn: aiosqlite.Connection,
        *,
        robot_id: str,
        token_hash: str,
    ) -> None:
        """Insert minimal robot row if missing, then store hashed connection token."""
        await conn.execute(
            """
            INSERT INTO robots (
                robot_id, model, status, battery_last, last_seen_ms,
                current_task_id, fsm_state, connection_token_hash
            )
            VALUES (?, '', ?, 0, NULL, '', ?, ?)
            ON CONFLICT(robot_id) DO UPDATE SET
                connection_token_hash = excluded.connection_token_hash
            """,
            (
                robot_id,
                int(pb.RobotStatus.IDLE),
                int(pb.FsmState.FSM_IDLE),
                token_hash,
            ),
        )
        await conn.commit()

    def _row_to_robot(self, r: aiosqlite.Row) -> pb.Robot:
        rob = pb.Robot(
            robot_id=r["robot_id"],
            model=r["model"] or "",
            status=r["status"],
            battery_last=r["battery_last"],
            current_task_id=r["current_task_id"] or "",
            fsm_state=r["fsm_state"],
        )
        if r["last_seen_ms"] is not None:
            rob.last_seen.CopyFrom(_timestamp_from_ms(int(r["last_seen_ms"])))
        return rob

    # ──────────────────────────────────────────────────────────────
    # Tasks
    # ──────────────────────────────────────────────────────────────

    async def create_task(
        self,
        conn: aiosqlite.Connection,
        *,
        requester_id: str,
        task_type: int,
        dest_id: str,
        priority: int,
        robot_id: str = "",
    ) -> pb.Task:
        task_id = str(uuid.uuid4())
        now = _ts_now_ms()
        await conn.execute(
            """
            INSERT INTO tasks
              (task_id, requester_id, task_type, dest_id, status, priority, robot_id,
               created_at_ms, updated_at_ms, completed_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                task_id, requester_id, task_type, dest_id,
                int(pb.TaskStatus.PENDING), priority, robot_id, now, now,
            ),
        )
        await conn.commit()
        task = pb.Task(
            task_id=task_id,
            requester_id=requester_id,
            task_type=task_type,
            dest_id=dest_id,
            status=pb.TaskStatus.PENDING,
            priority=priority,
            robot_id=robot_id,
        )
        task.created_at.CopyFrom(_timestamp_from_ms(now))
        task.updated_at.CopyFrom(_timestamp_from_ms(now))
        return task

    async def get_task(self, conn: aiosqlite.Connection, task_id: str) -> Optional[pb.Task]:
        cur = await conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = await cur.fetchone()
        if row is None:
            return None
        task = self._row_to_task(row)
        cur2 = await conn.execute(
            "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_num", (task_id,)
        )
        for s in await cur2.fetchall():
            task.steps.append(self._row_to_step(s))
        return task

    async def list_tasks(
        self,
        conn: aiosqlite.Connection,
        *,
        status: Optional[int] = None,
        requester_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[pb.Task], int]:
        filters: list[str] = []
        params: list[Any] = []
        if status is not None and status != int(pb.TaskStatus.TASK_STATUS_UNSPECIFIED):
            filters.append("status = ?")
            params.append(status)
        if requester_id is not None:
            filters.append("requester_id = ?")
            params.append(requester_id)

        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        total_row = await (
            await conn.execute(f"SELECT COUNT(*) FROM tasks {where}", params)
        ).fetchone()
        total = int(total_row[0])
        rows = await (
            await conn.execute(
                f"SELECT * FROM tasks {where} ORDER BY created_at_ms DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
        ).fetchall()

        tasks: list[pb.Task] = []
        for r in rows:
            t = self._row_to_task(r)
            cur2 = await conn.execute(
                "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_num", (r["task_id"],)
            )
            for s in await cur2.fetchall():
                t.steps.append(self._row_to_step(s))
            tasks.append(t)
        return tasks, total

    def _row_to_task(self, r: aiosqlite.Row) -> pb.Task:
        t = pb.Task(
            task_id=r["task_id"],
            requester_id=r["requester_id"],
            task_type=r["task_type"],
            dest_id=r["dest_id"],
            status=r["status"],
            priority=r["priority"],
            robot_id=r["robot_id"] or "",
        )
        t.created_at.CopyFrom(_timestamp_from_ms(int(r["created_at_ms"])))
        t.updated_at.CopyFrom(_timestamp_from_ms(int(r["updated_at_ms"])))
        if r["completed_at_ms"] is not None:
            t.completed_at.CopyFrom(_timestamp_from_ms(int(r["completed_at_ms"])))
        return t

    def _row_to_step(self, r: aiosqlite.Row) -> pb.TaskStep:
        st = pb.TaskStep(
            task_id=r["task_id"],
            step_num=r["step_num"],
            step_name=r["step_name"] or "",
            status=r["status"],
            dest_id=r["dest_id"] or "",
            error_code=r["error_code"],
            error_msg=r["error_msg"] or "",
        )
        if r["started_at_ms"] is not None:
            st.started_at.CopyFrom(_timestamp_from_ms(int(r["started_at_ms"])))
        if r["completed_at_ms"] is not None:
            st.completed_at.CopyFrom(_timestamp_from_ms(int(r["completed_at_ms"])))
        return st

    async def update_task_status(
        self,
        conn: aiosqlite.Connection,
        *,
        task_id: str,
        status: int,
        completed: bool = False,
    ) -> None:
        now = _ts_now_ms()
        if completed:
            await conn.execute(
                "UPDATE tasks SET status=?, updated_at_ms=?, completed_at_ms=? WHERE task_id=?",
                (status, now, now, task_id),
            )
        else:
            await conn.execute(
                "UPDATE tasks SET status=?, updated_at_ms=?, completed_at_ms=NULL WHERE task_id=?",
                (status, now, task_id),
            )
        await conn.commit()

    async def assign_task_robot(self, conn: aiosqlite.Connection, task_id: str, robot_id: str) -> None:
        now = _ts_now_ms()
        await conn.execute(
            "UPDATE tasks SET robot_id=?, updated_at_ms=? WHERE task_id=?",
            (robot_id, now, task_id),
        )
        await conn.commit()

    # ──────────────────────────────────────────────────────────────
    # Commands
    # ──────────────────────────────────────────────────────────────

    async def insert_command(
        self,
        conn: aiosqlite.Connection,
        *,
        cmd_id: str,
        task_id: str,
        robot_id: str,
        command: int,
        target_id: str,
        status: int,
        sent_at_ms: int,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO commands
              (cmd_id, task_id, robot_id, command, target_id, status, sent_at_ms, acked_at_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (cmd_id, task_id, robot_id, command, target_id, status, sent_at_ms),
        )
        await conn.commit()

    async def update_command_status(
        self,
        conn: aiosqlite.Connection,
        *,
        cmd_id: str,
        status: int,
        acked_at_ms: Optional[int] = None,
    ) -> None:
        if acked_at_ms is None:
            await conn.execute("UPDATE commands SET status=? WHERE cmd_id=?", (status, cmd_id))
        else:
            await conn.execute(
                "UPDATE commands SET status=?, acked_at_ms=? WHERE cmd_id=?",
                (status, acked_at_ms, cmd_id),
            )
        await conn.commit()

    async def get_command(self, conn: aiosqlite.Connection, cmd_id: str) -> Optional[dict[str, Any]]:
        cur = await conn.execute("SELECT * FROM commands WHERE cmd_id=?", (cmd_id,))
        row = await cur.fetchone()
        return dict(row) if row is not None else None
