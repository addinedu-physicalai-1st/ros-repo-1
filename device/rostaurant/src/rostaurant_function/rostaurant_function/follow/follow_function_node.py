"""
follow_function_node.py

동행 Sub FSM 기능 노드.

HQ 명령에 반응하여 실제 이동·동행 동작을 수행하고,
완료 시 /robot/event에 이벤트를 퍼블리시한다.

처리 명령 (state=FOLLOW 인 경우에만 반응):
  FollowRequest      → 요청자 위치로 이동, 도달 시 ArrivedAtRequester 퍼블리시
  RetryFollowRequest → 새 위치로 재이동, 도달 시 ArrivedAtRequester 퍼블리시
  FollowStart        → 동행 시작 (1분 타이머는 FSM이 관리)
  GoToTable          → 테이블 위치로 이동, 도달 시 ArrivedAtTable 퍼블리시
  RestartFollowStart → 동행 재시작 (테이블 도착 후 다시 동행 시작)
  FollowEnd          → 동행 종료, 이동 중지

참고:
  NearTableFor1Min 이벤트는 FollowFSM(rostaurant_state_machine)이 퍼블리시함.
  이 노드는 1분 타이머를 관리하지 않는다.

파라미터:
  use_nav2                        : Nav2 사용 여부 (기본 False)
  simulated_nav_time              : 시뮬 이동 시간 (기본 3.0초)
  follow_table_distance_threshold : 테이블 근접 거리 임계값 m (기본 1.5)
"""

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String

from typing import Optional

from rostaurant_state_machine.msg import RobotCommand
from rostaurant_function.core.navigation_client import NavigationClient
from rostaurant_function.core.event_publisher import EventPublisher
from rostaurant_function.core.pose_utils import pose_from_xyt


class FollowFunctionNode(Node):
    """동행 Sub FSM 기능 노드"""

    def __init__(self):
        super().__init__('follow_function_node')

        # ---------------------------------------------------------------- #
        # 파라미터                                                           #
        # ---------------------------------------------------------------- #
        self.declare_parameter('use_nav2', False)
        self.declare_parameter('simulated_nav_time', 3.0)
        self.declare_parameter('follow_table_distance_threshold', 1.5)

        # ---------------------------------------------------------------- #
        # 내부 상태                                                          #
        # ---------------------------------------------------------------- #
        self._current_state: str = ''
        self._session_id: str = ''
        self._requester_pose: PoseStamped = None          # 요청자 위치
        self._table_pose: PoseStamped = None               # 테이블 위치 (GoToTable)
        self._is_following: bool = False                   # 동행 중 여부
        self._pending_command: Optional[RobotCommand] = None  # state 전이 전 도착한 명령 버퍼

        # ---------------------------------------------------------------- #
        # 공통 모듈                                                          #
        # ---------------------------------------------------------------- #
        use_nav2 = self.get_parameter('use_nav2').value
        sim_time = self.get_parameter('simulated_nav_time').value
        self._nav = NavigationClient(self, use_nav2=use_nav2, simulated_nav_time=sim_time)
        self._event_pub = EventPublisher(self)

        # ---------------------------------------------------------------- #
        # 서브스크라이버                                                      #
        # ---------------------------------------------------------------- #
        self._state_sub = self.create_subscription(
            String, '/robot/state', self._on_state, 10
        )
        self._cmd_sub = self.create_subscription(
            RobotCommand, '/hq/command', self._on_command, 10
        )

        self.get_logger().info('follow_function_node 시작.')

    # ------------------------------------------------------------------ #
    # 상태 변경 감지                                                         #
    # ------------------------------------------------------------------ #

    def _on_state(self, msg: String) -> None:
        new_state = msg.data
        if new_state == self._current_state:
            return

        old_state = self._current_state
        self._current_state = new_state
        self.get_logger().info(f'[FollowFunc] 상태 변경: {old_state} → {new_state}')
        self._on_state_enter(new_state)

    def _on_state_enter(self, state: str) -> None:
        """상태 진입 처리"""
        if state == 'FOLLOW':
            self.get_logger().info('[FollowFunc] FOLLOW 태스크 진입. HQ 명령 대기...')
            self._reset_session()
            # 상태 전이 전에 도착한 pending 명령 처리
            if self._pending_command is not None:
                pending = self._pending_command
                self._pending_command = None
                self.get_logger().info(
                    f'[FollowFunc] pending 명령 처리: {pending.command}'
                )
                self._process_command(pending)
        else:
            self._pending_command = None
            if self._nav.is_navigating() or self._is_following:
                self.get_logger().info('[FollowFunc] 태스크 종료. 이동 중지 및 세션 초기화.')
                self._stop_all()

    # ------------------------------------------------------------------ #
    # HQ 명령 처리                                                          #
    # ------------------------------------------------------------------ #

    def _on_command(self, msg: RobotCommand) -> None:
        """HQ 명령 수신 — FOLLOW 상태일 때만 처리"""
        if self._current_state != 'FOLLOW':
            if msg.command == 'FollowRequest':
                self.get_logger().info(
                    f'[FollowFunc] FOLLOW 상태 아님 — FollowRequest 버퍼링 (현재: {self._current_state})'
                )
                self._pending_command = msg
            return

        self._process_command(msg)

    def _process_command(self, msg: RobotCommand) -> None:
        cmd = msg.command
        self._session_id = msg.session_id
        self.get_logger().info(f'[FollowFunc] 명령 수신: {cmd}')

        if cmd == 'FollowRequest':
            self._requester_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self.get_logger().info(
                f'[FollowFunc] FollowRequest — 요청자 위치로 이동: '
                f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}'
            )
            self._nav.send_goal(self._requester_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'RetryFollowRequest':
            self._requester_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self.get_logger().info(
                f'[FollowFunc] RetryFollowRequest — 새 위치로 재이동: '
                f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}'
            )
            self._nav.send_goal(self._requester_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'FollowStart':
            # 동행 시작 — 1분 타이머는 FollowFSM이 관리하므로 여기서는 상태만 기록
            self.get_logger().info('[FollowFunc] FollowStart — 동행 시작.')
            self._is_following = True

        elif cmd == 'GoToTable':
            # 테이블로 이동
            self._table_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self._is_following = False
            self.get_logger().info(
                f'[FollowFunc] GoToTable — 테이블로 이동: '
                f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}'
            )
            self._nav.send_goal(self._table_pose, on_arrived=self._on_arrived_table)

        elif cmd == 'RestartFollowStart':
            # 테이블 도착 후 동행 재시작
            self.get_logger().info('[FollowFunc] RestartFollowStart — 동행 재시작.')
            self._is_following = True

        elif cmd == 'FollowEnd':
            self.get_logger().info('[FollowFunc] FollowEnd — 동행 종료.')
            self._stop_all()

    # ------------------------------------------------------------------ #
    # 내비게이션 콜백                                                        #
    # ------------------------------------------------------------------ #

    def _on_arrived_requester(self) -> None:
        """요청자 위치 도달 시 ArrivedAtRequester 이벤트 퍼블리시"""
        self.get_logger().info('[FollowFunc] 요청자 위치 도착!')
        self._event_pub.publish_event('ArrivedAtRequester', self._session_id)

    def _on_arrived_table(self) -> None:
        """테이블 도달 시 ArrivedAtTable 이벤트 퍼블리시"""
        self.get_logger().info('[FollowFunc] 테이블 도착!')
        self._event_pub.publish_event('ArrivedAtTable', self._session_id)

    # ------------------------------------------------------------------ #
    # 세션 관리                                                              #
    # ------------------------------------------------------------------ #

    def _stop_all(self) -> None:
        """모든 동작 중지"""
        self._nav.cancel_goal()
        self._is_following = False

    def _reset_session(self) -> None:
        """세션 데이터 초기화"""
        self._stop_all()
        self._session_id = ''
        self._requester_pose = None
        self._table_pose = None


def main(args=None):
    rclpy.init(args=args)
    node = FollowFunctionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('follow_function_node 종료')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
