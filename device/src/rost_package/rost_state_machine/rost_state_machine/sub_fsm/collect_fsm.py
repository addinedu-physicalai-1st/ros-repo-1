"""
수거 Sub FSM (COLLECT)

상태:
  COLLECT_INIT         → 수거 시작, HQ의 CollectRequest 대기
  MOVE_TO_COLLECT_LOC  → 수거 요청자 위치로 이동
  VERIFY_COLLECT       → 수거 요청자 확인 (HQ 응답 대기)
  COLLECTING           → 그릇 수거 중 (HQ의 CollectionDone 대기)
  MOVE_TO_DISHWASH     → 설거지장으로 이동
  DISHWASHING          → 설거지 완료 대기 (HQ의 CollectionEnd 대기)
  COLLECT_END          → 수거 종료

특이사항:
  - request_count 관리: 5회 이상 또는 배터리 < 20% 시 설거지장으로 이동
  - CollectionDone 수신 후 조건에 따라 MOVE_TO_DISHWASH 또는 COLLECT_END 분기

HQ → ROBOT: CollectRequest, StartCollection, CollectionDone, MoveToDishwashing,
             RetryCollectRequest, CollectionEnd
ROBOT → HQ: ArrivedAtRequester, ArrivedAtDishwashing
"""

from enum import Enum, auto
from typing import Callable

from rost_state_machine.utils.fsm_base import FSMBase


class CollectState(Enum):
    COLLECT_INIT = auto()         # 초기화, CollectRequest 대기
    MOVE_TO_COLLECT_LOC = auto()  # 수거 위치로 이동 중
    VERIFY_COLLECT = auto()       # 수거 요청자 확인 중
    COLLECTING = auto()           # 수거 중
    MOVE_TO_DISHWASH = auto()     # 설거지장으로 이동 중
    DISHWASHING = auto()          # 설거지 완료 대기
    COLLECT_END = auto()          # 수거 종료


class CollectFSM(FSMBase):
    """수거 Sub FSM"""

    def __init__(
        self,
        node,
        done_callback: Callable,
        timeout_secs: float = 30.0,
        max_request_count: int = 3,
    ):
        super().__init__(node, 'CollectFSM')
        self._done_callback = done_callback
        self._timeout_secs = timeout_secs
        self._max_request_count = max_request_count
        self._session_id: str = ''
        self._request_count: int = 0  # 수거 요청 횟수 카운터

    def start(self) -> None:
        """FSM 시작: COLLECT_INIT 상태로 진입"""
        self._change_state(CollectState.COLLECT_INIT)

    def update_battery(self, battery_level: float) -> None:
        """배터리 레벨 업데이트 (TopFSM에서 호출)"""
        self._battery_level = battery_level

    def on_enter(self, state: CollectState) -> None:
        if state == CollectState.COLLECT_INIT:
            self._battery_level = 100.0  # 초기값
            self._node.get_logger().info('[CollectFSM] HQ로부터 CollectRequest 대기 중...')

        elif state == CollectState.MOVE_TO_COLLECT_LOC:
            self._node.navigate_to(
                label='MOVE_TO_COLLECT_LOC',
                on_arrived=self._on_arrived_at_collect_loc
            )

        elif state == CollectState.VERIFY_COLLECT:
            # 도착 이벤트 전송
            self._node.publish_event('ArrivedAtRequester', self._session_id)
            self._node.get_logger().info(
                '[CollectFSM] 수거 위치 도착. HQ의 StartCollection 또는 RetryCollectRequest 대기...'
            )
            self._start_timeout(self._timeout_secs, self._on_verify_timeout)

        elif state == CollectState.COLLECTING:
            self._cancel_timeout()
            self._request_count += 1
            self._node.get_logger().info(
                f'[CollectFSM] 수거 시작. 현재 수거 횟수: {self._request_count}. '
                'HQ의 CollectionDone 대기 중...'
            )
            self._start_timeout(self._timeout_secs, self._on_collecting_timeout)

        elif state == CollectState.MOVE_TO_DISHWASH:
            self._cancel_timeout()
            self._node.navigate_to(
                label='MOVE_TO_DISHWASH',
                on_arrived=self._on_arrived_at_dishwash
            )

        elif state == CollectState.DISHWASHING:
            # 설거지장 도착 이벤트 전송
            self._node.publish_event('ArrivedAtDishwashing', self._session_id)
            self._node.get_logger().info(
                '[CollectFSM] 설거지장 도착. HQ의 CollectionEnd 대기 중...'
            )
            self._start_timeout(self._timeout_secs, self._on_dishwashing_timeout)

        elif state == CollectState.COLLECT_END:
            self._cancel_timeout()
            self._node.get_logger().info(
                f'[CollectFSM] 수거 종료. 총 수거 횟수: {self._request_count}'
            )
            self._done_callback()

    def on_exit(self, state: CollectState) -> None:
        pass

    def handle_command(self, command: str, msg=None) -> bool:
        """HQ로부터 수신한 명령 처리"""
        if msg:
            self._session_id = msg.session_id

        # COLLECT_INIT: CollectRequest 수신
        if self._state == CollectState.COLLECT_INIT:
            if command == 'CollectRequest':
                self._node.get_logger().info(
                    f'[CollectFSM] CollectRequest 수신. 수거 위치: '
                    f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}' if msg else 'N/A'
                )
                self._change_state(CollectState.MOVE_TO_COLLECT_LOC)
                return True

        # VERIFY_COLLECT: StartCollection / RetryCollectRequest / CollectionEnd(타임아웃)
        elif self._state == CollectState.VERIFY_COLLECT:
            if command == 'StartCollection':
                self._node.get_logger().info('[CollectFSM] StartCollection 수신 → 수거 시작')
                self._change_state(CollectState.COLLECTING)
                return True
            elif command == 'RetryCollectRequest':
                self._node.get_logger().info('[CollectFSM] RetryCollectRequest 수신 → 재이동')
                self._change_state(CollectState.MOVE_TO_COLLECT_LOC)
                return True
            elif command == 'CollectionEnd':
                self._node.get_logger().info('[CollectFSM] CollectionEnd(타임아웃) 수신 → 종료')
                self._change_state(CollectState.COLLECT_END)
                return True

        # COLLECTING: CollectionDone 수신 → 조건 분기
        elif self._state == CollectState.COLLECTING:
            if command == 'CollectionDone':
                battery_low = self._node.get_parameter('battery_low').value
                battery_level = getattr(self, '_battery_level', 100.0)
                go_dishwash = (
                    battery_level < battery_low
                    or self._request_count >= self._max_request_count
                )
                self._node.get_logger().info(
                    f'[CollectFSM] CollectionDone 수신. '
                    f'배터리={battery_level:.1f}%, 수거횟수={self._request_count}. '
                    f'→ {"설거지장 이동" if go_dishwash else "수거 종료"}'
                )
                if go_dishwash:
                    self._change_state(CollectState.MOVE_TO_DISHWASH)
                else:
                    self._change_state(CollectState.COLLECT_END)
                return True
            elif command == 'MoveToDishwashing':
                self._node.get_logger().info('[CollectFSM] MoveToDishwashing 수신 → 설거지장으로')
                self._change_state(CollectState.MOVE_TO_DISHWASH)
                return True

        # DISHWASHING: CollectionEnd 수신
        elif self._state == CollectState.DISHWASHING:
            if command == 'CollectionEnd':
                self._node.get_logger().info('[CollectFSM] CollectionEnd 수신 → 수거 종료')
                self._change_state(CollectState.COLLECT_END)
                return True

        self._node.get_logger().warn(
            f'[CollectFSM] 처리되지 않은 명령: {command} (현재 상태: {self._state})'
        )
        return False

    # ------------------------------------------------------------------ #
    # 내부 콜백                                                            #
    # ------------------------------------------------------------------ #

    def _on_arrived_at_collect_loc(self) -> None:
        if self._state == CollectState.MOVE_TO_COLLECT_LOC:
            self._change_state(CollectState.VERIFY_COLLECT)

    def _on_arrived_at_dishwash(self) -> None:
        if self._state == CollectState.MOVE_TO_DISHWASH:
            self._change_state(CollectState.DISHWASHING)

    def _on_verify_timeout(self) -> None:
        self._node.get_logger().warn('[CollectFSM] VERIFY 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_verify_timeout)

    def _on_collecting_timeout(self) -> None:
        self._node.get_logger().warn('[CollectFSM] COLLECTING 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_collecting_timeout)

    def _on_dishwashing_timeout(self) -> None:
        self._node.get_logger().warn('[CollectFSM] DISHWASHING 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_dishwashing_timeout)
