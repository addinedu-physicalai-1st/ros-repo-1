<<<<<<< HEAD
# ros-repo-1

다중 로봇 작업 할당(MRTA)용 **관제 서버**(Python / FastAPI / asyncio / SQLite)와 **로봇 측 ROS2 브리지**(`rostaurant_networking`)가 포함된 저장소입니다.

---

## 저장소 구조

| 경로 | 설명 |
|------|------|
| `server/` | TCP(제어)·UDP(텔레메트리)·REST API·SQLite·RBAC |
| `server/proto/.../robotcafe.proto` | Protobuf 계약 (소스) |
| `server/robotcafe/db/v1/` | 생성된 Python protobuf 스텁 |
| `device/pinky_pro_robot/src/pinky_interfaces/` | ROS 메시지 `RobotCommand`, `RobotTaskStatus` |
| `device/rostaurant/src/rostaurant_networking/` | ROS2 패키지: TCP 클라이언트 + UDP 송신 + `rostaurant_comm_node` |
| `device/pinky_pro_robot/src/rostaurant_networking` | 위 패키지로 연결되는 심볼릭 링크(`pinky_pro_robot` 워크스페이스에서 colcon 빌드용) |

---

## 관제 서버 (`server/`)

### 요구 사항

- Python 3.10 이상
- 권장: `server` 디렉터리 안에 가상환경 `.venv`

### 설치

**`requirements.txt`는 `server/` 안에만 있습니다.** 저장소 루트가 아니라 반드시 `server`로 이동한 뒤 설치하세요.

```bash
cd /path/to/ros-repo-1/server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

(`/path/to/ros-repo-1`은 본인 환경의 실제 절대 경로로 바꿉니다.)

### 실행

`main` 모듈은 **`server` 디렉터리**를 현재 디렉터리로 두고, `PYTHONPATH=.` 로 찾습니다. 아래는 **한 줄씩** 입력합니다 (`export PYTHONPATH=.` 와 `uvicorn`을 붙이면 안 됩니다).

```bash
cd /path/to/ros-repo-1/server
source .venv/bin/activate
export PYTHONPATH=.
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

(`uvicorn`이 PATH에 있으면 `uvicorn main:app ...` 만으로도 됩니다.)

- **HTTP·REST**: `http://<호스트>:8000` — API 문서: `http://<호스트>:8000/docs`  
  운영에서는 `MRTA_DISABLE_OPENAPI=1` 또는 `MRTA_ENV=production`으로 `/docs`, `/redoc`, `/openapi.json` 비활성화를 권장합니다.
- **TCP** 기본 `9000`, **UDP** 기본 `9001` (`MRTA_TCP_HOST`, `MRTA_TCP_PORT`, `MRTA_UDP_HOST`, `MRTA_UDP_PORT`, `MRTA_DB_PATH` 등으로 변경 가능)

### 보안·운영 요약

- 방화벽: 관제 호스트 **8000·9000·9001 인바운드**는 신뢰 네트워크만, 로봇에서는 해당 호스트로 **아웃바운드** 허용.
- 최초 기동 시 관리자 API 키는 **로그에 전체 미기록**. 파일 저장: `MRTA_ADMIN_KEY_OUT=/path/to/file` (권한 `0600`).
- 로봇 평면 기본 무인증. 운영 시 `MRTA_REQUIRE_ROBOT_TOKEN=1` + `POST /robots/{robot_id}/rotate-connection-token`(ADMIN)으로 받은 값을 브리지 `connection_token`에 설정. UDP만 제한: `MRTA_UDP_REQUIRE_ACTIVE_SESSION=1`(해당 `robot_id`에 TCP 세션 있을 때만 UDP 반영).
- `GET /health` → 인증 없이 `{"status":"ok"}`만. 연결 로봇 ID: `GET /health/detail` + Bearer(STAFF_FLOOR 이상).
- 환경 변수 표: [server/docs/MRTA_Communication_Protocol_Spec.md](server/docs/MRTA_Communication_Protocol_Spec.md) §9.1

---

## 로봇 측 ROS2 (`rostaurant_networking`)

### 빌드

`device/pinky_pro_robot`을 워크스페이스 루트로 두고, `pinky_interfaces`와 함께 빌드합니다.

```bash
cd /path/to/ros-repo-1/device/pinky_pro_robot
colcon build --packages-select pinky_interfaces rostaurant_networking
source install/setup.bash
```

(zsh이면 `source install/setup.zsh`.)

`ros2 run`이 실행 파일을 찾으려면 패키지에 `setup.cfg`가 포함되어 있어야 합니다(본 저장소의 `rostaurant_networking`에 포함됨). 빌드 후 확인:

```bash
ros2 pkg executables rostaurant_networking
# 기대 출력: rostaurant_networking rostaurant_comm_node
```

### 노드 실행

관제 서버가 떠 있는 호스트를 `server_host`로 지정합니다. 로봇마다 **`robot_id`를 다르게** 줍니다.

```bash
source install/setup.bash
ros2 run rostaurant_networking rostaurant_comm_node --ros-args \
  -p robot_id:=PNK01 \
  -p server_host:=127.0.0.1 \
  -p tcp_port:=9000 \
  -p udp_port:=9001
```

- **`connection_token`**: 서버에 `MRTA_REQUIRE_ROBOT_TOKEN=1`일 때만 `-p connection_token:=...` (관제에서 `POST /robots/{robot_id}/rotate-connection-token`으로 발급).
- **토픽 리맵**: 시뮬/로봇에 따라 `-p odom_topic:=...`, `-p battery_topic:=...`, `-p task_status_topic:=...` (기본은 각각 `/odom`, `/battery`, `/task_status`). Gazebo만 켠 상태에서 이 토픽이 없으면 해당 텔레메트리는 서버로 거의 안 나갑니다.
- **명령 수신 토픽**: 브리지가 TCP로 받은 명령은 **`/robot_command`** (`pinky_interfaces/RobotCommand`)로 퍼블리시합니다. `-p robot_command_topic:=...` 으로 바꿀 수 있습니다.

### 권장 기동 순서 (터미널 나누기)

| 순서 | 터미널 | 내용 |
|------|--------|------|
| 1 | A | 위 **관제 서버** 실행 (`server` + venv + uvicorn) |
| 2 | B | (시뮬 사용 시) Gazebo 등 — 예: `ros2 launch pinky_gz_sim launch_sim.launch.xml` |
| 3 | C | `pinky_pro_robot`에서 `source install/setup.bash` 후 `ros2 run rostaurant_networking rostaurant_comm_node ...` |

---

## 명령 수신 테스트 (REST → TCP → ROS)

1. 브리지가 TCP로 붙어 있고, `curl`의 `robot_id`가 브리지의 `robot_id`와 같아야 합니다.
2. `POST /commands/send`는 DB 제약으로 **`task_id`가 기존 `tasks` 행과 일치**해야 할 수 있습니다. 먼저 `POST /tasks`로 작업을 만들고 응답의 `task_id`를 사용하세요.
3. **ADMIN** API 키로 호출합니다 (`Authorization: Bearer <키>`).

**터미널 1** — 수신 확인:

```bash
source install/setup.bash
ros2 topic echo /robot_command
```

**터미널 2** — 명령 전송(값은 환경에 맞게 수정):

```bash
curl -sS -X POST "http://127.0.0.1:8000/commands/send" \
  -H "Authorization: Bearer ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"robot_id":"PNK01","task_id":"위에서_만든_task_id","command":1,"target_id":"TBL_01"}'
```

- `command`는 `CommandType` 정수(예: `1`=MOVE_TO). 정의는 `server/proto/robotcafe/db/v1/robotcafe.proto` 참고.
- `503 robot not connected`이면 TCP 세션 없음(브리지·`server_host`/포트 확인).

**브리지 없이** 토픽만 점검할 때:

```bash
ros2 topic pub --once /robot_command pinky_interfaces/msg/RobotCommand \
  "{cmd_id: 'test', task_id: 't1', robot_id: 'PNK01', command: 1, target_id: 'TBL_01'}"
```

---

## 자주 나는 문제

| 증상 | 원인·조치 |
|------|-----------|
| `Could not open requirements.txt` | `cd .../server` 후 `pip install -r requirements.txt` |
| `Could not import module "main"` | `cd server` 후 `export PYTHONPATH=.` 실행 여부 확인 |
| `No executable found` / `ros2 pkg executables` 빈 줄 | `rostaurant_networking` 재빌드, `setup.cfg` 포함 여부 확인 후 `source install/setup.bash` |
| `ros2 topic echo` 가 멈춘 것처럼 보임 | 구독 대기 상태가 정상. 다른 터미널에서 `curl` 또는 `ros2 topic pub`으로 메시지 발생 |

주요 파라미터 전체는 [device/rostaurant/.../ros_bridge_node.py](device/rostaurant/src/rostaurant_networking/rostaurant_networking/ros_bridge_node.py) 의 `declare_parameter` 를 참고하세요.
=======
# Smart Restaurant Robot System - Admin Dashboard

## 📖 프로젝트 소개 (Introduction)
본 프로젝트는 스마트 레스토랑 로봇 시스템을 위한 모듈형 **PyQt5 기반의 통합 관제 대시보드 (Admin Dashboard)** 입니다. 로봇의 실시간 관제, 개별 네트워크 설정, 맵 및 테이블 관리, 태스크 할당, 블랙박스 녹화 기록 관리 및 시스템 네트워크 모의 테스트 기능을 단일 어플리케이션 안에서 모두 제공합니다.

## ✨ 주요 기능 (Key Features)
1. **🗺️ 관제 메인 페이지 (Map Dashboard)**
   - 로봇의 위치와 이동 경로를 시각적으로 모니터링할 수 있는 반응형 맵 뷰 제공.
2. **🤖 로봇 개별 환경 설정 (Robot Setting)**
   - 각 로봇의 TCP/UDP 네트워크 파라미터 등 상세 연결 환경을 구성하고 제어.
3. **🪑 맵(테이블/경로) 설정 (Map Setting)**
   - 매장 내 테이블 추가/삭제 및 로봇의 주행 경로 등을 직관적으로 설정.
4. **📝 태스크(작업) 통합 관리 (Task Management)**
   - 로봇에게 할당되는 각종 서빙 및 이동 태스크를 종합적으로 관리.
5. **📹 비전 및 녹화 관리 (Vision & Record Management)**
   - 로봇의 비전 시스템 및 블랙박스 역할을 하는 녹화 기록 조회 기능.
6. **🧪 관제 시스템 및 네트워크 테스트 (System & Network Tests)**
   - TCP 상태, REST API, 실시간 응답 성능, 장애 및 예외 상황 등에 대한 통합 네트워크 모의 테스트 및 히스토리 트래킹 기능 지원.

## 📂 디렉토리 구조 (Directory Structure)
UI 관련 코드는 `ui/desktop/admin_ui/` 하위에 완전하게 모듈화되어 있습니다.

```text
ros-repo-1/
└── ui/
    └── desktop/
        └── admin_ui/
            ├── main.py              # 메인 실행 파일 및 통합 GUI (QMainWindow)
            ├── components/          # 재사용 가능한 UI 컴포넌트(위젯)
            ├── utils/               # 유틸리티 (예: test_manager.py)
            └── views/               # 기능별 개별 페이지 화면 구성
                ├── map_view.py              # 맵 관제 대시보드
                ├── robot_setting_view.py    # 로봇 환경 설정
                ├── map_setting_view.py      # 맵 & 테이블 설정
                ├── task_view.py             # 태스크 관리
                └── record_view.py           # 비전 및 녹화 관리
```

## ⚙️ 요구 환경 (Requirements)
* **Python 3.x**
* **PyQt5**

필요한 패키지를 설치하려면 아래 명령어를 사용하세요:
```bash
pip install PyQt5
```

## 🚀 실행 가이드 (How to Run)
터미널에서 `admin_ui` 디렉토리로 이동한 후 `main.py`를 실행합니다.

```bash
# 디렉토리 이동
cd ui/desktop/admin_ui

# 어플리케이션 실행
python main.py
```
>>>>>>> origin/feat/admin-gui
