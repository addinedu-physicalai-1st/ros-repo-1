#!/usr/bin/env python3
"""
pinky_docking - ArUco marker tracking & docking node
카메라로 아르코 마커를 탐지하고, 모터를 제어하여 마커를 향해 이동하는 ROS2 노드.

Topics Published:
  /docking/status  (std_msgs/String)

Topics Subscribed:
  /docking/cmd    (std_msgs/String) - "start" / "stop"

Services:
  /docking/start  (std_srvs/SetBool)
"""

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import ParameterDescriptor

from std_msgs.msg import String
from std_srvs.srv import SetBool

import cv2
import numpy as np
import threading
import time

from pinkylib import Camera
from pinkylib import Motor


DEFAULT_TARGET_ID       = 0
DEFAULT_TARGET_DIST_CM  = 15.0
DEFAULT_MAX_SPEED       = 40.0
DEFAULT_KP_LINEAR       = 1.5
DEFAULT_KP_ANGULAR      = 0.8
DEFAULT_DEAD_ZONE_X_CM  = 2.0
DEFAULT_ANGLE_THRESH_DEG = 10.0   # 1단계/2단계 전환 각도
DEFAULT_CAMERA_WIDTH    = 640
DEFAULT_CAMERA_HEIGHT   = 480
DEFAULT_MARKER_SIZE_M   = 0.05
DEFAULT_CALIB_PATH      = ""


class DockingNode(Node):

    def __init__(self):
        super().__init__('docking_node')
        self._declare_parameters()

        self.target_id      = self.get_parameter('target_id').value
        self.target_dist    = self.get_parameter('target_dist_cm').value
        self.max_speed      = self.get_parameter('max_speed').value
        self.kp_linear      = self.get_parameter('kp_linear').value
        self.kp_angular     = self.get_parameter('kp_angular').value
        self.dead_zone_x    = self.get_parameter('dead_zone_x_cm').value
        self.angle_thresh   = np.deg2rad(self.get_parameter('angle_thresh_deg').value)
        self.cam_width      = self.get_parameter('camera_width').value
        self.cam_height     = self.get_parameter('camera_height').value
        self.marker_size    = self.get_parameter('marker_size_m').value
        self.calib_path     = self.get_parameter('calib_path').value

        self._running = False
        self._docked  = False
        self._lock    = threading.Lock()

        self.get_logger().info("카메라 초기화 중...")
        self.camera = Camera()
        self.camera.start(width=self.cam_width, height=self.cam_height)
        if self.calib_path:
            try:
                self.camera.set_calibration(self.calib_path)
                self.get_logger().info(f"캘리브레이션 파일 로드: {self.calib_path}")
            except Exception as e:
                self.get_logger().warn(f"캘리브레이션 로드 실패: {e}")

        self.get_logger().info("모터 초기화 중...")
        self.motor = Motor()

        self.status_pub = self.create_publisher(String, '/docking/status', 10)
        self.cmd_sub    = self.create_subscription(
            String, '/docking/cmd', self._cmd_callback, 10)
        self.srv = self.create_service(
            SetBool, '/docking/start', self._start_service_callback)
        self.status_timer = self.create_timer(1.0, self._publish_status)

        self._thread = threading.Thread(target=self._docking_loop, daemon=True)
        self._thread.start()

        self.get_logger().info("✅ pinky_docking 노드 시작 완료")
        self.get_logger().info(f"   타겟 마커 ID : {self.target_id}")
        self.get_logger().info(f"   정지 거리   : {self.target_dist} cm")

    def _declare_parameters(self):
        desc = lambda d: ParameterDescriptor(description=d)
        self.declare_parameter('target_id',        DEFAULT_TARGET_ID,        desc('추종할 ArUco 마커 ID'))
        self.declare_parameter('target_dist_cm',   DEFAULT_TARGET_DIST_CM,   desc('도킹 완료 판정 거리 (cm)'))
        self.declare_parameter('max_speed',        DEFAULT_MAX_SPEED,        desc('최대 모터 속도 0-100'))
        self.declare_parameter('kp_linear',        DEFAULT_KP_LINEAR,        desc('선형 속도 비례 게인'))
        self.declare_parameter('kp_angular',       DEFAULT_KP_ANGULAR,       desc('각도 보정 비례 게인'))
        self.declare_parameter('dead_zone_x_cm',   DEFAULT_DEAD_ZONE_X_CM,   desc('X 방향 데드존 (cm)'))
        self.declare_parameter('angle_thresh_deg', DEFAULT_ANGLE_THRESH_DEG, desc('1단계→2단계 전환 각도 (deg)'))
        self.declare_parameter('camera_width',     DEFAULT_CAMERA_WIDTH,     desc('카메라 해상도 너비'))
        self.declare_parameter('camera_height',    DEFAULT_CAMERA_HEIGHT,    desc('카메라 해상도 높이'))
        self.declare_parameter('marker_size_m',    DEFAULT_MARKER_SIZE_M,    desc('ArUco 마커 실물 크기 (m)'))
        self.declare_parameter('calib_path',       DEFAULT_CALIB_PATH,       desc('캘리브레이션 파일 경로'))

    def _cmd_callback(self, msg: String):
        cmd = msg.data.strip().lower()
        if cmd == 'start':
            self._start_docking()
        elif cmd == 'stop':
            self._stop_docking()

    def _start_service_callback(self, request: SetBool.Request,
                                response: SetBool.Response):
        if request.data:
            self._start_docking()
            response.success = True
            response.message = "도킹 시작"
        else:
            self._stop_docking()
            response.success = True
            response.message = "도킹 정지"
        return response

    def _start_docking(self):
        with self._lock:
            if self._running:
                self.get_logger().info("이미 도킹 동작 중입니다.")
                return
            self._running = True
            self._docked  = False
        self.get_logger().info("🚀 도킹 시작")

    def _stop_docking(self):
        with self._lock:
            self._running = False
        self.motor.stop()
        self.get_logger().info("🛑 도킹 정지")

    def _docking_loop(self):
        """
        ρ/θ 2단계 제어:
          1단계 ALIGN  : |θ| > angle_thresh → 제자리 회전
          2단계 ADVANCE: |θ| ≤ angle_thresh → 전진 + 미세 조향
        """
        while rclpy.ok():
            with self._lock:
                running = self._running
            if not running:
                time.sleep(0.05)
                continue

            try:
                frame = self.camera.get_frame()
            except Exception as e:
                self.get_logger().error(f"카메라 오류: {e}")
                time.sleep(0.1)
                continue

            pose, debug_frame = self._detect(frame)

            if pose is None:
                self._search_rotate()
                continue

            x_cam, y_cam, z_cam = pose

            rho   = np.sqrt(x_cam**2 + z_cam**2)
            theta = np.arctan2(x_cam, z_cam)   # 양수=오른쪽

            self.get_logger().debug(
                f"ρ={rho:.1f}cm  θ={np.degrees(theta):.1f}°")

            if rho <= self.target_dist:
                self.motor.stop()
                with self._lock:
                    self._docked  = True
                    self._running = False
                self.get_logger().info(
                    f"✅ 도킹 완료! ρ={rho:.1f} cm  θ={np.degrees(theta):.1f}°")
                continue

            if abs(theta) > self.angle_thresh:
                l, r = self._compute_align(theta)
            else:
                l, r = self._compute_advance(rho, theta)

            self.motor.move(l, r)
            time.sleep(0.03)

    def _detect(self, frame):
        """
        camera.py detect_aruco_target() 반환값을 안전하게 처리.
        항상 (pose, frame) 반환.
        """
        if self.camera.calibration_matrix is not None:
            result = self.camera.detect_aruco_target(
                frame, self.target_id, marker_size=self.marker_size)
            if result is None:
                return None, frame
            debug_frame, pose = result
            return pose, debug_frame
        else:
            return self._detect_no_calib(frame)

    def _detect_no_calib(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_250)
        detector   = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        corners, ids, _ = detector.detectMarkers(gray)

        if ids is None or self.target_id not in ids:
            return None, frame

        idx  = np.where(ids == self.target_id)[0][0]
        c    = corners[idx][0]
        cx   = int(c[:, 0].mean())
        x_cm = (cx - self.cam_width / 2) / (self.cam_width / 2) * 20.0
        area = cv2.contourArea(c)
        z_cm = max(5.0, 3000.0 / (area + 1e-3) * self.marker_size * 100)

        cv2.aruco.drawDetectedMarkers(frame, corners)
        cv2.circle(frame, (cx, int(c[:, 1].mean())), 6, (0, 255, 0), -1)
        cv2.putText(frame, f"id:{self.target_id} x:{x_cm:.1f} z:{z_cm:.1f}",
                    (cx, int(c[:, 1].mean()) - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        return [x_cm, 0.0, z_cm], frame

    def _compute_align(self, theta: float):
        """제자리 회전: θ > 0(오른쪽) → 우회전(L+, R-)"""
        turn_limit = self.max_speed * 0.6
        angular = np.clip(np.degrees(theta) * self.kp_angular,
                          -turn_limit, turn_limit)
        return float(angular), float(-angular)

    def _compute_advance(self, rho: float, theta: float):
        """전진 + 미세 조향"""
        forward = np.clip(
            self.kp_linear * (rho - self.target_dist), 0.0, self.max_speed)
        theta_deg = np.degrees(theta)
        angular = 0.0 if abs(theta_deg) < self.dead_zone_x else \
            np.clip(self.kp_angular * theta_deg,
                    -self.max_speed * 0.5, self.max_speed * 0.5)
        l = np.clip(forward + angular, -self.max_speed, self.max_speed)
        r = np.clip(forward - angular, -self.max_speed, self.max_speed)
        return float(l), float(r)

    def _search_rotate(self):
        self.motor.move(-20.0, 20.0)
        time.sleep(0.1)
        self.motor.stop()

    def _publish_status(self):
        with self._lock:
            running = self._running
            docked  = self._docked
        msg = String()
        msg.data = "DOCKED" if docked else ("RUNNING" if running else "IDLE")
        self.status_pub.publish(msg)


    def destroy_node(self):
        self.get_logger().info("노드 종료 중...")
        with self._lock:
            self._running = False
        try:
            self.motor.close()
        except Exception:
            pass
        try:
            self.camera.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DockingNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("KeyboardInterrupt — 종료합니다.")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()