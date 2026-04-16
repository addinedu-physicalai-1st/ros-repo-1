"""
pinky_docking.launch.py

사용법:
  기본 실행 (마커 ID 0, 캘리브레이션 없음)
    ros2 launch pinky_docking pinky_docking.launch.py

  마커 ID와 캘리브레이션 파일 지정
    ros2 launch pinky_docking pinky_docking.launch.py \
        target_id:=1 \
        calib_path:=/home/user/camera_calibration.npz \
        target_dist_cm:=20.0
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    # ── Launch 인수 선언 ─────────────────────────────────────────────
    args = [
        DeclareLaunchArgument(
            'target_id',
            default_value='0',
            description='추종할 ArUco 마커 ID'),
        DeclareLaunchArgument(
            'target_dist_cm',
            default_value='15.0',
            description='도킹 완료 판정 거리 (cm)'),
        DeclareLaunchArgument(
            'max_speed',
            default_value='40.0',
            description='최대 모터 속도 (0~100)'),
        DeclareLaunchArgument(
            'kp_linear',
            default_value='1.5',
            description='선형 P 게인'),
        DeclareLaunchArgument(
            'kp_angular',
            default_value='0.8',
            description='각도 P 게인'),
        DeclareLaunchArgument(
            'dead_zone_x_cm',
            default_value='2.0',
            description='X축 데드존 (cm)'),
        DeclareLaunchArgument(
            'camera_width',
            default_value='640',
            description='카메라 해상도 너비'),
        DeclareLaunchArgument(
            'camera_height',
            default_value='480',
            description='카메라 해상도 높이'),
        DeclareLaunchArgument(
            'marker_size_m',
            default_value='0.05',
            description='ArUco 마커 실물 크기 (m)'),
        DeclareLaunchArgument(
            'calib_path',
            default_value='',
            description='카메라 캘리브레이션 파일 경로 (.npz)'),
    ]

    # ── 노드 정의 ────────────────────────────────────────────────────
    docking_node = Node(
        package='pinky_docking',
        executable='docking_node',
        name='docking_node',
        output='screen',
        parameters=[{
            'target_id':      LaunchConfiguration('target_id'),
            'target_dist_cm': LaunchConfiguration('target_dist_cm'),
            'max_speed':      LaunchConfiguration('max_speed'),
            'kp_linear':      LaunchConfiguration('kp_linear'),
            'kp_angular':     LaunchConfiguration('kp_angular'),
            'dead_zone_x_cm': LaunchConfiguration('dead_zone_x_cm'),
            'camera_width':   LaunchConfiguration('camera_width'),
            'camera_height':  LaunchConfiguration('camera_height'),
            'marker_size_m':  LaunchConfiguration('marker_size_m'),
            'calib_path':     LaunchConfiguration('calib_path'),
        }],
    )

    return LaunchDescription(args + [docking_node])
