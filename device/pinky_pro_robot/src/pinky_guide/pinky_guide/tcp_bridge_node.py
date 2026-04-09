#!/usr/bin/env python3
"""
tcp_bridge_node.py
──────────────────
관제서버와 TCP로 JSON(NDJSON) 메시지를 주고받는 노드.

프레이밍: 한 줄에 UTF-8 JSON 객체 하나 + 개행(\\n).

관제서버 → 로봇 (명령):
  {"type":"guide_command","robot_id":1,"cmd_type":1,"dest_id":10}
  선택 키: "dest_name": "table_3"

로봇 → 관제서버 (안내 결과):
  {"type":"guide_result","robot_id":1,"cmd_type":1,"status":0,"dest_name":"table_3","message":""}

로봇 → 관제서버 (주기 상태):
  {"type":"robot_status","robot_id":1,"state":0,"battery":87.5,"pose_x":1.0,"pose_y":2.0,"current_task":""}

cmd_type / status / state 는 GuideCommand.msg, GuideResult.msg, RobotStatus.msg 의 상수와 동일한 정수.
"""

import json
import socket
import threading
import time
import rclpy
from rclpy.node import Node
from pinky_guide.msg import GuideCommand, GuideResult, RobotStatus

MSG_GUIDE_COMMAND = "guide_command"
MSG_GUIDE_RESULT = "guide_result"
MSG_ROBOT_STATUS = "robot_status"


class TcpBridgeNode(Node):
    def __init__(self):
        super().__init__('tcp_bridge_node')

        self.declare_parameter('robot_id', 1)
        self.declare_parameter('server_host', '192.168.1.100')
        self.declare_parameter('server_port', 9000)
        self.declare_parameter('reconnect_interval', 3.0)

        self.robot_id = self.get_parameter('robot_id').value
        self.server_host = self.get_parameter('server_host').value
        self.server_port = self.get_parameter('server_port').value
        self.reconnect_sec = self.get_parameter('reconnect_interval').value

        self.cmd_pub = self.create_publisher(
            GuideCommand, 'guide_command', 10)

        self.result_sub = self.create_subscription(
            GuideResult, 'guide_result', self._on_result, 10)

        self.status_sub = self.create_subscription(
            RobotStatus, 'robot_status', self._on_status, 10)

        self._sock = None
        self._lock = threading.Lock()

        self._connect_thread = threading.Thread(
            target=self._connect_loop, daemon=True)
        self._connect_thread.start()

        self.get_logger().info(
            f'tcp_bridge_node 시작 (JSON/NDJSON) — robot_id={self.robot_id} '
            f'server={self.server_host}:{self.server_port}')

    def _connect_loop(self):
        while rclpy.ok():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.server_host, self.server_port))
                sock.settimeout(None)
                with self._lock:
                    self._sock = sock
                self.get_logger().info('관제서버 TCP 연결 성공')
                self._recv_loop(sock)
            except Exception as e:
                self.get_logger().warn(
                    f'TCP 연결 실패: {e} — {self.reconnect_sec}초 후 재시도')
            finally:
                with self._lock:
                    self._sock = None
            time.sleep(self.reconnect_sec)

    def _recv_loop(self, sock):
        buf = b''
        while rclpy.ok():
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    self.get_logger().warn('서버 연결 종료')
                    break
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    text = line.decode('utf-8', errors='replace').strip()
                    if not text:
                        continue
                    try:
                        obj = json.loads(text)
                    except json.JSONDecodeError as e:
                        self.get_logger().warning(
                            f'JSON 파싱 실패 (무시): {e} — {text[:120]!r}')
                        continue
                    if not isinstance(obj, dict):
                        self.get_logger().warning('JSON 루트가 객체가 아님 — 무시')
                        continue
                    self._handle_inbound_json(obj)
            except Exception as e:
                self.get_logger().error(f'수신 오류: {e}')
                break

    def _handle_inbound_json(self, obj):
        if obj.get('type') != MSG_GUIDE_COMMAND:
            return
        try:
            rid = int(obj['robot_id'])
            cmd_type = int(obj['cmd_type'])
            dest_id = int(obj['dest_id'])
        except (KeyError, TypeError, ValueError) as e:
            self.get_logger().warning(f'guide_command 필드 누락/타입 오류: {e}')
            return
        if rid != self.robot_id:
            return
        if dest_id < 0 or dest_id > 0xFFFF:
            self.get_logger().warning(f'dest_id 범위 오류: {dest_id}')
            return
        msg = GuideCommand()
        msg.cmd_type = cmd_type
        msg.robot_id = rid
        msg.dest_id = dest_id
        dn = obj.get('dest_name')
        msg.dest_name = str(dn) if dn is not None else ''
        self.cmd_pub.publish(msg)
        self.get_logger().info(
            f'명령 수신 — cmd={cmd_type} dest_id={dest_id} dest_name={msg.dest_name!r}')

    def _on_result(self, msg: GuideResult):
        payload = {
            'type': MSG_GUIDE_RESULT,
            'robot_id': int(msg.robot_id),
            'cmd_type': int(msg.cmd_type),
            'status': int(msg.status),
            'dest_name': msg.dest_name or '',
            'message': msg.message or '',
        }
        self._send_json_line(payload)
        self.get_logger().info(
            f'결과 송신 — status={msg.status} dest={msg.dest_name}')

    def _on_status(self, msg: RobotStatus):
        payload = {
            'type': MSG_ROBOT_STATUS,
            'robot_id': int(msg.robot_id),
            'state': int(msg.state),
            'battery': float(msg.battery),
            'pose_x': float(msg.pose_x),
            'pose_y': float(msg.pose_y),
            'current_task': msg.current_task or '',
        }
        self._send_json_line(payload)

    def _send_json_line(self, obj):
        line = json.dumps(obj, ensure_ascii=False) + '\n'
        data = line.encode('utf-8')
        with self._lock:
            if self._sock is None:
                self.get_logger().debug('TCP 미연결 — JSON 줄 버림')
                return
            try:
                self._sock.sendall(data)
            except Exception as e:
                self.get_logger().error(f'송신 오류: {e}')
                self._sock = None


def main(args=None):
    rclpy.init(args=args)
    node = TcpBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
