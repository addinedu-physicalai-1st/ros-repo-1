# Rostaurant — 다중 로봇 관제 시스템

레스토랑 환경을 위한 MRTA(Multi-Robot Task Allocation) 시스템입니다.  
관제 서버, 웹 UI, 로봇 ROS2 브리지 노드로 구성됩니다.

---

## 시스템 구성

```
Browser ──REST──▶ Web Server (3000) ──REST──▶ Control Server (8000)
Browser ◀──WS───  Web Server        ◀──WS───  Control Server ◀──TCP/UDP──▶ Robot (ROS2)
                                               PyQt Dashboard ──REST──▶ Control Server
```

| 컴포넌트 | 경로 | 설명 |
|---------|------|------|
| 관제 서버 | `server/control/` | FastAPI + SQLite + TCP/UDP 로봇 통신 |
| 웹 서버 | `server/web/` | UI 서빙 + 관제 서버 프록시 |
| PyQt 대시보드 | `ui/desktop/admin_ui/` | 실시간 맵 모니터링 |
| 로봇 브리지 | `device/rostaurant/src/rostaurant_networking/` | ROS2 ↔ TCP/UDP 변환 |
| 로봇 실행기 | `device/rostaurant/src/task_executor/` | Nav2 기반 주행 명령 실행 |
| 로봇 인터페이스 | `device/pinky_pro/src/pinky_interfaces/` | ROS2 커스텀 메시지 정의 |

---

## 빠른 시작

### 필수 요건

| 항목 | 버전/설명 |
|------|----------|
| Python | 3.10 이상 |
| ROS2 | Jazzy (로봇 노드 실행 시) |
| PyQt5 | `sudo apt install python3-pyqt5 python3-requests` |

### 1. 저장소 클론

```bash
git clone <repo-url> rostaurant
cd rostaurant
```

### 2. 서버 의존성 설치

```bash
cd server

python3 -m venv .venv
source .venv/bin/activate

pip install -r control/requirements.txt
pip install -r web/requirements.txt
```

### 3. 최초 실행 — Admin API 키 발급

```bash
cd server
MRTA_ADMIN_KEY_OUT=~/admin_key.txt ./start.sh
```

서버 시작 후 `~/admin_key.txt` 파일에 키가 저장됩니다.

```bash
cat ~/admin_key.txt
# user_id=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# api_key=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

> 이 키를 이후 모든 실행에서 `ADMIN_API_KEY`로 사용합니다.

### 4. 서버 실행

```bash
cd server
ADMIN_API_KEY=<위에서_복사한_키> ./start.sh
```

| 서비스 | 주소 |
|--------|------|
| 관제 서버 REST API | http://localhost:8000/docs |
| 웹 서버 | http://localhost:3000 |
| 헬스체크 | http://localhost:8000/health |

---

## 웹 UI

| 화면 | 주소 |
|------|------|
| 키오스크 (손님 주문) | http://localhost:3000/static/kiosk/kiosk.html |
| 테이블 서비스 | http://localhost:3000/static/table_ui/index.html?table=1 |
| 주방 패널 | http://localhost:3000/static/kitchen/kitchen.html |
| API 문서 (Swagger) | http://localhost:8000/docs |

`table=1` 부분을 `table=2`, `table=3` 등으로 바꾸면 해당 테이블 UI가 열립니다.

---

## 로봇 연결

### 시뮬레이션 (Gazebo)

```bash
# 터미널 1 — 서버
cd server && ADMIN_API_KEY=<키> ./start.sh

# 터미널 2 — Gazebo 시뮬레이션
source /opt/ros/jazzy/setup.bash
ros2 launch pinky_gz_sim launch_sim.launch.xml

# 터미널 3 — 로봇 브리지 노드
cd device/rostaurant
source /opt/ros/jazzy/setup.bash
colcon build --packages-select pinky_interfaces rostaurant_networking task_executor
source install/setup.bash
ros2 launch rostaurant_networking robot.launch.py
```

연결 성공 시 서버 로그에 출력됩니다:
```
INFO  connection_manager  Registered TCP session for PNK01
```

### 실물 로봇

#### 사전 준비 (최초 1회)

```bash
# 로봇에서 — hostname을 robot_id로 사용
sudo hostnamectl set-hostname pnk01
```

```bash
# 서버 PC — 방화벽 허용
sudo ufw allow 8000/tcp  # REST API
sudo ufw allow 9000/tcp  # 로봇 TCP
sudo ufw allow 9001/udp  # 로봇 UDP 텔레메트리
```

#### 로봇 빌드 (최초 1회)

```bash
# 로봇에서 SSH 접속 후
ssh pinky@<로봇IP>

mkdir -p ~/pinky_pro/src
cd ~/pinky_pro

# pinky_interfaces, rostaurant 패키지 복사 (또는 git clone)
# 복사할 소스: device/pinky_pro/src/pinky_interfaces
#              device/rostaurant/src/rostaurant_networking
#              device/rostaurant/src/task_executor

source /opt/ros/jazzy/setup.bash
colcon build --packages-select pinky_interfaces rostaurant_networking task_executor
source install/setup.bash
```

#### 실행 순서

```bash
# 서버 PC
cd server && ADMIN_API_KEY=<키> ./start.sh

# 로봇 터미널 1 — 하드웨어 노드
source /opt/ros/jazzy/setup.bash
source ~/pinky_pro/install/setup.bash
ros2 launch pinky_bringup bringup_robot.launch.xml

# 로봇 터미널 2 — 관제 서버 브리지
source /opt/ros/jazzy/setup.bash
source ~/pinky_pro/install/setup.bash
ros2 launch rostaurant_networking robot.launch.py server_host:=<서버PC_IP>
```

서버 PC IP 확인: `hostname -I` (예: `192.168.1.10`)

---

## 환경변수

### 서버 (server/start.sh 또는 직접 실행 시)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ADMIN_API_KEY` | — | **필수.** 최초 실행 시 로그에서 확인 |
| `MRTA_ADMIN_KEY_OUT` | — | 최초 실행 시 Admin 키를 저장할 파일 경로 |
| `MRTA_PORT` | `8000` | 관제 서버 포트 |
| `WEB_PORT` | `3000` | 웹 서버 포트 |
| `MRTA_TCP_PORT` | `9000` | 로봇 TCP 포트 |
| `MRTA_UDP_PORT` | `9001` | 로봇 UDP 포트 |
| `MRTA_DB_PATH` | `rostaurant.db` | SQLite DB 경로 |
| `NO_DASHBOARD` | `0` | `1` 설정 시 PyQt 대시보드 자동 실행 안 함 |
| `MRTA_REQUIRE_ROBOT_TOKEN` | — | `1` 설정 시 로봇 connection token 인증 활성화 |

### 로봇 브리지 노드 (launch 파라미터)

| 파라미터 | 기본값 | 설명 |
|---------|--------|------|
| `server_host` | `127.0.0.1` | 관제 서버 IP |
| `tcp_port` | `9000` | 관제 서버 TCP 포트 |
| `udp_port` | `9001` | 관제 서버 UDP 포트 |
| `robot_id` | hostname 자동 사용 | 로봇 식별자 (대문자, 예: `PNK01`) |

`robot_id`는 `hostnamectl set-hostname pnk01` 설정 시 자동으로 `PNK01`로 결정됩니다.  
강제 지정: `ROBOT_ID=PNK02 ros2 launch rostaurant_networking robot.launch.py`

---

## 장소 ID (place_id) 목록

관제 서버 DB에 초기 등록된 장소입니다. 좌표는 `GET /places` 또는 `PATCH /places/{id}`로 수정합니다.

| place_id | 용도 |
|----------|------|
| `WAIT_A`, `WAIT_B` | 로봇 대기 위치 (자동 충전 귀환 시 사용) |
| `KIOSK_1` | 키오스크 위치 |
| `TBL_01` ~ `TBL_05` | 고객 테이블 1~5 |
| `TOILET` | 화장실 안내 목적지 |
| `EXIT_DINE` | 퇴식구 |
| `KITCHEN` | 주방 |
| `DISP_01` ~ `DISP_06` | 메뉴 진열장 1~6 |

좌표 설정 예시:
```bash
curl -X PATCH http://localhost:8000/places/TBL_01 \
  -H "Authorization: Bearer <ADMIN_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"x": 2.5, "y": -1.0, "theta": 0.0}'
```

---

## 통신 프로토콜 요약

| 구간 | 프로토콜 | 포트 | 설명 |
|------|---------|------|------|
| 관제 서버 ↔ 로봇 | TCP (Protobuf) | 9000 | 명령 전송, 상태 보고, 하트비트 |
| 로봇 → 관제 서버 | UDP (Protobuf) | 9001 | 위치(~10Hz), 배터리(~1Hz) 텔레메트리 |
| 브라우저 ↔ 서버 | WebSocket (JSON) | 3000 | 로봇 상태 실시간 이벤트 |
| 브라우저 → 서버 | HTTP REST | 3000 | 작업 생성, 응답 |

### WebSocket 이벤트 (`ws://localhost:3000/ws`)

```json
{ "event": "status",      "robot_id": "PNK01", "robot_status": 2, "fsm_state": 3, "battery": 85 }
{ "event": "heartbeat",   "robot_id": "PNK01", "timestamp_ms": 1713274800123 }
{ "event": "command_ack", "robot_id": "PNK01", "ack_status": 3, "task_id": "...", "cmd_id": "..." }
```

`robot_status` 값: 1=IDLE, 2=MOVING, 3=ARRIVED, 4=CHARGING, 5=ERROR, 6=OFFLINE  
`ack_status` 값: 1=ACCEPTED, 2=REJECTED, 3=EXECUTED, 4=ACK_FAILED

---

## 테스트 실행

```bash
cd server/control
../.venv/bin/pytest tests/ -v
```

---

## 저장소 구조

```
rostaurant/
├── server/
│   ├── control/          # 관제 서버 (FastAPI + SQLite + TCP/UDP)
│   │   ├── main.py
│   │   ├── scheduler.py  # 작업 배정 정책
│   │   ├── connection_manager.py
│   │   ├── proto/        # Protobuf 정의 (.proto)
│   │   └── tests/        # pytest 테스트
│   ├── web/              # 웹 서버 (UI 서빙 + 프록시)
│   │   └── static/       # kiosk, kitchen, table_ui HTML
│   └── start.sh          # 전체 서비스 동시 실행 스크립트
├── device/
│   ├── pinky_pro/
│   │   └── src/          # Pinky Pro 로봇 ROS2 패키지 소스
│   │       ├── pinky_interfaces/   # 커스텀 메시지 (RobotCommand, RobotTaskStatus)
│   │       ├── pinky_bringup/      # 하드웨어 초기화
│   │       ├── pinky_navigation/   # Nav2 설정
│   │       └── ...
│   └── rostaurant/
│       └── src/
│           ├── rostaurant_networking/  # TCP/UDP ↔ ROS2 브리지
│           └── task_executor/          # Nav2 주행 명령 실행
└── ui/
    └── desktop/admin_ui/ # PyQt5 관제 대시보드
```

---

## 자주 발생하는 문제

| 증상 | 해결 방법 |
|------|----------|
| `{"detail":"Not authenticated"}` | `ADMIN_API_KEY` 환경변수 미설정. `cat ~/admin_key.txt` 로 키 확인 후 재실행 |
| `ModuleNotFoundError: No module named 'pinky_interfaces.msg'` | 로봇 워크스페이스에 `pinky_interfaces` 빌드 필요. `colcon build --packages-select pinky_interfaces` |
| `{"detail":"dest_id '...' is not a valid active place"}` | 위 place_id 표에 없는 ID 사용. 표를 참고하거나 `GET /places`로 등록된 목록 확인 |
| 로봇이 서버에 연결 안 됨 | 서버 PC와 로봇이 같은 네트워크인지 확인. `ping <서버IP>` 및 포트 9000/9001 방화벽 확인 |
| PyQt 대시보드가 안 뜸 | `sudo apt install python3-pyqt5 python3-requests` 또는 `NO_DASHBOARD=1` 으로 대시보드 없이 실행 |
| `503 robot not connected` | 로봇 브리지 노드가 실행 중이지 않거나 TCP 연결이 끊어진 상태 |
| 배터리가 항상 0% 표시 | 시뮬레이션 환경에서는 정상. 실물 로봇의 `/battery` 토픽 확인 |
