cmake_minimum_required(VERSION 3.10)
project(rost_state_machine)

# 빌드 의존성
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)

# 커스텀 메시지/서비스 생성
rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/RobotCommand.msg"
  "msg/RobotEvent.msg"
  "srv/TaskRequest.srv"
  DEPENDENCIES geometry_msgs
)

# Python 패키지 직접 설치
# (rosidl_generate_interfaces가 동일 패키지명으로 Python 타겟을 생성하므로
#  ament_python_install_package 대신 install()을 직접 사용한다.)
install(DIRECTORY rost_state_machine
  DESTINATION ${PYTHON_INSTALL_DIR}
)

# Python 실행 노드 설치
install(PROGRAMS
  rost_state_machine/fsm_node.py
  test/test_state_machine.py
  DESTINATION lib/${PROJECT_NAME}
)

# 런치 파일 설치
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# 리소스 파일 설치
install(DIRECTORY resource/
  DESTINATION share/ament_index/resource_index/packages
)

ament_export_dependencies(rosidl_default_runtime)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
