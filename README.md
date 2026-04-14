# ros-repo-1

다중 로봇 작업 할당(MRTA)용 **관제 서버**(Python / FastAPI / asyncio / SQLite)와 **로봇 측 ROS2 브리지**(`rostaurant_networking`)가 포함된 저장소입니다.

---

## 전체 시스템 실행 방법

### 필수 요구 사항

| 항목 | 버전 |
|------|------|
| Python | 3.10 이상 |
| ROS2 | Jazzy |
| PyQt5 | 시스템 패키지 (`sudo apt install python3-pyqt5`) |
| requests | `pip install requests` |

---

### 1단계 — 서버 의존성 설치 (최초 1회)

```bash
cd /path/to/ros-repo-1/server/control
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd ../web
pip install -r requirements.txt
```

---

### 2단계 — ADMIN_API_KEY 확인

**최초 실행 시**: 키를 파일로 저장해두면 이후 재사용이 편합니다.

```bash
cd /path/to/ros-repo-1/server
MRTA_ADMIN_KEY_OUT=~/admin_key.txt ./start.sh
# 서버 시작 후 ~/admin_key.txt 에 키가 저장됨
cat ~/admin_key.txt
```

**이미 키를 알고 있는 경우**: 아래 3단계로 바로 진행.

---

### 3단계 — 서버 + PyQt 대시보드 실행

```bash
cd /path/to/ros-repo-1/server
ADMIN_API_KEY=<admin_api_key> ./start.sh
```

- 관제 서버: `http://localhost:8000` (API 문서: `http://localhost:8000/docs`)
- 웹 서버: `http://localhost:3000`
- PyQt 대시보드: DISPLAY 환경변수가 설정된 경우 **자동 실행**

> PyQt가 뜨지 않을 때: `sudo apt install python3-pyqt5 python3-requests` 후 재시도.  
> 대시보드 없이 서버만 실행하려면: `NO_DASHBOARD=1 ADMIN_API_KEY=<key> ./start.sh`

---

### 4단계 — Gazebo 시뮬레이션 실행 (별도 터미널)

```bash
# ROS2 환경 활성화
source /opt/ros/jazzy/setup.zsh   # 또는 setup.bash

# Gazebo 시뮬레이션 시작
ros2 launch pinky_gz_sim launch_sim.launch.xml
```

---

### 5단계 — 로봇 브리지 노드 실행 (별도 터미널)

```bash
cd /path/to/ros-repo-1/device/pinky_pro_robot

# 빌드 (최초 1회)
source /opt/ros/jazzy/setup.zsh
colcon build --packages-select pinky_interfaces rostaurant_networking
source install/setup.zsh

# 브리지 노드 실행
ros2 run rostaurant_networking rostaurant_comm_node \
  --ros-args \
  -p robot_id:=PNK01 \
  -p server_host:=127.0.0.1 \
  -p tcp_port:=9000 \
  -p udp_port:=9001 \
  -p odom_topic:=/odom \
  -p battery_topic:=/battery \
  -p task_status_topic:=/task_status \
  -p robot_command_topic:=/robot_command
```

연결 성공 시 서버 로그에 다음이 출력됩니다:
```
INFO  connection_manager  Registered TCP session for PNK01
```

---

### 권장 기동 순서 요약 (시뮬레이션)

| 순서 | 터미널 | 명령 |
|------|--------|------|
| 1 | A | `cd server && ADMIN_API_KEY=<key> ./start.sh` |
| 2 | B | `ros2 launch pinky_gz_sim launch_sim.launch.xml` |
| 3 | C | `ros2 run rostaurant_networking rostaurant_comm_node ...` |
| 4 | 브라우저 | `http://localhost:3000/static/table_ui/index.html?table=3` |

---

## 실물 로봇 구동 방법

### 사전 준비

| 항목 | 설명 |
|------|------|
| 서버 PC IP 확인 | 서버 PC에서 `hostname -I` 실행, 첫 번째 IP 사용 (예: `192.168.1.10`) |
| 로봇 hostname 설정 | 로봇에서 `sudo hostnamectl set-hostname pnk01` (최초 1회, robot_id로 사용됨) |
| 네트워크 | 서버 PC와 로봇이 같은 네트워크에 있어야 함. 로봇에서 `ping <서버IP>` 으로 확인 |
| 방화벽 | 서버 PC에서 8000(REST), 9000(TCP), 9001(UDP) 포트 인바운드 허용 |

### 1단계 — 서버 PC에서 관제 시스템 실행

```bash
cd /path/to/ros-repo-1/server
ADMIN_API_KEY=<key> ./start.sh
```

### 2단계 — 로봇에 소스코드 배포 및 빌드 (최초 1회)

로봇에 SSH 접속 후:

```bash
ssh pinky@<로봇IP>

# 소스코드 배포 (git clone 또는 scp)
cd ~/dev_ws/src
git clone <repo-url> ros-repo-1

# 빌드
cd ~/dev_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select pinky_interfaces rostaurant_networking
source install/setup.bash
```

> `pinky_bringup`, `pinky_description` 등 하드웨어 패키지는 로봇에 이미 빌드되어 있다고 가정합니다.

### 3단계 — 로봇 하드웨어 노드 실행 (로봇 터미널 1)

```bash
source /opt/ros/jazzy/setup.bash
source ~/dev_ws/install/setup.bash

ros2 launch pinky_bringup bringup_robot.launch.xml
```

이 런치 파일이 실행하는 노드:
- 모터 제어 (`pinky_bringup/bringup`) — diff-drive, `/odom` 발행
- 라이다 (`sllidar_ros2`) — `/dev/ttyAMA0` 시리얼 포트
- 배터리 (`pinky_bringup/battery_publisher`) — `battery/percent` 토픽 발행

### 4단계 — 관제서버 브리지 실행 (로봇 터미널 2)

```bash
source /opt/ros/jazzy/setup.bash
source ~/dev_ws/install/setup.bash

ros2 launch rostaurant_networking robot.launch.py server_host:=<서버PC IP>
```

예시:
```bash
ros2 launch rostaurant_networking robot.launch.py server_host:=192.168.1.10
```

> `robot.launch.py`가 자동으로 `battery_topic`을 `battery/percent`로 설정하므로 별도 지정이 불필요합니다.

연결 성공 시 서버 로그:
```
INFO  connection_manager  Registered TCP session for PNK01
```

### 5단계 — 웹 UI 접속 (태블릿/브라우저)

같은 네트워크의 기기에서:
```
http://<서버PC IP>:3000/static/table_ui/index.html?table=3
```

### 실물 로봇 기동 순서 요약

| 순서 | 위치 | 명령 |
|------|------|------|
| 1 | 서버 PC | `cd server && ADMIN_API_KEY=<key> ./start.sh` |
| 2 | 로봇 터미널 1 | `ros2 launch pinky_bringup bringup_robot.launch.xml` |
| 3 | 로봇 터미널 2 | `ros2 launch rostaurant_networking robot.launch.py server_host:=<서버IP>` |
| 4 | 태블릿 브라우저 | `http://<서버IP>:3000/static/table_ui/index.html?table=3` |

### 시뮬레이션 vs 실물 차이점

| 항목 | 시뮬레이션 | 실물 |
|------|-----------|------|
| 로봇 노드 | Gazebo + `ros2 run rostaurant_comm_node` | `bringup_robot.launch.xml` + `robot.launch.py` |
| server_host | `127.0.0.1` (같은 PC) | 서버 PC의 실제 LAN IP |
| robot_id | 파라미터로 직접 지정 | hostname 자동 사용 (`hostnamectl`) |
| battery_topic | `/battery` (기본값, 발행 노드 없음) | `battery/percent` (런치 파일에서 자동 설정) |
| 배터리 데이터 | 없음 (Gazebo 미지원) | 실제 배터리 IC에서 읽어 publish |
| odom 소스 | Gazebo diff-drive 플러그인 | 실물 모터 엔코더 |

---

## 데이터 송수신 흐름

### 시스템 아키텍처

```
Browser ──REST──▶ Web Server ──REST──▶ Control Server ◀──TCP/UDP──▶ Robot (ROS2)
Browser ◀──WS───  Web Server ◀──WS───  Control Server
PyQt Dashboard ─────────REST──────────▶ Control Server
```

| 프로토콜 | 구간 | 용도 |
|---------|------|------|
| REST (HTTP) | Web Frontend <-> Web Server <-> Control Server | 태스크 생성, 응답, 조회 |
| REST (HTTP) | PyQt Dashboard <-> Control Server | 로봇/태스크/텔레메트리 조회 |
| WebSocket | Control Server -> Web Server -> Browser | 로봇 상태 변경 실시간 브로드캐스트 |
| TCP | Control Server <-> Robot | 명령 전송, 상태 보고, 하트비트 |
| UDP | Robot -> Control Server | 텔레메트리 (pose, battery) |

### 시나리오별 요청 매핑 (Web Frontend -> 관제 서버)

| 시나리오 | Frontend `type` | `task_type` | Proto `TaskType` | `dest_id` 출처 | 예시 |
|---------|----------------|-------------|------------------|---------------|------|
| 키오스크 결제 | (POST /api/checkout) | 1 | KIOSK_TO_TABLE | `TBL_{table.zfill(2)}` | `TBL_03` |
| 화장실 안내 | `"toilet"` | 2 | TABLE_TO_TOILET | 프론트엔드 하드코딩 | `TOILET` |
| 메뉴 안내 | `"menu:DISP_01"` | 3 | TABLE_TO_DISPLAY | 메뉴 선택 항목의 `place_id` | `DISP_01` |
| 식기 수거 | `"dishPickup"` | 4 | DISH_PICKUP | 서버 자동 생성 | `TBL_03` |
| 로봇 교체 | `"robotSwap"` | 5 | ROBOT_SWAP | 서버 자동 생성 | `TBL_03` |
| 동행 서비스 | `"escort"` | 6 | ESCORT_SERVICE | 프론트엔드 `TBL_` 생성 | `TBL_03` |
| 직원 호출 | `"staff"` | 0 | (태스크 미생성) | — | — |
| 도킹 복귀 | (respond "ok") | 7 | RETURN_TO_DOCK | 서버 내부 | `""` |

### 사용자 응답 (POST /api/tasks/{id}/respond)

| `status` | `next_dest` | 서버 동작 |
|----------|-------------|----------|
| `"ok"` | 있음 | `MOVE_TO` 다음 경유지로 이동 |
| `"ok"` | 없음 | `RETURN_DOCK` + 태스크 COMPLETED |
| `"retry"` | — | `MOVE_TO` 같은 dest_id로 재이동 |
| 기타 | — | `RETURN_DOCK` + 태스크 FAILED |

### WebSocket 이벤트 형식 (관제 서버 -> 브라우저)

| 이벤트 | 주요 필드 | 설명 |
|--------|----------|------|
| `status` | `robot_id`, `robot_status`(int), `fsm_state`(int), `current_task`, `battery` | 로봇 상태 변경. `robot_status=3`(ARRIVED) + `current_task=taskId`로 도착 감지 |
| `heartbeat` | `robot_id`, `timestamp_ms` | 로봇 TCP 연결 유지 |
| `command_ack` | `cmd_id`, `robot_id`, `ack_status`, `task_id` | 명령 수신/실행 확인 |

### 로봇 텔레메트리 (ROS2 -> 관제 서버)

| ROS2 토픽 | 메시지 타입 | 프로토콜 | 관제 서버 수신 |
|-----------|-----------|---------|--------------|
| `/odom` | `nav_msgs/Odometry` | UDP `TelemetryPose` | `GET /telemetry/pose/{robot_id}` |
| `/battery` | `std_msgs/Float32` | UDP `TelemetryState` | `GET /telemetry/battery/{robot_id}` |
| `/task_status` | `RobotTaskStatus` | TCP `StatusReport` | DB 업데이트 + WS 브로드캐스트 |
| `/robot_command` | `RobotCommand` | (수신 전용) | 관제 서버 TCP `Command` -> ROS2 publish |

### DB 등록 장소 (place_id)

| place_id | 이름 | 용도 |
|----------|------|------|
| `WAIT_A`, `WAIT_B` | 대기 A/B | 로봇 대기 위치 |
| `KIOSK_1` | 키오스크(출입구) | 결제 후 안내 출발점 |
| `TBL_01` ~ `TBL_05` | 테이블 1~5 | 고객 테이블 |
| `TOILET` | 화장실 | 화장실 안내 목적지 |
| `EXIT_DINE` | 퇴식구 | 식기 수거 관련 |
| `KITCHEN` | 주방 | 서빙 출발점 |
| `DISP_01` ~ `DISP_06` | 진열장 1~6 | 메뉴 안내 목적지 |

---

## 환경변수 전체 목록

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ADMIN_API_KEY` | — | ADMIN 사용자 API 키. 서버 최초 기동 시 로그/파일에서 확인 |
| `MRTA_ADMIN_KEY_OUT` | — | ADMIN 키를 저장할 파일 경로 (`chmod 600` 권장) |
| `MRTA_DB_PATH` | `rostaurant.db` | SQLite DB 파일 경로 |
| `MRTA_PORT` | `8000` | 관제 서버 포트 |
| `WEB_PORT` | `3000` | 웹 서버 포트 |
| `MRTA_TCP_PORT` | `9000` | 로봇 TCP 포트 |
| `MRTA_UDP_PORT` | `9001` | 로봇 UDP 포트 |
| `CONTROL_BASE_URL` | `http://localhost:8000` | 웹서버/PyQt가 바라보는 관제 REST 주소 |
| `CONTROL_WS_URL` | `ws://localhost:8000/ws/stream` | 웹서버 WS relay 주소 |
| `CONTROL_SERVICE_KEY` | `ADMIN_API_KEY`와 동일 | 웹->관제 내부 인증 키 |
| `NO_DASHBOARD` | `0` | `1`로 설정하면 PyQt 대시보드 자동 실행 안 함 |
| `DASHBOARD_PYTHON` | 자동 탐색 | PyQt5가 설치된 Python 경로 |
| `MAP_POSE_SCALE_PX` | `200` | 맵 픽셀/미터 비율 (map4, 10x 업스케일 기준) |
| `MAP_ORIGIN_X` | `57` | Gazebo (0,0) 스폰 위치의 맵 이미지 X 픽셀 |
| `MAP_ORIGIN_Y` | `72` | Gazebo (0,0) 스폰 위치의 맵 이미지 Y 픽셀 |

---

## 웹 UI 주소

| UI | 주소 |
|----|------|
| 키오스크 (손님 입장/결제) | `http://localhost:3000/static/kiosk/kiosk.html` |
| 주방 패널 (직원용) | `http://localhost:3000/static/kitchen/kitchen.html` |
| 테이블 서비스 (손님 요청) | `http://localhost:3000/static/table_ui/index.html?table=1` |
| API 문서 (Swagger) | `http://localhost:8000/docs` |

---

## 저장소 구조

| 경로 | 설명 |
|------|------|
| `server/control/` | 관제 서버: TCP/UDP/REST API/SQLite(`rostaurant.db`)/RBAC |
| `server/web/` | 웹 서버: 브라우저 UI 서빙/REST 프록시/WebSocket relay |
| `server/web/frontend/` | React 테이블 UI (Vite + Tailwind CSS) |
| `server/start.sh` | 관제 서버 + 웹 서버 + PyQt 대시보드 동시 실행 스크립트 |
| `server/control/proto/` | Protobuf 계약 소스 |
| `server/web/static/kiosk/` | 키오스크 UI |
| `server/web/static/kitchen/` | 주방 패널 UI |
| `server/web/static/table_ui/` | 테이블 서비스 UI (빌드 결과물) |
| `ui/desktop/admin_ui/` | PyQt5 데스크톱 관제 대시보드 |
| `ui/desktop/admin_ui/utils/scheduler.py` | 태스크 스케줄링 엔진 (mock 시뮬레이션) |
| `ui/desktop/assets/images/gazebo_map.png` | Gazebo `map4` 점유 격자 맵 (PyQt 표시용, 400x320px) |
| `device/pinky_pro_robot/map4.pgm` | nav2 원본 맵 (40x32px, 0.05 m/px) |
| `device/pinky_pro_robot/map4.yaml` | nav2 맵 메타데이터 (origin, resolution) |
| `device/rostaurant/src/rostaurant_networking/` | ROS2 패키지: TCP 클라이언트 + UDP 송신 |
| `device/pinky_pro_robot/src/pinky_gz_sim/` | Gazebo 시뮬레이션 패키지 |

---

## Admin Dashboard (PyQt5)

### 주요 기능

1. **관제 메인 (Map Dashboard)** — 로봇 실시간 위치 + Gazebo 맵 동기화. pose 데이터 송신 중인 활성 로봇만 표시.
2. **로봇 설정 (Robot Setting)** — TCP/UDP 파라미터 구성 및 제어. DB 전체 로봇 수 + 활성/오프라인 분류 표시.
3. **맵 설정 (Map Setting)** — 테이블 추가/삭제, 주행 경로 설정
4. **태스크 관리 (Task Management)** — 서빙/이동 태스크 통합 관리. 로봇 상태 모니터(활성 로봇만), 시뮬레이션 스케줄러, 실제 서버 태스크 테이블 통합.
5. **비전/녹화 관리 (Vision & Record)** — 녹화 기록 조회
6. **시스템 테스트 (Network Tests)** — TCP/REST/실시간 응답 모의 테스트

### 스케줄링 엔진 (`utils/scheduler.py`)

태스크 관리 탭의 시뮬레이션 모니터에 사용되는 mock 스케줄러입니다.

- `Task`: 단일 작업의 메타데이터 (ID, 유형, 상태, 우선순위, 예상 소요 시간)
- `TaskScheduler`: 작업 큐 관리 및 로봇 할당 정책 실행. 자동 충전 트리거 포함.
- FSM 상태: 대기(PENDING) -> 이동(MOVING) -> 도착(ARRIVED) -> 작업(WORKING) -> 완료(COMPLETED)

### 디렉토리 구조

```
ui/desktop/admin_ui/
├── main.py              # 메인 실행 파일 (QMainWindow)
├── components/          # 재사용 UI 컴포넌트
├── utils/               # api_client.py, config.py, scheduler.py
└── views/
    ├── map_view.py          # 맵 관제 대시보드
    ├── robot_setting_view.py
    ├── map_setting_view.py
    ├── task_view.py
    └── record_view.py
```

### 단독 실행 (start.sh 없이)

```bash
ADMIN_API_KEY=<key> python3 ui/desktop/admin_ui/main.py
```

---

## PyQt 대시보드 맵 좌표 동기화

PyQt 맵(`gazebo_map.png`)은 `map4.pgm`을 10배 업스케일한 이미지입니다.  
Gazebo `/odom` 좌표가 그대로 맵 픽셀로 변환됩니다:

```
pixel_x = MAP_ORIGIN_X + odom_x * MAP_POSE_SCALE_PX
pixel_y = MAP_ORIGIN_Y - odom_y * MAP_POSE_SCALE_PX   (화면 Y축 반전)
```

| Gazebo 위치 | 맵 픽셀 | 의미 |
|---|---|---|
| (0, 0) — 로봇 스폰 | (57, 72) | 맵 좌상단 근처 |
| (+1m, 0) | (257, 72) | 오른쪽 1m |
| (0, -1m) | (57, 272) | 아래쪽 1m |

맵 또는 스폰 위치가 바뀌면 `MAP_ORIGIN_X`, `MAP_ORIGIN_Y`, `MAP_POSE_SCALE_PX` 환경변수로 재보정할 수 있습니다.

---

## 자주 나는 문제

| 증상 | 원인/조치 |
|------|-----------|
| `{"detail":"Not authenticated"}` | `ADMIN_API_KEY` 미설정 또는 `Authorization: Bearer <key>` 헤더 누락 |
| `{"detail":"dest_id '...' is not a valid active place"}` | dest_id가 DB places 테이블에 없음. 위 place_id 표 참조 |
| `{"detail":"no pose cached for robot"}` | 브리지 노드가 서버에 연결되지 않음. 브리지 재실행 필요 |
| PyQt 대시보드가 안 뜸 | `DISPLAY` 환경변수 미설정 또는 PyQt5 미설치 (`sudo apt install python3-pyqt5`) |
| PyQt에 로봇이 안 보임 | Gazebo/브리지 노드가 서버보다 늦게 시작됨. "새로 고침" 버튼 클릭 |
| 배터리 0% 표시 | 로봇이 battery 토픽을 publish하지 않는 상태. 시뮬레이션에서는 정상 |
| `TCP framing error` | 브리지 노드가 연결 후 즉시 끊어짐. 서버 로그의 상세 에러 확인 |
| `503 robot not connected` | 브리지 노드가 TCP로 연결되지 않은 상태에서 명령 전송 시도 |
| `FOREIGN KEY constraint failed` | 존재하지 않는 `task_id`로 명령 전송. `POST /tasks`로 먼저 태스크 생성 필요 |
| `Could not import module "main"` | `cd server/control` 후 `export PYTHONPATH=.` 실행 |
| Gazebo에서 로봇 이동 시 PyQt 맵이 안 움직임 | 브리지 노드가 서버에 연결된 후 `/odom`이 발행되고 있는지 `ros2 topic hz /odom`으로 확인 |

---

## 보안/운영 요약

- 방화벽: 관제 호스트 **8000/9000/9001 인바운드**는 신뢰 네트워크만 허용.
- 최초 기동 시 ADMIN API 키: `MRTA_ADMIN_KEY_OUT=/path/to/file`로 파일에 저장 (`chmod 600` 권장).
- 로봇 평면 기본 무인증. 운영 시 `MRTA_REQUIRE_ROBOT_TOKEN=1` 설정.
- `GET /health` — 인증 없이 `{"status":"ok"}`.
