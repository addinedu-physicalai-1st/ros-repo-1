---
name: MRTA Server Device
overview: Proto 생성 후 asyncio 서버(TCP/UDP/FastAPI)와 ROS2 Jazzy 브리지(ROS 데몬 스레드 + 메인 asyncio)를 추가합니다. 디바이스는 /odom·/battery에 `qos_profile_sensor_data`로 과거 샘플 지연을 줄이고, 서버 UDP 캐시는 시퀀스/타임스탬프 단조 갱신으로 역순 도착을 방지하며, SQLite는 WAL+INTEGER(ms) 타임스탬프로 동시성·기간 조회를 맞춥니다.
todos:
  - id: proto-and-gen
    content: .proto 수정(Tcp/Udp magic 제거·필드 재번호); __init__.py 3개; grpc_tools.protoc로 생성; import 스모크
    status: completed
  - id: server-db
    content: "db.py: 스키마+CRUD; Timestamp는 INTEGER(ms); 연결 직후 PRAGMA journal_mode=WAL"
    status: completed
  - id: server-net
    content: tcp_gateway + udp_receiver + 캐시; UDP는 타임스탬프/시퀀스로 역순 도착 시 덮어쓰기 금지
    status: completed
  - id: server-api
    content: "main.py: FastAPI lifespan, 하트비트 타임아웃 OFFLINE, REST 엔드포인트 및 SendCommand→TCP"
    status: completed
  - id: ros-msgs
    content: pinky_interfaces에 RobotCommand.msg, RobotTaskStatus.msg 추가 및 CMakeLists 갱신
    status: completed
  - id: ros-package
    content: "pinky_mrta_comm: 데몬 스레드 spin + 메인 asyncio; /odom·/battery 구독 시 qos_profile_sensor_data(BEST_EFFORT, KEEP_LAST, depth 1~5)"
    status: completed
isProject: false
---

# MRTA 프로토콜·서버·디바이스 구현 계획

## 빌드 전 필수 확인 (게이트)

**1단계(Proto 생성 + import 가능)가 선행 조건**이다. `*_pb2.py`가 없거나 `PYTHONPATH`/`__init__.py`가 어긋나면 2~6단계는 전부 `ImportError`로 실패한다.

- **`timestamp.proto`**: 원시 `protoc -I server/proto`만으로는 well-known import가 실패하기 쉽다. **권장**: `pip install grpcio-tools` 후 아래처럼 **`python -m grpc_tools.protoc`** 사용(번들 include로 경로 단순화).
- **수동 파일**: `protoc`는 패키지 디렉터리에 `__init__.py`를 만들지 않으므로 아래 **3개를 반드시 커밋/생성**한다.  
  - `server/robotcafe/__init__.py`  
  - `server/robotcafe/db/__init__.py`  
  - `server/robotcafe/db/v1/__init__.py`
- **ROS 메시지**: [`device/pinky_pro_robot/src/pinky_interfaces/msg/RobotCommand.msg`](device/pinky_pro_robot/src/pinky_interfaces/msg/RobotCommand.msg), [`.../RobotTaskStatus.msg`](device/pinky_pro_robot/src/pinky_interfaces/msg/RobotTaskStatus.msg) 실체 파일 + [`CMakeLists.txt`](device/pinky_pro_robot/src/pinky_interfaces/CMakeLists.txt) `MSG_FILES` 등록 없이는 **7단계 `colcon build` 실패**.

**권장: 구현 직후 바로 통과시킬 4단계**

1. `.proto` 수정(Tcp/Udp `magic` 제거·필드 번호 정리) — 아래「프로토·와이어 정합」과 동일.
2. 위 `__init__.py` 3개 생성.
3. venv에서 `grpcio-tools` 설치 후 `grpc_tools.protoc` 실행.
4. `PYTHONPATH=server`로 스모크: `python -c "from robotcafe.db.v1 import robotcafe_pb2; print('OK')"` (또는 `import robotcafe.db.v1.robotcafe_pb2`).

**단계별 가능 여부(요약)**

| 단계 | 내용 | 지금 가능? | 블로커 |
|------|------|------------|--------|
| 1 | protoc 생성 | 수정·게이트 통과 후 가능 | `.proto` magic/필드 정리, WKT include, `__init__.py` |
| 2 | db.py | 가능 | 1 선행 |
| 3 | connection_manager | 가능 | 1 선행 |
| 4 | tcp_gateway | 가능 | 1 + TCP 헤더(매직+길이) 포맷 확정 |
| 5 | udp_receiver | 가능 | 1 + UDP 매직 헤더 확정 |
| 6 | main.py | 가능 | 2~5 선행 |
| 7 | pinky_interfaces | 가능 | `.msg` 2개 + CMakeLists |
| 8 | pinky_mrta_comm | 가능 | 7 선행 |
| 9 | 스모크 테스트 | 1~8 완료 후 | 전 단계 |

**Proto 생성 명령 예시(고정 문구로 문서화)**

```bash
pip install grpcio-tools
python -m grpc_tools.protoc \
  -I server/proto \
  --python_out=server \
  server/proto/robotcafe/db/v1/robotcafe.proto
```

(조직 정책상 순수 `protoc`만 쓸 경우에는 `-I`에 `google/protobuf`가 포함된 well-known 루트를 **반드시** 추가한다.)

---

현재 레포 상태

ROS 패키지는 device/pinky_pro_robot/src/ 아래에 있으며, pinky_interfaces는 srv만 정의되어 있습니다.

배터리는 pinky_bringup/battery_[publisher.py](http://publisher.py)에서 Float32로 battery/percent에 발행 중입니다. 요구 스펙의 /battery, /task_status, /robot_command는 신규 정의 또는 리맵이 필요합니다.

디렉터리·산출물

영역

경로

Proto 원본

server/proto/robotcafe/db/v1/robotcafe.proto — 사용자 제공 정의를 기반으로 하되, **아래 ‘프로토·와이어 정합’ 절의 필수 수정**(Tcp/Udp `magic` 메시지 필드 제거 등)을 반영한 버전을 소스로 삼는다.

생성된 Python

server/robotcafe/db/v1/*_[pb2.py](http://pb2.py) (protoc --python_out=server + import 경로가 robotcafe.db.v1가 되도록)

서버 모듈

server/tcp_[gateway.py](http://gateway.py), server/connection_[manager.py](http://manager.py), server/udp_[receiver.py](http://receiver.py), server/[db.py](http://db.py), server/[main.py](http://main.py)

의존성

server/requirements.txt: fastapi, uvicorn[standard], aiosqlite, protobuf — **proto 생성용(개발/CI)**: `grpcio-tools` 권장(`python -m grpc_tools.protoc`가 well-known `timestamp.proto` 등 include 경로를 단순화).

ROS 패키지 (ament_python)

device/pinky_pro_robot/src/pinky_mrta_comm/ — 요구 파일명: tcp_[client.py](http://client.py), udp_[sender.py](http://sender.py), ros_bridge_[node.py](http://node.py)

커스텀 메시지

pinky_interfaces에 msg/RobotCommand.msg, msg/RobotTaskStatus.msg 추가 후 CMakeLists.txt의 MSG_FILES에 등록

네트워크·프로토콜

**프로토·와이어 정합 (필수)**  
- **`TcpPacket`에서 `magic` 필드 제거** (varint로는 고정 4바이트 매직이 될 수 없음). 메시지는 예시대로 **`seq`(1), `robot_id`(2), `oneof payload`(필드 번호 재배치)** 로 정리한다.  
- **`UdpTelemetryPacket`에서 `magic` 필드 제거**; `robot_id`·`oneof telemetry`의 **필드 번호를 재정렬**해 깨진 참조가 없게 한다. 문서 상수 **UDP_MAGIC = 0xDDCCBBAA** 는 **Protobuf 바깥 고정 4바이트 BE 헤더**로만 전송·검증한다.  
- **TCP 프레이밍 (확정)**: `[4-byte BE uint32 length = L][L bytes payload]` 이고, **`payload = [4-byte BE uint32 TCP_MAGIC=0xAABBCCDD][TcpPacket.SerializeToString()]`** 즉 `L = 4 + len(serialized TcpPacket)` . 수신측은 `L` 바이트를 모은 뒤 앞 4바이트가 매직인지 검사하고 나머지를 `TcpPacket.ParseFromString` — 연결별 버퍼로 partial read/write 처리.  
- **UDP 데이터그램**: **`[4-byte BE UDP_MAGIC][UdpTelemetryPacket.SerializeToString()]`** 전체가 하나의 datagram. `asyncio.DatagramProtocol`로 수신 후 매직 검증 → 역직렬화.

(향후 CRC 등이 필요하면 동일하게 **헤더 바이트**로만 확장하고 메시지 정의와 혼동하지 않는다.)

포트/호스트: 환경변수 또는 기본값(예: TCP 9000, UDP 9001, 바인 0.0.0.0) — server/[main.py](http://main.py)와 디바이스 파라미터로 동일 키 사용.

연결 수명·하트비트

첫 유효 TcpPacket이 heartbeat 또는 status_payload이면 robot_id로 세션 등록(없으면 거부/종료).

로봇은 2초마다 Heartbeat(또는 StatusReport로 last_seen 갱신 가능) 송신.

서버: connection_manager가 last_seen 모노토닉 타임스탬프 유지, 백그라운드 코루틴이 주기적으로 검사해 5초 초과 미수신 시 DB의 해당 Robot.status = OFFLINE 및 세션 정리.

재연결 (디바이스)

pinky_mrta_comm/tcp_[client.py](http://client.py): 연결 끊김 시 지연 1,2,4,8,... 초 최대 30초 exponential backoff, 동일 robot_id 유지.

명령 플로우 (서버)

insert Command status=SENT

send TcpPacket(cmd)

write framed bytes

TcpPacket(ack)

dispatch ack

ACCEPTED -> Command ACKED

REJECTED -> Command CMD_FAILED

EXECUTED -> Task COMPLETED (+ 단계 정리)

FAILED -> Task FAILED

FastAPI

aiosqlite

connection_manager

tcp_gateway

Device

￼

SendCommandRequest → cmd_id 생성(UUID) → DB SENT → 해당 robot_id의 활성 TCP writer로 TcpPacket 송신.

CommandAck: ACCEPTED → CommandStatus.ACKED; REJECTED → CommandStatus.CMD_FAILED; EXECUTED → 연결된 task_id의 Task.status = COMPLETED(+ completed_at); FAILED → Task.status = FAILED. Command 레코드의 acked_at 등 타임스탬프 갱신.

UDP 텔레메트리 정책

server/udp_[receiver.py](http://receiver.py) + connection_manager(또는 별도 TelemetryCache)에 dict[str, TelemetryPose] / dict[str, TelemetryState]로 최신만 보관. DB 저장 없음.

**UDP 순서 역행(Time-warp) 방어 (필수 구현 조건)**  
UDP는 순서 비보장이므로, 캐시 갱신은 **무조건 단조 증가 조건**을 만족할 때만 수행한다.  
- **TelemetryPose**: `UdpTelemetryPacket`의 `pose`에 대해, 캐시에 이미 값이 있으면 **`pose.seq`가 캐시보다 클 때만** 갱신하거나, 동일 `seq`에서는 **`timestamp`(protobuf → ms)가 캐시보다 엄격히 클 때만** 갱신(권장: **seq 우선**, seq 동률/누락 시 timestamp 보조).  
- **TelemetryState**: `seq` 필드가 없으므로 **`timestamp` ms 비교로 incoming > cached 일 때만** 갱신.  
위 조건을 만족하지 않으면 패킷은 버려 관제 UI의 “역주행/순간이동”을 방지한다.

SQLite 스키마 (server/[db.py](http://db.py))

테이블: robots, tasks, task_steps, commands — proto 필드와 enum은 INTEGER로 저장. **모든 `google.protobuf.Timestamp` 컬럼은 Unix epoch 밀리초 `INTEGER` 단일 규격** (`Timestamp.ToMilliseconds()` / `FromMilliseconds()`와 1:1). Range query는 정수 비교로 수행해 TEXT ISO 대비 인덱스·필터 비용을 피함.

초기화: CREATE TABLE IF NOT EXISTS + 필요한 인덱스(commands.robot_id, tasks.status 등). **동시성**: `aiosqlite.connect` 직후(또는 첫 커서에서) **`PRAGMA journal_mode=WAL;`** 를 반드시 실행해 읽기·쓰기 병행성을 확보하고 FastAPI 다중 요청 시 `database is locked` 빈도를 낮춘다(단일 파일 한계는 여전히 있으나 WAL이 실질적 방패).

REST: CreateTask, GetTask, ListTasks, ListRobots, SendCommand, GetPose(캐시에서 TelemetryPose JSON/바이너리 응답 — proto GetPoseResponse 필드에 맞춤).

FastAPI (server/[main.py](http://main.py))

lifespan에서 TCP 서버 태스크 시작, UDP 엔드포인트 시작, connection_manager에 DB·캐시 주입.

요청/응답 바디는 JSON으로 DTO 필드를 매핑(내부적으로는 CreateTaskRequest 등 protobuf 메시지를 채워 재사용 가능).

**서버**는 여전히 asyncio + aiosqlite 중심(업무 스레드 풀을 도입하지 않음). **디바이스**는 아래 스레드 모델로 CPU busy-wait를 제거.

ROS2 디바이스 (pinky_mrta_comm/ros_bridge_[node.py](http://node.py))

노드명: pinky_comm_node (launch/entry에서 name='pinky_comm_node').

**ROS ↔ asyncio 분리 (Best Practice)**  
- **데몬 스레드**에서 `rclpy` 노드를 `SingleThreadedExecutor`에 등록하고 **`executor.spin()`** 으로 **블로킹** 구동(타임아웃 0의 `spin_once` 폴링 루프 금지 → RPi5 등에서 코어 100%·발열 방지).  
- **메인 스레드**에서 `asyncio.run()`(또는 동등)으로 TCP/UDP 비동기 통신 전담.  
- ROS 콜백(스레드 A) → `loop.call_soon_threadsafe` / **`asyncio.run_coroutine_threadsafe`** 로 **스레드 안전한 `asyncio.Queue`**(또는 동기 `queue.Queue` + async 측 `await queue.get()` 래퍼)에 푸시 → asyncio 태스크가 UDP 송신·TCP Status 송신 처리.  
- 반대 방향(TCP에서 수신한 Command → ROS publish)은 asyncio에서 **`node.create_publisher`의 `publish()`는 스레드 안전**이므로 주의 깊게 직접 호출하거나, 동일 큐로 ROS 스레드에 위임하는 중 하나로 일관되게 설계(구현 시 한 경로로 고정).  
- 종료 시: asyncio 쪽 셧다운 신호 → ROS 스레드 `rclpy.shutdown()` / executor interrupt 순서 명시.

Subscribe

/odom (nav_msgs/Odometry) → TelemetryPose (map 좌표: pose.pose.position + yaw, twist.twist) → 10Hz UDP.

/battery (std_msgs/Float32 권장; int(round(data))로 battery_percent) → TelemetryState → 1Hz UDP.

/task_status (pinky_interfaces/RobotTaskStatus) → StatusReport → TCP TcpPacket.

**ROS2 QoS (필수)** — 큐에 쌓인 **과거 샘플**이 뒤늦게 처리되어 “늙은 odom”이 UDP로 나가는 것을 막기 위해, [`ros_bridge_node.py`](device/pinky_pro_robot/src/pinky_mrta_comm/pinky_mrta_comm/ros_bridge_node.py)에서 **`/odom` 및 `/battery` 구독 생성 시 반드시 `rclpy.qos.qos_profile_sensor_data`를 사용**한다. 이 프로파일은 **Reliability: BEST_EFFORT**, **History: KEEP_LAST**, **depth: 1~5**(구현 시 1 또는 소량으로 고정해 지연·메모리 트레이드오프를 명시)에 해당하며, 센서류 토픽에 맞는 지연 방어용 방패로 문서화한다. `/task_status`·`/robot_command`는 명령/상태 성격에 맞는 별도 QoS(기본 또는 RELIABLE)를 주석으로 구분해 선택한다.

Publish

/robot_command (pinky_interfaces/RobotCommand) ← TCP 수신 Command 매핑.

tcp_[client.py](http://client.py): **와이어**: `L` 길이 프리픽스 + `payload`(4바이트 TCP_MAGIC + `TcpPacket` 바이트) 송수신; partial read/write 버퍼; 파싱된 `TcpPacket`에서 `cmd_payload` 처리·재연결 백오프.

udp_[sender.py](http://sender.py): **와이어**: datagram = 4바이트 UDP_MAGIC + `UdpTelemetryPacket.SerializeToString()`; 비동기 `sendto`/DatagramTransport.

메시지 설계 제안 (간단·명시적)

RobotCommand.msg: string cmd_id, string task_id, string robot_id, uint8 command (CommandType enum 값), string target_id

RobotTaskStatus.msg: string robot_id, uint8 robot_status, uint8 fsm_state, string current_task, int32 battery, uint8 last_error

빌드 후 브리지에서 protobuf enum과 상호 변환.

빌드·실행 (구현 후 사용자 안내 문구)

Proto 생성: 위 **「빌드 전 필수 확인」**의 `grpc_tools.protoc` 블록을 표준으로 둔다(단순 `protoc -I server/proto`만으로는 `timestamp.proto` 실패 가능).

서버: cd server && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn main:app --host 0.0.0.0 --port 8080

ROS: colcon build --packages-select pinky_interfaces pinky_mrta_comm, source install/setup.bash, ros2 run pinky_mrta_comm pinky_comm_node --ros-args -p robot_id:=PNK01 -p server_host:=... (+ 필요 시 /battery 리맵 또는 토픽 이름 파라미터화).

## 리스크·주의

- `pinkylib` 등 기존 배터리 노드와 병행 시 **토픽 이름**을 파라미터로 맞추는 것이 안전합니다.
- **Protobuf Python import (`ModuleNotFoundError`)**  
  - `protoc --python_out=server` 시 생성물이 `robotcafe/db/v1/*.py` 트리를 형성하므로 **런타임 `PYTHONPATH`는 반드시 `server/` 디렉터리**를 가리키게 고정(README/launch 스크립트에 명시).  
  - `robotcafe/`, `robotcafe/db/`, `robotcafe/db/v1/` 각 단계에 **`__init__.py` 배치**로 패키지 네임스페이스를 명확히 하고, 상호 참조하는 `*_pb2.py` 간 **상대/절대 import가 깨지지 않는지** `python -c "import robotcafe.db.v1.robotcafe_pb2"` 스모크 테스트를 구현 체크리스트에 포함.  
  - `import "google/protobuf/timestamp.proto"` 컴파일: **기본 경로는 `python -m grpc_tools.protoc`**; 순수 `protoc`를 쓸 경우에만 `-I`에 **Well-known types 루트**를 수동 추가한다.  
  - **`--experimental_allow_proto3_optional`**: 현재 붙여주신 `.proto`에는 proto3 `optional` 필드가 없으므로 **필수 아님**. 향후 `optional` 키워드를 추가하고 구형 `protoc`를 쓸 때만 필요 여부를 재점검.
- **원초 요구「thread 사용 금지」와의 관계**: 디바이스 측은 본 계획대로 **ROS 전용 데몬 스레드 1개**를 허용하는 것이 운영·전력 특성상 타당. 서버 측은 불필요한 스레드 확장 없이 asyncio 유지.

## 구현 순서

1. **게이트 통과**: `.proto` 수정(magic 제거·필드 재번호) → `server/robotcafe{,/db,/db/v1}/__init__.py` 3개 → `grpc_tools.protoc` → `PYTHONPATH=server` import 스모크.
2. `db.py` 스키마 + `PRAGMA journal_mode=WAL` + CRUD.
3. `connection_manager.py` 세션·캐시·하트비트 감시.
4. `tcp_gateway.py` 프레이밍 + `TcpPacket` 라우팅.
5. `udp_receiver.py` + 단조 캐시 갱신(시퀀스/타임스탬프).
6. `main.py` FastAPI + lifespan 연동.
7. `pinky_interfaces` msg 추가 및 빌드.
8. `pinky_mrta_comm` 패키지 + 세 파일 + `setup.py`/`package.xml` 엔트리포인트.
9. 로컬에서 `uvicorn`과 `ros2 run` 스모크 검증(연결, 하트비트, SendCommand 라운드트립).

