"""
robot_bringup.launch.py

rostaurant_state_machine + rostaurant_function + rostaurant_safety_layer 를
한 번에 기동하는 통합 런치 파일.

실행 예:
  # 기본 (시뮬레이션 타이머, 안전레이어 포함)
  ros2 launch rostaurant_state_machine robot_bringup.launch.py

  # Gazebo + Nav2 연동
  ros2 launch rostaurant_state_machine robot_bringup.launch.py sim:=true use_sim_time:=true

  # 안전레이어 제외 (개발/테스트용)
  ros2 launch rostaurant_state_machine robot_bringup.launch.py safety:=false

  # Gazebo + 안전레이어 제외
  ros2 launch rostaurant_state_machine robot_bringup.launch.py sim:=true use_sim_time:=true safety:=false
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import (
    AnyLaunchDescriptionSource,
    PythonLaunchDescriptionSource,
)
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # ------------------------------------------------------------------ #
    # 공통 아규먼트                                                          #
    # ------------------------------------------------------------------ #
    sim_arg = DeclareLaunchArgument(
        'sim',
        default_value='false',
        description='true: Gazebo용 robot_function_gz.yaml 사용 (use_nav2=true)',
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

    use_sim_time = LaunchConfiguration('use_sim_time')
    sim = LaunchConfiguration('sim')
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
            'sim': sim,
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
            'use_sim_time': use_sim_time,
        }.items(),
        condition=IfCondition(safety),
    )

    return LaunchDescription([
        sim_arg,
        use_sim_time_arg,
        safety_arg,
        state_machine,
        robot_function,
        safety_layer,
    ])
