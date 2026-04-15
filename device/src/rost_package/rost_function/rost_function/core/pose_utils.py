"""
pose_utils.py

HQ로부터 받은 x, y, theta(yaw)를 Nav2가 사용하는
geometry_msgs/PoseStamped 로 변환하는 유틸리티.

모든 function 노드에서 공유하여 중복 구현을 제거한다.
"""

import math

from geometry_msgs.msg import PoseStamped


def pose_from_xyt(node, x: float, y: float, theta: float) -> PoseStamped:
    """
    x, y, theta(yaw, rad) → PoseStamped 변환.

    자동으로 채우는 필드:
        header.frame_id  = 'map'
        header.stamp     = 현재 노드 시각
        pose.position.z  = 0.0
        pose.orientation = theta를 쿼터니언으로 변환 (z, w 설정)

    Parameters
    ----------
    node   : rclpy.node.Node  현재 노드 (stamp 획득에 사용)
    x      : float            목표 x 좌표 (m)
    y      : float            목표 y 좌표 (m)
    theta  : float            목표 yaw 각도 (rad)
    """
    pose = PoseStamped()
    pose.header.frame_id = 'map'
    pose.header.stamp = node.get_clock().now().to_msg()
    pose.pose.position.x = x
    pose.pose.position.y = y
    pose.pose.position.z = 0.0
    pose.pose.orientation.x = 0.0
    pose.pose.orientation.y = 0.0
    pose.pose.orientation.z = math.sin(theta / 2.0)
    pose.pose.orientation.w = math.cos(theta / 2.0)
    return pose
