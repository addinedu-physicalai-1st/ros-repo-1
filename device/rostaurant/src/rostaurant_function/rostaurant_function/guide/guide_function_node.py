"""
guide_function_node.py

안내 Sub FSM 기능 노드.

처리 명령 (state=GUIDE 인 경우에만 반응):
  MoveToRequester    → 요청자 위치로 이동, 도달 시 ArrivedAtRequester 퍼블리시
  RetryMoveToRequester → 새 요청자 위치로 재이동, 도달 시 ArrivedAtRequester 퍼블리시
  GuideStart         → 안내 목적지로 이동, 도달 시 ArrivedAtTarget 퍼블리시
  RetryGuideStart    → 동일 안내 목적지로 재이동, 도달 시 ArrivedAtTarget 퍼블리시
  GuideEnd           → 안내 종료, 이동 중지, 세션 초기화

파라미터:
  use_nav2           : Nav2 사용 여부 (기본 False)
  simulated_nav_time : 시뮬 이동 시간 (기본 3.0초)
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


class GuideFunctionNode(Node):
    """안내 Sub FSM 기능 노드"""

    def __init__(self):
        super().__init__('guide_function_node')

        # ---------------------------------------------------------------- #
        # 파라미터                                                           #
        # ---------------------------------------------------------------- #
        self.declare_parameter('use_nav2', False)
        self.declare_parameter('simulated_nav_time', 3.0)

        # ---------------------------------------------------------------- #
        # 내부 상태                                                          #
        # ---------------------------------------------------------------- #
        self._current_state: str = ''
        self._session_id: str = ''
        self._requester_pose: PoseStamped = None          # 요청자 위치
        self._current_target_pose: PoseStamped = None     # 현재 안내 목적지
        # 내부 안내 단계: 'init' | 'to_requester' | 'to_target'
        self._guide_phase: str = 'init'
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

        self.get_logger().info('guide_function_node 시작.')

    # ------------------------------------------------------------------ #
    # 상태 변경 감지                                                         #
    # ------------------------------------------------------------------ #

    def _on_state(self, msg: String) -> None:
        new_state = msg.data
        if new_state == self._current_state:
            return

        old_state = self._current_state
        self._current_state = new_state
        self.get_logger().info(f'[GuideFunc] 상태 변경: {old_state} → {new_state}')
        self._on_state_enter(new_state)

    def _on_state_enter(self, state: str) -> None:
        if state == 'GUIDE':
            self.get_logger().info('[GuideFunc] GUIDE 태스크 진입. HQ 명령 대기...')
            self._reset_session()
            # 상태 전이 전에 도착한 pending 명령 처리
            if self._pending_command is not None:
                pending = self._pending_command
                self._pending_command = None
                self.get_logger().info(
                    f'[GuideFunc] pending 명령 처리: {pending.command}'
                )
                self._process_command(pending)
        else:
            self._pending_command = None
            if self._nav.is_navigating():
                self.get_logger().info('[GuideFunc] 태스크 종료. 이동 중지.')
                self._nav.cancel_goal()

    # ------------------------------------------------------------------ #
    # HQ 명령 처리                                                          #
    # ------------------------------------------------------------------ #

    def _on_command(self, msg: RobotCommand) -> None:
        if self._current_state != 'GUIDE':
            if msg.command == 'MoveToRequester':
                self.get_logger().info(
                    f'[GuideFunc] GUIDE 상태 아님 — MoveToRequester 버퍼링 (현재: {self._current_state})'
                )
                self._pending_command = msg
            return

        self._process_command(msg)

    def _process_command(self, msg: RobotCommand) -> None:
        cmd = msg.command
        self._session_id = msg.session_id
        self.get_logger().info(f'[GuideFunc] 명령 수신: {cmd}')

        if cmd == 'MoveToRequester':
            # 요청자 위치로 이동
            self._requester_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self._guide_phase = 'to_requester'
            self.get_logger().info(
                f'[GuideFunc] MoveToRequester — 요청자 위치로 이동: '
                f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}'
            )
            self._nav.send_goal(self._requester_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'RetryMoveToRequester':
            # 새 요청자 위치로 재이동
            self._requester_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self._guide_phase = 'to_requester'
            self.get_logger().info(
                f'[GuideFunc] RetryMoveToRequester — 요청자 재이동: '
                f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}'
            )
            self._nav.send_goal(self._requester_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'GuideStart':
            # 안내 목적지로 이동
            self._current_target_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self._guide_phase = 'to_target'
            self.get_logger().info(
                f'[GuideFunc] GuideStart — 안내 목적지로 이동: '
                f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}'
            )
            self._nav.send_goal(self._current_target_pose, on_arrived=self._on_arrived_target)

        elif cmd == 'RetryGuideStart':
            # 동일 안내 목적지 재이동 (HQ가 새 좌표를 보냈으면 갱신)
            if msg.x != 0.0 or msg.y != 0.0:
                self._current_target_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self.get_logger().info(
                f'[GuideFunc] RetryGuideStart — 동일 목적지 재이동: '
                f'({self._current_target_pose.pose.position.x:.2f}, '
                f'{self._current_target_pose.pose.position.y:.2f})'
            )
            self._nav.send_goal(self._current_target_pose, on_arrived=self._on_arrived_target)

        elif cmd == 'GuideEnd':
            self.get_logger().info('[GuideFunc] GuideEnd — 안내 종료.')
            self._reset_session()

    # ------------------------------------------------------------------ #
    # 내비게이션 콜백                                                        #
    # ------------------------------------------------------------------ #

    def _on_arrived_requester(self) -> None:
        self.get_logger().info('[GuideFunc] 요청자 위치 도착!')
        self._event_pub.publish_event('ArrivedAtRequester', self._session_id)

    def _on_arrived_target(self) -> None:
        self.get_logger().info('[GuideFunc] 안내 목적지 도착!')
        self._event_pub.publish_event('ArrivedAtTarget', self._session_id)

    # ------------------------------------------------------------------ #
    # 세션 초기화                                                            #
    # ------------------------------------------------------------------ #

    def _reset_session(self) -> None:
        self._nav.cancel_goal()
        self._session_id = ''
        self._requester_pose = None
        self._current_target_pose = None
        self._guide_phase = 'init'


def main(args=None):
    rclpy.init(args=args)
    node = GuideFunctionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('guide_function_node 종료')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
