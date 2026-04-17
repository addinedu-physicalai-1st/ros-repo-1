"""
follow_function_node.py

동행 Sub FSM 기능 노드 + YOLO 기반 사람 추적 통합 버전.

HQ 명령에 반응하여 실제 이동·동행 동작을 수행하고,
완료 시 /robot/event에 이벤트를 퍼블리시한다.

FollowStart / RestartFollowStart 명령을 받으면 YOLO + PD 제어로
주인을 추적하며 /cmd_vel 을 직접 발행한다.

처리 명령 (state=FOLLOW 인 경우에만 반응):
  FollowRequest      → 요청자 위치로 이동 (Nav2), 도달 시 ArrivedAtRequester 퍼블리시
  RetryFollowRequest → 새 위치로 재이동 (Nav2), 도달 시 ArrivedAtRequester 퍼블리시
  FollowStart        → YOLO 추적 동행 시작
  GoToTable          → 테이블 위치로 이동 (Nav2), 도달 시 ArrivedAtTable 퍼블리시
  RestartFollowStart → 동행 재시작
  FollowEnd          → 동행 종료, 이동 중지

주의:
  - Nav2 이동 중 (_is_following=False) 에는 /cmd_vel 을 발행하지 않는다.
    Nav2 가 점유 중이기 때문. 추적 중 (_is_following=True) 에만 발행.
  - NearTableFor1Min 이벤트는 FollowFSM(rost_state_machine)이 퍼블리시함.
    이 노드는 1분 타이머를 관리하지 않는다.
"""

import os
import sys
import math
import time
import threading

import numpy as np
import cv2
from PIL import Image

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped, Twist
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from rostaurant_state_machine.msg import RobotCommand
from rostaurant_function.core.navigation_client import NavigationClient
from rostaurant_function.core.event_publisher import EventPublisher

# -------------------------------------------------------------------- #
# 옵셔널 의존성 (없어도 FSM 동작은 유지되도록 try/except)                     #
# -------------------------------------------------------------------- #
try:
    from ultralytics import YOLO
    _YOLO_AVAILABLE = True
except ImportError:
    _YOLO_AVAILABLE = False
    print('⚠️ ultralytics 로드 실패 — YOLO 추적 기능 비활성화')

try:
    from picamera2 import Picamera2
    _PICAMERA2_AVAILABLE = True
except ImportError:
    _PICAMERA2_AVAILABLE = False
    print('⚠️ picamera2 로드 실패 — OpenCV 폴백 사용')

try:
    sys.path.append(os.path.expanduser('~') + '/catkin_ws/src/pinky_follower/src')
    from pinkylib import LED
    from pinky_lcd import LCD
    _HW_AVAILABLE = True
except ImportError:
    _HW_AVAILABLE = False
    print('⚠️ 하드웨어 라이브러리(LED/LCD) 로드 실패')


class FollowFunctionNode(Node):
    """동행 Sub FSM 기능 노드 (Nav2 이동 + YOLO 추적 통합)"""

    COLORS = {
        'RED': (255, 0, 0), 'GREEN': (0, 255, 0), 'BLUE': (0, 0, 255),
        'ORANGE': (255, 127, 0), 'YELLOW': (255, 255, 0),
        'VIOLET': (148, 0, 211), 'BLACK': (0, 0, 0), 'WHITE': (255, 255, 255),
    }

    def __init__(self):
        super().__init__('follow_function_node')

        # ---------------------------------------------------------------- #
        # 파라미터                                                           #
        # ---------------------------------------------------------------- #
        self.declare_parameter('use_nav2', False)
        self.declare_parameter('simulated_nav_time', 3.0)
        self.declare_parameter('follow_table_distance_threshold', 1.5)

        # YOLO 추적 파라미터
        self.declare_parameter('enable_yolo_follow', True)
        self.declare_parameter('yolo_model_path', 'yolov8n.pt')
        self.declare_parameter('camera_index', 0)
        self.declare_parameter('follow_kp', 0.009)
        self.declare_parameter('follow_kd', 0.006)
        self.declare_parameter('follow_max_speed', 0.25)
        self.declare_parameter('follow_lost_threshold', 150)
        self.declare_parameter('follow_rate_hz', 30.0)
        self.declare_parameter('test_follow_mode', False)

        # ---------------------------------------------------------------- #
        # 내부 상태 (FSM)                                                    #
        # ---------------------------------------------------------------- #
        self._current_state: str = ''
        self._session_id: str = ''
        self._requester_pose: PoseStamped = None
        self._table_pose: PoseStamped = None
        self._is_following: bool = False

        # ---------------------------------------------------------------- #
        # 내부 상태 (추적 제어)                                                #
        # ---------------------------------------------------------------- #
        self._target_id = None
        self._center_x = 160
        self._kp = self.get_parameter('follow_kp').value
        self._kd = self.get_parameter('follow_kd').value
        self._max_speed = self.get_parameter('follow_max_speed').value
        self._prev_error = 0.0
        self._emergency_stop = False
        self._lost_count = 0
        self._lost_threshold = self.get_parameter('follow_lost_threshold').value
        self._track_state = 'WAITING'  # WAITING / FOLLOWING / ARRIVED / EMERGENCY
        self._rainbow_offset = 0
        self._last_lcd_update = 0.0

        # 카메라 프레임 (스레드 공유)
        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._camera_stop_flag = False

        # ---------------------------------------------------------------- #
        # 공통 모듈 (Nav2 / 이벤트)                                           #
        # ---------------------------------------------------------------- #
        use_nav2 = self.get_parameter('use_nav2').value
        sim_time = self.get_parameter('simulated_nav_time').value
        self._nav = NavigationClient(self, use_nav2=use_nav2, simulated_nav_time=sim_time)
        self._event_pub = EventPublisher(self)

        # ---------------------------------------------------------------- #
        # 퍼블리셔 / 서브스크라이버                                             #
        # ---------------------------------------------------------------- #
        self._cmd_vel_pub = self.create_publisher(Twist, '/cmd_vel', 10)

        self._state_sub = self.create_subscription(
            String, '/robot/state', self._on_state, 10
        )
        self._cmd_sub = self.create_subscription(
            RobotCommand, '/hq/command', self._on_command, 10
        )
        self._lidar_sub = self.create_subscription(
            LaserScan, '/scan', self._on_lidar, 10
        )

        # ---------------------------------------------------------------- #
        # YOLO / 하드웨어 초기화                                              #
        # ---------------------------------------------------------------- #
        self._enable_yolo = self.get_parameter('enable_yolo_follow').value and _YOLO_AVAILABLE
        self._yolo_model = None
        self._leds = None
        self._lcd = None

        if self._enable_yolo:
            try:
                model_path = self.get_parameter('yolo_model_path').value
                self._yolo_model = YOLO(model_path)
                self.get_logger().info(f'[FollowFunc] YOLO 모델 로드 완료: {model_path}')
            except Exception as e:
                self.get_logger().error(f'[FollowFunc] YOLO 모델 로드 실패: {e}')
                self._enable_yolo = False

        self.get_logger().info(
            f'[FollowFunc] 하드웨어 라이브러리(LED/LCD): '
            f'{"로드 성공" if _HW_AVAILABLE else "로드 실패 — LED/LCD 비활성화"}'
        )
        if _HW_AVAILABLE:
            try:
                self._leds = LED()
                self._lcd = LCD()
                self.get_logger().info('[FollowFunc] LED/LCD 초기화 완료')
            except Exception as e:
                self.get_logger().warn(f'[FollowFunc] 하드웨어 초기화 실패: {e}')
                self._leds = None
                self._lcd = None

        # ---------------------------------------------------------------- #
        # 카메라 스레드 & 추적 타이머                                           #
        # ---------------------------------------------------------------- #
        if self._enable_yolo:
            self._camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
            self._camera_thread.start()

            # 타이머 대신 tight loop 스레드 — YOLO 속도에 자동으로 맞춰짐 (원본 코드 방식)
            self._track_thread = threading.Thread(target=self._track_loop, daemon=True)
            self._track_thread.start()

        # 테스트 모드: FSM 없이 바로 following 시작
        if self.get_parameter('test_follow_mode').value:
            self._current_state = 'FOLLOW'
            self._is_following = True
            self.get_logger().info('[FollowFunc] ★ test_follow_mode ON — 즉시 following 시작')

        self.get_logger().info('follow_function_node 시작.')

    # ------------------------------------------------------------------ #
    # 상태 변경 감지                                                         #
    # ------------------------------------------------------------------ #

    def _on_state(self, msg: String) -> None:
        new_state = msg.data
        if new_state == self._current_state:
            return

        old_state = self._current_state
        self._current_state = new_state
        self.get_logger().info(f'[FollowFunc] 상태 변경: {old_state} → {new_state}')
        self._on_state_enter(new_state)

    def _on_state_enter(self, state: str) -> None:
        if state == 'FOLLOW':
            self.get_logger().info('[FollowFunc] FOLLOW 태스크 진입. HQ 명령 대기...')
            self._reset_session()
        elif state not in ('FOLLOW',):
            if self._nav.is_navigating() or self._is_following:
                self.get_logger().info('[FollowFunc] 태스크 종료. 이동 중지 및 세션 초기화.')
                self._stop_all()

    # ------------------------------------------------------------------ #
    # HQ 명령 처리                                                          #
    # ------------------------------------------------------------------ #

    def _on_command(self, msg: RobotCommand) -> None:
        if self._current_state != 'FOLLOW':
            return

        cmd = msg.command
        self._session_id = msg.session_id
        self.get_logger().info(f'[FollowFunc] 명령 수신: {cmd}')

        if cmd == 'FollowRequest':
            self._requester_pose = self._make_pose(msg.x, msg.y, msg.theta)
            self.get_logger().info(
                f'[FollowFunc] FollowRequest — 요청자 위치로 이동: '
                f'({msg.x:.2f}, {msg.y:.2f})'
            )
            self._nav.send_goal(self._requester_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'RetryFollowRequest':
            self._requester_pose = self._make_pose(msg.x, msg.y, msg.theta)
            self.get_logger().info(
                f'[FollowFunc] RetryFollowRequest — 새 위치로 재이동: '
                f'({msg.x:.2f}, {msg.y:.2f})'
            )
            self._nav.send_goal(self._requester_pose, on_arrived=self._on_arrived_requester)

        elif cmd == 'FollowStart':
            self.get_logger().info('[FollowFunc] FollowStart — 동행 시작 (YOLO 추적 활성화).')
            self._start_following()

        elif cmd == 'GoToTable':
            # Nav2 이동으로 전환 — YOLO 추적은 반드시 꺼야 /cmd_vel 경합 방지
            self._table_pose = self._make_pose(msg.x, msg.y, msg.theta)
            self._stop_following()
            self.get_logger().info(
                f'[FollowFunc] GoToTable — 테이블로 이동: '
                f'({msg.x:.2f}, {msg.y:.2f})'
            )
            self._nav.send_goal(self._table_pose, on_arrived=self._on_arrived_table)

        elif cmd == 'RestartFollowStart':
            self.get_logger().info('[FollowFunc] RestartFollowStart — 동행 재시작.')
            self._start_following()

        elif cmd == 'FollowEnd':
            self.get_logger().info('[FollowFunc] FollowEnd — 동행 종료.')
            self._stop_all()

    # ------------------------------------------------------------------ #
    # 내비게이션 콜백                                                        #
    # ------------------------------------------------------------------ #

    def _on_arrived_requester(self) -> None:
        self.get_logger().info('[FollowFunc] 요청자 위치 도착!')
        self._event_pub.publish_event('ArrivedAtRequester', self._session_id)

    def _on_arrived_table(self) -> None:
        self.get_logger().info('[FollowFunc] 테이블 도착!')
        self._event_pub.publish_event('ArrivedAtTable', self._session_id)

    # ------------------------------------------------------------------ #
    # LiDAR (긴급 정지용)                                                    #
    # ------------------------------------------------------------------ #

    def _on_lidar(self, data: LaserScan) -> None:
        # 이동 중(_is_following=True)일 때만 긴급 정지 판정
        if not self._is_following:
            self._emergency_stop = False
            return
        ranges = [r for r in (list(data.ranges[:40]) + list(data.ranges[-40:]))
                  if 0.05 < r < 10.0 and not math.isinf(r)]
        self._emergency_stop = bool(ranges) and min(ranges) < 0.10

    # ------------------------------------------------------------------ #
    # 카메라 스레드                                                           #
    # ------------------------------------------------------------------ #

    def _camera_loop(self) -> None:
        """카메라 캡처 루프. picamera2(RPi CSI) → OpenCV 순으로 시도."""
        if _PICAMERA2_AVAILABLE:
            self._camera_loop_picamera2()
        else:
            self._camera_loop_opencv()

    def _camera_loop_picamera2(self) -> None:
        """picamera2를 사용한 RPi CSI 카메라 루프."""
        try:
            picam2 = Picamera2()
            # XRGB8888: picamera2에서 가장 안정적으로 컬러 출력되는 포맷
            # 메모리 레이아웃: [B, G, R, X] per pixel (little-endian)
            cfg = picam2.create_preview_configuration(
                main={'size': (320, 240), 'format': 'XRGB8888'}
            )
            picam2.configure(cfg)
            picam2.start()

            # 첫 프레임으로 실제 shape/채널 진단
            test = picam2.capture_array()
            self.get_logger().info(
                f'[FollowFunc] picamera2 시작 완료 — shape={test.shape}, dtype={test.dtype}'
            )

            while not self._camera_stop_flag:
                raw = picam2.capture_array()   # shape=(240,320,4): B,G,R,X
                frame = raw[:, :, :3]          # B,G,R → OpenCV BGR
                resized = cv2.resize(cv2.flip(frame, -1), (320, 240))
                with self._frame_lock:
                    self._latest_frame = resized

            picam2.stop()
            picam2.close()

        except Exception as e:
            self.get_logger().error(f'[FollowFunc] picamera2 오류: {e}')
            # picamera2 실패 시 OpenCV 폴백
            self._camera_loop_opencv()

    def _camera_loop_opencv(self) -> None:
        """OpenCV VideoCapture 폴백 (USB 카메라 등)."""
        cam_idx = self.get_parameter('camera_index').value
        cap = cv2.VideoCapture(cam_idx)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

        if not cap.isOpened():
            self.get_logger().error(f'[FollowFunc] 카메라 오픈 실패 (index={cam_idx})')
            return

        self.get_logger().info(f'[FollowFunc] OpenCV 카메라 오픈 성공 (index={cam_idx})')
        fail_count = 0
        while not self._camera_stop_flag:
            ret, frame = cap.read()
            if ret and frame is not None:
                resized = cv2.resize(cv2.flip(frame, -1), (320, 240))
                with self._frame_lock:
                    self._latest_frame = resized
                fail_count = 0
            else:
                fail_count += 1
                if fail_count % 100 == 1:
                    self.get_logger().warn(
                        f'[FollowFunc] 카메라 프레임 수신 실패 ({fail_count}회)'
                    )
                time.sleep(0.01)

        cap.release()

    # ------------------------------------------------------------------ #
    # YOLO 추적 틱 (타이머 콜백)                                              #
    # ------------------------------------------------------------------ #

    def _track_loop(self) -> None:
        """YOLO 추적 tight loop — 추론 속도에 자동으로 맞춰짐."""
        while not self._camera_stop_flag:
            self._track_tick()

    def _track_tick(self) -> None:
        """주기적으로 호출. 항상 YOLO 추론 + LCD 표시.
        _is_following=True 일 때만 cmd_vel 발행."""
        with self._frame_lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()

        if frame is None:
            self._no_frame_count = getattr(self, '_no_frame_count', 0) + 1
            if self._no_frame_count % 90 == 1:  # ~3초마다 로그
                self.get_logger().warn(f'[FollowFunc] 카메라 프레임 없음 ({self._no_frame_count}회)')
            return
        self._no_frame_count = 0

        # ── 항상 YOLO 실행 (LCD 박스 표시용) ──────────────────────────────── #
        results = self._yolo_model.track(
            source=frame, persist=True, tracker='bytetrack.yaml',
            classes=0, verbose=False, imgsz=160,
        )
        r = results[0]

        msg = Twist()
        self._track_state = 'WAITING'
        status_text = 'WAITING TARGET'
        text_color = self.COLORS['BLUE']
        found_target = False
        best_box = None

        if r.boxes is not None and r.boxes.id is not None:
            for box in r.boxes:
                idx = int(box.id[0])

                # 타겟 미등록 + 추적 중 → 화면 중앙 근처 사람 자동 등록
                if self._target_id is None and (self._is_following or self._current_state == 'FOLLOW'):
                    x1, _, x2, _ = box.xyxy[0].cpu().numpy()
                    cx = (x1 + x2) / 2
                    if 100 < cx < 220:
                        self._target_id = idx
                        self.get_logger().info(f'[FollowFunc] 타겟 등록 ID={idx}')

                if idx == self._target_id:
                    best_box = box
                    found_target = True
                    self._lost_count = 0
                    break

            # 추적 중이 아닐 때 감지된 사람 전부 박스 표시
            if not self._is_following:
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)),
                                  (100, 100, 255), 1)
                status_text = 'STANDBY'
                text_color = self.COLORS['BLUE']

        if best_box is not None:
            x1, y1, x2, y2 = best_box.xyxy[0].cpu().numpy()
            cx, h = (x1 + x2) / 2, y2 - y1

            error = self._center_x - cx
            angular = (error * self._kp) + (error - self._prev_error) * self._kd
            self._prev_error = error

            # angular은 항상 적용 (ARRIVED에서도 방향 보정 유지 — 원본 동일)
            if self._is_following:
                msg.angular.z = float(max(-3.0, min(3.0, angular)))

            if h < 210:
                self._track_state = 'FOLLOWING'
                status_text = f'FOLLOWING ID:{self._target_id}'
                text_color = self.COLORS['WHITE']
                if self._is_following:
                    msg.linear.x = self._max_speed if h < 160 else self._max_speed * 0.4
            else:
                self._track_state = 'ARRIVED'
                status_text = 'ARRIVED!'
                text_color = self.COLORS['GREEN']
                # linear.x = 0 (Twist 기본값), angular.z는 위에서 이미 설정

            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)

        # 타겟 놓침
        if not found_target and self._target_id is not None:
            self._lost_count += 1
            status_text = f'LOST.. {self._lost_threshold - self._lost_count}'
            text_color = self.COLORS['ORANGE']
            if self._lost_count > self._lost_threshold:
                self.get_logger().warn('[FollowFunc] 타겟 놓침 — 재탐색 모드')
                self._target_id = None
                self._lost_count = 0
                self._prev_error = 0.0

        # 긴급 정지
        if self._emergency_stop:
            msg.linear.x, msg.angular.z = 0.0, 0.0
            self._track_state = 'EMERGENCY'
            status_text = '!!! EMERGENCY !!!'
            text_color = self.COLORS['RED']

        # cmd_vel: 추적 중일 때만 발행
        if self._is_following:
            self._cmd_vel_pub.publish(msg)

        # LED / LCD: 항상 업데이트
        if self._leds is not None:
            self._update_leds()

        if self._lcd is not None and (time.time() - self._last_lcd_update > 0.05):
            overlay = self._draw_overlay(frame, status_text,
                                         (text_color[2], text_color[1], text_color[0]))
            img_pil = Image.fromarray(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))
            try:
                self._lcd.img_show(img_pil)
            except Exception:
                pass
            self._last_lcd_update = time.time()

    # ------------------------------------------------------------------ #
    # LED / LCD 유틸                                                       #
    # ------------------------------------------------------------------ #

    def _update_leds(self) -> None:
        if self._emergency_stop:
            self._leds.fill(self.COLORS['RED'])
        elif self._track_state == 'FOLLOWING':
            rainbow = [self.COLORS['RED'], self.COLORS['ORANGE'], self.COLORS['YELLOW'],
                       self.COLORS['GREEN'], self.COLORS['BLUE'], self.COLORS['VIOLET']]
            for i in range(8):
                self._leds.set_pixel(i, rainbow[(i + self._rainbow_offset) % len(rainbow)])
            self._rainbow_offset += 1
        elif self._track_state == 'ARRIVED':
            self._leds.fill(self.COLORS['GREEN'])
        else:
            self._leds.fill(self.COLORS['BLUE'])
        self._leds.show()

    def _draw_overlay(self, frame, text, color):
        cv2.rectangle(frame, (0, 200), (320, 240), (0, 0, 0), -1)
        cv2.putText(frame, text, (10, 230), cv2.FONT_HERSHEY_DUPLEX,
                    0.7, color, 2, cv2.LINE_AA)
        return frame

    # ------------------------------------------------------------------ #
    # 세션 / 추적 제어                                                        #
    # ------------------------------------------------------------------ #

    def _start_following(self) -> None:
        """YOLO 추적 ON"""
        if not self._enable_yolo:
            self.get_logger().warn('[FollowFunc] YOLO 비활성화 상태 — 추적 시작 불가')
            return
        self._is_following = True
        self._target_id = None
        self._lost_count = 0
        self._prev_error = 0.0

    def _stop_following(self) -> None:
        """YOLO 추적 OFF — cmd_vel 정지 1회 발행"""
        self._is_following = False
        self._target_id = None
        self._prev_error = 0.0
        self._cmd_vel_pub.publish(Twist())

    def _stop_all(self) -> None:
        """Nav2 취소 + 추적 중지"""
        self._nav.cancel_goal()
        self._stop_following()

    def _reset_session(self) -> None:
        self._stop_all()
        self._session_id = ''
        self._requester_pose = None
        self._table_pose = None

    @staticmethod
    def _make_pose(x: float, y: float, theta: float) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.pose.position.x = x
        pose.pose.position.y = y
        pose.pose.orientation.z = math.sin(theta / 2.0)
        pose.pose.orientation.w = math.cos(theta / 2.0)
        return pose

    # ------------------------------------------------------------------ #
    # 종료 정리                                                              #
    # ------------------------------------------------------------------ #

    def shutdown(self) -> None:
        self.get_logger().info('[FollowFunc] shutdown 정리 시작')
        self._camera_stop_flag = True
        try:
            self._cmd_vel_pub.publish(Twist())
        except Exception:
            pass
        if self._leds is not None:
            try:
                self._leds.fill((0, 0, 0))
                self._leds.show()
                self._leds.close()
            except Exception:
                pass
        if self._lcd is not None:
            try:
                self._lcd.close()
            except Exception:
                pass


def main(args=None):
    rclpy.init(args=args)
    node = FollowFunctionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('follow_function_node 종료')
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()