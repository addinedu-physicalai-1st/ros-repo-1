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
                fsm_state       INTEGER NOT NULL DEFAULT 0
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
            """
        )
        await conn.commit()
        logger.info("Database schema ready at %s", self._path)

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
