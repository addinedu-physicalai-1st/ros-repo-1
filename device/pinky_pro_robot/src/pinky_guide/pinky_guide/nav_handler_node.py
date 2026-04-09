#!/usr/bin/env python3
"""
nav_handler_node.py
───────────────────
waypoints_ready 토픽을 구독하고,
웨이포인트를 순서대로 하나씩 Nav2 NavigateToPose Action 으로 전송.

핵심 동작:
  1. 웨이포인트 리스트 수신
  2. max_speed 를 Nav2 controller_server 파라미터로 동적 설정
  3. waypoints → goal 순서대로 한 지점씩 이동
  4. 각 지점 도달 확인 후 다음 지점으로
  5. 전체 완료 또는 실패 시 guide_result publish
"""

import json
import math
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType
from rcl_interfaces.srv import SetParameters
from std_msgs.msg import String
from pinky_guide.msg import GuideResult, RobotStatus


class NavHandlerNode(Node):
    def __init__(self):
        super().__init__('nav_handler_node')

        self.declare_parameter('robot_id', 1)
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('arrival_tolerance', 0.25)   # m
        self.declare_parameter('default_max_speed', 0.3)    # m/s

        self.robot_id        = self.get_parameter('robot_id').value
        self.map_frame       = self.get_parameter('map_frame').value
        self.arrival_tol     = self.get_parameter('arrival_tolerance').value
        self.default_speed   = self.get_parameter('default_max_speed').value

        self._cb_group = ReentrantCallbackGroup()

        # Nav2 Action 클라이언트
        self._nav_client = ActionClient(
            self, NavigateToPose, 'navigate_to_pose',
            callback_group=self._cb_group)

        # Subscribe: location_map 에서 waypoints JSON 수신
        self.wp_sub = self.create_subscription(
            String, 'waypoints_ready', self._on_waypoints,
            10, callback_group=self._cb_group)

        # Publish: 완료/실패 결과
        self.result_pub = self.create_publisher(GuideResult, 'guide_result', 10)

        # Publish: 로봇 상태
        self.status_pub = self.create_publisher(RobotStatus, 'robot_status', 10)

        self._current_task: dict | None = None
        self._is_running = False

        self.get_logger().info('nav_handler_node 시작')

    # ── 웨이포인트 수신 ─────────────────────────────────
    def _on_waypoints(self, msg: String):
        if self._is_running:
            self.get_logger().warn(
                '이미 이동 중 — 새 명령 무시 (관제서버에서 취소 명령 필요)')
            return

        try:
            task = json.loads(msg.data)
        except json.JSONDecodeError as e:
            self.get_logger().error(f'JSON 파싱 오류: {e}')
            return

        self._current_task = task
        self._is_running   = True
        self.get_logger().info(
            f'이동 시작 — {task["dest_name"]} '
            f'(waypoints={len(task["waypoints"])}개, '
            f'max_speed={task["max_speed"]} m/s)')

        # 별도 스레드에서 순차 실행 (spin 블로킹 방지)
        import threading
        t = threading.Thread(target=self._execute_task, args=(task,), daemon=True)
        t.start()

    # ── 순차 이동 실행 ──────────────────────────────────
    def _execute_task(self, task: dict):
        robot_id  = task['robot_id']
        cmd_type  = task['cmd_type']
        dest_name = task['dest_name']
        max_speed = task.get('max_speed', self.default_speed)
        waypoints = task.get('waypoints', [])
        goal_pt   = task['goal']

        # Nav2 최대속도 동적 설정
        self._set_nav2_speed(max_speed)

        # 웨이포인트 순서대로 이동
        all_points = waypoints + [
            {**goal_pt, 'label': f'{dest_name} 도착'}
        ]
        total = len(all_points)

        for idx, point in enumerate(all_points):
            label = point.get('label', f'waypoint_{idx}')
            self.get_logger().info(
                f'[{idx+1}/{total}] → {label} '
                f'({point["x"]:.2f}, {point["y"]:.2f})')

            # 상태 퍼블리시
            self._publish_status(robot_id, RobotStatus.STATE_MOVING, dest_name)

            success = self._navigate_to(point, label)
            if not success:
                self.get_logger().error(f'이동 실패 — {label}')
                self._publish_result(robot_id, cmd_type, dest_name,
                                     GuideResult.STATUS_FAILED,
                                     f'{label} 이동 실패')
                self._is_running = False
                return

        # 모든 웨이포인트 완료
        self.get_logger().info(f'안내 완료 — {dest_name}')
        self._publish_status(robot_id, RobotStatus.STATE_ARRIVED, dest_name)
        self._publish_result(robot_id, cmd_type, dest_name,
                             GuideResult.STATUS_SUCCESS, '안내 완료')
        self._is_running = False
        self._current_task = None

    # ── 단일 지점 이동 ──────────────────────────────────
    def _navigate_to(self, point: dict, label: str) -> bool:
        """Nav2 NavigateToPose 로 단일 지점 이동. 완료 시 True 반환."""
        if not self._nav_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('Nav2 액션 서버 없음')
            return False

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = self._make_pose(
            point['x'], point['y'], point.get('yaw', 0.0))

        # 목표 전송
        send_future = self._nav_client.send_goal_async(
            goal_msg,
            feedback_callback=lambda fb: self._on_feedback(fb, label))
        rclpy.spin_until_future_complete(self, send_future)

        goal_handle = send_future.result()
        if not goal_handle or not goal_handle.accepted:
            self.get_logger().error(f'목표 거부됨 — {label}')
            return False

        # 결과 대기
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future)

        result = result_future.result()
        if result is None:
            return False

        status = result.status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f'도달 완료 — {label}')
            return True
        else:
            self.get_logger().warn(f'이동 중단 status={status} — {label}')
            return False

    def _on_feedback(self, feedback_msg, label: str):
        fb = feedback_msg.feedback
        # 필요 시 남은 거리 로그
        # self.get_logger().debug(f'{label} — 남은거리 {fb.distance_remaining:.2f}m')
        pass

    # ── Nav2 속도 동적 설정 ─────────────────────────────
    def _set_nav2_speed(self, max_speed: float):
        """
        controller_server 의 max_vel_x 파라미터를 동적으로 변경.
        관제서버와 합의된 max_speed 값을 적용해 천천히 이동.
        """
        client = self.create_client(
            SetParameters, '/controller_server/set_parameters')
        if not client.wait_for_service(timeout_sec=2.0):
            self.get_logger().warn('controller_server 파라미터 서비스 없음 — 속도 설정 스킵')
            return

        param = Parameter()
        param.name = 'FollowPath.max_vel_x'
        param.value = ParameterValue(
            type=ParameterType.PARAMETER_DOUBLE,
            double_value=float(max_speed))

        req = SetParameters.Request()
        req.parameters = [param]
        future = client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)
        self.get_logger().info(f'Nav2 최대속도 설정 → {max_speed} m/s')

    # ── 헬퍼 ────────────────────────────────────────────
    def _make_pose(self, x: float, y: float, yaw: float) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = self.map_frame
        pose.header.stamp    = self.get_clock().now().to_msg()
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.position.z = 0.0
        # yaw → quaternion
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def _publish_result(self, robot_id, cmd_type, dest_name, status, message):
        msg = GuideResult()
        msg.robot_id  = robot_id
        msg.cmd_type  = cmd_type
        msg.dest_name = dest_name
        msg.status    = status
        msg.message   = message
        self.result_pub.publish(msg)

    def _publish_status(self, robot_id, state, current_task):
        msg = RobotStatus()
        msg.robot_id     = robot_id
        msg.state        = state
        msg.current_task = current_task
        msg.battery      = 100.0  # 실제 배터리 토픽 연결 시 교체
        self.status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = NavHandlerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
