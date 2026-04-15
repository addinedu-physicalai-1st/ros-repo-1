#!/usr/bin/env python3
"""
robot_state_machine_node

레스토랑 서빙 로봇 상태 기계 메인 ROS2 노드.

- TopFSM 인스턴스를 보유하고 생명주기를 관리
- HQ 명령(/hq/command)을 수신하여 FSM에 전달
- 로봇 이벤트(/robot/event)를 HQ에 퍼블리시
- 현재 FSM 상태(/robot/state)를 주기적으로 퍼블리시
- 배터리 상태(/robot/battery)를 주기적으로 퍼블리시
- 내비게이션을 타이머 기반으로 시뮬레이션
- 작업 요청 서비스(/robot/task_request) 제공

파라미터:
  timeout_secs    : VERIFY 상태 타임아웃 시간 (기본 30.0초)
  battery_low     : 배터리 부족 임계값 (기본 20.0%)
  battery_mid     : 배터리 중간 임계값 (기본 60.0%)
  battery_high    : 배터리 충분 임계값 (기본 80.0%)
  nav_delay       : 내비게이션 시뮬레이션 지연 시간 (기본 5.0초)
"""

import rclpy
from rclpy.node import Node

from std_msgs.msg import String, Float32
from sensor_msgs.msg import BatteryState
from geometry_msgs.msg import PoseStamped

from rost_state_machine.msg import RobotCommand, RobotEvent
from rost_state_machine.srv import TaskRequest
from rost_state_machine.top_fsm import TopFSM, TopState

try:
    from pinkylib import Battery as _PinkyBattery
    _battery_hw = _PinkyBattery()
except Exception:
    _battery_hw = None


class StateMachineNode(Node):
    """레스토랑 서빙 로봇 상태 기계 노드"""

    def __init__(self):
        super().__init__('robot_state_machine_node')

        # ---------------------------------------------------------------- #
        # ROS2 파라미터 선언                                                 #
        # ---------------------------------------------------------------- #
        self.declare_parameter('timeout_secs', 30.0)      # VERIFY 타임아웃
        self.declare_parameter('battery_low', 20.0)       # 배터리 부족 임계값 (%)
        self.declare_parameter('battery_mid', 60.0)       # 배터리 중간 임계값 (%)
        self.declare_parameter('battery_high', 80.0)      # 배터리 충분 임계값 (%)
        self.declare_parameter('nav_delay', 5.0)          # 내비게이션 시뮬 지연 (초)
        self.declare_parameter('max_request_count', 3)    # 수거 횟수 상한

        # ---------------------------------------------------------------- #
        # 내부 상태                                                          #
        # ---------------------------------------------------------------- #
        self._battery_level: float = 85.0   # 초기 배터리 (충분히 높음)
        self._battery_hw = _battery_hw
        self._current_state: str = 'INIT'
        self._nav_timer = None              # 내비게이션 시뮬 타이머
        self._nav_callback = None           # 내비게이션 완료 콜백

        # ---------------------------------------------------------------- #
        # TopFSM 생성                                                        #
        # ---------------------------------------------------------------- #
        self._top_fsm = TopFSM(self)

        # ---------------------------------------------------------------- #
        # 퍼블리셔                                                           #
        # ---------------------------------------------------------------- #
        self._state_pub = self.create_publisher(
            String, '/robot/state', 10
        )
        self._event_pub = self.create_publisher(
            RobotEvent, '/robot/event', 10
        )
        self._battery_pub = self.create_publisher(
            BatteryState, '/robot/battery', 10
        )

        # ---------------------------------------------------------------- #
        # 서브스크라이버                                                      #
        # ---------------------------------------------------------------- #
        # HQ 명령 수신
        self._cmd_sub = self.create_subscription(
            RobotCommand,
            '/hq/command',
            self._on_hq_command,
            10
        )
        # 내비게이션 목표 수신 (선택적 — 실제 내비게이션 스택 연동 시 활용)
        self._nav_goal_sub = self.create_subscription(
            PoseStamped,
            '/hq/navigation_goal',
            self._on_navigation_goal,
            10
        )
        # 시뮬레이션용 배터리 레벨 오버라이드
        self._battery_sim_sub = self.create_subscription(
            Float32,
            '/sim/battery_level',
            self._on_battery_sim,
            10
        )

        # ---------------------------------------------------------------- #
        # 서비스 서버                                                         #
        # ---------------------------------------------------------------- #
        self._task_srv = self.create_service(
            TaskRequest,
            '/robot/task_request',
            self._on_task_request
        )

        # ---------------------------------------------------------------- #
        # 주기 타이머                                                         #
        # ---------------------------------------------------------------- #
        # 상태 퍼블리시 (1 Hz)
        self._state_pub_timer = self.create_timer(1.0, self._publish_state)
        # 배터리 퍼블리시 (1 Hz)
        self._battery_pub_timer = self.create_timer(1.0, self._publish_battery)
        # 초기 배터리 평가 트리거: 노드 시작 직후 FSM에 현재 배터리 레벨을 전달하여
        # use_sim_time 환경에서 타이머 지연과 무관하게 초기 상태를 결정한다.
        self._init_battery_trigger = self.create_timer(
            0.5, self._trigger_initial_battery_eval
        )

        # ---------------------------------------------------------------- #
        # FSM 시작                                                           #
        # ---------------------------------------------------------------- #
        self.get_logger().info('robot_state_machine_node 시작. TopFSM 초기화...')
        self._top_fsm.start()

    # ------------------------------------------------------------------ #
    # TopFSM / SubFSM이 호출하는 공개 인터페이스                              #
    # ------------------------------------------------------------------ #

    def publish_event(self, event_name: str, session_id: str = '',
                      pose: PoseStamped = None) -> None:
        """
        ROBOT → HQ 이벤트 퍼블리시.
        FSM에서 도착/완료 이벤트를 HQ에 알릴 때 호출한다.
        """
        msg = RobotEvent()
        msg.event = event_name
        msg.session_id = session_id
        if pose is not None:
            msg.current_pose = pose
        self._event_pub.publish(msg)
        self.get_logger().info(f'[EVENT → HQ] {event_name} (세션: {session_id})')

    def publish_top_state(self, state_name: str) -> None:
        """TopFSM 상태 변경 시 즉시 /robot/state 퍼블리시"""
        self._current_state = state_name
        msg = String()
        msg.data = state_name
        self._state_pub.publish(msg)

    def navigate_to(self, label: str, on_arrived) -> None:
        """
        내비게이션 시뮬레이션.
        nav_delay 초 후 on_arrived 콜백을 호출한다.
        실제 로봇에서는 Nav2 액션 클라이언트로 교체.
        """
        nav_delay = self.get_parameter('nav_delay').value
        self.get_logger().info(
            f'[NAV] {label} 이동 시작. (시뮬: {nav_delay:.1f}초 후 도착)'
        )

        # 이전 내비게이션 취소
        if self._nav_timer is not None:
            self._nav_timer.cancel()
            self._nav_timer = None

        self._nav_callback = on_arrived
        self._nav_timer = self.create_timer(
            nav_delay,
            self._on_nav_timer_fired
        )

    # ------------------------------------------------------------------ #
    # 내부 콜백                                                             #
    # ------------------------------------------------------------------ #

    def _on_nav_timer_fired(self) -> None:
        """내비게이션 완료 시뮬레이션 콜백"""
        if self._nav_timer is not None:
            self._nav_timer.cancel()
            self._nav_timer = None

        callback = self._nav_callback
        self._nav_callback = None

        self.get_logger().info('[NAV] 목적지 도착!')
        if callback:
            callback()

    def _on_hq_command(self, msg: RobotCommand) -> None:
        """HQ 명령 수신 콜백"""
        self.get_logger().info(
            f'[CMD ← HQ] {msg.command} (세션: {msg.session_id})'
        )
        self._top_fsm.handle_command(msg.command, msg)

    def _on_navigation_goal(self, msg: PoseStamped) -> None:
        """HQ로부터 내비게이션 목표 수신 (실제 로봇 연동 시 활용)"""
        self.get_logger().debug(f'[NAV GOAL] {msg.pose.position}')

    def _trigger_initial_battery_eval(self) -> None:
        """노드 시작 직후 1회만 실행 — FSM 초기 배터리 평가를 강제 트리거"""
        self._init_battery_trigger.cancel()
        self._init_battery_trigger = None
        self.get_logger().info(
            f'[FSM] 초기 배터리 평가 트리거. 현재 레벨: {self._battery_level:.1f}%'
        )
        self._top_fsm.update_battery(self._battery_level)

    def _on_battery_sim(self, msg: Float32) -> None:
        """시뮬레이션용 배터리 오버라이드 수신"""
        old = self._battery_level
        self._battery_level = float(msg.data)
        self.get_logger().info(
            f'[SIM] 배터리 레벨 변경: {old:.1f}% → {self._battery_level:.1f}%'
        )
        self._top_fsm.update_battery(self._battery_level)

    def _on_task_request(self, request: TaskRequest.Request,
                         response: TaskRequest.Response) -> TaskRequest.Response:
        """
        /robot/task_request 서비스 핸들러.
        HQ가 작업 종류와 목표를 직접 서비스로 요청한다.
        """
        task = request.task_type
        self.get_logger().info(
            f'[SERVICE] 작업 요청 수신: {task} (세션: {request.session_id})'
        )

        # 현재 TopFSM 상태 확인
        current = self._top_fsm.state
        if current not in (TopState.STANDBY, TopState.CHARGING_WITH_TASK):
            response.accepted = False
            response.message = (
                f'현재 상태({current.name})에서는 작업을 수락할 수 없습니다.'
            )
            return response

        # 작업 유형별 명령 생성
        task_command_map = {
            'FOLLOW': 'FollowRequest',
            'DELIVERY': 'MoveToKitchen',
            'COLLECT': 'CollectRequest',
            'GUIDE': 'MoveToRequester',
        }
        command = task_command_map.get(task.upper())
        if command is None:
            response.accepted = False
            response.message = f'알 수 없는 작업 유형: {task}'
            return response

        # RobotCommand 형태로 FSM에 전달
        fake_msg = RobotCommand()
        fake_msg.command = command
        fake_msg.session_id = request.session_id
        fake_msg.x = request.x
        fake_msg.y = request.y
        fake_msg.theta = request.theta

        self._top_fsm.handle_command(command, fake_msg)

        response.accepted = True
        response.message = f'{task} 작업 수락됨.'
        return response

    def _publish_state(self) -> None:
        """현재 FSM 상태를 주기적으로 퍼블리시"""
        msg = String()
        msg.data = self._current_state
        self._state_pub.publish(msg)

    def _publish_battery(self) -> None:
        """배터리 상태를 주기적으로 퍼블리시"""
        if self._battery_hw is not None:
            try:
                voltage = float(self._battery_hw.get_voltage())
                percent_raw = self._battery_hw.battery_percentage()  # 0~100
                self._battery_level = float(percent_raw)             # % 단위 유지
                self._top_fsm.update_battery(self._battery_level)
            except Exception as e:
                self.get_logger().warn(f'[FSM] 배터리 읽기 실패: {e}')
                voltage = 0.0
        else:
            voltage = 0.0

        msg = BatteryState()
        msg.percentage = self._battery_level / 100.0  # 0.0 ~ 1.0
        msg.voltage = voltage
        msg.present = True
        self._battery_pub.publish(msg)


# ------------------------------------------------------------------ #
# 엔트리포인트                                                           #
# ------------------------------------------------------------------ #

def main(args=None):
    rclpy.init(args=args)
    node = StateMachineNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('종료 요청 (Ctrl+C)')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
