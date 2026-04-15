"""ROS-free pure helpers for ACK decision and battery caching.

ROS 의존성 없이 임포트 가능 — 서버/장치 양쪽 테스트에서 사용.
"""

from __future__ import annotations

from typing import Optional

from rostaurant_networking.robotcafe.db.v1 import robotcafe_pb2 as pb

# FsmState 숫자값 (proto enum과 동일)
_FSM_ARRIVED    = int(pb.FsmState.FSM_ARRIVED)
_FSM_NAV_FAILED = int(pb.FsmState.FSM_NAV_FAILED)


def _decide_ack(fsm_state: int, pending_cmd_id: str) -> Optional[int]:
    """주행 완료/실패 FSM 상태와 대기 중인 cmd_id를 받아 전송할 AckStatus를 반환.

    Returns:
        pb.AckStatus.EXECUTED    — 도착 완료
        pb.AckStatus.ACK_FAILED  — 내비게이션 실패
        None                     — ACK 불필요 (pending_cmd_id 없거나 중간 상태)
    """
    if not pending_cmd_id:
        return None
    if fsm_state == _FSM_ARRIVED:
        return int(pb.AckStatus.EXECUTED)
    if fsm_state == _FSM_NAV_FAILED:
        return int(pb.AckStatus.ACK_FAILED)
    return None


# battery 캐시 초기값 (ros_bridge_node.RostaurantCommNode 에서 참조)
_BATTERY_INIT: int = 0
