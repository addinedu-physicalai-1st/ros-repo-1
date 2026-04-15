"""Unit tests for ros_bridge ack_logic pure helpers.

ROS 없이 실행 가능 — protobuf enum 값만 사용.
"""

import sys
import os

# ack_logic.py 가 있는 패키지를 sys.path에 추가
_DEVICE_PKG = os.path.join(
    os.path.dirname(__file__),
    "../../../device/rostaurant/src/rostaurant_networking",
)
sys.path.insert(0, _DEVICE_PKG)
# server/control protobuf도 참조 (robotcafe_pb2)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from robotcafe.db.v1 import robotcafe_pb2 as pb
from rostaurant_networking.ack_logic import _decide_ack, _BATTERY_INIT

FSM_IDLE         = int(pb.FsmState.FSM_IDLE)
FSM_MOVING_TO_WP = int(pb.FsmState.FSM_MOVING_TO_WP)
FSM_ARRIVED      = int(pb.FsmState.FSM_ARRIVED)
FSM_NAV_FAILED   = int(pb.FsmState.FSM_NAV_FAILED)


# ──────────────────────────────────────────────────────────────────
# _decide_ack: ACK 결정 순수 함수
# ──────────────────────────────────────────────────────────────────

def test_arrived_with_pending_cmd_returns_executed():
    """FSM_ARRIVED + pending_cmd_id → AckStatus.EXECUTED"""
    result = _decide_ack(FSM_ARRIVED, "cmd-123")
    assert result == int(pb.AckStatus.EXECUTED)


def test_nav_failed_with_pending_cmd_returns_ack_failed():
    """FSM_NAV_FAILED + pending_cmd_id → AckStatus.ACK_FAILED"""
    result = _decide_ack(FSM_NAV_FAILED, "cmd-123")
    assert result == int(pb.AckStatus.ACK_FAILED)


def test_arrived_without_pending_cmd_returns_none():
    """pending_cmd_id 없으면 None"""
    result = _decide_ack(FSM_ARRIVED, "")
    assert result is None


def test_nav_failed_without_pending_cmd_returns_none():
    """pending_cmd_id 없으면 None"""
    result = _decide_ack(FSM_NAV_FAILED, "")
    assert result is None


def test_moving_state_returns_none():
    """이동 중 상태는 ACK 불필요"""
    result = _decide_ack(FSM_MOVING_TO_WP, "cmd-123")
    assert result is None


def test_idle_state_returns_none():
    """IDLE 상태는 ACK 불필요"""
    result = _decide_ack(FSM_IDLE, "cmd-123")
    assert result is None


# ──────────────────────────────────────────────────────────────────
# _BATTERY_INIT: 배터리 캐시 초기값
# ──────────────────────────────────────────────────────────────────

def test_battery_init_is_zero():
    """배터리 캐시 초기값은 0."""
    assert _BATTERY_INIT == 0
