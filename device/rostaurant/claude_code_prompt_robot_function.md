# Claude Code Prompt: ROS2 Robot Function Package (`robot_function`)

---

## 목표

기존에 작성된 `robot_state_machine` 패키지와 연동하여, 로봇의 각 FSM 상태에서 실제로 실행될 **기능 노드**들을 `robot_function` 패키지로 구현해줘. 이 패키지는 상태 머신이 각 상태에 진입할 때 실제 로봇 동작(이동, 이벤트 퍼블리시 등)을 수행하는 역할을 한다.

---

## 패키지 구조

```
robot_function/
├── package.xml
├── setup.py
├── launch/
│   └── robot_function.launch.py
└── robot_function/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── navigation_client.py     # Nav2 Action Client 래퍼
    │   └── event_publisher.py       # /robot/event 퍼블리셔 래퍼
    ├── top/
    │   ├── __init__.py
    │   └── top_function_node.py     # Top FSM 상태 기능 (충전/대기/이동)
    ├── follow/
    │   ├── __init__.py
    │   └── follow_function_node.py  # 동행 Sub FSM 기능
    ├── delivery/
    │   ├── __init__.py
    │   └── delivery_function_node.py # 운반 Sub FSM 기능
    ├── collect/
    │   ├── __init__.py
    │   └── collect_function_node.py  # 수거 Sub FSM 기능
    └── guide/
        ├── __init__.py
        └── guide_function_node.py    # 안내 Sub FSM 기능
```

---

## 설계 원칙

### 상태 머신 ↔ 기능 노드 통신 구조

```
[robot_state_machine 패키지]           [robot_function 패키지]
  /robot/state (String) ──────────────→ 각 function_node (상태 구독)
  /hq/command (RobotCommand) ─────────→ 각 function_node (명령 구독)
                                         │
  /robot/event (RobotEvent) ←────────── 각 function_node (이벤트 퍼블리시)
  /robot/battery (BatteryState) ←────── top_function_node (배터리 시뮬)
```

### 핵심 동작 방식

- 각 function_node는 `/robot/state` 토픽을 구독하여 **현재 FSM 상태**를 파악한다.
- 해당 상태에 대응하는 기능(이동 명령, 이벤트 퍼블리시 등)을 실행한다.
- 기능 완료 후 `/robot/event` 토픽에 이벤트를 퍼블리시하여 상태 머신이 전이를 트리거하도록 한다.
- `/hq/command` 구독을 통해 HQ 명령에 반응하여 추가 동작을 실행한다.

---

## 공통 모듈

### 1. `navigation_client.py`

Nav2 `NavigateToPose` Action Client를 래핑한 클래스:

```
class NavigationClient:
    - send_goal(pose: PoseStamped) → Future
    - cancel_goal()
    - is_navigating() → bool
    - on_goal_reached_callback 등록 기능
    - 목표 도달 시 콜백 호출
```

### 2. `event_publisher.py`

`/robot/event` 토픽 퍼블리셔 래퍼 클래스:

```
class EventPublisher:
    - publish_event(event: str, session_id: str = "", pose: PoseStamped = None)
    # 지원 이벤트명:
    # ArrivedAtRequester, ArrivedAtKitchen, ArrivedAtMenuLocation,
    # ArrivedAtDishwashing, ArrivedAtTarget, NearTableOr1Min
```

---

## Top FSM 기능 노드 (`top_function_node.py`)

### 담당 상태

| 상태명 | 실행 기능 |
|--------|-----------|
| `CHARGING` | 충전 중 상태 유지, 배터리 레벨 모니터링 |
| `CHARGING_NO_TASK` | 배터리 < 20%: 투입불가 상태 유지 |
| `CHARGING_WITH_TASK` | 배터리 60~80%: 투입가능 상태 알림 |
| `MOVE_TO_STANDBY` | 대기장소(standby_pos) 파라미터 위치로 Nav2 이동 명령 실행 |
| `STANDBY` | 대기장소 도달 후 작업 대기 |

### 구현 내용

**배터리 시뮬레이션 (`/robot/battery` 퍼블리시):**
```
- 파라미터: battery_level (0.0 ~ 1.0, 기본값 0.8)
- 1초마다 /robot/battery 에 BatteryState 메시지 퍼블리시
- 배터리 레벨은 외부에서 파라미터 업데이트로 변경 가능
- 충전 중(CHARGING_*) 상태에서는 배터리 레벨 증가 시뮬레이션 (0.005/sec)
- 작업 상태(GUIDE/COLLECT/FOLLOW/DELIVERY)에서는 배터리 레벨 감소 시뮬레이션 (0.002/sec)
```

**`MOVE_TO_STANDBY` 상태 진입 시:**
```
1. 파라미터 standby_pos (x, y, theta) 읽기
2. NavigationClient.send_goal(standby_pose) 호출
3. 목표 도달 시 → /robot/event 에 "ArrivedAtStandby" 퍼블리시
```

**파라미터:**
```yaml
standby_pos_x: 0.0       # 대기장소 x 좌표
standby_pos_y: 0.0       # 대기장소 y 좌표
standby_pos_theta: 0.0   # 대기장소 방향 (rad)
battery_level: 0.8       # 초기 배터리 레벨 (0.0~1.0)
```

---

## 동행 Sub FSM 기능 노드 (`follow_function_node.py`)

### 담당 상태 및 실행 기능

```
FOLLOW_INIT
  └─ /hq/command (FollowRequest, target_pos) 수신 대기
  └─ 수신 시 → target_pos 저장, 상태 머신이 MOVE_TO_REQUESTER로 전이하도록 트리거

MOVE_TO_REQUESTER
  └─ 저장된 target_pos로 NavigationClient.send_goal() 실행
  └─ 도달 시 → /robot/event 에 "ArrivedAtRequester" 퍼블리시

VERIFY_REQUESTER
  └─ /hq/command 구독 대기
     └─ FollowStart → FOLLOWING 전이 신호 (상태 머신이 처리)
     └─ RetryFollowRequest(new_pos) → 새 target_pos 저장, NavigationClient.send_goal() 재실행
                                      → 도달 시 ArrivedAtRequester 퍼블리시
     └─ FollowEnd → FOLLOW_END 전이 신호 (타임아웃)

FOLLOWING
  └─ 동행 요청자 추종 동작 (주기적으로 목표 위치 갱신 or Navigation 유지)
  └─ 타이머: 1분 또는 테이블 근접 조건 체크
     └─ 조건 충족 시 → /robot/event 에 "NearTableOr1Min" 퍼블리시
  └─ /hq/command FollowEnd 수신 시 → 이동 중지, FOLLOW_END 전이

FOLLOW_END
  └─ 현재 이동 중지 (NavigationClient.cancel_goal())
  └─ 세션 데이터 초기화
```

**파라미터:**
```yaml
follow_table_distance_threshold: 1.5   # 테이블 근접 판정 거리 (m)
follow_time_limit: 60.0                # 동행 최대 시간 (초)
```

---

## 운반 Sub FSM 기능 노드 (`delivery_function_node.py`)

### 담당 상태 및 실행 기능

```
DELIVERY_INIT
  └─ /hq/command (MoveToKitchen, kitchen_pos) 수신 대기
  └─ 수신 시 → kitchen_pos 저장

MOVE_TO_KITCHEN
  └─ 저장된 kitchen_pos로 NavigationClient.send_goal() 실행
  └─ 도달 시 → /robot/event 에 "ArrivedAtKitchen" 퍼블리시

LOADING
  └─ /hq/command (StartDelivery, target_pose) 수신 대기
     └─ StartDelivery 수신 → menu_pos 저장 (첫 번째 목적지)
     └─ 로봇 이동 없음 (적재 대기 중)

DELIVERY_LOOP
  └─ 현재 배송해야 할 menu_pos 확인
  └─ menu_pos가 남아있으면 → MOVE_TO_MENU_LOC 로직 실행
  └─ /hq/command (DeliveryEnd) 수신 시 → DELIVERY_END 전이

MOVE_TO_MENU_LOC
  └─ 현재 menu_pos로 NavigationClient.send_goal() 실행
  └─ 도달 시 → /robot/event 에 "ArrivedAtMenuLocation" 퍼블리시

UNLOAD_MENU
  └─ /hq/command 구독 대기
     └─ StartDelivery(next_pos) → 다음 menu_pos 저장, DELIVERY_LOOP로 복귀
     └─ RetryStartDelivery(same_pos) → 동일 위치로 NavigationClient.send_goal() 재실행
                                       → 도달 시 ArrivedAtMenuLocation 퍼블리시
     └─ DeliveryEnd → DELIVERY_END 전이

DELIVERY_END
  └─ 세션 데이터 초기화 (menu_pos 리스트 클리어)
  └─ NavigationClient.cancel_goal() (잔여 이동 있을 경우)
```

---

## 수거 Sub FSM 기능 노드 (`collect_function_node.py`)

### 담당 상태 및 실행 기능

```
COLLECT_INIT
  └─ /hq/command (CollectRequest, requester_pos) 수신 대기
  └─ 수신 시 → requester_pos 저장

MOVE_TO_COLLECT_LOC
  └─ 저장된 requester_pos로 NavigationClient.send_goal() 실행
  └─ 도달 시 → /robot/event 에 "ArrivedAtRequester" 퍼블리시

VERIFY_COLLECT
  └─ /hq/command 구독 대기
     └─ CollectionStart → COLLECTING 전이 (상태 머신이 처리)
     └─ RetryCollectRequest(new_pos) → new_pos로 NavigationClient.send_goal() 재실행
                                       → 도달 시 ArrivedAtRequester 퍼블리시
     └─ CollectionEnd(타임아웃) → COLLECT_END 전이

COLLECTING
  └─ 수거 대기 중 (이동 없음)
  └─ request_count 증가
  └─ /hq/command 구독
     └─ CollectionDone 수신 시:
        - 배터리 < 20% or request_count >= 5 → MOVE_TO_DISHWASH 전이
        - 그 외 → CollectionEnd 전이
     └─ CollectionEnd 수신 시 → COLLECT_END 전이

MOVE_TO_DISHWASH
  └─ 파라미터 dishwash_pos로 NavigationClient.send_goal() 실행
  └─ 도달 시 → /robot/event 에 "ArrivedAtDishwashing" 퍼블리시

DISHWASHING
  └─ /hq/command (CollectionEnd) 수신 대기
  └─ 수신 시 → COLLECT_END 전이

COLLECT_END
  └─ request_count 초기화
  └─ 세션 데이터 초기화
```

**파라미터:**
```yaml
dishwash_pos_x: 0.0
dishwash_pos_y: 0.0
dishwash_pos_theta: 0.0
max_collect_count: 5          # 설거지장 이동 임계 수거 횟수
```

---

## 안내 Sub FSM 기능 노드 (`guide_function_node.py`)

### 담당 상태 및 실행 기능

```
GUIDE_INIT
  └─ /hq/command (MoveToRequester, current_user_pos) 수신 대기
  └─ 수신 시 → user_pos 저장

MOVE_TO_GUIDE_REQUESTER
  └─ 저장된 user_pos로 NavigationClient.send_goal() 실행
  └─ 도달 시 → /robot/event 에 "ArrivedAtRequester" 퍼블리시

VERIFY_AND_SELECT
  └─ /hq/command 구독 대기
     └─ GuideStart(target_pos) → target_pos 저장 (첫 안내 목적지)
                                  GUIDE_LOOP 전이 (상태 머신이 처리)
     └─ RetryMoveRequester(user_pos) → new_pos로 NavigationClient.send_goal() 재실행
                                       → 도달 시 ArrivedAtRequester 퍼블리시
     └─ GuideEnd(타임아웃) → GUIDE_END 전이

GUIDE_LOOP
  └─ 현재 target_pos 확인
  └─ target_pos가 남아있으면 → MOVE_TO_TARGET 로직 실행
  └─ /hq/command (GuideEnd) 수신 시 → GUIDE_END 전이

MOVE_TO_TARGET
  └─ 현재 target_pos로 NavigationClient.send_goal() 실행
  └─ 도달 시 → /robot/event 에 "ArrivedAtTarget" 퍼블리시

VERIFY_ARRIVAL
  └─ /hq/command 구독 대기
     └─ GuideStart(next_pos) → 다음 target_pos 저장, GUIDE_LOOP 복귀
     └─ RetryGuideStart(same_pos) → 동일 위치로 NavigationClient.send_goal() 재실행
                                    → 도달 시 ArrivedAtTarget 퍼블리시
     └─ GuideEnd → GUIDE_END 전이

GUIDE_END
  └─ 세션 데이터 초기화 (target_pos 리스트 클리어)
  └─ NavigationClient.cancel_goal()
```

---

## 런치 파일 (`robot_function.launch.py`)

모든 function_node를 동시에 실행하며, 각각 독립적인 노드로 기동:

```python
# 실행 노드:
# - top_function_node
# - follow_function_node
# - delivery_function_node
# - collect_function_node
# - guide_function_node
#
# 공통 파라미터 파일 경로 지정 가능하도록 구성
```

전체 실행 예시 (robot_state_machine과 함께):

```bash
ros2 launch robot_function robot_function.launch.py
ros2 launch robot_state_machine state_machine.launch.py
```

---

## 구현 요구사항

1. **상태 구독 방식**: 각 function_node는 `/robot/state` 토픽(`std_msgs/String`)을 구독하여 현재 상태를 확인하고, 해당 상태의 진입 시(`on_state_enter`) 기능을 실행한다. 이전 상태와 비교하여 상태 변경 시점을 감지한다.

2. **Nav2 연동**: `NavigationClient`는 `nav2_msgs/action/NavigateToPose` 액션을 사용한다. Nav2가 없는 환경에서는 파라미터 `use_nav2: false` 설정 시 목표 수신 후 일정 시간(파라미터 `simulated_nav_time: 3.0`) 후 자동으로 도달 이벤트를 퍼블리시하는 **시뮬레이션 모드**로 동작한다.

3. **HQ 명령 파싱**: `/hq/command` 토픽의 `RobotCommand.msg` `command` 필드를 파싱하여 해당 상태에서 처리해야 할 명령인지 확인한다. 관련 없는 명령은 무시한다.

4. **이벤트 퍼블리시**: 모든 이벤트는 `robot_state_machine/msg/RobotEvent.msg`를 사용하여 `/robot/event` 토픽에 퍼블리시한다. `session_id`는 현재 세션 ID를 포함한다.

5. **로깅**: 모든 상태 진입, 이동 명령 전송, 이벤트 퍼블리시는 `rclpy.logging` INFO 레벨로 출력한다.

6. **파라미터**: 모든 좌표 및 임계값은 ROS2 파라미터로 설정 가능하게 구현한다.

7. **노드 명명**: 각 노드는 다음 이름을 사용한다:
   - `top_function_node`
   - `follow_function_node`
   - `delivery_function_node`
   - `collect_function_node`
   - `guide_function_node`

8. **의존성**: `robot_state_machine` 패키지의 커스텀 메시지(`RobotCommand`, `RobotEvent`)를 import하여 사용한다. `package.xml`에 `robot_state_machine` 의존성을 명시한다.

---

## 메시지 인터페이스 참조 (`robot_state_machine` 패키지)

```
# RobotCommand.msg (HQ → ROBOT)
string command
string session_id
geometry_msgs/PoseStamped target_pose
int32 count

# RobotEvent.msg (ROBOT → HQ)
string event
string session_id
geometry_msgs/PoseStamped current_pose
```

### 명령(command) 파싱 대응표

| command 값 | 처리 노드 | 처리 상태 |
|------------|-----------|-----------|
| `FollowRequest` | follow_function_node | FOLLOW_INIT |
| `FollowStart` | follow_function_node | VERIFY_REQUESTER |
| `FollowEnd` | follow_function_node | VERIFY_REQUESTER / FOLLOWING |
| `RetryFollowRequest` | follow_function_node | VERIFY_REQUESTER |
| `MoveToKitchen` | delivery_function_node | DELIVERY_INIT |
| `StartDelivery` | delivery_function_node | LOADING / UNLOAD_MENU |
| `RetryStartDelivery` | delivery_function_node | UNLOAD_MENU |
| `DeliveryEnd` | delivery_function_node | DELIVERY_LOOP / UNLOAD_MENU |
| `CollectRequest` | collect_function_node | COLLECT_INIT |
| `CollectionStart` | collect_function_node | VERIFY_COLLECT |
| `CollectionDone` | collect_function_node | COLLECTING |
| `MoveToDishwashing` | collect_function_node | COLLECTING |
| `RetryCollectRequest` | collect_function_node | VERIFY_COLLECT |
| `CollectionEnd` | collect_function_node | VERIFY_COLLECT / COLLECTING / DISHWASHING |
| `MoveToRequester` | guide_function_node | GUIDE_INIT |
| `GuideStart` | guide_function_node | VERIFY_AND_SELECT / VERIFY_ARRIVAL |
| `RetryGuideStart` | guide_function_node | VERIFY_ARRIVAL |
| `GuideEnd` | guide_function_node | VERIFY_AND_SELECT / GUIDE_LOOP / VERIFY_ARRIVAL |
| `RetryMoveRequester` | guide_function_node | VERIFY_AND_SELECT |

---

## 참고사항

- Python 3.10+ 기준
- ROS2 Humble 또는 Iron 호환
- `rclpy` 사용
- 의존성: `rclpy`, `std_msgs`, `geometry_msgs`, `sensor_msgs`, `nav2_msgs`, `action_msgs`, `robot_state_machine`
- `use_nav2: false` 시뮬레이션 모드를 기본값으로 구현하여 Nav2 없이도 테스트 가능하게 할 것
- 모든 파일에 한국어 주석 포함 가능
