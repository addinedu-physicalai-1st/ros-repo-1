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
YOLO Viewer Node — UDP 멀티캐스트 이미지 수신 + YOLO 추론 시각화.

UDP Multicast(239.255.0.1:5000)에서 JPEG 프레임을 수신하고,
YOLO 추론 결과(bbox, 클래스, confidence)를 OpenCV 창에 표시합니다.

Architecture
------------
  UDP Multicast 239.255.0.1:5000
       │  [frame_id(4B) | data_len(4B) | JPEG]
       ▼
  백그라운드 스레드 (recvfrom)
       │  BGR ndarray
       ▼
  YOLO 추론 (rate-limited, yolo_interval_sec)
       │  results
       ▼
  OpenCV 창 (cv2.imshow)

ROS Parameters
--------------
  yolo_model          str    './best.pt'
  yolo_interval_sec   float  0.1         추론 최소 간격(초)
  confidence          float  0.5
  child_class_names   list   ['kid']     이 클래스는 초록, 나머지는 회색
  window_name         str    'YOLO Viewer'
"""

import os
import socket
import struct
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from ultralytics import YOLO

# ── UDP Multicast ──────────────────────────────────────────────────────────────
MULTICAST_GROUP = '239.255.0.1'
MULTICAST_PORT  = 5000

# 클래스별 bbox 색상
COLOR_TARGET = (0, 255, 0)    # 감시 대상 클래스 (초록)
COLOR_OTHER  = (160, 160, 160)  # 그 외 클래스 (회색)


class YoloViewerNode(Node):
    """
    UDP 멀티캐스트 이미지를 수신하여 YOLO 추론 결과를 OpenCV 창에 표시합니다.

    ROS 토픽 발행/구독 없이 순수 시각화 목적으로 동작합니다.
    """

    def __init__(self):
        super().__init__('yolo_viewer_node')

        # ── Parameters ─────────────────────────────────────────────────────────
        self.declare_parameter('yolo_model',         './best.pt')
        self.declare_parameter('yolo_interval_sec',  0.1)
        self.declare_parameter('confidence',         0.5)
        self.declare_parameter('child_class_names',  ['kid'])
        self.declare_parameter('window_name',        'YOLO Viewer')

        model_path: str = self.get_parameter('yolo_model').value
        self._yolo_interval: float = self.get_parameter('yolo_interval_sec').value
        self._confidence: float = self.get_parameter('confidence').value
        self._target_classes: set = {
            n.lower()
            for n in self.get_parameter('child_class_names')
            .get_parameter_value().string_array_value
        }
        self._window_name: str = self.get_parameter('window_name').value

        # ── YOLO 모델 로드 ──────────────────────────────────────────────────────
        self.get_logger().info(f'Loading YOLO model: {model_path}')
        if not os.path.isfile(model_path):
            self.get_logger().warn(
                f'Model file not found at "{model_path}". '
                'YOLO will attempt to use a default model.'
            )
        self._model = YOLO(model_path)
        self.get_logger().info('YOLO model loaded.')

        # ── 내부 상태 ───────────────────────────────────────────────────────────
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._last_infer_t: float = 0.0

        # ── UDP Multicast 소켓 ──────────────────────────────────────────────────
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

        # ── 추론·표시 타이머 ────────────────────────────────────────────────────
        # rclpy.spin() 스레드에서 imshow를 호출하기 위해 타이머를 사용합니다.
        self._display_timer = self.create_timer(self._yolo_interval, self._infer_and_display)

        self.get_logger().info(
            f'YoloViewerNode started. '
            f'interval={self._yolo_interval}s  '
            f'conf={self._confidence}  '
            f'target={sorted(self._target_classes)}'
        )

    # ── UDP 수신 루프 (백그라운드 스레드) ──────────────────────────────────────

    def _udp_recv_loop(self):
        """멀티캐스트 UDP 패킷을 블로킹 수신하여 _latest_frame 을 갱신합니다."""
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

    # ── 추론 & 시각화 타이머 콜백 ──────────────────────────────────────────────

    def _infer_and_display(self):
        """YOLO 추론 후 bbox를 그려 OpenCV 창에 표시합니다."""
        with self._frame_lock:
            frame = self._latest_frame

        if frame is None:
            self.get_logger().info(
                'UDP 이미지 미수신 — 대기 중.', throttle_duration_sec=3.0,
            )
            return

        # ── YOLO 추론 ──────────────────────────────────────────────────────────
        try:
            results = self._model(frame, conf=self._confidence, verbose=False)
        except Exception as exc:
            self.get_logger().error(
                f'YOLO 추론 실패: {exc}', throttle_duration_sec=2.0,
            )
            return

        vis = frame.copy()

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_name = result.names.get(int(box.cls.item()), '').lower()
                conf_val = float(box.conf.item())
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())

                is_target = cls_name in self._target_classes
                color = COLOR_TARGET if is_target else COLOR_OTHER

                # bbox 사각형
                cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)

                # 레이블 배경 + 텍스트
                label = f'{cls_name} {conf_val:.2f}'
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
                cv2.rectangle(vis, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
                cv2.putText(
                    vis, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA,
                )

        cv2.imshow(self._window_name, vis)
        cv2.waitKey(1)

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def destroy_node(self):
        """노드 종료 시 UDP 소켓과 OpenCV 창을 닫습니다."""
        self._udp_sock.close()
        cv2.destroyAllWindows()
        super().destroy_node()


# ── Entry point ────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = YoloViewerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
