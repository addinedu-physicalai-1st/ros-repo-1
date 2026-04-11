"""
events.py — Common FSM event definitions.

All FSMs in the rost_state framework share this event vocabulary.
Sub FSMs may define their own additional internal events, but external
signals from the ROS2 node always arrive as one of these common events.

Design note
-----------
Events are the *input* to the FSM. They do NOT carry target state
information — the FSM's transition table decides what state to move to.
The optional payload dict lets callers attach structured data to an event
without changing the event type (e.g. task_type with TASK_ASSIGNED).
"""

from enum import Enum, auto


class Event(Enum):
    """
    Top-level event vocabulary shared by all FSMs.

    Battery events
    --------------
    BATTERY_LOW   Battery fell below the low threshold (default 20 %).
                  TopFSM immediately interrupts any running Sub FSM and
                  transitions to CHARGING.
    BATTERY_OK    Battery rose above the recovery threshold (default 80 %).
                  TopFSM leaves CHARGING and moves to MOVE_TO_WAITING.

    Task lifecycle events
    ---------------------
    TASK_ASSIGNED   A new task has been dispatched.
                    Payload: {"task_type": TaskType, ...task-specific fields}
    TASK_COMPLETED  The active Sub FSM finished its task successfully.
    TASK_CANCELLED  The active task was aborted (operator cancel, safety stop, …).

    Navigation events
    -----------------
    ARRIVED         The robot reached its current navigation goal.
    OBSTACLE_DETECTED  A static or dynamic obstacle blocks the path.
    OBSTACLE_CLEARED   The obstacle has been removed / navigated around.

    Human-interaction events
    ------------------------
    USER_DETECTED   A target user/passenger has been detected nearby.
    USER_LOST       The tracked user is no longer visible / reachable.

    General
    -------
    TIMEOUT  A time-boxed operation did not complete within the deadline.
    TICK     Periodic heartbeat emitted by the ROS2 timer (10 Hz).
             Useful for FSMs that need to poll internal conditions.
    """

    # Battery
    BATTERY_LOW = auto()
    BATTERY_OK = auto()

    # Task lifecycle
    TASK_ASSIGNED = auto()
    TASK_COMPLETED = auto()
    TASK_CANCELLED = auto()

    # Navigation
    ARRIVED = auto()
    OBSTACLE_DETECTED = auto()
    OBSTACLE_CLEARED = auto()

    # Human interaction
    USER_DETECTED = auto()
    USER_LOST = auto()

    # User verification (FollowFSM)
    USER_CONFIRMED = auto()    # Detected user matches the task requester.
    USER_NOT_MATCH = auto()    # Detected user does NOT match → abort follow task.

    # Destination verification
    WRONG_DESTINATION = auto()   # Sent by verifier when destination is incorrect.
                                  # GuideFSM retries navigation on this event.

    # Sensor / hardware status replies
    BATTERY_STATUS = auto()   # payload: {"battery_level": float}  (0.0 – 1.0)
                               # Sent by the ROS2 node in response to a
                               # battery-info request from a Sub FSM.

    # General
    TIMEOUT = auto()
    TICK = auto()


class TaskType(Enum):
    """
    Identifies which Sub FSM should be activated by a TASK_ASSIGNED event.

    Pass as payload["task_type"] when emitting TASK_ASSIGNED.
    """

    DELIVERY = auto()
    PICKUP = auto()
    FOLLOW = auto()
    GUIDE = auto()
