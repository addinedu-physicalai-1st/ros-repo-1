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

/image (sensor_msgs/CompressedImage) 토픽을 구독하고 YOLO 추론을 수행해
검출 결과만 /child_detected Bool 토픽으로 퍼블리시합니다.

cv2.VideoCapture 를 제거하고 pinky_camera 패키지가 퍼블리시하는
/image CompressedImage 토픽을 구독하도록 리팩터링되었습니다.
여러 노드가 동일 토픽을 공유하므로 카메라 접근 충돌이 발생하지 않습니다.

Architecture
------------
  pinky_camera node
       │  /image (CompressedImage, JPEG q=90)
       ▼
  _image_callback   ←── 구독 콜백 (디코딩 후 self.frame 저장)
       │
       ▼
  _detect (timer)   ←── 추론 타이머 (YOLO inference)
       │
       ▼
  /child_detected (std_msgs/Bool)
       │
       ▼
  safety_layer_node  →  /cmd_vel

Fail-safe
---------
CAMERA_TIMEOUT_S 초 동안 /image 메시지가 수신되지 않으면
child_detected = True 를 퍼블리시해 로봇을 정지시킵니다.

ROS Parameters
--------------
capture_rate_hz   (float,  default 10.0) – 초당 추론 횟수
model_path        (string, default './best.pt')
confidence        (float,  default 0.5)
child_class_names (list,   default ['kid'])
"""

import os

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage  # [CHANGED] VideoCapture → 토픽 구독
from std_msgs.msg import Bool
from ultralytics import YOLO

# ── Topics ─────────────────────────────────────────────────────────────────────
IMAGE_TOPIC = '/image'             # [CHANGED] 카메라 입력 소스
CHILD_DETECTED_TOPIC = 'child_detected'

# ── Default constants ──────────────────────────────────────────────────────────
DEFAULT_CAPTURE_RATE_HZ = 10.0    # 추론 타이머 주기 (Hz)
DEFAULT_MODEL_PATH = './best.pt'
DEFAULT_CONFIDENCE = 0.5
DEFAULT_CHILD_CLASS_NAMES = ['kid']

# 이 시간 동안 /image 메시지가 없으면 fail-safe 발동
CAMERA_TIMEOUT_S = 1.0


class ChildDetectionNode(Node):
    """
    /image CompressedImage 기반 YOLO 아동 감지 노드.

    Subscribes
    ----------
    /image  (sensor_msgs/CompressedImage)
        pinky_camera 가 퍼블리시하는 JPEG 압축 이미지

    Publishes
    ---------
    /child_detected  (std_msgs/Bool)
        True  : 현재 프레임에서 아동이 감지됨 → safety_layer 가 로봇 정지
        False : 아동 미감지 → 정상 주행 허용
    """

    def __init__(self):
        super().__init__('child_detection_node')

        # ── ROS parameters ─────────────────────────────────────────────────────
        # [CHANGED] camera_index 파라미터 제거 — 더 이상 VideoCapture 불필요
        self.declare_parameter('capture_rate_hz', DEFAULT_CAPTURE_RATE_HZ)
        self.declare_parameter('model_path', DEFAULT_MODEL_PATH)
        self.declare_parameter('confidence', DEFAULT_CONFIDENCE)
        self.declare_parameter('child_class_names', DEFAULT_CHILD_CLASS_NAMES)

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
        # [CHANGED] self.cap → self.frame: 최신 디코딩 프레임을 보관합니다.
        # 구독 콜백이 갱신하고, 추론 타이머가 읽습니다.
        self.frame = None             # np.ndarray | None

        # 마지막으로 /image 메시지가 수신된 시각. None = 아직 한 번도 없음.
        self.last_frame_time = None   # rclpy.time.Time | None

        # ── Publisher ──────────────────────────────────────────────────────────
        self.child_detected_pub = self.create_publisher(Bool, CHILD_DETECTED_TOPIC, 10)

        # ── [CHANGED] /image 구독 ──────────────────────────────────────────────
        # VideoCapture.read() 루프를 제거하고 토픽 구독으로 대체합니다.
        # 콜백은 디코딩만 수행하고 즉시 반환해 스핀을 블로킹하지 않습니다.
        self.create_subscription(
            CompressedImage,
            IMAGE_TOPIC,
            self._image_callback,
            10,
        )

        # ── [CHANGED] 추론 타이머 ──────────────────────────────────────────────
        # 과거의 capture 타이머와 역할이 같지만, 이제는 카메라를 직접 읽지 않고
        # self.frame 에 저장된 최신 프레임을 가져다 YOLO 추론만 수행합니다.
        self.inference_timer = self.create_timer(
            1.0 / capture_rate_hz,
            self._detect,
        )

        # ── Watchdog timer ─────────────────────────────────────────────────────
        # /image 메시지가 끊겼을 때 fail-safe 퍼블리시를 보장합니다.
        self.watchdog_timer = self.create_timer(
            CAMERA_TIMEOUT_S / 2.0,
            self._watchdog_callback,
        )

        self.get_logger().info('ChildDetectionNode started.')
        self.get_logger().info(f'  Subscribing          : {IMAGE_TOPIC}')
        self.get_logger().info(f'  Inference rate       : {capture_rate_hz} Hz')
        self.get_logger().info(f'  Publishing           : {CHILD_DETECTED_TOPIC}')
        self.get_logger().info(f'  Confidence threshold : {self.confidence}')
        self.get_logger().info(f'  Child class names    : {sorted(self.child_class_names)}')
        self.get_logger().info(f'  Camera timeout       : {CAMERA_TIMEOUT_S} s')

    # ── [CHANGED] /image subscription callback ────────────────────────────────

    def _image_callback(self, msg: CompressedImage):
        """
        CompressedImage 메시지를 수신해 OpenCV BGR 프레임으로 디코딩합니다.

        무거운 YOLO 추론은 이 콜백에서 수행하지 않습니다.
        디코딩된 프레임을 self.frame 에 저장하고 즉시 반환합니다.
        """
        # CompressedImage.data → numpy 배열 → BGR 프레임
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is None:
            self.get_logger().warn(
                'Failed to decode CompressedImage.',
                throttle_duration_sec=1.0,
            )
            return

        # 최신 프레임과 수신 시각 갱신
        self.frame = frame
        self.last_frame_time = self.get_clock().now()

    # ── [CHANGED] Inference timer (replaces _capture_and_detect) ──────────────

    def _detect(self):
        """
        추론 타이머 콜백: self.frame 에서 YOLO 추론 후 결과를 퍼블리시합니다.

        self.frame 이 None 이면 (아직 메시지 미수신) 이번 사이클은 건너뜁니다.
        watchdog 이 timeout 을 처리합니다.
        """
        if self.frame is None:
            # 아직 첫 프레임이 도착하지 않음 — watchdog 이 처리
            return

        # 콜백과의 경쟁 조건을 최소화하기 위해 레퍼런스를 로컬 변수로 복사합니다.
        # (GIL 하에서 단순 대입은 원자적이므로 별도 락 불필요)
        frame = self.frame

        # ── YOLO inference ─────────────────────────────────────────────────────
        try:
            results = self.model(frame, conf=self.confidence, verbose=False)
        except Exception as exc:
            self.get_logger().error(
                f'YOLO inference failed: {exc}',
                throttle_duration_sec=2.0,
            )
            return

        # ── Detection logic ────────────────────────────────────────────────────
        child_present = self._child_in_results(results)

        # ── Publish ────────────────────────────────────────────────────────────
        self._publish(child_present)

        if child_present:
            self.get_logger().warn(
                'Child detected in frame!',
                throttle_duration_sec=1.0,
            )

    # ── Watchdog callback ──────────────────────────────────────────────────────

    def _watchdog_callback(self):
        """
        /image 스트림이 멈췄을 때 fail-safe 로 child_detected=True 를 퍼블리시합니다.

        last_frame_time 이 갱신되지 않으면 timeout 을 감지해 로봇을 정지시킵니다.
        """
        if self.last_frame_time is None:
            self.get_logger().warn(
                'No image received yet — '
                'publishing child_detected=True as a precaution.',
                throttle_duration_sec=5.0,
            )
            self._publish(True)
            return

        elapsed = (self.get_clock().now() - self.last_frame_time).nanoseconds / 1e9
        if elapsed > CAMERA_TIMEOUT_S:
            self.get_logger().warn(
                f'/image silent for {elapsed:.1f} s '
                f'(timeout={CAMERA_TIMEOUT_S} s) — '
                'publishing child_detected=True (fail-safe stop).',
                throttle_duration_sec=1.0,
            )
            self._publish(True)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _child_in_results(self, results) -> bool:
        """
        YOLO 결과에서 아동 클래스가 하나라도 있으면 True 를 반환합니다.

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
        """Bool 메시지를 /child_detected 에 퍼블리시합니다."""
        msg = Bool()
        msg.data = detected
        self.child_detected_pub.publish(msg)

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def destroy_node(self):
        """노드 종료 시 정리합니다."""
        # [CHANGED] cv2.VideoCapture 핸들 해제 코드 제거 — 더 이상 카메라를 직접 열지 않음
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
