"""Task scheduling: assignment policy + dispatcher.

TaskAssignmentPolicy  — pure business logic, no I/O (easy to unit-test)
TaskDispatcher        — wires Policy to DB + ConnectionManager
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Optional

import aiosqlite

from db import Database, _ts_now_ms
from robotcafe.db.v1 import robotcafe_pb2 as pb

if TYPE_CHECKING:
    from connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Pure policy (no I/O — unit-testable)
# ──────────────────────────────────────────────────────────────────

class TaskAssignmentPolicy:
    """Stateful but I/O-free scheduling rules.

    UI scheduler.py 의 로직을 서버 레이어로 이관:
    - 우선순위 큐 (DISH_PICKUP = HIGH)
    - 배터리 게이트
    - 수거 전담 로봇 (collector exclusivity)
    - 자동 충전 트리거 판단
    """

    BATTERY_MIN_ASSIGN: int = 20   # 이 미만이면 모든 배정 거부
    BATTERY_MIN_HEAVY: int  = 25   # 이 미만이면 KIOSK_TO_TABLE / ESCORT_SERVICE skip
    MAX_COLLECTION_BATCH: int = 5

    # TaskType 값 (proto enum 숫자)
    _DISH_PICKUP    = int(pb.TaskType.DISH_PICKUP)
    _RETURN_TO_DOCK = int(pb.TaskType.RETURN_TO_DOCK)
    _HEAVY_TYPES    = frozenset([int(pb.TaskType.KIOSK_TO_TABLE), int(pb.TaskType.ESCORT_SERVICE)])

    def __init__(self) -> None:
        self._collector_robot_id: Optional[str] = None
        self._collection_count: int = 0
        self._lock = asyncio.Lock()

    @property
    def collector_robot_id(self) -> Optional[str]:
        return self._collector_robot_id

    async def pick_task_for_robot(
        self,
        robot_id: str,
        pending_tasks: list[pb.Task],
        battery: int,
    ) -> Optional[pb.Task]:
        """배정할 작업을 선택해 반환. 없으면 None.

        pending_tasks 는 priority DESC, created_at_ms ASC 로 정렬된 상태여야 함.
        """
        if not pending_tasks:
            return None

        async with self._lock:
            # 1. 배터리 최소 기준 미달 — 무조건 거부
            if battery < self.BATTERY_MIN_ASSIGN:
                return None

            # 2. 이 로봇이 collector 전담인 경우 → DISH_PICKUP만 선택
            if self._collector_robot_id == robot_id:
                for task in pending_tasks:
                    if int(task.task_type) == self._DISH_PICKUP:
                        return task
                # 더 이상 수거 작업 없음 → collector 해제 후 일반 작업 선택
                self._collector_robot_id = None
                self._collection_count = 0

            # 3. 다른 collector가 이미 존재 → DISH_PICKUP 제외하고 선택
            if self._collector_robot_id is not None:
                for task in pending_tasks:
                    if int(task.task_type) == self._DISH_PICKUP:
                        continue
                    if battery < self.BATTERY_MIN_HEAVY and int(task.task_type) in self._HEAVY_TYPES:
                        continue
                    return task
                return None

            # 4. collector 없음 → 큐 맨 앞에서 선택 (배터리 조건 적용)
            for task in pending_tasks:
                if battery < self.BATTERY_MIN_HEAVY and int(task.task_type) in self._HEAVY_TYPES:
                    continue
                # DISH_PICKUP이 선택되면 이 로봇을 collector로 지정
                if int(task.task_type) == self._DISH_PICKUP:
                    self._collector_robot_id = robot_id
                    self._collection_count = 0
                return task

            return None

    async def on_task_assigned(self, task: pb.Task, robot_id: str) -> None:
        """작업 배정 완료 시 호출 — collector 카운트 갱신."""
        async with self._lock:
            if int(task.task_type) == self._DISH_PICKUP and self._collector_robot_id == robot_id:
                self._collection_count += 1

    async def on_task_completed(
        self,
        task: pb.Task,
        robot_id: str,
        pending_tasks: list[pb.Task],
    ) -> None:
        """작업 완료 시 호출 — collector 해제 여부 판단."""
        async with self._lock:
            if self._collector_robot_id != robot_id:
                return
            if int(task.task_type) != self._DISH_PICKUP:
                return

            has_more_collect = any(int(t.task_type) == self._DISH_PICKUP for t in pending_tasks)
            if not has_more_collect or self._collection_count >= self.MAX_COLLECTION_BATCH:
                self._collector_robot_id = None
                self._collection_count = 0
                logger.info("Collector released from %s (count=%d)", robot_id, self._collection_count)

    def should_auto_charge(self, battery: int, has_pending_tasks: bool) -> bool:
        """충전 트리거 여부 판단 (Lock 불필요 — 읽기 전용)."""
        return battery < self.BATTERY_MIN_ASSIGN


# ──────────────────────────────────────────────────────────────────
# Dispatcher (I/O 담당)
# ──────────────────────────────────────────────────────────────────

class TaskDispatcher:
    """Policy 결정을 DB + ConnectionManager 작업으로 실행."""

    def __init__(
        self,
        db: Database,
        get_conn: asyncio.coroutines,  # type: ignore[type-arg]
        db_lock: asyncio.Lock,
        manager: "ConnectionManager",
        policy: TaskAssignmentPolicy,
    ) -> None:
        self._db = db
        self._get_conn = get_conn
        self._db_lock = db_lock
        self._manager = manager
        self._policy = policy

    # ── 외부 진입점 ────────────────────────────────────────────────

    async def try_assign_for_robot(self, robot_id: str) -> None:
        """특정 로봇에게 대기 작업을 배정 시도. TCP 세션 없으면 skip."""
        sess = await self._manager.get_session(robot_id)
        if sess is None:
            return

        battery = await self._manager.telemetry.get_battery(robot_id) or 100

        async with self._db_lock:
            conn = await self._get_conn()
            pending = await self._db.list_pending_tasks_sorted(conn)

        task = await self._policy.pick_task_for_robot(robot_id, pending, battery)
        if task is None:
            return

        await self._dispatch(task, robot_id)
        await self._policy.on_task_assigned(task, robot_id)

    async def try_assign_pending(self) -> None:
        """새 작업 생성 시: 모든 IDLE 로봇에 대해 배정 시도."""
        idle_robots = await self._get_idle_robot_ids()
        for robot_id in idle_robots:
            await self.try_assign_for_robot(robot_id)

    async def maybe_trigger_charge(self, robot_id: str, battery: int) -> None:
        """UDP 텔레메트리 수신 시 배터리 체크 → 자동 충전 커맨드 전송."""
        if not self._policy.should_auto_charge(battery, has_pending_tasks=True):
            return

        # 이미 충전 중이거나 RETURN_TO_DOCK 진행 중이면 skip
        async with self._db_lock:
            conn = await self._get_conn()
            robot_row = await conn.execute(
                "SELECT status FROM robots WHERE robot_id = ?", (robot_id,)
            )
            row = await robot_row.fetchone()

        if row is None:
            return
        current_status = int(row["status"])
        if current_status in (int(pb.RobotStatus.CHARGING), int(pb.RobotStatus.OFFLINE)):
            return

        sess = await self._manager.get_session(robot_id)
        if sess is None:
            return

        cmd_id = str(uuid.uuid4())
        now_ms = _ts_now_ms()

        # RETURN_TO_DOCK 커맨드 생성
        # ZONE_DOCK place 중 첫 번째를 찾아 target으로 설정
        async with self._db_lock:
            conn = await self._get_conn()
            dock_cur = await conn.execute(
                "SELECT place_id, x, y, theta FROM places WHERE zone = ? AND is_active = 1 LIMIT 1",
                (int(pb.ZoneType.ZONE_DOCK),),
            )
            dock_row = await dock_cur.fetchone()

        target_id   = dock_row["place_id"] if dock_row else ""
        target_x    = float(dock_row["x"]     or 0.0) if dock_row else 0.0
        target_y    = float(dock_row["y"]     or 0.0) if dock_row else 0.0
        target_theta = float(dock_row["theta"] or 0.0) if dock_row else 0.0

        cmd_pb = pb.Command(
            cmd_id=cmd_id,
            task_id="",
            robot_id=robot_id,
            command=pb.CommandType.RETURN_DOCK,
            target_id=target_id,
            target_x=target_x,
            target_y=target_y,
            target_theta=target_theta,
            status=pb.CommandStatus.SENT,
        )
        cmd_pb.sent_at.FromMilliseconds(now_ms)

        pkt = pb.TcpPacket(robot_id=robot_id, seq=sess.next_seq(), cmd_payload=cmd_pb)
        try:
            await self._manager.send_command_packet(robot_id, pkt)
            logger.info("Auto-charge triggered for robot=%s battery=%d%%", robot_id, battery)
        except Exception as e:  # noqa: BLE001
            logger.warning("Auto-charge send failed robot=%s: %s", robot_id, e)

    async def on_task_completed(self, task: pb.Task, robot_id: str) -> None:
        """작업 완료 시 policy 알림 후 다음 작업 배정 시도."""
        async with self._db_lock:
            conn = await self._get_conn()
            pending = await self._db.list_pending_tasks_sorted(conn)
        await self._policy.on_task_completed(task, robot_id, pending)
        await self.try_assign_for_robot(robot_id)

    # ── 내부 헬퍼 ──────────────────────────────────────────────────

    async def _dispatch(self, task: pb.Task, robot_id: str) -> None:
        """DB 업데이트 + TCP MOVE_TO 전송."""
        async with self._db_lock:
            conn = await self._get_conn()
            place = await self._db.get_place(conn, task.dest_id)

        target_x     = float(place["x"]     or 0.0) if place else 0.0
        target_y     = float(place["y"]     or 0.0) if place else 0.0
        target_theta = float(place["theta"] or 0.0) if place else 0.0

        cmd_id = str(uuid.uuid4())
        now_ms = _ts_now_ms()

        cmd_pb = pb.Command(
            cmd_id=cmd_id,
            task_id=task.task_id,
            robot_id=robot_id,
            command=pb.CommandType.MOVE_TO,
            target_id=task.dest_id,
            target_x=target_x,
            target_y=target_y,
            target_theta=target_theta,
            status=pb.CommandStatus.SENT,
        )
        cmd_pb.sent_at.FromMilliseconds(now_ms)

        async with self._db_lock:
            conn = await self._get_conn()
            await self._db.insert_command(
                conn,
                cmd_id=cmd_id,
                task_id=task.task_id,
                robot_id=robot_id,
                command=int(pb.CommandType.MOVE_TO),
                target_id=task.dest_id,
                status=int(pb.CommandStatus.SENT),
                sent_at_ms=now_ms,
            )
            await self._db.assign_task_robot(conn, task.task_id, robot_id)
            await self._db.update_task_status(
                conn, task_id=task.task_id, status=int(pb.TaskStatus.IN_PROGRESS)
            )
            await self._db.mark_robot_moving(conn, robot_id, current_task_id=task.task_id)

        sess = await self._manager.get_session(robot_id)
        if sess is None:
            logger.warning("Scheduler dispatch: robot %s disconnected", robot_id)
            return

        pkt = pb.TcpPacket(robot_id=robot_id, seq=sess.next_seq(), cmd_payload=cmd_pb)
        try:
            await self._manager.send_command_packet(robot_id, pkt)
            logger.info(
                "Scheduler MOVE_TO robot=%s task=%s dest=%s",
                robot_id, task.task_id, task.dest_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Scheduler dispatch send failed robot=%s: %s", robot_id, e)

    async def _get_idle_robot_ids(self) -> list[str]:
        session_ids = await self._manager.get_all_session_ids()
        idle: list[str] = []
        async with self._db_lock:
            conn = await self._get_conn()
            for rid in session_ids:
                cur = await conn.execute(
                    "SELECT status FROM robots WHERE robot_id = ?", (rid,)
                )
                row = await cur.fetchone()
                if row and int(row["status"]) == int(pb.RobotStatus.IDLE):
                    idle.append(rid)
        return idle
