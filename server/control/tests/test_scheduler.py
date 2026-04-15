"""Unit tests for TaskAssignmentPolicy.

I/O 없이 순수 로직만 검증 — pytest로 빠르게 실행 가능.
"""

import asyncio
import sys
import os

# server/control 을 import path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock

from robotcafe.db.v1 import robotcafe_pb2 as pb
from scheduler import TaskAssignmentPolicy


# ──────────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────────

def make_task(task_type: int, priority: int = int(pb.TaskPriority.NORMAL)) -> pb.Task:
    t = pb.Task()
    t.task_id = f"task-{task_type}-{priority}"
    t.task_type = task_type
    t.priority = priority
    t.status = int(pb.TaskStatus.PENDING)
    t.dest_id = "TBL_01"
    return t


DISH    = int(pb.TaskType.DISH_PICKUP)
SERVE   = int(pb.TaskType.KIOSK_TO_TABLE)
ESCORT  = int(pb.TaskType.ESCORT_SERVICE)
GUIDE   = int(pb.TaskType.TABLE_TO_TOILET)


# ──────────────────────────────────────────────────────────────────
# 배터리 게이트
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_battery_too_low_blocks_all_assignment():
    policy = TaskAssignmentPolicy()
    tasks = [make_task(SERVE), make_task(DISH)]
    result = await policy.pick_task_for_robot("R1", tasks, battery=15)
    assert result is None


@pytest.mark.asyncio
async def test_battery_exact_minimum_allows_assignment():
    policy = TaskAssignmentPolicy()
    tasks = [make_task(GUIDE)]
    result = await policy.pick_task_for_robot("R1", tasks, battery=20)
    assert result is not None


@pytest.mark.asyncio
async def test_battery_below_heavy_threshold_skips_heavy_tasks():
    """배터리 20~24% 구간: 서빙/에스코트 skip, 가벼운 작업은 받음."""
    policy = TaskAssignmentPolicy()
    tasks = [make_task(SERVE), make_task(GUIDE)]
    result = await policy.pick_task_for_robot("R1", tasks, battery=22)
    assert result is not None
    assert int(result.task_type) == GUIDE


@pytest.mark.asyncio
async def test_battery_below_heavy_threshold_skips_escort():
    policy = TaskAssignmentPolicy()
    tasks = [make_task(ESCORT), make_task(DISH)]
    result = await policy.pick_task_for_robot("R1", tasks, battery=22)
    # DISH_PICKUP 은 heavy type 아님 → 선택됨
    assert result is not None
    assert int(result.task_type) == DISH


# ──────────────────────────────────────────────────────────────────
# Collector 지정
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dish_pickup_assigns_collector():
    """DISH_PICKUP 작업을 받으면 그 로봇이 collector로 지정된다."""
    policy = TaskAssignmentPolicy()
    tasks = [make_task(DISH)]
    result = await policy.pick_task_for_robot("R1", tasks, battery=80)
    assert result is not None
    assert int(result.task_type) == DISH
    assert policy.collector_robot_id == "R1"


@pytest.mark.asyncio
async def test_non_dish_task_does_not_set_collector():
    policy = TaskAssignmentPolicy()
    tasks = [make_task(SERVE)]
    await policy.pick_task_for_robot("R1", tasks, battery=80)
    assert policy.collector_robot_id is None


# ──────────────────────────────────────────────────────────────────
# Collector 전담 로직
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collector_robot_only_gets_dish_pickup():
    """collector로 지정된 로봇은 DISH_PICKUP만 받는다."""
    policy = TaskAssignmentPolicy()
    # R1을 먼저 collector로 지정
    await policy.pick_task_for_robot("R1", [make_task(DISH)], battery=80)
    assert policy.collector_robot_id == "R1"

    # 이제 SERVE + DISH 혼합 큐에서 R1은 DISH만 선택해야 함
    tasks = [make_task(SERVE), make_task(DISH, priority=int(pb.TaskPriority.HIGH))]
    result = await policy.pick_task_for_robot("R1", tasks, battery=80)
    assert result is not None
    assert int(result.task_type) == DISH


@pytest.mark.asyncio
async def test_non_collector_skips_dish_pickup_when_collector_exists():
    """collector가 있을 때 다른 로봇은 DISH_PICKUP 건너뜀."""
    policy = TaskAssignmentPolicy()
    await policy.pick_task_for_robot("R1", [make_task(DISH)], battery=80)

    tasks = [make_task(DISH), make_task(SERVE)]
    result = await policy.pick_task_for_robot("R2", tasks, battery=80)
    assert result is not None
    assert int(result.task_type) == SERVE


@pytest.mark.asyncio
async def test_non_collector_returns_none_if_only_dish_in_queue():
    """큐에 DISH_PICKUP만 있을 때 non-collector 로봇은 None."""
    policy = TaskAssignmentPolicy()
    await policy.pick_task_for_robot("R1", [make_task(DISH)], battery=80)

    tasks = [make_task(DISH)]
    result = await policy.pick_task_for_robot("R2", tasks, battery=80)
    assert result is None


# ──────────────────────────────────────────────────────────────────
# Collector 해제
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collector_released_when_no_more_dish_in_pending():
    policy = TaskAssignmentPolicy()
    dish_task = make_task(DISH)
    await policy.pick_task_for_robot("R1", [dish_task], battery=80)

    # 완료 후 pending에 DISH 없음
    await policy.on_task_completed(dish_task, "R1", pending_tasks=[make_task(SERVE)])
    assert policy.collector_robot_id is None


@pytest.mark.asyncio
async def test_collector_released_after_max_batch():
    policy = TaskAssignmentPolicy()
    # collection_count를 MAX_COLLECTION_BATCH 까지 채움
    dish_task = make_task(DISH)
    await policy.pick_task_for_robot("R1", [dish_task], battery=80)

    for _ in range(policy.MAX_COLLECTION_BATCH):
        await policy.on_task_assigned(dish_task, "R1")

    # pending에 DISH 있어도 batch 초과 → collector 해제
    await policy.on_task_completed(dish_task, "R1", pending_tasks=[make_task(DISH)])
    assert policy.collector_robot_id is None


@pytest.mark.asyncio
async def test_collector_not_released_if_more_dish_and_batch_not_full():
    policy = TaskAssignmentPolicy()
    dish_task = make_task(DISH)
    await policy.pick_task_for_robot("R1", [dish_task], battery=80)
    await policy.on_task_assigned(dish_task, "R1")

    # pending에 DISH 남아있고 batch 미달
    await policy.on_task_completed(dish_task, "R1", pending_tasks=[make_task(DISH)])
    assert policy.collector_robot_id == "R1"


@pytest.mark.asyncio
async def test_collector_auto_released_when_no_dish_in_queue_during_pick():
    """collector인데 큐에 DISH가 없으면 pick 시 collector 해제 후 일반 작업 선택."""
    policy = TaskAssignmentPolicy()
    await policy.pick_task_for_robot("R1", [make_task(DISH)], battery=80)
    assert policy.collector_robot_id == "R1"

    # 이제 큐에 DISH 없음
    tasks = [make_task(SERVE)]
    result = await policy.pick_task_for_robot("R1", tasks, battery=80)
    assert result is not None
    assert int(result.task_type) == SERVE
    assert policy.collector_robot_id is None


# ──────────────────────────────────────────────────────────────────
# 자동 충전 트리거
# ──────────────────────────────────────────────────────────────────

def test_should_auto_charge_below_threshold():
    policy = TaskAssignmentPolicy()
    assert policy.should_auto_charge(battery=15, has_pending_tasks=True) is True
    assert policy.should_auto_charge(battery=19, has_pending_tasks=False) is True


def test_no_auto_charge_above_threshold():
    policy = TaskAssignmentPolicy()
    assert policy.should_auto_charge(battery=20, has_pending_tasks=True) is False
    assert policy.should_auto_charge(battery=80, has_pending_tasks=False) is False


# ──────────────────────────────────────────────────────────────────
# 빈 큐
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_queue_returns_none():
    policy = TaskAssignmentPolicy()
    result = await policy.pick_task_for_robot("R1", [], battery=80)
    assert result is None
