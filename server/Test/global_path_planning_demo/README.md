# Waypoint-based A* Global Path Planner Demo

뷔페 환경에서 동작하는 pinky pro 로봇용 **웨이포인트 기반 Global Path Planning** 방식의 구현 검증을 위한 독립 기술 데모 프로그램입니다. 본 프로그램은 메인 ROS 프로젝트와 분리된 순수 Python 데모이며, 알고리즘 동작과 시각적 결과 확인만을 목적으로 합니다.

## 배경

현재 프로젝트는 격자 형태의 뷔페 공간에서 작은 모바일 로봇(pinky pro) 여러 대로 서비스를 제공하는 것을 목표로 합니다. 사람이 많이 다니는 공간이라 안전한 주행이 필요하고, 격자 구조의 통로를 따라 **예측 가능한 직진 + 직각 회전** 위주의 경로가 요구됩니다.

이를 위해 Nav2의 기본 Global Planner인 NavFn 대신, 통로 교차점과 주요 지점(입구, 충전소, 주방, 퇴식구, 테이블 앞)에 미리 찍어둔 웨이포인트 그래프 위에서 A*로 최단 경로를 탐색하는 방식을 검증합니다. 본 데모는 그 방식이 실제로 원하는 형태의 경로를 만들어내는지 시각적으로 보여주는 것이 목적입니다.

## 동작 환경

- Ubuntu 24.04
- Python 3.12+
- matplotlib 3.7 이상 (인터랙티브 모드)

코드 스타일은 PEP 8을 따릅니다.

## 설치

```bash
# 시스템 패키지로 설치하는 경우
sudo apt install python3-matplotlib

# 또는 pip 사용
pip install -r requirements.txt
```

## 실행

```bash
cd server/Test/global_path_planning_demo

# 인터랙티브 모드 (matplotlib 창이 열림)
python3 main.py

# 헤드리스 모드 (창 없이 시나리오 자동 실행)
#  - Waypoint -> Waypoint  5개
#  - Free start point -> Waypoint  4개
python3 main.py --headless
```

### 인터랙티브 조작

| 입력 | 동작 |
|---|---|
| **좌클릭 1회** | START 자유 좌표 선택 — 클릭 위치를 그대로 시작점으로 사용. 웨이포인트로 스냅하지 않음. 시작점 주변 옅은 점선 원이 진입 반경(`entry_radius`, 기본 2.5 m)을 표시. 장애물 내부거나 맵 밖이면 거부 메시지 후 다시 클릭 대기 |
| **좌클릭 2회** | GOAL 웨이포인트 선택 (가장 가까운 웨이포인트로 스냅), A* 즉시 실행 후 경로 표시 |
| **좌클릭 3회** | 새로운 쿼리 시작 (이전 선택 초기화) |
| **우클릭** | 동적 장애물(다른 로봇 등) 추가 — 클릭 위치에 반경 0.6 m 원형 장애물을 떨어뜨림. start/goal이 이미 설정되어 있으면 즉시 재계획. 정적 장애물 내부 / 맵 밖 / 현재 시작점 위에는 거부 |
| `r` | 현재 start/goal 선택 리셋 (동적 장애물은 유지) |
| `c` | 모든 동적 장애물 삭제 (start/goal 유지). start/goal이 설정되어 있으면 재계획 |
| `q` | 종료 |

> 시작점만 자유롭고 목적지는 웨이포인트로 스냅합니다. 뷔페 운용에서 목적지는 입구·주방·퇴식구·테이블 앞 등 미리 정의된 서비스 위치로 한정되는 것이 자연스러운 반면, 시작점은 로봇의 임의 현재 자세이기 때문입니다.

## 테스트 맵 구성

20m × 15m 크기의 단순화된 뷔페 공간으로, 1셀 = 1m 입니다.

- **정적 장애물 (8개)**: 뷔페 스테이션 6개(A1~A3, B1~B3) 2열 + 주방(Kitchen) + 퇴식구(Return) + 외벽 — 축 정렬 사각형, 그래프 빌드 시 한 번만 평가
- **동적 장애물 (런타임)**: `DynamicObstacle(x, y, radius)` — 다른 로봇 등을 표현하는 원형 장애물. plan 호출 시점의 스냅샷으로만 사용되고 정적 그래프는 변경하지 않음
- **웨이포인트 (27개)**: 통로 교차점 + 명명된 서비스 지점
  - `Entrance`: 입구
  - `CS-Left`, `CS-Right`: 좌/우 충전 스테이션
  - `Kitchen`: 주방 진입점
  - `Return`: 퇴식구 진입점
  - `A1-S`, `A3-S`: 뷔페 A열 남쪽 서빙 위치
  - `A1-N/B1-S`, `A2-N/B2-S`, `A3-N/B3-S`: 뷔페 A열·B열 사이 통로 서빙 위치
  - `B1-N`, `B2-N`, `B3-N`: 뷔페 B열 북쪽 서빙 위치
- **간선 (37개)**: 같은 행/열에 있는 인접 웨이포인트 중 장애물을 통과하지 않는 쌍만 자동 연결 → 모든 간선이 축 정렬(horizontal/vertical)

이 구조 덕분에 어떤 조합의 start/goal을 골라도 결과 경로는 항상 직진과 직각 회전만으로 구성됩니다.

## 알고리즘

- **탐색 알고리즘**: A* (`heapq` 기반 우선순위 큐)
- **간선 비용**: 인접 웨이포인트 간 Euclidean 거리 (축 정렬이므로 Manhattan과 동일)
- **휴리스틱**: 목표까지의 Manhattan 거리. 모든 간선이 축 정렬이라 admissible 하며 항상 최적 경로를 보장합니다.

### 자유 시작점 처리 (반경 제한 multi-source A*)

자유 좌표 `(sx, sy)`에서 출발할 때는 단순히 가장 가까운 웨이포인트로 스냅하지 않고, **진입 반경 내에서의 다중 시드 A***로 진입 웨이포인트를 최적화합니다.

1. `(sx, sy)`가 장애물 내부면 거부.
2. `(sx, sy)`에서 직선 시야(line-of-sight, 0.1m 간격 샘플링)로 도달 가능하면서 **`entry_radius` (기본 2.5 m) 이내**에 있는 모든 웨이포인트를 진입 후보로 수집.
3. 각 후보에 `(sx, sy)`까지의 직선 거리(Euclidean)를 **초기 g-score**로 부여.
4. 위 시드들을 모두 open list에 넣은 상태로 A*를 한 번만 실행 → A*가 자연스럽게 `entry_distance + corridor_cost`가 최소인 진입점을 선택.
5. 반경 내에 단 하나의 후보도 없으면(예: 시작점이 통로 그래프와 멀리 떨어진 위치) **fallback**으로 가장 가까운 line-of-sight 도달 가능 웨이포인트 1개를 사용. 이 경우 결과의 `entry_radius_fallback` 플래그가 True가 되어 호출 측에서 경고할 수 있도록 함.
6. 결과는 `FreeStartPlan(start_xy, waypoints, entry_distance, waypoint_cost, entry_radius, entry_radius_fallback)` 데이터 클래스로 반환.

#### 왜 진입 반경을 제한하는가

반경 제한이 없으면, 시작점에서 목적지까지 직선이 line-of-sight로 뚫려 있을 때 A*가 **목적지 자체를 시드**로 잡고 격자를 무시한 채 길게 사선 주행하는 경로를 반환할 수 있습니다. 이는 본 프로젝트가 명시적으로 피하고자 하는 형태입니다.

- 본 프로젝트의 핵심 요구사항: "예측 가능한 직진 + 직각 회전"
- 뷔페는 사람이 많은 공간 → 통로를 따라가는 동선이 안전하고 사람에게 예측 가능
- Local Planner(DWB)는 Global Path가 알려진 통로를 따른다고 가정할 때 가장 안정적
- 운영/검증 측면에서도 동선이 항상 "현재 위치 → 근처 웨이포인트 → 격자 경로 → 목적지" 한 가지 형태로 일관되는 것이 유리

`entry_radius`(기본 2.5 m, 셀 약 2~3개)는 이 균형을 위한 값으로, 반경 안에서는 multi-source A* 최적화가 그대로 살아 있어 의미 있는 케이스에서는 여전히 최적 진입점을 골라줍니다.

#### 진입점이 가장 가까운 웨이포인트가 아닌 케이스 (반경 내 최적화 예시)

- `(8.50, 6.00) → Return`: 가장 가까운 웨이포인트는 1.5m 거리의 `A1-N/B1-S(7,6)`이지만, A*는 같은 거리의 `A2-N/B2-S(10,6)`을 선택 → 이후 통로 비용이 더 짧음 (총 12.50 m).
- `(19.00, 10.20) → Kitchen`: 가장 가까운 웨이포인트는 1.02m 거리의 `(18,10)`이지만, A*는 2.06m 거리의 `(18,12)`를 선택 → `(18,10)` 진입 시 총 17.02 m vs `(18,12)` 진입 시 총 16.06 m.
- `(10.40, 0.60) → Kitchen`: 반경 2.5 m 안에는 `Entrance(10,1)` 하나뿐이라 그것이 진입점 → 17.57 m. 반경 제한이 없을 때 가능한 17.42 m(`(7,1)` 진입) 대비 0.15 m 손실은 안전성/일관성 측면 이득에 비해 무시 가능.

### 동적 장애물 처리 (quasi-static + 재계획)

다른 로봇이 통로에 정차해 있거나 잠시 멈춰 있는 상황을 시뮬레이션하기 위해 원형 동적 장애물을 지원합니다. 시간에 따른 미래 궤적 예측(time-expanded ST-A*) 방식이 아닌, **plan 호출 시점에 "지금 그 자리에 있는 벽"으로 취급**하고 상황이 바뀌면 다시 plan을 호출하는 quasi-static 방식입니다 (Nav2 등 거의 모든 프로덕션 시스템이 채택).

처리 절차:

1. plan 호출 시 `dynamic_obstacles` 리스트가 주어지면 `_compute_blockage()`로 차단 집합 미리 계산:
   - **차단 웨이포인트**: 어떤 동적 장애물의 원이 웨이포인트를 포함하면 차단 (`circle_contains_point`)
   - **차단 간선**: 양 끝 웨이포인트가 차단되었거나, 간선 segment가 어떤 동적 장애물의 원과 교차하면 차단 (`circle_intersects_segment`, 표준 segment-vs-circle 거리 계산)
2. A* expansion에서 차단된 웨이포인트와 간선은 스킵
3. 자유 시작점 처리 시:
   - 시작점 자체가 어느 동적 장애물의 원 안이면 거부 (`None` 반환)
   - 진입 후보 수집 단계에서 차단된 웨이포인트는 제외
   - 진입 segment가 어느 동적 장애물의 원과 교차하면 그 후보는 제외
4. 목적지가 차단되면 즉시 `None` 반환
5. 최단 우회 경로가 없으면 `None` 반환

이렇게 하면 정적 그래프는 그대로 유지된 채 런타임 상황에 따라 자연스럽게 우회 경로가 만들어집니다. 본 데모에서는 우클릭으로 동적 장애물을 추가/`c`키로 삭제할 때마다 즉시 재계획되어, "시간이 흘러 상황이 바뀌면 새 plan을 받는" 운영 모델을 시각적으로 확인할 수 있습니다.

#### 동적 장애물 시나리오 예시 (헤드리스)

```
[dyn] Entrance -> Kitchen
  scenario: R1 parked at junction (7,6) blocks the central north-south corridor
  obstacles: R1@(7,6) r=0.6
  baseline (no dyn): cost=17.00 m, 6 wps
    path: Entrance -> (7,1) -> (7,6) -> (7,10) -> B1-N -> Kitchen
  with dyn:          cost=23.00 m, 8 wps
    path: Entrance -> (7,1) -> A1-S -> CS-Left -> (1,6) -> (1,10) -> B1-N -> Kitchen
    detour: +6.00 m vs baseline

[dyn] Entrance -> Return
  scenario: R1 stopped on edge (13,1)->(13,6); A* should find an alternative column
  obstacles: R1@(13,3.5) r=0.6
  baseline (no dyn): cost=16.00 m, 6 wps
    path: Entrance -> (13,1) -> (13,6) -> (13,10) -> B3-N -> Return
  with dyn:          cost=22.00 m, 8 wps
    path: Entrance -> (13,1) -> A3-S -> CS-Right -> (18,6) -> (18,10) -> B3-N -> Return
    detour: +6.00 m vs baseline

[dyn] Entrance -> Kitchen
  scenario: R1 sits exactly on the goal Kitchen - planner must report no path
  obstacles: R1@(4,12) r=0.6
  with dyn:          NO PATH FOUND

[dyn-free] (11.00, 0.50) -> Kitchen
  scenario: R1 sits on the preferred entry waypoint (10,1)
  obstacles: R1@(10,1) r=0.6
  baseline (no dyn): entry=Entrance (1.12 m), total=18.12 m
  with dyn:          entry=(13,1) (2.06 m), total=22.06 m
    path: (11.00,0.50) -> (13,1) -> (13,6) -> (13,10) -> (13,12) -> (7,12) -> Kitchen

[dyn-free] (19.00, 10.20) -> Kitchen
  scenario: R1 blocks the entry waypoint (18,12) used by the baseline
  obstacles: R1@(18,12) r=0.6
  baseline (no dyn): entry=(18,12) (2.06 m), total=16.06 m
  with dyn:          entry=(18,10) (1.02 m), total=17.02 m
    path: (19.00,10.20) -> (18,10) -> B3-N -> (13,10) -> (13,12) -> (7,12) -> Kitchen
```

확인 포인트:
- **간선 차단**: R1@(13, 3.5)는 어느 웨이포인트도 포함하지 않지만 간선 `(13,1)→(13,6)` 위에 있으므로 segment-vs-circle 검사로 정확히 그 간선만 차단됨.
- **목적지 차단 안전 처리**: R1이 Kitchen 위에 있으면 즉시 `NO PATH FOUND` 반환.
- **자유 시작점 진입 재선택**: 동적 장애물이 baseline 진입 웨이포인트를 막으면, 반경 내 multi-source A*가 자동으로 다른 진입점을 골라 우회 경로를 만듦.

## 파일 구조

```
global_path_planning_demo/
├── main.py            # 진입점 (인터랙티브 / --headless)
├── map_data.py        # 뷔페 테스트 맵 + 웨이포인트 그래프 정의
├── astar_planner.py   # 웨이포인트 그래프 위의 A* 구현
├── visualizer.py      # matplotlib 인터랙티브 시각화
├── requirements.txt
└── README.md
```

각 모듈의 역할:

- `map_data.py`
  - `Waypoint`, `Obstacle`, `WaypointGraph`, `BuffetMap`, `DynamicObstacle` 데이터 클래스
  - `build_buffet_map()`: 정적 뷔페 맵을 생성. 손으로 정의한 웨이포인트와 장애물 목록으로부터 같은 행/열에서 장애물에 가로막히지 않는 인접 쌍을 자동 연결합니다.
  - 자유 좌표 검사 헬퍼: `is_inside_any_obstacle`, `is_in_map_bounds`, `is_line_clear` (0.1m 간격 샘플링).
  - 동적 장애물 기하 헬퍼: `circle_contains_point`, `circle_intersects_segment` (segment의 디스크 중심 최근접점을 [0,1] 클램프 + 거리 비교).
- `astar_planner.py`
  - `DEFAULT_ENTRY_RADIUS`: 자유 시작점에서 진입 웨이포인트까지 허용되는 최대 직선 거리(기본 2.5 m).
  - `plan_path(graph, start, goal, *, dynamic_obstacles=None) -> (path, cost)`: 웨이포인트 ID → 웨이포인트 ID 단일 소스 A*. 경로가 없으면 `(None, inf)`.
  - `plan_path_from_point(graph, start_xy, goal, obstacles, entry_radius=2.5, *, dynamic_obstacles=None) -> FreeStartPlan | None`: 자유 좌표에서 출발하는 반경 제한 multi-source A*. `entry_radius` 안에 line-of-sight 도달 가능 웨이포인트들만 진입 후보로 시드해 그 중 최적 진입점을 선택. 반경 안에 후보가 없으면 가장 가까운 reachable 웨이포인트로 fallback (`FreeStartPlan.entry_radius_fallback = True`).
  - 두 함수 모두 `dynamic_obstacles` 키워드 인자를 지원: 호출 시점의 차단된 웨이포인트/간선 집합을 미리 계산(`_compute_blockage`)해서 A* expansion에서 스킵.
  - 내부적으로 둘 다 `_astar_multi_source(graph, seeds_dict, goal, blockage)`를 호출하므로 단일/다중 소스 + 정적/동적 장애물 모두 동일 코드 경로를 사용.
- `visualizer.py`
  - `PathPlanningVisualizer`: 정적 요소(벽, 장애물, 웨이포인트, 간선)와 동적 요소(start 자유 좌표 마커 + 진입 반경 점선 원, goal 웨이포인트 마커, 동적 장애물 빨간 원, 계산된 경로)를 그리고 마우스/키 이벤트를 처리.
  - 좌클릭: 자유 좌표 start → goal 웨이포인트 (맵 밖/장애물 내부면 거부, goal만 스냅).
  - 우클릭: 클릭 위치에 동적 장애물(`DynamicObstacle`) 추가, start/goal이 이미 있으면 즉시 재계획.
  - `c` 키: 모든 동적 장애물 삭제 + 재계획. `r` 키: start/goal 선택만 리셋(동적 장애물 유지).
  - `entry_radius` fallback이 발생한 경우 타이틀에 `[radius fallback]` 표시 + 콘솔에도 경고 출력.
- `main.py`
  - CLI 파싱 → 맵 빌드 → 인터랙티브 또는 헤드리스 실행 분기. 헤드리스 모드는 다음 4개 섹션을 출력:
    1. `Waypoint -> Waypoint` 기본 시나리오
    2. `Free start point -> Waypoint` 시나리오
    3. `Dynamic obstacles (waypoint -> waypoint)` — baseline 비용/경로와 차단 후 경로를 나란히 비교
    4. `Dynamic obstacles (free start)` — 동적 장애물이 자유 시작점의 진입 웨이포인트를 막을 때 multi-source A*가 다른 진입점으로 우회하는지 검증

## 헤드리스 검증 결과

```
Loaded buffet test map: 27 waypoints, 37 edges, 8 obstacles.
Running headless A* scenarios on the buffet test map.

--- Waypoint -> Waypoint ---

[scenario] Entrance -> Kitchen
  cost = 17.00 m, 6 waypoints
  path: Entrance -> (7,1) -> (7,6) -> (7,10) -> B1-N -> Kitchen

[scenario] Kitchen -> A3-S
  cost = 22.00 m, 7 waypoints
  path: Kitchen -> (7,12) -> (13,12) -> (13,10) -> (13,6) -> (13,1) -> A3-S

[scenario] CS-Left -> Return
  cost = 25.00 m, 8 waypoints
  path: CS-Left -> A1-S -> (7,1) -> (7,6) -> (7,10) -> (7,12) -> (13,12) -> Return

[scenario] Entrance -> B2-N
  cost = 15.00 m, 5 waypoints
  path: Entrance -> (7,1) -> (7,6) -> (7,10) -> B2-N

[scenario] Return -> CS-Right
  cost = 14.00 m, 5 waypoints
  path: Return -> (18,12) -> (18,10) -> (18,6) -> CS-Right

--- Free start point -> Waypoint ---

[free-start] (10.40, 0.60) -> Kitchen
  entry waypoint = Entrance (distance 0.57 m, radius 2.5 m)
  total cost = 17.57 m (6 waypoints)
  path: (10.40,0.60) -> Entrance -> (7,1) -> (7,6) -> (7,10) -> B1-N -> Kitchen

[free-start] (8.50, 6.00) -> Return
  entry waypoint = A2-N/B2-S (distance 1.50 m, radius 2.5 m)
  total cost = 12.50 m (5 waypoints)
  path: (8.50,6.00) -> A2-N/B2-S -> (13,6) -> (13,10) -> B3-N -> Return

[free-start] (1.70, 11.40) -> A3-S
  entry waypoint = Kitchen (distance 2.38 m, radius 2.5 m)
  total cost = 24.38 m (7 waypoints)
  path: (1.70,11.40) -> Kitchen -> (7,12) -> (13,12) -> (13,10) -> (13,6) -> (13,1) -> A3-S

[free-start] (17.20, 9.80) -> Entrance
  entry waypoint = B3-N (distance 2.21 m, radius 2.5 m)
  total cost = 16.21 m (5 waypoints)
  path: (17.20,9.80) -> B3-N -> (13,10) -> (13,6) -> (13,1) -> Entrance

[free-start] (19.00, 10.20) -> Kitchen
  entry waypoint = (18,12) (distance 2.06 m, radius 2.5 m)
  total cost = 16.06 m (5 waypoints)
  path: (19.00,10.20) -> (18,12) -> Return -> (13,12) -> (7,12) -> Kitchen
```

**Waypoint → Waypoint**: 각 시나리오의 비용이 start/goal의 Manhattan 거리와 정확히 일치하므로, A*가 최적 경로를 반환하고 있음을 확인할 수 있습니다. 모든 경로가 직진과 직각 회전만으로 구성되어 의도한 주행 형태를 잘 만들어냄을 보여줍니다.

**Free start → Waypoint**: 모든 시나리오가 진입 반경 2.5 m 안의 웨이포인트로 들어간 뒤 격자를 따라 이동합니다. 특히 주목할 점:
- 시나리오 2 `(8.50, 6.00) → Return`은 가장 가까운 웨이포인트(`(7,6)`, 1.5 m) 대신 같은 거리의 `(10,6)`을 진입점으로 선택해 후속 통로 비용을 줄입니다 (총 12.50 m). 반경 안에서의 multi-source 최적화가 살아 있음을 보여줍니다.
- 시나리오 5 `(19.00, 10.20) → Kitchen`은 반경 제한 없이 multi-source A*만 돌리면 18 m 이상의 사선 한 줄이 나오던 케이스입니다. 이제는 `(18,12)`로 진입한 뒤 격자(`Return → (13,12) → (7,12) → Kitchen`)를 따라 16.06 m로 이동 — 동선이 통로 안에 머무르므로 사람과의 상호작용이 훨씬 예측 가능합니다.

## 본 프로젝트로 옮길 때 고려할 점

본 데모는 다음과 같은 부분이 단순화되어 있습니다. 실제 ROS 통합 시 검토가 필요합니다.

- 맵 정의가 코드에 하드코딩되어 있음 → 실제로는 YAML/JSON 등 외부 파일에서 로드 필요
- 웨이포인트 좌표가 정수 격자 → 실제로는 SLAM 맵 좌표계의 float 위치로 운용
- 동적 장애물은 quasi-static 스냅샷 + 재계획 모델 → 본 데모는 실제 시간 경과를 시뮬레이션하지 않음 (우클릭으로 추가/`c`로 삭제 시점에만 재계획). 실제 운용에서는 일정 주기(예: 0.5~1초)로 관제 서버가 plan을 호출하고, 미세한 회피는 DWB 등 Local Planner에 위임
- 단일 로봇 가정 → 멀티 로봇 운용 시 충돌/대기 정책 별도 설계 필요
- HQ Service에서 task와 함께 웨이포인트 시퀀스를 내려주는 인터페이스가 별도로 필요
- 자유 시작점의 line-of-sight 검사가 0.1m 샘플링 기반 → 실제 운용에서는 정확한 segment-vs-rectangle 교차 또는 inflated costmap 기반 판정으로 교체 권장
- 자유 시작점에서 진입 웨이포인트까지의 구간은 직선으로 가정 → 실제로는 Local Planner가 처리하는 구간이며, costmap의 동적 장애물에 따라 경로가 달라질 수 있음
- `entry_radius`(기본 2.5 m)는 데모 맵의 통로 폭/웨이포인트 간격에 맞춰 손으로 정한 값 → 실제 환경에서는 통로 폭, 로봇 반경, 웨이포인트 밀도, Local Planner의 회복 거리 등을 고려해 재조정 필요
