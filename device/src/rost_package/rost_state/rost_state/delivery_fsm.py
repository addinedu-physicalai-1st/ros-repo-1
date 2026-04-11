"""
delivery_fsm.py — Food delivery Sub FSM (실시간 음식 운반).

State diagram
-------------

    IDLE
     │  TASK_ASSIGNED
     ▼
  MOVING_TO_KITCHEN
     │  ARRIVED
     ▼
  LOADING_FOOD
     │  TASK_COMPLETED (적재 완료)
     ▼
  MOVING_TO_DESTINATION
     │  ARRIVED
     ▼
  UNLOADING_FOOD
     ├── TASK_COMPLETED (하차 완료) ──► DONE
     └── WRONG_DESTINATION ──────────► MOVING_TO_DESTINATION

Any state: TASK_CANCELLED → DONE
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

from .base_fsm import BaseFSM
from .events import Event


class DeliveryState(Enum):
    """Private states of the food delivery Sub FSM."""

    IDLE = auto()
    MOVING_TO_KITCHEN = auto()
    LOADING_FOOD = auto()
    MOVING_TO_DESTINATION = auto()
    UNLOADING_FOOD = auto()
    DONE = auto()


class DeliveryFSM(BaseFSM):
    """
    Handles a single food delivery cycle: travel to kitchen → load food
    → travel to destination → unload. Retries navigation if the destination
    turns out to be wrong (WRONG_DESTINATION).
    """

    def __init__(self) -> None:
        super().__init__(DeliveryState.IDLE)

    # =========================================================================
    # Transition table
    # =========================================================================

    def _handle_event(self, event: Event, payload: dict[str, Any]) -> None:
        s = self._state

        # ── Global: cancellation from any state ───────────────────────────────
        if event is Event.TASK_CANCELLED:
            self.transition(DeliveryState.DONE)
            return

        # ── State-specific transitions ────────────────────────────────────────
        if s is DeliveryState.IDLE:
            if event is Event.TASK_ASSIGNED:
                self.transition(DeliveryState.MOVING_TO_KITCHEN)

        elif s is DeliveryState.MOVING_TO_KITCHEN:
            if event is Event.ARRIVED:
                self.transition(DeliveryState.LOADING_FOOD)

        elif s is DeliveryState.LOADING_FOOD:
            if event is Event.TASK_COMPLETED:
                self.transition(DeliveryState.MOVING_TO_DESTINATION)

        elif s is DeliveryState.MOVING_TO_DESTINATION:
            if event is Event.ARRIVED:
                self.transition(DeliveryState.UNLOADING_FOOD)

        elif s is DeliveryState.UNLOADING_FOOD:
            if event is Event.TASK_COMPLETED:
                self.transition(DeliveryState.DONE)
            elif event is Event.WRONG_DESTINATION:
                self._logger.warning('[DeliveryFSM] Wrong destination — re-requesting navigation.')
                self.transition(DeliveryState.MOVING_TO_DESTINATION)

        # DeliveryState.DONE is terminal — TopFSM detects is_done and resets us.

    # =========================================================================
    # Lifecycle hooks
    # =========================================================================

    def on_enter(self, state: DeliveryState) -> None:
        super().on_enter(state)
        messages = {
            DeliveryState.MOVING_TO_KITCHEN:     '→ Moving to kitchen.',
            DeliveryState.LOADING_FOOD:          '→ Loading food.',
            DeliveryState.MOVING_TO_DESTINATION: '→ Moving to destination.',
            DeliveryState.UNLOADING_FOOD:        '→ Unloading food.',
            DeliveryState.DONE:                  '→ Delivery task complete.',
        }
        if state in messages:
            self._logger.info('[DeliveryFSM] %s', messages[state])

    def on_exit(self, state: DeliveryState) -> None:
        super().on_exit(state)

    # =========================================================================
    # Public interface (used by TopFSM)
    # =========================================================================

    @property
    def is_done(self) -> bool:
        """True when the FSM has reached its terminal DONE state."""
        return self._state is DeliveryState.DONE

    def reset(self) -> None:
        """Return to IDLE for reuse by TopFSM."""
        if self._state is not DeliveryState.IDLE:
            self.on_exit(self._state)
            self._state = DeliveryState.IDLE
            self.on_enter(self._state)
