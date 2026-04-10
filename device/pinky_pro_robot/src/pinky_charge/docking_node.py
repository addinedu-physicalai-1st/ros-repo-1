import sys
import os
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from action_msgs.msg import GoalStatusArray
import cv2
import numpy as np

# 1. 핑키 라이브러리 경로 추가
if '/home/pinky' not in sys.path:
    sys.path.append('/home/pinky')

try:
    from pinkylib import Camera, Battery
except ImportError:
    print("에러: pinkylib을 찾을 수 없습니다.")
    sys.exit(1)

class DockingNode(Node):
    def __init__(self):
        super().__init__('docking_node')
        
        self.get_logger().info('📸 하드웨어 및 캘리브레이션 초기화 중...')
        try:
            self.cam = Camera()
            self.cam.start()
            self.battery = Battery() 
            
            # 실제 절대 경로
            calib_file = "/home/pinky/pinky_pro/src/Rostaurant/pinky_docking/pinky_docking/camera_calibration.npz"
            
            if os.path.exists(calib_file):
                with np.load(calib_file) as data:
                    self.mtx = data['camera_matrix']
                    self.dist = data['distortion_coefficients']
                self.get_logger().info('✅ 캘리브레이션 데이터 로드 완료!')
            else:
                self.get_logger().error(f'❌ 파일을 찾을 수 없습니다: {calib_file}')
                sys.exit(1)
        except Exception as e:
            self.get_logger().error(f'❌ 초기화 실패: {e}')
            sys.exit(1)
        
        # --- ROS 설정 ---
        self.publisher = self.create_publisher(Twist, '/cmd_vel', 10)
        self.nav_status_sub = self.create_subscription(
            GoalStatusArray,
            '/navigate_to_pose/_action/status',
            self.nav_status_callback,
            10)
            
        self.timer = self.create_timer(0.1, self.main_loop)
        self.report_timer = self.create_timer(10.0, self.status_report_callback)
        
        # --- 설정값 ---
        self.target_id = 0 
        self.aruco_dict_type = cv2.aruco.DICT_5X5_250 
        self.marker_real_size = 0.15      # 150mm
        self.docking_threshold = 85.0     # 실제 접촉 시의 Z값 (실험 후 미세조정)
        
        # --- 상태 및 타이머 변수 ---
        self.state = "IDLE"
        self.battery_level = 100.0        
        self.is_nav_finished = False      
        self.last_marker_seen_time = self.get_clock().now() 
        
        self.get_logger().info('🚀 [자율 도킹 시스템] 가동! 배터리와 네비 신호를 감시합니다.')

    def nav_status_callback(self, msg):
        """내비게이션 도착 감지"""
        if not self.is_nav_finished and msg.status_list:
            last_status = msg.status_list[-1].status
            if last_status == 3: # SUCCEEDED
                self.is_nav_finished = True
                self.get_logger().info('🏁 [바톤 터치] 목표 지점 도착 완료!')

    def status_report_callback(self):
        """10초마다 상태 보고"""
        self.get_logger().info(f'📊 배터리: {self.battery_level:.1f}% | 네비도착: {self.is_nav_finished} | 상태: {self.state}')

    def main_loop(self):
        """메인 제어 로직"""
        cmd_msg = Twist()
        
        try:
            self.battery_level = self.battery.battery_percentage()
        except:
            pass 

        # [실전 운영 조건] 배터리 20% 이하 AND 네비게이션 완료 시에만 동작
        if self.battery_level <= 20.0 and self.is_nav_finished and self.state == "IDLE":
            self.state = "APPROACH"
            self.get_logger().warn(f'🚨 배터리 부족({self.battery_level:.1f}%)! 자동 도킹을 시작합니다.')

        if self.state in ["APPROACH", "DOCKING"]:
            self.execute_docking_with_recovery(cmd_msg)
        
        elif self.state == "CHARGING":
            if self.battery_level >= 100.0:
                self.state = "IDLE"
                self.is_nav_finished = False 
                self.get_logger().info('✅ 충전 완료! 대기 상태로 복귀합니다.')
            
        self.publisher.publish(cmd_msg)

    def execute_docking_with_recovery(self, cmd_msg):
        """마커 추적 및 접근 로직"""
        frame = self.cam.get_frame()
        if frame is None: return

        _, pose = self.cam.target_pose_estimation(
            frame, self.aruco_dict_type, self.mtx, self.dist, 
            self.target_id, self.marker_real_size
        )
        
        now = self.get_clock().now()

        if pose is not None:
            self.last_marker_seen_time = now
            x_mm = pose[0] * 10
            z_mm = pose[2] * 10
            
            self.get_logger().info(f'🔎 마커 감지! 거리(Z): {z_mm:.1f}mm', throttle_duration_sec=1.0)
            
            if z_mm > 500.0:
                self.state = "APPROACH"
                cmd_msg.linear.x = 0.05
                cmd_msg.angular.z = -(x_mm / 250.0)
            elif self.docking_threshold < z_mm <= 500.0:
                self.state = "DOCKING"
                cmd_msg.linear.x = 0.02 
                cmd_msg.angular.z = -(x_mm / 200.0)
            else:
                self.state = "CHARGING"
                cmd_msg.linear.x = 0.0
                cmd_msg.angular.z = 0.0
                self.get_logger().info(f'🎯 [도킹 성공] 충전 시작 (최종 거리: {z_mm:.1f}mm)')
        
        else:
            # 회복 로직: 마커를 놓쳤을 때
            time_diff = (now - self.last_marker_seen_time).nanoseconds / 1e9
            if time_diff < 3.0:
                cmd_msg.linear.x = 0.0
            elif time_diff < 30.0:
                self.get_logger().error("🔄 마커 재탐색 중: 천천히 회전")
                cmd_msg.angular.z = 0.1 
            else:
                self.state = "IDLE"
                self.get_logger().error("❌ 도킹 실패: 마커를 찾을 수 없습니다.")

    def destroy_node(self):
        self.get_logger().info('👋 도킹 노드를 종료합니다.')
        self.cam.close()
        self.battery.close() 
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = DockingNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
