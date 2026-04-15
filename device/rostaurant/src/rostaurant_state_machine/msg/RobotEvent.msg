# ROBOT → HQ 이벤트 메시지
# 지원 event 값:
#   ArrivedAtRequester   - 요청자 위치 도착
#   ArrivedAtKitchen     - 주방 도착
#   ArrivedAtMenuLocation - 메뉴 목적지 도착
#   ArrivedAtDishwashing - 설거지장 도착
#   ArrivedAtTarget      - 안내 목적지 도착
#   NearTableFor1Min     - 테이블 근처 1분 경과 (동행)
#   TimeoutWaiting       - 대기 타임아웃 발생

string event
string session_id
geometry_msgs/PoseStamped current_pose
