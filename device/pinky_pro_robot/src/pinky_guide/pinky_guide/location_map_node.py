#!/usr/bin/env python3
"""
location_map_node.py
────────────────────
locations.yaml 을 로드하고,
dest_id 또는 dest_name 으로 웨이포인트 목록을 제공하는 노드.

topic 방식으로 운용:
  Subscribe: guide_command  (GuideCommand)
  Publish:   guide_command_resolved  (GuideCommand — dest_name 채워진 버전)
  Publish:   waypoints_ready         (WaypointList 대신 JSON string 으로 단순화)
"""

import os
import json
import yaml
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from pinky_guide.msg import GuideCommand
from ament_index_python.packages import get_package_share_directory


class LocationMapNode(Node):
    def __init__(self):
        super().__init__('location_map_node')

        # locations.yaml 로드
        pkg_share = get_package_share_directory('pinky_guide')
        yaml_path = os.path.join(pkg_share, 'config', 'locations.yaml')
        with open(yaml_path, 'r', encoding='utf-8') as f:
            self._locations = yaml.safe_load(f)

        self._id_map: dict = self._locations.get('id_map', {})
        self.get_logger().info(
            f'locations.yaml 로드 완료 — '
            f'{len(self._locations) - 1}개 목적지')  # id_map 제외

        # Subscribe: tcp_bridge 에서 파싱된 원시 명령
        self.sub = self.create_subscription(
            GuideCommand, 'guide_command', self._on_command, 10)

        # Publish: dest_name 과 waypoints JSON 이 채워진 명령
        self.cmd_pub = self.create_publisher(
            GuideCommand, 'guide_command_resolved', 10)

        # Publish: 웨이포인트 목록 (JSON string) → nav_handler
        self.wp_pub = self.create_publisher(
            String, 'waypoints_ready', 10)

    def _on_command(self, msg: GuideCommand):
        # dest_id → dest_name 변환
        dest_name = self._id_map.get(msg.dest_id, '')
        if not dest_name:
            self.get_logger().error(
                f'알 수 없는 dest_id: {msg.dest_id}')
            return

        if dest_name not in self._locations:
            self.get_logger().error(
                f'locations.yaml 에 없는 목적지: {dest_name}')
            return

        entry = self._locations[dest_name]
        msg.dest_name = dest_name

        # 웨이포인트 + goal 을 JSON 으로 직렬화해서 nav_handler 에 전달
        waypoints = entry.get('waypoints', [])
        goal      = entry['goal']
        max_speed = entry.get('max_speed', 0.3)

        payload = {
            'dest_name':  dest_name,
            'cmd_type':   msg.cmd_type,
            'robot_id':   msg.robot_id,
            'max_speed':  max_speed,
            'waypoints':  waypoints,   # 중간 경유지 리스트
            'goal':       goal,        # 최종 목적지
            'description': entry.get('description', ''),
        }

        wp_msg = String()
        wp_msg.data = json.dumps(payload, ensure_ascii=False)

        self.cmd_pub.publish(msg)
        self.wp_pub.publish(wp_msg)

        self.get_logger().info(
            f'목적지 해석 완료 — {dest_name} '
            f'(waypoints={len(waypoints)}개, goal={goal})')

    def lookup(self, dest_name: str) -> dict | None:
        """직접 조회용 헬퍼 (다른 노드에서 import 시 사용)."""
        return self._locations.get(dest_name)


def main(args=None):
    rclpy.init(args=args)
    node = LocationMapNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
