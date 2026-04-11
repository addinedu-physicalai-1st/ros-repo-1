"""
states.py — Top-level state definitions for the Supervisor (TopFSM).

Only the states that TopFSM itself occupies are defined here.
Each Sub FSM defines its own private state enum inside its own module.

State descriptions
------------------
CHARGING
    Robot is docked at the charging station. No Sub FSM is active.
    All incoming TASK_ASSIGNED events are queued and processed once the
    robot returns to IDLE.

MOVE_TO_WAITING
    Robot is navigating to the designated waiting/home position.
    No Sub FSM is active. Triggered after charging completes or after
    a task finishes.

IDLE
    Robot is stationary at the waiting position, ready to receive tasks.
    No Sub FSM is active.

DELIVERY
    The DeliveryFSM Sub FSM is active. The robot is executing a delivery
    task (pick up item → navigate → hand off).

PICKUP
    The PickupFSM Sub FSM is active. The robot is collecting an item or
    fetching something on behalf of a user.

FOLLOW
    The FollowFSM Sub FSM is active. The robot is accompanying a user
    from one location to another.

GUIDE
    The GuideFSM Sub FSM is active. The robot is leading a user to a
    destination (user follows the robot).
"""

from enum import Enum, auto


class TopState(Enum):
    """Global states managed exclusively by TopFSM."""

    CHARGING = auto()
    MOVE_TO_WAITING = auto()
    IDLE = auto()
    DELIVERY = auto()
    PICKUP = auto()
    FOLLOW = auto()
    GUIDE = auto()
