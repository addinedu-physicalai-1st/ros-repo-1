"""
FSM 기본 클래스 모듈
모든 상태 기계(Top FSM, Sub FSM)의 공통 인터페이스를 정의한다.
"""

from enum import Enum
from typing import Callable, Optional


class FSMBase:
    """
    상태 기계(FSM) 기본 클래스.

    각 FSM은 이 클래스를 상속받아 구현한다.
    - 상태 변경 시 로깅
    - 타임아웃 타이머 관리
    - on_enter / on_exit 훅
    """

    def __init__(self, node, name: str):
        """
        :param node: ROS2 노드 인스턴스 (rclpy.node.Node)
        :param name: FSM 식별 이름 (로그 출력용)
        """
        self._node = node
        self._name = name
        self._state = None
        self._timeout_timer = None
        self._timeout_callback: Optional[Callable] = None

    # ------------------------------------------------------------------ #
    # 공개 속성                                                            #
    # ------------------------------------------------------------------ #

    @property
    def state(self):
        """현재 상태 반환"""
        return self._state

    @property
    def name(self) -> str:
        """FSM 이름 반환"""
        return self._name

    # ------------------------------------------------------------------ #
    # 상태 전이                                                            #
    # ------------------------------------------------------------------ #

    def _change_state(self, new_state) -> None:
        """
        상태를 변경하고 on_exit / on_enter 훅을 호출한다.
        로그는 INFO 레벨로 출력한다.
        """
        old_state = self._state

        # 이탈 훅
        if old_state is not None:
            self.on_exit(old_state)

        self._state = new_state

        self._node.get_logger().info(
            f'[{self._name}] 상태 전이: {old_state} → {new_state}'
        )

        # 진입 훅
        self.on_enter(new_state)

    # ------------------------------------------------------------------ #
    # 서브클래스 오버라이드 메서드                                           #
    # ------------------------------------------------------------------ #

    def on_enter(self, state) -> None:
        """상태 진입 시 호출. 서브클래스에서 오버라이드."""
        pass

    def on_exit(self, state) -> None:
        """상태 이탈 시 호출. 서브클래스에서 오버라이드."""
        pass

    def handle_command(self, command: str, msg=None) -> bool:
        """
        HQ 명령을 처리한다.
        :return: True면 처리됨, False면 현재 상태에서 처리 불가
        """
        raise NotImplementedError(f'{self._name}.handle_command()를 구현해야 합니다.')

    # ------------------------------------------------------------------ #
    # 타임아웃 타이머 관리                                                  #
    # ------------------------------------------------------------------ #

    def _start_timeout(self, seconds: float, callback: Callable) -> None:
        """
        타임아웃 타이머를 시작한다.
        이전 타이머가 있으면 취소 후 새로 시작한다.
        :param seconds: 타임아웃 시간 (초)
        :param callback: 타임아웃 발생 시 호출할 콜백
        """
        self._cancel_timeout()
        self._timeout_callback = callback
        self._timeout_timer = self._node.create_timer(
            seconds,
            self._on_timeout_fired
        )
        self._node.get_logger().info(
            f'[{self._name}] 타임아웃 타이머 시작: {seconds}초'
        )

    def _on_timeout_fired(self) -> None:
        """타이머 콜백 - 한 번만 실행되도록 즉시 취소한다."""
        # 먼저 취소하여 반복 실행 방지
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None

        self._node.get_logger().warn(
            f'[{self._name}] 타임아웃 발생!'
        )

        cb = self._timeout_callback
        self._timeout_callback = None
        if cb:
            cb()

    def _cancel_timeout(self) -> None:
        """진행 중인 타임아웃 타이머를 취소한다."""
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None
            self._timeout_callback = None
