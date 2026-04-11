"""
follow_fsm.py — Linear accompaniment FSM (동행 Sub FSM).

State diagram
-------------

    IDLE
     │  TASK_ASSIGNED
     ▼
  MOVING_TO_USER
     │  ARRIVED
     ▼
  VERIFYING_USER
     ├── USER_CONFIRMED ──► ACCOMPANYING_USER
     │                             │  TASK_COMPLETED
     │                             ▼
     └── USER_NOT_MATCH ─────►  DONE

Any state: TASK_CANCELLED → DONE

Design notes
------------
* Intentionally simple and linear: 이동 → 확인 → 동행 → 종료.
* No search / pause / USER_LOST logic — this is not a tracking FSM.
* USER_NOT_MATCH terminates immediately; the requester identity mismatch
  is treated as a hard stop rather than a retry condition.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

from .base_fsm import BaseFSM
from .events import Event


class FollowState(Enum):
    """Private states of the Follow (동행) Sub FSM."""

    IDLE = auto()
    MOVING_TO_USER = auto()
    VERIFYING_USER = auto()
    ACCOMPANYING_USER = auto()
    DONE = auto()


class FollowFSM(BaseFSM):
    """
    Accompanies a verified user from their current location to a destination.

    Flow
    ----
    1. Navigate to the requesting user's location (MOVING_TO_USER).
    2. Confirm the detected person is the correct requester (VERIFYING_USER).
       - Mismatch → abort immediately (DONE).
    3. Walk alongside the user until they end the session (ACCOMPANYING_USER).
    4. Task complete (DONE).
    """

    def __init__(self) -> None:
        super().__init__(FollowState.IDLE)

    # =========================================================================
    # Transition table
    # =========================================================================

    def _handle_event(self, event: Event, payload: dict[str, Any]) -> None:
        s = self._state

        # ── Global: cancellation from any state ───────────────────────────────
        if event is Event.TASK_CANCELLED:
            self.transition(FollowState.DONE)
            return

        # ── State-specific transitions ────────────────────────────────────────
        if s is FollowState.IDLE:
            if event is Event.TASK_ASSIGNED:
                self.transition(FollowState.MOVING_TO_USER)

        elif s is FollowState.MOVING_TO_USER:
            if event is Event.ARRIVED:
                self.transition(FollowState.VERIFYING_USER)
            elif event is Event.OBSTACLE_DETECTED:
                self._logger.warning('[FollowFSM] Obstacle en route to user — waiting.')
            elif event is Event.TIMEOUT:
                self._logger.warning('[FollowFSM] Navigation to user timed out.')
                self.transition(FollowState.DONE)

        elif s is FollowState.VERIFYING_USER:
            if event is Event.USER_CONFIRMED:
                self.transition(FollowState.ACCOMPANYING_USER)
            elif event is Event.USER_NOT_MATCH:
                self._logger.warning('[FollowFSM] User identity mismatch — aborting task.')
                self.transition(FollowState.DONE)
            elif event is Event.TIMEOUT:
                self._logger.warning('[FollowFSM] User verification timed out.')
                self.transition(FollowState.DONE)

        elif s is FollowState.ACCOMPANYING_USER:
            if event is Event.TASK_COMPLETED:
                self.transition(FollowState.DONE)
            elif event is Event.TIMEOUT:
                self._logger.warning('[FollowFSM] Accompaniment timed out.')
                self.transition(FollowState.DONE)

        # FollowState.DONE is terminal — TopFSM detects is_done and resets us.

    # =========================================================================
    # Lifecycle hooks
    # =========================================================================

    def on_enter(self, state: FollowState) -> None:
        super().on_enter(state)
        messages = {
            FollowState.MOVING_TO_USER:    '→ Moving to user location.',
            FollowState.VERIFYING_USER:    '→ Verifying requesting user.',
            FollowState.ACCOMPANYING_USER: '→ Accompanying user.',
            FollowState.DONE:              '→ Follow task complete.',
        }
        if state in messages:
            self._logger.info('[FollowFSM] %s', messages[state])

    def on_exit(self, state: FollowState) -> None:
        super().on_exit(state)

    # =========================================================================
    # Public interface (used by TopFSM)
    # =========================================================================

    @property
    def is_done(self) -> bool:
        """True when the FSM has reached its terminal DONE state."""
        return self._state is FollowState.DONE

    def reset(self) -> None:
        """Return to IDLE for reuse by TopFSM."""
        if self._state is not FollowState.IDLE:
            self.on_exit(self._state)
            self._state = FollowState.IDLE
            self.on_enter(self._state)
