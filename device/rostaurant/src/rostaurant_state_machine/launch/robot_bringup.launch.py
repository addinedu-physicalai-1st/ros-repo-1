"""
robot_bringup.launch.py

rostaurant_state_machine + rostaurant_function + rostaurant_safety_layer 를
한 번에 기동하는 통합 런치 파일.

모든 노드 파라미터는 src/config/config.yaml (통합 설정) 에서 로드합니다.

실행 예:
  # 기본
  ros2 launch rostaurant_state_machine robot_bringup.launch.py

  # 커스텀 설정 파일
  ros2 launch rostaurant_state_machine robot_bringup.launch.py config:=/path/to/custom.yaml

  # Gazebo + Nav2 연동
  ros2 launch rostaurant_state_machine robot_bringup.launch.py use_sim_time:=true

  # 안전레이어 제외 (개발/테스트용)
  ros2 launch rostaurant_state_machine robot_bringup.launch.py safety:=false
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import (
    AnyLaunchDescriptionSource,
    PythonLaunchDescriptionSource,
)
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # ------------------------------------------------------------------ #
    # 공통 아규먼트                                                          #
    # ------------------------------------------------------------------ #
    config_arg = DeclareLaunchArgument(
        'config',
        default_value=PathJoinSubstitution([
            FindPackageShare('rostaurant_state_machine'), 'config', 'config.yaml'
        ]),
        description='통합 파라미터 yaml 파일 경로. 기본값: src/config/config.yaml',
    )
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Gazebo 시뮬레이션 시간 사용 여부',
    )
    safety_arg = DeclareLaunchArgument(
        'safety',
        default_value='true',
        description='false: safety_layer 제외 (개발/테스트용)',
    )

    config = LaunchConfiguration('config')
    use_sim_time = LaunchConfiguration('use_sim_time')
    safety = LaunchConfiguration('safety')

    # ------------------------------------------------------------------ #
    # 1. rostaurant_state_machine                                          #
    # ------------------------------------------------------------------ #
    state_machine = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rostaurant_state_machine'),
                'launch', 'state_machine.launch.py',
            ])
        ]),
        launch_arguments={
            'config': config,
            'use_sim_time': use_sim_time,
        }.items(),
    )

    # ------------------------------------------------------------------ #
    # 2. rostaurant_function                                               #
    # ------------------------------------------------------------------ #
    robot_function = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rostaurant_function'),
                'launch', 'robot_function.launch.py',
            ])
        ]),
        launch_arguments={
            'config': config,
            'use_sim_time': use_sim_time,
        }.items(),
    )

    # ------------------------------------------------------------------ #
    # 3. rostaurant_safety_layer (safety:=false 이면 제외)                  #
    # ------------------------------------------------------------------ #
    safety_layer = IncludeLaunchDescription(
        AnyLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('rostaurant_safety_layer'),
                'launch', 'safety_layer.launch.xml',
            ])
        ]),
        launch_arguments={
            'config': config,
            'use_sim_time': use_sim_time,
        }.items(),
        condition=IfCondition(safety),
    )

    return LaunchDescription([
        config_arg,
        use_sim_time_arg,
        safety_arg,
        state_machine,
        robot_function,
        safety_layer,
    ])
