string robot_id
uint8 robot_status   # RobotStatus enum 값
uint8 fsm_state      # FsmState enum 값
string current_task
int32 battery
uint8 last_error     # ErrorCode enum 값
uint8 event_type     # TaskEventType enum 값 (0=없음, 1=ARRIVED_AT_REQUESTER, ...)
