"""Multi-robot simulation launch file.

Spawns one rostaurant_comm_node per robot entry in ROBOTS, each with a
unique ROBOT_ID environment variable so that robot IDs are injected without
relying on hostnames (all nodes run on the same machine in simulation).

Each robot's ROS topics are namespaced by robot ID:
    /PNK01/odom, /PNK01/battery, /PNK01/task_status, /PNK01/robot_command
    /PNK02/odom, ...

To add or remove robots, edit the ROBOTS list only.

Usage:
    ros2 launch rostaurant_networking multi_robot_sim.launch.py
    ros2 launch rostaurant_networking multi_robot_sim.launch.py server_host:=192.168.1.10
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# Edit this list to change how many robots are simulated.
ROBOTS = ["PNK01", "PNK02", "PNK03"]


def generate_launch_description() -> LaunchDescription:
    actions = [
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
    ]

    for rid in ROBOTS:
        rid_lower = rid.lower()
        actions.append(Node(
            package="rostaurant_networking",
            executable="rostaurant_comm_node",
            name=f"rostaurant_comm_{rid_lower}",
            parameters=[{
                "server_host":          LaunchConfiguration("server_host"),
                "tcp_port":             LaunchConfiguration("tcp_port"),
                "udp_port":             LaunchConfiguration("udp_port"),
                "odom_topic":           f"/{rid}/odom",
                "battery_topic":        f"/{rid}/battery",
                "task_status_topic":    f"/{rid}/task_status",
                "robot_command_topic":  f"/{rid}/robot_command",
            }],
            additional_env={"ROBOT_ID": rid},
            output="screen",
        ))

    return LaunchDescription(actions)
