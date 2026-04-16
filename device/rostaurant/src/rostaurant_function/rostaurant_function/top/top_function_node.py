"""
top_function_node.py

Top FSM 기능 노드.

담당 상태:
  CHARGING           - 충전 중 (배터리 모니터링)
  CHARGING_NO_TASK   - 배터리 < 20%, 충전 중
  CHARGING_WITH_TASK - 배터리 60~80%, 충전 중
  MOVE_TO_STANDBY    - 대기장소(standby_pos)로 이동
  STANDBY            - 작업 대기

기능:
  - /robot/battery 구독하여 배터리 상태 수신 (fsm_node에서 publish)
  - MOVE_TO_STANDBY: NavigationClient로 대기장소 이동
  - 대기장소 도달 시 "ArrivedAtStandby" 이벤트 퍼블리시

파라미터:
  use_nav2              : Nav2 사용 여부 (기본 False)
  simulated_nav_time    : 시뮬 이동 시간 (기본 3.0초)
  standby_pos_x/y/theta : 대기장소 좌표
"""

import math

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String

from rostaurant_state_machine.msg import RobotCommand
from rostaurant_function.core.navigation_client import NavigationClient
from rostaurant_function.core.event_publisher import EventPublisher


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
        self.declare_parameter('charging_pos_x', 0.0)
        self.declare_parameter('charging_pos_y', 0.0)
        self.declare_parameter('charging_pos_theta', 0.0)

        # ---------------------------------------------------------------- #
        # 내부 상태                                                          #
        # ---------------------------------------------------------------- #
        self._current_state: str = ''
        self._battery_level: float = 0.0   # /robot/battery 에서 수신한 값 (0.0~1.0)
        self._battery_voltage: float = 0.0
        self._docking_active: bool = False  # pinky_docking 진행 중 여부

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
        self._docking_pub = self.create_publisher(String, '/docking/cmd', 10)

        # ---------------------------------------------------------------- #
        # 서브스크라이버                                                      #
        # ---------------------------------------------------------------- #
        self._state_sub = self.create_subscription(
            String, '/robot/state', self._on_state, 10
        )
        self._cmd_sub = self.create_subscription(
            RobotCommand, '/hq/command', self._on_command, 10
        )
        self._battery_sub = self.create_subscription(
            BatteryState, '/robot/battery', self._on_battery, 10
        )
        self._docking_status_sub = self.create_subscription(
            String, '/docking/status', self._on_docking_status, 10
        )

        self.get_logger().info('top_function_node 시작.')

    # ------------------------------------------------------------------ #
    # /robot/battery 콜백                                                  #
    # ------------------------------------------------------------------ #

    def _on_battery(self, msg: BatteryState) -> None:
        """fsm_node가 publish하는 배터리 상태 수신"""
        self._battery_level = msg.percentage   # 0.0~1.0
        self._battery_voltage = msg.voltage

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
        if state == 'MOVE_TO_CHARGING':
            self._navigate_to_charging()

        elif state == 'MOVE_TO_STANDBY':
            self._navigate_to_standby()

        elif state in _CHARGING_STATES:
            self.get_logger().info(
                f'[TopFunc] {state}: 충전 중. '
                f'배터리={self._battery_level*100:.1f}% ({self._battery_voltage:.2f}V)'
            )

        elif state == 'STANDBY':
            self.get_logger().info('[TopFunc] STANDBY: 작업 대기 중.')

        elif state in _TASK_STATES:
            self.get_logger().info(
                f'[TopFunc] {state}: 작업 중. '
                f'배터리={self._battery_level*100:.1f}% ({self._battery_voltage:.2f}V)'
            )

    # ------------------------------------------------------------------ #
    # /docking/status 콜백                                                 #
    # ------------------------------------------------------------------ #

    def _on_docking_status(self, msg: String) -> None:
        """pinky_docking 노드 상태 수신 (IDLE / RUNNING / DOCKED).
        DOCKED 수신 시 ArrivedAtCharging 이벤트를 발행하여 FSM을 CHARGING으로 전이시킨다."""
        self.get_logger().info(f'[TopFunc] 도킹 상태: {msg.data}')
        if msg.data == 'DOCKED' and self._docking_active:
            self._docking_active = False
            self.get_logger().info('[TopFunc] 도킹 완료! ArrivedAtCharging 이벤트 발행')
            self._event_pub.publish_event('ArrivedAtCharging', session_id='')

    # ------------------------------------------------------------------ #
    # /hq/command 콜백 (Top 관련 명령 처리)                                  #
    # ------------------------------------------------------------------ #

    def _on_command(self, msg: RobotCommand) -> None:
        """Top Function Node에서 처리할 HQ 명령은 없음 (미래 확장용)"""
        pass

    # ------------------------------------------------------------------ #
    # 내비게이션                                                             #
    # ------------------------------------------------------------------ #

    def _navigate_to_charging(self) -> None:
        """파라미터로 설정된 충전소로 이동"""
        x = self.get_parameter('charging_pos_x').value
        y = self.get_parameter('charging_pos_y').value
        theta = self.get_parameter('charging_pos_theta').value

        pose = self._make_pose(x, y, theta)
        self.get_logger().info(
            f'[TopFunc] 충전소로 이동: ({x:.2f}, {y:.2f}, θ={theta:.2f}rad)'
        )
        self._nav.send_goal(pose, on_arrived=self._on_arrived_charging)

    def _on_arrived_charging(self) -> None:
        """Nav2 충전소 근처 도착 → pinky_docking 시작.
        ArrivedAtCharging 이벤트는 도킹 완료(DOCKED) 후 발행한다."""
        self.get_logger().info('[TopFunc] 충전소 근처 도착. 도킹 시작...')
        self._docking_active = True
        dock_msg = String()
        dock_msg.data = 'start'
        self._docking_pub.publish(dock_msg)
        self.get_logger().info('[TopFunc] /docking/cmd → start')

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
