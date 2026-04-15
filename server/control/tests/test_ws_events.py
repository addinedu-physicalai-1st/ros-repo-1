"""WS 이벤트 브로드캐스트 테스트.

broker.broadcast() 가 올바른 이벤트를 올바른 시점에 호출하는지 검증.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from robotcafe.db.v1 import robotcafe_pb2 as pb
from ws_broker import WSBroker


# ──────────────────────────────────────────────────────────────────
# WSBroker.broadcast 호출 캡처 헬퍼
# ──────────────────────────────────────────────────────────────────

def _make_broker() -> tuple[WSBroker, list[dict]]:
    """실제 WSBroker 인스턴스 + 브로드캐스트 이벤트 캡처 리스트."""
    broker = WSBroker()
    captured: list[dict] = []

    async def _capture(data: dict) -> None:
        captured.append(data)

    broker.broadcast = _capture  # type: ignore[method-assign]
    return broker, captured


# ──────────────────────────────────────────────────────────────────
# scheduler._dispatch → task_assigned 이벤트
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_broadcasts_task_assigned():
    """_dispatch 실행 후 broker에 task_assigned 이벤트가 전달돼야 한다."""
    from scheduler import TaskDispatcher, TaskAssignmentPolicy

    broker, captured = _make_broker()

    task = pb.Task()
    task.task_id = "t-001"
    task.dest_id = "TBL_01"
    task.task_type = int(pb.TaskType.KIOSK_TO_TABLE)

    db = MagicMock()
    db.get_place = AsyncMock(return_value={"x": 1.0, "y": 2.0, "theta": 0.0})
    db.insert_command = AsyncMock()
    db.assign_task_robot = AsyncMock()
    db.update_task_status = AsyncMock()
    db.mark_robot_moving = AsyncMock()

    conn_mock = AsyncMock()
    db_lock = asyncio.Lock()

    async def get_conn():
        return conn_mock

    sess_mock = MagicMock()
    sess_mock.next_seq.return_value = 1
    manager = MagicMock()
    manager.get_session = AsyncMock(return_value=sess_mock)
    manager.send_command_packet = AsyncMock()

    dispatcher = TaskDispatcher(
        db=db,
        get_conn=get_conn,
        db_lock=db_lock,
        manager=manager,
        policy=TaskAssignmentPolicy(),
        broker=broker,
    )

    await dispatcher._dispatch(task, "PNK01")

    events = [e["event"] for e in captured]
    assert "task_assigned" in events, f"task_assigned not in {events}"
    assigned = next(e for e in captured if e["event"] == "task_assigned")
    assert assigned["task_id"] == "t-001"
    assert assigned["robot_id"] == "PNK01"


# ──────────────────────────────────────────────────────────────────
# connection_manager._handle_command_ack(EXECUTED) → task_completed 이벤트
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_command_ack_executed_broadcasts_task_completed():
    """EXECUTED ACK 수신 시 broker에 task_completed 이벤트가 전달돼야 한다."""
    from connection_manager import ConnectionManager

    broker, captured = _make_broker()

    db = MagicMock()
    row_mock = {"task_id": "t-002", "robot_id": "PNK01"}
    db.get_command = AsyncMock(return_value=row_mock)
    db.update_command_status = AsyncMock()
    db.update_task_status = AsyncMock()

    conn_mock = AsyncMock()
    db_lock = asyncio.Lock()

    async def get_conn():
        return conn_mock

    manager = ConnectionManager(
        db=db,
        get_conn=get_conn,
        db_lock=db_lock,
        broker=broker,
    )

    ack = pb.CommandAck()
    ack.cmd_id = "cmd-abc"
    ack.robot_id = "PNK01"
    ack.status = pb.AckStatus.EXECUTED

    await manager._handle_command_ack(ack)

    events = [e["event"] for e in captured]
    assert "task_completed" in events, f"task_completed not in {events}"
    completed = next(e for e in captured if e["event"] == "task_completed")
    assert completed["task_id"] == "t-002"
    assert completed["robot_id"] == "PNK01"


# ──────────────────────────────────────────────────────────────────
# main.create_task → task_created 이벤트 (broker 주입 검증)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_task_broadcasts_task_created():
    """작업 생성 API가 broker에 task_created 이벤트를 전달해야 한다."""
    from fastapi.testclient import TestClient
    import main as ctrl_main

    broker, captured = _make_broker()

    # DB mock
    created_task = pb.Task()
    created_task.task_id = "t-003"
    created_task.dest_id = "TBL_01"
    created_task.status = int(pb.TaskStatus.PENDING)
    created_task.robot_id = ""

    db_mock = MagicMock()
    db_mock.place_exists_active = AsyncMock(return_value=True)
    db_mock.create_task = AsyncMock(return_value=created_task)

    conn_mock = AsyncMock()
    dispatcher_mock = MagicMock()
    dispatcher_mock.try_assign_pending = AsyncMock()

    # app.state patch
    from fastapi.testclient import TestClient
    app = ctrl_main.app

    async def override_lifespan():
        pass

    with patch.object(app, "state") as state_mock:
        state_mock.db = db_mock
        state_mock.conn = conn_mock
        state_mock.db_lock = asyncio.Lock()
        state_mock.broker = broker
        state_mock.dispatcher = dispatcher_mock

        # auth bypass: 관리자 권한
        from auth import CurrentUser, Permission
        admin_user = CurrentUser(
            user_id="admin",
            role=int(pb.UserRole.ADMIN),
            api_key_hash="",
        )
        app.dependency_overrides[ctrl_main.require(Permission.TASK_CREATE)] = lambda: admin_user

        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/tasks",
                json={"dest_id": "TBL_01", "task_type": 1},
                headers={"Authorization": "Bearer test"},
            )

        app.dependency_overrides.clear()

    # 이벤트 검증
    await asyncio.sleep(0)  # create_task 내부 asyncio.create_task 실행 기회 제공
    events = [e["event"] for e in captured]
    assert "task_created" in events, f"task_created not in {events}"
    created_ev = next(e for e in captured if e["event"] == "task_created")
    assert created_ev["task_id"] == "t-003"
