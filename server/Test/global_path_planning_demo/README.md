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

# 헤드리스 모드 (창 없이 5개 시나리오 자동 실행)
python3 main.py --headless
```

### 인터랙티브 조작

| 입력 | 동작 |
|---|---|
| 클릭 1회 | START 웨이포인트 선택 (가장 가까운 웨이포인트로 스냅) |
| 클릭 2회 | GOAL 웨이포인트 선택, A* 즉시 실행 후 경로 표시 |
| 클릭 3회 | 새로운 쿼리 시작 (이전 선택 초기화) |
| `r` | 현재 선택 리셋 |
| `q` | 종료 |

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
- `astar_planner.py`
  - `plan_path(graph, start, goal) -> (path, cost)`: 웨이포인트 ID 시퀀스와 총 거리를 반환. 경로가 없으면 `(None, inf)`.
- `visualizer.py`
  - `PathPlanningVisualizer`: 정적 요소(벽, 장애물, 웨이포인트, 간선)와 동적 요소(start/goal 마커, 계산된 경로)를 그리고 클릭/키 이벤트를 처리.
- `main.py`
  - CLI 파싱 → 맵 빌드 → 인터랙티브 또는 헤드리스 실행 분기.

## 헤드리스 검증 결과

```
Loaded buffet test map: 27 waypoints, 37 edges, 8 obstacles.
Running headless A* scenarios on the buffet test map.

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
```

각 시나리오의 비용이 start/goal의 Manhattan 거리와 정확히 일치하므로, A*가 최적 경로를 반환하고 있음을 확인할 수 있습니다. 또한 모든 경로가 직진과 직각 회전만으로 구성되어 본 데모가 의도한 주행 형태를 잘 만들어냄을 보여줍니다.

## 본 프로젝트로 옮길 때 고려할 점

본 데모는 다음과 같은 부분이 단순화되어 있습니다. 실제 ROS 통합 시 검토가 필요합니다.

- 맵 정의가 코드에 하드코딩되어 있음 → 실제로는 YAML/JSON 등 외부 파일에서 로드 필요
- 웨이포인트 좌표가 정수 격자 → 실제로는 SLAM 맵 좌표계의 float 위치로 운용
- 동적 장애물·local planner 미반영 → DWB 등 Local Planner와 결합하여 회피 처리
- 단일 로봇 가정 → 멀티 로봇 운용 시 충돌/대기 정책 별도 설계 필요
- HQ Service에서 task와 함께 웨이포인트 시퀀스를 내려주는 인터페이스가 별도로 필요
