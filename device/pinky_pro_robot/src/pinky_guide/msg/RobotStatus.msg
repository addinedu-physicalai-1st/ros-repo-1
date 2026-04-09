# 로봇 상태 — tcp_bridge_node 가 TCP NDJSON(type=robot_status)으로 주기 전송

uint8 STATE_IDLE     = 0
uint8 STATE_MOVING   = 1
uint8 STATE_ARRIVED  = 2
uint8 STATE_ERROR    = 3

uint8   robot_id
uint8   state
string  current_task   # 현재 수행 중인 dest_name ("" 이면 idle)
float32 battery        # 0.0 ~ 100.0
float32 pose_x
float32 pose_y
