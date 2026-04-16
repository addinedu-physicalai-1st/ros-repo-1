"""
pinky_parking.launch.py

Nav2 + SLAM이 이미 실행 중인 상태에서 주차 노드만 추가로 실행.

사용법:
  # 기본 실행
  ros2 launch pinky_docking pinky_parking.launch.py

  # 마커 ID·거리·캘리브레이션 지정
  ros2 launch pinky_docking pinky_parking.launch.py \\
      target_id:=1 \\
      parking_dist_cm:=25.0 \\
      calib_path:=/home/pinky/camera_calibration.npz

사전 조건:
  ros2 launch pinky_bringup bringup_robot.launch.xml
  ros2 launch pinky_navigation bringup_launch.xml map:=<map>
"""
import os
from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

pkg_dir = get_package_share_directory('pinky_docking')


def generate_launch_description():

    args = [
        DeclareLaunchArgument('target_id',          default_value='0',
                              description='추종할 ArUco 마커 ID'),
        DeclareLaunchArgument('parking_dist_cm',    default_value='15.0',
                              description='최종 정차 거리 (cm)'),
        DeclareLaunchArgument('nav_goal_dist_m',    default_value='0.5',
                              description='Nav2 목표: 마커 앞 거리 (m)'),
        DeclareLaunchArgument('max_speed',          default_value='35.0',
                              description='정밀 도킹 최대 속도 (0~100)'),
        DeclareLaunchArgument('kp_rho',             default_value='1.2',
                              description='전진 P 게인'),
        DeclareLaunchArgument('kp_theta',           default_value='50.0',
                              description='회전 P 게인'),
        DeclareLaunchArgument('theta_thresh_deg',   default_value='5.0',
                              description='전진 시작 각도 임계값 (deg)'),
        DeclareLaunchArgument('marker_size_m',      default_value='0.05',
                              description='ArUco 마커 실물 크기 (m)'),
        DeclareLaunchArgument('calib_path',
                              default_value=os.path.join(
                                  pkg_dir, 'launch', 'camera_calibration.npz'),
                              description='카메라 캘리브레이션 파일 경로 (.npz)'),
        DeclareLaunchArgument('camera_frame',       default_value='front_camera_link',
                              description='카메라 TF 프레임 이름'),
        DeclareLaunchArgument('robot_base_frame',   default_value='base_link',
                              description='로봇 베이스 TF 프레임 이름'),
        DeclareLaunchArgument('scan_angular_vel',  default_value='0.2',
                              description='마커 탐색 회전 속도'),
        DeclareLaunchArgument('nav2_timeout_sec',   default_value='30.0',
                              description='Nav2 타임아웃 (초)'),
        DeclareLaunchArgument('camera_width',       default_value='640'),
        DeclareLaunchArgument('camera_height',      default_value='480'),
        DeclareLaunchArgument('cam_tilt_deg',       default_value='0.0',
                              description='카메라 틸트 각도 (deg)'),
    ]

    parking_node = Node(
        package='pinky_docking',
        executable='parking_node',
        output='screen',
        parameters=[{
            'target_id':         LaunchConfiguration('target_id'),
            'parking_dist_cm':   LaunchConfiguration('parking_dist_cm'),
            'nav_goal_dist_m':   LaunchConfiguration('nav_goal_dist_m'),
            'max_speed':         LaunchConfiguration('max_speed'),
            'kp_rho':            LaunchConfiguration('kp_rho'),
            'kp_theta':          LaunchConfiguration('kp_theta'),
            'theta_thresh_deg':  LaunchConfiguration('theta_thresh_deg'),
            'marker_size_m':     LaunchConfiguration('marker_size_m'),
            'calib_path':        LaunchConfiguration('calib_path'),
            'camera_frame':      LaunchConfiguration('camera_frame'),
            'robot_base_frame':  LaunchConfiguration('robot_base_frame'),
            'scan_angular_vel': LaunchConfiguration('scan_angular_vel'),
            'nav2_timeout_sec':  LaunchConfiguration('nav2_timeout_sec'),
            'camera_width':      LaunchConfiguration('camera_width'),
            'camera_height':     LaunchConfiguration('camera_height'),
            'cam_tilt_deg':      LaunchConfiguration('cam_tilt_deg'),
        }],
    )

    return LaunchDescription(args + [parking_node])