"""
follow_function_node.py

동행 Sub FSM 기능 노드.

HQ 명령에 반응하여 실제 이동·동행 동작을 수행하고,
완료 시 /robot/event에 이벤트를 퍼블리시한다.

처리 명령 (state=FOLLOW 인 경우에만 반응):
  FollowRequest      → 요청자 위치로 이동, 도달 시 ArrivedAtRequester 퍼블리시
  FollowStart        → 동행 시작 (추종 타이머 시작)
  FollowEnd          → 동행 종료, 이동 중지
  RetryFollowRequest → 새 위치로 재이동, 도달 시 ArrivedAtRequester 퍼블리시

파라미터:
  use_nav2                    : Nav2 사용 여부 (기본 False)
  simulated_nav_time          : 시뮬 이동 시간 (기본 3.0초)
  follow_table_distance_threshold : 테이블 근접 거리 임계값 m (기본 1.5)
  follow_time_limit           : 동행 최대 시간 초 (기본 60.0)
"""

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String

from rost_state_machine.msg import RobotCommand
from rost_function.core.navigation_client import NavigationClient
from rost_function.core.event_publisher import EventPublisher


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
        self.declare_parameter('follow_time_limit', 60.0)

        # ---------------------------------------------------------------- #
        # 내부 상태                                                          #
        # ---------------------------------------------------------------- #
        self._current_state: str = ''
        self._session_id: str = ''
        self._target_pose: PoseStamped = None    # 요청자 위치
        self._is_following: bool = False          # 동행 중 여부
        self._follow_timer = None                 # 동행 시간 제한 타이머

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
            # 동행 태스크 시작 — HQ 명령 대기
            self.get_logger().info('[FollowFunc] FOLLOW 태스크 진입. HQ 명령 대기...')
            self._reset_session()

        elif state not in ('FOLLOW',):
            # 다른 태스크로 전환 시 진행 중인 동작 중지
            if self._nav.is_navigating() or self._is_following:
                self.get_logger().info('[FollowFunc] 태스크 종료. 이동 중지 및 세션 초기화.')
                self._stop_all()

    # ------------------------------------------------------------------ #
    # HQ 명령 처리                                                          #
    # ------------------------------------------------------------------ #

    def _on_command(self, msg: RobotCommand) -> None:
        """HQ 명령 수신 — FOLLOW 상태일 때만 처리"""
        if self._current_state != 'FOLLOW':
            return

        cmd = msg.command
        self._session_id = msg.session_id

        self.get_logger().info(f'[FollowFunc] 명령 수신: {cmd}')

        if cmd == 'FollowRequest':
            # 요청자 위치로 이동
            self._target_pose = msg.target_pose
            self.get_logger().info(
                f'[FollowFunc] FollowRequest — 요청자 위치로 이동: '
                f'({msg.target_pose.pose.position.x:.2f}, '
                f'{msg.target_pose.pose.position.y:.2f})'
            )
            self._nav.send_goal(self._target_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'RetryFollowRequest':
            # 새 위치로 재이동
            self._target_pose = msg.target_pose
            self.get_logger().info(
                f'[FollowFunc] RetryFollowRequest — 새 위치로 재이동: '
                f'({msg.target_pose.pose.position.x:.2f}, '
                f'{msg.target_pose.pose.position.y:.2f})'
            )
            self._nav.send_goal(self._target_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'FollowStart':
            # 동행 시작
            self.get_logger().info('[FollowFunc] FollowStart — 동행 시작.')
            self._start_following()

        elif cmd == 'FollowEnd':
            # 동행 종료
            self.get_logger().info('[FollowFunc] FollowEnd — 동행 종료.')
            self._stop_all()

    # ------------------------------------------------------------------ #
    # 내비게이션 콜백                                                        #
    # ------------------------------------------------------------------ #

    def _on_arrived_requester(self) -> None:
        """요청자 위치 도달 시"""
        self.get_logger().info('[FollowFunc] 요청자 위치 도착!')
        self._event_pub.publish_event('ArrivedAtRequester', self._session_id)

    # ------------------------------------------------------------------ #
    # 동행 동작                                                              #
    # ------------------------------------------------------------------ #

    def _start_following(self) -> None:
        """동행 시작 — 시간 제한 타이머 가동"""
        self._is_following = True
        time_limit = self.get_parameter('follow_time_limit').value
        self.get_logger().info(
            f'[FollowFunc] 동행 중. {time_limit:.0f}초 후 NearTableOr1Min 이벤트 예정.'
        )
        self._stop_follow_timer()
        self._follow_timer = self.create_timer(time_limit, self._on_follow_time_limit)

    def _on_follow_time_limit(self) -> None:
        """동행 시간 제한 도달 시 NearTableOr1Min 이벤트 퍼블리시"""
        self._stop_follow_timer()
        if self._is_following:
            self.get_logger().info('[FollowFunc] 동행 시간 제한 도달 → NearTableOr1Min 이벤트')
            self._event_pub.publish_event('NearTableOr1Min', self._session_id)

    def _stop_follow_timer(self) -> None:
        if self._follow_timer is not None:
            self._follow_timer.cancel()
            self._follow_timer = None

    def _stop_all(self) -> None:
        """모든 동작 중지 및 세션 초기화"""
        self._nav.cancel_goal()
        self._is_following = False
        self._stop_follow_timer()

    def _reset_session(self) -> None:
        """세션 데이터 초기화"""
        self._stop_all()
        self._session_id = ''
        self._target_pose = None


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
