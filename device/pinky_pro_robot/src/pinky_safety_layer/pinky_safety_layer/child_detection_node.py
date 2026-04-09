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
Child Detection Node for Pinky Pro robot.

카메라 이미지를 ROS 토픽으로 주고받지 않고 OpenCV VideoCapture로
로컬에서 직접 읽어 YOLO 추론을 수행하고, 검출 결과만 /child_detected
Bool 토픽으로 퍼블리시합니다.

네트워크 트래픽
--------------
/image_raw 토픽을 사용하면 30 fps × ~2 MB/frame = ~60 MB/s 가 ROS
미들웨어를 통해 전송됩니다.  VideoCapture를 사용하면 이미지 데이터는
노드 프로세스 안에서만 처리되므로 네트워크 트래픽이 전혀 발생하지
않습니다.  퍼블리시되는 것은 Bool 하나(수 바이트)뿐입니다.

Architecture
------------
  camera hardware
       │  (V4L2 / USB, /dev/videoX)
       ▼
  cv2.VideoCapture   ←── 타이머가 직접 호출
       │
       ▼
  YOLO inference
       │
       ▼
  /child_detected (std_msgs/Bool)
       │
       ▼
  safety_layer_node  →  /cmd_vel

Fail-safe
---------
cap.read() 실패 혹은 캡처 타이머가 한 번도 성공하지 못한 채
CAMERA_TIMEOUT_S 초가 지나면 child_detected = True 를 퍼블리시해
로봇을 정지시킵니다.

ROS Parameters
--------------
camera_index      (int,    default 0)    – VideoCapture 인덱스 (/dev/video0)
capture_rate_hz   (float,  default 10.0) – 초당 캡처·추론 횟수
model_path        (string, default 'child_detection_model.pt')
confidence        (float,  default 0.5)
child_class_names (list,   default ['child', 'person_child'])
"""

import os

import cv2
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool
from ultralytics import YOLO

# ── Topic ──────────────────────────────────────────────────────────────────────
CHILD_DETECTED_TOPIC = 'child_detected'

# ── Default constants ──────────────────────────────────────────────────────────
DEFAULT_CAMERA_INDEX = 0
DEFAULT_CAPTURE_RATE_HZ = 10.0
DEFAULT_MODEL_PATH = 'child_detection_model.pt'
DEFAULT_CONFIDENCE = 0.5
DEFAULT_CHILD_CLASS_NAMES = ['child', 'person_child']

# 이 시간 동안 성공적인 프레임 캡처가 없으면 fail-safe 발동
CAMERA_TIMEOUT_S = 1.0


class ChildDetectionNode(Node):
    """
    OpenCV VideoCapture 기반 YOLO 아동 감지 노드.

    Publishes
    ---------
    /child_detected  (std_msgs/Bool)
        True  : 현재 프레임에서 아동이 감지됨 → safety_layer가 로봇 정지
        False : 아동 미감지 → 정상 주행 허용
    """

    def __init__(self):
        super().__init__('child_detection_node')

        # ── ROS parameters ─────────────────────────────────────────────────────
        self.declare_parameter('camera_index', DEFAULT_CAMERA_INDEX)
        self.declare_parameter('capture_rate_hz', DEFAULT_CAPTURE_RATE_HZ)
        self.declare_parameter('model_path', DEFAULT_MODEL_PATH)
        self.declare_parameter('confidence', DEFAULT_CONFIDENCE)
        self.declare_parameter('child_class_names', DEFAULT_CHILD_CLASS_NAMES)

        camera_index: int = (
            self.get_parameter('camera_index')
            .get_parameter_value().integer_value
        )
        capture_rate_hz: float = (
            self.get_parameter('capture_rate_hz')
            .get_parameter_value().double_value
        )
        model_path: str = (
            self.get_parameter('model_path')
            .get_parameter_value().string_value
        )
        self.confidence: float = (
            self.get_parameter('confidence')
            .get_parameter_value().double_value
        )
        # 소문자 set으로 저장 → O(1) 조회, 대소문자 무관
        self.child_class_names: set = {
            name.lower()
            for name in self.get_parameter('child_class_names')
            .get_parameter_value().string_array_value
        }

        # ── OpenCV VideoCapture ────────────────────────────────────────────────
        self.get_logger().info(f'Opening camera index {camera_index} ...')
        self.cap = cv2.VideoCapture(camera_index)

        if not self.cap.isOpened():
            # 카메라를 열지 못해도 노드는 계속 실행됩니다.
            # watchdog이 timeout을 감지해 로봇을 안전하게 정지시킵니다.
            self.get_logger().error(
                f'Failed to open camera index {camera_index}. '
                'The watchdog will keep the robot stopped until the '
                'camera becomes available.'
            )
        else:
            self.get_logger().info(f'Camera {camera_index} opened successfully.')

        # ── YOLO model ─────────────────────────────────────────────────────────
        self.get_logger().info(f'Loading YOLO model from: {model_path}')
        if not os.path.isfile(model_path):
            self.get_logger().warn(
                f'Model file not found at "{model_path}". '
                'YOLO will attempt to use a default model. '
                'Set the correct path via the "model_path" parameter.'
            )
        self.model = YOLO(model_path)
        self.get_logger().info('YOLO model loaded.')

        # ── Internal state ─────────────────────────────────────────────────────
        # 마지막으로 프레임 캡처에 성공한 시각.  None = 아직 한 번도 성공 못 함.
        self.last_frame_time = None  # rclpy.time.Time | None

        # ── Publisher ──────────────────────────────────────────────────────────
        self.child_detected_pub = self.create_publisher(Bool, CHILD_DETECTED_TOPIC, 10)

        # ── Capture timer ──────────────────────────────────────────────────────
        # 이 타이머가 프레임 읽기 + YOLO 추론 + 퍼블리시를 모두 담당합니다.
        # rclpy.spin() 안에서 싱글스레드로 동작하므로 별도 스레드가 필요 없습니다.
        self.capture_timer = self.create_timer(
            1.0 / capture_rate_hz,
            self._capture_and_detect
        )

        # ── Watchdog timer ─────────────────────────────────────────────────────
        # 캡처 실패가 지속될 때 fail-safe 퍼블리시를 보장합니다.
        self.watchdog_timer = self.create_timer(
            CAMERA_TIMEOUT_S / 2.0,
            self._watchdog_callback
        )

        self.get_logger().info('ChildDetectionNode started.')
        self.get_logger().info(f'  Camera index         : {camera_index}')
        self.get_logger().info(f'  Capture rate         : {capture_rate_hz} Hz')
        self.get_logger().info(f'  Publishing           : {CHILD_DETECTED_TOPIC}')
        self.get_logger().info(f'  Confidence threshold : {self.confidence}')
        self.get_logger().info(f'  Child class names    : {sorted(self.child_class_names)}')
        self.get_logger().info(f'  Camera timeout       : {CAMERA_TIMEOUT_S} s')

    # ── Capture & detect (main loop) ───────────────────────────────────────────

    def _capture_and_detect(self):
        """
        타이머 콜백: 프레임을 읽고 YOLO 추론 후 결과를 퍼블리시합니다.

        cap.read() 실패 시에는 last_frame_time을 갱신하지 않아
        watchdog이 timeout을 감지할 수 있도록 합니다.
        """
        ret, frame = self.cap.read()

        if not ret or frame is None:
            self.get_logger().warn(
                'Failed to capture frame from camera.',
                throttle_duration_sec=1.0
            )
            # 프레임 획득 실패 → 이번 사이클은 건너뜀
            # watchdog이 timeout을 처리합니다.
            return

        # 캡처 성공 → 타임스탬프 갱신
        self.last_frame_time = self.get_clock().now()

        # ── YOLO inference ─────────────────────────────────────────────────────
        try:
            results = self.model(frame, conf=self.confidence, verbose=False)
        except Exception as exc:
            self.get_logger().error(
                f'YOLO inference failed: {exc}',
                throttle_duration_sec=2.0
            )
            return

        # ── Detection logic ────────────────────────────────────────────────────
        child_present = self._child_in_results(results)

        # ── Publish ────────────────────────────────────────────────────────────
        self._publish(child_present)

        if child_present:
            self.get_logger().warn(
                'Child detected in frame!',
                throttle_duration_sec=1.0
            )

    # ── Watchdog callback ──────────────────────────────────────────────────────

    def _watchdog_callback(self):
        """
        카메라 스트림이 멈췄을 때 fail-safe로 child_detected=True를 퍼블리시합니다.

        _capture_and_detect가 cap.read() 실패를 계속하면 last_frame_time이
        갱신되지 않고 이 watchdog이 timeout을 감지해 로봇을 정지시킵니다.
        """
        if self.last_frame_time is None:
            self.get_logger().warn(
                'No frame captured yet — '
                'publishing child_detected=True as a precaution.',
                throttle_duration_sec=5.0
            )
            self._publish(True)
            return

        elapsed = (self.get_clock().now() - self.last_frame_time).nanoseconds / 1e9
        if elapsed > CAMERA_TIMEOUT_S:
            self.get_logger().warn(
                f'Camera silent for {elapsed:.1f} s '
                f'(timeout={CAMERA_TIMEOUT_S} s) — '
                'publishing child_detected=True (fail-safe stop).',
                throttle_duration_sec=1.0
            )
            self._publish(True)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _child_in_results(self, results) -> bool:
        """
        YOLO 결과에서 아동 클래스가 하나라도 있으면 True를 반환합니다.

        Parameters
        ----------
        results : list[ultralytics.engine.results.Results]

        Returns
        -------
        bool
        """
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                class_index = int(box.cls.item())
                class_name = result.names.get(class_index, '').lower()
                if class_name in self.child_class_names:
                    return True
        return False

    def _publish(self, detected: bool):
        """Bool 메시지를 /child_detected에 퍼블리시합니다."""
        msg = Bool()
        msg.data = detected
        self.child_detected_pub.publish(msg)

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def destroy_node(self):
        """노드 종료 시 카메라 핸들을 해제합니다."""
        if self.cap.isOpened():
            self.cap.release()
            self.get_logger().info('Camera released.')
        super().destroy_node()


# ── Entry point ────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = ChildDetectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
