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
Safety Layer Node for Rost Pro robot.

Sits between the navigation / teleoperation stack and the robot base
controller.  It subscribes to raw velocity commands on /cmd_vel_raw,
applies safety rules based on child_safety_zone, and publishes safe
commands on /cmd_vel.

Safety rules
------------
1. child_safety_zone topic timeout (no message for > 1 s)
   → assume unsafe, stop the robot.
2. child_safety_zone == STOP
   → publish zero-velocity at 10 Hz until the zone clears.
3. child_safety_zone == CAUTION
   → scale /cmd_vel_raw by 50% and forward to /cmd_vel.
4. Normal operation (NORMAL / MONITOR, topic fresh)
   → forward /cmd_vel_raw to /cmd_vel unchanged.
"""

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist
from std_msgs.msg import Bool, String

# ── Topic names ────────────────────────────────────────────────────────────────
CMD_VEL_RAW_TOPIC = 'cmd_vel_raw'
CHILD_SAFETY_ZONE_TOPIC = 'child_safety_zone'
CMD_VEL_TOPIC = 'cmd_vel'
SAFETY_STOP_EVENT_TOPIC = 'safety_stop_event'

# ── Tuneable constants ─────────────────────────────────────────────────────────
PUBLISH_RATE_HZ = 10.0               # Timer rate for safety-stop heartbeat
CHILD_DETECTED_TIMEOUT_S = 1.0       # Max seconds between /child_safety_zone messages
CAUTION_SPEED_SCALE = 0.5            # CAUTION 구역 속도 감속 비율

# ── Zone identifiers ───────────────────────────────────────────────────────────
ZONE_NORMAL = 'NORMAL'
ZONE_MONITOR = 'MONITOR'
ZONE_CAUTION = 'CAUTION'
ZONE_STOP = 'STOP'


def _zero_twist() -> Twist:
    """Return a Twist message with all fields set to zero."""
    return Twist()  # All fields default to 0.0


def _bool_msg(value: bool) -> Bool:
    """Return std_msgs/Bool initialized with value."""
    msg = Bool()
    msg.data = value
    return msg


class SafetyLayerNode(Node):
    """
    Velocity-command safety filter.

    Subscribes
    ----------
    /cmd_vel_raw       (geometry_msgs/Twist)  – raw commands from nav / teleop
    /child_safety_zone (std_msgs/String)      – NORMAL / MONITOR / CAUTION / STOP

    Publishes
    ---------
    /cmd_vel  (geometry_msgs/Twist)  – filtered, safe commands
      STOP    → zero velocity
      CAUTION → 50% scaled velocity
      others  → raw velocity forwarded unchanged
    """

    def __init__(self):
        super().__init__('safety_layer_node')

        # ── Parameters ─────────────────────────────────────────────────────────
        self.declare_parameter('publish_rate_hz',    PUBLISH_RATE_HZ)
        self.declare_parameter('zone_timeout_s',     CHILD_DETECTED_TIMEOUT_S)
        self.declare_parameter('caution_speed_scale', CAUTION_SPEED_SCALE)

        self._publish_rate_hz     = self.get_parameter('publish_rate_hz').value
        self._zone_timeout_s      = self.get_parameter('zone_timeout_s').value
        self._caution_speed_scale = self.get_parameter('caution_speed_scale').value

        # ── Internal state ─────────────────────────────────────────────────────
        # Latest raw velocity command received from navigation / teleop.
        self.latest_cmd_vel_raw: Twist = _zero_twist()

        # Current child safety zone (NORMAL / MONITOR / CAUTION / STOP).
        self.child_safety_zone: str = ZONE_NORMAL

        # Timestamp of the last /child_safety_zone message.  Initialised to None
        # so we can distinguish "never received" from "received NORMAL".
        self.last_child_msg_time = None  # rclpy.time.Time | None

        # ── Publisher ──────────────────────────────────────────────────────────
        self.cmd_vel_pub = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)

        self.safety_stop_event_pub = self.create_publisher(Bool, SAFETY_STOP_EVENT_TOPIC, 10)

        # ── Subscribers ───────────────────────────────────────────────────────
        self.cmd_vel_raw_sub = self.create_subscription(
            Twist,
            CMD_VEL_RAW_TOPIC,
            self._cmd_vel_raw_callback,
            10
        )

        self.child_safety_zone_sub = self.create_subscription(
            String,
            CHILD_SAFETY_ZONE_TOPIC,
            self._child_safety_zone_callback,
            10
        )

        # ── Timer ─────────────────────────────────────────────────────────────
        # Drives the safety logic at a fixed rate.  When an emergency stop is
        # active this guarantees the robot keeps receiving zero-velocity even
        # if /cmd_vel_raw goes silent.
        self.timer = self.create_timer(1.0 / self._publish_rate_hz, self._timer_callback)

        self.get_logger().info('SafetyLayerNode started.')
        self.get_logger().info(
            f'  Subscribing : {CMD_VEL_RAW_TOPIC}, {CHILD_SAFETY_ZONE_TOPIC}'
        )
        self.get_logger().info(f'  Publishing  : {CMD_VEL_TOPIC}')
        self.get_logger().info(
            f'  Publish rate: {self._publish_rate_hz} Hz  |  '
            f'Timeout: {self._zone_timeout_s} s  |  '
            f'CAUTION scale: {self._caution_speed_scale}'
        )

    # ── Subscriber callbacks ───────────────────────────────────────────────────

    def _cmd_vel_raw_callback(self, msg: Twist):
        """Cache the latest raw velocity command from navigation / teleop."""
        self.latest_cmd_vel_raw = msg

    def _child_safety_zone_callback(self, msg: String):
        """Update child safety zone state and refresh the liveness timestamp."""
        self.last_child_msg_time = self.get_clock().now()

        zone = msg.data
        if zone != self.child_safety_zone:
            self.get_logger().info(
                f'Safety zone: {self.child_safety_zone} → {zone}'
            )
            if zone == ZONE_STOP:
                self.get_logger().warn('Emergency stop active — child in STOP zone!')
            elif zone == ZONE_CAUTION:
                self.get_logger().warn(
                    f'CAUTION zone — speed reduced to {int(CAUTION_SPEED_SCALE * 100)}%.'
                )

        self.child_safety_zone = zone

    # ── Timer callback (safety logic) ──────────────────────────────────────────

    def _timer_callback(self):
        """
        Evaluate safety conditions and publish the appropriate Twist.

        Priority (highest first):
        1. /child_safety_zone topic has timed out  → emergency stop + warn
        2. child_safety_zone == STOP               → emergency stop (zero velocity)
        3. child_safety_zone == CAUTION            → 50% scaled velocity
        4. Normal operation (NORMAL / MONITOR)     → forward raw command unchanged
        """
        now = self.get_clock().now()

        # ── Condition 1: topic timeout ─────────────────────────────────────────
        if self.last_child_msg_time is None:
            self.get_logger().warn(
                'Waiting for first /child_safety_zone message — '
                'holding robot stopped as a precaution.',
                throttle_duration_sec=5.0
            )
            self.cmd_vel_pub.publish(_zero_twist())
            self.safety_stop_event_pub.publish(_bool_msg(True))
            return

        elapsed = (now - self.last_child_msg_time).nanoseconds / 1e9
        if elapsed > self._zone_timeout_s:
            self.get_logger().warn(
                f'/child_safety_zone topic silent for {elapsed:.1f} s '
                f'(timeout={self._zone_timeout_s} s) — '
                'assuming unsafe, stopping robot.',
                throttle_duration_sec=1.0
            )
            self.cmd_vel_pub.publish(_zero_twist())
            self.safety_stop_event_pub.publish(_bool_msg(True))
            return

        # ── Condition 2: STOP zone ─────────────────────────────────────────────
        if self.child_safety_zone == ZONE_STOP:
            self.get_logger().warn(
                'Emergency stop active — child in STOP zone!',
                throttle_duration_sec=1.0
            )
            self.cmd_vel_pub.publish(_zero_twist())
            self.safety_stop_event_pub.publish(_bool_msg(True))
            return

        # ── Condition 3: CAUTION zone ──────────────────────────────────────────
        if self.child_safety_zone == ZONE_CAUTION:
            raw = self.latest_cmd_vel_raw
            s = self._caution_speed_scale
            scaled = Twist()
            scaled.linear.x  = raw.linear.x  * s
            scaled.linear.y  = raw.linear.y  * s
            scaled.linear.z  = raw.linear.z  * s
            scaled.angular.x = raw.angular.x * s
            scaled.angular.y = raw.angular.y * s
            scaled.angular.z = raw.angular.z * s
            self.cmd_vel_pub.publish(scaled)
            self.safety_stop_event_pub.publish(_bool_msg(False))
            return

        # ── Condition 4: normal operation (NORMAL / MONITOR) ───────────────────
        self.cmd_vel_pub.publish(self.latest_cmd_vel_raw)
        self.safety_stop_event_pub.publish(_bool_msg(False))


# ── Entry point ────────────────────────────────────────────────────────────────

def main(args=None):
    rclpy.init(args=args)
    node = SafetyLayerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
