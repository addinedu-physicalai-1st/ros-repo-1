"""
navigation_client.py

Nav2 NavigateToPose Action Client 래퍼.

use_nav2=True  : nav2_msgs/action/NavigateToPose 액션으로 실제 내비게이션 수행
use_nav2=False : simulated_nav_time 초 후 자동 도달 이벤트를 발행하는 시뮬레이션 모드

사용 예:
    nav = NavigationClient(node, use_nav2=False, simulated_nav_time=3.0)
    nav.send_goal(pose, on_arrived=my_callback)
    nav.cancel_goal()
    nav.is_navigating()
"""

from typing import Callable, Optional

from geometry_msgs.msg import PoseStamped


class NavigationClient:
    """Nav2 내비게이션 클라이언트 래퍼"""

    def __init__(
        self,
        node,
        use_nav2: bool = False,
        simulated_nav_time: float = 3.0,
    ):
        """
        :param node: rclpy.node.Node 인스턴스
        :param use_nav2: True면 Nav2 ActionClient 사용, False면 시뮬레이션 모드
        :param simulated_nav_time: 시뮬레이션 모드에서 도달까지 걸리는 시간 (초)
        """
        self._node = node
        self._use_nav2 = use_nav2
        self._sim_time = simulated_nav_time

        self._is_navigating: bool = False
        self._current_cb: Optional[Callable] = None
        self._sim_timer = None

        # Nav2 관련 (use_nav2=True 시 초기화)
        self._action_client = None
        self._goal_handle = None

        if use_nav2:
            self._init_nav2_client()

    # ------------------------------------------------------------------ #
    # 공개 인터페이스                                                        #
    # ------------------------------------------------------------------ #

    def send_goal(self, pose: PoseStamped, on_arrived: Callable = None) -> None:
        """
        내비게이션 목표를 전송한다.
        이미 이동 중이면 이전 목표를 취소하고 새 목표로 전환한다.

        :param pose: 목표 위치 (geometry_msgs/PoseStamped)
        :param on_arrived: 목표 도달 시 호출할 콜백
        """
        # 이전 이동 취소
        self.cancel_goal()

        self._current_cb = on_arrived
        self._is_navigating = True

        self._node.get_logger().info(
            f'[NavClient] 내비게이션 목표 전송 → '
            f'({pose.pose.position.x:.2f}, {pose.pose.position.y:.2f}) '
            f'[{"Nav2" if self._use_nav2 else "시뮬"}]'
        )

        if self._use_nav2:
            self._send_nav2_goal(pose)
        else:
            # 시뮬레이션: simulated_nav_time 초 후 도달 콜백 호출
            self._sim_timer = self._node.create_timer(
                self._sim_time,
                self._on_sim_done
            )

    def cancel_goal(self) -> None:
        """진행 중인 내비게이션 목표를 취소한다."""
        # 시뮬레이션 타이머 취소
        if self._sim_timer is not None:
            self._sim_timer.cancel()
            self._sim_timer = None

        # Nav2 목표 취소
        if self._goal_handle is not None:
            try:
                self._goal_handle.cancel_goal_async()
            except Exception:
                pass
            self._goal_handle = None

        self._is_navigating = False
        self._current_cb = None

    def is_navigating(self) -> bool:
        """현재 이동 중이면 True"""
        return self._is_navigating

    # ------------------------------------------------------------------ #
    # 시뮬레이션 내부 콜백                                                   #
    # ------------------------------------------------------------------ #

    def _on_sim_done(self) -> None:
        """시뮬레이션 타이머 콜백 — 목표 도달 처리"""
        if self._sim_timer is not None:
            self._sim_timer.cancel()
            self._sim_timer = None

        self._is_navigating = False
        self._node.get_logger().info('[NavClient] 시뮬레이션 내비게이션 완료 (목표 도달)')

        cb = self._current_cb
        self._current_cb = None
        if cb:
            cb()

    # ------------------------------------------------------------------ #
    # Nav2 연동                                                             #
    # ------------------------------------------------------------------ #

    def _init_nav2_client(self) -> None:
        """Nav2 ActionClient 초기화"""
        try:
            from nav2_msgs.action import NavigateToPose
            from rclpy.action import ActionClient

            self._NavigateToPose = NavigateToPose
            self._action_client = ActionClient(
                self._node, NavigateToPose, 'navigate_to_pose'
            )
            self._node.get_logger().info('[NavClient] Nav2 ActionClient 초기화 완료')
        except ImportError:
            self._node.get_logger().error(
                '[NavClient] nav2_msgs를 import할 수 없음. use_nav2=False로 폴백.'
            )
            self._use_nav2 = False

    def _send_nav2_goal(self, pose: PoseStamped) -> None:
        """Nav2에 목표 전송"""
        if self._action_client is None:
            self._node.get_logger().error('[NavClient] ActionClient가 초기화되지 않았습니다.')
            self._is_navigating = False
            return

        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self._node.get_logger().error('[NavClient] Nav2 서버 응답 없음 (5초 타임아웃)')
            self._is_navigating = False
            return

        goal_msg = self._NavigateToPose.Goal()
        goal_msg.pose = pose

        future = self._action_client.send_goal_async(
            goal_msg,
            feedback_callback=self._on_nav2_feedback
        )
        future.add_done_callback(self._on_nav2_goal_accepted)

    def _on_nav2_goal_accepted(self, future) -> None:
        """Nav2 목표 수락 여부 처리"""
        goal_handle = future.result()
        if not goal_handle.accepted:
            self._node.get_logger().warn('[NavClient] Nav2 목표 거부됨')
            self._is_navigating = False
            return

        self._goal_handle = goal_handle
        self._node.get_logger().info('[NavClient] Nav2 목표 수락됨. 이동 중...')
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_nav2_result)

    def _on_nav2_result(self, future) -> None:
        """Nav2 목표 결과 처리"""
        from action_msgs.msg import GoalStatus

        self._is_navigating = False
        self._goal_handle = None

        result = future.result()
        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self._node.get_logger().info('[NavClient] Nav2 내비게이션 완료 (목표 도달)')
            cb = self._current_cb
            self._current_cb = None
            if cb:
                cb()
        elif result.status == GoalStatus.STATUS_CANCELED:
            # cancel_goal()로 의도적으로 취소한 경우 — 정상 동작이므로 debug 로그만 출력
            self._node.get_logger().debug('[NavClient] Nav2 목표 취소됨 (의도적 취소)')
        else:
            self._node.get_logger().warn(
                f'[NavClient] Nav2 내비게이션 실패 (status={result.status})'
            )

    def _on_nav2_feedback(self, feedback_msg) -> None:
        """Nav2 피드백 처리 (필요 시 확장)"""
        pass
