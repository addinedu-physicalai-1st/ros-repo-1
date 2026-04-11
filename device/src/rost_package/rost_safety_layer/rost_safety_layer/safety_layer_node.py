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
applies safety rules, and publishes safe commands on /cmd_vel.

Safety rules
------------
1. Child detected (/child_detected == True)
   → publish zero-velocity at 10 Hz until the flag clears.
2. Child-detection topic timeout (no message for > 1 s)
   → assume unsafe, stop the robot.
3. Normal operation (/child_detected == False, topic fresh)
   → forward /cmd_vel_raw to /cmd_vel unchanged.
"""

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist
from std_msgs.msg import Bool

# ── Topic names ────────────────────────────────────────────────────────────────
CMD_VEL_RAW_TOPIC = 'cmd_vel_raw'
CHILD_DETECTED_TOPIC = 'child_detected'
CMD_VEL_TOPIC = 'cmd_vel'
SAFETY_STOP_EVENT_TOPIC = 'safety_stop_event'

# ── Tuneable constants ─────────────────────────────────────────────────────────
PUBLISH_RATE_HZ = 10.0          # Timer rate for safety-stop heartbeat
CHILD_DETECTED_TIMEOUT_S = 1.0  # Max seconds between /child_detected messages


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
    /cmd_vel_raw  (geometry_msgs/Twist)  – raw commands from nav / teleop
    /child_detected (std_msgs/Bool)      – True when a child is nearby

    Publishes
    ---------
    /cmd_vel  (geometry_msgs/Twist)  – filtered, safe commands
    """

    def __init__(self):
        super().__init__('safety_layer_node')

        # ── Internal state ─────────────────────────────────────────────────────
        # Latest raw velocity command received from navigation / teleop.
        self.latest_cmd_vel_raw: Twist = _zero_twist()

        # True when a child is detected nearby (triggers emergency stop).
        self.child_detected_state: bool = False

        # Timestamp of the last /child_detected message.  Initialised to None
        # so we can distinguish "never received" from "received False".
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

        self.child_detected_sub = self.create_subscription(
            Bool,
            CHILD_DETECTED_TOPIC,
            self._child_detected_callback,
            10
        )

        # ── Timer ─────────────────────────────────────────────────────────────
        # Drives the safety logic at a fixed rate.  When an emergency stop is
        # active this guarantees the robot keeps receiving zero-velocity even
        # if /cmd_vel_raw goes silent.
        self.timer = self.create_timer(1.0 / PUBLISH_RATE_HZ, self._timer_callback)

        self.get_logger().info('SafetyLayerNode started.')
        self.get_logger().info(
            f'  Subscribing : {CMD_VEL_RAW_TOPIC}, {CHILD_DETECTED_TOPIC}'
        )
        self.get_logger().info(f'  Publishing  : {CMD_VEL_TOPIC}')
        self.get_logger().info(
            f'  Publish rate: {PUBLISH_RATE_HZ} Hz  |  '
            f'Timeout: {CHILD_DETECTED_TIMEOUT_S} s'
        )

    # ── Subscriber callbacks ───────────────────────────────────────────────────

    def _cmd_vel_raw_callback(self, msg: Twist):
        """Cache the latest raw velocity command from navigation / teleop."""
        self.latest_cmd_vel_raw = msg

    def _child_detected_callback(self, msg: Bool):
        """Update child-detection state and refresh the liveness timestamp."""
        self.last_child_msg_time = self.get_clock().now()

        if msg.data != self.child_detected_state:
            if msg.data:
                self.get_logger().warn(
                    'Child detected — activating emergency stop!'
                )
            else:
                self.get_logger().info(
                    'Child no longer detected — resuming normal operation.'
                )

        self.child_detected_state = msg.data

    # ── Timer callback (safety logic) ──────────────────────────────────────────

    def _timer_callback(self):
        """
        Evaluate safety conditions and publish the appropriate Twist.

        Priority (highest first):
        1. /child_detected topic has timed out  → emergency stop + warn
        2. child_detected_state is True          → emergency stop
        3. Normal operation                      → forward raw command
        """
        now = self.get_clock().now()

        # ── Condition 1: topic timeout ─────────────────────────────────────────
        if self.last_child_msg_time is None:
            # We have never received a /child_detected message yet.
            self.get_logger().warn(
                'Waiting for first /child_detected message — '
                'holding robot stopped as a precaution.',
                throttle_duration_sec=5.0
            )
            self.cmd_vel_pub.publish(_zero_twist())
            self.safety_stop_event_pub.publish(_bool_msg(True))
            return

        elapsed = (now - self.last_child_msg_time).nanoseconds / 1e9
        if elapsed > CHILD_DETECTED_TIMEOUT_S:
            self.get_logger().warn(
                f'/child_detected topic silent for {elapsed:.1f} s '
                f'(timeout={CHILD_DETECTED_TIMEOUT_S} s) — '
                'assuming unsafe, stopping robot.',
                throttle_duration_sec=1.0
            )
            self.cmd_vel_pub.publish(_zero_twist())
            self.safety_stop_event_pub.publish(_bool_msg(True))
            return

        # ── Condition 2: child detected ────────────────────────────────────────
        if self.child_detected_state:
            self.get_logger().warn(
                'Emergency stop active — child nearby!',
                throttle_duration_sec=1.0
            )
            self.cmd_vel_pub.publish(_zero_twist())
            self.safety_stop_event_pub.publish(_bool_msg(True))
            return

        # ── Condition 3: normal operation ──────────────────────────────────────
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
