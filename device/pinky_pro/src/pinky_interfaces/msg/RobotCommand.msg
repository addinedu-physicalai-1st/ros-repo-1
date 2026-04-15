string cmd_id
string task_id
string robot_id
uint8 command        # CommandType enum 값 (MOVE_TO=1, FOLLOW_CMD=6, COLLECT_CMD=7, ...)
string target_id
float64 target_x
float64 target_y
float64 target_theta
uint8 task_action    # 태스크별 액션 (FollowAction / CollectionAction / DeliveryAction / GuidanceAction)
int32 step_index     # 운반/안내에서 N번째 목적지 (0-based, 해당 없으면 0)
