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
| 클릭 1회 | **START 자유 좌표 선택** — 클릭 위치를 그대로 시작점으로 사용. 웨이포인트로 스냅하지 않음. 시작점 주변 옅은 점선 원이 진입 반경(`entry_radius`, 기본 2.5 m)을 표시. 장애물 내부거나 맵 밖이면 거부 메시지 후 다시 클릭 대기 |
| 클릭 2회 | GOAL 웨이포인트 선택 (가장 가까운 웨이포인트로 스냅), A* 즉시 실행 후 경로 표시 |
| 클릭 3회 | 새로운 쿼리 시작 (이전 선택 초기화) |
| `r` | 현재 선택 리셋 |
| `q` | 종료 |

> 시작점만 자유롭고 목적지는 웨이포인트로 스냅합니다. 뷔페 운용에서 목적지는 입구·주방·퇴식구·테이블 앞 등 미리 정의된 서비스 위치로 한정되는 것이 자연스러운 반면, 시작점은 로봇의 임의 현재 자세이기 때문입니다.

## 테스트 맵 구성

20m × 15m 크기의 단순화된 뷔페 공간으로, 1셀 = 1m 입니다.

- **장애물 (8개)**: 뷔페 스테이션 6개(A1~A3, B1~B3) 2열 + 주방(Kitchen) + 퇴식구(Return) + 외벽
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
  - `Waypoint`, `Obstacle`, `WaypointGraph`, `BuffetMap` 데이터 클래스
  - `build_buffet_map()`: 정적 뷔페 맵을 생성. 손으로 정의한 웨이포인트와 장애물 목록으로부터 같은 행/열에서 장애물에 가로막히지 않는 인접 쌍을 자동 연결합니다.
  - 자유 좌표 검사 헬퍼: `is_inside_any_obstacle`, `is_in_map_bounds`, `is_line_clear` (0.1m 간격 샘플링).
- `astar_planner.py`
  - `DEFAULT_ENTRY_RADIUS`: 자유 시작점에서 진입 웨이포인트까지 허용되는 최대 직선 거리(기본 2.5 m).
  - `plan_path(graph, start, goal) -> (path, cost)`: 웨이포인트 ID → 웨이포인트 ID 단일 소스 A*. 경로가 없으면 `(None, inf)`.
  - `plan_path_from_point(graph, start_xy, goal, obstacles, entry_radius=2.5) -> FreeStartPlan | None`: 자유 좌표에서 출발하는 반경 제한 multi-source A*. `entry_radius` 안에 line-of-sight 도달 가능 웨이포인트들만 진입 후보로 시드해 그 중 최적 진입점을 선택. 반경 안에 후보가 없으면 가장 가까운 reachable 웨이포인트로 fallback (`FreeStartPlan.entry_radius_fallback = True`).
  - 내부적으로 둘 다 `_astar_multi_source(graph, seeds_dict, goal)`를 호출하므로 단일/다중 소스 모두 동일 코드 경로를 사용.
- `visualizer.py`
  - `PathPlanningVisualizer`: 정적 요소(벽, 장애물, 웨이포인트, 간선)와 동적 요소(start 자유 좌표 마커 + 진입 반경 점선 원, goal 웨이포인트 마커, 계산된 경로)를 그리고 클릭/키 이벤트를 처리.
  - 첫 클릭은 자유 좌표로 처리(맵 밖/장애물 내부면 거부), 두 번째 클릭만 가장 가까운 웨이포인트로 스냅.
  - `entry_radius` fallback이 발생한 경우 타이틀에 `[radius fallback]` 표시 + 콘솔에도 경고 출력.
- `main.py`
  - CLI 파싱 → 맵 빌드 → 인터랙티브 또는 헤드리스 실행 분기. 헤드리스 모드는 `Waypoint -> Waypoint`와 `Free start point -> Waypoint` 두 섹션을 모두 출력.

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
- 동적 장애물·local planner 미반영 → DWB 등 Local Planner와 결합하여 회피 처리
- 단일 로봇 가정 → 멀티 로봇 운용 시 충돌/대기 정책 별도 설계 필요
- HQ Service에서 task와 함께 웨이포인트 시퀀스를 내려주는 인터페이스가 별도로 필요
- 자유 시작점의 line-of-sight 검사가 0.1m 샘플링 기반 → 실제 운용에서는 정확한 segment-vs-rectangle 교차 또는 inflated costmap 기반 판정으로 교체 권장
- 자유 시작점에서 진입 웨이포인트까지의 구간은 직선으로 가정 → 실제로는 Local Planner가 처리하는 구간이며, costmap의 동적 장애물에 따라 경로가 달라질 수 있음
- `entry_radius`(기본 2.5 m)는 데모 맵의 통로 폭/웨이포인트 간격에 맞춰 손으로 정한 값 → 실제 환경에서는 통로 폭, 로봇 반경, 웨이포인트 밀도, Local Planner의 회복 거리 등을 고려해 재조정 필요
