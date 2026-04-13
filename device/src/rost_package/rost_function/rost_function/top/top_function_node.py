"""
top_function_node.py

Top FSM 기능 노드.

담당 상태:
  CHARGING           - 충전 중 (배터리 모니터링)
  CHARGING_NO_TASK   - 배터리 < 20%, 충전 중 (충전 증가 시뮬)
  CHARGING_WITH_TASK - 배터리 60~80%, 충전 중
  MOVE_TO_STANDBY    - 대기장소(standby_pos)로 이동
  STANDBY            - 작업 대기

기능:
  - /robot/battery 배터리 상태 주기 퍼블리시 (1 Hz)
  - 충전 중: 배터리 +0.5%/초, 작업 중: -0.2%/초
  - MOVE_TO_STANDBY: NavigationClient로 대기장소 이동
  - 대기장소 도달 시 "ArrivedAtStandby" 이벤트 퍼블리시

파라미터:
  use_nav2              : Nav2 사용 여부 (기본 False)
  simulated_nav_time    : 시뮬 이동 시간 (기본 3.0초)
  standby_pos_x/y/theta : 대기장소 좌표
  battery_level         : 초기 배터리 레벨 (0.0~1.0, 기본 0.8)
"""

import math

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String, Float32

from rost_state_machine.msg import RobotCommand
from rost_function.core.navigation_client import NavigationClient
from rost_function.core.event_publisher import EventPublisher


# Top FSM 상태 중 이 노드가 관심을 갖는 상태
_CHARGING_STATES = {'CHARGING', 'CHARGING_NO_TASK', 'CHARGING_WITH_TASK'}
_TASK_STATES = {'GUIDE', 'COLLECT', 'FOLLOW', 'DELIVERY'}


class TopFunctionNode(Node):
    """Top FSM 기능 노드"""

    def __init__(self):
        super().__init__('top_function_node')

        # ---------------------------------------------------------------- #
        # 파라미터 선언                                                       #
        # ---------------------------------------------------------------- #
        self.declare_parameter('use_nav2', False)
        self.declare_parameter('simulated_nav_time', 3.0)
        self.declare_parameter('standby_pos_x', 0.0)
        self.declare_parameter('standby_pos_y', 0.0)
        self.declare_parameter('standby_pos_theta', 0.0)
        self.declare_parameter('battery_level', 0.8)        # 초기 배터리 레벨

        # ---------------------------------------------------------------- #
        # 내부 상태                                                          #
        # ---------------------------------------------------------------- #
        self._current_state: str = ''
        self._battery_level: float = self.get_parameter('battery_level').value

        # ---------------------------------------------------------------- #
        # 공통 모듈                                                          #
        # ---------------------------------------------------------------- #
        use_nav2 = self.get_parameter('use_nav2').value
        sim_time = self.get_parameter('simulated_nav_time').value
        self._nav = NavigationClient(self, use_nav2=use_nav2, simulated_nav_time=sim_time)
        self._event_pub = EventPublisher(self)

        # ---------------------------------------------------------------- #
        # 퍼블리셔                                                           #
        # ---------------------------------------------------------------- #
        self._battery_pub = self.create_publisher(BatteryState, '/robot/battery', 10)
        # rost_state_machine이 /sim/battery_level을 구독하므로 통합 지원
        self._battery_sim_pub = self.create_publisher(Float32, '/sim/battery_level', 10)

        # ---------------------------------------------------------------- #
        # 서브스크라이버                                                      #
        # ---------------------------------------------------------------- #
        self._state_sub = self.create_subscription(
            String, '/robot/state', self._on_state, 10
        )
        self._cmd_sub = self.create_subscription(
            RobotCommand, '/hq/command', self._on_command, 10
        )

        # ---------------------------------------------------------------- #
        # 주기 타이머                                                         #
        # ---------------------------------------------------------------- #
        # 배터리 업데이트 및 퍼블리시 (1 Hz)
        self._battery_timer = self.create_timer(1.0, self._battery_tick)

        self.get_logger().info('top_function_node 시작.')

    # ------------------------------------------------------------------ #
    # /robot/state 콜백                                                    #
    # ------------------------------------------------------------------ #

    def _on_state(self, msg: String) -> None:
        new_state = msg.data
        if new_state == self._current_state:
            return

        old_state = self._current_state
        self._current_state = new_state
        self.get_logger().info(f'[TopFunc] 상태 변경: {old_state} → {new_state}')
        self._on_state_enter(new_state)

    def _on_state_enter(self, state: str) -> None:
        """상태 진입 시 처리"""
        if state == 'MOVE_TO_STANDBY':
            self._navigate_to_standby()

        elif state in _CHARGING_STATES:
            self.get_logger().info(
                f'[TopFunc] {state}: 충전 중. 배터리={self._battery_level*100:.1f}%'
            )

        elif state == 'STANDBY':
            self.get_logger().info('[TopFunc] STANDBY: 작업 대기 중.')

        elif state in _TASK_STATES:
            self.get_logger().info(
                f'[TopFunc] {state}: 작업 중. 배터리 소모 시뮬 시작.'
            )

    # ------------------------------------------------------------------ #
    # /hq/command 콜백 (Top 관련 명령 처리)                                  #
    # ------------------------------------------------------------------ #

    def _on_command(self, msg: RobotCommand) -> None:
        """Top Function Node에서 처리할 HQ 명령은 없음 (미래 확장용)"""
        pass

    # ------------------------------------------------------------------ #
    # 내비게이션                                                             #
    # ------------------------------------------------------------------ #

    def _navigate_to_standby(self) -> None:
        """파라미터로 설정된 대기장소로 이동"""
        x = self.get_parameter('standby_pos_x').value
        y = self.get_parameter('standby_pos_y').value
        theta = self.get_parameter('standby_pos_theta').value

        pose = self._make_pose(x, y, theta)
        self.get_logger().info(
            f'[TopFunc] 대기장소로 이동: ({x:.2f}, {y:.2f}, θ={theta:.2f}rad)'
        )
        self._nav.send_goal(pose, on_arrived=self._on_arrived_standby)

    def _on_arrived_standby(self) -> None:
        """대기장소 도달 시 처리"""
        self.get_logger().info('[TopFunc] 대기장소 도착!')
        self._event_pub.publish_event('ArrivedAtStandby', session_id='')

    # ------------------------------------------------------------------ #
    # 배터리 시뮬레이션                                                       #
    # ------------------------------------------------------------------ #

    def _battery_tick(self) -> None:
        """1초마다 배터리 레벨 업데이트 및 퍼블리시"""
        # 상태에 따라 배터리 증감
        if self._current_state in _CHARGING_STATES:
            # 충전 중: 0.5%/초 증가
            self._battery_level = min(1.0, self._battery_level + 0.005)
        elif self._current_state in _TASK_STATES:
            # 작업 중: 0.2%/초 감소
            self._battery_level = max(0.0, self._battery_level - 0.002)

        # /robot/battery 퍼블리시
        battery_msg = BatteryState()
        battery_msg.percentage = self._battery_level
        battery_msg.voltage = 24.0
        battery_msg.present = True
        self._battery_pub.publish(battery_msg)

        # /sim/battery_level 퍼블리시 (rost_state_machine 통합용)
        sim_msg = Float32()
        sim_msg.data = self._battery_level * 100.0  # % 단위
        self._battery_sim_pub.publish(sim_msg)

    # ------------------------------------------------------------------ #
    # 헬퍼                                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_pose(x: float, y: float, theta: float) -> PoseStamped:
        """PoseStamped 생성 헬퍼"""
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(theta / 2.0)
        pose.pose.orientation.w = math.cos(theta / 2.0)
        return pose


def main(args=None):
    rclpy.init(args=args)
    node = TopFunctionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('top_function_node 종료')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
