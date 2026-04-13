"""
Top FSM

레스토랑 서빙 로봇의 최상위 상태 기계.
배터리 레벨과 HQ 명령에 따라 Sub FSM을 활성화·비활성화한다.

상태:
  CHARGING           → 충전소 진입점 (배터리 평가 후 즉시 전이)
  CHARGING_NO_TASK   → 충전 중, 투입 불가 (배터리 < 20%)
  CHARGING_WITH_TASK → 충전 중, 투입 가능 (배터리 60~80%)
  MOVE_TO_STANDBY    → 대기장소로 이동 (배터리 > 80%)
  STANDBY            → 작업 대기
  FOLLOW             → 동행 Sub FSM 실행
  DELIVERY           → 운반 Sub FSM 실행
  COLLECT            → 수거 Sub FSM 실행
  GUIDE              → 안내 Sub FSM 실행
"""

from enum import Enum, auto
from typing import Optional

from rost_state_machine.utils.fsm_base import FSMBase
from rost_state_machine.sub_fsm.follow_fsm import FollowFSM
from rost_state_machine.sub_fsm.delivery_fsm import DeliveryFSM
from rost_state_machine.sub_fsm.collect_fsm import CollectFSM
from rost_state_machine.sub_fsm.guide_fsm import GuideFSM


class TopState(Enum):
    CHARGING = auto()            # 충전소 진입 (평가 포인트)
    CHARGING_NO_TASK = auto()    # 충전 중, 배터리 < 20%
    CHARGING_WITH_TASK = auto()  # 충전 중, 배터리 60~80%
    MOVE_TO_STANDBY = auto()     # 대기장소로 이동 중
    STANDBY = auto()             # 작업 대기
    FOLLOW = auto()              # 동행 Sub FSM 실행 중
    DELIVERY = auto()            # 운반 Sub FSM 실행 중
    COLLECT = auto()             # 수거 Sub FSM 실행 중
    GUIDE = auto()               # 안내 Sub FSM 실행 중


# 작업을 시작시키는 HQ 명령 → Top 상태 매핑
_TASK_TRIGGER_COMMANDS = {
    'FollowRequest': TopState.FOLLOW,
    'MoveToKitchen': TopState.DELIVERY,
    'CollectRequest': TopState.COLLECT,
    'MoveToRequester': TopState.GUIDE,
}

# 작업 시작 가능한 Top 상태
_TASK_READY_STATES = {TopState.STANDBY, TopState.CHARGING_WITH_TASK}


class TopFSM(FSMBase):
    """최상위 FSM"""

    def __init__(self, node):
        super().__init__(node, 'TopFSM')
        self._active_sub_fsm: Optional[FSMBase] = None
        self._battery_level: float = 100.0
        # 배터리 평가가 끝날 때까지 초기 전이를 지연하는 타이머
        self._init_timer = None
        # 작업 시작 시 SubFSM에 전달할 초기 명령
        self._pending_command: Optional[str] = None
        self._pending_msg = None

    # ------------------------------------------------------------------ #
    # 시작                                                                 #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """FSM을 CHARGING 상태로 시작"""
        self._change_state(TopState.CHARGING)

    # ------------------------------------------------------------------ #
    # on_enter / on_exit                                                   #
    # ------------------------------------------------------------------ #

    def on_enter(self, state: TopState) -> None:
        self._node.publish_top_state(state.name)

        if state == TopState.CHARGING:
            # 0.1초 후 배터리 레벨에 따라 즉시 전이
            self._schedule_battery_eval()

        elif state == TopState.CHARGING_NO_TASK:
            self._node.get_logger().info(
                f'[TopFSM] 배터리 부족 충전 중. 배터리={self._battery_level:.1f}% '
                '(> 60% 시 CHARGING_WITH_TASK로 전이)'
            )

        elif state == TopState.CHARGING_WITH_TASK:
            self._node.get_logger().info(
                f'[TopFSM] 충전 중 (투입 가능). 배터리={self._battery_level:.1f}% '
                '(> 80% 시 MOVE_TO_STANDBY, 작업 요청 시 즉시 수행)'
            )

        elif state == TopState.MOVE_TO_STANDBY:
            self._node.navigate_to(
                label='MOVE_TO_STANDBY',
                on_arrived=self._on_arrived_at_standby
            )

        elif state == TopState.STANDBY:
            self._node.get_logger().info('[TopFSM] 대기 중. HQ 작업 요청 대기...')

        elif state in (TopState.FOLLOW, TopState.DELIVERY, TopState.COLLECT, TopState.GUIDE):
            self._start_sub_fsm(state)

    def on_exit(self, state: TopState) -> None:
        if state == TopState.CHARGING:
            # 배터리 평가 타이머 취소
            if self._init_timer is not None:
                self._init_timer.cancel()
                self._init_timer = None

    # ------------------------------------------------------------------ #
    # 명령 처리                                                             #
    # ------------------------------------------------------------------ #

    def handle_command(self, command: str, msg=None) -> bool:
        """HQ 명령을 처리한다."""
        # 작업 시작 명령인지 확인
        task_state = _TASK_TRIGGER_COMMANDS.get(command)
        if task_state is not None and self._state in _TASK_READY_STATES:
            self._node.get_logger().info(
                f'[TopFSM] 작업 요청 수신: {command} → {task_state.name}'
            )
            # SubFSM에 전달할 초기 명령 저장
            self._pending_command = command
            self._pending_msg = msg
            self._change_state(task_state)
            return True

        # 활성 SubFSM에 명령 위임
        if self._active_sub_fsm is not None:
            return self._active_sub_fsm.handle_command(command, msg)

        self._node.get_logger().warn(
            f'[TopFSM] 처리되지 않은 명령: {command} (현재 상태: {self._state})'
        )
        return False

    # ------------------------------------------------------------------ #
    # 배터리 모니터링                                                        #
    # ------------------------------------------------------------------ #

    def update_battery(self, level: float) -> None:
        """배터리 레벨이 변경될 때마다 호출된다."""
        self._battery_level = level

        # 활성 수거 FSM에도 배터리 레벨 전달
        if isinstance(self._active_sub_fsm, CollectFSM):
            self._active_sub_fsm.update_battery(level)

        self._check_battery_transitions()

    def _check_battery_transitions(self) -> None:
        """현재 배터리 레벨에 따라 충전 상태 전이를 트리거한다."""
        low = self._node.get_parameter('battery_low').value
        mid = self._node.get_parameter('battery_mid').value
        high = self._node.get_parameter('battery_high').value

        if self._state == TopState.CHARGING_NO_TASK:
            if self._battery_level > mid:
                self._node.get_logger().info(
                    f'[TopFSM] 배터리 {self._battery_level:.1f}% > {mid}% → CHARGING_WITH_TASK'
                )
                self._change_state(TopState.CHARGING_WITH_TASK)

        elif self._state == TopState.CHARGING_WITH_TASK:
            if self._battery_level > high:
                self._node.get_logger().info(
                    f'[TopFSM] 배터리 {self._battery_level:.1f}% > {high}% → MOVE_TO_STANDBY'
                )
                self._change_state(TopState.MOVE_TO_STANDBY)

    # ------------------------------------------------------------------ #
    # Sub FSM 시작                                                          #
    # ------------------------------------------------------------------ #

    def _start_sub_fsm(self, state: TopState) -> None:
        """주어진 TopState에 대응하는 Sub FSM을 생성하고 시작한다."""
        timeout_secs = self._node.get_parameter('timeout_secs').value

        if state == TopState.FOLLOW:
            self._active_sub_fsm = FollowFSM(
                self._node, self._on_sub_done, timeout_secs
            )
        elif state == TopState.DELIVERY:
            self._active_sub_fsm = DeliveryFSM(
                self._node, self._on_sub_done, timeout_secs
            )
        elif state == TopState.COLLECT:
            self._active_sub_fsm = CollectFSM(
                self._node, self._on_sub_done, timeout_secs
            )
        elif state == TopState.GUIDE:
            self._active_sub_fsm = GuideFSM(
                self._node, self._on_sub_done, timeout_secs
            )

        if self._active_sub_fsm:
            self._active_sub_fsm.start()
            # 작업 시작 명령을 SubFSM에 즉시 전달
            if self._pending_command:
                self._active_sub_fsm.handle_command(
                    self._pending_command, self._pending_msg
                )
                self._pending_command = None
                self._pending_msg = None

    # ------------------------------------------------------------------ #
    # 내부 콜백                                                             #
    # ------------------------------------------------------------------ #

    def _schedule_battery_eval(self) -> None:
        """CHARGING 진입 직후 배터리 평가를 비동기 스케줄"""
        if self._init_timer is not None:
            self._init_timer.cancel()
        self._init_timer = self._node.create_timer(
            0.1, self._do_charging_battery_eval
        )

    def _do_charging_battery_eval(self) -> None:
        """CHARGING 상태에서 배터리 레벨을 평가하여 다음 상태로 전이"""
        if self._init_timer is not None:
            self._init_timer.cancel()
            self._init_timer = None

        # CHARGING 상태가 아니면 무시 (중복 호출 방지)
        if self._state != TopState.CHARGING:
            return

        low = self._node.get_parameter('battery_low').value
        if self._battery_level < low:
            self._node.get_logger().info(
                f'[TopFSM] 배터리 {self._battery_level:.1f}% < {low}% → CHARGING_NO_TASK'
            )
            self._change_state(TopState.CHARGING_NO_TASK)
        else:
            self._node.get_logger().info(
                f'[TopFSM] 배터리 {self._battery_level:.1f}% >= {low}% → MOVE_TO_STANDBY'
            )
            self._change_state(TopState.MOVE_TO_STANDBY)

    def _on_arrived_at_standby(self) -> None:
        """MOVE_TO_STANDBY 완료 → STANDBY"""
        if self._state == TopState.MOVE_TO_STANDBY:
            self._change_state(TopState.STANDBY)

    def _on_sub_done(self) -> None:
        """Sub FSM 완료 → CHARGING으로 복귀"""
        self._node.get_logger().info(
            f'[TopFSM] Sub FSM 완료. CHARGING으로 복귀.'
        )
        self._active_sub_fsm = None
        self._change_state(TopState.CHARGING)
