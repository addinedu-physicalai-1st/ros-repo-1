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

  Camera (/dev/videoX)
      │  VideoCapture (타이머, 10 Hz)
      │  resize 640×480  →  JPEG 압축
      ▼
  ┌─────────────────────────────────────┐
  │  rolling_buffer  (deque, 60 s)      │  ← 라이다 스캔도 함께 보관
  │  entry: (timestamp, jpeg_bytes,     │
  │          LaserScan | None)          │
  └─────────────────────────────────────┘
      │                      ▲
      │ safety_stop_event=True         /scan (LaserScan)
      ▼
  ┌─────────────────────────────────────────────────────┐
  │  EventRecorder                                      │
  │  1) buffer → video.mp4  (VideoWriter)               │
  │  2) 이벤트 진행 중 live 프레임 → video.mp4 계속 기록 │
  │  3) safety_stop_event=False → 파일 닫기             │
  │     lidar.csv 저장                                  │
  └─────────────────────────────────────────────────────┘

메모리 절약 설계 (Raspberry Pi)
---------------------------------
* 프레임은 JPEG 바이트로만 보관 (raw BGR 절대 저장 안 함)
  640×480 BGR raw : ~900 KB/frame × 10 fps × 60 s = ~540 MB  ← 불가
  JPEG q=80       :  ~25 KB/frame × 10 fps × 60 s =  ~15 MB  ← 허용
* deque maxlen 으로 자동 오버플로우 방지
* VideoWriter에 쓸 때만 JPEG → BGR 디코딩 (순간적, 재사용 없음)
* 라이다는 이벤트 기간 동안만 메모리에 누적 (평상시 buffer 1개만 캐시)

ROS Parameters
--------------
camera_index      int    0       VideoCapture 인덱스
capture_rate_hz   float  10.0    초당 프레임 캡처 횟수
buffer_seconds    float  60.0    롤링 버퍼 유지 시간(초)
output_dir        str    "safety_events"  저장 루트 디렉터리
jpeg_quality      int    80      JPEG 압축 품질 (0–100)

Topics
------
Subscribe  /scan               sensor_msgs/LaserScan
Subscribe  /safety_stop_event  std_msgs/Bool
"""

import csv
import os
import time
from collections import deque
from datetime import datetime

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool

# ── 기본 상수 ─────────────────────────────────────────────────────────────────
FRAME_W = 640
FRAME_H = 480
FOURCC = cv2.VideoWriter_fourcc(*'mp4v')

SCAN_TOPIC = 'scan'
SAFETY_TOPIC = 'safety_stop_event'


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
    /safety_stop_event == True 가 되면 버퍼를 video.mp4 로 덤프하고
    이후 live 프레임을 계속 기록하다가 False 가 되면 파일을 닫습니다.
    """

    def __init__(self):
        super().__init__('event_recorder_node')

        # ── ROS Parameters ────────────────────────────────────────────────────
        self.declare_parameter('camera_index', 0)
        self.declare_parameter('capture_rate_hz', 10.0)
        self.declare_parameter('buffer_seconds', 60.0)
        self.declare_parameter('output_dir', 'safety_events')
        self.declare_parameter('jpeg_quality', 80)

        self._camera_index: int = (
            self.get_parameter('camera_index').get_parameter_value().integer_value
        )
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
        # 롤링 버퍼: maxlen으로 메모리 상한을 보장합니다.
        # capture_rate × buffer_seconds 개 항목을 초과하면 가장 오래된 항목이
        # 자동으로 제거됩니다.
        _maxlen = int(self._capture_rate * self._buffer_seconds) + 1
        self._rolling_buffer: deque = deque(maxlen=_maxlen)

        # 가장 최근 수신한 라이다 스캔 (캡처 시점에 버퍼 항목과 묶임)
        self._latest_scan: LaserScan | None = None

        # 이벤트 기록 상태
        self._recording: bool = False
        self._video_writer: cv2.VideoWriter | None = None
        self._event_dir: str = ''

        # 이벤트 기간 동안 누적된 라이다 스캔 목록
        self._event_lidar_rows: list = []

        # ── OpenCV VideoCapture ────────────────────────────────────────────────
        self.get_logger().info(f'Opening camera {self._camera_index} ...')
        self._cap = cv2.VideoCapture(self._camera_index)
        if not self._cap.isOpened():
            self.get_logger().error(
                f'Camera {self._camera_index} 열기 실패. '
                'capture 타이머가 계속 시도합니다.'
            )

        # ── ROS Subscribers ───────────────────────────────────────────────────
        self.create_subscription(
            LaserScan, SCAN_TOPIC, self._scan_callback, 10
        )
        self.create_subscription(
            Bool, SAFETY_TOPIC, self._safety_callback, 10
        )

        # ── Capture timer ─────────────────────────────────────────────────────
        # 모든 캡처·기록 로직을 이 타이머 콜백 안에서 처리합니다.
        # ROS spin 스레드에서만 실행되므로 별도 락이 필요 없습니다.
        self.create_timer(1.0 / self._capture_rate, self._capture_tick)

        self.get_logger().info('EventRecorderNode started.')
        self.get_logger().info(
            f'  Camera       : index={self._camera_index}, '
            f'{FRAME_W}×{FRAME_H} @ {self._capture_rate} Hz'
        )
        self.get_logger().info(
            f'  Buffer       : {self._buffer_seconds} s  '
            f'(max {_maxlen} frames)'
        )
        self.get_logger().info(
            f'  JPEG quality : {self._jpeg_quality}'
        )
        self.get_logger().info(f'  Output dir   : {self._output_dir}')

    # ── Subscriber callbacks ───────────────────────────────────────────────────

    def _scan_callback(self, msg: LaserScan):
        """최신 라이다 스캔을 캐시합니다. 버퍼에 직접 넣지 않습니다."""
        self._latest_scan = msg

    def _safety_callback(self, msg: Bool):
        """safety_stop_event 상태 변화에 반응합니다."""
        if msg.data and not self._recording:
            self._start_event()
        elif not msg.data and self._recording:
            self._stop_event()

    # ── Capture tick (core loop) ───────────────────────────────────────────────

    def _capture_tick(self):
        """
        매 타이머 틱:
        1. 카메라에서 프레임을 읽어 JPEG 압축 후 롤링 버퍼에 넣습니다.
        2. 60초보다 오래된 항목을 제거합니다.
        3. 이벤트 기록 중이면 VideoWriter에 프레임을 씁니다.
        """
        ret, frame = self._cap.read()
        if not ret or frame is None:
            self.get_logger().warn(
                '프레임 캡처 실패.', throttle_duration_sec=2.0
            )
            return

        # ── 리사이즈 → JPEG 압축 ──────────────────────────────────────────────
        # 리사이즈: 640×480 보장 (카메라 해상도가 달라도 통일)
        if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))

        # JPEG 압축 — raw BGR 프레임은 이 시점 이후 절대 보관하지 않습니다.
        ok, jpeg_buf = cv2.imencode(
            '.jpg', frame,
            [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        )
        if not ok:
            self.get_logger().warn('JPEG 인코딩 실패.', throttle_duration_sec=2.0)
            return

        jpeg_bytes: bytes = jpeg_buf.tobytes()
        now: float = time.monotonic()

        # ── 롤링 버퍼에 추가 ──────────────────────────────────────────────────
        # deque의 maxlen이 자동으로 가장 오래된 항목을 제거합니다.
        # 추가로 시간 기반 만료도 적용해 버퍼 기간이 정확하도록 합니다.
        entry = _BufferEntry(now, jpeg_bytes, self._latest_scan)
        self._rolling_buffer.append(entry)
        self._evict_old_entries(now)

        # ── 이벤트 기록 중: VideoWriter에 프레임 쓰기 ─────────────────────────
        if self._recording and self._video_writer is not None:
            self._write_frame_to_video(frame)

            # 이벤트 기간 라이다 저장
            if self._latest_scan is not None:
                self._event_lidar_rows.append(
                    self._scan_to_row(self._latest_scan)
                )

    # ── Event lifecycle ────────────────────────────────────────────────────────

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

        # VideoWriter 초기화
        video_path = os.path.join(self._event_dir, 'video.mp4')
        self._video_writer = cv2.VideoWriter(
            video_path, FOURCC, self._capture_rate, (FRAME_W, FRAME_H)
        )
        if not self._video_writer.isOpened():
            self.get_logger().error(f'VideoWriter 초기화 실패: {video_path}')
            self._video_writer = None

        self._event_lidar_rows = []
        self._recording = True

        # 롤링 버퍼에 쌓인 최근 60초 프레임을 video.mp4 앞부분으로 씁니다.
        self._flush_buffer_to_video()

    def _stop_event(self):
        """safety_stop_event=False: 파일을 닫고 라이다 CSV 를 저장합니다."""
        self._recording = False

        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            self.get_logger().info('video.mp4 저장 완료.')

        if self._event_lidar_rows:
            self._save_lidar_csv()

        self.get_logger().info(
            f'Safety event 종료 — 저장 위치: {self._event_dir}'
        )
        self._event_dir = ''
        self._event_lidar_rows = []

    # ── Buffer helpers ─────────────────────────────────────────────────────────

    def _evict_old_entries(self, now: float):
        """
        deque 왼쪽(가장 오래된) 항목 중 buffer_seconds 를 초과한 것을 제거합니다.

        deque.maxlen 이 있어도 시간 기반으로 추가 제거해
        capture_rate 가 변동해도 60초 창이 정확하게 유지됩니다.
        """
        cutoff = now - self._buffer_seconds
        while self._rolling_buffer and self._rolling_buffer[0].timestamp < cutoff:
            self._rolling_buffer.popleft()

    def _flush_buffer_to_video(self):
        """
        현재 롤링 버퍼의 모든 항목을 VideoWriter에 씁니다.

        JPEG → BGR 디코딩은 여기서만 수행되며 디코딩된 BGR 배열은
        VideoWriter에 전달한 직후 해제됩니다 (참조 없음 → GC 즉시 수거).
        """
        if self._video_writer is None:
            return

        n = len(self._rolling_buffer)
        self.get_logger().info(f'버퍼 {n}프레임 → video.mp4 덤프 중 ...')

        for entry in self._rolling_buffer:
            self._write_jpeg_to_video(entry.jpeg_bytes)
            if entry.scan is not None:
                self._event_lidar_rows.append(self._scan_to_row(entry.scan))

        self.get_logger().info('버퍼 덤프 완료.')

    def _write_jpeg_to_video(self, jpeg_bytes: bytes):
        """JPEG bytes → BGR ndarray → VideoWriter. 디코딩 배열은 즉시 해제."""
        if self._video_writer is None:
            return
        buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            return
        if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))
        self._video_writer.write(frame)
        # frame 은 이 함수 반환 시 참조 소멸 → GC 즉시 수거

    def _write_frame_to_video(self, frame: np.ndarray):
        """live BGR 프레임을 VideoWriter에 씁니다 (이벤트 기록 중 live 경로)."""
        if self._video_writer is None:
            return
        self._video_writer.write(frame)

    # ── Lidar helpers ──────────────────────────────────────────────────────────

    def _scan_to_row(self, scan: LaserScan) -> list:
        """
        LaserScan 메시지를 CSV 한 행(list)으로 변환합니다.

        행 구조: timestamp, angle_min, angle_max, range_0, range_1, ...
        """
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

        # 헤더: 첫 번째 행에서 range 개수를 파악합니다.
        if not self._event_lidar_rows:
            return

        n_ranges = len(self._event_lidar_rows[0]) - 3  # timestamp, min, max 제외
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

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def destroy_node(self):
        """노드 종료 시 열린 파일과 카메라 핸들을 안전하게 닫습니다."""
        if self._recording:
            self.get_logger().warn('종료 시 기록 중 — 이벤트 파일 강제 닫기.')
            self._stop_event()

        if self._cap.isOpened():
            self._cap.release()
            self.get_logger().info('Camera released.')

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
