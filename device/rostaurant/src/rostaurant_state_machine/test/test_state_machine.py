#!/usr/bin/env python3
"""
test_state_machine.py

HQ 역할을 시뮬레이션하는 테스트 노드.

기능:
  - /hq/command 토픽에 RobotCommand 메시지 퍼블리시
  - /robot/event 토픽을 구독하여 로봇 이벤트 콘솔 출력
  - /robot/state 토픽을 구독하여 현재 FSM 상태 콘솔 출력
  - /sim/battery_level 토픽으로 배터리 레벨 조작
  - 각 시나리오 (동행/운반/수거/안내) 자동 시뮬레이션

실행:
  ros2 run rostaurant_state_machine test_state_machine.py
  또는
  ros2 run rostaurant_state_machine test_state_machine.py --ros-args -p scenario:=follow

파라미터:
  scenario        : 실행할 시나리오
                    follow | delivery | collect | guide | battery | collect_gz | docking | all
                    기본값 = all
  step_delay      : 명령 사이 대기 시간 (초), 기본값 = 3.0
  collect_done_delay : collect_gz 시나리오에서 StartCollection 발행 후
                       CollectionDone 발행까지 대기 시간 (초), 기본값 = 3.0
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String

from rostaurant_state_machine.msg import RobotCommand, RobotEvent


class HQSimulatorNode(Node):
    """HQ 시뮬레이터 노드"""

    def __init__(self):
        super().__init__('hq_simulator_node')

        # 파라미터
        self.declare_parameter('scenario', 'all')
        self.declare_parameter('step_delay', 3.0)
        self.declare_parameter('collect_done_delay', 3.0)

        # 퍼블리셔
        self._cmd_pub = self.create_publisher(RobotCommand, '/hq/command', 10)
        self._battery_pub = self.create_publisher(Float32, '/sim/battery_level', 10)

        # 서브스크라이버
        self._state_sub = self.create_subscription(
            String, '/robot/state', self._on_robot_state, 10
        )
        self._event_sub = self.create_subscription(
            RobotEvent, '/robot/event', self._on_robot_event, 10
        )
        self._docking_status_sub = self.create_subscription(
            String, '/docking/status', self._on_docking_status, 10
        )
        self._docking_cmd_sub = self.create_subscription(
            String, '/docking/cmd', self._on_docking_cmd, 10
        )

        # 시나리오 실행 상태
        self._scenario_steps = []
        self._step_idx = 0
        self._step_timer = None
        self._scenario_mode: str = ''

        # collect_gz 이벤트 기반 상태
        self._collect_gz_session_id: str = ''
        self._collect_gz_arrived: bool = False   # ArrivedAtRequester 수신 여부
        self._collect_gz_done_timer = None

        # 1초 후 시나리오 시작 (노드 초기화 대기) — 한 번만 실행되도록 참조 저장
        self._init_timer = self.create_timer(1.0, self._start_scenarios)
        self.get_logger().info('HQ 시뮬레이터 시작. 1초 후 시나리오를 실행합니다.')

    # ------------------------------------------------------------------ #
    # 구독 콜백                                                             #
    # ------------------------------------------------------------------ #

    def _on_robot_state(self, msg: String) -> None:
        self.get_logger().info(f'[ROBOT STATE] → {msg.data}')

    def _on_docking_status(self, msg: String) -> None:
        self.get_logger().info(f'[DOCKING STATUS] → {msg.data}')

    def _on_docking_cmd(self, msg: String) -> None:
        self.get_logger().info(f'[DOCKING CMD] → {msg.data}')

    def _on_robot_event(self, msg: RobotEvent) -> None:
        self.get_logger().info(
            f'[ROBOT EVENT] {msg.event} (세션: {msg.session_id})'
        )
        # collect_gz 시나리오: 이벤트 기반으로 수거 명령 자동 발행
        if self._scenario_mode == 'collect_gz':
            self._handle_collect_gz_event(msg.event, msg.session_id)

    def _handle_collect_gz_event(self, event: str, session_id: str) -> None:
        """collect_gz 시나리오 이벤트 핸들러"""
        if event == 'ArrivedAtRequester' and not self._collect_gz_arrived:
            self._collect_gz_arrived = True
            self._collect_gz_session_id = session_id
            self.get_logger().info(
                '[COLLECT_GZ] 수거 위치 도착 확인! StartCollection 발행'
            )
            self._send_command('StartCollection', session_id)

            # collect_done_delay 초 후 CollectionDone 발행 (1회만 실행)
            delay = self.get_parameter('collect_done_delay').value
            self._collect_gz_done_timer = self.create_timer(
                delay, self._send_collection_done_gz
            )

    def _send_collection_done_gz(self) -> None:
        """collect_gz: CollectionDone 발행 후 타이머 취소"""
        if self._collect_gz_done_timer is not None:
            self._collect_gz_done_timer.cancel()
            self._collect_gz_done_timer = None

        self.get_logger().info(
            '[COLLECT_GZ] CollectionDone 발행 → 로봇이 standby(0, 0, 0)으로 복귀 시작'
        )
        self._send_command('CollectionDone', self._collect_gz_session_id)

    # ------------------------------------------------------------------ #
    # 퍼블리시 헬퍼                                                          #
    # ------------------------------------------------------------------ #

    def _send_command(self, command: str, session_id: str = 'sim-001',
                      x: float = 0.0, y: float = 0.0, theta: float = 0.0,
                      count: int = 0) -> None:
        """HQ → ROBOT 명령 전송"""
        msg = RobotCommand()
        msg.command = command
        msg.session_id = session_id
        msg.x = x
        msg.y = y
        msg.theta = theta
        msg.count = count
        self._cmd_pub.publish(msg)
        self.get_logger().info(f'[HQ → ROBOT] 명령 전송: {command}')

    def _set_battery(self, level: float) -> None:
        """배터리 레벨 설정"""
        msg = Float32()
        msg.data = level
        self._battery_pub.publish(msg)
        self.get_logger().info(f'[SIM] 배터리 → {level:.1f}%')

    # ------------------------------------------------------------------ #
    # 시나리오                                                               #
    # ------------------------------------------------------------------ #

    def _start_scenarios(self) -> None:
        """시나리오 선택 및 실행 시작 — 반복 타이머이므로 즉시 취소하여 1회만 실행"""
        self._init_timer.cancel()
        self._init_timer = None

        scenario = self.get_parameter('scenario').value
        step_delay = self.get_parameter('step_delay').value
        self._scenario_mode = scenario

        if scenario == 'follow':
            steps = self._scenario_follow()
        elif scenario == 'delivery':
            steps = self._scenario_delivery()
        elif scenario == 'collect':
            steps = self._scenario_collect()
        elif scenario == 'guide':
            steps = self._scenario_guide()
        elif scenario == 'battery':
            steps = self._scenario_standby_to_charge()
        elif scenario == 'collect_gz':
            steps = self._scenario_collect_gz()
        elif scenario == 'docking':
            steps = self._scenario_docking()
        else:
            # all: 순서대로 실행
            steps = (
                self._scenario_battery_critical()
                + self._scenario_follow()
                + self._scenario_delivery()
                + self._scenario_collect()
                + self._scenario_guide()
            )

        self._scenario_steps = steps
        self._step_idx = 0
        self.get_logger().info(
            f'시나리오 [{scenario}] 시작. 총 {len(steps)}단계, '
            f'단계 간격 {step_delay}초.'
        )
        self._step_timer = self.create_timer(step_delay, self._run_next_step)

    def _run_next_step(self) -> None:
        """다음 시나리오 단계 실행"""
        if self._step_idx >= len(self._scenario_steps):
            self._step_timer.cancel()
            self.get_logger().info('=== 모든 시나리오 완료 ===')
            return

        step = self._scenario_steps[self._step_idx]
        self._step_idx += 1

        # 단계는 (설명, 콜백) 튜플
        desc, action = step
        self.get_logger().info(f'--- 단계 {self._step_idx}: {desc} ---')
        action()

    # ------------------------------------------------------------------ #
    # 시나리오 정의                                                          #
    # ------------------------------------------------------------------ #

    def _scenario_battery_critical(self):
        """배터리 부족 → 충전 → 복귀 시나리오 (all 모드용)"""
        return [
            ('배터리를 10%로 설정 (CHARGING_NO_TASK 진입)',
             lambda: self._set_battery(10.0)),
            ('배터리를 65%로 설정 (CHARGING_WITH_TASK 진입)',
             lambda: self._set_battery(65.0)),
            ('배터리를 85%로 설정 (MOVE_TO_STANDBY 진입)',
             lambda: self._set_battery(85.0)),
        ]

    def _scenario_standby_to_charge(self):
        """
        STANDBY 대기 → 배터리 부족 → 충전소 이동 → 충전 → STANDBY 복귀

        흐름:
          배터리 85% → CHARGING → MOVE_TO_STANDBY → STANDBY
          배터리 10% → MOVE_TO_CHARGING → (로봇 이동) → ArrivedAtCharging
                    → CHARGING → CHARGING_NO_TASK
          배터리 65% → CHARGING_WITH_TASK
          배터리 85% → MOVE_TO_STANDBY → (로봇 이동) → ArrivedAtStandby → STANDBY

        주의: step_delay는 로봇이 실제로 이동하는 시간보다 충분히 크게 설정해야 한다.
              Gazebo + Nav2 환경에서는 --ros-args -p step_delay:=20.0 권장.
        """
        return [
            ('배터리 85% 설정 → STANDBY로 이동 시작',
             lambda: self._set_battery(85.0)),
            # step_delay 동안 로봇이 대기장소(standby_pos)로 이동
            ('배터리 10%로 낮춤 → MOVE_TO_CHARGING 진입 (충전소로 이동 시작)',
             lambda: self._set_battery(10.0)),
            # step_delay 동안 로봇이 충전소(charging_pos)로 이동
            # top_function_node가 ArrivedAtCharging 이벤트를 publish하면
            # FSM이 자동으로 CHARGING → CHARGING_NO_TASK로 전이
            ('배터리 65%로 충전 중 → CHARGING_WITH_TASK 진입',
             lambda: self._set_battery(65.0)),
            ('배터리 85%로 충전 완료 → MOVE_TO_STANDBY 진입 (대기장소로 복귀)',
             lambda: self._set_battery(85.0)),
            # step_delay 동안 로봇이 대기장소로 복귀
            # top_function_node가 ArrivedAtStandby 이벤트를 publish하면 STANDBY로 전이
        ]

    def _scenario_follow(self):
        """동행 시나리오: FollowRequest → FOLLOWING → FollowEnd"""
        return [
            ('배터리 85% 설정 (STANDBY 상태 유지)',
             lambda: self._set_battery(85.0)),
            ('[FOLLOW] FollowRequest 전송',
             lambda: self._send_command(
                 'FollowRequest', 'follow-001',
                 1.0, 2.0, 0.0
             )),
            # 로봇이 자동으로 MOVE_TO_REQUESTER → VERIFY_REQUESTER (nav_delay 후)
            ('[FOLLOW] FollowStart 전송 (요청자 확인 완료)',
             lambda: self._send_command('FollowStart', 'follow-001')),
            # 로봇이 FOLLOWING 상태 유지 (1분 타이머가 있지만 테스트에서는 짧게)
            ('[FOLLOW] FollowEnd 전송 (동행 종료)',
             lambda: self._send_command('FollowEnd', 'follow-001')),
        ]

    def _scenario_delivery(self):
        """운반 시나리오: MoveToKitchen → StartDelivery(2회) → DeliveryEnd"""
        return [
            ('[DELIVERY] MoveToKitchen 전송',
             lambda: self._send_command(
                 'MoveToKitchen', 'delivery-001',
                 5.0, 0.0, 0.0
             )),
            # 로봇이 주방으로 이동 후 LOADING 상태 진입
            ('[DELIVERY] StartDelivery 전송 (첫 번째 테이블, 좌표 3,4)',
             lambda: self._send_command(
                 'StartDelivery', 'delivery-001',
                 3.0, 4.0, 0.0
             )),
            # 로봇이 목적지 이동 후 UNLOAD_MENU 상태 진입
            ('[DELIVERY] StartDelivery 전송 (두 번째 테이블, 좌표 6,4)',
             lambda: self._send_command(
                 'StartDelivery', 'delivery-001',
                 6.0, 4.0, 0.0
             )),
            ('[DELIVERY] DeliveryEnd 전송 (배송 완료)',
             lambda: self._send_command('DeliveryEnd', 'delivery-001')),
        ]

    def _scenario_collect(self):
        """수거 시나리오: CollectRequest → StartCollection → CollectionDone → CollectionEnd"""
        return [
            ('[COLLECT] CollectRequest 전송',
             lambda: self._send_command(
                 'CollectRequest', 'collect-001',
                 2.0, 3.0, 0.0
             )),
            # 로봇이 수거 위치로 이동 후 VERIFY_COLLECT 상태 진입
            ('[COLLECT] StartCollection 전송 (수거 시작)',
             lambda: self._send_command('StartCollection', 'collect-001')),
            # 로봇이 COLLECTING 상태 유지
            ('[COLLECT] CollectionDone 전송 (수거 완료)',
             lambda: self._send_command('CollectionDone', 'collect-001')),
            # 배터리가 충분하고 횟수 < 5이므로 COLLECT_END로 전이
            # CHARGING 복귀 후 다시 STANDBY로
        ]

    def _scenario_collect_gz(self):
        """
        Gazebo 이벤트 기반 수거 시나리오

        흐름:
          배터리 85% → STANDBY 진입 대기 (step_delay 동안 로봇이 standby_pos로 이동)
          CollectRequest (1.36, -0.63, 0.0) → 로봇이 수거 위치로 이동
          [이벤트] ArrivedAtRequester 수신 시 → StartCollection 자동 발행
          collect_done_delay 초 후 → CollectionDone 자동 발행
          FSM: COLLECT_END → CHARGING → MOVE_TO_STANDBY → 로봇이 (0, 0, 0)으로 복귀

        파라미터:
          step_delay         : 배터리 설정 후 STANDBY 진입까지 대기 시간 (Nav2 이동 시간보다 크게)
          collect_done_delay : 수거 위치 도착 후 CollectionDone 발행까지 대기 시간 (기본 3.0초)

        실행 예:
          ros2 run rostaurant_state_machine test_state_machine.py \\
            --ros-args -p scenario:=collect_gz -p step_delay:=20.0 -p collect_done_delay:=3.0
        """
        return [
            ('배터리 85% 설정 → STANDBY 진입 대기',
             lambda: self._set_battery(85.0)),
            # step_delay 동안 로봇이 standby_pos로 이동하여 STANDBY 상태 진입
            ('[COLLECT_GZ] CollectRequest 전송 → 수거 위치 (1.36, -0.63, 0.0)으로 이동',
             lambda: self._send_command(
                 'CollectRequest', 'collect-gz-001',
                 1.36, 0.032, 0.0
             )),
            # 이후는 이벤트 기반으로 처리:
            #   ArrivedAtRequester 수신 → StartCollection 발행
            #   collect_done_delay 초 후 → CollectionDone 발행
            #   FSM이 COLLECT_END → CHARGING → MOVE_TO_STANDBY 전이
            #   top_function_node가 standby_pos(0, 0, 0)으로 로봇 복귀
        ]

    def _scenario_collect_with_dishwash(self):
        """수거 5회 후 설거지장 이동 시나리오"""
        steps = []
        for i in range(5):
            session = f'collect-{i+1:03d}'
            steps += [
                (f'[COLLECT {i+1}/5] CollectRequest 전송',
                 lambda s=session: self._send_command(
                     'CollectRequest', s, 2.0, 3.0, 0.0
                 )),
                (f'[COLLECT {i+1}/5] StartCollection 전송',
                 lambda s=session: self._send_command('StartCollection', s)),
                (f'[COLLECT {i+1}/5] CollectionDone 전송',
                 lambda s=session: self._send_command('CollectionDone', s)),
            ]
        # 5회 후 설거지장으로 이동
        steps += [
            ('[COLLECT] CollectionEnd 전송 (설거지 완료)',
             lambda: self._send_command('CollectionEnd', 'collect-005')),
        ]
        return steps

    def _scenario_guide(self):
        """안내 시나리오: MoveToRequester → GuideStart(2회) → GuideEnd"""
        return [
            ('[GUIDE] MoveToRequester 전송',
             lambda: self._send_command(
                 'MoveToRequester', 'guide-001',
                 0.0, 0.0, 0.0
             )),
            # 로봇이 요청자 위치로 이동 후 VERIFY_AND_SELECT 상태 진입
            ('[GUIDE] GuideStart 전송 (첫 번째 목적지: 화장실)',
             lambda: self._send_command(
                 'GuideStart', 'guide-001',
                 10.0, 2.0, 0.0
             )),
            # 로봇이 목적지로 이동 후 VERIFY_ARRIVAL 상태 진입
            ('[GUIDE] GuideStart 전송 (두 번째 목적지: 출구)',
             lambda: self._send_command(
                 'GuideStart', 'guide-001',
                 15.0, 0.0, 0.0
             )),
            ('[GUIDE] GuideEnd 전송 (안내 완료)',
             lambda: self._send_command('GuideEnd', 'guide-001')),
        ]

    def _scenario_retry(self):
        """재시도 시나리오 예시: RetryFollowRequest 사용"""
        return [
            ('[RETRY] FollowRequest 전송',
             lambda: self._send_command(
                 'FollowRequest', 'retry-001',
                 3.0, 3.0, 0.0
             )),
            ('[RETRY] RetryFollowRequest 전송 (요청자가 자리 이동)',
             lambda: self._send_command(
                 'RetryFollowRequest', 'retry-001',
                 4.0, 3.0, 0.0
             )),
            ('[RETRY] FollowStart 전송',
             lambda: self._send_command('FollowStart', 'retry-001')),
            ('[RETRY] FollowEnd 전송',
             lambda: self._send_command('FollowEnd', 'retry-001')),
        ]

    def _scenario_docking(self):
        """
        충전소 이동 → pinky_docking 연동 시나리오

        흐름:
          배터리 85% → STANDBY 진입 대기 (step_delay 동안 로봇이 standby_pos로 이동)
          배터리 10% → MOVE_TO_CHARGING 진입 (충전소로 이동 시작)
          nav_delay 초 후 → top_function_node._on_arrived_charging() 호출
            - ArrivedAtCharging 이벤트 발행 → FSM: CHARGING 진입
            - /docking/cmd → "start" 발행 → pinky_docking 도킹 시작
          /docking/status 변화: IDLE → RUNNING → DOCKED

        확인 포인트:
          [ROBOT STATE]   → MOVE_TO_CHARGING
          [ROBOT EVENT]   ArrivedAtCharging
          [DOCKING CMD]   → start          ← top_function_node가 발행
          [DOCKING STATUS]→ RUNNING        ← docking_node 상태
          [DOCKING STATUS]→ DOCKED         ← 도킹 완료
          [ROBOT STATE]   → CHARGING_NO_TASK (배터리 10% 이므로)

        실행 예:
          ros2 run rostaurant_state_machine test_state_machine.py \\
            --ros-args -p scenario:=docking -p step_delay:=8.0
        """
        return [
            ('배터리 85% 설정 → STANDBY 진입 대기',
             lambda: self._set_battery(85.0)),
            # step_delay 동안 로봇이 standby_pos로 이동하여 STANDBY 상태 진입
            ('배터리 10%로 낮춤 → MOVE_TO_CHARGING 진입 → 충전소 이동 + 도킹 시작',
             lambda: self._set_battery(10.0)),
            # nav_delay 초 후 top_function_node가 /docking/cmd → "start" 발행
            # docking_node: IDLE → RUNNING → DOCKED
        ]


def main(args=None):
    rclpy.init(args=args)
    node = HQSimulatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('HQ 시뮬레이터 종료')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
