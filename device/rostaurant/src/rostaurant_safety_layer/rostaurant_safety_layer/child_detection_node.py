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
Child Detection Node — Camera-LiDAR Fusion 3-Zone Safety System.

YOLO로 아이를 감지하고 LiDAR로 거리를 측정해 3단계 안전 구역을 결정합니다.

Architecture
------------
  /image (CompressedImage)   → _image_callback → self._latest_frame
  /scan  (LaserScan)         → _scan_callback  → self._latest_scan
  /camera/camera_info        → _camera_info_cb → self._fx, self._cx

  YOLO inference (rate-limited to yolo_interval_sec):
    bbox 중심 픽셀 u → θ = atan2(u-cx, fx)
    → LiDAR 최솟값 d (θ±angle_window 구간)
    → zone 결정 → 퍼블리시

  cmd_vel 파이프라인:
    nav2 → cmd_vel_raw → safety_layer_node → cmd_vel
    child_detection_node → child_safety_zone → safety_layer_node
      CAUTION 시 cmd_vel_raw 를 50% 스케일링 / STOP 시 속도 0 으로 발행

Publishes
---------
  child_safety_zone (std_msgs/String)  NORMAL / MONITOR / CAUTION / STOP

Fail-safe
---------
CAMERA_TIMEOUT_S 동안 /image가 없으면 STOP 퍼블리시.
5Hz 하트비트 타이머로 safety_layer 1초 타임아웃 방지.

ROS Parameters
--------------
  zone_stop           float  0.3    m
  zone_caution        float  0.8    m
  zone_monitor        float  1.5    m
  angle_window_deg    float  8.0    deg  - LiDAR 탐색 반폭
  angle_offset_rad    float  0.0    rad  - 마운팅 보정값
  yolo_model          str    'best.pt'
  yolo_interval_sec   float  0.2    s    - 추론 최소 간격
  camera_fx           float  0.0    px   - camera_info 없을 때 fallback
  camera_cx           float  0.0    px   - camera_info 없을 때 fallback
  confidence          float  0.5
  child_class_names   list   ['child']
"""

import math
import os
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, CompressedImage, LaserScan
from std_msgs.msg import String
from ultralytics import YOLO

try:
    from pinky_interfaces.srv import Emotion, SetLed
    _HAS_PINKY = True
except ImportError:
    _HAS_PINKY = False

# ── Topic names ────────────────────────────────────────────────────────────────
IMAGE_TOPIC = '/image'
SCAN_TOPIC = '/scan'
CAMERA_INFO_TOPIC = '/camera/camera_info'
CHILD_SAFETY_ZONE_TOPIC = 'child_safety_zone'

# ── Zone identifiers ───────────────────────────────────────────────────────────
ZONE_NORMAL = 'NORMAL'
ZONE_MONITOR = 'MONITOR'
ZONE_CAUTION = 'CAUTION'
ZONE_STOP = 'STOP'

# ── LED colors (R, G, B) per zone ──────────────────────────────────────────────
_ZONE_LED = {
    ZONE_NORMAL:  (0, 255, 0),     # 초록
    ZONE_MONITOR: (0, 0, 255),     # 청색
    ZONE_CAUTION: (255, 165, 0),   # 황색
    ZONE_STOP:    (255, 0, 0),     # 적색
}

# ── Emotion name per zone ──────────────────────────────────────────────────────
_ZONE_EMOTION = {
    ZONE_NORMAL:  'happy',
    ZONE_MONITOR: 'interest',
    ZONE_CAUTION: 'sad',
    ZONE_STOP:    'angry',
}

# 이 시간 동안 /image가 없으면 STOP 퍼블리시
CAMERA_TIMEOUT_S = 1.0

# 하트비트 타이머 주기: safety_layer 1초 타임아웃 방지
HEARTBEAT_HZ = 5.0


class ChildDetectionNode(Node):
    """
    카메라-LiDAR 융합 3단계 안전 구역 감지 노드.

    Subscribes
    ----------
    /image               sensor_msgs/CompressedImage  - JPEG 압축 카메라 이미지
    /scan                sensor_msgs/LaserScan         - 360도 LiDAR 스캔
    /camera/camera_info  sensor_msgs/CameraInfo        - 카메라 내부 파라미터 (선택)

    Publishes
    ---------
    child_safety_zone std_msgs/String  NORMAL / MONITOR / CAUTION / STOP
    """

    def __init__(self):
        super().__init__('child_detection_node')

        # ── Parameters ─────────────────────────────────────────────────────────
        self.declare_parameter('zone_stop',          0.3)
        self.declare_parameter('zone_caution',       0.8)
        self.declare_parameter('zone_monitor',       1.5)
        self.declare_parameter('angle_window_deg',   8.0)
        self.declare_parameter('angle_offset_rad',   0.0)
        self.declare_parameter('yolo_model',         './best.pt')
        self.declare_parameter('yolo_interval_sec',  0.2)
        self.declare_parameter('camera_fx',          0.0)
        self.declare_parameter('camera_cx',          0.0)
        self.declare_parameter('confidence',         0.5)
        self.declare_parameter('child_class_names',  ['kid'])
        self.declare_parameter('show_window',        False)

        self._zone_stop    = self.get_parameter('zone_stop').value
        self._zone_caution = self.get_parameter('zone_caution').value
        self._zone_monitor = self.get_parameter('zone_monitor').value
        self._angle_window = math.radians(self.get_parameter('angle_window_deg').value)
        self._angle_offset = self.get_parameter('angle_offset_rad').value
        self._yolo_interval = self.get_parameter('yolo_interval_sec').value
        self._confidence   = self.get_parameter('confidence').value
        self._child_classes: set = {
            n.lower()
            for n in self.get_parameter('child_class_names')
            .get_parameter_value().string_array_value
        }

        # 카메라 내부 파라미터 (camera_info 수신 전 fallback)
        self._fx: float = self.get_parameter('camera_fx').value
        self._cx: float = self.get_parameter('camera_cx').value
        self._show_window: bool = self.get_parameter('show_window').value

        # ── YOLO model ─────────────────────────────────────────────────────────
        model_path: str = self.get_parameter('yolo_model').value
        self.get_logger().info(f'Loading YOLO model: {model_path}')
        if not os.path.isfile(model_path):
            self.get_logger().warn(
                f'Model file not found at "{model_path}". '
                'YOLO will attempt to use a default model. '
                'Set the correct path via the "yolo_model" parameter.'
            )
        self._model = YOLO(model_path)
        self.get_logger().info('YOLO model loaded.')

        # ── Internal state ─────────────────────────────────────────────────────
        self._latest_frame = None     # np.ndarray | None
        self._latest_scan  = None     # LaserScan | None
        self._last_frame_t = None     # float (monotonic) | None
        self._last_infer_t = 0.0      # float (monotonic): 마지막 추론 시각
        self._current_zone = None     # str | None: 마지막으로 결정된 구역

        # ── Publishers ─────────────────────────────────────────────────────────
        self._safety_zone_pub = self.create_publisher(String, CHILD_SAFETY_ZONE_TOPIC, 10)

        # ── Subscribers ────────────────────────────────────────────────────────
        self.create_subscription(CompressedImage, IMAGE_TOPIC, self._image_callback, 10)
        self.create_subscription(LaserScan, SCAN_TOPIC, self._scan_callback, 10)
        self.create_subscription(CameraInfo, CAMERA_INFO_TOPIC, self._camera_info_callback, 10)

        # ── LED / Emotion service clients ──────────────────────────────────────
        self._led_client = None
        self._emotion_client = None
        if _HAS_PINKY:
            self._led_client = self.create_client(SetLed, 'set_led')
            self._emotion_client = self.create_client(Emotion, 'set_emotion')
        else:
            self.get_logger().warn(
                'pinky_interfaces not available — LED/emotion control disabled.'
            )

        # ── Heartbeat timer (5Hz) ──────────────────────────────────────────────
        # safety_layer의 1초 타임아웃을 방지하고 camera watchdog을 겸합니다.
        self.create_timer(1.0 / HEARTBEAT_HZ, self._heartbeat_callback)

        self.get_logger().info('ChildDetectionNode (camera-LiDAR fusion) started.')
        self.get_logger().info(f'  Image topic        : {IMAGE_TOPIC}')
        self.get_logger().info(f'  Scan topic         : {SCAN_TOPIC}')
        self.get_logger().info(f'  zone_stop={self._zone_stop}m  '
                               f'zone_caution={self._zone_caution}m  '
                               f'zone_monitor={self._zone_monitor}m')
        self.get_logger().info(f'  YOLO interval      : {self._yolo_interval} s')
        self.get_logger().info(f'  Child class names  : {sorted(self._child_classes)}')
        self.get_logger().info(f'  camera_fx={self._fx}  camera_cx={self._cx}')
        self.get_logger().info(
            f'  Publishing         : {CHILD_SAFETY_ZONE_TOPIC} → safety_layer / event_recorder'
        )

    # ── Subscription callbacks ─────────────────────────────────────────────────

    def _image_callback(self, msg: CompressedImage):
        """CompressedImage를 디코딩하고 rate-limit된 추론을 트리거합니다."""
        np_arr = np.frombuffer(msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            self.get_logger().warn(
                'Failed to decode CompressedImage.',
                throttle_duration_sec=1.0,
            )
            return
        self._latest_frame = frame
        self._last_frame_t = time.monotonic()
        self._maybe_infer()

    def _scan_callback(self, msg: LaserScan):
        """항상 최신 LiDAR 스캔을 유지합니다. 추론 주기와 무관하게 갱신."""
        self._latest_scan = msg

    def _camera_info_callback(self, msg: CameraInfo):
        """CameraInfo에서 fx, cx를 추출해 내부 파라미터를 갱신합니다."""
        # K = [fx 0 cx 0 fy cy 0 0 1] (row-major 3×3)
        if msg.k[0] == 0.0:
            return
        self._fx = msg.k[0]
        self._cx = msg.k[2]
        self.get_logger().info(
            f'Camera info received: fx={self._fx:.1f}, cx={self._cx:.1f}',
            throttle_duration_sec=10.0,
        )

    # ── Inference (rate-limited) ───────────────────────────────────────────────

    def _maybe_infer(self):
        """0.2초 간격으로 YOLO 추론을 실행합니다."""
        now = time.monotonic()
        if now - self._last_infer_t < self._yolo_interval:
            return
        self._last_infer_t = now

        # 필수 데이터 준비 확인
        if self._latest_scan is None:
            self.get_logger().warn(
                'LiDAR scan not yet received — skipping inference.',
                throttle_duration_sec=5.0,
            )
            return
        if self._fx == 0.0:
            self.get_logger().warn(
                'Camera intrinsics not set (camera_fx=0). '
                'Set camera_fx/camera_cx parameters or publish /camera/camera_info.',
                throttle_duration_sec=5.0,
            )
            return

        frame = self._latest_frame
        scan  = self._latest_scan

        # ── YOLO inference ─────────────────────────────────────────────────────
        try:
            results = self._model(frame, conf=self._confidence, verbose=False)
        except Exception as exc:
            self.get_logger().error(
                f'YOLO inference failed: {exc}',
                throttle_duration_sec=2.0,
            )
            return

        # ── Find closest child across all detections ───────────────────────────
        min_dist = float('inf')
        child_found = False
        vis_frame = frame.copy() if self._show_window else None

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_name = result.names.get(int(box.cls.item()), '').lower()
                conf_val = float(box.conf.item())
                xyxy = box.xyxy[0].tolist()
                x1, y1, x2, y2 = (int(v) for v in xyxy)

                is_child = cls_name in self._child_classes

                # 시각화: 모든 bbox 표시 (child=초록, 기타=회색)
                if self._show_window:
                    color = (0, 255, 0) if is_child else (160, 160, 160)
                    cv2.rectangle(vis_frame, (x1, y1), (x2, y2), color, 2)
                    label = f'{cls_name} {conf_val:.2f}'
                    (tw, th), _ = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
                    cv2.rectangle(vis_frame,
                                  (x1, y1 - th - 6), (x1 + tw + 4, y1),
                                  color, -1)
                    cv2.putText(vis_frame, label,
                                (x1 + 2, y1 - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                                (0, 0, 0), 1, cv2.LINE_AA)

                if not is_child:
                    continue
                child_found = True

                # bbox 중심 픽셀 u → 수평 각도 θ
                u = (xyxy[0] + xyxy[2]) / 2.0
                theta_cam = math.atan2(u - self._cx, self._fx)

                d = self._lidar_range_at(scan, theta_cam)
                if d < min_dist:
                    min_dist = d

        # ── Zone 결정 ──────────────────────────────────────────────────────────
        if not child_found or min_dist == float('inf'):
            zone = ZONE_NORMAL
        elif min_dist < self._zone_stop:
            zone = ZONE_STOP
        elif min_dist < self._zone_caution:
            zone = ZONE_CAUTION
        elif min_dist < self._zone_monitor:
            zone = ZONE_MONITOR
        else:
            zone = ZONE_NORMAL

        # ── OpenCV 시각화 ──────────────────────────────────────────────────────
        if self._show_window and vis_frame is not None:
            zone_color = {
                ZONE_NORMAL:  (0, 255, 0),
                ZONE_MONITOR: (255, 180, 0),
                ZONE_CAUTION: (0, 140, 255),
                ZONE_STOP:    (0, 0, 255),
            }
            dist_str = f'{min_dist:.2f} m' if min_dist != float('inf') else '--'
            overlay = f'Zone: {zone}  dist: {dist_str}'
            color = zone_color.get(zone, (255, 255, 255))
            cv2.putText(vis_frame, overlay,
                        (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(vis_frame, overlay,
                        (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        color, 2, cv2.LINE_AA)
            cv2.imshow('child_detection', vis_frame)
            cv2.waitKey(1)

        self._apply_zone(zone)

    def _lidar_range_at(self, scan: LaserScan, theta_cam: float) -> float:
        """
        theta_cam 방향 ±angle_window 구간에서 LiDAR 최솟값을 반환합니다.

        카메라 오른쪽 = LiDAR 음수 각도이므로 theta_lidar = -theta_cam 변환.
        """
        theta_lidar = -theta_cam + self._angle_offset

        lo = max(scan.angle_min, theta_lidar - self._angle_window)
        hi = min(scan.angle_max, theta_lidar + self._angle_window)
        if lo > hi:
            return float('inf')

        step = scan.angle_increment
        idx_lo = max(0, int((lo - scan.angle_min) / step))
        idx_hi = min(len(scan.ranges) - 1, int((hi - scan.angle_min) / step))

        valid = [
            r for r in scan.ranges[idx_lo:idx_hi + 1]
            if scan.range_min <= r <= scan.range_max
        ]
        return min(valid) if valid else float('inf')

    # ── Heartbeat / watchdog ───────────────────────────────────────────────────

    def _heartbeat_callback(self):
        """
        5Hz 하트비트:
        - camera timeout 시 STOP 퍼블리시 (fail-safe)
        - 정상 시 현재 zone 재퍼블리시 (safety_layer 타임아웃 방지)
        """
        if self._last_frame_t is None:
            # 아직 첫 프레임 미수신 — safety_layer 자체 타임아웃이 처리
            return

        elapsed = time.monotonic() - self._last_frame_t
        if elapsed > CAMERA_TIMEOUT_S:
            self.get_logger().warn(
                f'/image silent for {elapsed:.1f} s (timeout={CAMERA_TIMEOUT_S} s) '
                '— publishing STOP (fail-safe).',
                throttle_duration_sec=1.0,
            )
            self._apply_zone(ZONE_STOP)
            return

        # 정상 상태: 현재 zone을 재퍼블리시 (heartbeat)
        if self._current_zone is not None:
            self._publish_state(self._current_zone)

    # ── Zone apply & publish ───────────────────────────────────────────────────

    def _apply_zone(self, zone: str):
        """Zone을 퍼블리시하고, 변경 시에만 LED/emotion 서비스를 호출합니다."""
        self._publish_state(zone)

        if zone == self._current_zone:
            return

        self.get_logger().info(f'Safety zone: {self._current_zone} → {zone}')
        self._current_zone = zone

        self._call_set_led(zone)
        self._call_set_emotion(zone)

    def _publish_state(self, zone: str):
        """child_safety_zone (String) 을 퍼블리시합니다."""
        zone_msg = String()
        zone_msg.data = zone
        self._safety_zone_pub.publish(zone_msg)

    # ── LED / Emotion ──────────────────────────────────────────────────────────

    def _call_set_led(self, zone: str):
        if self._led_client is None or not self._led_client.service_is_ready():
            return
        r, g, b = _ZONE_LED[zone]
        req = SetLed.Request()
        req.command = 'fill'
        req.r = r
        req.g = g
        req.b = b
        self._led_client.call_async(req)

    def _call_set_emotion(self, zone: str):
        if self._emotion_client is None or not self._emotion_client.service_is_ready():
            return
        req = Emotion.Request()
        req.emotion = _ZONE_EMOTION[zone]
        self._emotion_client.call_async(req)


# ── Entry point ────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = ChildDetectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
