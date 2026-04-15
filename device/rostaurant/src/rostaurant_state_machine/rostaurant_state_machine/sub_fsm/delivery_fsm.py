"""
운반 Sub FSM (DELIVERY)

상태:
  DELIVERY_INIT     → 운반 시작, HQ의 MoveToKitchen 대기
  MOVE_TO_KITCHEN   → 주방으로 이동
  LOADING           → 음식 적재 대기 (HQ의 StartDelivery 대기)
  DELIVERY_LOOP     → 다중 목적지 배송 루프 진입
  MOVE_TO_MENU_LOC  → 배송 목적지로 이동
  UNLOAD_MENU       → 메뉴 하차 (HQ 신호 대기)
  DELIVERY_END      → 운반 종료

HQ → ROBOT: MoveToKitchen, StartDelivery, RetryStartDelivery, DeliveryEnd
ROBOT → HQ: ArrivedAtKitchen, ArrivedAtMenuLocation
"""

from enum import Enum, auto
from typing import Callable

from rostaurant_state_machine.utils.fsm_base import FSMBase


class DeliveryState(Enum):
    DELIVERY_INIT = auto()     # 초기화, MoveToKitchen 대기
    MOVE_TO_KITCHEN = auto()   # 주방으로 이동 중
    LOADING = auto()           # 음식 적재 대기
    DELIVERY_LOOP = auto()     # 배송 루프 (다음 목적지 선택)
    MOVE_TO_MENU_LOC = auto()  # 배송 목적지로 이동 중
    UNLOAD_MENU = auto()       # 메뉴 하차 대기
    DELIVERY_END = auto()      # 운반 종료


class DeliveryFSM(FSMBase):
    """운반 Sub FSM"""

    def __init__(self, node, done_callback: Callable, timeout_secs: float = 30.0):
        super().__init__(node, 'DeliveryFSM')
        self._done_callback = done_callback
        self._timeout_secs = timeout_secs
        self._session_id: str = ''
        self._current_target_pose = None  # 현재 배송 목적지

    def start(self) -> None:
        """FSM 시작: DELIVERY_INIT 상태로 진입"""
        self._change_state(DeliveryState.DELIVERY_INIT)

    def on_enter(self, state: DeliveryState) -> None:
        if state == DeliveryState.DELIVERY_INIT:
            self._node.get_logger().info('[DeliveryFSM] HQ로부터 MoveToKitchen 대기 중...')

        elif state == DeliveryState.MOVE_TO_KITCHEN:
            self._node.navigate_to(
                label='MOVE_TO_KITCHEN',
                on_arrived=self._on_arrived_at_kitchen
            )

        elif state == DeliveryState.LOADING:
            # use_function_nodes=False 일 때만 FSM이 직접 이벤트를 publish한다.
            if not self._node.get_parameter('use_function_nodes').value:
                self._node.publish_event('ArrivedAtKitchen', self._session_id)
            self._node.get_logger().info(
                '[DeliveryFSM] 주방 도착. HQ의 StartDelivery 대기 중...'
            )
            # 타임아웃 시작
            self._start_timeout(self._timeout_secs, self._on_loading_timeout)

        elif state == DeliveryState.DELIVERY_LOOP:
            self._cancel_timeout()
            self._node.get_logger().info(
                '[DeliveryFSM] 배송 루프. HQ의 StartDelivery(목적지) 또는 DeliveryEnd 대기 중...'
            )
            # 타임아웃 시작
            self._start_timeout(self._timeout_secs, self._on_loop_timeout)

        elif state == DeliveryState.MOVE_TO_MENU_LOC:
            self._cancel_timeout()
            self._node.navigate_to(
                label='MOVE_TO_MENU_LOC',
                on_arrived=self._on_arrived_at_menu_loc
            )

        elif state == DeliveryState.UNLOAD_MENU:
            # use_function_nodes=False 일 때만 FSM이 직접 이벤트를 publish한다.
            if not self._node.get_parameter('use_function_nodes').value:
                self._node.publish_event('ArrivedAtMenuLocation', self._session_id)
            self._node.get_logger().info(
                '[DeliveryFSM] 배송 목적지 도착. HQ의 StartDelivery(다음) 또는 RetryStartDelivery 대기 중...'
            )
            self._start_timeout(self._timeout_secs, self._on_unload_timeout)

        elif state == DeliveryState.DELIVERY_END:
            self._cancel_timeout()
            self._node.get_logger().info('[DeliveryFSM] 운반 종료.')
            self._done_callback()

    def on_exit(self, state: DeliveryState) -> None:
        pass

    def handle_command(self, command: str, msg=None) -> bool:
        """HQ로부터 수신한 명령 처리"""
        if msg:
            self._session_id = msg.session_id

        # DELIVERY_INIT: MoveToKitchen 수신
        if self._state == DeliveryState.DELIVERY_INIT:
            if command == 'MoveToKitchen':
                self._node.get_logger().info(
                    f'[DeliveryFSM] MoveToKitchen 수신. 주방 좌표: '
                    f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}' if msg else 'N/A'
                )
                self._change_state(DeliveryState.MOVE_TO_KITCHEN)
                return True

        # LOADING: StartDelivery 수신 → 배송 루프 시작
        elif self._state == DeliveryState.LOADING:
            if command == 'StartDelivery':
                self._node.get_logger().info('[DeliveryFSM] StartDelivery 수신 → 배송 루프 시작')
                self._change_state(DeliveryState.DELIVERY_LOOP)
                # 바로 첫 목적지로 이동
                self._change_state(DeliveryState.MOVE_TO_MENU_LOC)
                return True

        # DELIVERY_LOOP: StartDelivery(다음 목적지) 또는 DeliveryEnd
        elif self._state == DeliveryState.DELIVERY_LOOP:
            if command == 'StartDelivery':
                self._node.get_logger().info('[DeliveryFSM] 다음 배송 목적지 수신')
                self._change_state(DeliveryState.MOVE_TO_MENU_LOC)
                return True
            elif command == 'DeliveryEnd':
                self._node.get_logger().info('[DeliveryFSM] DeliveryEnd 수신 → 운반 종료')
                self._change_state(DeliveryState.DELIVERY_END)
                return True

        # UNLOAD_MENU: StartDelivery(다음) / RetryStartDelivery / DeliveryEnd
        elif self._state == DeliveryState.UNLOAD_MENU:
            if command == 'StartDelivery':
                self._node.get_logger().info('[DeliveryFSM] 다음 배송 목적지 수신 → 배송 루프 재진입')
                self._change_state(DeliveryState.DELIVERY_LOOP)
                self._change_state(DeliveryState.MOVE_TO_MENU_LOC)
                return True
            elif command == 'RetryStartDelivery':
                self._node.get_logger().info('[DeliveryFSM] RetryStartDelivery 수신 → 동일 목적지 재이동')
                self._change_state(DeliveryState.MOVE_TO_MENU_LOC)
                return True
            elif command == 'DeliveryEnd':
                self._node.get_logger().info('[DeliveryFSM] DeliveryEnd 수신 → 운반 종료')
                self._change_state(DeliveryState.DELIVERY_END)
                return True

        self._node.get_logger().warn(
            f'[DeliveryFSM] 처리되지 않은 명령: {command} (현재 상태: {self._state})'
        )
        return False

    def handle_event(self, event: str, session_id: str = '') -> bool:
        """function node 도착 이벤트를 수신하여 상태 전이를 트리거한다."""
        if event == 'ArrivedAtKitchen' and self._state == DeliveryState.MOVE_TO_KITCHEN:
            self._on_arrived_at_kitchen()
            return True
        if event == 'ArrivedAtMenuLocation' and self._state == DeliveryState.MOVE_TO_MENU_LOC:
            self._on_arrived_at_menu_loc()
            return True
        return False

    # ------------------------------------------------------------------ #
    # 내부 콜백                                                            #
    # ------------------------------------------------------------------ #

    def _on_arrived_at_kitchen(self) -> None:
        if self._state == DeliveryState.MOVE_TO_KITCHEN:
            self._change_state(DeliveryState.LOADING)

    def _on_arrived_at_menu_loc(self) -> None:
        if self._state == DeliveryState.MOVE_TO_MENU_LOC:
            self._change_state(DeliveryState.UNLOAD_MENU)

    def _on_loading_timeout(self) -> None:
        self._node.get_logger().warn('[DeliveryFSM] LOADING 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_loading_timeout)

    def _on_loop_timeout(self) -> None:
        self._node.get_logger().warn('[DeliveryFSM] DELIVERY_LOOP 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_loop_timeout)

    def _on_unload_timeout(self) -> None:
        self._node.get_logger().warn('[DeliveryFSM] UNLOAD_MENU 타임아웃. HQ 이벤트 전송 후 재대기.')
        self._node.publish_event('TimeoutWaiting', self._session_id)
        self._start_timeout(self._timeout_secs, self._on_unload_timeout)
