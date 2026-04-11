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
| `device/pinky_pro_robot/src/rostaurant_networking` | 위 패키지로 연결되는 심볼릭 링크(선택, `pinky_pro_robot` 워크스페이스에서 colcon 빌드용) |

---

## 관제 서버 (`server/`)

### 요구 사항

- Python 3.10 이상
- 권장: 가상환경(예: `.venv`)

### 설치 및 실행

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PYTHONPATH=.
uvicorn main:app --host 0.0.0.0 --port 8000
```

- HTTP(OpenAPI): `http://<호스트>:8000` — `http://<호스트>:8000/docs`
- TCP 기본: `9000`, UDP 기본: `9001` (환경 변수 `MRTA_TCP_*`, `MRTA_UDP_*`, `MRTA_DB_PATH`로 변경 가능)

---

## 로봇 측 ROS2 (`rostaurant_networking`)

### 빌드

`pinky_interfaces`와 함께 빌드합니다.

```bash
cd device/pinky_pro_robot
colcon build --packages-select pinky_interfaces rostaurant_networking
source install/setup.bash
```

### 노드 실행

```bash
ros2 run rostaurant_networking rostaurant_comm_node --ros-args \
  -p robot_id:=PNK01 \
  -p server_host:=127.0.0.1 \
  -p tcp_port:=9000 \
  -p udp_port:=9001
```

주요 파라미터: `robot_id`, `server_host`, `tcp_port`, `udp_port`, `odom_topic`, `battery_topic`, `task_status_topic`, `robot_command_topic` (기본값은 노드 소스 참고).
