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

  pinky_camera node
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
  │  2) 이벤트 진행 중 live 카메라 프레임 → video.mp4 계속 기록    │
  │  3) 이벤트 진행 중 live LiDAR 시각화 → lidar_visual.mp4     │  [NEW]
  │  4) safety_stop_event=False → 파일 닫기 / lidar.csv 저장    │
  └───────────────────────────────────────────────────────────┘

메모리 절약 설계 (Raspberry Pi)
---------------------------------
* 카메라 프레임은 JPEG 바이트로만 보관 (raw BGR 절대 저장 안 함)
* LiDAR 시각화는 이벤트 기간에만 VideoWriter 에 직접 쓰고 보관하지 않음
* deque maxlen 으로 자동 오버플로우 방지

ROS Parameters
--------------
capture_rate_hz   float  10.0    초당 버퍼 저장 횟수 (타이머 주기)
buffer_seconds    float  60.0    롤링 버퍼 유지 시간(초)
output_dir        str    "safety_events"  저장 루트 디렉터리
jpeg_quality      int    80      JPEG 재압축 품질 (0–100)

Topics
------
Subscribe  /image              sensor_msgs/CompressedImage
Subscribe  /scan               sensor_msgs/LaserScan
Subscribe  /map                nav_msgs/OccupancyGrid          [NEW]
Subscribe  /amcl_pose          geometry_msgs/PoseWithCovarianceStamped  [NEW]
Subscribe  /safety_stop_event  std_msgs/Bool
"""

import csv
import math                                           # [NEW]
import os
import time
from collections import deque
from datetime import datetime

import cv2
import numpy as np
import rclpy
import tf2_ros                                        # [NEW]
from geometry_msgs.msg import PoseWithCovarianceStamped  # [NEW]
from nav_msgs.msg import OccupancyGrid                # [NEW]
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, LaserScan
from std_msgs.msg import Bool
from tf2_ros import TransformException                # [NEW]

# ── 기본 상수 ─────────────────────────────────────────────────────────────────
FRAME_W = 640
FRAME_H = 480
FOURCC = cv2.VideoWriter_fourcc(*'mp4v')

# [NEW] LiDAR 시각화 캔버스 크기 (정사각형 top-down 뷰)
LIDAR_VIZ_W = 640
LIDAR_VIZ_H = 640

IMAGE_TOPIC = '/image'
SCAN_TOPIC = 'scan'
MAP_TOPIC = '/map'                                    # [NEW]
AMCL_POSE_TOPIC = '/amcl_pose'                        # [NEW]
SAFETY_TOPIC = 'safety_stop_event'
STOP_EVENT_FALSE_HOLD_S = 3.0


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
      · 카메라 버퍼 → video.mp4
      · 이후 live 카메라 → video.mp4 계속 기록
      · 이후 live LiDAR 시각화 → lidar_visual.mp4 기록  [NEW]
    False 가 되면 두 파일을 닫습니다.
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

        # [NEW] 맵·포즈 캐시 — 콜백에서 갱신, 렌더링 타이밍에 읽습니다.
        self._map_data: OccupancyGrid | None = None
        self._pose_data: PoseWithCovarianceStamped | None = None

        # 이벤트 기록 상태
        self._recording: bool = False
        self._video_writer: cv2.VideoWriter | None = None
        self._lidar_writer: cv2.VideoWriter | None = None  # [NEW]
        self._event_dir: str = ''
        self._last_safety_stop_state: bool = False
        self._event_lidar_rows: list = []
        self._stop_event_false_time: float | None = None

        # ── [NEW] TF2 Buffer + TransformListener ──────────────────────────────
        # LiDAR 스캔 포인트를 map 프레임으로 변환하는 데 사용합니다.
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)

        # ── Subscribers ───────────────────────────────────────────────────────
        self.create_subscription(
            CompressedImage, IMAGE_TOPIC, self._image_callback, 10,
        )
        self.create_subscription(
            LaserScan, SCAN_TOPIC, self._scan_callback, 10,
        )
        self.create_subscription(
            Bool, SAFETY_TOPIC, self._safety_callback, 10,
        )

        # [NEW] 맵과 로봇 포즈 구독
        self.create_subscription(
            OccupancyGrid, MAP_TOPIC, self._map_callback, 1,
        )
        self.create_subscription(
            PoseWithCovarianceStamped, AMCL_POSE_TOPIC, self._pose_callback, 10,
        )

        # ── Capture timer ─────────────────────────────────────────────────────
        self.create_timer(1.0 / self._capture_rate, self._capture_tick)

        self.get_logger().info('EventRecorderNode started.')
        self.get_logger().info(f'  Subscribing  : {IMAGE_TOPIC} (CompressedImage)')
        self.get_logger().info(f'  Subscribing  : {MAP_TOPIC}, {AMCL_POSE_TOPIC}, {SCAN_TOPIC}')  # [NEW]
        self.get_logger().info(
            f'  Buffer       : {self._buffer_seconds} s  (max {_maxlen} frames)'
        )
        self.get_logger().info(f'  JPEG quality : {self._jpeg_quality}')
        self.get_logger().info(f'  Output dir   : {self._output_dir}')

    # =========================================================================
    # Subscriber callbacks
    # =========================================================================

    def _image_callback(self, msg: CompressedImage):
        """CompressedImage → BGR ndarray 로 디코딩 후 self._latest_frame 에 저장."""
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            self.get_logger().warn(
                'Failed to decode CompressedImage.', throttle_duration_sec=2.0,
            )
            return
        self._latest_frame = frame

    def _scan_callback(self, msg: LaserScan):
        """최신 라이다 스캔을 캐시합니다."""
        self._latest_scan = msg

    # [NEW] ──────────────────────────────────────────────────────────────────
    def _map_callback(self, msg: OccupancyGrid):
        """
        OccupancyGrid 메시지를 캐시합니다.

        맵은 자주 바뀌지 않으므로 QoS depth=1 로 구독합니다.
        콜백 안에서 무거운 연산을 하지 않고 레퍼런스만 저장합니다.
        """
        self._map_data = msg

    # [NEW] ──────────────────────────────────────────────────────────────────
    def _pose_callback(self, msg: PoseWithCovarianceStamped):
        """AMCL 로봇 포즈를 캐시합니다."""
        self._pose_data = msg

    def _safety_callback(self, msg: Bool):
        """safety_stop_event 상태 변화에 반응합니다."""
        if msg.data:
            if not self._recording:
                self._start_event()
            self._stop_event_false_time = None
        elif self._recording and self._last_safety_stop_state:
            self._stop_event_false_time = time.monotonic()
            self.get_logger().info(
                f'safety_stop_event=False 감지. '
                f'{STOP_EVENT_FALSE_HOLD_S:.1f}s 유지되면 녹화를 종료합니다.'
            )
        self._last_safety_stop_state = msg.data

    # =========================================================================
    # Capture tick (core loop)
    # =========================================================================

    def _capture_tick(self):
        """
        매 타이머 틱:
        1. self._latest_frame 에서 카메라 프레임을 가져와 롤링 버퍼에 넣습니다.
        2. 이벤트 기록 중이면 카메라 VideoWriter에 씁니다.
        3. [NEW] 이벤트 기록 중이면 LiDAR 시각화 프레임을 렌더링 후 씁니다.
        """
        self._check_delayed_stop()

        frame = self._latest_frame
        if frame is None:
            self.get_logger().warn(
                '/image 미수신 — 프레임 없음.', throttle_duration_sec=2.0,
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
            # 카메라 영상
            if self._video_writer is not None:
                self._write_frame_to_video(frame)
            if self._latest_scan is not None:
                self._event_lidar_rows.append(self._scan_to_row(self._latest_scan))

            # [NEW] LiDAR 시각화 영상
            if self._lidar_writer is not None:
                lidar_frame = self._render_lidar_frame(self._latest_scan)
                if lidar_frame is not None:
                    self._lidar_writer.write(lidar_frame)

    def _check_delayed_stop(self):
        """safety_stop_event=False 가 STOP_EVENT_FALSE_HOLD_S 초 유지되면 종료."""
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

        # 카메라 VideoWriter 초기화
        video_path = os.path.join(self._event_dir, 'video.mp4')
        self._video_writer = cv2.VideoWriter(
            video_path, FOURCC, self._capture_rate, (FRAME_W, FRAME_H)
        )
        if not self._video_writer.isOpened():
            self.get_logger().error(f'카메라 VideoWriter 초기화 실패: {video_path}')
            self._video_writer = None

        # [NEW] LiDAR 시각화 VideoWriter 초기화
        lidar_path = os.path.join(
            self._event_dir, f'lidar_visual_{timestamp_str}.mp4'
        )
        self._lidar_writer = cv2.VideoWriter(
            lidar_path, FOURCC, self._capture_rate, (LIDAR_VIZ_W, LIDAR_VIZ_H)
        )
        if not self._lidar_writer.isOpened():
            self.get_logger().error(f'LiDAR VideoWriter 초기화 실패: {lidar_path}')
            self._lidar_writer = None

        self._event_lidar_rows = []
        self._recording = True
        self._stop_event_false_time = None

        # 롤링 버퍼에 쌓인 최근 60초 프레임을 video.mp4 앞부분으로 씁니다.
        self._flush_buffer_to_video()

    def _stop_event(self):
        """safety_stop_event=False: 파일을 닫고 라이다 CSV 를 저장합니다."""
        self._recording = False
        self._stop_event_false_time = None

        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            self.get_logger().info('video.mp4 저장 완료.')

        # [NEW] LiDAR VideoWriter 닫기
        if self._lidar_writer is not None:
            self._lidar_writer.release()
            self._lidar_writer = None
            self.get_logger().info('lidar_visual.mp4 저장 완료.')

        if self._event_lidar_rows:
            self._save_lidar_csv()

        self.get_logger().info(
            f'Safety event 종료 — 저장 위치: {self._event_dir}'
        )
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
        현재 롤링 버퍼의 모든 항목을 두 VideoWriter에 씁니다.

        카메라: JPEG bytes → BGR → VideoWriter
        LiDAR:  [NEW] 버퍼 항목의 scan + 현재 map/pose 로 렌더링 → LiDAR VideoWriter
                map/pose 가 없으면 해당 프레임은 회색으로 채웁니다.
        """
        n = len(self._rolling_buffer)
        self.get_logger().info(f'버퍼 {n}프레임 → video.mp4 덤프 중 ...')

        for entry in self._rolling_buffer:
            # 카메라 프레임
            self._write_jpeg_to_video(entry.jpeg_bytes)
            if entry.scan is not None:
                self._event_lidar_rows.append(self._scan_to_row(entry.scan))

            # [NEW] LiDAR 시각화 프레임 (버퍼 항목의 scan 을 사용, map/pose 는 현재값)
            if self._lidar_writer is not None:
                lidar_frame = self._render_lidar_frame(entry.scan)
                if lidar_frame is None:
                    # map 또는 pose 가 없으면 회색 플레이스홀더로 채웁니다.
                    lidar_frame = np.full(
                        (LIDAR_VIZ_H, LIDAR_VIZ_W, 3), 127, dtype=np.uint8
                    )
                self._lidar_writer.write(lidar_frame)

        self.get_logger().info('버퍼 덤프 완료.')

    def _write_jpeg_to_video(self, jpeg_bytes: bytes):
        """JPEG bytes → BGR ndarray → VideoWriter."""
        if self._video_writer is None:
            return
        buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            return
        if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))
        self._video_writer.write(frame)

    def _write_frame_to_video(self, frame: np.ndarray):
        """live BGR 프레임을 카메라 VideoWriter에 씁니다."""
        if self._video_writer is None:
            return
        self._video_writer.write(frame)

    # =========================================================================
    # [NEW] LiDAR visualization
    # =========================================================================

    def render_lidar_map(self) -> np.ndarray | None:
        """
        Public API: 현재 self._latest_scan 을 사용해 LiDAR 시각화 프레임을 반환합니다.

        Returns
        -------
        np.ndarray (BGR, LIDAR_VIZ_W × LIDAR_VIZ_H) | None
            렌더링에 필요한 데이터가 없거나 실패하면 None.
        """
        return self._render_lidar_frame(self._latest_scan)

    def _render_lidar_frame(self, scan: LaserScan | None) -> np.ndarray | None:
        """
        [NEW] Map + Robot pose + LiDAR scan 을 BGR 이미지로 렌더링합니다.

        별도의 함수로 분리해 버퍼 플러시 시 항목별 scan 을 주입할 수 있습니다.

        Parameters
        ----------
        scan : LaserScan | None
            사용할 스캔 데이터. None 이면 렌더링을 건너뜁니다.

        Returns
        -------
        np.ndarray (BGR, LIDAR_VIZ_W × LIDAR_VIZ_H) | None
        """
        # 필수 데이터가 없으면 렌더링 불가
        if self._map_data is None or scan is None or self._pose_data is None:
            return None

        try:
            return self._do_render(scan)
        except Exception as exc:
            self.get_logger().warn(
                f'LiDAR 맵 렌더링 실패: {exc}', throttle_duration_sec=2.0,
            )
            return None

    def _do_render(self, scan: LaserScan) -> np.ndarray:
        """
        [NEW] 실제 렌더링 로직. 예외는 호출자(_render_lidar_frame)가 처리합니다.

        단계:
        1. OccupancyGrid → grayscale → BGR canvas
        2. canvas 를 LIDAR_VIZ 크기로 스케일 + 중앙 패딩
        3. LiDAR 포인트를 map 프레임으로 TF 변환 후 빨간 점으로 표시
        4. 로봇 위치(초록 원) + 방향 화살표 표시
        """
        map_msg = self._map_data
        pose_msg = self._pose_data

        info = map_msg.info
        res: float = info.resolution          # meters per cell
        map_w: int = info.width
        map_h: int = info.height
        origin_x: float = info.origin.position.x
        origin_y: float = info.origin.position.y

        # ── (1) OccupancyGrid → BGR canvas ────────────────────────────────────
        # data 는 int8 배열. -1=unknown, 0=free, 1-100=occupied
        raw = np.array(map_msg.data, dtype=np.int8).reshape((map_h, map_w))

        img_gray = np.full((map_h, map_w), 127, dtype=np.uint8)  # unknown = gray
        img_gray[raw == 0] = 255   # free  → white
        img_gray[raw > 0] = 0      # occupied → black

        # 상하 반전: ROS map 의 row 0 은 남쪽(origin), image 의 row 0 은 북쪽
        img_gray = np.flipud(img_gray)
        canvas = cv2.cvtColor(img_gray, cv2.COLOR_GRAY2BGR)

        # ── (2) LIDAR_VIZ 캔버스로 스케일 + 중앙 패딩 ─────────────────────────
        scale: float = min(LIDAR_VIZ_W / map_w, LIDAR_VIZ_H / map_h)
        scaled_w: int = max(1, int(map_w * scale))
        scaled_h: int = max(1, int(map_h * scale))

        # INTER_NEAREST: 픽셀 경계를 뭉개지 않아 Raspberry Pi 에서 가장 빠름
        canvas = cv2.resize(canvas, (scaled_w, scaled_h), interpolation=cv2.INTER_NEAREST)

        pad_top: int = (LIDAR_VIZ_H - scaled_h) // 2
        pad_left: int = (LIDAR_VIZ_W - scaled_w) // 2
        frame = np.full((LIDAR_VIZ_H, LIDAR_VIZ_W, 3), 127, dtype=np.uint8)
        frame[pad_top:pad_top + scaled_h, pad_left:pad_left + scaled_w] = canvas

        # ── world (map frame) ↔ pixel 변환 헬퍼 ──────────────────────────────
        def world_to_pixel(wx: float, wy: float):
            """map 좌표(m) → 화면 픽셀 좌표."""
            px = int((wx - origin_x) / res * scale) + pad_left
            # flipud 에 맞춰 Y 축도 반전합니다.
            py = int(scaled_h - (wy - origin_y) / res * scale) + pad_top
            return px, py

        # ── (3) LiDAR 스캔 포인트 그리기 ──────────────────────────────────────
        try:
            # 스캔 프레임 → map 프레임 변환 행렬을 조회합니다.
            tf = self._tf_buffer.lookup_transform(
                'map',
                scan.header.frame_id,
                rclpy.time.Time(),                         # 가장 최신 transform 사용
                timeout=rclpy.duration.Duration(seconds=0.05),
            )
            tx: float = tf.transform.translation.x
            ty: float = tf.transform.translation.y
            q = tf.transform.rotation
            # 쿼터니언 → yaw (평면 주행 로봇이므로 yaw 만 사용)
            tf_yaw: float = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            cos_y = math.cos(tf_yaw)
            sin_y = math.sin(tf_yaw)

            # 성능을 위해 최대 ~180 포인트만 그립니다.
            n_rays = len(scan.ranges)
            step = max(1, n_rays // 180)
            for i in range(0, n_rays, step):
                r = scan.ranges[i]
                if not (scan.range_min <= r <= scan.range_max):
                    continue
                angle = scan.angle_min + i * scan.angle_increment
                # 극좌표 → 레이저 프레임 Cartesian
                lx = r * math.cos(angle)
                ly = r * math.sin(angle)
                # 레이저 프레임 → map 프레임 (2D 회전 + 평행이동)
                mx = tx + lx * cos_y - ly * sin_y
                my = ty + lx * sin_y + ly * cos_y
                px, py = world_to_pixel(mx, my)
                if 0 <= px < LIDAR_VIZ_W and 0 <= py < LIDAR_VIZ_H:
                    cv2.circle(frame, (px, py), 2, (0, 0, 220), -1)  # 빨간 점

        except TransformException as exc:
            # TF 변환 실패 시 스캔 포인트를 건너뛰고 map + pose 만 그립니다.
            self.get_logger().warn(
                f'TF 변환 실패 ({scan.header.frame_id} → map): {exc}',
                throttle_duration_sec=2.0,
            )

        # ── (4) 로봇 포즈 그리기 ──────────────────────────────────────────────
        rx: float = pose_msg.pose.pose.position.x
        ry: float = pose_msg.pose.pose.position.y
        rq = pose_msg.pose.pose.orientation
        yaw: float = math.atan2(
            2.0 * (rq.w * rq.z + rq.x * rq.y),
            1.0 - 2.0 * (rq.y * rq.y + rq.z * rq.z),
        )
        rpx, rpy = world_to_pixel(rx, ry)

        # 로봇 원 (초록)
        cv2.circle(frame, (rpx, rpy), 8, (0, 200, 0), -1)
        cv2.circle(frame, (rpx, rpy), 8, (0, 100, 0), 2)

        # 방향 화살표 (image Y 는 아래가 +이므로 sin 을 반전)
        arrow_len = 22
        arrow_tip = (
            int(rpx + arrow_len * math.cos(yaw)),
            int(rpy - arrow_len * math.sin(yaw)),
        )
        cv2.arrowedLine(frame, (rpx, rpy), arrow_tip, (0, 255, 0), 2, tipLength=0.35)

        return frame

    # =========================================================================
    # Lidar CSV helpers (unchanged)
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
        """노드 종료 시 열린 파일을 안전하게 닫습니다."""
        if self._recording:
            self.get_logger().warn('종료 시 기록 중 — 이벤트 파일 강제 닫기.')
            self._stop_event()

        # [NEW] 혹시 _stop_event 호출 전에 writer 가 열려있는 경우 추가 방어
        if self._lidar_writer is not None:
            self._lidar_writer.release()
            self._lidar_writer = None

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
