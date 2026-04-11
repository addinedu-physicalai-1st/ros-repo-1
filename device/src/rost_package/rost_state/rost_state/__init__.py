"""
rost_state — Reusable ROS2 FSM framework for robot task management.

Public API
----------
from rost_state.base_fsm   import BaseFSM
from rost_state.events     import Event, TaskType
from rost_state.states     import TopState
from rost_state.top_fsm    import TopFSM
from rost_state.delivery_fsm import DeliveryFSM
from rost_state.pickup_fsm   import PickupFSM
from rost_state.follow_fsm   import FollowFSM
from rost_state.guide_fsm    import GuideFSM

Creating a new Sub FSM for your feature package
-----------------------------------------------
1. Create a new module (e.g. my_feature_fsm.py) inside your own package.
2. Inherit BaseFSM:

    from rost_state.base_fsm import BaseFSM
    from rost_state.events   import Event
    from enum import Enum, auto

    class MyState(Enum):
        IDLE = auto()
        WORKING = auto()
        DONE = auto()

    class MyFeatureFSM(BaseFSM):
        def __init__(self):
            super().__init__(MyState.IDLE)

        def _handle_event(self, event, payload):
            if self._state is MyState.IDLE and event is Event.TASK_ASSIGNED:
                self.transition(MyState.WORKING)

        @property
        def is_done(self):
            return self._state is MyState.DONE

        def reset(self):
            if self._state is not MyState.IDLE:
                self.on_exit(self._state)
                self._state = MyState.IDLE
                self.on_enter(self._state)

3. Register your FSM in top_fsm.py:
   - Add a new TopState value to states.py
   - Add a TaskType value to events.py
   - Add the FSM to _TASK_STATE_TO_FSM and _TASK_TYPE_TO_STATE dicts
   - Add an entry in TopFSM._sub_fsms
"""
