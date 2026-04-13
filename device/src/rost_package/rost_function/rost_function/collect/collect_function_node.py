"""
collect_function_node.py

수거 Sub FSM 기능 노드.

처리 명령 (state=COLLECT 인 경우에만 반응):
  CollectRequest      → 수거 위치로 이동, 도달 시 ArrivedAtRequester 퍼블리시
  RetryCollectRequest → 새 위치로 재이동, 도달 시 ArrivedAtRequester 퍼블리시
  StartCollection     → 수거 시작 (request_count 증가)
  CollectionDone      → 수거 완료:
                         배터리 < 20% or request_count >= max_collect_count
                         → 설거지장으로 이동, 도달 시 ArrivedAtDishwashing 퍼블리시
                         그 외 → 수거 종료
  MoveToDishwashing   → 설거지장으로 이동, 도달 시 ArrivedAtDishwashing 퍼블리시
  CollectionEnd       → 수거 종료, 세션 초기화

파라미터:
  use_nav2           : Nav2 사용 여부 (기본 False)
  simulated_nav_time : 시뮬 이동 시간 (기본 3.0초)
  dishwash_pos_x/y/theta : 설거지장 좌표
  max_collect_count  : 설거지장 이동 임계 수거 횟수 (기본 5)
  battery_low        : 배터리 부족 임계값 % (기본 20.0)
"""

import math

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String
from sensor_msgs.msg import BatteryState

from rost_state_machine.msg import RobotCommand
from rost_function.core.navigation_client import NavigationClient
from rost_function.core.event_publisher import EventPublisher


class CollectFunctionNode(Node):
    """수거 Sub FSM 기능 노드"""

    def __init__(self):
        super().__init__('collect_function_node')

        # ---------------------------------------------------------------- #
        # 파라미터                                                           #
        # ---------------------------------------------------------------- #
        self.declare_parameter('use_nav2', False)
        self.declare_parameter('simulated_nav_time', 3.0)
        self.declare_parameter('dishwash_pos_x', 0.0)
        self.declare_parameter('dishwash_pos_y', 0.0)
        self.declare_parameter('dishwash_pos_theta', 0.0)
        self.declare_parameter('max_collect_count', 5)
        self.declare_parameter('battery_low', 20.0)   # % 단위

        # ---------------------------------------------------------------- #
        # 내부 상태                                                          #
        # ---------------------------------------------------------------- #
        self._current_state: str = ''
        self._session_id: str = ''
        self._requester_pose: PoseStamped = None  # 수거 요청자 위치
        self._request_count: int = 0              # 누적 수거 횟수
        self._battery_percent: float = 100.0      # 최근 배터리 레벨 (%)

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
        # 배터리 모니터링 (설거지장 이동 판단에 사용)
        self._battery_sub = self.create_subscription(
            BatteryState, '/robot/battery', self._on_battery, 10
        )

        self.get_logger().info('collect_function_node 시작.')

    # ------------------------------------------------------------------ #
    # 상태 변경 감지                                                         #
    # ------------------------------------------------------------------ #

    def _on_state(self, msg: String) -> None:
        new_state = msg.data
        if new_state == self._current_state:
            return

        old_state = self._current_state
        self._current_state = new_state
        self.get_logger().info(f'[CollectFunc] 상태 변경: {old_state} → {new_state}')
        self._on_state_enter(new_state)

    def _on_state_enter(self, state: str) -> None:
        if state == 'COLLECT':
            self.get_logger().info('[CollectFunc] COLLECT 태스크 진입. HQ 명령 대기...')
            self._reset_session()
        elif state not in ('COLLECT',):
            if self._nav.is_navigating():
                self.get_logger().info('[CollectFunc] 태스크 종료. 이동 중지.')
                self._nav.cancel_goal()

    # ------------------------------------------------------------------ #
    # /robot/battery 콜백                                                  #
    # ------------------------------------------------------------------ #

    def _on_battery(self, msg: BatteryState) -> None:
        """배터리 레벨 업데이트 (percentage: 0.0~1.0)"""
        self._battery_percent = msg.percentage * 100.0

    # ------------------------------------------------------------------ #
    # HQ 명령 처리                                                          #
    # ------------------------------------------------------------------ #

    def _on_command(self, msg: RobotCommand) -> None:
        if self._current_state != 'COLLECT':
            return

        cmd = msg.command
        self._session_id = msg.session_id
        self.get_logger().info(f'[CollectFunc] 명령 수신: {cmd}')

        if cmd == 'CollectRequest':
            # 수거 위치로 이동
            self._requester_pose = msg.target_pose
            self.get_logger().info(
                f'[CollectFunc] CollectRequest — 수거 위치로 이동: '
                f'({msg.target_pose.pose.position.x:.2f}, '
                f'{msg.target_pose.pose.position.y:.2f})'
            )
            self._nav.send_goal(self._requester_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'RetryCollectRequest':
            # 새 위치로 재이동
            new_pose = msg.target_pose if msg.target_pose else self._requester_pose
            self._requester_pose = new_pose
            self.get_logger().info(
                f'[CollectFunc] RetryCollectRequest — 재이동: '
                f'({new_pose.pose.position.x:.2f}, {new_pose.pose.position.y:.2f})'
            )
            self._nav.send_goal(self._requester_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'StartCollection':
            # 수거 시작 — request_count 증가
            self._request_count += 1
            self.get_logger().info(
                f'[CollectFunc] StartCollection — 수거 시작. '
                f'누적 횟수: {self._request_count}'
            )

        elif cmd == 'CollectionDone':
            # 수거 완료 — 조건에 따라 설거지장 이동 or 종료
            low = self.get_parameter('battery_low').value
            max_count = self.get_parameter('max_collect_count').value
            go_dishwash = (
                self._battery_percent < low
                or self._request_count >= max_count
            )
            self.get_logger().info(
                f'[CollectFunc] CollectionDone — 배터리={self._battery_percent:.1f}%, '
                f'수거횟수={self._request_count}. '
                f'→ {"설거지장 이동" if go_dishwash else "수거 종료"}'
            )
            if go_dishwash:
                self._navigate_to_dishwash()
            else:
                self.get_logger().info('[CollectFunc] 수거 종료 처리.')
                # rost_state_machine이 COLLECT_END 처리 — 여기서는 로깅만

        elif cmd == 'MoveToDishwashing':
            # 명시적 설거지장 이동 명령
            self.get_logger().info('[CollectFunc] MoveToDishwashing — 설거지장으로 이동.')
            self._navigate_to_dishwash()

        elif cmd == 'CollectionEnd':
            self.get_logger().info('[CollectFunc] CollectionEnd — 수거 종료.')
            self._reset_session()

    # ------------------------------------------------------------------ #
    # 내비게이션 콜백                                                        #
    # ------------------------------------------------------------------ #

    def _on_arrived_requester(self) -> None:
        self.get_logger().info('[CollectFunc] 수거 위치 도착!')
        self._event_pub.publish_event('ArrivedAtRequester', self._session_id)

    def _on_arrived_dishwash(self) -> None:
        self.get_logger().info('[CollectFunc] 설거지장 도착!')
        self._event_pub.publish_event('ArrivedAtDishwashing', self._session_id)

    # ------------------------------------------------------------------ #
    # 헬퍼                                                                  #
    # ------------------------------------------------------------------ #

    def _navigate_to_dishwash(self) -> None:
        """파라미터로 설정된 설거지장으로 이동"""
        x = self.get_parameter('dishwash_pos_x').value
        y = self.get_parameter('dishwash_pos_y').value
        theta = self.get_parameter('dishwash_pos_theta').value
        pose = self._make_pose(x, y, theta)
        self.get_logger().info(f'[CollectFunc] 설거지장으로 이동: ({x:.2f}, {y:.2f})')
        self._nav.send_goal(pose, on_arrived=self._on_arrived_dishwash)

    def _reset_session(self) -> None:
        """세션 데이터 및 수거 횟수 초기화"""
        self._nav.cancel_goal()
        self._session_id = ''
        self._requester_pose = None
        self._request_count = 0

    @staticmethod
    def _make_pose(x: float, y: float, theta: float) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(theta / 2.0)
        pose.pose.orientation.w = math.cos(theta / 2.0)
        return pose


def main(args=None):
    rclpy.init(args=args)
    node = CollectFunctionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('collect_function_node 종료')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
