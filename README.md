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

## 처음 실행하는 분을 위한 단계별 안내

> 터미널을 여러 개 열어야 합니다. 각 단계마다 **어느 터미널**인지 표시되어 있으니 잘 읽고 따라하세요.

### 0단계 — 저장소 클론 (딱 한 번만)

```bash
git clone <repo-url> rostaurant
cd rostaurant
```

---

### 1단계 — 서버 의존성 설치 (딱 한 번만)

```bash
cd server

python3 -m venv .venv
source .venv/bin/activate

pip install -r control/requirements.txt
pip install -r web/requirements.txt
```

---

### 1-1단계 — 프론트엔드 빌드 (딱 한 번만, UI 수정 시마다)

```bash
cd server/web/frontend

npm install
npm run build
```

> `npm install`은 처음 한 번만 실행하면 됩니다.  
> UI 코드를 수정했을 때는 `npm run build`만 다시 실행하면 됩니다.

---

### 2단계 — Admin API 키 발급 (딱 한 번만)

처음 실행하면 자동으로 관리자 계정이 만들어지고 키가 발급됩니다.

```bash
cd server
rm -f control/rostaurant.db
MRTA_ADMIN_KEY_OUT=~/admin_key.txt ./start.sh
```

서버 로그에 아래 메시지가 나오면 성공입니다:

```
INFO  main  INITIAL ADMIN user_id=xxxxxxxx-... — api_key written to /root/admin_key.txt
INFO  main  FIRST-RUN: Admin user created. Use the api_key above for ADMIN_API_KEY.
```

**Ctrl+C** 로 서버를 멈추고, 키를 확인합니다:

```bash
cat ~/admin_key.txt
# api_key=xxxxxxxxxxxxxxxxxxxx...  ← 이 값을 복사해 두세요!
```

> 키를 잃어버렸으면 `rm server/control/rostaurant.db` 후 이 단계를 다시 하면 됩니다.

---

### 3단계 — 로봇 Python 의존성 설치 (딱 한 번만)

> protobuf 버전이 맞지 않으면 아래 오류 중 하나가 납니다:
> - `ImportError: cannot import name 'runtime_version'` (protobuf 3.x)
> - `RuntimeVersionError: ... supports runtime versions 6.x.x` (protobuf 4.x/5.x)
>
> `robotcafe_pb2.py`가 **protobuf 6.31.1**로 생성되었으므로 반드시 6.31.1 이상이어야 합니다.

```bash
pip install -r device/rostaurant/requirements.txt --break-system-packages
```

확인:

```bash
python3 -c "import google.protobuf; print(google.protobuf.__version__)"
# 6.31.1 이상이면 OK
```

---

### 4단계 — 로봇 패키지 빌드 (딱 한 번만)

> **중요:** 반드시 **새 터미널**을 열어서 순서대로 실행하세요.  
> 중간에 터미널을 닫거나 새로 열면 2번(`source /opt/ros/jazzy/setup.bash`)부터 다시 시작해야 합니다.

```bash
# (1) ROS2 환경 불러오기
source /opt/ros/jazzy/setup.bash

# (2) pinky_interfaces 빌드
cd /path/to/rostaurant/device/pinky_pro
colcon build --packages-select pinky_interfaces

# (3) pinky_interfaces 적용
source install/setup.bash

# (4) rostaurant 패키지 빌드  ← (3) 과 같은 터미널에서 계속!
cd ../rostaurant
colcon build --packages-select rostaurant_state_machine rostaurant_networking task_executor

# (5) rostaurant 적용
source install/setup.bash
```

빌드가 끝나면 아래처럼 출력됩니다:

```
Summary: 2 packages finished [...]
```

---

## 매일 실행하는 방법

빌드는 이미 끝났으니, 아래 순서로 터미널 3개를 엽니다.

### 터미널 1 — 서버 실행

```bash
cd server
ADMIN_API_KEY=<2단계에서_복사한_키> ./start.sh
```

| 서비스 | 주소 |
|--------|------|
| 관제 서버 API | http://localhost:8000/docs |
| 웹 서버 | http://localhost:3000 |
| 헬스체크 | http://localhost:8000/health |

---

### 터미널 2 — Gazebo 시뮬레이션

```bash
source /opt/ros/jazzy/setup.bash
ros2 launch pinky_gz_sim launch_sim.launch.xml
```

---

### 터미널 3 — 로봇 브리지 노드 (새 터미널에서!)

```bash
# (1) ROS2 환경 불러오기
source /opt/ros/jazzy/setup.bash

# (2) pinky_interfaces 적용
cd /path/to/rostaurant/device/pinky_pro
source install/setup.bash

# (3) rostaurant 적용  ← (2) 와 같은 터미널에서 계속!
cd ../rostaurant
source install/setup.bash

# (4) 실행
ros2 launch rostaurant_networking robot.launch.py
```

서버 로그에 아래가 출력되면 연결 성공입니다:

```
INFO  connection_manager  Registered TCP session for PNK01
```

---

## 웹 UI 주소

| 화면 | 주소 |
|------|------|
| 키오스크 (손님 주문) | http://localhost:3000/static/kiosk/ |
| 테이블 서비스 | http://localhost:3000/static/table_ui/?table=1 |
| 주방 패널 | http://localhost:3000/static/kitchen/ |
| 스태프 패널 | http://localhost:3000/static/staff/ |
| API 문서 (Swagger) | http://localhost:8000/docs |

`table=1` 부분을 `table=2`, `table=3` 등으로 바꾸면 해당 테이블 UI가 열립니다.

---

## 실물 로봇 연결

### 사전 준비 (최초 1회)

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

### 로봇 빌드 (최초 1회)

```bash
# 로봇에 SSH 접속
ssh pinky@<로봇IP>

# 워크스페이스 디렉토리 생성
mkdir -p ~/pinky_pro/src ~/rostaurant/src

# 소스를 아래 경로에 복사 (git clone 또는 scp)
# device/pinky_pro/src/pinky_interfaces       →  ~/pinky_pro/src/pinky_interfaces
# device/rostaurant/src/rostaurant_networking  →  ~/rostaurant/src/rostaurant_networking
# device/rostaurant/src/task_executor          →  ~/rostaurant/src/task_executor
# device/rostaurant/requirements.txt           →  ~/rostaurant/requirements.txt

# 0단계: Python 의존성 설치
pip install -r ~/rostaurant/requirements.txt --break-system-packages

# 1단계: pinky_interfaces 빌드 (새 터미널)
source /opt/ros/jazzy/setup.bash
cd ~/pinky_pro
colcon build --packages-select pinky_interfaces
source install/setup.bash

# 2단계: rostaurant 패키지 빌드 (같은 터미널)
cd ~/rostaurant
colcon build --packages-select rostaurant_state_machine rostaurant_networking task_executor
source install/setup.bash
```

### 실물 로봇 실행

```bash
# 서버 PC
cd server && ADMIN_API_KEY=<키> ./start.sh

# 로봇 터미널 1 — 하드웨어 노드 (새 터미널)
source /opt/ros/jazzy/setup.bash
source ~/pinky_pro/install/setup.bash
ros2 launch pinky_bringup bringup_robot.launch.xml

# 로봇 터미널 2 — 관제 서버 브리지 (새 터미널)
source /opt/ros/jazzy/setup.bash
source ~/pinky_pro/install/setup.bash
source ~/rostaurant/install/setup.bash
ros2 launch rostaurant_networking robot.launch.py server_host:=<서버PC_IP>
```

서버 PC IP 확인: `hostname -I`

---

## 오류가 났을 때

| 오류 메시지 | 해결 방법 |
|------------|----------|
| `{"detail":"Not authenticated"}` | `ADMIN_API_KEY` 환경변수 미설정. `cat ~/admin_key.txt` 로 키 확인 후 재실행 |
| `TransientParseError: not enough data to read` | empy 버전 문제. `pip install empy==3.3.4` 후 재빌드 |
| `ImportError: cannot import name 'runtime_version' from 'google.protobuf'` | protobuf 버전 낮음. `pip install "protobuf>=6.31.1" --break-system-packages` |
| `RuntimeVersionError: ... supports runtime versions 6.x.x ...` | protobuf가 4.x/5.x로 설치됨. `pip install "protobuf>=6.31.1" --break-system-packages` |
| `ModuleNotFoundError: No module named 'pinky_interfaces.msg'` | `pinky_interfaces` 빌드 후 `source install/setup.bash` 필요 |
| `ignoring unknown package 'pinky_interfaces'` | `pinky_interfaces`는 `device/pinky_pro/`에서만 빌드 가능. 별도 워크스페이스 빌드 필요 |
| `no such file or directory: .../local_setup.sh` | 빌드 캐시 오염. `rm -rf build install log` 후 **새 터미널**에서 재빌드 |
| `{"detail":"dest_id '...' is not a valid active place"}` | 아래 place_id 표에 없는 ID 사용. `GET /places`로 등록된 목록 확인 |
| 로봇이 서버에 연결 안 됨 | 서버 PC와 로봇이 같은 네트워크인지 확인. `ping <서버IP>` 및 포트 9000/9001 방화벽 확인 |
| PyQt 대시보드가 안 뜸 | `sudo apt install python3-pyqt5 python3-requests` 또는 `NO_DASHBOARD=1 ./start.sh` |
| `503 robot not connected` | 로봇 브리지 노드가 실행 중이지 않거나 TCP 연결이 끊어진 상태 |
| 배터리가 항상 0% 표시 | 시뮬레이션 환경에서는 정상. 실물 로봇의 `/battery` 토픽 확인 |

---

## 환경변수 목록

### 서버 (start.sh)

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

| place_id | 용도 |
|----------|------|
| `WAIT_A`, `WAIT_B` | 로봇 대기 위치 |
| `KIOSK_1` | 키오스크 위치 |
| `TBL_01` ~ `TBL_05` | 고객 테이블 1~5 |
| `TOILET` | 화장실 안내 목적지 |
| `EXIT_DINE` | 퇴식구 |
| `KITCHEN` | 주방 |
| `DISP_01` ~ `DISP_06` | 메뉴 진열장 1~6 |

좌표 수정:

```bash
curl -X PATCH http://localhost:8000/places/TBL_01 \
  -H "Authorization: Bearer <ADMIN_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"x": 2.5, "y": -1.0, "theta": 0.0}'
```

---

## 통신 프로토콜

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
│   │   └── src/
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
