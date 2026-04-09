# 안내 완료 / 실패 결과 — tcp_bridge_node 가 JSON(type=guide_result) 한 줄로 송신

uint8 STATUS_SUCCESS   = 0
uint8 STATUS_FAILED    = 1
uint8 STATUS_CANCELLED = 2
uint8 STATUS_OBSTACLE  = 3  # 장애물로 인한 중단

uint8  robot_id
uint8  cmd_type     # 원본 명령 타입
uint8  status       # 위 상수 중 하나
string dest_name    # 완료된 목적지 이름
string message      # 부가 메시지 (오류 원인 등)
