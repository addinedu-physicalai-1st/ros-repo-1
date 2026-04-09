#!/usr/bin/env python3
"""
task_executor_node.py
─────────────────────
guide_command_resolved 를 구독해 시나리오별로 흐름을 제어.

시나리오:
  CMD_KIOSK_TO_TABLE  (1): 키오스크 결제 완료 → 테이블 안내
  CMD_TABLE_TO_TOILET (2): 테이블 요청 → 화장실 안내
  CMD_TABLE_TO_DISPLAY(3): 테이블 요청 → 메뉴 진열대 안내
  CMD_RETURN_TO_DOCK  (4): 안내 완료 후 대기장소 복귀 (관제서버가 지시)

각 시나리오는 동일한 waypoints 실행 흐름을 사용하되,
시나리오 타입에 따라 로그 / 알림 동작을 다르게 처리.
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from pinky_guide.msg import GuideCommand, GuideResult


SCENARIO_LABEL = {
    GuideCommand.CMD_KIOSK_TO_TABLE:   '키오스크→테이블 안내',
    GuideCommand.CMD_TABLE_TO_TOILET:  '테이블→화장실 안내',
    GuideCommand.CMD_TABLE_TO_DISPLAY: '테이블→진열대 안내',
    GuideCommand.CMD_RETURN_TO_DOCK:   '대기장소 복귀',
}


class TaskExecutorNode(Node):
    def __init__(self):
        super().__init__('task_executor_node')

        self.declare_parameter('robot_id', 1)
        self.robot_id = self.get_parameter('robot_id').value

        # Subscribe: location_map 이 해석한 명령
        self.cmd_sub = self.create_subscription(
            GuideCommand, 'guide_command_resolved',
            self._on_command, 10)

        # Subscribe: nav_handler 완료 결과
        self.result_sub = self.create_subscription(
            GuideResult, 'guide_result',
            self._on_result, 10)

        # Publish: nav_handler 에 waypoints JSON 재전달 가능
        # (location_map 이 직접 publish 하므로 여기선 모니터링 역할)
        self._active_cmd: GuideCommand | None = None

        self.get_logger().info(
            f'task_executor_node 시작 — robot_id={self.robot_id}')

    def _on_command(self, msg: GuideCommand):
        """시나리오별 사전 처리 및 로그."""
        label = SCENARIO_LABEL.get(msg.cmd_type, f'알 수 없는 명령({msg.cmd_type})')
        self.get_logger().info(
            f'시나리오 시작: [{label}] → {msg.dest_name}')

        self._active_cmd = msg

        # 시나리오별 추가 처리
        if msg.cmd_type == GuideCommand.CMD_KIOSK_TO_TABLE:
            self._handle_kiosk_to_table(msg)
        elif msg.cmd_type == GuideCommand.CMD_TABLE_TO_TOILET:
            self._handle_table_to_toilet(msg)
        elif msg.cmd_type == GuideCommand.CMD_TABLE_TO_DISPLAY:
            self._handle_table_to_display(msg)
        elif msg.cmd_type == GuideCommand.CMD_RETURN_TO_DOCK:
            self._handle_return_to_dock(msg)
        else:
            self.get_logger().error(f'알 수 없는 cmd_type: {msg.cmd_type}')

    # ── 시나리오별 핸들러 ────────────────────────────────
    def _handle_kiosk_to_table(self, msg: GuideCommand):
        """
        키오스크 결제 완료 → 지정 테이블까지 안내.
        nav_handler 는 location_map 이 publish 한 waypoints_ready 를 이미 구독 중.
        여기서는 시나리오 로그와 필요 시 추가 알림만 처리.
        """
        self.get_logger().info(
            f'[키오스크→테이블] 로봇이 {msg.dest_name} 으로 손님을 안내합니다')
        # TODO: 필요 시 로봇 디스플레이 메시지 publish ("저를 따라오세요!")

    def _handle_table_to_toilet(self, msg: GuideCommand):
        """
        테이블에서 화장실 안내 요청.
        로봇이 해당 테이블로 먼저 이동 후 화장실까지 안내.
        → 현재 구현: 화장실 목적지로 직접 이동 (테이블 경유 없이).
          테이블 경유가 필요하면 관제서버에서 2단계 명령으로 처리 요청.
        """
        self.get_logger().info(
            f'[테이블→화장실] 화장실 {msg.dest_name} 안내 시작')

    def _handle_table_to_display(self, msg: GuideCommand):
        """
        테이블에서 메뉴 진열대 안내 요청.
        dest_name 예: display_steak, display_salad
        """
        self.get_logger().info(
            f'[테이블→진열대] {msg.dest_name} 안내 시작')

    def _handle_return_to_dock(self, msg: GuideCommand):
        """
        관제서버가 지정한 대기장소(dock_a or dock_b)로 복귀.
        복귀 대기장소 선택은 관제서버가 결정 — 이 노드는 그냥 이동.
        """
        self.get_logger().info(
            f'[복귀] 대기장소 {msg.dest_name} 으로 복귀')

    # ── 완료 결과 처리 ───────────────────────────────────
    def _on_result(self, msg: GuideResult):
        status_str = {
            GuideResult.STATUS_SUCCESS:   '성공',
            GuideResult.STATUS_FAILED:    '실패',
            GuideResult.STATUS_CANCELLED: '취소',
            GuideResult.STATUS_OBSTACLE:  '장애물 중단',
        }.get(msg.status, f'알 수 없음({msg.status})')

        self.get_logger().info(
            f'시나리오 완료 — {msg.dest_name} [{status_str}] {msg.message}')
        self._active_cmd = None


def main(args=None):
    rclpy.init(args=args)
    node = TaskExecutorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
