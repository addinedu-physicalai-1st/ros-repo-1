# 관제서버(TCP NDJSON type=guide_command)에서 파싱한 명령
# tcp_bridge_node 가 수신 후 이 메시지로 publish

uint8 CMD_KIOSK_TO_TABLE  = 1   # 키오스크 → 테이블 안내
uint8 CMD_TABLE_TO_TOILET = 2   # 테이블 → 화장실 안내
uint8 CMD_TABLE_TO_DISPLAY = 3  # 테이블 → 메뉴 진열대 안내
uint8 CMD_RETURN_TO_DOCK  = 4   # 대기장소 복귀

uint8  cmd_type       # 위 상수 중 하나
uint8  robot_id       # 이 로봇의 ID (1~5)
uint16 dest_id        # 목적지 ID (locations.yaml 키와 매핑)
string dest_name      # 목적지 이름 (예: "table_3", "toilet_a", "steak_display")
