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

### 권장 기동 순서 요약

| 순서 | 터미널 | 명령 |
|------|--------|------|
| 1 | A | `cd server && ADMIN_API_KEY=<key> ./start.sh` |
| 2 | B | `ros2 launch pinky_gz_sim launch_sim.launch.xml` |
| 3 | C | `ros2 run rostaurant_networking rostaurant_comm_node ...` |
| 4 | 브라우저 | `http://localhost:3000/static/kiosk/kiosk.html` |

---

### 환경변수 전체 목록

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `ADMIN_API_KEY` | — | ADMIN 사용자 API 키. 서버 최초 기동 시 로그/파일에서 확인 |
| `MRTA_ADMIN_KEY_OUT` | — | ADMIN 키를 저장할 파일 경로 (`chmod 600` 권장) |
| `MRTA_DB_PATH` | `rostaurant.db` | SQLite DB 파일 경로 |
| `MRTA_PORT` | `8000` | 관제 서버 포트 |
| `WEB_PORT` | `3000` | 웹 서버 포트 |
| `MRTA_TCP_PORT` | `9000` | 로봇 TCP 포트 |
| `MRTA_UDP_PORT` | `9001` | 로봇 UDP 포트 |
| `CONTROL_BASE_URL` | `http://localhost:8000` | 웹서버·PyQt가 바라보는 관제 REST 주소 |
| `CONTROL_WS_URL` | `ws://localhost:8000/ws/stream` | 웹서버 WS relay 주소 |
| `CONTROL_SERVICE_KEY` | `ADMIN_API_KEY`와 동일 | 웹→관제 내부 인증 키 |
| `NO_DASHBOARD` | `0` | `1`로 설정하면 PyQt 대시보드 자동 실행 안 함 |
| `DASHBOARD_PYTHON` | 자동 탐색 | PyQt5가 설치된 Python 경로 |
| `MAP_POSE_SCALE_PX` | `200` | 맵 픽셀/미터 비율 (map4, 10x 업스케일 기준) |
| `MAP_ORIGIN_X` | `57` | Gazebo (0,0) 스폰 위치의 맵 이미지 X 픽셀 |
| `MAP_ORIGIN_Y` | `72` | Gazebo (0,0) 스폰 위치의 맵 이미지 Y 픽셀 |

---

## 웹 UI 주소

| UI | 주소 |
|----|------|
| 키오스크 (손님 입장·결제) | `http://localhost:3000/static/kiosk/kiosk.html` |
| 주방 패널 (직원용) | `http://localhost:3000/static/kitchen/kitchen.html` |
| 테이블 서비스 (손님 요청) | `http://localhost:3000/static/table_ui/table_service.html?table=1` |
| API 문서 (Swagger) | `http://localhost:8000/docs` |

---

## 저장소 구조

| 경로 | 설명 |
|------|------|
| `server/control/` | 관제 서버: TCP·UDP·REST API·SQLite(`rostaurant.db`)·RBAC |
| `server/web/` | 웹 서버: 브라우저 UI 서빙·REST 프록시·WebSocket relay |
| `server/start.sh` | 관제 서버 + 웹 서버 + PyQt 대시보드 동시 실행 스크립트 |
| `server/control/proto/` | Protobuf 계약 소스 |
| `server/web/static/kiosk/` | 키오스크 UI |
| `server/web/static/kitchen/` | 주방 패널 UI |
| `server/web/static/table_ui/` | 테이블 서비스 UI |
| `ui/desktop/admin_ui/` | PyQt5 데스크톱 관제 대시보드 |
| `ui/desktop/assets/images/gazebo_map.png` | Gazebo `map4` 점유 격자 맵 (PyQt 표시용, 400×320px) |
| `device/pinky_pro_robot/map4.pgm` | nav2 원본 맵 (40×32px, 0.05 m/px) |
| `device/pinky_pro_robot/map4.yaml` | nav2 맵 메타데이터 (origin, resolution) |
| `device/rostaurant/src/rostaurant_networking/` | ROS2 패키지: TCP 클라이언트 + UDP 송신 |
| `device/pinky_pro_robot/src/pinky_gz_sim/` | Gazebo 시뮬레이션 패키지 |

---

## PyQt 대시보드 맵 좌표 동기화

PyQt 맵(`gazebo_map.png`)은 `map4.pgm`을 10배 업스케일한 이미지입니다.  
Gazebo `/odom` 좌표가 그대로 맵 픽셀로 변환됩니다:

```
pixel_x = MAP_ORIGIN_X + odom_x × MAP_POSE_SCALE_PX
pixel_y = MAP_ORIGIN_Y - odom_y × MAP_POSE_SCALE_PX   (화면 Y축 반전)
```

| Gazebo 위치 | 맵 픽셀 | 의미 |
|---|---|---|
| (0, 0) — 로봇 스폰 | (57, 72) | 맵 좌상단 근처 |
| (+1m, 0) | (257, 72) | 오른쪽 1m |
| (0, -1m) | (57, 272) | 아래쪽 1m |

맵 또는 스폰 위치가 바뀌면 `MAP_ORIGIN_X`, `MAP_ORIGIN_Y`, `MAP_POSE_SCALE_PX` 환경변수로 재보정할 수 있습니다.

---

## 자주 나는 문제

| 증상 | 원인·조치 |
|------|-----------|
| `{"detail":"Not authenticated"}` | `ADMIN_API_KEY` 미설정 또는 `Authorization: Bearer <key>` 헤더 누락 |
| `{"detail":"no pose cached for robot"}` | 브리지 노드가 서버에 연결되지 않음. 브리지 재실행 필요 |
| PyQt 대시보드가 안 뜸 | `DISPLAY` 환경변수 미설정 또는 PyQt5 미설치 (`sudo apt install python3-pyqt5`) |
| `TCP framing error` | 브리지 노드가 연결 후 즉시 끊어짐. 서버 로그의 상세 에러 확인 |
| `503 robot not connected` | 브리지 노드가 TCP로 연결되지 않은 상태에서 명령 전송 시도 |
| `FOREIGN KEY constraint failed` | 존재하지 않는 `task_id`로 명령 전송. `POST /tasks`로 먼저 태스크 생성 필요 |
| `Could not import module "main"` | `cd server/control` 후 `export PYTHONPATH=.` 실행 |
| Gazebo에서 로봇 이동 시 PyQt 맵이 안 움직임 | 브리지 노드가 서버에 연결된 후 `/odom`이 발행되고 있는지 `ros2 topic hz /odom`으로 확인 |

---

## 보안·운영 요약

- 방화벽: 관제 호스트 **8000·9000·9001 인바운드**는 신뢰 네트워크만 허용.
- 최초 기동 시 ADMIN API 키: `MRTA_ADMIN_KEY_OUT=/path/to/file`로 파일에 저장 (`chmod 600` 권장).
- 로봇 평면 기본 무인증. 운영 시 `MRTA_REQUIRE_ROBOT_TOKEN=1` 설정.
- `GET /health` → 인증 없이 `{"status":"ok"}`.

---

## Admin Dashboard (PyQt5)

### 주요 기능

1. **관제 메인 (Map Dashboard)** — 로봇 실시간 위치 + Gazebo 맵 동기화
2. **로봇 설정 (Robot Setting)** — TCP/UDP 파라미터 구성 및 제어
3. **맵 설정 (Map Setting)** — 테이블 추가/삭제, 주행 경로 설정
4. **태스크 관리 (Task Management)** — 서빙·이동 태스크 통합 관리
5. **비전·녹화 관리 (Vision & Record)** — 녹화 기록 조회
6. **시스템 테스트 (Network Tests)** — TCP·REST·실시간 응답 모의 테스트

### 디렉토리 구조

```
ui/desktop/admin_ui/
├── main.py              # 메인 실행 파일 (QMainWindow)
├── components/          # 재사용 UI 컴포넌트
├── utils/               # api_client.py, config.py 등
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
