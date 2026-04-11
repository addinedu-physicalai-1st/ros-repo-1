"""
fsm_node.py — ROS2 node that hosts and drives the TopFSM.

Responsibilities
----------------
* Instantiate TopFSM with the configured initial_state.
* Run a 10 Hz timer that:
    - emits a TICK event so FSMs can do time-based checks
    - simulates a battery drain/charge cycle (demo mode)
    - logs the current FSM status
* Subscribe to /fsm/event to receive external event commands.
* Subscribe to /battery_percent to receive real battery readings.
* Publish /fsm/state (std_msgs/String) for downstream nodes.

Topics
------
Subscribe  /fsm/event       std_msgs/String   — event name (e.g. "TASK_ASSIGNED")
Subscribe  /battery_percent std_msgs/Float32  — battery level 0–100
Publish    /fsm/state       std_msgs/String   — JSON status snapshot

Parameters
----------
initial_state  str    "IDLE"   initial TopState
debug_mode     bool   false    print detailed per-tick logs
battery_sim    bool   true     simulate battery drain/charge for demo

How to extend
-------------
To trigger events from another node publish to /fsm/event:
  ros2 topic pub --once /fsm/event std_msgs/String "{data: 'TASK_ASSIGNED:DELIVERY'}"
  ros2 topic pub --once /fsm/event std_msgs/String "{data: 'TASK_ASSIGNED:PICKUP,dish_count=3'}"
  ros2 topic pub --once /fsm/event std_msgs/String "{data: 'BATTERY_STATUS:battery_level=0.45'}"
  ros2 topic pub --once /fsm/event std_msgs/String "{data: 'ARRIVED'}"

Payload format
--------------
  TASK_ASSIGNED:<TASK_TYPE>[,key=value,...]   first token is the TaskType name
  <EVENT>:<key=value>[,key=value,...]          all tokens are key=value pairs
  Numeric values are coerced to int or float automatically.
"""

from __future__ import annotations

import json
import logging

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String

from .events import Event, TaskType
from .states import TopState
from .top_fsm import TopFSM

# ── Configure Python logging → ROS logger bridge ─────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format='%(name)s [%(levelname)s] %(message)s',
)


class FsmNode(Node):
    """
    ROS2 node that hosts the TopFSM and bridges it to the ROS2 ecosystem.

    All FSM logic lives in TopFSM / Sub FSMs. This node is deliberately
    thin — it only handles ROS2 I/O (params, topics, timers).
    """

    # Battery simulation: drain at this rate per tick (10 Hz)
    _SIM_DRAIN_RATE = 0.05    # %/tick  (0.5 %/s)
    _SIM_CHARGE_RATE = 0.2    # %/tick  (2   %/s)

    def __init__(self) -> None:
        super().__init__('fsm_node')

        # ── Parameters ───────────────────────────────────────────────────────
        self.declare_parameter('initial_state', 'IDLE')
        self.declare_parameter('debug_mode', False)
        self.declare_parameter('battery_sim', True)

        initial_state_name: str = (
            self.get_parameter('initial_state').get_parameter_value().string_value
        )
        self._debug_mode: bool = (
            self.get_parameter('debug_mode').get_parameter_value().bool_value
        )
        self._battery_sim: bool = (
            self.get_parameter('battery_sim').get_parameter_value().bool_value
        )

        # Map string → TopState
        try:
            initial_state = TopState[initial_state_name.upper()]
        except KeyError:
            self.get_logger().warn(
                f'Unknown initial_state "{initial_state_name}" — defaulting to IDLE.'
            )
            initial_state = TopState.IDLE

        # ── FSM ───────────────────────────────────────────────────────────────
        self._fsm = TopFSM(initial_state=initial_state)
        # Bridge Python logging from the FSM to ROS logger
        logging.root.handlers.clear()
        logging.root.addHandler(_RosLogHandler(self.get_logger()))

        # ── Publishers ───────────────────────────────────────────────────────
        self._state_pub = self.create_publisher(String, '/fsm/state', 10)

        # ── Subscribers ──────────────────────────────────────────────────────
        self.create_subscription(String, '/fsm/event', self._event_callback, 10)
        self.create_subscription(Float32, '/battery_percent', self._battery_callback, 10)

        # ── Timer (10 Hz) ─────────────────────────────────────────────────────
        self.create_timer(0.1, self._tick)

        self.get_logger().info(
            f'FsmNode started — initial state: {self._fsm.state.name}'
        )
        self.get_logger().info(
            f'  debug_mode  : {self._debug_mode}'
        )
        self.get_logger().info(
            f'  battery_sim : {self._battery_sim}'
        )
        self.get_logger().info(
            "  Send events via: ros2 topic pub --once /fsm/event "
            "std_msgs/String \"{data: 'TASK_ASSIGNED:DELIVERY'}\""
        )

    # =========================================================================
    # Timer callback (10 Hz)
    # =========================================================================

    def _tick(self) -> None:
        """Main control loop: battery sim → TICK event → publish state."""
        if self._battery_sim:
            self._simulate_battery()

        self._fsm.update(Event.TICK)

        self._publish_state()

        if self._debug_mode:
            status = self._fsm.status()
            self.get_logger().debug(
                f'[tick] {status["top_state"]} '
                f'/ {status["sub_state"] or "-"} '
                f'(bat={status["battery"]}%, queue={status["queued_tasks"]})'
            )

    def _simulate_battery(self) -> None:
        """
        Demo battery simulation:
          * While CHARGING:  battery rises at _SIM_CHARGE_RATE per tick
          * Otherwise:       battery drains at _SIM_DRAIN_RATE per tick
        """
        if self._fsm.state is TopState.CHARGING:
            new_level = min(100.0, self._fsm.battery + self._SIM_CHARGE_RATE)
        else:
            new_level = max(0.0, self._fsm.battery - self._SIM_DRAIN_RATE)

        self._fsm.set_battery(new_level)

    # =========================================================================
    # Subscriber callbacks
    # =========================================================================

    def _battery_callback(self, msg: Float32) -> None:
        """Receive real battery reading from hardware driver."""
        self._fsm.set_battery(float(msg.data))

    def _event_callback(self, msg: String) -> None:
        """
        Parse and inject an event from the /fsm/event topic.

        Message format: "EVENT_NAME" or "EVENT_NAME:TASK_TYPE[,key=value,...]"

        Examples
        --------
        "TASK_ASSIGNED:DELIVERY"
        "TASK_ASSIGNED:PICKUP,dish_count=3"
        "ARRIVED"
        "TASK_COMPLETED"
        "TASK_CANCELLED"
        "BATTERY_STATUS:battery_level=0.45"
        "USER_CONFIRMED"
        "USER_NOT_MATCH"
        "WRONG_DESTINATION"

        Format rules
        ------------
        * If the first token after ':' contains '=', all tokens are key=value pairs.
        * Otherwise the first token is a TaskType name; remaining tokens are key=value.
        * Numeric values (int/float) are automatically coerced.
        """
        raw = msg.data.strip()
        self.get_logger().info(f'[/fsm/event] Received: "{raw}"')

        # Split into event name and optional payload string
        parts = raw.split(':', 1)
        event_name = parts[0].upper()
        payload_str = parts[1] if len(parts) > 1 else ''

        # Resolve event
        try:
            event = Event[event_name]
        except KeyError:
            self.get_logger().error(
                f'Unknown event "{event_name}". '
                f'Valid events: {[e.name for e in Event]}'
            )
            return

        # Build payload dict
        payload: dict = {}
        if payload_str:
            tokens = payload_str.split(',')
            first = tokens[0]

            if '=' in first:
                # All tokens are key=value pairs (e.g. BATTERY_STATUS:battery_level=0.45)
                kv_tokens = tokens
            else:
                # First token is a TaskType name (e.g. TASK_ASSIGNED:DELIVERY,target=room_3)
                task_type_name = first.upper()
                try:
                    payload['task_type'] = TaskType[task_type_name]
                except KeyError:
                    self.get_logger().warn(
                        f'Unknown task_type "{task_type_name}" — '
                        f'valid: {[t.name for t in TaskType]}'
                    )
                kv_tokens = tokens[1:]

            # Parse key=value pairs; coerce numeric strings to float/int
            for tok in kv_tokens:
                if '=' in tok:
                    k, v = tok.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    try:
                        payload[k] = int(v)
                    except ValueError:
                        try:
                            payload[k] = float(v)
                        except ValueError:
                            payload[k] = v

        changed = self._fsm.update(event, payload)
        if changed:
            self.get_logger().info(
                f'[FSM] State changed → {self._fsm.state.name}'
                + (f' / {self._fsm.sub_state.name}' if self._fsm.sub_state else '')
            )

    # =========================================================================
    # Publisher helpers
    # =========================================================================

    def _publish_state(self) -> None:
        """Publish the current FSM status as a JSON string."""
        status = self._fsm.status()
        msg = String()
        msg.data = json.dumps(status)
        self._state_pub.publish(msg)


# ── Python logging → ROS2 logger bridge ─────────────────────────────────────

class _RosLogHandler(logging.Handler):
    """
    Redirect Python stdlib logging records to the ROS2 get_logger() API.

    This lets FSM modules use standard ``logging.getLogger(__name__)``
    without caring about ROS, while still having output routed through
    the ROS logging subsystem.
    """

    def __init__(self, ros_logger) -> None:
        super().__init__()
        self._ros = ros_logger

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        level = record.levelno
        if level >= logging.ERROR:
            self._ros.error(msg)
        elif level >= logging.WARNING:
            self._ros.warn(msg)
        elif level >= logging.INFO:
            self._ros.info(msg)
        else:
            self._ros.debug(msg)


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None) -> None:
    rclpy.init(args=args)
    node = FsmNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
