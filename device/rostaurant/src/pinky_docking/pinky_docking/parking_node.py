#!/usr/bin/env python3
"""
pinky_docking — ArUco 마커 기반 Nav2 자율주차 노드
=====================================================
동작 흐름:
  1. [SCANNING]   카메라로 ArUco 마커를 탐지
  2.              마커 pose(카메라 프레임) → map 프레임 TF 변환
  3. [NAVIGATING] Nav2 NavigateToPose action으로 마커 앞까지 자율주행
  4. [DOCKING]    정밀 도킹 (ρ/θ 제어)
                    ① θ 오차 수렴 (제자리 회전) → ② ρ 직진

※ BasicNavigator 대신 NavigateToPose action client 직접 사용.
  BasicNavigator는 독립 프로세스용으로 설계되어 ROS 노드 내부에서
  사용하면 Executor 충돌이 발생합니다.

ROS 2 인터페이스:
  Publish  : /docking/status  (std_msgs/String)
  Publish  : /cmd_vel         (geometry_msgs/Twist)
  Subscribe: /docking/cmd     (std_msgs/String)   — "start" / "stop"
  Service  : /docking/start   (std_srvs/SetBool)
"""

import math
import threading
import time

import cv2
import numpy as np
from PIL import Image as PILImage

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rcl_interfaces.msg import ParameterDescriptor

from std_msgs.msg import String
from std_srvs.srv import SetBool
from geometry_msgs.msg import Twist, PoseStamped
from nav2_msgs.action import NavigateToPose

import tf2_ros
import tf2_geometry_msgs  # noqa: F401

from pinkylib import Camera

try:
    from pinky_lcd import LCD
    _LCD_AVAILABLE = True
except Exception:
    _LCD_AVAILABLE = False


# ── 상태 열거 ────────────────────────────────────────────────────────
class State:
    IDLE       = "IDLE"
    SCANNING   = "SCANNING"
    NAVIGATING = "NAVIGATING"
    DOCKING    = "DOCKING"
    PARKED     = "PARKED"
    ERROR      = "ERROR"


# ── 기본 파라미터 ────────────────────────────────────────────────────
DEFAULTS = dict(
    target_id           = 0,
    parking_dist_cm     = 15.0,
    nav_goal_dist_m     = 0.5,
    max_linear_vel      = 0.15,
    max_angular_vel     = 0.8,
    kp_rho              = 0.6,
    kp_theta            = 1.2,
    theta_thresh_deg    = 5.0,
    scan_angular_vel    = 0.2,
    camera_width        = 640,
    camera_height       = 480,
    marker_size_m       = 0.05,
    calib_path          = "",
    camera_frame        = "front_camera_link",
    robot_base_frame    = "base_link",
    nav2_timeout_sec    = 30.0,
    cam_tilt_deg        = 0.0,
)


class ParkingNode(Node):

    def __init__(self):
        super().__init__('pinky_parking_node')
        self._declare_params()
        self._load_params()

        self._state      = State.IDLE
        self._state_lock = threading.Lock()

        # ── 카메라 ───────────────────────────────────────────────────
        self.get_logger().info("📷 카메라 초기화...")
        self.camera = Camera()
        self.camera.start(width=self.p.camera_width,
                          height=self.p.camera_height)
        if self.p.calib_path:
            try:
                self.camera.set_calibration(self.p.calib_path)
                self.get_logger().info(f"✅ 캘리브레이션 로드: {self.p.calib_path}")
            except Exception as e:
                self.get_logger().error(f"캘리브레이션 로드 실패: {e}")

        # ── LCD (디버그용 카메라 영상 표시) ──────────────────────────
        self._lcd = None

        if _LCD_AVAILABLE:
            try:
                self._lcd = LCD()
                self.get_logger().info("🖥️  LCD 초기화 완료")
            except Exception as e:
                self.get_logger().warn(f"LCD 초기화 실패 (무시): {e}")
                self._lcd = None
        else:
            self.get_logger().warn("LCD 라이브러리 없음 — LCD 표시 비활성화")

        # ── TF ───────────────────────────────────────────────────────
        self.tf_buffer   = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        # ── Nav2 action client (노드 자신에 붙임 — executor 충돌 없음)
        self._nav_client = ActionClient(
            self, NavigateToPose, 'navigate_to_pose')
        self._nav_goal_handle = None
        self._nav_result      = None
        self._nav_done_event  = threading.Event()

        # ── ROS 2 인터페이스 ─────────────────────────────────────────
        self.status_pub  = self.create_publisher(String, '/docking/status', 10)
        self.cmd_vel_pub = self.create_publisher(Twist,  '/cmd_vel', 10)

        self.create_subscription(String, '/docking/cmd', self._cmd_cb, 10)
        self.create_service(SetBool, '/docking/start', self._srv_cb)
        self.create_timer(0.5, self._publish_status)

        # ── 메인 루프 스레드 ─────────────────────────────────────────
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()

        # LCD 스레드는 _stop_event 생성 후에 시작
        if self._lcd is not None:
            self._lcd_thread = threading.Thread(
                target=self._lcd_loop, daemon=True)
            self._lcd_thread.start()

        self.get_logger().info("✅ pinky_docking 노드 시작")
        self.get_logger().info("   /docking/start 서비스 또는 /docking/cmd 토픽으로 제어하세요.")

    # ── 파라미터 ─────────────────────────────────────────────────────
    def _declare_params(self):
        desc = lambda d: ParameterDescriptor(description=d)
        for k, v in DEFAULTS.items():
            self.declare_parameter(k, v, desc(k))

    def _load_params(self):
        class P:
            pass
        self.p = P()
        for k in DEFAULTS:
            setattr(self.p, k, self.get_parameter(k).value)

    # ── 상태 관리 ────────────────────────────────────────────────────
    def _set_state(self, s: str):
        with self._state_lock:
            if self._state != s:
                self.get_logger().info(f"상태: {self._state} → {s}")
            self._state = s

    def _get_state(self):
        with self._state_lock:
            return self._state

    # ── ROS 콜백 ─────────────────────────────────────────────────────
    def _cmd_cb(self, msg: String):
        cmd = msg.data.strip().lower()
        if cmd == 'start':
            self._request_start()
        elif cmd == 'stop':
            self._request_stop()

    def _srv_cb(self, req: SetBool.Request, res: SetBool.Response):
        if req.data:
            self._request_start()
            res.success = True
            res.message = "도킹 시작"
        else:
            self._request_stop()
            res.success = True
            res.message = "도킹 정지"
        return res

    def _request_start(self):
        state = self._get_state()
        if state in (State.IDLE, State.ERROR, State.PARKED):
            self._stop_event.clear()
            self._set_state(State.SCANNING)
            self.get_logger().info("🚀 주차 시퀀스 시작")
        else:
            self.get_logger().info(f"이미 실행 중입니다 ({state})")

    def _request_stop(self):
        self._stop_event.set()
        self._cancel_nav()
        self._stop_robot()
        self._set_state(State.IDLE)
        self.get_logger().info("🛑 정지 요청")

    # ── cmd_vel 헬퍼 ─────────────────────────────────────────────────
    def _publish_twist(self, linear: float, angular: float):
        msg = Twist()
        msg.linear.x  = float(linear)
        msg.angular.z = float(angular)
        self.cmd_vel_pub.publish(msg)

    def _stop_robot(self):
        self._publish_twist(0.0, 0.0)

    # ── Nav2 action 헬퍼 ─────────────────────────────────────────────
    def _send_nav_goal(self, goal_pose: PoseStamped) -> bool:
        """NavigateToPose goal 전송. 서버 대기 후 goal handle 저장."""
        if not self._nav_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error("NavigateToPose action server 없음")
            return False

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose = goal_pose

        self._nav_done_event.clear()
        self._nav_result = None

        send_future = self._nav_client.send_goal_async(
            goal_msg,
            feedback_callback=self._nav_feedback_cb)
        send_future.add_done_callback(self._nav_goal_response_cb)
        return True

    def _nav_goal_response_cb(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().warn("Nav2 goal 거부됨")
            self._nav_result = 'REJECTED'
            self._nav_done_event.set()
            return
        self._nav_goal_handle = goal_handle
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._nav_result_cb)

    def _nav_result_cb(self, future):
        self._nav_result = future.result().status  # 4=SUCCEEDED, 6=ABORTED
        self._nav_goal_handle = None
        self._nav_done_event.set()

    def _nav_feedback_cb(self, feedback):
        pass  # 필요시 진행 상황 로깅

    def _cancel_nav(self):
        if self._nav_goal_handle is not None:
            self._nav_goal_handle.cancel_goal_async()
            self._nav_goal_handle = None

    # ── 메인 루프 ────────────────────────────────────────────────────
    def _main_loop(self):
        while rclpy.ok():
            state = self._get_state()
            if state == State.SCANNING:
                self._do_scanning()
            elif state == State.NAVIGATING:
                self._do_navigating()
            elif state == State.DOCKING:
                self._do_docking()
            else:
                time.sleep(0.05)

    # ═══════════════════════════════════════════════════════════════
    # Phase 1 : SCANNING
    # ═══════════════════════════════════════════════════════════════
    def _do_scanning(self):
        self.get_logger().info("🔍 마커 탐색 중...")

        while rclpy.ok() and self._get_state() == State.SCANNING:
            if self._stop_event.is_set():
                return

            frame = self._get_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            pose_cam = self._detect_marker(frame)

            if pose_cam is None:
                self._search_rotate()
                continue

            marker_in_map = self._transform_to_map(pose_cam)
            if marker_in_map is None:
                self.get_logger().warn("TF 변환 실패 — 재시도")
                time.sleep(0.1)
                continue

            goal_pose = self._compute_parking_goal(marker_in_map)

            self.get_logger().info(
                f"✅ 마커 발견! 맵 좌표: "
                f"x={marker_in_map.pose.position.x:.2f} "
                f"y={marker_in_map.pose.position.y:.2f}")

            self._parking_goal = goal_pose
            self._set_state(State.NAVIGATING)
            return

    # ═══════════════════════════════════════════════════════════════
    # Phase 2 : NAVIGATING
    # ═══════════════════════════════════════════════════════════════
    def _do_navigating(self):
        self.get_logger().info("🗺️  Nav2 주행 시작")

        if not self._send_nav_goal(self._parking_goal):
            self._set_state(State.SCANNING)
            return

        timeout = self.p.nav2_timeout_sec
        t0 = time.time()

        while not self._nav_done_event.wait(timeout=0.1):
            if self._stop_event.is_set():
                self._cancel_nav()
                return
            if time.time() - t0 > timeout:
                self.get_logger().warn("⏱️  Nav2 타임아웃 — 재탐색")
                self._cancel_nav()
                self._set_state(State.SCANNING)
                return

        # action status 4 = SUCCEEDED
        if self._nav_result == 4:
            self.get_logger().info("✅ Nav2 목표 도착 — 정밀 도킹 시작")
            self._set_state(State.DOCKING)
        else:
            self.get_logger().warn(f"Nav2 실패 (status={self._nav_result}) — 재탐색")
            self._set_state(State.SCANNING)

    # ═══════════════════════════════════════════════════════════════
    # Phase 3 : DOCKING  (ρ/θ 제어)
    # ═══════════════════════════════════════════════════════════════
    def _do_docking(self):
        """
        ① θ 정렬 완료까지 제자리 회전 (전진 없음)
        ② θ ≤ thresh 확인 후 직진

        마커 상실 시 → 제자리 소각도 좌우 스캔 (SCANNING 전이 없음)
        SCANNING 전이는 MAX_FAIL 연속 실패 시에만.
        """
        self.get_logger().info("🎯 정밀 도킹 시작 (ρ/θ 제어)")

        fail_count   = 0
        MAX_FAIL     = 60   # 약 2초 (30Hz × 2)
        # 마커 상실 시 좌우 번갈아 소각도 회전
        search_dir   = 1    # +1 or -1
        search_speed = 0.15  # rad/s — 작게 유지

        while rclpy.ok() and self._get_state() == State.DOCKING:
            if self._stop_event.is_set():
                self._stop_robot()
                return

            frame = self._get_frame()
            if frame is None:
                time.sleep(0.03)
                continue

            pose_cam = self._detect_marker(frame)

            if pose_cam is None:
                fail_count += 1
                self.get_logger().debug(f"마커 미탐지 {fail_count}/{MAX_FAIL}")
                if fail_count >= MAX_FAIL:
                    self.get_logger().warn("마커 장시간 상실 — 재탐색")
                    self._stop_robot()
                    self._set_state(State.SCANNING)
                    return
                # 좌우 번갈아 소각도 회전으로 마커 재탐색
                if fail_count % 20 == 0:
                    search_dir *= -1   # 방향 전환
                self._publish_twist(0.0, search_dir * search_speed)
                time.sleep(0.03)
                continue

            # 마커 재발견 — 카운터 리셋, 정지
            if fail_count > 0:
                self._stop_robot()
                fail_count = 0

            x_cm, _, z_cm = pose_cam

            rho_cm    = math.sqrt(x_cm ** 2 + z_cm ** 2)
            theta_deg = math.degrees(math.atan2(x_cm, z_cm))

            self.get_logger().debug(f"ρ={rho_cm:.1f}cm  θ={theta_deg:.1f}°")

            # 완료 판정
            if rho_cm <= self.p.parking_dist_cm:
                self._stop_robot()
                self._set_state(State.PARKED)
                self.get_logger().info(f"🅿️  주차 완료! ρ={rho_cm:.1f} cm")
                return

            # ① θ 정렬 (제자리 회전 — 전진 없음)
            if abs(theta_deg) > self.p.theta_thresh_deg:
                angular = self._clamp(
                    math.radians(theta_deg) * self.p.kp_theta,
                    -self.p.max_angular_vel,
                    self.p.max_angular_vel)
                self._publish_twist(0.0, -angular)

            # ② ρ 전진 (θ 정렬 완료 후만 직진)
            else:
                linear = self._clamp(
                    (rho_cm - self.p.parking_dist_cm) / 100.0 * self.p.kp_rho,
                    0.0,
                    self.p.max_linear_vel)
                self._publish_twist(linear, 0.0)

            time.sleep(0.03)

    # ── 마커 탐지 ────────────────────────────────────────────────────
    def _detect_marker(self, frame):
        """
        pose([x,y,z] cm) 또는 None 반환.
        camera.py detect_aruco_target() 반환 순서: (pose, frame)
        """
        result = self.camera.detect_aruco_target(
            frame,
            self.p.target_id,
            marker_size=self.p.marker_size_m)

        if result is None:
            return None

        pose, _ = result
        return pose

    # ── 좌표 변환 ────────────────────────────────────────────────────
    def _transform_to_map(self, pose_cam):
        x_cam, y_cam, z_cam = pose_cam

        tilt    = math.radians(self.p.cam_tilt_deg)
        z_horiz = z_cam * math.cos(tilt) + y_cam * math.sin(tilt)
        y_vert  = z_cam * math.sin(tilt) - y_cam * math.cos(tilt)

        ps = PoseStamped()
        ps.header.stamp    = self.get_clock().now().to_msg()
        ps.header.frame_id = self.p.camera_frame
        ps.pose.position.x =  z_horiz / 100.0
        ps.pose.position.y = -x_cam   / 100.0
        ps.pose.position.z = -y_vert  / 100.0
        ps.pose.orientation.w = 1.0

        try:
            return self.tf_buffer.transform(
                ps, 'map',
                timeout=rclpy.duration.Duration(seconds=0.3))
        except Exception as e:
            self.get_logger().warn(f"TF 변환 실패: {e}")
            return None

    def _compute_parking_goal(self, marker_in_map: PoseStamped) -> PoseStamped:
        try:
            tf_robot = self.tf_buffer.lookup_transform(
                'map', self.p.robot_base_frame,
                rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=0.5))
        except Exception:
            tf_robot = None

        mx = marker_in_map.pose.position.x
        my = marker_in_map.pose.position.y

        if tf_robot is not None:
            rx = tf_robot.transform.translation.x
            ry = tf_robot.transform.translation.y
            dx, dy = mx - rx, my - ry
            dist = math.sqrt(dx**2 + dy**2)
            if dist > 0.01:
                dx /= dist
                dy /= dist
            gx  = mx - dx * self.p.nav_goal_dist_m
            gy  = my - dy * self.p.nav_goal_dist_m
            yaw = math.atan2(dy, dx)
        else:
            gx  = mx
            gy  = my - self.p.nav_goal_dist_m
            yaw = 0.0

        goal = PoseStamped()
        goal.header.stamp    = self.get_clock().now().to_msg()
        goal.header.frame_id = 'map'
        goal.pose.position.x = gx
        goal.pose.position.y = gy
        goal.pose.position.z = 0.0
        goal.pose.orientation.z = math.sin(yaw / 2.0)
        goal.pose.orientation.w = math.cos(yaw / 2.0)

        self.get_logger().info(
            f"🅿️  주차 목표: map({gx:.2f}, {gy:.2f})  yaw={math.degrees(yaw):.1f}°")
        return goal

    # ── 유틸 ─────────────────────────────────────────────────────────
    def _search_rotate(self):
        self._publish_twist(0.0, self.p.scan_angular_vel)
        time.sleep(0.08)
        self._stop_robot()

    def _get_frame(self):
        try:
            return self.camera.get_frame()
        except Exception as e:
            self.get_logger().error(f"카메라 오류: {e}")
            return None

    # ── LCD 루프 (별도 스레드, 약 10 Hz) ─────────────────────────────
    def _lcd_loop(self):
        """카메라에서 직접 프레임을 읽어 LCD에 표시. 상태 오버레이 포함."""
        INTERVAL = 0.1   # 10 Hz
        while not self._stop_event.is_set():
            try:
                frame = self.camera.get_frame()
                if frame is not None and not self._stop_event.is_set():
                    self._frame_to_lcd(frame)
            except Exception:
                pass
            # sleep을 짧게 나눠서 stop_event에 빠르게 반응
            for _ in range(10):
                if self._stop_event.is_set():
                    return
                time.sleep(0.01)

    def _frame_to_lcd(self, frame):
        """OpenCV BGR frame → 상태 오버레이 → PIL Image → LCD."""
        try:
            display = frame.copy()   # 원본 프레임 보호
            state = self._get_state()

            color_map = {
                State.IDLE:       (128, 128, 128),
                State.SCANNING:   (0,   200, 255),
                State.NAVIGATING: (0,   200,   0),
                State.DOCKING:    (255, 140,   0),
                State.PARKED:     (0,   255,   0),
                State.ERROR:      (255,   0,   0),
            }
            color = color_map.get(state, (255, 255, 255))
            cv2.putText(display, state,
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, color, 2, cv2.LINE_AA)

            # BGR → RGB → PIL → LCD
            rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
            pil_img = PILImage.fromarray(rgb)
            self._lcd.img_show(pil_img)
        except Exception:
            pass

    @staticmethod
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    def _publish_status(self):
        msg = String()
        msg.data = self._get_state()
        self.status_pub.publish(msg)

    # ── 소멸자 ───────────────────────────────────────────────────────
    def destroy_node(self):
        self.get_logger().info("노드 종료 중...")
        self._stop_event.set()
        self._cancel_nav()
        self._stop_robot()
        # 카메라를 먼저 닫아서 LCD 루프의 get_frame() 블로킹 해제
        try:
            self.camera.close()
        except Exception:
            pass
        # LCD 스레드 종료 대기 (최대 1초)
        if self._lcd is not None:
            if hasattr(self, '_lcd_thread'):
                self._lcd_thread.join(timeout=1.0)
            try:
                self._lcd.clear()
                self._lcd.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = ParkingNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()