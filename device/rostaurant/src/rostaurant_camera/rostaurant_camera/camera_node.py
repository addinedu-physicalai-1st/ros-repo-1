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
Camera Node — Rost Pro 단일 카메라 퍼블리셔.

카메라를 단 한 번만 열고, JPEG 압축 후 UDP Multicast로 전송합니다.
여러 노드(child_detection_node, event_recorder_node 등)가 멀티캐스트 그룹에
가입하여 동일한 프레임을 수신합니다.

Architecture
------------
  camera hardware  (/dev/videoX, V4L2)
       │
       ▼
  cv2.VideoCapture  (타이머, ~10–15 Hz)
       │  640×480 BGR
       ▼
  cv2.imencode  (JPEG q=90)
       │  bytes
       ▼
  UDP Multicast 239.255.0.1:5000
       │  [frame_id(4B) | data_len(4B) | JPEG]
       │
       ├──▶  child_detection_node   (YOLO)
       └──▶  event_recorder_node    (rolling buffer)

ROS Parameters
--------------
camera_index   int    3      VideoCapture 인덱스 (/dev/video3)
fps            float  10.0   타이머 주기 (Hz)
jpeg_quality   int    90     JPEG 압축 품질 (0–100)
               ↑ YOLO 성능 보존을 위해 기본값 90을 권장합니다.
"""

import socket
import struct

import cv2
import numpy as np
import rclpy
from rclpy.node import Node

# ── UDP Multicast ──────────────────────────────────────────────────────────────
MULTICAST_GROUP = '239.255.0.1'
MULTICAST_PORT  = 5000
# loopback UDP 최대 페이로드(65535 - IP헤더20 - UDP헤더8) 에서 헤더 8바이트 제외
UDP_MAX_PAYLOAD = 65499

# ── Default constants ──────────────────────────────────────────────────────────
DEFAULT_CAMERA_INDEX = 0
DEFAULT_FPS = 10.0
DEFAULT_JPEG_QUALITY = 90   # YOLO 성능 저하를 막기 위해 90 이상 권장

# 카메라 출력 해상도 고정값 — 모든 다운스트림 노드가 이 크기를 기대합니다.
FRAME_W = 640
FRAME_H = 480


class CameraNode(Node):
    """
    단일 카메라 UDP 멀티캐스트 송신 노드.

    Sends
    -----
    UDP Multicast 239.255.0.1:5000
        패킷: [frame_id(uint32 BE)][data_len(uint32 BE)][JPEG bytes]
        다운스트림 노드가 멀티캐스트 그룹에 가입하여 수신합니다.
    """

    def __init__(self):
        super().__init__('camera_node')

        # ── ROS parameters ─────────────────────────────────────────────────────
        self.declare_parameter('camera_index', DEFAULT_CAMERA_INDEX)
        self.declare_parameter('fps', DEFAULT_FPS)
        self.declare_parameter('jpeg_quality', DEFAULT_JPEG_QUALITY)

        camera_index: int = (
            self.get_parameter('camera_index').get_parameter_value().integer_value
        )
        fps: float = (
            self.get_parameter('fps').get_parameter_value().double_value
        )
        self._jpeg_quality: int = (
            self.get_parameter('jpeg_quality').get_parameter_value().integer_value
        )

        # ── OpenCV VideoCapture ────────────────────────────────────────────────
        self.get_logger().info(f'Opening camera index {camera_index} ...')
        self._cap = cv2.VideoCapture(camera_index)

        if not self._cap.isOpened():
            self.get_logger().error(
                f'Failed to open camera index {camera_index}. '
                'The node will keep retrying each timer tick.'
            )
        else:
            # 카메라 해상도를 640×480으로 고정합니다.
            # 카메라 드라이버가 이 값을 지원하지 않으면 가장 가까운 값으로 설정됩니다.
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
            # 카메라 내부 버퍼를 1프레임으로 줄여 latency를 최소화합니다.
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.get_logger().info(
                f'Camera {camera_index} opened. '
                f'Target resolution: {FRAME_W}×{FRAME_H} @ {fps} Hz, '
                f'JPEG quality: {self._jpeg_quality}'
            )

        # ── UDP Multicast 소켓 ────────────────────────────────────────────────
        self._frame_id = 0
        self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        # 같은 머신의 수신 노드가 자신이 보낸 패킷을 받을 수 있도록 loopback 활성화
        self._udp_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        self.get_logger().info(
            f'UDP multicast socket ready → {MULTICAST_GROUP}:{MULTICAST_PORT}'
        )

        # ── Capture timer ──────────────────────────────────────────────────────
        # while True 대신 ROS2 타이머를 사용합니다.
        # rclpy.spin() 안에서 단일 스레드로 동작하므로 별도 락이 필요 없습니다.
        self._timer = self.create_timer(1.0 / fps, self._capture_and_publish)

        self.get_logger().info(
            f'CameraNode started — multicast {MULTICAST_GROUP}:{MULTICAST_PORT} at {fps} Hz.'
        )

    # ── Timer callback ─────────────────────────────────────────────────────────

    def _capture_and_publish(self):
        """
        타이머 콜백: 카메라에서 프레임을 읽고 JPEG 압축 후 퍼블리시합니다.

        cap.read() 실패 시에는 경고 로그만 남기고 다음 틱을 기다립니다.
        """
        # 카메라가 열려 있지 않으면 재시도합니다.
        if not self._cap.isOpened():
            self.get_logger().warn(
                'Camera not open — skipping frame.',
                throttle_duration_sec=2.0,
            )
            return

        ret, frame = self._cap.read()

        if not ret or frame is None:
            self.get_logger().warn(
                'Failed to capture frame.',
                throttle_duration_sec=2.0,
            )
            return

        # ── 해상도 보정 ────────────────────────────────────────────────────────
        # 카메라가 요청한 해상도를 정확히 지원하지 않을 경우를 대비합니다.
        if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))

        # ── JPEG 압축 ──────────────────────────────────────────────────────────
        # quality=90: YOLO 추론 정확도와 네트워크 대역폭 사이의 최적 균형점입니다.
        ok, jpeg_buf = cv2.imencode(
            '.jpg', frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality],
        )
        if not ok:
            self.get_logger().warn(
                'JPEG encoding failed — skipping frame.',
                throttle_duration_sec=2.0,
            )
            return

        # ── UDP Multicast 전송 ─────────────────────────────────────────────────
        jpeg_bytes = jpeg_buf.tobytes()
        if len(jpeg_bytes) > UDP_MAX_PAYLOAD:
            self.get_logger().warn(
                f'Frame too large ({len(jpeg_bytes)} B > {UDP_MAX_PAYLOAD} B) — dropped.',
                throttle_duration_sec=2.0,
            )
            return

        self._frame_id = (self._frame_id + 1) & 0xFFFFFFFF
        header = struct.pack('>II', self._frame_id, len(jpeg_bytes))
        self._udp_sock.sendto(header + jpeg_bytes, (MULTICAST_GROUP, MULTICAST_PORT))

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def destroy_node(self):
        """노드 종료 시 카메라 핸들과 UDP 소켓을 안전하게 해제합니다."""
        if self._cap.isOpened():
            self._cap.release()
            self.get_logger().info('Camera released.')
        self._udp_sock.close()
        super().destroy_node()


# ── Entry point ────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = CameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
