"""Single-robot launch file for physical deployment.

Robot ID is resolved automatically inside the node (hostname → ROBOT_ID env var).
The only argument exposed here is the control server address so that operators
do not need to memorise or type the robot name.

Usage (on each physical robot after `hostnamectl set-hostname pnkXX`):
    ros2 launch rostaurant_networking robot.launch.py
    ros2 launch rostaurant_networking robot.launch.py server_host:=192.168.1.10

Override robot ID without changing the hostname (e.g. for quick testing):
    ROBOT_ID=PNK02 ros2 launch rostaurant_networking robot.launch.py
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument(
            "server_host",
            default_value="127.0.0.1",
            description="IP address of the MRTA control server",
        ),
        DeclareLaunchArgument(
            "tcp_port",
            default_value="9000",
            description="Control server TCP port",
        ),
        DeclareLaunchArgument(
            "udp_port",
            default_value="9001",
            description="Control server UDP port",
        ),
        Node(
            package="rostaurant_networking",
            executable="rostaurant_comm_node",
            parameters=[{
                "server_host":    LaunchConfiguration("server_host"),
                "tcp_port":       LaunchConfiguration("tcp_port"),
                "udp_port":       LaunchConfiguration("udp_port"),
                "battery_topic":  "battery/percent",  # matches battery_publisher.py
            }],
            output="screen",
        ),
    ])
