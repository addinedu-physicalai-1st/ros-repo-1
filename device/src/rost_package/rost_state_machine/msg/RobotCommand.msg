# HQ → ROBOT 명령 메시지
# 지원 command 값:
#   동행: FollowRequest, FollowStart, FollowEnd, RetryFollowRequest
#   운반: MoveToKitchen, StartDelivery, RetryStartDelivery, DeliveryEnd
#   수거: CollectRequest, StartCollection, CollectionDone, MoveToDishwashing,
#          RetryCollectRequest, CollectionEnd
#   안내: MoveToRequester, GuideStart, RetryGuideStart, GuideEnd, RetryMoveToRequester

string command
string session_id
geometry_msgs/PoseStamped target_pose
int32 count
