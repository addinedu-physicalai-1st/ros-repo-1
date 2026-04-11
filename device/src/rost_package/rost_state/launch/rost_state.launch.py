"""
rost_state.launch.py — Launch file for the rost_state FSM system.

Usage
-----
# Default (IDLE start, battery simulation enabled)
ros2 launch rost_state rost_state.launch.py

# Start in CHARGING state with debug output
ros2 launch rost_state rost_state.launch.py initial_state:=CHARGING debug_mode:=true

# Real hardware — disable battery simulation (use /battery_percent topic)
ros2 launch rost_state rost_state.launch.py battery_sim:=false

Parameters
----------
initial_state   str     IDLE     One of: CHARGING, MOVE_TO_WAITING, IDLE,
                                         DELIVERY, PICKUP, FOLLOW, GUIDE
debug_mode      bool    false    Print per-tick state logs at DEBUG level
battery_sim     bool    true     Simulate battery drain/charge cycle

After launch — send test events
---------------------------------
# Assign a delivery task
ros2 topic pub --once /fsm/event std_msgs/String "{data: 'TASK_ASSIGNED:DELIVERY'}"

# Signal arrival at pickup location
ros2 topic pub --once /fsm/event std_msgs/String "{data: 'ARRIVED'}"

# Complete the pickup step (item secured)
ros2 topic pub --once /fsm/event std_msgs/String "{data: 'TASK_COMPLETED'}"

# Signal arrival at drop-off location
ros2 topic pub --once /fsm/event std_msgs/String "{data: 'ARRIVED'}"

# Complete the drop-off step
ros2 topic pub --once /fsm/event std_msgs/String "{data: 'TASK_COMPLETED'}"

# Simulate low battery
ros2 topic pub --once /fsm/event std_msgs/String "{data: 'BATTERY_LOW'}"

# Monitor state in real time
ros2 topic echo /fsm/state
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    # ── Declare arguments ─────────────────────────────────────────────────────
    initial_state_arg = DeclareLaunchArgument(
        'initial_state',
        default_value='IDLE',
        description=(
            'Initial TopFSM state. '
            'Choices: CHARGING | MOVE_TO_WAITING | IDLE | '
            'DELIVERY | PICKUP | FOLLOW | GUIDE'
        ),
    )

    debug_mode_arg = DeclareLaunchArgument(
        'debug_mode',
        default_value='false',
        description='Enable verbose per-tick state logging.',
    )

    battery_sim_arg = DeclareLaunchArgument(
        'battery_sim',
        default_value='true',
        description=(
            'Simulate battery drain/charge cycle. '
            'Set false when using real /battery_percent topic.'
        ),
    )

    # ── FSM node ──────────────────────────────────────────────────────────────
    fsm_node = Node(
        package='rost_state',
        executable='fsm_node',
        name='fsm_node',
        output='screen',
        parameters=[{
            'initial_state': LaunchConfiguration('initial_state'),
            'debug_mode':    LaunchConfiguration('debug_mode'),
            'battery_sim':   LaunchConfiguration('battery_sim'),
        }],
        # Emit ROS2 INFO and above; set to DEBUG for _handle_event traces.
        arguments=['--ros-args', '--log-level', 'INFO'],
    )

    return LaunchDescription([
        initial_state_arg,
        debug_mode_arg,
        battery_sim_arg,
        fsm_node,
    ])
