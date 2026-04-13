"""
robot_function.launch.py

모든 function_node를 동시에 기동하는 런치 파일.

실행 노드:
  - top_function_node      : 충전/대기/이동 기능, 배터리 시뮬
  - follow_function_node   : 동행 기능
  - delivery_function_node : 운반 기능
  - collect_function_node  : 수거 기능
  - guide_function_node    : 안내 기능

rost_state_machine과 함께 사용하는 예:
  ros2 launch rost_function robot_function.launch.py
  ros2 launch rost_state_machine state_machine.launch.py

시뮬레이션 모드 (Nav2 없이):
  ros2 launch rost_function robot_function.launch.py use_nav2:=false simulated_nav_time:=3.0

Nav2 사용:
  ros2 launch rost_function robot_function.launch.py use_nav2:=true
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # ------------------------------------------------------------------ #
    # 공통 런치 아규먼트                                                      #
    # ------------------------------------------------------------------ #
    use_nav2_arg = DeclareLaunchArgument(
        'use_nav2',
        default_value='false',
        description='Nav2 사용 여부. false면 simulated_nav_time 후 자동 도달 처리.'
    )
    simulated_nav_time_arg = DeclareLaunchArgument(
        'simulated_nav_time',
        default_value='3.0',
        description='시뮬레이션 모드에서 내비게이션 도달 시뮬 시간 (초).'
    )

    # ------------------------------------------------------------------ #
    # Top 전용 아규먼트                                                       #
    # ------------------------------------------------------------------ #
    standby_x_arg = DeclareLaunchArgument(
        'standby_pos_x', default_value='0.0',
        description='대기장소 X 좌표 (m)'
    )
    standby_y_arg = DeclareLaunchArgument(
        'standby_pos_y', default_value='0.0',
        description='대기장소 Y 좌표 (m)'
    )
    standby_theta_arg = DeclareLaunchArgument(
        'standby_pos_theta', default_value='0.0',
        description='대기장소 방향 (rad)'
    )
    battery_level_arg = DeclareLaunchArgument(
        'battery_level', default_value='0.8',
        description='초기 배터리 레벨 (0.0~1.0)'
    )

    # ------------------------------------------------------------------ #
    # Collect 전용 아규먼트                                                   #
    # ------------------------------------------------------------------ #
    dishwash_x_arg = DeclareLaunchArgument(
        'dishwash_pos_x', default_value='0.0',
        description='설거지장 X 좌표 (m)'
    )
    dishwash_y_arg = DeclareLaunchArgument(
        'dishwash_pos_y', default_value='0.0',
        description='설거지장 Y 좌표 (m)'
    )
    dishwash_theta_arg = DeclareLaunchArgument(
        'dishwash_pos_theta', default_value='0.0',
        description='설거지장 방향 (rad)'
    )
    max_collect_arg = DeclareLaunchArgument(
        'max_collect_count', default_value='5',
        description='설거지장 이동 임계 수거 횟수'
    )

    # ------------------------------------------------------------------ #
    # Follow 전용 아규먼트                                                    #
    # ------------------------------------------------------------------ #
    follow_time_arg = DeclareLaunchArgument(
        'follow_time_limit', default_value='60.0',
        description='동행 최대 시간 (초). 초과 시 NearTableOr1Min 이벤트 퍼블리시.'
    )
    follow_dist_arg = DeclareLaunchArgument(
        'follow_table_distance_threshold', default_value='1.5',
        description='테이블 근접 판정 거리 (m)'
    )

    # ------------------------------------------------------------------ #
    # 공통 파라미터 딕셔너리                                                   #
    # ------------------------------------------------------------------ #
    common_params = {
        'use_nav2': LaunchConfiguration('use_nav2'),
        'simulated_nav_time': LaunchConfiguration('simulated_nav_time'),
    }

    # ------------------------------------------------------------------ #
    # 노드 정의                                                              #
    # ------------------------------------------------------------------ #
    top_node = Node(
        package='rost_function',
        executable='top_function_node',
        name='top_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[{
            **common_params,
            'standby_pos_x': LaunchConfiguration('standby_pos_x'),
            'standby_pos_y': LaunchConfiguration('standby_pos_y'),
            'standby_pos_theta': LaunchConfiguration('standby_pos_theta'),
            'battery_level': LaunchConfiguration('battery_level'),
        }]
    )

    follow_node = Node(
        package='rost_function',
        executable='follow_function_node',
        name='follow_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[{
            **common_params,
            'follow_time_limit': LaunchConfiguration('follow_time_limit'),
            'follow_table_distance_threshold':
                LaunchConfiguration('follow_table_distance_threshold'),
        }]
    )

    delivery_node = Node(
        package='rost_function',
        executable='delivery_function_node',
        name='delivery_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[common_params]
    )

    collect_node = Node(
        package='rost_function',
        executable='collect_function_node',
        name='collect_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[{
            **common_params,
            'dishwash_pos_x': LaunchConfiguration('dishwash_pos_x'),
            'dishwash_pos_y': LaunchConfiguration('dishwash_pos_y'),
            'dishwash_pos_theta': LaunchConfiguration('dishwash_pos_theta'),
            'max_collect_count': LaunchConfiguration('max_collect_count'),
        }]
    )

    guide_node = Node(
        package='rost_function',
        executable='guide_function_node',
        name='guide_function_node',
        output='screen',
        emulate_tty=True,
        parameters=[common_params]
    )

    return LaunchDescription([
        # 런치 아규먼트
        use_nav2_arg,
        simulated_nav_time_arg,
        standby_x_arg,
        standby_y_arg,
        standby_theta_arg,
        battery_level_arg,
        dishwash_x_arg,
        dishwash_y_arg,
        dishwash_theta_arg,
        max_collect_arg,
        follow_time_arg,
        follow_dist_arg,
        # 노드
        top_node,
        follow_node,
        delivery_node,
        collect_node,
        guide_node,
    ])
