# Waypoint-based A* Global Path Planner Demo

뷔페 환경에서 동작하는 pinky-pro 로봇용 **웨이포인트 기반 Global Path Planning** 데모입니다. Gazebo 시뮬레이션(`--sim`) 또는 실물 핑키(`--real`)에 연결하여, monitor 화면에서 클릭 주행과 웨이포인트/로봇 포즈 편집을 수행합니다.

실제 운용 스케일은 **약 2.0 m × 1.6 m**, pinky-pro는 **12 × 12 cm 정사각 footprint**(`pinky_navigation/params/nav2_params.yaml` 기준) 입니다. 즉 맵 가로세로가 로봇 폭의 약 13~16배에 불과한 매우 좁은 환경입니다. 본 데모의 두 샘플 맵 모두 이 스케일을 그대로 반영합니다:

- [maps/buffet_sim.yaml](maps/buffet_sim.yaml) + [maps/map4.pgm](maps/map4.pgm) — 실제 SLAM 스캔(`device/pinky_pro_robot/map4.pgm`의 사본). 여러 뷔페 스테이션이 있는 복잡한 구조. **기본 맵**.
- [maps/buffet_realistic.yaml](maps/buffet_realistic.yaml) + [maps/buffet_realistic.pgm](maps/buffet_realistic.pgm) — 같은 스케일의 합성 맵. 서빙 스테이션 1개만 있는 ring 구조로, 알고리즘 자체 검증이 용이한 대조군.

## 배경

현재 프로젝트는 격자 형태의 뷔페 공간에서 작은 모바일 로봇(pinky pro) 여러 대로 서비스를 제공하는 것을 목표로 합니다. 사람이 많이 다니는 공간이라 안전한 주행이 필요하고, 격자 구조의 통로를 따라 **예측 가능한 직진 + 직각 회전** 위주의 경로가 요구됩니다.

이를 위해 Nav2의 기본 Global Planner인 NavFn 대신, 통로 교차점과 주요 지점(입구, 충전소, 주방, 퇴식구, 테이블 앞)에 미리 찍어둔 웨이포인트 그래프 위에서 A*로 최단 경로를 탐색하는 방식을 검증합니다. 본 데모는 그 방식이 실제로 원하는 형태의 경로를 만들어내는지 시각적으로 보여주는 것이 목적입니다.

## 동작 환경

- Ubuntu 24.04
- Python 3.12+
- matplotlib 3.7 이상 (인터랙티브 모드)
- numpy 1.24 이상 (점유 격자 처리)
- PyYAML 6.0 이상 (맵 파일 로딩)

코드 스타일은 PEP 8을 따릅니다.

## 설치

```bash
# 시스템 패키지로 설치하는 경우 (권장)
sudo apt install python3-matplotlib python3-numpy python3-yaml

# 또는 venv + pip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 파일 구조

```
global_path_planning_demo/
├── start.sh              # 데모 스택 시작 (--sim / --real)
├── kill.sh               # 데모 스택 종료
├── start_pinky.sh        # 핑키 로봇에서 driver + Nav2 기동
├── kill_pinky.sh         # 핑키 프로세스 종료
├── monitor.py            # 시각화 + 클릭 네비게이션 + 편집 모드 (ROS2 노드)
├── nav2_bridge.py        # CLI 목표 전달 (A* 경로 → FollowPath)
├── astar_planner.py      # A* 경로 계획 알고리즘
├── map_data.py           # 맵 로딩 / 편집 / 저장 (YAML ↔ BuffetMap)
├── test_drive.sh         # 자동 연속 주행 테스트
├── requirements.txt      # Python 의존성
└── maps/
    ├── buffet_sim.yaml   # 기본 맵 (실제 SLAM 스캔)
    ├── map4.pgm
    ├── buffet_realistic.yaml  # 합성 ring 구조 맵 (대조군)
    └── buffet_realistic.pgm
```

## 실행

### 시뮬레이션 모드 (Gazebo)

```bash
cd server/Test/global_path_planning_demo
bash start.sh --sim
```

`start.sh --sim`이 아래를 순서대로 실행합니다:
1. Gazebo (`pinky_gz_sim`) 기동 → `/scan` 토픽 대기
2. Nav2 (`gz_bringup_launch.xml`, `use_sim_time=true`) 기동 → `/follow_path` 액션 대기
3. `monitor.py` 기동 → matplotlib 시각화 창 표시

종료:
```bash
bash kill.sh
```

### Monitor 조작

#### 일반 모드

| 입력 | 동작 |
|---|---|
| **좌클릭** | 가장 가까운 웨이포인트로 스냅 → A* 경로 계획 → `FollowPath` 전송 |
| `e` | 편집 모드 진입 |

CLI로도 목표를 보낼 수 있습니다:
```bash
cd server/Test/global_path_planning_demo
ROS_DOMAIN_ID=41 DEMO_USE_SIM_TIME=true python3 nav2_bridge.py --goal Kitchen
```

#### 편집 모드 (`e`로 진입/퇴장)

편집 모드에 진입하면 "EDIT MODE" 배너가 표시되고, 모든 웨이포인트에 오렌지 드래그 핸들이 나타납니다.

| 입력 | 동작 |
|---|---|
| **드래그** | 웨이포인트 위치 이동 (기존 간선 토폴로지 유지) |
| `p` | 로봇 시작 포즈 추가 (클릭 → 위치 설정, 드래그 → yaw 방향 설정) |
| `d` | 마지막 로봇 포즈 삭제 |
| `s` | 변경사항을 맵 YAML 파일에 저장 |
| `e` | 편집 모드 종료 (간선 자동 재건) |
| `Escape` | 포즈 편집 취소 |

편집 종료 시 간선은 **RNG(Relative Neighborhood Graph)** 방식으로 자동 재건됩니다:
- 두 웨이포인트 사이에 장애물이 없고, 더 가까운 중간 웨이포인트가 없으면 연결
- 그래프가 분리되면 컴포넌트 간 최단 가시선으로 자동 브리지

#### 자동 주행 테스트

```bash
# 기본 시퀀스 (Kitchen → Charging → Return → Entrance → ...)
bash test_drive.sh

# 커스텀 시퀀스, 3회 반복
bash test_drive.sh --loops 3 Kitchen Charging Return
```

## 실물 핑키(real 모드)에서 실행

실제 pinky-pro 로봇에 연결해 동일한 monitor/클릭 주행을 사용하는 절차입니다. Gazebo는 쓰지 않으며, **Nav2와 로봇 driver는 핑키의 Raspberry Pi 위에서 직접 돌리고, global path planner(monitor.py)만 노트북에서** 실행합니다. 두 기계는 같은 `ROS_DOMAIN_ID`(기본 **41**)를 공유해서 ROS 2 discovery로 연결됩니다.

### 구성

| 위치 | 역할 | 스크립트 |
|---|---|---|
| **핑키** (SSH) | driver (LiDAR·모터·odom·TF) + Nav2 | `start_pinky.sh` / `kill_pinky.sh` |
| **노트북** | monitor(시각화 + 클릭 네비) + `nav2_bridge.py` | `start.sh --real` / `kill.sh` |

### 로봇 목록

로봇별 hostname, AP SSID, IP 주소, SSH 비밀번호는 팀 내부 문서를 참조하세요.

### 전제 조건

- 핑키에 `pinky_bringup`, `pinky_navigation`, `sllidar_ros2` 패키지가 ROS overlay로 빌드돼 있어야 합니다. 기본 오버레이 경로는 `~/pinky_pro/install/setup.bash`이며, 다르면 `PINKY_OVERLAY=/path/to/install/setup.bash`로 덮어쓸 수 있습니다.
- SSH 접속: 핑키 AP 직접 또는 교실 WiFi 경유. IP/비밀번호는 팀 내부 문서 참조.
- `ROS_DOMAIN_ID`는 로봇별로 다르게 설정 (멀티로봇 시 도메인 분리):
  - 단일 로봇: 기본 41
  - 멀티 로봇: 핑키1=41, 핑키2=42 등
- 두 기계가 같은 서브넷에 있고 UDP multicast가 막히지 않아야 합니다(ROS 2 Fast DDS 기본 동작).

### 최초 1회: 핑키로 파일 전송

노트북에서 (레포 루트 기준):

```bash
# 1) 스크립트 두 개
scp server/Test/global_path_planning_demo/start_pinky.sh \
    server/Test/global_path_planning_demo/kill_pinky.sh \
    pinky@192.168.4.1:~/

# 2) 맵 파일 (Nav2 map_server가 핑키에서 로드)
scp install/pinky_navigation/share/pinky_navigation/map/map4.yaml \
    install/pinky_navigation/share/pinky_navigation/map/map4.pgm \
    pinky@192.168.4.1:~/

# 3) 튜닝된 Nav2 파라미터 (inflation, RPP cost scaling 등 반영된 버전)
scp device/pinky_pro_robot/src/pinky_navigation/params/nav2_params.yaml \
    pinky@192.168.4.1:~/

# 4) 실행 권한
ssh pinky@192.168.4.1 'chmod +x ~/start_pinky.sh ~/kill_pinky.sh'
```

스크립트나 파라미터를 수정했다면 해당 파일만 다시 `scp`로 덮어쓰면 됩니다.

### 매번 실행하는 절차

**① 핑키에서 driver + Nav2 기동 (SSH 세션)**

```bash
ssh pinky@192.168.4.1
# 핑키 쉘에서:
bash ~/start_pinky.sh
# → ROS_DOMAIN_ID=41, 오버레이 자동 감지
# → pinky_bringup 실행 → /scan 10 Hz 확인
# → pinky_navigation Nav2 실행 → /follow_path 확인
# → "ready" 메시지가 뜨면 완료
```

옵션:
- `--map ~/다른맵.yaml`: 기본 `~/map4.yaml` 대신 다른 맵 사용
- `--params ~/다른params.yaml`: 기본 `~/nav2_params.yaml`이 없거나 다른 파일을 쓰고 싶을 때
- `--no-driver`: driver는 이미 돌고 있고 Nav2만 재기동할 때

로그는 `~/.pinky_demo/{driver,nav2}.log`, PID는 같은 경로에 저장됩니다. SSH를 끊어도 `setsid`로 세션 분리해서 프로세스는 계속 동작합니다.

**② 노트북에서 monitor 기동**

```bash
cd server/Test/global_path_planning_demo
bash start.sh --real
```

`start.sh --real`은:
- `ROS_DOMAIN_ID=41`, `DEMO_USE_SIM_TIME=false` 환경변수 export
- `.run/mode=real` 기록 (kill.sh가 읽어서 원격 Nav2를 건드리지 않도록)
- 60 초 내에 `/follow_path` 액션이 discovery로 잡히는지 확인. 안 잡히면 **도메인/네트워크 문제 안내 메시지**와 함께 실패
- 성공 시 `monitor.py`만 로컬에서 기동 (Gazebo·Nav2 생략)

**③ 초기 pose 정렬 (중요)**

`nav2_params.yaml`의 `set_initial_pose: true`, `initial_pose: [0, 0, 0]`에 따라 AMCL은 기동 직후 **map 원점 근처(≈ Charging 웨이포인트)** 로 자신을 가정합니다. 실제 로봇이 그 위치에 있지 않다면 localization이 어긋난 채 주행이 시작돼 벽 충돌로 이어집니다.

세 가지 방식 중 하나로 맞추세요:
- 로봇을 물리적으로 Charging 지점(`maps/buffet_sim.yaml`의 `x=0.05, y=+0.05, yaw=180°`)에 두고 기동
- 핑키에 연결된 화면/원격 RViz에서 "2D Pose Estimate" 버튼으로 설정
- 노트북에서 터미널로 직접 publish:
  ```bash
  ROS_DOMAIN_ID=41 ros2 topic pub -1 /initialpose \
    geometry_msgs/msg/PoseWithCovarianceStamped \
    "{header: {frame_id: 'map'}, pose: {pose: {position: {x: 0.05, y: 0.05}, orientation: {z: 1.0, w: 0.0}}}}"
  ```

monitor 창에서 로봇 아이콘이 실제 로봇과 같은 위치에 찍혔는지 눈으로 확인한 뒤 클릭 주행을 시도하세요.

**④ 주행**

monitor 창의 웨이포인트를 클릭 → 가장 가까운 웨이포인트로 스냅 → 경로 계획 → `FollowPath` 전송 → 근접 preempt 후 Arrived. 여러 번 클릭해서 연속 주행이 정상인지 확인합니다.

CLI로도 goal을 보낼 수 있습니다:
```bash
cd server/Test/global_path_planning_demo
ROS_DOMAIN_ID=41 DEMO_USE_SIM_TIME=false python3 nav2_bridge.py --goal Kitchen
```

### 종료 순서

**반드시 노트북 → 핑키 순서**로 정리합니다(원격 Nav2가 먼저 죽으면 monitor 쪽 콜백이 꼬일 수 있음).

```bash
# 1) 노트북
bash kill.sh
# → .run/mode=real을 읽어 monitor만 정리, 핑키의 Nav2는 건드리지 않음

# 2) 핑키
ssh pinky@192.168.4.1 'bash ~/kill_pinky.sh'
# → Nav2 + driver 모두 정리
```

### 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| `start.sh --real`에서 `/follow_path action` 60 초 타임아웃 | 도메인 ID 불일치 또는 네트워크 분리 | 양쪽 터미널에서 `ROS_DOMAIN_ID=41`인지 확인, 노트북이 pinky AP에 붙어 있는지 확인 |
| monitor의 로봇 아이콘이 움직이지 않음 | AMCL이 publish 안 하거나 TF 끊김 | 핑키에서 `ros2 topic hz /amcl_pose`, `ros2 run tf2_ros tf2_echo map base_footprint` 확인 |
| `start_pinky.sh`에서 `/scan`이 30 초 안에 안 잡힘 | LiDAR 연결/권한 문제 | `~/.pinky_demo/driver.log` 확인, `/dev/ttyAMA0` 권한, LiDAR 전원 |
| 주행 중 벽 박음 → map vs Gazebo 위치 어긋남 | 휠 slip으로 odom drift → AMCL 분산 | Nav2 재기동 + 초기 pose 재설정 (`③` 참조). 재현되면 `buffet_sim.yaml`의 `inflation_radius` 또는 `nav2_params.yaml`의 costmap `inflation_radius` 상향 |
| `Permission denied (publickey,password)` | SSH 키 미설정 | `ssh-copy-id pinky@192.168.4.1`로 키 등록(한 번만), 또는 매번 암호 입력 |

## 맵 파일 (YAML)

맵은 외부 YAML 파일에서 로드합니다. **두 가지 형식**을 모두 지원하며 `load_buffet_map()`이 YAML 내용을 보고 자동 감지합니다.

| 형식 | 감지 키 | 좌표계 | 장애물 표현 | 용도 |
|---|---|---|---|---|
| **rect** | `obstacles:` | 정수 셀 (1셀 = 1 m) | 사각형 리스트 | 알고리즘 테스트용 큰 공간, 빠른 프로토타이핑 |
| **Nav2** | `image:` | 실수 미터 + 픽셀 | 점유 격자 (PGM) | **실제 SLAM 출력, 운영 환경** — realistic 맵은 이 포맷만 제공 |

실제 운용 맵이 전부 SLAM 출력(2 m × 1.6 m 수준의 작은 공간)이기 때문에 본 데모에서는 **Nav2 형식의 샘플만 제공**합니다. rect 형식 로더는 유지되어 있으므로, 필요하면 사용자가 손으로 rect YAML을 작성해 알고리즘을 테스트할 수 있습니다. 두 형식 모두 동일한 `BuffetMap` 객체로 로드되어 플래너/시각화는 차이를 보지 못합니다 (`StaticEnv` 추상화).

### Rect 형식 스키마 (옵션, 손-작성용)

```yaml
name: "Map display name"          # 자유 형식 (선택)

# Optional per-map defaults (all fields optional)
defaults:
  dynamic_radius: 0.12            # m, default dynamic-obs disc radius
  inflation_radius: 0.09          # m, static-obstacle inflation

size:
  width: 20                       # 정수, > 0
  height: 15                      # 정수, > 0

obstacles:                        # 정적 사각 장애물 리스트
  - {name: "Table A", x_min: 2, y_min: 2, x_max: 6, y_max: 5}
  # x_min..x_max, y_min..y_max는 닫힌 구간 (포함). 모두 정수, 맵 내부.

waypoints:                        # 그래프 노드 리스트, 인덱스가 곧 wp_id
  - {x: 1, y: 1, label: "CS-Left"}
  - {x: 7, y: 1}                  # label 생략 == 이름 없는 교차점
  # 좌표는 정수 또는 실수, 맵 내부, 어느 장애물 안에도 들어가면 안 됨.
  # 좌표/라벨 중복 금지. yaw(도)는 선택.
```

Rect 포맷은 1 셀 = 1 m 해상도라 2 m × 1.6 m 실제 맵에는 너무 거칠지만, 큰 가상 공간에서 알고리즘 회귀 테스트 시에는 유용합니다.

### Nav2 형식 (PGM + 메타데이터 YAML)

SLAM 도구(slam_toolbox / cartographer)가 출력하는 표준 형식이고, Nav2 map_server가 그대로 소비하는 형식입니다. 본 데모는 거기에 `waypoints:` (그리고 선택적으로 `name:`) 라는 추가 키를 얹어서 글로벌 플래너용 의미 위치를 정의합니다. **Nav2 map_server는 알지 못하는 키를 무시**하기 때문에 동일한 한 파일을 Nav2 코스트맵과 본 데모(또는 본 프로젝트의 커스텀 글로벌 플래너) 양쪽이 함께 소비할 수 있습니다.

```yaml
# Nav2 map_server 표준 키
image: my_map.pgm                  # 같은 디렉토리 기준 상대 경로
mode: trinary                      # trinary | scale | raw
resolution: 0.05                   # m / pixel
origin: [-0.285, -1.241, 0]        # 이미지 좌하단의 월드 [x, y, yaw]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196

# 본 데모/HQ Service만 사용하는 확장 키
name: "Buffet floor 1"
defaults:                          # per-map 디폴트 (선택)
  dynamic_radius: 0.12             # m, 동적 장애물 디스크 반경
  inflation_radius: 0.09           # m, 정적 장애물 inflation (pinky-pro inscribed + padding)
waypoints:                         # 월드 좌표(미터), 정수/실수 모두 OK
  - {x: 0.50, y: -0.80, label: "Entrance"}
  - {x: 1.20, y: -0.30, label: "Table-1", yaw: 90}
  - {x: 0.80, y:  0.00}             # label 생략 == 교차점
```

PGM 처리 규칙 (Nav2 트리너리 모드 기준):

- pixel_value = 0 → 점유 (벽)
- pixel_value = 255 → free
- 그 외 (예: 205 unknown gray) → **본 데모는 안전상 점유로 간주**
- 맵 밖 영역도 점유로 간주 (암묵적 outer wall)
- 픽셀 → 월드: `x = origin_x + col * resolution`, `y = origin_y + row * resolution` (PGM의 row 0은 이미지 상단이지만 로딩 시 `flipud`로 뒤집어 row 0 = 월드 하단으로 정규화)

샘플:
- [maps/buffet_sim.yaml](maps/buffet_sim.yaml) + [maps/map4.pgm](maps/map4.pgm) — **기본 맵**, 실제 SLAM 스캔(`device/pinky_pro_robot/map4.pgm`에서 복사). 40×32 픽셀, 12 웨이포인트, 여러 뷔페 스테이션 + inflation 0.09 m.
- [maps/buffet_realistic.yaml](maps/buffet_realistic.yaml) + [maps/buffet_realistic.pgm](maps/buffet_realistic.pgm) — 같은 스케일의 합성 ring 맵 (단순 대조군), 40×32 픽셀, 8 웨이포인트, 중앙 서빙 스테이션 1개.

### 맵별 디폴트 (`defaults:` 블록)

두 포맷 모두 **선택적 `defaults:` 블록**을 지원합니다. 맵별 적절한 파라미터를 맵 자체에 선언해서, 운영자가 매번 CLI/코드에서 값을 넘기지 않아도 되게 합니다.

- `dynamic_radius` (m): 동적 장애물 디스크의 기본 반경. 실제 다른 pinky-pro 반경 + 마진 (기본 0.12 m).
- `inflation_radius` (m): 정적 장애물을 얼마나 부풀려 ego 로봇의 안전 마진을 확보할지. pinky-pro의 `Nav2 inscribed(0.06) + padding(0.03) = 0.09 m` 가 기본값이자 권장값.

생략하면 모듈 단위 디폴트(`DEFAULT_DYNAMIC_RADIUS`, `DEFAULT_INFLATION_RADIUS`)로 폴백합니다. `BuffetMap.defaults`를 통해 플래너/시각화가 이 값을 읽습니다.

### 정적 장애물 inflation

`inflation_radius > 0`이면 로드 시점에 정적 장애물이 로봇 반경만큼 부풀려집니다. 이렇게 하면 "맵에는 통과 가능해 보이지만 실제로는 로봇 본체가 끼이는" 버그가 사라집니다. pinky-pro는 Nav2 설정 기준 **0.09 m** 가 정확한 값입니다 (footprint inscribed 0.06 + padding 0.03, `nav2_params.yaml` 기준).

- **RectangleEnv**: 각 사각형의 시각적 footprint에서 점까지 거리가 `inflation_radius` 이하면 점유로 판정. 점→사각형 거리는 축별 max 차이로 계산(모서리는 Euclidean). 시각화에는 원본 사각형과 `inflation_radius` 만큼 확장된 반투명 빨간색 밴드가 함께 그려집니다.
- **OccupancyGridEnv**: 로드 시점에 `ceil(inflation_radius/resolution)` 픽셀 반경의 원형 커널로 점유 마스크를 **disc dilation** 합니다(numpy만 사용, scipy 불필요). 시각화에는 원본 PGM이 배경으로 깔리고, 팽창된 영역(원본이 아닌 픽셀 중 점유가 된 것)이 반투명 빨간색 오버레이로 표시되어 "실제 벽"과 "로봇 반경이 만든 안전 영역"을 구분할 수 있습니다.

두 구현 모두 `StaticEnv` 인터페이스 뒤에 숨어 있어 플래너와 시각화는 inflation 사용 여부를 알 필요가 없습니다.

### 검증

`load_buffet_map()`은 다음을 자동 검증하고, 문제가 있으면 한 줄짜리 명확한 `ValueError`를 던집니다.

- 두 형식 모두: 누락된 최상위 키, 잘못된 타입, 좌표/라벨 중복, 웨이포인트가 정적 장애물 내부, 웨이포인트가 맵 밖, 빈 웨이포인트 리스트, `defaults:`의 알 수 없는 키, 음수/0 값
- rect 형식: 장애물 좌표 반전, 장애물이 맵 밖, 빈 이름
- Nav2 형식: PGM 파일 미존재, 알 수 없는 모드, `negate ∉ {0, 1}`, `resolution <= 0`, `waypoints:` 키 누락

에러 메시지 예시: `map: waypoints[5] (3,3) lies inside a static obstacle`, `PGM /path/to/x.pgm: expected P5 magic, got b'P3'`.

### pinky-pro 실제 치수

실제 로봇 파라미터는 `device/pinky_pro_robot/src/pinky_description/urdf/pinky.urdf.xacro`와 `pinky_navigation/params/nav2_params.yaml`에서 가져왔습니다:

| 항목 | 값 | 출처 |
|---|---|---|
| base_link inertia box | 0.09 × 0.08 × 0.086 m | URDF |
| Nav2 footprint | 12 × 12 cm 정사각 | `nav2_params.yaml` |
| footprint half-extent | 0.06 m | 위 |
| footprint_padding | 0.03 m | 위 |
| Inscribed radius | **0.06 m** | half-extent |
| Circumscribed radius | ~0.085 m | √2 × half-extent |
| Inscribed + padding | **0.09 m** | 본 데모가 사용하는 값 |

본 데모의 `DEFAULT_INFLATION_RADIUS = 0.09 m`는 Nav2의 inscribed radius + padding과 정확히 일치합니다. 이 값을 사용하면 글로벌 플래너가 찾은 경로는 Nav2의 local costmap이 통과 가능하다고 판정한 모든 구간을 통과할 수 있습니다. 더 보수적으로 가려면 circumscribed 기반 0.115 m을 쓸 수 있지만, 본 데모의 2 m × 1.6 m 공간에서는 너무 엄격해서 대부분의 통로가 사라집니다.

### SLAM 맵 구성 (실제 운용 환경)

[maps/buffet_sim.yaml](maps/buffet_sim.yaml) + [maps/map4.pgm](maps/map4.pgm)는 `device/pinky_pro_robot/map4.pgm`의 직접 사본으로, 실제 Gazebo 시뮬레이션/물리 스캔 결과물입니다:

- **해상도**: 0.05 m/px (40 × 32 px, slam_toolbox 표준 출력)
- **Origin**: `(-0.285, -1.241, 0)` — 실제 SLAM이 세팅한 world frame
- **World extent**: x ∈ [-0.285, 1.715], y ∈ [-1.241, 0.359] → 2.0 × 1.6 m
- **Topology** (0.09 m inflation 적용 후):
  - 좌측 수직 통로 (x ≈ 0, y ∈ [-0.95, +0.09])
  - 우측 수직 통로 (x ≈ 1.5, 같은 y 범위)
  - 상단 수평 통로 (y ≈ +0.03, x ∈ [0, 1.5])
  - **중간/하단 수평 연결 없음** — 방 중앙의 뷔페 스테이션들이 좌↔우 가로 이동을 모두 차단
- **9개 웨이포인트** — "U자형" 구조 (좌 수직 4 + 상단 수평 1 + 우 수직 4):
  - `Entrance` (0.00, -0.90): 좌측 하단 (진입구 가정)
  - `Charging` (0.00, +0.05): 좌측 상단
  - `Kitchen` (1.50, +0.05): 우측 상단
  - `Return` (1.50, -0.90): 우측 하단
  - + 명명되지 않은 중간 junction 5개
- **8개 edge** — U자 외곽선
- `Entrance → Kitchen` 기본 경로: **2.45 m** (좌측 수직 → 상단 수평, 우회 불가)

이 U자 구조는 **실제 운용에서 멀티 로봇 policy의 핵심 제약**을 드러냅니다: 방 중앙은 지나갈 수 없으므로 모든 좌↔우 이동은 상단 통로를 거쳐야 하고, 통로가 한 로봇에 의해 막히면 맵이 두 개의 고립된 영역으로 나뉩니다. 이 사실은 본 데모에서 `Entrance → Return`로 가는 동안 좌측 통로 중간에 `R1@(0.0, -0.20)`을 놓으면 `NO PATH FOUND`가 되는 것으로 직접 검증됩니다.

### Realistic 맵 구성 (합성, ring 구조)

2.0 m × 1.6 m 크기의 합성 공간으로 [maps/buffet_realistic.yaml](maps/buffet_realistic.yaml) + [maps/buffet_realistic.pgm](maps/buffet_realistic.pgm)에 정의됩니다. 중앙에 단일 서빙 스테이션을 배치해 알고리즘 검증을 단순화한 버전입니다.

- **해상도**: 0.05 m/px (40 × 32 px, SLAM 출력 해상도)
- **정적 장애물**: 서빙 스테이션 1개 (0.40 × 0.20 m, 중앙 배치) + 외벽 1 픽셀
- **Inflation**: 0.20 m (pinky-pro 반경 0.15 m + 0.05 m 안전 버퍼)
- **웨이포인트** (8개): 서빙 스테이션을 둘러싸는 ring 구조
  - `Charging` (0.40, 0.35): 남서 코너
  - `Return` (0.40, 1.25): 북서 코너
  - `Kitchen` (1.00, 1.25): 상단 중앙 (주방 픽업)
  - `Table` (1.60, 1.25): 북동 코너
  - + 명명되지 않은 교차점 4개 (양쪽 중앙 열)
- **간선 (8개)**: 서빙 스테이션을 도는 외곽 ring. 중앙 수직 간선은 스테이션 inflation으로 자동 차단.

이 ring 구조에서 "반대편 웨이포인트로 가는 경로"는 항상 링의 절반 (~2.1 m)이라 A*는 항상 유효하지만, 중간 간선이 동적 장애물로 차단되면 큰 우회를 발생시킵니다 (예: Kitchen↔Table 0.6 m 간선이 막히면 반대편으로 우회해서 3.60 m).

### Default 맵 구성 (알고리즘 테스트용 큰 공간)

20 m × 15 m 크기의 가상 큰 뷔페 홀로, 1셀 = 1 m 입니다.

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

### 자유 시작점 처리 (multi-source A* + 진입 페널티)

자유 좌표 `(sx, sy)`에서 출발할 때는 단순히 가장 가까운 웨이포인트로 스냅하지 않고, **진입 페널티가 있는 다중 시드 A***로 진입 웨이포인트를 최적화합니다.

1. `(sx, sy)`가 정적/동적 장애물 내부면 거부.
2. `(sx, sy)`에서 직선 시야(line-of-sight, 0.1 m 간격 샘플링)로 도달 가능한 **모든** 웨이포인트를 진입 후보로 수집.
3. 각 후보에 `entry_distance × entry_penalty_factor` 를 **초기 g-score**로 부여 (기본 factor = **1.2**).
4. 위 시드들을 모두 open list에 넣은 상태로 A*를 한 번만 실행 → A*가 `(entry × 1.2) + corridor`가 최소인 진입점을 선택.
5. 결과는 **실제 거리**(페널티 없는 값)로 리포트: `FreeStartPlan(entry_distance, waypoint_cost, ...)`.

#### 진입 페널티(`entry_penalty_factor`)의 역할

**물리적 해석**: entry segment 1 m는 corridor edge 1 m보다 약간 더 비쌉니다. 이유:

- Entry segment는 **free-space 직선** (corridor edge는 축 정렬된 known-safe 경로)
- SLAM localization 오차에 대한 안전 마진이 corridor 대비 약간 약함
- 경로 예측성 측면에서도 corridor 쪽이 더 명확함

`entry_penalty_factor = 1.2`는 "entry 1 m는 corridor 1.2 m와 동일한 비용"이라는 soft bias입니다. Hard constraint가 아니라서, corridor savings가 충분히 크면 여전히 긴 entry가 선택됩니다.

**공식**: far-away seed가 선택되려면 `corridor_savings > 0.2 × entry_difference` 가 성립해야 함.

#### 두 대비 사례 (같은 맵에서)

**사례 1: U턴 방지** — start `(1.27, -0.56)`, goal `Charging`

| 진입 후보 | entry (m) | corridor (m) | total + 페널티 | 선택 |
|---|---|---|---|---|
| `(1.5, -0.566)` | 0.23 | 2.12 | 0.276 + 2.12 = 2.40 | |
| **Table-N** | **0.43** | **1.46** | 0.516 + 1.46 = **1.98** | **✓** |

차이: corridor savings가 0.66 m, entry 차이 × 0.2 = 0.04 m. 이득이 페널티를 크게 상회하므로 **Table-N (더 먼 진입점) 선택**이 옳음. 실제 경로 1.89 m (0.46 m 단축).

**사례 2: 긴 대각선 억제** — start `(0.62, -0.70)`, goal `Kitchen`

| 진입 후보 | entry (m) | corridor (m) | total + 페널티 | 선택 |
|---|---|---|---|---|
| `(1.5, -0.566)` | 0.89 | 0.62 | 1.068 + 0.62 = 1.69 | |
| **Table-N** | **0.26** | **1.28** | 0.312 + 1.28 = **1.59** | **✓** |

차이: corridor savings가 0.66 m, entry 차이 × 0.2 = 0.126 m. Corridor 이득이 있지만 **겨우 0.02 m** (1.3%)만 유의미. 페널티가 균형을 뒤집어 **Table-N (가까운 진입점) 선택**. 경로 1.53 m (0.02 m 손해, 대신 긴 diagonal 제거).

**요약**:
- corridor savings가 **충분히 클 때** (~20% 이상) → 먼 진입점 선택 (U턴 방지)
- corridor savings가 **미미할 때** (~2% 이하) → 가까운 진입점 선택 (긴 diagonal 억제)

`entry_penalty_factor` 값을 1.0으로 override하면 기존의 "pure cost" 동작으로 돌아가고, 더 크게 (예: 1.5) 하면 corridor 선호가 더 강해집니다. `plan_path_from_point(..., entry_penalty_factor=1.5)`로 호출 시점에 오버라이드 가능.

### Goal Pose (도착 방향) 지원

좁은 운용 공간에서는 "Kitchen 도착" 만으로는 부족합니다. 실제 서비스를 수행하려면 **주방 카운터를 보고 서 있어야** 음식 픽업이 가능하고, **테이블 정면을 향해 있어야** 서빙이 가능합니다. 이를 위해 각 서비스 웨이포인트에 **선택적 yaw**(도착 방향)을 선언할 수 있습니다.

#### 스키마

`waypoints:` 항목에 `yaw` 키를 추가합니다(단위: **도**, 편의상 하드코딩된 라디안보다 사람이 읽기 쉬움. 로더가 라디안으로 변환).

```yaml
waypoints:
  - {x: 1.50, y: +0.050, label: "Kitchen", yaw: 90}     # 카운터 북쪽 바라봄
  - {x: 1.50, y: -0.900, label: "Return", yaw: 0}       # 반납구 동쪽 바라봄
  - {x: 0.00, y: +0.050, label: "Charging", yaw: 180}   # 서쪽 벽에 도킹
  - {x: 0.84, y: -0.766, label: "Table-S", yaw: -90}    # 남쪽 고객 바라봄
  - {x: 0.00, y: -0.766}                                 # junction, yaw 생략
```

**표준 수학 관례** (ROS [REP 103](https://www.ros.org/reps/rep-0103.html)와 일치):

- `0°` = +x (east) 방향
- `90°` = +y (north) 방향 — 렌더 화면의 "위"
- `180°` = -x (west) 방향
- `-90°` (또는 `270°`) = -y (south) 방향 — 렌더 화면의 "아래"

yaw를 생략한 웨이포인트(교차점 등)는 도착 자세 제약이 없습니다. 로컬 플래너(DWB)가 자연스러운 각도로 통과합니다.

#### API

```python
from map_data import Waypoint

wp = graph.waypoints[goal_id]
wp.yaw                # float (radians) or None
```

```python
from astar_planner import plan_path_from_point

plan = plan_path_from_point(
    buffet_map, start_xy, goal_id,
    goal_yaw=math.radians(45),   # optional override of waypoint default
)
plan.goal_yaw         # radians or None
# 결정 규칙: 인자 goal_yaw가 주어지면 그것을 사용,
# 아니면 goal 웨이포인트의 yaw를, 둘 다 없으면 None.
```

`goal_yaw`는 본 글로벌 플래너가 경로 비용에 직접 반영하지 않습니다 (A* 상태 공간이 `(x, y, θ)`까지 확장되지 않음). 대신 **pass-through** 방식으로 플랜 결과에 실어서 내보냅니다. 실제 도착 자세 정렬은 Nav2 `follow_path` action 또는 DWB가 마지막 rotation-in-place로 처리합니다. 이는 Nav2의 표준 플래너(NavFn)도 동일한 방식으로 동작합니다.

#### 시각화

monitor 시각화는 자동으로:

- **yaw를 가진 웨이포인트**: 웨이포인트에서 해당 방향으로 작은 파란 화살표
- **goal waypoint의 yaw**: 도착 시 로봇이 어디를 봐야 하는지 명확히 표시
- 화살표 길이는 맵 크기에 비례해 자동 조정

#### 헤드리스 출력

자유 시작점 시나리오에서 `goal_yaw`가 있으면 함께 출력:

```
[free-start] (0.00, -0.90) -> Kitchen
  entry waypoint = (0,-0.766) (distance 0.13 m, radius 0.35 m)
  total cost = 2.45 m (5 waypoints)
  goal yaw   = 90 deg (robot must arrive facing this direction)
  path: (0.00,-0.90) -> (0,-0.766) -> Table-S -> Table-N -> (0.84,0.05) -> Kitchen
```

#### HQ Service / Nav2 통합

HQ Service는 이 `goal_yaw` 값을 `nav_msgs/Path`의 마지막 `PoseStamped.orientation`에 quaternion으로 변환해 실어서 로봇에 내려보내면 됩니다. 로봇 측 `follow_path` action이 경로 실행 후 최종 자세 정렬까지 자동으로 처리합니다.

```python
# HQ side의 의사 코드
from geometry_msgs.msg import Quaternion
import math

def yaw_to_quaternion(yaw):
    return Quaternion(x=0, y=0, z=math.sin(yaw/2), w=math.cos(yaw/2))

# ...plan path를 받은 후
if plan.goal_yaw is not None:
    last_pose = path_msg.poses[-1]
    last_pose.pose.orientation = yaw_to_quaternion(plan.goal_yaw)
```

#### 현재 샘플 맵의 yaw 선언

**`buffet_sim.yaml`** (실제 SLAM 맵, 실제 운용 의미를 반영):

| 웨이포인트 | yaw | 의미 |
|---|---|---|
| Entrance | 90° | 방 안쪽(+y)을 보고 진입 |
| Charging | 180° | 서쪽 벽에 도킹 |
| Table-S | -90° | 남쪽 customer 쪽을 보고 서빙 |
| Table-N | 90° | 북쪽 customer 쪽을 보고 서빙 |
| Kitchen | 90° | 북쪽 카운터 쪽을 보고 픽업 |
| Return | 0° | 동쪽 반납구를 보고 접근 |

실제 운용 시에는 물리적 카운터/테이블 배치에 맞춰 조정이 필요합니다 (본 데모의 값은 예시).

### 그래프 bottleneck 분석 (cut vertex / bridge)

본 데모는 맵 로드 시점에 웨이포인트 그래프의 **cut vertex**(articulation point)와 **bridge**를 자동으로 계산해 `BuffetMap`에 저장합니다. HQ Service 멀티 로봇 정책의 직접 입력으로 활용하기 위함입니다.

- **Cut vertex**: 그 웨이포인트를 제거하면 그래프가 2개 이상 컴포넌트로 분리되는 지점. 즉 로봇이 거기 멈춰있으면 맵의 일부가 접근 불가능해짐.
- **Bridge**: 그 간선을 제거하면 그래프가 분리되는 통로 구간. 해당 구간이 차단되면 로봇이 반대편으로 갈 수 없음.

알고리즘은 **Tarjan의 DFS 기반 articulation point / bridge 탐색** (시간 복잡도 O(V+E))이고, 본 데모 규모의 그래프(12~27개 웨이포인트)에서는 마이크로초 단위로 실행됩니다. 로드 시점에 한 번 계산되어 `BuffetMap.cut_vertices` / `BuffetMap.bridges` 필드에 캐시됩니다.

#### API

```python
from map_data import load_buffet_map

m = load_buffet_map("maps/buffet_sim.yaml")

m.cut_vertices             # Set[int] — 위험한 웨이포인트 id
m.bridges                  # Set[FrozenSet[int]] — 위험한 간선 (양 끝 id)
m.is_cut_vertex(wp_id)     # bool
m.is_bridge(a, b)          # bool
m.components_after_removing(wp_id) -> List[Set[int]]
#   wp_id를 제거한 뒤의 연결 컴포넌트들. HQ가 "이 로봇을 여기 멈추면
#   어느 영역이 고립되는지" 확인할 때 사용.
```

#### 시각화

monitor 시각화에서 자동으로:

- Cut vertex 웨이포인트 주변에 **빨간 hollow ring** 표시
- Bridge 간선을 **빨간 점선**으로 표시

#### 헤드리스 로드 출력 예시

`buffet_sim.yaml` (map4의 U자 그래프 + 중간 column):

```
Loaded buffet map 'Buffet SLAM map (map4)' from maps/buffet_sim.yaml: 2x1.6 m, ...
  defaults: entry_radius=0.35 m, dynamic_radius=0.12 m, inflation_radius=0.09 m
  bottlenecks: 2 cut vertex(s), 2 bridge(s)
    #1 (0,-0.766): removal isolates {Entrance} (remaining component has 10 wps)
    #9 (1.5,-0.566): removal isolates {Return} (remaining component has 10 wps)
    bridge #0-#1: Entrance <-> (0,-0.766)
    bridge #8-#9: Return <-> (1.5,-0.566)
```

→ `#1`에 로봇이 멈추면 `Entrance` 한 곳만 고립되고 나머지 10개 웨이포인트는 서로 도달 가능. 이 2개 cut vertex는 모두 **leaf 서비스 노드의 유일한 진출입 지점**이라는 특징이 있습니다. 즉 map4에는 "내부 bottleneck"은 없고 leaf gate만 있다는 의미 — 중간 column을 추가한 덕분에 맵이 매우 건강한 2-connected 구조를 가짐이 확인됩니다.

`buffet_realistic.yaml` (합성 ring 맵):

```
  bottlenecks: none (graph is fully 2-connected; no single waypoint or edge can disconnect it)
```

→ Ring 구조는 완벽히 2-connected이므로 bottleneck이 전혀 없음.

#### HQ Service 정책 활용

HQ Service가 이 정보를 다음과 같이 활용할 수 있습니다:

1. **"Cut vertex에는 로봇을 주차/충전/대기시키지 않음"** — `m.cut_vertices` 조회만으로 정책화 가능
2. **"Bridge 구간 점유 시 반대편 목적지 task 배정 유예"** — 예: `Entrance <-> #1` bridge를 지나가는 로봇이 있으면, 같은 시간에 Entrance 방향 task를 다른 로봇에 배정하지 않음
3. **"새 task 배정 전 도달 가능성 사전 체크"** — `components_after_removing(other_robot_wp)` 호출해서 "지금 다른 로봇 위치를 고려하면 이 목적지에 도달 가능한지" 판단
4. **"맵 품질 평가 지표"** — cut vertex 개수가 많다 = 맵이 취약. 적을수록 redundancy가 높음. 지난 수정에서 `buffet_sim`에 중간 column을 추가해 내부 cut vertex를 모두 제거하고 leaf gate만 남긴 것이 이 지표의 직접 개선 사례.

#### 한계

- **정적 분석**: 그래프 topology만 봄. 동적 장애물(움직이는 로봇, 사람)은 `dynamic_obstacles`로 따로 처리.
- **1-connectivity만 다룸**: "노드 1개 또는 간선 1개 제거" 영향만 계산. "2개 동시 제거"까지 가려면 k-connectivity 분석(비싼 계산)이 필요.
- **기하학적 협소는 별개**: "Cut vertex는 아니지만 두 로봇이 동시에 지나가기엔 좁음"은 이 분석이 잡아내지 못함. 본 프로젝트의 2×1.6 m 공간에서는 애초에 모든 통로가 단일 로봇만 허용하므로 area lockout 정책으로 해결.

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

### 2-로봇 경로 예약 (reserved paths)

단일 로봇이 아닌 **2대 로봇이 동시에 경로를 생성**하는 시나리오를 지원합니다. Robot 1(우선순위)이 먼저 plan을 계산하면, Robot 2는 R1의 경로를 `reserved_paths`로 넘겨받아 **R1이 지나갈 ���이포인트와 간선을 회피**하는 경로를 생성합니다.

#### 동작 원리

1. `_compute_blockage()`가 기존 `dynamic_obstacles`(원형 디스크)에 더해 `reserved_paths`(웨이포인트 ID 시���스)도 차단 집합에 추가
2. 예약된 경로의 **모든 웨이포인트 + 연속 간선**이 blockage에 포함됨
3. A* 알고리즘 자체는 변경 없음 — blockage 입력만 확장

#### API

```python
from astar_planner import plan_path, plan_path_from_point

# R1: 우선순위 로봇 — 단독 계획
r1_path, r1_cost = plan_path(m, r1_start, r1_goal)

# R2: R1의 경로를 예약(차단)하고 계획
r2_path, r2_cost = plan_path(
    m, r2_start, r2_goal,
    reserved_paths=[r1_path],     # R1의 웨이포인트 시퀀스
)

# plan_path_from_point에서도 동일하게 사용 가능
plan = plan_path_from_point(
    m, start_xy, goal,
    reserved_paths=[r1_path],
    dynamic_obstacles=[...],      # 함께 사용 가능
)
```

#### ���각화 (2-robot 모드)

`m` 키를 눌러 2-robot 모드로 전환합니다:

1. 좌클릭 4번: R1 start → R1 goal → R2 start → R2 goal
2. R1 경로는 **주황색 실선**, R2 경로는 **녹색 점선**
3. **공유 웨이포인트**가 있으면 빨간 ring으로 하이라이트 (충돌 위험)
4. R2가 경로를 찾지 못하면 "R2: no path (conflict!)" 표시

#### 헤드리스 시나리오 결과

```
[2-robot] R1: Entrance -> Charging, R2: Kitchen -> Return
  R1 alone:  cost=0.95 m, 5 wps  (left column)
  R2 alone:  cost=0.95 m, 4 wps  (right column)
  R2 with R1 reserved: cost=0.95 m, 4 wps
    detour: none (reservation had no effect)

[2-robot] R1: Table-S -> Return, R2: Entrance -> Kitchen
  R1 alone:  cost=1.19 m, 4 wps  (mid bridges)
  R2 alone:  cost=2.45 m, 6 wps  (mid column shortcut)
  R2 with R1 reserved: cost=2.45 m, 7 wps
    detour: rerouted (different path, same cost 2.45 m)

[2-robot] R1: Entrance -> Kitchen, R2: Return -> Kitchen
  R2 with R1 reserved: NO PATH FOUND (conflict!)
    shared waypoints: Kitchen

[2-robot] R1: Table-S -> Table-N, R2: Table-N -> Table-S
  R2 with R1 reserved: NO PATH FOUND (conflict!)
    shared waypoints: Table-N, Table-S
```

#### 핵심 발견: 2 m × 1.6 m 공간의 근본 제약

12개 웨이포인트, 4개 cross-column bridge로 구성된 이 그래프에서 **대부분의 2-robot 조합은 경로 충돌**을 일으킵니다. 이는 `reserved_paths` API의 한계가 아니라 **물리적 공간의 한���**입니다:

- 통로 폭 ≈ 0.15~0.25 m, 로봇 폭 = 0.12 m → 교차 불가
- 그래프가 3개 vertical column + 4개 bridge로 구성 → 하나의 경로가 2개 이상 bridge를 점유하면 나머지 로봇의 경로 옵션이 급격히 줄어듦

이 결과는 **area lockout 정책**(한 번에 한 로봇만 특정 구역 진입)이 이 공간에서 유일하게 안전한 멀티 로봇 전략이라는 것을 정량적으로 뒷받침합니다. `reserved_paths`는 area lockout보다 세밀한 제어가 필요할 때(예: 더 큰 공간, 더 많은 대체 경로가 있는 맵)를 위한 API입니다.

## 코드 구조

각 모듈의 역할:

- `map_data.py` — 맵 로딩 / 편집 / 저장
  - `Waypoint`, `Obstacle`, `WaypointGraph`, `BuffetMap`, `DynamicObstacle`, `RobotStartPose`, `MapDefaults` 데이터 클래스.
  - `StaticEnv` (ABC) + 두 구현: `RectangleEnv` (축 정렬 사각형), `OccupancyGridEnv` (Nav2 점유 격자 + disc inflation).
  - `load_buffet_map(path)`: YAML 내용 기반 형식 자동 감지 (`image:` → Nav2, `obstacles:` → rect).
  - `BuffetMap.move_waypoint()`: 편집 중 위치만 이동 (간선 유지). `BuffetMap._rebuild_edges()`: RNG 기반 간선 재건. `BuffetMap.save_to_yaml()`: 웨이포인트 + 로봇 포즈를 YAML에 저장.
  - 간선 빌드: 초기 로딩은 축 정렬 매칭(`_connect_neighbors`), 편집 후 재건은 RNG(`_connect_visible`) + 컴포넌트 브리지.
  - 동적 장애물 기하 헬퍼: `circle_contains_point`, `circle_intersects_segment`.
- `astar_planner.py` — A* 경로 계획
  - `plan_path(buffet_map, start, goal, ...)`: 웨이포인트 → 웨이포인트 단일 소스 A*.
  - `plan_path_from_point(buffet_map, start_xy, goal, ...)`: 자유 좌표 출발 multi-source A* (`entry_penalty_factor=1.2`).
  - `dynamic_obstacles`: 호출 시점의 동적 장애물로 웨이포인트/간선 차단. `reserved_paths`: 다른 로봇이 예약한 경로 회피.
- `monitor.py` — 시각화 + 클릭 네비게이션 + 편집 모드 (ROS2 노드)
  - TF(`map → base_footprint`)로 로봇 위치 추적, 클릭 시 A* 경로 → `FollowPath` 전송.
  - 편집 모드(`e`): 웨이포인트 드래그 이동, 로봇 포즈 배치(`p`), YAML 저장(`s`).
- `nav2_bridge.py` — CLI 목표 전달
  - `--goal <라벨>` 인자로 A* 경로 계산 → Nav2 `FollowPath` 액션 전송 → 근접 preempt → Spin(yaw 정렬).

## 헤드리스 검증 결과

```
Loaded buffet map 'Buffet SLAM map (map4)' from maps/buffet_sim.yaml:
  2x1.6 m, occupancy grid 40x32 px @ 0.05 m/px, 12 waypoints, 13 edges.
  defaults: dynamic_radius=0.12 m, inflation_radius=0.09 m
  bottlenecks: 2 cut vertex(s), 2 bridge(s)
    #1 (0,-0.766): removal isolates {Entrance} (remaining component has 10 wps)
    #9 (1.5,-0.566): removal isolates {Return} (remaining component has 10 wps)
    bridge #0-#1: Entrance <-> (0,-0.766)
    bridge #8-#9: Return <-> (1.5,-0.566)

--- Waypoint -> Waypoint ---

[scenario] Charging -> Kitchen
  cost = 1.50 m, 3 waypoints
  path: Charging -> (0.84,0.05) -> Kitchen

[scenario] Kitchen -> Return
  cost = 0.95 m, 4 waypoints
  path: Kitchen -> (1.5,-0.2) -> (1.5,-0.566) -> Return

[scenario] Charging -> Return
  cost = 2.45 m, 5 waypoints
  path: Charging -> (0.84,0.05) -> Table-N -> (1.5,-0.566) -> Return

[scenario] Entrance -> Kitchen
  cost = 2.45 m, 6 waypoints
  path: Entrance -> (0,-0.766) -> Table-S -> Table-N -> (0.84,0.05) -> Kitchen

[scenario] Entrance -> Table-N
  cost = 1.17 m, 4 waypoints
  path: Entrance -> (0,-0.766) -> Table-S -> Table-N

[scenario] Table-S -> Kitchen
  cost = 1.48 m, 4 waypoints
  path: Table-S -> Table-N -> (0.84,0.05) -> Kitchen

--- Free start point -> Waypoint ---

[free-start] (1.27, -0.56) -> Charging
  entry waypoint = Table-N (distance 0.43 m)
  total cost = 1.89 m (3 waypoints)
  goal yaw   = 180 deg (robot must arrive facing this direction)
  path: (1.27,-0.56) -> Table-N -> (0.84,0.05) -> Charging

[free-start] (0.00, -0.20) -> Return
  entry waypoint = (0,-0.766) (distance 0.57 m)
  total cost = 2.60 m (5 waypoints)
  goal yaw   = 0 deg (robot must arrive facing this direction)
  path: (0.00,-0.20) -> (0,-0.766) -> Table-S -> Table-N -> (1.5,-0.566) -> Return
```

**Waypoint → Waypoint**: 격자 edge만으로 구성된 쿨한 corridor 경로. `Entrance → Kitchen` 2.45 m 는 Entrance → 좌측 column 진입 → Table-S → Table-N (중간 column) → 상단 corridor → Kitchen 순서로 움직입니다. 모두 직진과 직각 회전만으로 이루어져 있습니다.

**Free start → Waypoint**:
- `(1.27, -0.56) → Charging`: 가장 가까운 웨이포인트는 `(1.5, -0.566)` at 0.23 m지만, A*는 **Table-N at 0.43 m** 을 진입점으로 선택 → 총 1.89 m. 단순 snap-to-nearest 플래너였다면 (1.5,-0.566)로 들어가 U턴해 2.35 m가 됐을 것. Multi-source A*가 **진입 거리보다 전체 비용을 최적화**한다는 직접 증거입니다.
- 두 케이스 모두 `goal yaw`가 함께 출력되어, 로봇이 도착 시 어느 방향을 봐야 하는지를 HQ Service / Nav2 follow_path가 받아쓸 수 있습니다.

## 본 프로젝트로 옮길 때 고려할 점

본 데모는 다음과 같은 부분이 단순화되어 있습니다. 실제 ROS 통합 시 검토가 필요합니다.

- ~~맵 정의가 코드에 하드코딩되어 있음~~ → **YAML 외부 파일 로딩 지원** (`--map` CLI 옵션). SLAM이 만든 실제 맵(Nav2 PGM+YAML)을 그대로 사용 가능.
- ~~정적 장애물 inflation 미반영~~ → **`inflation_radius` per-map 설정 지원**. OccupancyGridEnv는 disc dilation으로 로드 시점에 점유 마스크를 팽창. 기본값 0.09 m = Nav2의 footprint inscribed + padding.
- ~~그래프 topology 약점 분석 부재~~ → **cut vertex / bridge 자동 검출**. 로드 시점에 Tarjan 알고리즘으로 캐시. HQ Service 멀티 로봇 정책의 직접 입력으로 사용 가능.
- ~~Goal pose / 도착 자세 미반영~~ → **웨이포인트에 선택적 yaw 선언 + `FreeStartPlan.goal_yaw` pass-through**. 서비스 웨이포인트는 도착 방향을 도 단위로 선언.
- ~~pinky-pro 치수 가정 부정확~~ → URDF + Nav2 설정 실측 값 반영 (**0.09 m** inflation, **0.12 m** 정사각 footprint).
- ~~`entry_radius` 반경 캡의 역효과~~ → 캡 제거 + **`entry_penalty_factor` (1.2) soft bias** 도입. 하드 캡은 맵 사이즈에 민감해서 U턴을 유발했는데, soft penalty는 "corridor savings가 유의미한 경우에만 먼 진입점을 택함"을 수학적으로 보장.
- 동적 장애물은 quasi-static 스냅샷 + 재계획 모델 → 본 데모는 실제 시간 경과를 시뮬레이션하지 않음 (우클릭으로 추가/`c`로 삭제 시점에만 재계획). 실제 운용에서는 일정 주기(예: 0.5~1초)로 HQ Service가 plan을 호출하고, 미세한 회피는 DWB 등 Local Planner에 위임.
- ~~단일 로봇 가정~~ → **`reserved_paths` 인자로 2-robot 경로 예약 지원**. R1 우선 계획 후 R2가 R1 경로를 회피. 2×1.6 m 공간에서는 대부분��� 조합이 충돌하므로 **HQ Service 레벨 area lockout**이 여전히 필수이지만, 더 큰 공간이나 더 밀집된 그래프에서는 `reserved_paths`가 세밀한 멀티 로봇 경로 분리를 제공.
- ROS 2 패키지 래퍼 없음 → HQ Service가 RPC로 호출할 수 있도록 `PlanRoute.srv` 형태 노드로 감싸는 작업이 남아있음.
- 자유 시작점의 line-of-sight 검사가 0.1 m 샘플링 기반 → 실제 운용에서는 정확한 픽셀 ray-cast 또는 inflated costmap 기반 판정으로 교체 고려.
