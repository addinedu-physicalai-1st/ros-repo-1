"""
동행 Sub FSM (FOLLOW)

상태:
  FOLLOW_INIT        → 동행 시작, HQ의 FollowRequest 대기
  MOVE_TO_REQUESTER  → 요청자 위치로 이동
  VERIFY_REQUESTER   → 요청자 확인 (HQ 응답 대기)
  FOLLOWING          → 요청자와 함께 이동
  FOLLOW_END         → 동행 종료

HQ → ROBOT 명령: FollowRequest, FollowStart, FollowEnd, RetryFollowRequest
ROBOT → HQ 이벤트: ArrivedAtRequester, NearTableFor1Min
"""

from enum import Enum, auto
from typing import Callable, Optional

from rost_state_machine.utils.fsm_base import FSMBase


class FollowState(Enum):
    FOLLOW_INIT = auto()        # 동행 초기화, FollowRequest 대기
    MOVE_TO_REQUESTER = auto()  # 요청자 위치로 이동 중
    VERIFY_REQUESTER = auto()   # 요청자 확인 중 (HQ 응답 대기)
    FOLLOWING = auto()          # 요청자와 함께 이동 중
    FOLLOW_END = auto()         # 동행 종료


class FollowFSM(FSMBase):
    """동행 Sub FSM"""

    def __init__(self, node, done_callback: Callable, timeout_secs: float = 30.0):
        """
        :param node: ROS2 노드
        :param done_callback: 동행 완료 시 TopFSM에 알리는 콜백
        :param timeout_secs: VERIFY 상태 타임아웃 시간 (초)
        """
        super().__init__(node, 'FollowFSM')
        self._done_callback = done_callback
        self._timeout_secs = timeout_secs
        self._session_id: str = ''
        self._near_table_timer: Optional[object] = None  # 1분 타이머

    def start(self) -> None:
        """FSM 시작: FOLLOW_INIT 상태로 진입"""
        self._change_state(FollowState.FOLLOW_INIT)

    def on_enter(self, state: FollowState) -> None:
        if state == FollowState.FOLLOW_INIT:
            self._node.get_logger().info('[FollowFSM] HQ로부터 FollowRequest 대기 중...')

        elif state == FollowState.MOVE_TO_REQUESTER:
            # 요청자 위치로 내비게이션 시작
            self._node.navigate_to(
                label='MOVE_TO_REQUESTER',
                on_arrived=self._on_arrived_at_requester
            )

        elif state == FollowState.VERIFY_REQUESTER:
            # HQ에 도착 이벤트 전송
            self._node.publish_event('ArrivedAtRequester', self._session_id)
            # 타임아웃 시작 (HQ 응답 없을 경우)
            self._start_timeout(
                self._timeout_secs,
                self._on_verify_timeout
            )

        elif state == FollowState.FOLLOWING:
            self._cancel_timeout()
            self._node.get_logger().info('[FollowFSM] 동행 시작. HQ의 FollowEnd 대기 중...')
            # 1분 후 테이블 근처 이벤트 전송
            self._near_table_timer = self._node.create_timer(
                60.0,
                self._on_near_table_1min
            )

        elif state == FollowState.FOLLOW_END:
            self._cancel_timeout()
            self._cancel_near_table_timer()
            self._node.get_logger().info('[FollowFSM] 동행 종료.')
            # TopFSM에 완료 알림
            self._done_callback()

    def on_exit(self, state: FollowState) -> None:
        if state == FollowState.FOLLOWING:
            self._cancel_near_table_timer()

    def handle_command(self, command: str, msg=None) -> bool:
        """HQ로부터 수신한 명령 처리"""
        self._session_id = msg.session_id if msg else self._session_id

        # FOLLOW_INIT: FollowRequest 수신 → 요청자 위치로 이동
        if self._state == FollowState.FOLLOW_INIT:
            if command == 'FollowRequest':
                self._node.get_logger().info(
                    f'[FollowFSM] FollowRequest 수신. 목표: {msg.target_pose if msg else "N/A"}'
                )
                self._change_state(FollowState.MOVE_TO_REQUESTER)
                return True

        # VERIFY_REQUESTER: FollowStart / RetryFollowRequest / FollowEnd(타임아웃)
        elif self._state == FollowState.VERIFY_REQUESTER:
            if command == 'FollowStart':
                self._node.get_logger().info('[FollowFSM] FollowStart 수신 → 동행 시작')
                self._change_state(FollowState.FOLLOWING)
                return True
            elif command == 'RetryFollowRequest':
                self._node.get_logger().info('[FollowFSM] RetryFollowRequest 수신 → 재이동')
                self._change_state(FollowState.MOVE_TO_REQUESTER)
                return True
            elif command == 'FollowEnd':
                self._node.get_logger().info('[FollowFSM] FollowEnd(타임아웃) 수신 → 종료')
                self._change_state(FollowState.FOLLOW_END)
                return True

        # FOLLOWING: FollowEnd 수신 → 종료
        elif self._state == FollowState.FOLLOWING:
            if command == 'FollowEnd':
                self._node.get_logger().info('[FollowFSM] FollowEnd 수신 → 동행 종료')
                self._change_state(FollowState.FOLLOW_END)
                return True

        self._node.get_logger().warn(
            f'[FollowFSM] 처리되지 않은 명령: {command} (현재 상태: {self._state})'
        )
        return False

    # ------------------------------------------------------------------ #
    # 내부 콜백                                                            #
    # ------------------------------------------------------------------ #

    def _on_arrived_at_requester(self) -> None:
        """요청자 위치 도착 시 호출"""
        if self._state == FollowState.MOVE_TO_REQUESTER:
            self._change_state(FollowState.VERIFY_REQUESTER)

    def _on_verify_timeout(self) -> None:
        """VERIFY_REQUESTER 타임아웃 발생 시: HQ에 이벤트 전송 후 대기 유지"""
        self._node.get_logger().warn(
            '[FollowFSM] VERIFY 타임아웃. HQ에 TimeoutWaiting 이벤트 전송 후 대기 재시작.'
        )
        self._node.publish_event('TimeoutWaiting', self._session_id)
        # 다시 타임아웃 대기 (HQ 명령 올 때까지 반복)
        self._start_timeout(self._timeout_secs, self._on_verify_timeout)

    def _on_near_table_1min(self) -> None:
        """1분간 테이블 근처 머문 경우 HQ에 이벤트 전송"""
        self._cancel_near_table_timer()
        if self._state == FollowState.FOLLOWING:
            self._node.publish_event('NearTableFor1Min', self._session_id)
            self._node.get_logger().info('[FollowFSM] NearTableFor1Min 이벤트 퍼블리시')

    def _cancel_near_table_timer(self) -> None:
        if self._near_table_timer is not None:
            self._near_table_timer.cancel()
            self._near_table_timer = None
