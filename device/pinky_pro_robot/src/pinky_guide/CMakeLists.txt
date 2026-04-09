cmake_minimum_required(VERSION 3.8)
project(pinky_guide)

find_package(ament_cmake REQUIRED)
find_package(rclpy REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(std_msgs REQUIRED)

# 커스텀 메시지 / 액션 생성
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/GuideCommand.msg"
  "msg/GuideResult.msg"
  "msg/RobotStatus.msg"
  "action/GuideTask.action"
  DEPENDENCIES geometry_msgs std_msgs
)

# Python 노드 설치
install(PROGRAMS
  pinky_guide/tcp_bridge_node.py
  pinky_guide/task_executor_node.py
  pinky_guide/nav_handler_node.py
  pinky_guide/location_map_node.py
  DESTINATION lib/${PROJECT_NAME}
)

# config / launch 설치
install(DIRECTORY config launch
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
