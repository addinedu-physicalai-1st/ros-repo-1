"""
동행 Sub FSM (FOLLOW)

상태:
  FOLLOW_INIT           → 동행 시작, HQ의 FollowRequest 대기
  MOVE_TO_REQUESTER     → 요청자 위치로 이동
  VERIFY_REQUESTER      → 요청자 확인 (HQ 응답 대기)
  FOLLOWING             → 요청자와 함께 이동 (1분 타이머)
  FOLLOW_COMPLETE_CHECK → NearTableFor1Min 이후 완료 또는 테이블 이동 대기
  MOVE_TO_TABLE         → 테이블로 이동 중
  TABLE_END_CHECK       → 테이블 도착 후 종료 또는 동행 재시작 대기
  FOLLOW_END            → 동행 종료

HQ → ROBOT: FollowRequest, FollowStart, RetryFollowRequest, FollowEnd,
             GoToTable, RestartFollowStart
ROBOT → HQ: ArrivedAtRequester, NearTableFor1Min, ArrivedAtTable
"""

from enum import Enum, auto
from typing import Callable, Optional

from rostaurant_state_machine.utils.fsm_base import FSMBase


class FollowState(Enum):
    FOLLOW_INIT = auto()              # 초기화, FollowRequest 대기
    MOVE_TO_REQUESTER = auto()        # 요청자 위치로 이동 중
    VERIFY_REQUESTER = auto()         # 요청자 확인 중 (HQ 응답 대기)
    FOLLOWING = auto()                # 요청자와 함께 이동 중 (1분 타이머)
    FOLLOW_COMPLETE_CHECK = auto()    # NearTableFor1Min 후 완료/테이블 대기
    MOVE_TO_TABLE = auto()            # 테이블로 이동 중
    TABLE_END_CHECK = auto()          # 테이블 도착 후 종료/재시작 대기
    FOLLOW_END = auto()               # 동행 종료


class FollowFSM(FSMBase):
    """동행 Sub FSM"""

    def __init__(self, node, done_callback: Callable, timeout_secs: float = 30.0):
        super().__init__(node, 'FollowFSM')
        self._done_callback = done_callback
        self._timeout_secs = timeout_secs
        self._session_id: str = ''
        self._near_table_timer: Optional[object] = None  # 1분 타이머
        self._table_pose = None                           # GoToTable 목적지

    def start(self) -> None:
        self._change_state(FollowState.FOLLOW_INIT)

    # ------------------------------------------------------------------ #
    # on_enter                                                             #
    # ------------------------------------------------------------------ #

    def on_enter(self, state: FollowState) -> None:
        if state == FollowState.FOLLOW_INIT:
            self._node.get_logger().info('[FollowFSM] HQ로부터 FollowRequest 대기 중...')

        elif state == FollowState.MOVE_TO_REQUESTER:
            self._node.navigate_to(
                label='MOVE_TO_REQUESTER',
                on_arrived=self._on_arrived_at_requester
            )

        elif state == FollowState.VERIFY_REQUESTER:
            # use_function_nodes=False 일 때만 FSM이 직접 이벤트를 publish한다.
            # use_function_nodes=True 일 때는 follow_function_node가 이미 publish했다.
            if not self._node.get_parameter('use_function_nodes').value:
                self._node.publish_event('ArrivedAtRequester', self._session_id)
            self._node.get_logger().info(
                '[FollowFSM] 요청자 위치 도착. HQ의 FollowStart / RetryFollowRequest 대기...'
            )
            self._start_timeout(self._timeout_secs, self._on_verify_timeout)

        elif state == FollowState.FOLLOWING:
            self._cancel_timeout()
            self._node.get_logger().info(
                '[FollowFSM] 동행 시작. 1분 후 NearTableFor1Min 이벤트 예정.'
            )
            self._cancel_near_table_timer()
            self._near_table_timer = self._node.create_timer(
                60.0, self._on_near_table_1min
            )

        elif state == FollowState.FOLLOW_COMPLETE_CHECK:
            self._cancel_timeout()
            self._node.get_logger().info(
                '[FollowFSM] 동행 완료 확인 중. HQ의 FollowEnd 또는 GoToTable 대기...'
            )
            self._start_timeout(self._timeout_secs, self._on_complete_check_timeout)

        elif state == FollowState.MOVE_TO_TABLE:
            self._cancel_timeout()
            self._node.navigate_to(
                label='MOVE_TO_TABLE',
                on_arrived=self._on_arrived_at_table
            )

        elif state == FollowState.TABLE_END_CHECK:
            # use_function_nodes=False 일 때만 FSM이 직접 이벤트를 publish한다.
            if not self._node.get_parameter('use_function_nodes').value:
                self._node.publish_event('ArrivedAtTable', self._session_id)
            self._node.get_logger().info(
                '[FollowFSM] 테이블 도착. HQ의 FollowEnd 또는 RestartFollowStart 대기...'
            )
            self._start_timeout(self._timeout_secs, self._on_table_end_timeout)

        elif state == FollowState.FOLLOW_END:
            self._cancel_timeout()
            self._cancel_near_table_timer()
            self._node.get_logger().info('[FollowFSM] 동행 종료.')
            self._done_callback()

    def on_exit(self, state: FollowState) -> None:
        if state == FollowState.FOLLOWING:
            self._cancel_near_table_timer()

    # ------------------------------------------------------------------ #
    # handle_command                                                        #
    # ------------------------------------------------------------------ #

    def handle_command(self, command: str, msg=None) -> bool:
        if msg:
            self._session_id = msg.session_id

        # FOLLOW_INIT: FollowRequest 수신 → 요청자 위치로 이동
        if self._state == FollowState.FOLLOW_INIT:
            if command == 'FollowRequest':
                self._node.get_logger().info(
                    f'[FollowFSM] FollowRequest 수신. 목표: '
                    f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}' if msg else 'N/A'
                )
                self._change_state(FollowState.MOVE_TO_REQUESTER)
                return True

        # VERIFY_REQUESTER: FollowStart / RetryFollowRequest / FollowEnd(타임아웃)
        elif self._state == FollowState.VERIFY_REQUESTER:
            if command == 'FollowStart':
                self._node.get_logger().info('[FollowFSM] FollowStart → 동행 시작')
                self._change_state(FollowState.FOLLOWING)
                return True
            elif command == 'RetryFollowRequest':
                self._node.get_logger().info('[FollowFSM] RetryFollowRequest → 재이동')
                self._change_state(FollowState.MOVE_TO_REQUESTER)
                return True
            elif command == 'FollowEnd':
                self._node.get_logger().info('[FollowFSM] FollowEnd(타임아웃) → 종료')
                self._change_state(FollowState.FOLLOW_END)
                return True

        # FOLLOWING: FollowEnd(조기 종료)
        elif self._state == FollowState.FOLLOWING:
            if command == 'FollowEnd':
                self._node.get_logger().info('[FollowFSM] FollowEnd(조기 종료) → 동행 종료')
                self._change_state(FollowState.FOLLOW_END)
                return True

        # FOLLOW_COMPLETE_CHECK: FollowEnd / GoToTable
        elif self._state == FollowState.FOLLOW_COMPLETE_CHECK:
            if command == 'FollowEnd':
                self._node.get_logger().info('[FollowFSM] FollowEnd → 동행 종료')
                self._change_state(FollowState.FOLLOW_END)
                return True
            elif command == 'GoToTable':
                self._node.get_logger().info(
                    f'[FollowFSM] GoToTable → 테이블로 이동: '
                    f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}' if msg else 'N/A'
                )
                self._change_state(FollowState.MOVE_TO_TABLE)
                return True

        # TABLE_END_CHECK: FollowEnd / RestartFollowStart
        elif self._state == FollowState.TABLE_END_CHECK:
            if command == 'FollowEnd':
                self._node.get_logger().info('[FollowFSM] FollowEnd → 동행 종료')
                self._change_state(FollowState.FOLLOW_END)
                return True
            elif command == 'RestartFollowStart':
                self._node.get_logger().info('[FollowFSM] RestartFollowStart → 동행 재시작')
                self._change_state(FollowState.FOLLOWING)
                return True

        self._node.get_logger().warn(
            f'[FollowFSM] 처리되지 않은 명령: {command} (현재 상태: {self._state})'
        )
        return False

    # ------------------------------------------------------------------ #
    # 내부 콜백                                                             #
    # ------------------------------------------------------------------ #

    def handle_event(self, event: str, session_id: str = '') -> bool:
        """function node 도착 이벤트를 수신하여 상태 전이를 트리거한다."""
        if event == 'ArrivedAtRequester' and self._state == FollowState.MOVE_TO_REQUESTER:
            self._on_arrived_at_requester()
            return True
        if event == 'ArrivedAtTable' and self._state == FollowState.MOVE_TO_TABLE:
            self._on_arrived_at_table()
            return True
        return False

    def _on_arrived_at_requester(self) -> None:
        if self._state == FollowState.MOVE_TO_REQUESTER:
            self._change_state(FollowState.VERIFY_REQUESTER)

    def _on_arrived_at_table(self) -> None:
        if self._state == FollowState.MOVE_TO_TABLE:
            self._change_state(FollowState.TABLE_END_CHECK)

    def _on_near_table_1min(self) -> None:
        """1분 타이머 — NearTableFor1Min 이벤트 전송 후 FOLLOW_COMPLETE_CHECK로 전이"""
        self._cancel_near_table_timer()
        if self._state == FollowState.FOLLOWING:
            self._node.get_logger().info(
                '[FollowFSM] NearTableFor1Min → FOLLOW_COMPLETE_CHECK'
            )
            self._node.publish_event('NearTableFor1Min', self._session_id)
            self._change_state(FollowState.FOLLOW_COMPLETE_CHECK)

    def _on_verify_timeout(self) -> None:
        self._node.get_logger().warn('[FollowFSM] VERIFY 타임아웃. HQ에 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_verify_timeout)

    def _on_complete_check_timeout(self) -> None:
        self._node.get_logger().warn('[FollowFSM] FOLLOW_COMPLETE_CHECK 타임아웃. HQ에 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_complete_check_timeout)

    def _on_table_end_timeout(self) -> None:
        self._node.get_logger().warn('[FollowFSM] TABLE_END_CHECK 타임아웃. HQ에 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_table_end_timeout)

    def _cancel_near_table_timer(self) -> None:
        if self._near_table_timer is not None:
            self._near_table_timer.cancel()
            self._near_table_timer = None
