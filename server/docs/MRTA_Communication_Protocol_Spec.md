# MRTA / Robot Café 통신 패키지 프로토콜 명세서

| 항목 | 내용 |
|------|------|
| 문서 버전 | 1.2 |
| 대상 코드베이스 | `ros-repo-1` — `server/`, `device/rostaurant/.../rostaurant_networking/` |
| 스키마 원본 | `server/proto/robotcafe/db/v1/robotcafe.proto` |
| DB 구현 | SQLite `mrta.db` (`server/db.py`) |
| 변경 이력 | v1.0 초안 / v1.1 places·waypoints·menu_items / **v1.2** 보안·`Heartbeat.connection_token` |

---

## 1. 프로토콜 요약

| 항목 | 내용 |
|------|------|
| TCP 용도 | 로봇 ↔ 서버: 명령(`Command`), ACK(`CommandAck`), 상태(`StatusReport`), 하트비트(`Heartbeat`) |
| UDP 용도 | 로봇 → 서버: 고속 텔레메트리(`UdpTelemetryPacket`) |
| 애플리케이션 인코딩 | **Protobuf 3** (`TcpPacket`, `UdpTelemetryPacket`) |
| TCP 프레임 | `[BE uint32 L][L bytes payload]` — `payload = [4B TCP_MAGIC 0xAABBCCDD][TcpPacket]` |
| UDP 데이터그램 | `[4B UDP_MAGIC 0xDDCCBBAA][UdpTelemetryPacket]` |
| 기본 포트 | TCP **9000** (`MRTA_TCP_PORT`), UDP **9001** (`MRTA_UDP_PORT`) |
| 하트비트 타임아웃 | 5초 무응답 → 로봇 OFFLINE 처리 |

### 1.1 보안·방화벽 (요약)

- **REST(기본 8000)**: `Authorization: Bearer <api_key>` 필수(문서화된 예외: `GET /health`만 비인증·최소 응답).
- **TCP 9000 / UDP 9001**: 로봇 평면은 기본 **무인증**이므로, 운영망에서는 **서버 인바운드 제한**, **사설망/VPN**, 선택적으로 **`MRTA_REQUIRE_ROBOT_TOKEN=1`** + `POST /robots/{id}/rotate-connection-token`으로 발급한 토큰을 브리지 `connection_token` 파라미터로 넣는 것을 권장.
- **`MRTA_UDP_REQUIRE_ACTIVE_SESSION=1`**: 해당 `robot_id`에 **활성 TCP 세션**이 있을 때만 UDP 텔레메트리를 반영(스푸핑 완화, TCP 먼저 연결 필요).

---

## 2. TCP 와이어 프레임 (고정 부)

| Offset (payload 기준) | Size | 필드명 | 타입 | 설명 |
|------------------------|------|--------|------|------|
| 0x00 | 4 | `tcp_magic` | uint32 BE | `0xAABBCCDD` 고정 |
| 0x04 | `L−4` | `tcp_packet` | bytes | `TcpPacket.ParseFromString()` |

---

## 3. UDP 데이터그램 (고정 부)

| Offset | Size | 필드명 | 타입 | 설명 |
|--------|------|--------|------|------|
| 0x00 | 4 | `udp_magic` | uint32 BE | `0xDDCCBBAA` 고정 |
| 0x04 | 나머지 | `udp_packet` | bytes | `UdpTelemetryPacket.ParseFromString()` |

---

## 4. `TcpPacket` — oneof payload

| 필드 # | 필드명 | 하위 메시지 | 방향 | 요약 |
|--------|--------|--------------|------|------|
| 3 | `cmd_payload` | `Command` | Server→Robot | 명령 전달 |
| 4 | `ack_payload` | `CommandAck` | Robot→Server | 명령 처리 결과 |
| 5 | `status_payload` | `StatusReport` | Robot→Server | 상태·배터리·FSM |
| 6 | `heartbeat` | `Heartbeat` | Robot→Server | 연결 유지 |

---

## 5. TCP 하위 메시지 — 필드 및 DB 매핑

### 5.1 `Heartbeat`

| 필드명 | # | 타입 | DB 매핑 |
|--------|---|------|---------|
| `robot_id` | 1 | string | — |
| `timestamp` | 2 | uint64 | 서버에서 `robots.last_seen_ms` 갱신 |
| `connection_token` | 3 | string | `MRTA_REQUIRE_ROBOT_TOKEN=1`일 때 **첫 Heartbeat에 필수**. 서버는 `robots.connection_token_hash`(SHA-256)와 비교 |

### 5.2 `StatusReport`

| 필드명 | # | 타입 | DB 매핑 |
|--------|---|------|---------|
| `robot_id` | 1 | string | `robots.robot_id` |
| `robot_status` | 2 | `RobotStatus` | `robots.status` |
| `fsm_state` | 3 | `FsmState` | `robots.fsm_state` |
| `current_task` | 4 | string | `robots.current_task_id` |
| `battery` | 5 | int32 | `robots.battery_last` |
| `last_error` | 6 | `ErrorCode` | 로그용 |
| `reported_at` | 7 | `Timestamp` | `robots.last_seen_ms` |

### 5.3 `Command`

| 필드명 | # | 타입 | DB 매핑 |
|--------|---|------|---------|
| `cmd_id` | 1 | string | `commands.cmd_id` (PK) |
| `task_id` | 2 | string | `commands.task_id` → FK `tasks.task_id` |
| `robot_id` | 3 | string | `commands.robot_id` |
| `command` | 4 | `CommandType` | `commands.command` |
| `target_id` | 5 | string | `commands.target_id` (**`places.place_id`** 슬러그 권장) |
| `status` | 6 | `CommandStatus` | `commands.status` |
| `sent_at` | 7 | `Timestamp` | `commands.sent_at_ms` |
| `acked_at` | 8 | `Timestamp` | `commands.acked_at_ms` |

### 5.4 `CommandAck`

| 필드명 | # | 타입 | DB 매핑 |
|--------|---|------|---------|
| `cmd_id` | 1 | string | `commands` 조회 키 |
| `robot_id` | 2 | string | 로그 |
| `status` | 3 | `AckStatus` | `commands.status` + `tasks.status` 갱신 |
| `reason` | 4 | `ErrorCode` | 로그 |
| `acked_at` | 5 | `Timestamp` | `commands.acked_at_ms` |

---

## 6. UDP `UdpTelemetryPacket`

### `TelemetryPose`

| 필드명 | # | 타입 | 비고 |
|--------|---|------|------|
| `robot_id` | 1 | string | 캐시 키 |
| `seq` | 2 | uint32 | 최신성 판단 |
| `timestamp` | 3 | `Timestamp` | — |
| `x`,`y`,`theta` | 4–6 | double | **map 프레임** 기준 (좌표계는 `places` 테이블과 동일) |
| `linear_x`,`angular_z` | 7–8 | double | 속도 |

### `TelemetryState`

| 필드명 | # | 타입 | 비고 |
|--------|---|------|------|
| `robot_id` | 1 | string | 캐시 키 |
| `timestamp` | 2 | `Timestamp` | — |
| `battery_percent` | 3 | int32 | 메모리 캐시 |
| `current_state` | 4 | `RobotStatus` | 캐시 |
| `current_fsm` | 5 | `FsmState` | 캐시 |
| `current_step` | 6 | string | 캐시 |
| `task_id` | 7 | string | 캐시 |

---

## 7. 주기·트리거

| 메시지 | 방향 | 주기 / 트리거 | 비고 |
|--------|------|---------------|------|
| `Heartbeat` | Robot→Server | 2초 주기 | 5초 미수신 → OFFLINE |
| `StatusReport` | Robot→Server | 상태 변경 시 | `robots` DB 반영 |
| `Command` | Server→Robot | REST `POST /commands/send` | 세션 없으면 실패 |
| `CommandAck` | Robot→Server | 명령 처리 후 | `commands`/`tasks` 갱신 |
| UDP 텔레메트리 | Robot→Server | 고주기 | 메모리 캐시만 |

---

## 8. SQLite DB 테이블 매핑 (전체)

### 8.1 `users`

| 컬럼 | 타입 | 키 | 설명 |
|------|------|----|------|
| `user_id` | TEXT | PK | UUID |
| `prefix` | TEXT | — | 호칭 |
| `name` | TEXT | — | 표시명 |
| `role` | INTEGER | — | `UserRole` enum (CUSTOMER=1…ADMIN=4) |
| `api_key_hash` | TEXT | UNIQUE | SHA-256 해시 |
| `created_at_ms` | INTEGER | — | Unix ms |
| `is_active` | INTEGER | — | 0/1 |

### 8.2 `robots`

| 컬럼 | 타입 | 키 | 설명 |
|------|------|----|------|
| `robot_id` | TEXT | PK | 로봇 ID |
| `model` | TEXT | — | 모델명 |
| `status` | INTEGER | — | `RobotStatus` |
| `battery_last` | INTEGER | — | 배터리 % |
| `last_seen_ms` | INTEGER | — | NULL 가능 |
| `current_task_id` | TEXT | — | 수행 중 task_id |
| `fsm_state` | INTEGER | — | `FsmState` |
| `connection_token_hash` | TEXT | — | TCP 연결 토큰 SHA-256(평문은 저장 안 함). `rotate-connection-token`으로 설정 |

### 8.3 `tasks`

| 컬럼 | 타입 | 키 | 설명 |
|------|------|----|------|
| `task_id` | TEXT | PK | UUID |
| `requester_id` | TEXT | 인덱스 | `users.user_id` |
| `task_type` | INTEGER | — | `TaskType` |
| `dest_id` | TEXT | — | **`places.place_id`** 슬러그 (활성 장소만 허용) |
| `status` | INTEGER | 인덱스 | `TaskStatus` |
| `priority` | INTEGER | — | `TaskPriority` |
| `robot_id` | TEXT | — | 배정 로봇 |
| `created_at_ms` | INTEGER | 인덱스 | Unix ms |
| `updated_at_ms` | INTEGER | — | Unix ms |
| `completed_at_ms` | INTEGER | — | NULL 가능 |

### 8.4 `task_steps`

| 컬럼 | 타입 | 키 | 설명 |
|------|------|----|------|
| `task_id` | TEXT | PK(복합), FK | CASCADE 삭제 |
| `step_num` | INTEGER | PK(복합) | 0, 1, 2… |
| `step_name` | TEXT | — | 단계명 |
| `status` | INTEGER | — | `StepStatus` |
| `dest_id` | TEXT | — | 단계 목적지 |
| `started_at_ms` | INTEGER | — | NULL 가능 |
| `completed_at_ms` | INTEGER | — | NULL 가능 |
| `error_code` | INTEGER | — | `ErrorCode` |
| `error_msg` | TEXT | — | 오류 메시지 |

### 8.5 `commands`

| 컬럼 | 타입 | 키 | 설명 |
|------|------|----|------|
| `cmd_id` | TEXT | PK | UUID |
| `task_id` | TEXT | FK | `tasks.task_id` |
| `robot_id` | TEXT | 인덱스 | 대상 로봇 |
| `command` | INTEGER | — | `CommandType` |
| `target_id` | TEXT | — | `places.place_id` 권장 |
| `status` | INTEGER | — | `CommandStatus` |
| `sent_at_ms` | INTEGER | — | Unix ms |
| `acked_at_ms` | INTEGER | — | NULL 가능 |

### 8.6 `places` *(v1.1 추가)*

로봇 주행 목적지 17곳의 메타데이터. 좌표는 맵 확정 후 REST(`PATCH /places/{id}`)로 저장.

| 컬럼 | 타입 | 키 | 설명 |
|------|------|----|------|
| `place_id` | TEXT | PK | 슬러그 (예: `TBL_01`, `DISP_03`) |
| `name` | TEXT | — | 표시명 |
| `zone` | INTEGER | 인덱스 | `ZoneType` enum |
| `x` | REAL | — | **NULL 허용** — map 프레임 x |
| `y` | REAL | — | **NULL 허용** — map 프레임 y |
| `theta` | REAL | — | **NULL 허용** — 방향(rad) |
| `max_speed` | REAL | — | NULL 허용 |
| `is_active` | INTEGER | 인덱스 | 0/1 — 비활성 시 작업 목적지 불가 |
| `sort_order` | INTEGER | — | 관제 UI 정렬 순서 |
| `created_at_ms` | INTEGER | — | Unix ms |
| `updated_at_ms` | INTEGER | — | Unix ms |

**시드 17곳 (초기 x,y,theta=NULL)**

| place_id | name | zone |
|----------|------|------|
| `WAIT_A` | 대기 A | ZONE_CORRIDOR=6 |
| `WAIT_B` | 대기 B | ZONE_CORRIDOR=6 |
| `KIOSK_1` | 키오스크(출입구) | ZONE_DISPLAY=4 |
| `TBL_01`~`TBL_05` | 테이블 1~5 | ZONE_TABLE=1 |
| `TOILET` | 화장실 | ZONE_TOILET=3 |
| `EXIT_DINE` | 퇴식구 | ZONE_CORRIDOR=6 |
| `KITCHEN` | 주방 | ZONE_KITCHEN=2 |
| `DISP_01`~`DISP_06` | 진열장 1~6 | ZONE_DISPLAY=4 |

### 8.7 `place_waypoints` *(v1.1 추가)*

각 장소에 도달하기까지 거쳐야 할 경유점(1:N). proto `Waypoint`와 1:1 대응.

| 컬럼 | 타입 | 키 | 설명 |
|------|------|----|------|
| `wp_id` | INTEGER | PK (AUTOINCREMENT) | 자동 증가 |
| `place_id` | TEXT | FK → `places` | ON DELETE CASCADE |
| `seq` | INTEGER | — | 경유 순서 (0, 1…). `(place_id,seq)` UNIQUE |
| `label` | TEXT | — | 경유점 이름 (예: `"approach"`, `"dock"`) |
| `x` | REAL | — | **NULL 허용** |
| `y` | REAL | — | **NULL 허용** |
| `theta` | REAL | — | **NULL 허용** |

### 8.8 `menu_items` *(v1.1 추가)*

메뉴 6개와 진열장 6곳의 **1:1 매핑**. `place_id UNIQUE` 제약으로 중복 매핑 방지.

| 컬럼 | 타입 | 키 | 설명 |
|------|------|----|------|
| `menu_id` | INTEGER | PK (AUTOINCREMENT) | 메뉴 번호 |
| `name` | TEXT | — | 메뉴 이름 |
| `place_id` | TEXT | FK → `places`, UNIQUE | 매핑된 진열장 (`DISP_*`) |
| `is_available` | INTEGER | — | 0/1 — 품절/활성 |
| `sort_order` | INTEGER | — | 메뉴판 순서 |

**시드 (메뉴명은 운영 전 `PATCH /menu-items/{id}`로 교체)**

| menu_id | name | place_id |
|---------|------|----------|
| 1 | 메뉴 1 | `DISP_01` |
| 2 | 메뉴 2 | `DISP_02` |
| 3 | 메뉴 3 | `DISP_03` |
| 4 | 메뉴 4 | `DISP_04` |
| 5 | 메뉴 5 | `DISP_05` |
| 6 | 메뉴 6 | `DISP_06` |

---

## 9. REST API 요약 (전체)

| Method | 경로 | 최소 역할 | 설명 |
|--------|------|-----------|------|
| POST | `/tasks` | CUSTOMER | 작업 생성 (`dest_id` → `places` 검증) |
| GET | `/tasks` | CUSTOMER | 작업 목록 (CUSTOMER는 본인 것만) |
| GET | `/tasks/{id}` | CUSTOMER | 단건 조회 |
| GET | `/robots` | STAFF_FLOOR | 로봇 목록 |
| POST | `/robots/{id}/rotate-connection-token` | ADMIN | 로봇 TCP용 연결 토큰 재발급(평문 1회 응답) |
| GET | `/telemetry/pose/{id}` | STAFF_FLOOR | 최신 pose |
| POST | `/commands/send` | ADMIN | 명령 전송 |
| GET | `/users` | ADMIN | 사용자 목록 |
| POST | `/users` | ADMIN | 사용자 생성 |
| PATCH | `/users/{id}/deactivate` | ADMIN | 비활성화 |
| GET | `/places` | CUSTOMER | 장소 목록 (`?active_only=true`) |
| GET | `/places/{id}` | CUSTOMER | 장소 단건 |
| PATCH | `/places/{id}` | ADMIN | 좌표·메타 수정 |
| GET | `/places/{id}/waypoints` | CUSTOMER | 경유점 목록 |
| PUT | `/places/{id}/waypoints` | ADMIN | 경유점 일괄 교체 |
| GET | `/menu-items` | CUSTOMER | 메뉴 목록 |
| PATCH | `/menu-items/{id}` | ADMIN | 메뉴명·장소 수정 |
| GET | `/health` | — (no auth) | `{"status":"ok"}` 만 반환 |
| GET | `/health/detail` | STAFF_FLOOR | `connected_robots` 포함 |

### 9.1 서버 환경 변수 (보안·운영)

| 변수 | 기본 | 설명 |
|------|------|------|
| `MRTA_DISABLE_OPENAPI` | (unset) | `1`이면 `/docs`, `/redoc`, `/openapi.json` 비활성 |
| `MRTA_ENV` | (unset) | `production`이면 OpenAPI 비활성(위와 동일 효과) |
| `MRTA_ADMIN_KEY_OUT` | (unset) | 최초 관리자 생성 시 API 키를 이 경로에 `0600`으로 기록 |
| `MRTA_MAX_TCP_FRAME_BYTES` | `2097152` | TCP 프레임 최대 길이(바이트), 상한 16MiB |
| `MRTA_REQUIRE_ROBOT_TOKEN` | (unset) | `1`이면 TCP 세션 등록 시 Heartbeat의 `connection_token` 필수 |
| `MRTA_UDP_REQUIRE_ACTIVE_SESSION` | (unset) | `1`이면 활성 TCP 세션이 있는 `robot_id`의 UDP만 캐시 반영 |

로봇 브리지·`TcpClient`는 동일하게 `MRTA_MAX_TCP_FRAME_BYTES`를 읽습니다.

---

## 10. 부록 A — 열거형 정수값

### `RobotStatus`
IDLE=1, MOVING=2, ARRIVED=3, CHARGING=4, ERROR=5, OFFLINE=6

### `TaskStatus`
PENDING=1, IN_PROGRESS=2, COMPLETED=3, FAILED=4, CANCELLED=5

### `TaskType`
KIOSK_TO_TABLE=1, TABLE_TO_TOILET=2, TABLE_TO_DISPLAY=3, DISH_PICKUP=4, ROBOT_SWAP=5, ESCORT_SERVICE=6, RETURN_TO_DOCK=7

### `TaskPriority`
LOW=1, NORMAL=2, HIGH=3, URGENT=4

### `CommandType`
MOVE_TO=1, CANCEL=2, RESET=3, RETURN_DOCK=4, EMERGENCY_STOP=5

### `CommandStatus`
SENT=1, ACKED=2, CMD_FAILED=3

### `AckStatus`
ACCEPTED=1, REJECTED=2, EXECUTED=3, ACK_FAILED=4

### `ZoneType`
ZONE_TABLE=1, ZONE_KITCHEN=2, ZONE_TOILET=3, ZONE_DISPLAY=4, ZONE_DOCK=5, ZONE_CORRIDOR=6

### `FsmState`
FSM_IDLE=1, FSM_LOAD_WAYPOINTS=2, FSM_MOVING_TO_WP=3, FSM_WAYPOINT_REACHED=4, FSM_ARRIVED=5, FSM_RETURNING=6, FSM_NAV_FAILED=7, FSM_RESOLVE_DEST=8

### `ErrorCode` (주요)
ERR_NONE=0, ERR_NETWORK=101, ERR_NAV_FAILED=201, ERR_OBSTACLE=202, ERR_TIMEOUT=203, ERR_GOAL_REJECTED=204, ERR_LOW_BATTERY=301, ERR_HARDWARE=401, ERR_UNKNOWN=999

---

## 변경 이력

| 버전 | 날짜 | 내용 |
|------|------|------|
| 1.0 | 2026-04-12 | 초안 |
| 1.1 | 2026-04-12 | places·place_waypoints·menu_items 테이블 추가, REST 목록 갱신 |
| 1.2 | 2026-04-12 | 보안: OpenAPI 비활성·health 분리·TCP 프레임 상한·로봇 연결 토큰·UDP 세션 옵션, `Heartbeat.connection_token` |
