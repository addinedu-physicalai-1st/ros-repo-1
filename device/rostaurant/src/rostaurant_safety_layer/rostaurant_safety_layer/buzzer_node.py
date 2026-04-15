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
Buzzer Node — child_safety_zone 토픽을 구독해 부저 패턴을 제어합니다.

Subscribes
----------
  child_safety_zone (std_msgs/String)  NORMAL / MONITOR / CAUTION / STOP

Buzzer patterns
---------------
  NORMAL  / MONITOR : OFF
  CAUTION           : 0.3초 ON → 0.3초 OFF 반복 (삐-삐-삐-)
  STOP              : 계속 ON  (삐---)

안전 상태가 변경될 때만 패턴을 갱신합니다(불필요한 재시작 방지).

ROS Parameters
--------------
  buzzer_pin  int  18   BCM GPIO 핀 번호 (Raspberry Pi)
"""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

try:
    import RPi.GPIO as GPIO
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False

# ── Topic names ────────────────────────────────────────────────────────────────
CHILD_SAFETY_ZONE_TOPIC = 'child_safety_zone'

# ── Zone identifiers ───────────────────────────────────────────────────────────
ZONE_CAUTION = 'CAUTION'
ZONE_STOP = 'STOP'

# CAUTION 패턴 반주기 (초): 0.3초 ON → 0.3초 OFF
BEEP_HALF_PERIOD_S = 0.3


class BuzzerNode(Node):
    """
    child_safety_zone 구독 기반 부저 패턴 제어 노드.

    GPIO가 없는 환경(개발 PC 등)에서는 로그로 시뮬레이션합니다.
    """

    def __init__(self):
        super().__init__('buzzer_node')

        self.declare_parameter('buzzer_pin',          18)
        self.declare_parameter('beep_half_period_s',  BEEP_HALF_PERIOD_S)

        self._pin: int           = self.get_parameter('buzzer_pin').value
        self._beep_half: float   = self.get_parameter('beep_half_period_s').value

        self._zone: str = ''      # 현재 zone
        self._buzzer_on: bool = False

        # ── GPIO 초기화 ────────────────────────────────────────────────────────
        if _HAS_GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self._pin, GPIO.OUT)
            GPIO.output(self._pin, GPIO.LOW)
            self.get_logger().info(f'GPIO initialized: pin {self._pin} (BCM).')
        else:
            self.get_logger().warn(
                'RPi.GPIO not available — buzzer will be simulated via log.'
            )

        # ── Subscriber ─────────────────────────────────────────────────────────
        self.create_subscription(String, CHILD_SAFETY_ZONE_TOPIC, self._zone_callback, 10)

        # ── Beep timer (CAUTION 패턴 전용) ─────────────────────────────────────
        # beep_half_period_s마다 호출. CAUTION 상태일 때만 토글.
        self._beep_timer = self.create_timer(self._beep_half, self._beep_timer_callback)

        self.get_logger().info(
            f'BuzzerNode started. pin={self._pin}, '
            f'beep_half_period={self._beep_half}s'
        )

    # ── Callback ───────────────────────────────────────────────────────────────

    def _zone_callback(self, msg: String):
        """zone이 변경될 때만 부저 패턴을 갱신합니다."""
        new_zone = msg.data
        if new_zone == self._zone:
            return

        self.get_logger().info(f'Buzzer zone: "{self._zone}" → "{new_zone}"')
        self._zone = new_zone

        if new_zone == ZONE_STOP:
            # 연속 ON
            self._buzzer_set(True)
        elif new_zone == ZONE_CAUTION:
            # 패턴 시작: ON 상태로 시작, 이후 타이머가 토글
            self._buzzer_set(True)
        else:
            # NORMAL / MONITOR: OFF
            self._buzzer_set(False)

    def _beep_timer_callback(self):
        """CAUTION 상태일 때 BEEP_HALF_PERIOD_S마다 ON/OFF를 토글합니다."""
        if self._zone != ZONE_CAUTION:
            return
        self._buzzer_set(not self._buzzer_on)

    # ── GPIO helper ────────────────────────────────────────────────────────────

    def _buzzer_set(self, on: bool):
        """부저 ON/OFF를 제어합니다."""
        self._buzzer_on = on
        if _HAS_GPIO:
            GPIO.output(self._pin, GPIO.HIGH if on else GPIO.LOW)
        else:
            self.get_logger().debug(f'Buzzer {"ON " if on else "OFF"}')

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def destroy_node(self):
        """노드 종료 시 부저를 끄고 GPIO를 정리합니다."""
        self._buzzer_set(False)
        if _HAS_GPIO:
            GPIO.cleanup()
        super().destroy_node()


# ── Entry point ────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = BuzzerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
