"""
base_fsm.py — Abstract base class for all FSMs in the rost_state framework.

How to create a new Sub FSM
---------------------------
1. Define a private State enum in your module.
2. Subclass BaseFSM and pass the initial state to super().__init__().
3. Override on_enter() and on_exit() for side-effects (logging, actuators, …).
4. Override _handle_event() to implement the transition table.
5. Call self.transition(new_state) from _handle_event() when a transition
   should occur. Do NOT call transition() from outside the FSM.

Thread safety
-------------
BaseFSM is NOT thread-safe by design. All calls must come from the same
ROS2 executor thread (the timer callback). If you need cross-thread access,
protect with a threading.Lock in the concrete subclass or the node.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BaseFSM(ABC):
    """
    Minimal, reusable Finite State Machine base class.

    Attributes
    ----------
    _state : Enum
        Current state. Read via the ``state`` property; never set directly
        from outside — always go through ``transition()``.
    _logger : logging.Logger
        Module-level logger. Concrete classes may override with a ROS logger.
    """

    def __init__(self, initial_state: Enum) -> None:
        self._state: Enum = initial_state
        self._logger = logger
        # Trigger on_enter for the initial state so subclasses can initialise.
        self.on_enter(self._state)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def state(self) -> Enum:
        """Read-only view of the current state."""
        return self._state

    def update(self, event: Enum, payload: dict[str, Any] | None = None) -> bool:
        """
        Feed an event into the FSM.

        Parameters
        ----------
        event : Enum
            The event to process (typically from ``events.Event``).
        payload : dict | None
            Optional structured data attached to the event.
            Example: {"task_type": TaskType.DELIVERY, "target": "room_3"}

        Returns
        -------
        bool
            True if the event triggered a state transition, False otherwise.
        """
        prev = self._state
        self._handle_event(event, payload or {})
        return self._state is not prev

    def transition(self, new_state: Enum) -> None:
        """
        Execute a state transition.

        Calls on_exit() for the current state, then on_enter() for the new
        state. No-ops if new_state equals the current state.

        Only call this from within ``_handle_event()``.
        """
        if new_state is self._state:
            return
        self._logger.info(
            '[%s] %s → %s',
            type(self).__name__,
            self._state.name,
            new_state.name,
        )
        self.on_exit(self._state)
        self._state = new_state
        self.on_enter(self._state)

    # ------------------------------------------------------------------
    # Hooks — override in concrete subclasses
    # ------------------------------------------------------------------

    def on_enter(self, state: Enum) -> None:
        """
        Called immediately after entering ``state``.

        Override to start timers, send navigation goals, play sounds, etc.
        The default implementation just logs the entry.
        """
        self._logger.debug('[%s] enter %s', type(self).__name__, state.name)

    def on_exit(self, state: Enum) -> None:
        """
        Called immediately before leaving ``state``.

        Override to cancel timers, stop actuators, save progress, etc.
        The default implementation just logs the exit.
        """
        self._logger.debug('[%s] exit %s', type(self).__name__, state.name)

    # ------------------------------------------------------------------
    # Abstract — must be implemented by every concrete FSM
    # ------------------------------------------------------------------

    @abstractmethod
    def _handle_event(self, event: Enum, payload: dict[str, Any]) -> None:
        """
        Implement the FSM's transition table.

        Use ``self.transition(NewState.X)`` to move to a new state.
        Do nothing (return without calling transition) to stay in the
        current state.

        Parameters
        ----------
        event : Enum
        payload : dict  (never None — guaranteed by ``update()``)
        """

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f'{type(self).__name__}(state={self._state.name})'
