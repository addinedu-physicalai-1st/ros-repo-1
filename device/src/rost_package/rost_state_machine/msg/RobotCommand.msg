# HQ → ROBOT 명령 메시지
# 지원 command 값:
#   동행: FollowRequest, FollowStart, FollowEnd, RetryFollowRequest
#   운반: MoveToKitchen, StartDelivery, RetryStartDelivery, DeliveryEnd
#   수거: CollectRequest, StartCollection, CollectionDone, MoveToDishwashing,
#          RetryCollectRequest, CollectionEnd
#   안내: MoveToRequester, GuideStart, RetryGuideStart, GuideEnd, RetryMoveToRequester
#
# 목표 위치는 x, y, theta(yaw, rad)만 전달하면 됩니다.
# 나머지 PoseStamped 필드(frame_id, stamp, orientation)는 각 function 노드에서 자동으로 채웁니다.

string command
string session_id
float64 x
float64 y
float64 theta
int32 count
