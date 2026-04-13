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
  ros2 run rost_state_machine test_state_machine.py
  또는
  ros2 run rost_state_machine test_state_machine.py --ros-args -p scenario:=follow

파라미터:
  scenario : 실행할 시나리오 (follow | delivery | collect | guide | all)
             기본값 = all
  step_delay : 명령 사이 대기 시간 (초), 기본값 = 3.0
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String
from geometry_msgs.msg import PoseStamped

from rost_state_machine.msg import RobotCommand, RobotEvent


def _make_pose(x: float = 0.0, y: float = 0.0) -> PoseStamped:
    """간단한 PoseStamped 생성 헬퍼"""
    pose = PoseStamped()
    pose.header.frame_id = 'map'
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.orientation.w = 1.0
    return pose


class HQSimulatorNode(Node):
    """HQ 시뮬레이터 노드"""

    def __init__(self):
        super().__init__('hq_simulator_node')

        # 파라미터
        self.declare_parameter('scenario', 'all')
        self.declare_parameter('step_delay', 3.0)

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

        # 시나리오 실행 상태
        self._scenario_steps = []
        self._step_idx = 0
        self._step_timer = None

        # 1초 후 시나리오 시작 (노드 초기화 대기)
        self.create_timer(1.0, self._start_scenarios)
        self.get_logger().info('HQ 시뮬레이터 시작. 1초 후 시나리오를 실행합니다.')

    # ------------------------------------------------------------------ #
    # 구독 콜백                                                             #
    # ------------------------------------------------------------------ #

    def _on_robot_state(self, msg: String) -> None:
        self.get_logger().info(f'[ROBOT STATE] → {msg.data}')

    def _on_robot_event(self, msg: RobotEvent) -> None:
        self.get_logger().info(
            f'[ROBOT EVENT] {msg.event} (세션: {msg.session_id})'
        )

    # ------------------------------------------------------------------ #
    # 퍼블리시 헬퍼                                                          #
    # ------------------------------------------------------------------ #

    def _send_command(self, command: str, session_id: str = 'sim-001',
                      target_pose: PoseStamped = None, count: int = 0) -> None:
        """HQ → ROBOT 명령 전송"""
        msg = RobotCommand()
        msg.command = command
        msg.session_id = session_id
        msg.count = count
        if target_pose:
            msg.target_pose = target_pose
        else:
            msg.target_pose = _make_pose()
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
        """시나리오 선택 및 실행 시작"""
        scenario = self.get_parameter('scenario').value
        step_delay = self.get_parameter('step_delay').value

        if scenario == 'follow':
            steps = self._scenario_follow()
        elif scenario == 'delivery':
            steps = self._scenario_delivery()
        elif scenario == 'collect':
            steps = self._scenario_collect()
        elif scenario == 'guide':
            steps = self._scenario_guide()
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
        """배터리 부족 → 충전 → 복귀 시나리오"""
        return [
            ('배터리를 10%로 설정 (CHARGING_NO_TASK 진입)',
             lambda: self._set_battery(10.0)),
            ('배터리를 65%로 설정 (CHARGING_WITH_TASK 진입)',
             lambda: self._set_battery(65.0)),
            ('배터리를 85%로 설정 (MOVE_TO_STANDBY 진입)',
             lambda: self._set_battery(85.0)),
        ]

    def _scenario_follow(self):
        """동행 시나리오: FollowRequest → FOLLOWING → FollowEnd"""
        return [
            ('배터리 85% 설정 (STANDBY 상태 유지)',
             lambda: self._set_battery(85.0)),
            ('[FOLLOW] FollowRequest 전송',
             lambda: self._send_command(
                 'FollowRequest', 'follow-001',
                 _make_pose(1.0, 2.0)
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
                 _make_pose(5.0, 0.0)
             )),
            # 로봇이 주방으로 이동 후 LOADING 상태 진입
            ('[DELIVERY] StartDelivery 전송 (첫 번째 테이블, 좌표 3,4)',
             lambda: self._send_command(
                 'StartDelivery', 'delivery-001',
                 _make_pose(3.0, 4.0)
             )),
            # 로봇이 목적지 이동 후 UNLOAD_MENU 상태 진입
            ('[DELIVERY] StartDelivery 전송 (두 번째 테이블, 좌표 6,4)',
             lambda: self._send_command(
                 'StartDelivery', 'delivery-001',
                 _make_pose(6.0, 4.0)
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
                 _make_pose(2.0, 3.0)
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

    def _scenario_collect_with_dishwash(self):
        """수거 5회 후 설거지장 이동 시나리오"""
        steps = []
        for i in range(5):
            session = f'collect-{i+1:03d}'
            steps += [
                (f'[COLLECT {i+1}/5] CollectRequest 전송',
                 lambda s=session: self._send_command(
                     'CollectRequest', s, _make_pose(2.0, 3.0)
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
                 _make_pose(0.0, 0.0)
             )),
            # 로봇이 요청자 위치로 이동 후 VERIFY_AND_SELECT 상태 진입
            ('[GUIDE] GuideStart 전송 (첫 번째 목적지: 화장실)',
             lambda: self._send_command(
                 'GuideStart', 'guide-001',
                 _make_pose(10.0, 2.0)
             )),
            # 로봇이 목적지로 이동 후 VERIFY_ARRIVAL 상태 진입
            ('[GUIDE] GuideStart 전송 (두 번째 목적지: 출구)',
             lambda: self._send_command(
                 'GuideStart', 'guide-001',
                 _make_pose(15.0, 0.0)
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
                 _make_pose(3.0, 3.0)
             )),
            ('[RETRY] RetryFollowRequest 전송 (요청자가 자리 이동)',
             lambda: self._send_command(
                 'RetryFollowRequest', 'retry-001',
                 _make_pose(4.0, 3.0)
             )),
            ('[RETRY] FollowStart 전송',
             lambda: self._send_command('FollowStart', 'retry-001')),
            ('[RETRY] FollowEnd 전송',
             lambda: self._send_command('FollowEnd', 'retry-001')),
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
