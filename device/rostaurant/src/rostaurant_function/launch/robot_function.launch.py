"""
robot_function.launch.py

모든 function_node를 동시에 기동하는 런치 파일.

실행 노드:
  - top_function_node      : 충전/대기/이동 기능, 배터리 모니터링
  - follow_function_node   : 동행 기능
  - delivery_function_node : 운반 기능
  - collect_function_node  : 수거 기능
  - guide_function_node    : 안내 기능

기본 실행 (config/robot_function.yaml 로드):
  ros2 launch rostaurant_function robot_function.launch.py

Gazebo 시뮬레이션 실행 (Nav2 연동):
  ros2 launch rostaurant_function robot_function.launch.py sim:=true use_sim_time:=true

커스텀 yaml 지정:
  ros2 launch rostaurant_function robot_function.launch.py config:=/path/to/custom.yaml

rostaurant_state_machine과 함께 사용:
  ros2 launch rostaurant_function robot_function.launch.py sim:=true use_sim_time:=true
  ros2 launch rostaurant_state_machine state_machine.launch.py use_sim_time:=true
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # ------------------------------------------------------------------ #
    # yaml 설정 파일 경로 아규먼트                                            #
    # ------------------------------------------------------------------ #
    sim_arg = DeclareLaunchArgument(
        'sim',
        default_value='false',
        description='true: Gazebo용 robot_function_gz.yaml 사용 (use_nav2=true), false: robot_function.yaml 사용'
    )
    config_arg = DeclareLaunchArgument(
        'config',
        default_value=PathJoinSubstitution([
            FindPackageShare('rostaurant_function'), 'config',
            PythonExpression([
                '"robot_function_gz.yaml" if "', LaunchConfiguration('sim'), '" == "true" else "robot_function.yaml"'
            ])
        ]),
        description='파라미터 yaml 파일 경로. sim:=true 시 robot_function_gz.yaml 자동 선택'
    )
    use_sim_time_arg = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Gazebo 시뮬레이션 시간 사용 여부'
    )

    config = LaunchConfiguration('config')
    use_sim_time = LaunchConfiguration('use_sim_time')

    # ------------------------------------------------------------------ #
    # 노드 정의 — parameters 에 yaml 파일 경로를 전달                         #
    # ------------------------------------------------------------------ #
    top_node = Node(
        package='rostaurant_function',
        executable='top_function_node',
        name='top_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[config, {'use_sim_time': use_sim_time}],
    )

    follow_node = Node(
        package='rostaurant_function',
        executable='follow_function_node',
        name='follow_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[config, {'use_sim_time': use_sim_time}],
    )

    delivery_node = Node(
        package='rostaurant_function',
        executable='delivery_function_node',
        name='delivery_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[config, {'use_sim_time': use_sim_time}],
    )

    collect_node = Node(
        package='rostaurant_function',
        executable='collect_function_node',
        name='collect_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[config, {'use_sim_time': use_sim_time}],
    )

    guide_node = Node(
        package='rostaurant_function',
        executable='guide_function_node',
        name='guide_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[config, {'use_sim_time': use_sim_time}],
    )

    return LaunchDescription([
        sim_arg,
        config_arg,
        use_sim_time_arg,
        top_node,
        follow_node,
        delivery_node,
        collect_node,
        guide_node,
    ])
