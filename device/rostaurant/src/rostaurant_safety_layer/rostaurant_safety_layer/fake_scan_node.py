#!/usr/bin/env python3

# Copyright 2026 PinkLab
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Fake Scan Node — 테스트용 LiDAR 스캔 퍼블리셔.

전면 카메라 각도 구간만 0.1 m로 설정하고, 나머지는 range_max(10 m)로
채운 360° LaserScan 을 지정 주기로 퍼블리시합니다.

child_detection_node 의 camera-LiDAR 융합 로직을 테스트할 때 사용합니다.

ROS Parameters
--------------
  front_half_fov_deg  float  30.0  deg  - 전면 0.1 m 구간의 반폭 (±)
  publish_hz          float  10.0  Hz   - 퍼블리시 주기
  fake_range          float  0.1   m    - 전면 구간에 채울 거리 값
  background_range    float  10.0  m    - 나머지 구간 거리 값
  angle_resolution_deg float  0.5  deg  - 스캔 각도 해상도
"""

import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


class FakeScanNode(Node):
    """전면 각도만 0.1 m 로 채운 가짜 LaserScan 을 퍼블리시하는 테스트 노드."""

    def __init__(self):
        super().__init__('fake_scan_node')

        self.declare_parameter('front_half_fov_deg',   30.0)
        self.declare_parameter('publish_hz',           10.0)
        self.declare_parameter('fake_range',            0.1)
        self.declare_parameter('background_range',     10.0)
        self.declare_parameter('angle_resolution_deg',  0.5)

        self._front_half = math.radians(
            self.get_parameter('front_half_fov_deg').value)
        hz                = self.get_parameter('publish_hz').value
        self._fake_range  = self.get_parameter('fake_range').value
        self._bg_range    = self.get_parameter('background_range').value
        res_deg           = self.get_parameter('angle_resolution_deg').value
        self._resolution  = math.radians(res_deg)

        self._pub = self.create_publisher(LaserScan, '/scan', 10)
        self.create_timer(1.0 / hz, self._publish)

        self.get_logger().info('FakeScanNode started.')
        self.get_logger().info(
            f'  front ±{math.degrees(self._front_half):.1f}° → {self._fake_range} m')
        self.get_logger().info(
            f'  background → {self._bg_range} m  |  resolution {res_deg}°  |  {hz} Hz')

    def _publish(self):
        now = self.get_clock().now().to_msg()

        angle_min = -math.pi
        angle_max =  math.pi
        num_ranges = int((angle_max - angle_min) / self._resolution) + 1

        ranges = []
        for i in range(num_ranges):
            angle = angle_min + i * self._resolution
            # 전면 ± front_half_fov_deg 구간은 fake_range, 나머지는 background_range
            if -self._front_half <= angle <= self._front_half:
                ranges.append(self._fake_range)
            else:
                ranges.append(self._bg_range)

        msg = LaserScan()
        msg.header.stamp    = now
        msg.header.frame_id = 'laser'
        msg.angle_min       = angle_min
        msg.angle_max       = angle_max
        msg.angle_increment = self._resolution
        msg.time_increment  = 0.0
        msg.scan_time       = 1.0 / 10.0
        msg.range_min       = 0.05
        msg.range_max       = self._bg_range
        msg.ranges          = ranges
        msg.intensities     = []

        self._pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = FakeScanNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
