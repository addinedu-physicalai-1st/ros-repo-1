"""
buffet_system.launch.py
───────────────────────
로봇 1대 기준 런치 파일.
여러 대 운용 시 robot_id 와 namespace 를 바꿔서 각 로봇에 배포.

사용법:
  ros2 launch pinky_guide buffet_system.launch.py robot_id:=1 server_host:=192.168.1.100
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    robot_id_arg = DeclareLaunchArgument(
        'robot_id', default_value='1',
        description='이 로봇의 고유 ID (1~5)')
    server_host_arg = DeclareLaunchArgument(
        'server_host', default_value='192.168.1.100',
        description='관제서버 IP 주소')
    server_port_arg = DeclareLaunchArgument(
        'server_port', default_value='9000',
        description='관제서버 TCP 포트')

    robot_id    = LaunchConfiguration('robot_id')
    server_host = LaunchConfiguration('server_host')
    server_port = LaunchConfiguration('server_port')

    # 공통 파라미터
    common_params = [{'robot_id': robot_id}]

    tcp_bridge = Node(
        package='pinky_guide',
        executable='tcp_bridge_node.py',
        name='tcp_bridge_node',
        parameters=common_params + [
            {'server_host': server_host},
            {'server_port': server_port},
            {'reconnect_interval': 3.0},
        ],
        output='screen',
    )

    location_map = Node(
        package='pinky_guide',
        executable='location_map_node.py',
        name='location_map_node',
        parameters=common_params,
        output='screen',
    )

    task_executor = Node(
        package='pinky_guide',
        executable='task_executor_node.py',
        name='task_executor_node',
        parameters=common_params,
        output='screen',
    )

    nav_handler = Node(
        package='pinky_guide',
        executable='nav_handler_node.py',
        name='nav_handler_node',
        parameters=common_params + [
            {'map_frame': 'map'},
            {'arrival_tolerance': 0.25},
            {'default_max_speed': 0.3},
        ],
        output='screen',
    )

    return LaunchDescription([
        robot_id_arg,
        server_host_arg,
        server_port_arg,
        tcp_bridge,
        location_map,
        task_executor,
        nav_handler,
    ])
