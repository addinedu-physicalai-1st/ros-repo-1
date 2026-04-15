# Claude Code Prompt: ROS2 Robot State Machine Package

---

## 목표

레스토랑 서빙 로봇에 탑재될 ROS2 State Machine 패키지를 생성해줘. 1개의 Top FSM과 4개의 Sub FSM으로 구성되며, **로봇(ROBOT)과 중앙관제서버(HQ) 간의 ROS2 토픽/서비스 통신**만을 다룬다. 사용자 입력 디스플레이(DISPLAY)와의 통신은 HQ가 담당하므로, 로봇 측에서는 고려하지 않는다.

---

## 패키지 구조

```
rost_state_machine/
├── package.xml
├── CMakeLists.txt (or setup.py for Python)
├── launch/
│   └── state_machine.launch.py
├── rost_state_machine/
│   ├── __init__.py
│   ├── top_fsm.py
│   ├── sub_fsm/
│   │   ├── __init__.py
│   │   ├── follow_fsm.py       # 동행 Sub FSM
│   │   ├── delivery_fsm.py     # 운반 Sub FSM
│   │   ├── collect_fsm.py      # 수거 Sub FSM
│   │   └── guide_fsm.py        # 안내 Sub FSM
│   └── utils/
│       ├── __init__.py
│       └── fsm_base.py
└── msg/ (or use custom interface package)
```

Python 패키지로 구성하고, `smach` 또는 순수 Python 클래스 기반으로 FSM을 구현해줘. smach가 없다면 순수 Python enum + 클래스 기반으로 구현해줘.

---

## 1. Top FSM 설계

### 상태(States)

| 상태명 | 설명 |
|--------|------|
| `CHARGING` | 충전 중 (진입점) |
| `CHARGING_NO_TASK` | 충전 중 (투입불가, 배터리 < 20%) |
| `CHARGING_WITH_TASK` | 충전 중 (투입가능, 배터리 60~80%) |
| `MOVE_TO_STANDBY` | 대기장소로 이동 (배터리 > 80%) |
| `STANDBY` | 작업대기 |
| `GUIDE` | 안내 Sub FSM 실행 |
| `COLLECT` | 수거 Sub FSM 실행 |
| `FOLLOW` | 동행 Sub FSM 실행 |
| `DELIVERY` | 운반 Sub FSM 실행 |

### 전이(Transitions)

```
START → CHARGING

# 충전 흐름 (배터리 기반)
CHARGING --[배터리 < 20%]--> CHARGING_NO_TASK
CHARGING_NO_TASK --[배터리 > 60%]--> CHARGING_WITH_TASK
CHARGING_WITH_TASK --[배터리 > 80%]--> MOVE_TO_STANDBY

# 충전 중 투입가능(CHARGING_WITH_TASK) 상태에서 직접 작업 수신
CHARGING_WITH_TASK --[안내요청]--> GUIDE
CHARGING_WITH_TASK --[수거요청]--> COLLECT
CHARGING_WITH_TASK --[동행요청]--> FOLLOW
CHARGING_WITH_TASK --[운반요청]--> DELIVERY

# 대기장소 이동 후 대기 및 작업 분기
MOVE_TO_STANDBY --[도착]--> STANDBY
STANDBY --[안내 요청]--> GUIDE
STANDBY --[수거 요청]--> COLLECT
STANDBY --[동행 요청]--> FOLLOW
STANDBY --[운반 요청]--> DELIVERY

# 작업 완료 후 충전 복귀
GUIDE --[안내 완료]--> CHARGING
COLLECT --[수거 완료]--> CHARGING
FOLLOW --[동행 완료]--> CHARGING
DELIVERY --[운반 완료]--> CHARGING

# 충전으로 복귀 조건: 배터리 >= 20% 이면 MOVE_TO_STANDBY로
CHARGING --[배터리 >= 20%]--> MOVE_TO_STANDBY
```

---

## 2. Sub FSM: 동행 (FOLLOW)

### 상태(States)

| 상태명 | 설명 |
|--------|------|
| `FOLLOW_INIT` | 동행 시작 |
| `MOVE_TO_REQUESTER` | 동행 요청자 위치로 이동 |
| `VERIFY_REQUESTER` | 동행 요청자 확인 (HQ의 응답 대기) |
| `FOLLOWING` | 동행 요청자와 함께 이동 |
| `FOLLOW_END` | 동행 종료 |

### 전이(Transitions)

```
FOLLOW_INIT --[HQ로부터 FollowRequest 수신]--> MOVE_TO_REQUESTER
MOVE_TO_REQUESTER --[도착]--> VERIFY_REQUESTER
VERIFY_REQUESTER --[HQ로부터 FollowStart 수신]--> FOLLOWING
VERIFY_REQUESTER --[HQ로부터 RetryFollowRequest 수신]--> MOVE_TO_REQUESTER
VERIFY_REQUESTER --[HQ로부터 FollowEnd(타임아웃) 수신]--> FOLLOW_END
FOLLOWING --[HQ로부터 FollowEnd 수신]--> FOLLOW_END
FOLLOW_END --> (Top FSM: FOLLOW_DONE)
```

### ROS2 통신 (ROBOT ↔ HQ)

**동행 시작 단계:**
```
HQ → ROBOT : FollowRequest(target_pos)        # HQ가 이동 목표 위치 전달
ROBOT → HQ : ArrivedAtRequester()             # 로봇이 요청자 위치 도착 알림
```

**동행 진행 단계:**
```
HQ → ROBOT : FollowStart()                    # HQ가 동행 시작 명령 전달
ROBOT → HQ : NearTableFor1Min()               # 로봇이 테이블 근처 도달 1분 경과 알림
HQ → ROBOT : FollowEnd()                      # HQ가 동행 종료 명령 전달
```

**재시도 / 타임아웃:**
```
HQ → ROBOT : RetryFollowRequest()             # HQ가 재이동 명령 전달
HQ → ROBOT : FollowEnd()                      # HQ가 타임아웃으로 종료 명령 전달
```

---

## 3. Sub FSM: 운반 (DELIVERY)

### 상태(States)

| 상태명 | 설명 |
|--------|------|
| `DELIVERY_INIT` | 운반 시작 |
| `MOVE_TO_KITCHEN` | 주방으로 이동 |
| `LOADING` | 음식 적재 중 (HQ 신호 대기) |
| `DELIVERY_LOOP` | 다중 목적지 배송 루프 |
| `MOVE_TO_MENU_LOC` | 메뉴 위치로 이동 |
| `UNLOAD_MENU` | 메뉴 하차 (HQ 신호 대기) |
| `DELIVERY_END` | 운반 종료 |

### 전이(Transitions)

```
DELIVERY_INIT --[HQ로부터 MoveToKitchen 수신]--> MOVE_TO_KITCHEN
MOVE_TO_KITCHEN --[도착]--> LOADING
LOADING --[HQ로부터 StartDelivery 수신]--> DELIVERY_LOOP   # 적재 완료 신호로 간주

# 루프: MENU_POS_LIST 내 모든 위치 배송 완료까지 반복
DELIVERY_LOOP --[각 menu_pos 시작]--> MOVE_TO_MENU_LOC
MOVE_TO_MENU_LOC --[도착]--> UNLOAD_MENU
UNLOAD_MENU --[HQ로부터 StartDelivery(next) 수신]--> DELIVERY_LOOP   # 다음 목적지
UNLOAD_MENU --[HQ로부터 RetryStartDelivery 수신]--> MOVE_TO_MENU_LOC
DELIVERY_LOOP --[HQ로부터 DeliveryEnd 수신]--> DELIVERY_END
DELIVERY_END --> (Top FSM: DELIVERY_DONE)
```

### ROS2 통신 (ROBOT ↔ HQ)

**Phase 1: 주방 이동 및 적재 대기**
```
HQ → ROBOT : MoveToKitchen(kitchen_pos)       # HQ가 주방 좌표 전달
ROBOT → HQ : ArrivedAtKitchen()              # 로봇이 주방 도착 알림
# 로봇은 HQ로부터 다음 명령(StartDelivery) 수신까지 LOADING 상태 대기
```

**Phase 2: 다중 목적지 순차 배송 루프**
```
loop [각 menu_pos in MENU_POS_LIST (모두 배송 시까지)]:
    HQ → ROBOT : StartDelivery(MENU_POS_LIST[N])      # HQ가 배송 목적지 전달
    ROBOT → HQ : ArrivedAtMenuLocation()              # 로봇이 목적지 도착 알림
    # 로봇은 HQ로부터 다음 명령 수신까지 UNLOAD_MENU 상태 대기

    alt [OK]:
        HQ → ROBOT : StartDelivery(MENU_POS_LIST[N+1])  # 다음 목적지 전달
    alt [RETRY]:
        HQ → ROBOT : RetryStartDelivery(MENU_POS_LIST[N]) # 동일 위치 재이동
```

**Phase 3: 배송 완료**
```
HQ → ROBOT : DeliveryEnd()                    # HQ가 전체 배송 종료 명령 전달
```

---

## 4. Sub FSM: 수거 (COLLECT)

### 상태(States)

| 상태명 | 설명 |
|--------|------|
| `COLLECT_INIT` | 수거 시작 |
| `MOVE_TO_COLLECT_LOC` | 수거 요청자 위치로 이동 |
| `VERIFY_COLLECT` | 수거 요청자 확인 (HQ 응답 대기) |
| `COLLECTING` | 그릇 수거 (HQ 신호 대기) |
| `MOVE_TO_DISHWASH` | 설거지장으로 이동 |
| `DISHWASHING` | 설거지 제거 중 (HQ 신호 대기) |
| `COLLECT_END` | 수거 종료 |

### 전이(Transitions)

```
COLLECT_INIT --[HQ로부터 CollectRequest 수신]--> MOVE_TO_COLLECT_LOC
MOVE_TO_COLLECT_LOC --[도착]--> VERIFY_COLLECT
VERIFY_COLLECT --[HQ로부터 StartCollection 수신]--> COLLECTING
VERIFY_COLLECT --[HQ로부터 RetryCollectRequest 수신]--> MOVE_TO_COLLECT_LOC
VERIFY_COLLECT --[HQ로부터 CollectionEnd(타임아웃) 수신]--> COLLECT_END

COLLECTING --[HQ로부터 CollectionDone 수신 & (배터리 < 20% or request_count >= 5)]--> MOVE_TO_DISHWASH
COLLECTING --[HQ로부터 CollectionDone 수신 & request_count < 5]--> COLLECT_END

MOVE_TO_DISHWASH --[도착]--> DISHWASHING
DISHWASHING --[HQ로부터 CollectionEnd 수신]--> COLLECT_END
COLLECT_END --> (Top FSM: COLLECT_DONE)
```

### ROS2 통신 (ROBOT ↔ HQ)

**초기 이동 및 확인:**
```
HQ → ROBOT : CollectRequest(requester_pos)    # HQ가 수거 위치 전달
ROBOT → HQ : ArrivedAtRequester()            # 로봇이 요청자 위치 도착 알림
# 로봇은 HQ로부터 다음 명령 수신까지 VERIFY_COLLECT 상태 대기
```

**수거 진행:**
```
HQ → ROBOT : StartCollection()               # HQ가 수거 시작 명령 전달
# 로봇은 HQ로부터 CollectionDone 수신까지 COLLECTING 상태 대기
HQ → ROBOT : CollectionDone()               # HQ가 수거 완료 명령 전달
```

**분기 처리:**
```
alt [battery < 20% or request_count >= 5]:
    HQ → ROBOT : MoveToDishwashing()         # HQ가 설거지장 이동 명령 전달
alt [request_count < 5]:
    HQ → ROBOT : CollectionEnd()             # HQ가 수거 종료 명령 전달
```

**재시도 / 타임아웃:**
```
HQ → ROBOT : RetryCollectRequest(requester_pos)  # HQ가 재이동 명령 전달
HQ → ROBOT : CollectionEnd()                     # HQ가 타임아웃 종료 명령 전달
```

**설거지장 도착 및 완료:**
```
ROBOT → HQ : ArrivedAtDishwashing()         # 로봇이 설거지장 도착 알림
# 로봇은 HQ로부터 CollectionEnd 수신까지 DISHWASHING 상태 대기
HQ → ROBOT : CollectionEnd()               # HQ가 설거지 완료 후 종료 명령 전달
```

---

## 5. Sub FSM: 안내 (GUIDE)

### 상태(States)

| 상태명 | 설명 |
|--------|------|
| `GUIDE_INIT` | 안내 시작 |
| `MOVE_TO_GUIDE_REQUESTER` | 안내 요청자 위치로 이동 |
| `VERIFY_AND_SELECT` | 안내 요청자 확인 및 목적지 수신 (HQ 응답 대기) |
| `GUIDE_LOOP` | 다중 안내 위치 루프 |
| `MOVE_TO_TARGET` | 안내 위치로 이동 |
| `VERIFY_ARRIVAL` | 안내자 도착 확인 (HQ 응답 대기) |
| `GUIDE_END` | 안내 종료 |

### 전이(Transitions)

```
GUIDE_INIT --[HQ로부터 MoveToRequester 수신]--> MOVE_TO_GUIDE_REQUESTER
MOVE_TO_GUIDE_REQUESTER --[도착]--> VERIFY_AND_SELECT
VERIFY_AND_SELECT --[HQ로부터 GuideStart(target_pos) 수신]--> GUIDE_LOOP
VERIFY_AND_SELECT --[HQ로부터 RetryMoveToRequester 수신]--> MOVE_TO_GUIDE_REQUESTER
VERIFY_AND_SELECT --[HQ로부터 GuideEnd(타임아웃) 수신]--> GUIDE_END

# 루프: 안내 위치 모두 안내 완료까지
GUIDE_LOOP --[각 target_pos 시작]--> MOVE_TO_TARGET
MOVE_TO_TARGET --[도착]--> VERIFY_ARRIVAL
VERIFY_ARRIVAL --[HQ로부터 GuideStart(next) 수신 (OK or TIMEOUT)]--> GUIDE_LOOP
VERIFY_ARRIVAL --[HQ로부터 RetryGuideStart 수신]--> MOVE_TO_TARGET
GUIDE_LOOP --[HQ로부터 GuideEnd 수신]--> GUIDE_END
GUIDE_END --> (Top FSM: GUIDE_DONE)
```

### ROS2 통신 (ROBOT ↔ HQ)

**Phase 1: 초기 이동**
```
HQ → ROBOT : MoveToRequester(current_user_pos)  # HQ가 요청자 위치 전달
ROBOT → HQ : ArrivedAtRequester()              # 로봇이 요청자 위치 도착 알림
# 로봇은 HQ로부터 다음 명령 수신까지 VERIFY_AND_SELECT 상태 대기
```

**Phase 2: 목적지별 순차 안내 루프**
```
loop [각 target_pos in SELECTED_DESTINATION_LIST (모든 안내 완료까지)]:
    HQ → ROBOT : GuideStart(target_pos)          # HQ가 안내 목적지 전달
    ROBOT → HQ : ArrivedAtTarget()              # 로봇이 안내 목적지 도착 알림
    # 로봇은 HQ로부터 다음 명령 수신까지 VERIFY_ARRIVAL 상태 대기

    alt [confirm_STATUS is OK or TIMEOUT]:
        HQ → ROBOT : GuideStart(next_target_pos)  # 다음 안내 목적지 전달
    alt [confirm_STATUS is RETRY]:
        HQ → ROBOT : RetryGuideStart(target_pos)  # 동일 목적지 재이동 명령
```

**Phase 3: 완료**
```
HQ → ROBOT : GuideEnd()                         # HQ가 안내 종료 명령 전달

alt [RETRY 상황]:
    HQ → ROBOT : RetryMoveRequester(current_user_pos)  # 요청자에게 재이동 명령

alt [TIMEOUT 상황]:
    HQ → ROBOT : GuideEnd()                     # HQ가 세션 타임아웃으로 종료 명령
```

---

## 6. ROS2 토픽/서비스/액션 인터페이스 정의

> **설계 원칙**: 로봇은 HQ로부터 명령을 수신하고, 이벤트(도착, 상태변화)를 HQ에 전송한다.
> DISPLAY와의 통신은 HQ가 전담하므로 로봇 노드에서 구현하지 않는다.

### Topics (ROBOT → HQ)

| 토픽 | 메시지 타입 | 설명 |
|------|------------|------|
| `/robot/state` | `std_msgs/String` | 현재 FSM 상태 퍼블리시 |
| `/robot/battery` | `sensor_msgs/BatteryState` | 배터리 상태 퍼블리시 |
| `/robot/event` | `robot_state_machine/RobotEvent` | 도착 이벤트, 완료 이벤트 등 퍼블리시 |

### Topics (HQ → ROBOT)

| 토픽 | 메시지 타입 | 설명 |
|------|------------|------|
| `/hq/command` | `robot_state_machine/RobotCommand` | HQ가 로봇에 전달하는 명령 |
| `/hq/navigation_goal` | `geometry_msgs/PoseStamped` | 이동 목표 좌표 |

### Services (HQ → ROBOT, 작업 요청)

| 서비스 | 타입 | 설명 |
|--------|------|------|
| `/robot/task_request` | `robot_state_machine/TaskRequest` | HQ가 로봇에 작업 종류 및 목표 전달 |

### Custom Messages

다음 커스텀 메시지/서비스를 `msg/` 및 `srv/` 폴더에 정의해줘:

```
# msg/RobotCommand.msg
# HQ → ROBOT 명령 메시지
string command         # FollowRequest, FollowStart, FollowEnd, RetryFollowRequest,
                       # MoveToKitchen, StartDelivery, RetryStartDelivery, DeliveryEnd,
                       # CollectRequest, CollectionStart, CollectionDone, MoveToDishwashing,
                       # RetryCollectRequest, CollectionEnd,
                       # MoveToRequester, GuideStart, RetryGuideStart, GuideEnd, RetryMoveToRequester
string session_id
geometry_msgs/PoseStamped target_pose
int32 count

# msg/RobotEvent.msg
# ROBOT → HQ 이벤트 메시지
string event           # ArrivedAtRequester, ArrivedAtKitchen, ArrivedAtMenuLocation,
                       # ArrivedAtDishwashing, ArrivedAtTarget, NearTableFor1Min
string session_id
geometry_msgs/PoseStamped current_pose

# srv/TaskRequest.srv
# HQ → ROBOT 작업 시작 요청
string task_type       # FOLLOW, DELIVERY, COLLECT, GUIDE
geometry_msgs/PoseStamped[] target_poses
string session_id
---
bool accepted
string message
```

---

## 7. 구현 요구사항

1. **FSM 클래스 구조**: 각 FSM은 `state`, `transition()`, `on_enter()`, `on_exit()` 메서드를 갖는 기본 클래스를 상속받아 구현
2. **ROS2 Node**: Top FSM은 하나의 ROS2 노드(`robot_state_machine_node`)로 실행
3. **배터리 모니터링**: `/robot/battery` 토픽을 내부 퍼블리시하고, 배터리 퍼센트에 따라 Top FSM 전이 트리거
4. **HQ 명령 수신**: `/hq/command` 토픽을 구독하여 `command` 필드에 따라 적절한 Sub FSM 전이 트리거
5. **이벤트 퍼블리시**: 도착, 완료 등의 이벤트는 `/robot/event` 토픽으로 HQ에 전달
6. **타임아웃 처리**: 각 Sub FSM의 `VERIFY_*` 상태에서 HQ 명령이 오지 않을 경우를 대비해 파라미터로 설정 가능한 로컬 타임아웃(기본값 30초) 구현. 타임아웃 시 HQ에 이벤트를 전송하고 HQ 명령을 기다린다.
7. **수거 횟수 카운터**: COLLECT Sub FSM에서 `request_count` 변수 관리 (5회 이상 또는 배터리 < 20% 시 설거지장 이동)
8. **로깅**: 모든 상태 전이는 `rclpy.logging`으로 INFO 레벨 로그 출력
9. **파라미터**: 타임아웃 시간, 배터리 임계값(20%, 60%, 80%)은 ROS2 파라미터로 외부 설정 가능하게 구현
10. **런치 파일**: `state_machine.launch.py`에서 노드 실행 및 파라미터 설정

---

## 8. 테스트 노드

간단한 테스트/시뮬레이션을 위한 `test_state_machine.py` 노드도 생성해줘. 이 노드는 **HQ 역할을 시뮬레이션**하여 로봇 FSM을 테스트한다:

- `/hq/command` 토픽에 `RobotCommand` 메시지를 수동으로 퍼블리시하여 FSM 전이 트리거
- `/robot/event` 토픽을 구독하여 로봇 이벤트를 콘솔에 출력
- `/robot/state` 토픽을 구독하여 현재 FSM 상태를 콘솔에 출력
- 배터리 레벨 시뮬레이션: `/robot/battery`에 0~100% 값 퍼블리시
- 각 작업(동행/운반/수거/안내) 시나리오를 순서대로 시뮬레이션하는 헬퍼 함수 포함

---

## 참고사항

- Python 3.10+ 기준
- ROS2 Humble 또는 Iron 호환
- `rclpy` 사용
- 의존성: `rclpy`, `std_msgs`, `geometry_msgs`, `sensor_msgs`, `action_msgs`
- 모든 파일에 한국어 주석 포함 가능
