"""
delivery_function_node.py

운반 Sub FSM 기능 노드.

처리 명령 (state=DELIVERY 인 경우에만 반응):
  MoveToKitchen      → 주방으로 이동, 도달 시 ArrivedAtKitchen 퍼블리시
  StartDelivery      → (첫 호출) 목적지 저장 후 이동 시작
                       (이후 호출) 다음 목적지로 이동
                       도달 시 ArrivedAtMenuLocation 퍼블리시
  RetryStartDelivery → 동일 목적지로 재이동, 도달 시 ArrivedAtMenuLocation 퍼블리시
  DeliveryEnd        → 운반 종료, 이동 중지, 세션 초기화

파라미터:
  use_nav2           : Nav2 사용 여부 (기본 False)
  simulated_nav_time : 시뮬 이동 시간 (기본 3.0초)
"""

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String

from typing import Optional

from rost_state_machine.msg import RobotCommand
from rost_function.core.navigation_client import NavigationClient
from rost_function.core.event_publisher import EventPublisher
from rost_function.core.pose_utils import pose_from_xyt


class DeliveryFunctionNode(Node):
    """운반 Sub FSM 기능 노드"""

    def __init__(self):
        super().__init__('delivery_function_node')

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
        self._kitchen_pose: PoseStamped = None           # 주방 위치
        self._current_menu_pose: PoseStamped = None      # 현재 배송 목적지
        # 내부 배송 단계: 'init' | 'kitchen' | 'menu'
        self._delivery_phase: str = 'init'
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

        self.get_logger().info('delivery_function_node 시작.')

    # ------------------------------------------------------------------ #
    # 상태 변경 감지                                                         #
    # ------------------------------------------------------------------ #

    def _on_state(self, msg: String) -> None:
        new_state = msg.data
        if new_state == self._current_state:
            return

        old_state = self._current_state
        self._current_state = new_state
        self.get_logger().info(f'[DeliveryFunc] 상태 변경: {old_state} → {new_state}')
        self._on_state_enter(new_state)

    def _on_state_enter(self, state: str) -> None:
        if state == 'DELIVERY':
            self.get_logger().info('[DeliveryFunc] DELIVERY 태스크 진입. HQ 명령 대기...')
            self._reset_session()
            # 상태 전이 전에 도착한 pending 명령 처리
            if self._pending_command is not None:
                pending = self._pending_command
                self._pending_command = None
                self.get_logger().info(
                    f'[DeliveryFunc] pending 명령 처리: {pending.command}'
                )
                self._process_command(pending)
        else:
            self._pending_command = None
            if self._nav.is_navigating():
                self.get_logger().info('[DeliveryFunc] 태스크 종료. 이동 중지.')
                self._nav.cancel_goal()

    # ------------------------------------------------------------------ #
    # HQ 명령 처리                                                          #
    # ------------------------------------------------------------------ #

    def _on_command(self, msg: RobotCommand) -> None:
        if self._current_state != 'DELIVERY':
            if msg.command == 'MoveToKitchen':
                self.get_logger().info(
                    f'[DeliveryFunc] DELIVERY 상태 아님 — MoveToKitchen 버퍼링 (현재: {self._current_state})'
                )
                self._pending_command = msg
            return

        self._process_command(msg)

    def _process_command(self, msg: RobotCommand) -> None:
        cmd = msg.command
        self._session_id = msg.session_id
        self.get_logger().info(f'[DeliveryFunc] 명령 수신: {cmd}')

        if cmd == 'MoveToKitchen':
            # 주방으로 이동
            self._kitchen_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self._delivery_phase = 'kitchen'
            self.get_logger().info(
                f'[DeliveryFunc] MoveToKitchen — 주방으로 이동: '
                f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}'
            )
            self._nav.send_goal(self._kitchen_pose, on_arrived=self._on_arrived_kitchen)

        elif cmd == 'StartDelivery':
            # 배송 목적지 저장 및 이동
            self._current_menu_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self._delivery_phase = 'menu'
            self.get_logger().info(
                f'[DeliveryFunc] StartDelivery — 배송 목적지로 이동: '
                f'({msg.x:.2f}, {msg.y:.2f}) θ={msg.theta:.2f}'
            )
            self._nav.send_goal(self._current_menu_pose, on_arrived=self._on_arrived_menu_loc)

        elif cmd == 'RetryStartDelivery':
            # 동일 목적지로 재이동 (이전 목적지가 없으면 현재 msg 값 사용)
            if self._current_menu_pose is None:
                self._current_menu_pose = pose_from_xyt(self, msg.x, msg.y, msg.theta)
            self.get_logger().info(
                f'[DeliveryFunc] RetryStartDelivery — 동일 목적지 재이동: '
                f'({self._current_menu_pose.pose.position.x:.2f}, '
                f'{self._current_menu_pose.pose.position.y:.2f})'
            )
            self._nav.send_goal(self._current_menu_pose, on_arrived=self._on_arrived_menu_loc)

        elif cmd == 'DeliveryEnd':
            self.get_logger().info('[DeliveryFunc] DeliveryEnd — 운반 종료.')
            self._reset_session()

    # ------------------------------------------------------------------ #
    # 내비게이션 콜백                                                        #
    # ------------------------------------------------------------------ #

    def _on_arrived_kitchen(self) -> None:
        self.get_logger().info('[DeliveryFunc] 주방 도착!')
        self._event_pub.publish_event('ArrivedAtKitchen', self._session_id)

    def _on_arrived_menu_loc(self) -> None:
        self.get_logger().info('[DeliveryFunc] 배송 목적지 도착!')
        self._event_pub.publish_event('ArrivedAtMenuLocation', self._session_id)

    # ------------------------------------------------------------------ #
    # 세션 초기화                                                            #
    # ------------------------------------------------------------------ #

    def _reset_session(self) -> None:
        self._nav.cancel_goal()
        self._session_id = ''
        self._kitchen_pose = None
        self._current_menu_pose = None
        self._delivery_phase = 'init'


def main(args=None):
    rclpy.init(args=args)
    node = DeliveryFunctionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('delivery_function_node 종료')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
