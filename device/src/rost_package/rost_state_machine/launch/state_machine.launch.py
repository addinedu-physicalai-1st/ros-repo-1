"""
state_machine.launch.py

robot_state_machine_node 런치 파일.
모든 파라미터를 런치 아규먼트로 재정의할 수 있다.

사용 예:
  ros2 launch rost_state_machine state_machine.launch.py
  ros2 launch rost_state_machine state_machine.launch.py battery_low:=15.0 nav_delay:=3.0
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # ------------------------------------------------------------------ #
    # 런치 아규먼트 선언                                                     #
    # ------------------------------------------------------------------ #
    timeout_secs_arg = DeclareLaunchArgument(
        'timeout_secs',
        default_value='30.0',
        description='VERIFY 상태 타임아웃 시간 (초). HQ 명령이 없을 경우 이벤트를 보내고 재대기한다.'
    )
    battery_low_arg = DeclareLaunchArgument(
        'battery_low',
        default_value='20.0',
        description='배터리 부족 임계값 (%). 이 값 미만이면 CHARGING_NO_TASK 상태.'
    )
    battery_mid_arg = DeclareLaunchArgument(
        'battery_mid',
        default_value='60.0',
        description='배터리 중간 임계값 (%). 이 값 초과 시 CHARGING_WITH_TASK 상태.'
    )
    battery_high_arg = DeclareLaunchArgument(
        'battery_high',
        default_value='80.0',
        description='배터리 충분 임계값 (%). 이 값 초과 시 대기장소로 이동.'
    )
    nav_delay_arg = DeclareLaunchArgument(
        'nav_delay',
        default_value='5.0',
        description='내비게이션 시뮬레이션 지연 시간 (초). 실제 로봇에서는 Nav2로 교체.'
    )

    # ------------------------------------------------------------------ #
    # 노드 실행                                                              #
    # ------------------------------------------------------------------ #
    state_machine_node = Node(
        package='rost_state_machine',
        executable='fsm_node.py',
        name='robot_state_machine_node',
        output='screen',
        emulate_tty=True,
        parameters=[{
            'timeout_secs': LaunchConfiguration('timeout_secs'),
            'battery_low': LaunchConfiguration('battery_low'),
            'battery_mid': LaunchConfiguration('battery_mid'),
            'battery_high': LaunchConfiguration('battery_high'),
            'nav_delay': LaunchConfiguration('nav_delay'),
        }]
    )

    return LaunchDescription([
        timeout_secs_arg,
        battery_low_arg,
        battery_mid_arg,
        battery_high_arg,
        nav_delay_arg,
        state_machine_node,
    ])
