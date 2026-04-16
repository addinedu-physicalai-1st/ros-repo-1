# UDP Multicast 이미지 전송 설계

**날짜:** 2026-04-16  
**대상:** camera_node → child_detection_node (및 이후 추가될 수신 노드)  
**동기:** ROS DDS 미들웨어의 이미지 직렬화/역직렬화 오버헤드 제거

---

## 문제

`/image` ROS 토픽(CompressedImage)을 통한 이미지 전송이 DDS 미들웨어 오버헤드로 인해 네트워크 부하를 유발한다. 같은 로봇 내 여러 노드가 동일 이미지를 구독하므로 부하가 누적된다.

## 해결 방법

`/image` ROS 토픽만 **UDP Multicast**로 대체한다. 나머지 제어 메시지(/scan, child_safety_zone, LED/emotion 서비스 등)는 ROS 그대로 유지한다.

---

## 아키텍처

```
camera_node ──UDP Multicast──► [239.255.0.1:5000]
                                      │
                          ┌───────────┼────────────┐
                          ▼           ▼             ▼
              child_detection   event_recorder   (기타 노드)
```

- 그룹 주소: `239.255.0.1` (사설 멀티캐스트 대역)
- 포트: `5000`
- TTL: `1` (로컬 네트워크 밖으로 나가지 않음)
- Loopback: ON (같은 머신에서 수신 가능)

---

## 패킷 포맷

```
[frame_id: uint32 BE][data_len: uint32 BE][JPEG bytes...]
      4 bytes               4 bytes           가변
```

- 총 크기 = 8 bytes (헤더) + N bytes (JPEG)
- 640×360 JPEG q=90 ≈ 30~60 KB → loopback UDP 한도(65,499 bytes) 이내
- 한도 초과 시: 경고 로그 후 프레임 드롭 (재전송 없음)

---

## 송신 (camera_node)

- 기존 ROS CompressedImage publisher 제거
- UDP multicast 소켓으로 대체
- 타이머 콜백에서 JPEG 인코딩 후 단일 sendto() 호출

## 수신 (child_detection_node 등)

- 기존 `/image` ROS subscription 제거
- 백그라운드 daemon thread에서 recvfrom() 블로킹 대기
- 프레임 수신 시 threading.Lock으로 보호하여 `_latest_frame`, `_last_frame_t` 갱신
- 메인 스레드(rclpy.spin)에서 YOLO 추론 및 ROS 퍼블리시 유지

## Fail-safe

- 기존 1초 camera watchdog (`_heartbeat_callback`) 그대로 유지
- `_last_frame_t` 갱신을 UDP 스레드에서 수행 → watchdog 동작 변화 없음
