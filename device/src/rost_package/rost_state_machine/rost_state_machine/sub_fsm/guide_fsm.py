"""
안내 Sub FSM (GUIDE)

상태:
  GUIDE_INIT             → 안내 시작, HQ의 MoveToRequester 대기
  MOVE_TO_GUIDE_REQUESTER → 안내 요청자 위치로 이동
  VERIFY_AND_SELECT      → 요청자 확인 및 목적지 수신 (HQ 응답 대기)
  GUIDE_LOOP             → 다중 안내 위치 루프 진입
  MOVE_TO_TARGET         → 안내 목적지로 이동
  VERIFY_ARRIVAL         → 안내 도착 확인 (HQ 응답 대기)
  GUIDE_END              → 안내 종료

HQ → ROBOT: MoveToRequester, GuideStart, RetryGuideStart, GuideEnd, RetryMoveToRequester
ROBOT → HQ: ArrivedAtRequester, ArrivedAtTarget
"""

from enum import Enum, auto
from typing import Callable

from rost_state_machine.utils.fsm_base import FSMBase


class GuideState(Enum):
    GUIDE_INIT = auto()               # 초기화, MoveToRequester 대기
    MOVE_TO_GUIDE_REQUESTER = auto()  # 요청자 위치로 이동 중
    VERIFY_AND_SELECT = auto()        # 요청자 확인 및 목적지 수신 대기
    GUIDE_LOOP = auto()               # 안내 루프 (다음 목적지 선택)
    MOVE_TO_TARGET = auto()           # 안내 목적지로 이동 중
    VERIFY_ARRIVAL = auto()           # 도착 확인 대기
    GUIDE_END = auto()                # 안내 종료


class GuideFSM(FSMBase):
    """안내 Sub FSM"""

    def __init__(self, node, done_callback: Callable, timeout_secs: float = 30.0):
        super().__init__(node, 'GuideFSM')
        self._done_callback = done_callback
        self._timeout_secs = timeout_secs
        self._session_id: str = ''
        self._current_target_pose = None

    def start(self) -> None:
        """FSM 시작: GUIDE_INIT 상태로 진입"""
        self._change_state(GuideState.GUIDE_INIT)

    def on_enter(self, state: GuideState) -> None:
        if state == GuideState.GUIDE_INIT:
            self._node.get_logger().info('[GuideFSM] HQ로부터 MoveToRequester 대기 중...')

        elif state == GuideState.MOVE_TO_GUIDE_REQUESTER:
            self._node.navigate_to(
                label='MOVE_TO_GUIDE_REQUESTER',
                on_arrived=self._on_arrived_at_requester
            )

        elif state == GuideState.VERIFY_AND_SELECT:
            # 도착 이벤트 전송
            self._node.publish_event('ArrivedAtRequester', self._session_id)
            self._node.get_logger().info(
                '[GuideFSM] 요청자 위치 도착. HQ의 GuideStart 또는 RetryMoveToRequester 대기...'
            )
            self._start_timeout(self._timeout_secs, self._on_verify_select_timeout)

        elif state == GuideState.GUIDE_LOOP:
            self._cancel_timeout()
            self._node.get_logger().info(
                '[GuideFSM] 안내 루프. HQ의 GuideStart(목적지) 또는 GuideEnd 대기...'
            )
            self._start_timeout(self._timeout_secs, self._on_guide_loop_timeout)

        elif state == GuideState.MOVE_TO_TARGET:
            self._cancel_timeout()
            self._node.navigate_to(
                label='MOVE_TO_TARGET',
                on_arrived=self._on_arrived_at_target
            )

        elif state == GuideState.VERIFY_ARRIVAL:
            # 목적지 도착 이벤트 전송
            self._node.publish_event('ArrivedAtTarget', self._session_id)
            self._node.get_logger().info(
                '[GuideFSM] 안내 목적지 도착. HQ의 GuideStart(다음) 또는 RetryGuideStart 대기...'
            )
            self._start_timeout(self._timeout_secs, self._on_verify_arrival_timeout)

        elif state == GuideState.GUIDE_END:
            self._cancel_timeout()
            self._node.get_logger().info('[GuideFSM] 안내 종료.')
            self._done_callback()

    def on_exit(self, state: GuideState) -> None:
        pass

    def handle_command(self, command: str, msg=None) -> bool:
        """HQ로부터 수신한 명령 처리"""
        if msg:
            self._session_id = msg.session_id

        # GUIDE_INIT: MoveToRequester 수신
        if self._state == GuideState.GUIDE_INIT:
            if command == 'MoveToRequester':
                self._node.get_logger().info(
                    f'[GuideFSM] MoveToRequester 수신. 요청자 위치: {msg.target_pose if msg else "N/A"}'
                )
                self._change_state(GuideState.MOVE_TO_GUIDE_REQUESTER)
                return True

        # VERIFY_AND_SELECT: GuideStart / RetryMoveToRequester / GuideEnd(타임아웃)
        elif self._state == GuideState.VERIFY_AND_SELECT:
            if command == 'GuideStart':
                self._node.get_logger().info('[GuideFSM] GuideStart 수신 → 안내 루프 시작')
                if msg:
                    self._current_target_pose = msg.target_pose
                self._change_state(GuideState.GUIDE_LOOP)
                self._change_state(GuideState.MOVE_TO_TARGET)
                return True
            elif command == 'RetryMoveToRequester':
                self._node.get_logger().info('[GuideFSM] RetryMoveToRequester 수신 → 요청자 재이동')
                self._change_state(GuideState.MOVE_TO_GUIDE_REQUESTER)
                return True
            elif command == 'GuideEnd':
                self._node.get_logger().info('[GuideFSM] GuideEnd(타임아웃) 수신 → 종료')
                self._change_state(GuideState.GUIDE_END)
                return True

        # GUIDE_LOOP: GuideStart(다음 목적지) / GuideEnd
        elif self._state == GuideState.GUIDE_LOOP:
            if command == 'GuideStart':
                self._node.get_logger().info('[GuideFSM] GuideStart(다음 목적지) 수신 → 이동 시작')
                if msg:
                    self._current_target_pose = msg.target_pose
                self._change_state(GuideState.MOVE_TO_TARGET)
                return True
            elif command == 'GuideEnd':
                self._node.get_logger().info('[GuideFSM] GuideEnd 수신 → 안내 종료')
                self._change_state(GuideState.GUIDE_END)
                return True

        # VERIFY_ARRIVAL: GuideStart(다음) / RetryGuideStart / GuideEnd
        elif self._state == GuideState.VERIFY_ARRIVAL:
            if command == 'GuideStart':
                self._node.get_logger().info(
                    '[GuideFSM] GuideStart(다음 목적지 또는 OK) 수신 → 루프 재진입'
                )
                if msg:
                    self._current_target_pose = msg.target_pose
                self._change_state(GuideState.GUIDE_LOOP)
                self._change_state(GuideState.MOVE_TO_TARGET)
                return True
            elif command == 'RetryGuideStart':
                self._node.get_logger().info('[GuideFSM] RetryGuideStart 수신 → 동일 목적지 재이동')
                self._change_state(GuideState.MOVE_TO_TARGET)
                return True
            elif command == 'GuideEnd':
                self._node.get_logger().info('[GuideFSM] GuideEnd 수신 → 안내 종료')
                self._change_state(GuideState.GUIDE_END)
                return True

        self._node.get_logger().warn(
            f'[GuideFSM] 처리되지 않은 명령: {command} (현재 상태: {self._state})'
        )
        return False

    # ------------------------------------------------------------------ #
    # 내부 콜백                                                            #
    # ------------------------------------------------------------------ #

    def _on_arrived_at_requester(self) -> None:
        if self._state == GuideState.MOVE_TO_GUIDE_REQUESTER:
            self._change_state(GuideState.VERIFY_AND_SELECT)

    def _on_arrived_at_target(self) -> None:
        if self._state == GuideState.MOVE_TO_TARGET:
            self._change_state(GuideState.VERIFY_ARRIVAL)

    def _on_verify_select_timeout(self) -> None:
        self._node.get_logger().warn('[GuideFSM] VERIFY_AND_SELECT 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_verify_select_timeout)

    def _on_guide_loop_timeout(self) -> None:
        self._node.get_logger().warn('[GuideFSM] GUIDE_LOOP 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_guide_loop_timeout)

    def _on_verify_arrival_timeout(self) -> None:
        self._node.get_logger().warn('[GuideFSM] VERIFY_ARRIVAL 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_verify_arrival_timeout)
