"""
state_machine.launch.py

robot_state_machine_node 런치 파일.
파라미터는 config/state_machine.yaml 에서 로드한다.

사용 예:
  ros2 launch rostaurant_state_machine state_machine.launch.py
  ros2 launch rostaurant_state_machine state_machine.launch.py config:=/path/to/custom.yaml
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # ------------------------------------------------------------------ #
    # yaml 설정 파일 경로 아규먼트                                            #
    # ------------------------------------------------------------------ #
    config_arg = DeclareLaunchArgument(
        'config',
        default_value=PathJoinSubstitution([
            FindPackageShare('rostaurant_state_machine'), 'config', 'state_machine.yaml'
        ]),
        description='파라미터 yaml 파일 경로. 기본값: config/state_machine.yaml'
    )
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Gazebo 시뮬레이션 시간 사용 여부'
    )

    # ------------------------------------------------------------------ #
    # 노드 실행                                                              #
    # ------------------------------------------------------------------ #
    state_machine_node = Node(
        package='rostaurant_state_machine',
        executable='fsm_node.py',
        name='robot_state_machine_node',
        output='screen',
        emulate_tty=True,
        parameters=[
            LaunchConfiguration('config'),
            {'use_sim_time': LaunchConfiguration('use_sim_time')},
        ],
    )

    return LaunchDescription([
        config_arg,
        use_sim_time_arg,
        state_machine_node,
    ])
