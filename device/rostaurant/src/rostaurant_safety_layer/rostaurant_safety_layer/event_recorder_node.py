#!/usr/bin/env python3

# Copyright 2026 PinkLab
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Event Recorder Node — Raspberry Pi 최적화 안전 이벤트 기록기.

/safety_stop_event 가 True 가 되는 순간 직전 60초 영상과 라이다를
자동으로 파일로 저장합니다.

Architecture
------------

  rostaurant_camera node
      │  /image (CompressedImage, JPEG q=90)
      │  _image_callback  →  self._latest_frame (BGR ndarray)
      ▼
  ┌─────────────────────────────────────┐
  │  rolling_buffer  (deque, 60 s)      │  ← 라이다 스캔도 함께 보관
  │  entry: (timestamp, jpeg_bytes,     │
  │          LaserScan | None)          │
  └─────────────────────────────────────┘
      │                      ▲
      │ safety_stop_event=True         /scan  /map  /amcl_pose
      ▼
  ┌───────────────────────────────────────────────────────────┐
  │  EventRecorder                                            │
  │  1) buffer → video.mp4      (카메라 VideoWriter)           │
  │  2) buffer → lidar_visual.mp4 (LiDAR VideoWriter)        │
  │     둘 다 동시에 시작, 동시에 종료 → 동일한 길이 보장          │
  │  3) 이벤트 진행 중 live 카메라 → video.mp4 계속 기록          │
  │  4) 이벤트 진행 중 live LiDAR 시각화 → lidar_visual.mp4     │
  │  5) safety_stop_event=False → 파일 닫기 / lidar.csv 저장    │
  └───────────────────────────────────────────────────────────┘

동기화 보장
-----------
* _flush_buffer_to_video() 에서 카메라·LiDAR 모두 동시에 씁니다.
* _capture_tick() 에서 카메라·LiDAR 모두 동시에 씁니다.
* LiDAR 프레임은 절대 건너뛰지 않습니다 (검정 fallback 사용).
* 결과: 두 비디오의 프레임 수·시작/종료 시점이 완전히 일치합니다.

맵 렌더링
---------
* /map 토픽은 Nav2 가 transient_local QoS 로 발행합니다.
  → 이 노드도 transient_local QoS 로 구독해야 늦게 참여해도 맵을 수신합니다.
* 맵이 바뀔 때만 BGR canvas 를 재빌드하고 캐시합니다 (_map_canvas).
  → 매 프레임마다 OccupancyGrid 재변환 불필요 (Raspberry Pi 성능 절약).
* 렌더링 순서: map(배경) → LiDAR points(빨강) → robot(초록).

ROS Parameters
--------------
capture_rate_hz   float  10.0    초당 버퍼 저장 횟수 (타이머 주기)
buffer_seconds    float  60.0    롤링 버퍼 유지 시간(초)
output_dir        str    "safety_events"  저장 루트 디렉터리
jpeg_quality      int    80      JPEG 재압축 품질 (0–100)

Topics
------
Subscribe  UDP 239.255.0.1:5000  JPEG 압축 카메라 이미지 (백그라운드 스레드)
Subscribe  /scan               sensor_msgs/LaserScan
Subscribe  /map                nav_msgs/OccupancyGrid   (transient_local QoS)
Subscribe  /amcl_pose          geometry_msgs/PoseWithCovarianceStamped
Subscribe  /safety_stop_event  std_msgs/Bool
"""

import csv
import math
import os
import socket
import struct
import threading
import time
from collections import deque
from datetime import datetime

import cv2
import numpy as np
import rclpy
import tf2_ros
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_ros import TransformException

# ── UDP Multicast ──────────────────────────────────────────────────────────────
MULTICAST_GROUP = '239.255.0.1'
MULTICAST_PORT  = 5000

# ── 기본 상수 ─────────────────────────────────────────────────────────────────
FRAME_W = 640
FRAME_H = 480
FOURCC = cv2.VideoWriter_fourcc(*'mp4v')

# LiDAR 시각화 캔버스 크기 (정사각형 top-down 뷰)
LIDAR_VIZ_W = 640
LIDAR_VIZ_H = 640

# 로봇 중심 크롭 반경 (픽셀). 이 값의 2배 범위를 출력 해상도로 리사이즈.
CROP_SIZE = 200

# TF fallback 렌더링 시 픽셀/미터 스케일 (로컬 프레임)
LOCAL_SCALE = 40.0  # px/m

SCAN_TOPIC = 'scan'
MAP_TOPIC = '/map'
AMCL_POSE_TOPIC = '/amcl_pose'
CHILD_SAFETY_ZONE_TOPIC = 'child_safety_zone'
STOP_EVENT_FALSE_HOLD_S = 3.0
STOP_DEBOUNCE_S = 0.5          # STOP 첫 수신 후 이 시간이 지나야 녹화 시작

ZONE_STOP = 'STOP'

# /map 은 Nav2 가 transient_local (latched) QoS 로 발행합니다.
# 구독자도 동일 QoS 를 사용해야 늦게 참여해도 마지막 메시지를 수신합니다.
_MAP_QOS = QoSProfile(
    durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
    reliability=QoSReliabilityPolicy.RELIABLE,
    history=QoSHistoryPolicy.KEEP_LAST,
    depth=1,
)

# 맵 메타데이터를 담는 간단한 컨테이너
class _MapMeta:
    """스케일링된 맵 canvas 의 좌표 변환에 필요한 파라미터."""

    __slots__ = ('origin_x', 'origin_y', 'res', 'scale',
                 'pad_left', 'pad_top', 'scaled_w', 'scaled_h')

    def __init__(self, origin_x, origin_y, res, scale,
                 pad_left, pad_top, scaled_w, scaled_h):
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.res = res
        self.scale = scale
        self.pad_left = pad_left
        self.pad_top = pad_top
        self.scaled_w = scaled_w
        self.scaled_h = scaled_h

    def world_to_pixel(self, wx: float, wy: float):
        """map 좌표(m) → 화면 픽셀 좌표."""
        px = int((wx - self.origin_x) / self.res * self.scale) + self.pad_left
        # flipud 에 맞춰 Y 축 반전
        py = int(self.scaled_h - (wy - self.origin_y) / self.res * self.scale) + self.pad_top
        return px, py


# ── 롤링 버퍼 항목 ─────────────────────────────────────────────────────────────
class _BufferEntry:
    """한 타이머 틱에서 수집된 데이터를 담는 경량 컨테이너."""

    __slots__ = ('timestamp', 'jpeg_bytes', 'scan')

    def __init__(self, timestamp: float, jpeg_bytes: bytes, scan):
        self.timestamp = timestamp    # float (time.monotonic)
        self.jpeg_bytes = jpeg_bytes  # bytes — JPEG 압축된 프레임
        self.scan = scan              # LaserScan | None


class EventRecorderNode(Node):
    """
    롤링 버퍼 기반 안전 이벤트 기록 노드.

    평소에는 프레임을 JPEG 압축 후 60초 deque에 보관합니다.
    /safety_stop_event == True 가 되면:
      · 카메라·LiDAR 버퍼 → video.mp4 / lidar_visual.mp4 (동시에)
      · 이후 live 카메라·LiDAR → 각 파일에 계속 기록
    False 가 되면 두 파일을 동시에 닫습니다.
    """

    def __init__(self):
        super().__init__('event_recorder_node')

        # ── ROS Parameters ────────────────────────────────────────────────────
        self.declare_parameter('capture_rate_hz', 10.0)
        self.declare_parameter('buffer_seconds', 60.0)
        self.declare_parameter('output_dir', 'safety_events')
        self.declare_parameter('jpeg_quality', 80)

        self._capture_rate: float = (
            self.get_parameter('capture_rate_hz').get_parameter_value().double_value
        )
        self._buffer_seconds: float = (
            self.get_parameter('buffer_seconds').get_parameter_value().double_value
        )
        self._output_dir: str = (
            self.get_parameter('output_dir').get_parameter_value().string_value
        )
        self._jpeg_quality: int = (
            self.get_parameter('jpeg_quality').get_parameter_value().integer_value
        )

        # ── 내부 상태 ─────────────────────────────────────────────────────────
        _maxlen = int(self._capture_rate * self._buffer_seconds) + 1
        self._rolling_buffer: deque = deque(maxlen=_maxlen)

        self._latest_scan: LaserScan | None = None
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()  # _latest_frame 보호 (UDP 스레드 ↔ 타이머)

        # 맵·포즈 캐시
        self._map_data: OccupancyGrid | None = None
        self._pose_data: PoseWithCovarianceStamped | None = None

        # 맵 렌더링 캐시 — _map_callback 에서만 갱신됩니다.
        # OccupancyGrid 재변환 비용을 매 프레임 지불하지 않습니다.
        self._map_canvas: np.ndarray | None = None   # BGR (LIDAR_VIZ_H, LIDAR_VIZ_W, 3)
        self._map_meta: _MapMeta | None = None

        # 마지막으로 성공한 LiDAR 프레임 — 프레임 드롭 방지용 fallback
        self._last_lidar_frame: np.ndarray | None = None

        # 이벤트 기록 상태
        self._recording: bool = False
        self._video_writer: cv2.VideoWriter | None = None
        self._lidar_writer: cv2.VideoWriter | None = None
        self._event_dir: str = ''
        self._last_safety_stop_state: bool = False
        self._event_lidar_rows: list = []
        self._stop_event_false_time: float | None = None
        self._stop_first_seen_time: float | None = None   # 디바운스용

        # TF2 Buffer + TransformListener
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)

        # ── UDP Multicast 수신 스레드 ──────────────────────────────────────────
        self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._udp_sock.bind(('', MULTICAST_PORT))
        mreq = struct.pack('4sL', socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
        self._udp_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._udp_thread = threading.Thread(target=self._udp_recv_loop, daemon=True)
        self._udp_thread.start()
        self.get_logger().info(
            f'UDP multicast receiver joined {MULTICAST_GROUP}:{MULTICAST_PORT}'
        )

        # ── Subscribers ───────────────────────────────────────────────────────
        self.create_subscription(
            LaserScan, SCAN_TOPIC, self._scan_callback, 10,
        )
        self.create_subscription(
            String, CHILD_SAFETY_ZONE_TOPIC, self._safety_callback, 10,
        )
        # /map: transient_local QoS — Nav2 와 동일하게 맞춰야 메시지를 수신합니다.
        self.create_subscription(
            OccupancyGrid, MAP_TOPIC, self._map_callback, _MAP_QOS,
        )
        self.create_subscription(
            PoseWithCovarianceStamped, AMCL_POSE_TOPIC, self._pose_callback, 10,
        )

        # ── Capture timer ─────────────────────────────────────────────────────
        self.create_timer(1.0 / self._capture_rate, self._capture_tick)

        self.get_logger().info('EventRecorderNode started.')
        self.get_logger().info(f'  Image source : UDP {MULTICAST_GROUP}:{MULTICAST_PORT}')
        self.get_logger().info(
            f'  Subscribing  : {MAP_TOPIC} (transient_local QoS), '
            f'{AMCL_POSE_TOPIC}, {SCAN_TOPIC}'
        )
        self.get_logger().info(
            f'  Buffer       : {self._buffer_seconds} s  (max {_maxlen} frames)'
        )
        self.get_logger().info(f'  JPEG quality : {self._jpeg_quality}')
        self.get_logger().info(f'  Output dir   : {self._output_dir}')

    # =========================================================================
    # Subscriber callbacks
    # =========================================================================

    # =========================================================================
    # UDP 수신 루프 (백그라운드 스레드)
    # =========================================================================

    def _udp_recv_loop(self):
        """
        멀티캐스트 UDP 패킷을 블로킹 수신하여 _latest_frame 을 갱신합니다.
        패킷 포맷: [frame_id(uint32 BE)][data_len(uint32 BE)][JPEG bytes]
        """
        while True:
            try:
                packet, _ = self._udp_sock.recvfrom(65535)
            except OSError:
                break

            if len(packet) < 8:
                continue

            _frame_id, data_len = struct.unpack('>II', packet[:8])
            jpeg_bytes = packet[8:8 + data_len]

            np_arr = np.frombuffer(jpeg_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            with self._frame_lock:
                self._latest_frame = frame

    def _scan_callback(self, msg: LaserScan):
        """최신 라이다 스캔을 캐시합니다."""
        self._latest_scan = msg

    def _map_callback(self, msg: OccupancyGrid):
        """
        OccupancyGrid 메시지를 캐시하고 BGR canvas 를 즉시 재빌드합니다.

        맵은 자주 바뀌지 않으므로 여기서 한 번만 변환해 캐시합니다.
        이후 매 프레임은 캐시된 canvas 를 복사해 사용하므로 렌더링 부하가 낮습니다.
        """
        self._map_data = msg
        self._build_map_canvas()

    def _pose_callback(self, msg: PoseWithCovarianceStamped):
        """AMCL 로봇 포즈를 캐시합니다."""
        self._pose_data = msg

    def _safety_callback(self, msg: String):
        """child_safety_zone 상태 변화에 반응합니다. STOP 시 녹화를 시작합니다."""
        is_stop = (msg.data == ZONE_STOP)
        if is_stop:
            if not self._recording:
                # 처음 STOP을 본 시각을 기록해 두고, _capture_tick 에서 디바운스를 확인합니다.
                if self._stop_first_seen_time is None:
                    self._stop_first_seen_time = time.monotonic()
                    self.get_logger().info(
                        f'STOP 감지. {STOP_DEBOUNCE_S:.1f}s 유지되면 녹화를 시작합니다.'
                    )
            self._stop_event_false_time = None
        else:
            # STOP이 아닌 상태가 오면 디바운스 타이머를 초기화합니다.
            self._stop_first_seen_time = None
            if self._recording and self._last_safety_stop_state:
                self._stop_event_false_time = time.monotonic()
                self.get_logger().info(
                    f'child_safety_zone STOP 해제 감지. '
                    f'{STOP_EVENT_FALSE_HOLD_S:.1f}s 유지되면 녹화를 종료합니다.'
                )
        self._last_safety_stop_state = is_stop

    # =========================================================================
    # Capture tick (core loop)
    # =========================================================================

    def _capture_tick(self):
        """
        매 타이머 틱:
        1. self._latest_frame 에서 카메라 프레임을 가져와 롤링 버퍼에 넣습니다.
        2. 이벤트 기록 중이면 카메라·LiDAR VideoWriter 에 동시에 씁니다.
           LiDAR 프레임은 절대 건너뛰지 않습니다 (fallback 사용).
        """
        self._check_delayed_stop()

        with self._frame_lock:
            frame = self._latest_frame
        if frame is None:
            self.get_logger().warn(
                'UDP 이미지 미수신 — 프레임 없음.', throttle_duration_sec=2.0,
            )
            return

        # ── 리사이즈 → JPEG 압축 ──────────────────────────────────────────────
        if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))

        ok, jpeg_buf = cv2.imencode(
            '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        )
        if not ok:
            self.get_logger().warn('JPEG 인코딩 실패.', throttle_duration_sec=2.0)
            return

        jpeg_bytes: bytes = jpeg_buf.tobytes()
        now: float = time.monotonic()

        # ── 롤링 버퍼에 추가 ──────────────────────────────────────────────────
        entry = _BufferEntry(now, jpeg_bytes, self._latest_scan)
        self._rolling_buffer.append(entry)
        self._evict_old_entries(now)

        # ── 이벤트 기록 중 ────────────────────────────────────────────────────
        if self._recording:
            if self._video_writer is not None:
                self._video_writer.write(frame)
            if self._latest_scan is not None:
                self._event_lidar_rows.append(self._scan_to_row(self._latest_scan))

            # LiDAR 프레임은 항상 기록 (절대 건너뛰지 않음)
            if self._lidar_writer is not None:
                lidar_frame = self._render_lidar_frame(self._latest_scan)
                self._lidar_writer.write(lidar_frame)

    def _check_delayed_stop(self):
        """디바운스 후 녹화 시작 / STOP_EVENT_FALSE_HOLD_S 초 유지 후 녹화 종료."""
        # ── 디바운스: STOP_DEBOUNCE_S 경과 후 녹화 시작 ──────────────────────
        if not self._recording and self._stop_first_seen_time is not None:
            if time.monotonic() - self._stop_first_seen_time >= STOP_DEBOUNCE_S:
                self._stop_first_seen_time = None
                self._start_event()
                return

        # ── 녹화 종료 대기 ────────────────────────────────────────────────────
        if not self._recording or self._stop_event_false_time is None:
            return
        if time.monotonic() - self._stop_event_false_time >= STOP_EVENT_FALSE_HOLD_S:
            self._stop_event_false_time = None
            self._stop_event()

    # =========================================================================
    # Event lifecycle
    # =========================================================================

    def _start_event(self):
        """safety_stop_event=True: 이벤트 폴더 생성 후 버퍼를 덤프합니다."""
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._event_dir = os.path.join(
            self._output_dir, f'event_{timestamp_str}'
        )
        os.makedirs(self._event_dir, exist_ok=True)

        self.get_logger().warn(
            f'Safety event 시작 — 기록 폴더: {self._event_dir}'
        )

        # 카메라·LiDAR VideoWriter 를 동시에 초기화합니다.
        video_path = os.path.join(self._event_dir, 'video.mp4')
        self._video_writer = cv2.VideoWriter(
            video_path, FOURCC, self._capture_rate, (FRAME_W, FRAME_H)
        )
        if not self._video_writer.isOpened():
            self.get_logger().error(f'카메라 VideoWriter 초기화 실패: {video_path}')
            self._video_writer = None

        lidar_path = os.path.join(self._event_dir, f'lidar_visual_{timestamp_str}.mp4')
        self._lidar_writer = cv2.VideoWriter(
            lidar_path, FOURCC, self._capture_rate, (LIDAR_VIZ_W, LIDAR_VIZ_H)
        )
        if not self._lidar_writer.isOpened():
            self.get_logger().error(f'LiDAR VideoWriter 초기화 실패: {lidar_path}')
            self._lidar_writer = None

        self._event_lidar_rows = []
        self._recording = True
        self._stop_event_false_time = None

        # 버퍼에 쌓인 과거 60초를 카메라·LiDAR 모두 동시에 씁니다.
        # 이로써 두 영상의 프레임 수가 완전히 일치합니다.
        self._flush_buffer_to_video()

    def _stop_event(self):
        """safety_stop_event=False: 파일을 닫고 라이다 CSV 를 저장합니다."""
        self._recording = False
        self._stop_event_false_time = None

        # 카메라·LiDAR VideoWriter 를 동시에 닫습니다.
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            self.get_logger().info('video.mp4 저장 완료.')

        if self._lidar_writer is not None:
            self._lidar_writer.release()
            self._lidar_writer = None
            self.get_logger().info('lidar_visual.mp4 저장 완료.')

        if self._event_lidar_rows:
            self._save_lidar_csv()

        self.get_logger().info(f'Safety event 종료 — 저장 위치: {self._event_dir}')
        self._event_dir = ''
        self._event_lidar_rows = []

    # =========================================================================
    # Buffer helpers
    # =========================================================================

    def _evict_old_entries(self, now: float):
        """buffer_seconds 를 초과한 오래된 항목을 제거합니다."""
        cutoff = now - self._buffer_seconds
        while self._rolling_buffer and self._rolling_buffer[0].timestamp < cutoff:
            self._rolling_buffer.popleft()

    def _flush_buffer_to_video(self):
        """
        롤링 버퍼의 모든 항목을 카메라·LiDAR VideoWriter 에 동시에 씁니다.

        동기화 보장:
          - 카메라와 LiDAR 는 항상 같은 루프 반복에서 씁니다.
          - LiDAR 렌더링이 실패해도 fallback 프레임을 씁니다.
          - 결과: 두 비디오의 총 프레임 수가 완전히 일치합니다.

        버퍼 구간의 scan 에 대해서는 최신 TF (rclpy.time.Time()) 를 사용합니다.
        scan.header.stamp 기준 TF 는 TF 버퍼에 과거 데이터가 없어 실패하므로
        최신 변환으로 근사하고, 실패 시 로컬 fallback 을 씁니다.
        """
        n = len(self._rolling_buffer)
        self.get_logger().info(f'버퍼 {n}프레임 → video.mp4 + lidar_visual.mp4 덤프 중 ...')

        for entry in self._rolling_buffer:
            # ── 카메라 ──────────────────────────────────────────────────────
            if self._video_writer is not None:
                buf = np.frombuffer(entry.jpeg_bytes, dtype=np.uint8)
                cam_frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                if cam_frame is not None:
                    if cam_frame.shape[1] != FRAME_W or cam_frame.shape[0] != FRAME_H:
                        cam_frame = cv2.resize(cam_frame, (FRAME_W, FRAME_H))
                    self._video_writer.write(cam_frame)

            if entry.scan is not None:
                self._event_lidar_rows.append(self._scan_to_row(entry.scan))

            # ── LiDAR (항상 기록 — fallback 사용) ────────────────────────────
            if self._lidar_writer is not None:
                lidar_frame = self._render_lidar_frame_latest_tf(entry.scan)
                self._lidar_writer.write(lidar_frame)

        self.get_logger().info('버퍼 덤프 완료.')

    # =========================================================================
    # Map canvas builder
    # =========================================================================

    def _build_map_canvas(self):
        """
        OccupancyGrid → BGR canvas 를 빌드하고 self._map_canvas 에 캐시합니다.

        _map_callback 에서만 호출됩니다 (맵이 바뀔 때만 재빌드).

        변환 규칙:
          -1 (unknown)  → (200, 200, 200) 밝은 회색
           0 (free)     → (255, 255, 255) 흰색
          >0 (occupied) → (  0,   0,   0) 검정
        """
        msg = self._map_data
        if msg is None:
            self._map_canvas = None
            self._map_meta = None
            return

        info = msg.info
        res: float = info.resolution
        map_w: int = info.width
        map_h: int = info.height
        origin_x: float = info.origin.position.x
        origin_y: float = info.origin.position.y

        if map_w == 0 or map_h == 0:
            self.get_logger().warn('맵 크기가 0 입니다. canvas 빌드 생략.')
            self._map_canvas = None
            self._map_meta = None
            return

        # OccupancyGrid data 는 int8[] — unknown=-1, free=0, occupied=1..100
        raw = np.array(msg.data, dtype=np.int8).reshape((map_h, map_w))
        img_gray = np.full((map_h, map_w), 200, dtype=np.uint8)  # unknown → 밝은 회색
        img_gray[raw == 0] = 255    # free → 흰색
        img_gray[raw > 0] = 0       # occupied → 검정

        # ROS map row 0 은 Y 최솟값(남쪽), 이미지 row 0 은 위(북쪽) → 상하 반전
        img_gray = np.flipud(img_gray)
        canvas_bgr = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)

        # LIDAR_VIZ 크기로 종횡비 유지 스케일
        scale: float = min(LIDAR_VIZ_W / map_w, LIDAR_VIZ_H / map_h)
        scaled_w: int = max(1, int(map_w * scale))
        scaled_h: int = max(1, int(map_h * scale))
        canvas_scaled = cv2.resize(
            canvas_bgr, (scaled_w, scaled_h), interpolation=cv2.INTER_NEAREST
        )

        # 중앙 패딩 (나머지 영역은 어두운 회색)
        pad_top: int = (LIDAR_VIZ_H - scaled_h) // 2
        pad_left: int = (LIDAR_VIZ_W - scaled_w) // 2
        base = np.full((LIDAR_VIZ_H, LIDAR_VIZ_W, 3), 50, dtype=np.uint8)
        base[pad_top:pad_top + scaled_h, pad_left:pad_left + scaled_w] = canvas_scaled

        self._map_canvas = base
        self._map_meta = _MapMeta(
            origin_x=origin_x,
            origin_y=origin_y,
            res=res,
            scale=scale,
            pad_left=pad_left,
            pad_top=pad_top,
            scaled_w=scaled_w,
            scaled_h=scaled_h,
        )
        self.get_logger().info(
            f'맵 canvas 빌드 완료: {map_w}×{map_h} cells, '
            f'res={res:.3f} m/cell, scale={scale:.3f}'
        )

    # =========================================================================
    # LiDAR visualization
    # =========================================================================

    def render_lidar_map(self) -> np.ndarray:
        """Public API: 현재 scan 으로 LiDAR 시각화 프레임을 반환합니다."""
        return self._render_lidar_frame(self._latest_scan)

    def _render_lidar_frame(self, scan: LaserScan | None) -> np.ndarray:
        """
        scan.header.stamp 기준 TF 로 렌더링합니다 (live 구간용).

        항상 유효한 ndarray 반환 (None 없음).
        """
        try:
            return self._do_render(scan, use_latest_tf=False)
        except Exception as exc:
            self.get_logger().warn(
                f'LiDAR 렌더링 실패: {exc}', throttle_duration_sec=2.0,
            )
            return self._fallback_frame()

    def _render_lidar_frame_latest_tf(self, scan: LaserScan | None) -> np.ndarray:
        """
        최신 TF 로 렌더링합니다 (버퍼 플러시 구간용).

        과거 scan 에 대해 scan.header.stamp 기준 TF 를 조회하면 TF 버퍼에
        해당 시점 데이터가 없어 항상 실패합니다. 최신 TF 로 근사합니다.
        항상 유효한 ndarray 반환 (None 없음).
        """
        try:
            return self._do_render(scan, use_latest_tf=True)
        except Exception as exc:
            self.get_logger().warn(
                f'LiDAR 렌더링 실패 (버퍼): {exc}', throttle_duration_sec=2.0,
            )
            return self._fallback_frame()

    def _fallback_frame(self) -> np.ndarray:
        """마지막으로 성공한 프레임 또는 검정 배경을 반환합니다."""
        if self._last_lidar_frame is not None:
            return self._last_lidar_frame.copy()
        return np.zeros((LIDAR_VIZ_H, LIDAR_VIZ_W, 3), dtype=np.uint8)

    def _do_render(self, scan: LaserScan | None, *, use_latest_tf: bool) -> np.ndarray:
        """
        실제 렌더링 로직.

        렌더링 순서: map(배경) → LiDAR points(빨강) → robot(초록)

        Parameters
        ----------
        scan : LaserScan | None
        use_latest_tf : bool
            True  → rclpy.time.Time() (최신 TF, 버퍼 구간)
            False → scan.header.stamp (정확한 TF, live 구간)
        """
        # ── (1) 맵 배경 캔버스 복사 ────────────────────────────────────────────
        # _map_canvas 는 _map_callback 에서 미리 빌드된 BGR 이미지입니다.
        if self._map_canvas is not None and self._map_meta is not None:
            frame = self._map_canvas.copy()
            meta = self._map_meta
            has_map = True
        else:
            frame = np.zeros((LIDAR_VIZ_H, LIDAR_VIZ_W, 3), dtype=np.uint8)
            meta = None
            has_map = False

        # ── (2) TF 변환 시도 → LiDAR 포인트 그리기 ───────────────────────────
        tf_ok = False
        tx, ty, tf_yaw = 0.0, 0.0, 0.0

        if scan is not None and has_map:
            stamp = rclpy.time.Time() if use_latest_tf else scan.header.stamp
            try:
                tf = self._tf_buffer.lookup_transform(
                    'map',
                    scan.header.frame_id,
                    stamp,
                    timeout=rclpy.duration.Duration(seconds=0.05),
                )
                tx = tf.transform.translation.x
                ty = tf.transform.translation.y
                q = tf.transform.rotation
                tf_yaw = math.atan2(
                    2.0 * (q.w * q.z + q.x * q.y),
                    1.0 - 2.0 * (q.y * q.y + q.z * q.z),
                )
                tf_ok = True
            except TransformException as exc:
                self.get_logger().warn(
                    f'TF 변환 실패 ({scan.header.frame_id} → map): {exc}',
                    throttle_duration_sec=2.0,
                )

        if scan is not None:
            n_rays = len(scan.ranges)
            step = max(1, n_rays // 90)

            if tf_ok:
                # map 프레임으로 변환해 그립니다.
                cos_y = math.cos(tf_yaw)
                sin_y = math.sin(tf_yaw)
                for i in range(0, n_rays, step):
                    r = scan.ranges[i]
                    if not (scan.range_min <= r <= scan.range_max):
                        continue
                    angle = scan.angle_min + i * scan.angle_increment
                    lx = r * math.cos(angle)
                    ly = r * math.sin(angle)
                    mx = tx + lx * cos_y - ly * sin_y
                    my = ty + lx * sin_y + ly * cos_y
                    px, py = meta.world_to_pixel(mx, my)
                    if 0 <= px < LIDAR_VIZ_W and 0 <= py < LIDAR_VIZ_H:
                        cv2.circle(frame, (px, py), 2, (0, 0, 220), -1)
            else:
                # TF 실패 fallback: 로봇 로컬 프레임으로 캔버스 중심에 렌더링합니다.
                cx, cy = LIDAR_VIZ_W // 2, LIDAR_VIZ_H // 2
                for i in range(0, n_rays, step):
                    r = scan.ranges[i]
                    if not (scan.range_min <= r <= scan.range_max):
                        continue
                    angle = scan.angle_min + i * scan.angle_increment
                    lx = r * math.cos(angle)
                    ly = r * math.sin(angle)
                    px = int(cx + lx * LOCAL_SCALE)
                    py = int(cy - ly * LOCAL_SCALE)   # ROS Y 위가 + → image Y 반전
                    if 0 <= px < LIDAR_VIZ_W and 0 <= py < LIDAR_VIZ_H:
                        cv2.circle(frame, (px, py), 2, (0, 0, 220), -1)

                # 로컬 fallback 시 로봇은 항상 중앙에 표시합니다.
                cv2.circle(frame, (cx, cy), 8, (0, 200, 0), -1)
                cv2.circle(frame, (cx, cy), 8, (0, 100, 0), 2)
                cv2.arrowedLine(frame, (cx, cy), (cx + 22, cy), (0, 255, 0), 2, tipLength=0.35)

                self._last_lidar_frame = frame
                # 로컬 프레임은 이미 중앙 정렬 — 크롭 불필요
                return frame

        # ── (3) 로봇 포즈 그리기 (pose 없으면 생략, 크롭 기준점은 중앙) ─────────
        rpx, rpy = LIDAR_VIZ_W // 2, LIDAR_VIZ_H // 2  # 기본값

        pose_msg = self._pose_data
        if pose_msg is not None and has_map:
            rx: float = pose_msg.pose.pose.position.x
            ry: float = pose_msg.pose.pose.position.y
            rq = pose_msg.pose.pose.orientation
            yaw: float = math.atan2(
                2.0 * (rq.w * rq.z + rq.x * rq.y),
                1.0 - 2.0 * (rq.y * rq.y + rq.z * rq.z),
            )
            rpx, rpy = meta.world_to_pixel(rx, ry)

            cv2.circle(frame, (rpx, rpy), 8, (0, 200, 0), -1)
            cv2.circle(frame, (rpx, rpy), 8, (0, 100, 0), 2)
            arrow_len = 22
            arrow_tip = (
                int(rpx + arrow_len * math.cos(yaw)),
                int(rpy - arrow_len * math.sin(yaw)),
            )
            cv2.arrowedLine(frame, (rpx, rpy), arrow_tip, (0, 255, 0), 2, tipLength=0.35)

        # ── (4) 로봇 중심 크롭 → 출력 해상도로 리사이즈 ─────────────────────
        x1 = max(0, rpx - CROP_SIZE)
        x2 = min(LIDAR_VIZ_W, rpx + CROP_SIZE)
        y1 = max(0, rpy - CROP_SIZE)
        y2 = min(LIDAR_VIZ_H, rpy + CROP_SIZE)

        if x2 > x1 and y2 > y1:
            crop = frame[y1:y2, x1:x2]
            frame = cv2.resize(crop, (LIDAR_VIZ_W, LIDAR_VIZ_H))

        self._last_lidar_frame = frame
        return frame

    # =========================================================================
    # Lidar CSV helpers
    # =========================================================================

    def _scan_to_row(self, scan: LaserScan) -> list:
        """LaserScan 메시지를 CSV 한 행으로 변환합니다."""
        row = [
            scan.header.stamp.sec + scan.header.stamp.nanosec * 1e-9,
            scan.angle_min,
            scan.angle_max,
        ]
        row.extend(scan.ranges)
        return row

    def _save_lidar_csv(self):
        """누적된 라이다 행들을 lidar.csv 로 저장합니다."""
        csv_path = os.path.join(self._event_dir, 'lidar.csv')
        if not self._event_lidar_rows:
            return
        n_ranges = len(self._event_lidar_rows[0]) - 3
        header = (
            ['timestamp', 'angle_min', 'angle_max']
            + [f'range_{i}' for i in range(n_ranges)]
        )
        try:
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(self._event_lidar_rows)
            self.get_logger().info(
                f'lidar.csv 저장 완료 ({len(self._event_lidar_rows)} 행).'
            )
        except OSError as exc:
            self.get_logger().error(f'lidar.csv 저장 실패: {exc}')

    # =========================================================================
    # Cleanup
    # =========================================================================

    def destroy_node(self):
        """노드 종료 시 열린 파일과 UDP 소켓을 안전하게 닫습니다."""
        if self._recording:
            self.get_logger().warn('종료 시 기록 중 — 이벤트 파일 강제 닫기.')
            self._stop_event()

        if self._lidar_writer is not None:
            self._lidar_writer.release()
            self._lidar_writer = None

        self._udp_sock.close()
        super().destroy_node()


# ── Entry point ────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = EventRecorderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
