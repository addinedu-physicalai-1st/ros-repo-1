"""ROS-free pure helpers for ACK decision, event mapping, and battery caching.

ROS 의존성 없이 임포트 가능 — 서버/장치 양쪽 테스트에서 사용.
"""

from __future__ import annotations

from typing import Optional

from rostaurant_networking.robotcafe.db.v1 import robotcafe_pb2 as pb

# FsmState 숫자값 (proto enum과 동일)
_FSM_ARRIVED    = int(pb.FsmState.FSM_ARRIVED)
_FSM_NAV_FAILED = int(pb.FsmState.FSM_NAV_FAILED)

# CommandType 숫자값
_CMD_FOLLOW    = int(pb.CommandType.FOLLOW_CMD)
_CMD_COLLECT   = int(pb.CommandType.COLLECT_CMD)
_CMD_DELIVERY  = int(pb.CommandType.DELIVERY_CMD)
_CMD_GUIDE     = int(pb.CommandType.GUIDE_CMD)

# FollowAction / CollectionAction / DeliveryAction / GuidanceAction (도착 관련)
_FOLLOW_MOVE_TO_REQUESTER    = int(pb.FollowAction.FOLLOW_MOVE_TO_REQUESTER)
_FOLLOW_GO_TO_TABLE          = int(pb.FollowAction.FOLLOW_GO_TO_TABLE)
_COLLECT_MOVE_TO_REQUESTER   = int(pb.CollectionAction.COLLECT_MOVE_TO_REQUESTER)
_COLLECT_MOVE_TO_DISHWASHING = int(pb.CollectionAction.COLLECT_MOVE_TO_DISHWASHING)
_DELIVERY_MOVE_TO_KITCHEN    = int(pb.DeliveryAction.DELIVERY_MOVE_TO_KITCHEN)
_DELIVERY_START              = int(pb.DeliveryAction.DELIVERY_START)
_GUIDANCE_MOVE_TO_REQUESTER  = int(pb.GuidanceAction.GUIDANCE_MOVE_TO_REQUESTER)
_GUIDANCE_START              = int(pb.GuidanceAction.GUIDANCE_START)


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


def _decide_task_event(
    fsm_state: int,
    cmd_type: int,
    task_action: int,
    event_type_override: int = 0,
) -> Optional[int]:
    """현재 FSM 상태 + 커맨드 컨텍스트로부터 보낼 TaskEventType을 결정.

    task_executor 가 RobotTaskStatus.event_type에 명시적으로 값을 설정한 경우
    (event_type_override != 0) 해당 값을 우선 사용한다.

    Returns:
        TaskEventType int 값, 또는 이벤트 불필요 시 None
    """
    if event_type_override != 0:
        return event_type_override

    if fsm_state != _FSM_ARRIVED:
        return None

    # 커맨드 타입별 도착 이벤트 매핑
    if cmd_type == _CMD_FOLLOW:
        if task_action == _FOLLOW_MOVE_TO_REQUESTER:
            return int(pb.TaskEventType.ARRIVED_AT_REQUESTER)
        if task_action == _FOLLOW_GO_TO_TABLE:
            return int(pb.TaskEventType.ARRIVED_AT_TABLE)

    elif cmd_type == _CMD_COLLECT:
        if task_action == _COLLECT_MOVE_TO_REQUESTER:
            return int(pb.TaskEventType.ARRIVED_AT_REQUESTER)
        if task_action == _COLLECT_MOVE_TO_DISHWASHING:
            return int(pb.TaskEventType.ARRIVED_AT_DISHWASHING)

    elif cmd_type == _CMD_DELIVERY:
        if task_action == _DELIVERY_MOVE_TO_KITCHEN:
            return int(pb.TaskEventType.ARRIVED_AT_KITCHEN)
        if task_action == _DELIVERY_START:
            return int(pb.TaskEventType.ARRIVED_AT_MENU_LOCATION)

    elif cmd_type == _CMD_GUIDE:
        if task_action == _GUIDANCE_MOVE_TO_REQUESTER:
            return int(pb.TaskEventType.ARRIVED_AT_REQUESTER)
        if task_action == _GUIDANCE_START:
            return int(pb.TaskEventType.ARRIVED_AT_DESTINATION)

    return None


# battery 캐시 초기값 (ros_bridge_node.RostaurantCommNode 에서 참조)
_BATTERY_INIT: int = 0
