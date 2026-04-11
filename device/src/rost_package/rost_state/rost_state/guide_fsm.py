"""
guide_fsm.py — Step-based guide FSM with user verification and destination retry.

State diagram
-------------

    IDLE
     │  TASK_ASSIGNED
     ▼
  MOVING_TO_USER
     │  ARRIVED
     ▼
  VERIFYING_USER ──── TASK_COMPLETED ──────────────────► MOVING_TO_DESTINATION
     │  (20 s timer starts on enter)                            │  ARRIVED
     │  TIMEOUT                                                 ▼
     │                                               VERIFYING_DESTINATION
     ▼                                  WRONG_DESTINATION ◄────┤
    DONE ◄──────────────────────────────────────────────────── │ TASK_COMPLETED
                                                                ▼
                                                              DONE

Any state: TASK_CANCELLED → DONE

Design notes
------------
* The 20-second user-verification timer is implemented with threading.Timer.
  The timer callback only sets a boolean flag (_verify_timed_out) which is
  consumed on the next update() call. This keeps all FSM state mutations on
  the caller's thread (safe for single-threaded ROS2 executors).

* The timer is started in on_enter(VERIFYING_USER) and cancelled in
  on_exit(VERIFYING_USER). It never leaks into other states.

* An explicit Event.TIMEOUT is also accepted in VERIFYING_USER for
  deterministic testing without real time delays.

* WRONG_DESTINATION in VERIFYING_DESTINATION loops back to
  MOVING_TO_DESTINATION — the navigation goal is re-sent each time.
"""

from __future__ import annotations

import threading
from enum import Enum, auto
from typing import Any

from .base_fsm import BaseFSM
from .events import Event

# Duration of the user-verification window (seconds).
# Configurable here; kept outside the class so it can be patched in tests.
USER_VERIFY_TIMEOUT_S: float = 20.0


class GuideState(Enum):
    """Private states of the step-based Guide FSM."""

    IDLE = auto()
    MOVING_TO_USER = auto()
    VERIFYING_USER = auto()
    MOVING_TO_DESTINATION = auto()
    VERIFYING_DESTINATION = auto()
    DONE = auto()


class GuideFSM(BaseFSM):
    """
    Step-based guide FSM: navigate to user → verify identity → navigate to
    destination → verify arrival → retry or finish.

    User-verification timeout
    -------------------------
    A threading.Timer is started when VERIFYING_USER is entered.  Its
    callback sets the ``_verify_timed_out`` flag.  The flag is checked at the
    start of every _handle_event call while in VERIFYING_USER, ensuring the
    transition to DONE occurs on the next update() regardless of event type.
    The timer is cancelled (and the flag cleared) in on_exit(VERIFYING_USER)
    so no side-effects escape into other states.

    Destination retry
    -----------------
    VERIFYING_DESTINATION + WRONG_DESTINATION loops back to
    MOVING_TO_DESTINATION unconditionally — there is no retry limit in this
    implementation (add a counter here if needed).
    """

    def __init__(self) -> None:
        # Timer state — must be set before super().__init__() calls on_enter.
        self._verify_timer: threading.Timer | None = None
        self._verify_timed_out: bool = False

        super().__init__(GuideState.IDLE)

    # =========================================================================
    # Transition table
    # =========================================================================

    def _handle_event(self, event: Event, payload: dict[str, Any]) -> None:
        s = self._state

        # ── Global: cancellation from any state ───────────────────────────────
        if event is Event.TASK_CANCELLED:
            self.transition(GuideState.DONE)
            return

        # ── VERIFYING_USER: check timeout flag before processing the event ────
        # The flag is written by the timer thread; reading a bool is atomic in
        # CPython.  We consume it here (on the caller's thread) and transition.
        if s is GuideState.VERIFYING_USER and self._verify_timed_out:
            self._verify_timed_out = False
            self._logger.warning(
                '[GuideFSM] User verification timeout (20s) — aborting guide'
            )
            self.transition(GuideState.DONE)
            return

        # ── State-specific transitions ────────────────────────────────────────
        if s is GuideState.IDLE:
            if event is Event.TASK_ASSIGNED:
                self.transition(GuideState.MOVING_TO_USER)

        elif s is GuideState.MOVING_TO_USER:
            if event is Event.ARRIVED:
                self.transition(GuideState.VERIFYING_USER)
            elif event is Event.OBSTACLE_DETECTED:
                self._logger.warning('[GuideFSM] Obstacle en route to user — waiting.')
            elif event is Event.TIMEOUT:
                self._logger.warning('[GuideFSM] Navigation to user timed out.')
                self.transition(GuideState.DONE)

        elif s is GuideState.VERIFYING_USER:
            if event is Event.TASK_COMPLETED:
                # User confirmed — timer will be cancelled in on_exit.
                self.transition(GuideState.MOVING_TO_DESTINATION)
            elif event is Event.TIMEOUT:
                # Explicit TIMEOUT (e.g. injected by tests without real wait).
                self._logger.warning(
                    '[GuideFSM] User verification timeout (20s) — aborting guide'
                )
                self.transition(GuideState.DONE)

        elif s is GuideState.MOVING_TO_DESTINATION:
            if event is Event.ARRIVED:
                self.transition(GuideState.VERIFYING_DESTINATION)
            elif event is Event.OBSTACLE_DETECTED:
                self._logger.warning('[GuideFSM] Obstacle on route to destination — waiting.')
            elif event is Event.TIMEOUT:
                self._logger.warning('[GuideFSM] Navigation to destination timed out.')
                self.transition(GuideState.DONE)

        elif s is GuideState.VERIFYING_DESTINATION:
            if event is Event.TASK_COMPLETED:
                # Correct destination confirmed.
                self.transition(GuideState.DONE)
            elif event is Event.WRONG_DESTINATION:
                # Wrong location — navigate again.
                self._logger.info('[GuideFSM] Wrong destination — retrying navigation')
                self.transition(GuideState.MOVING_TO_DESTINATION)

        # GuideState.DONE is terminal — TopFSM detects is_done and resets us.

    # =========================================================================
    # Timer management
    # =========================================================================

    def _start_verify_timer(self) -> None:
        """
        Start the 20-second user-verification countdown.

        The callback runs in a daemon thread and only sets a flag — it never
        directly mutates FSM state, avoiding cross-thread data races.
        """
        self._cancel_verify_timer()
        self._verify_timed_out = False

        def _on_timeout() -> None:
            self._verify_timed_out = True
            self._verify_timer = None

        timer = threading.Timer(USER_VERIFY_TIMEOUT_S, _on_timeout)
        timer.daemon = True
        timer.start()
        self._verify_timer = timer
        self._logger.info('[GuideFSM] Verifying user (timeout: 20s)')

    def _cancel_verify_timer(self) -> None:
        """
        Cancel the verification timer and clear all related state.

        Safe to call even if the timer has already fired or was never started.
        """
        if self._verify_timer is not None:
            self._verify_timer.cancel()
            self._verify_timer = None
        self._verify_timed_out = False

    # =========================================================================
    # Lifecycle hooks
    # =========================================================================

    def on_enter(self, state: GuideState) -> None:
        super().on_enter(state)

        messages = {
            GuideState.MOVING_TO_USER:        '→ Moving to guide requester.',
            GuideState.VERIFYING_USER:        '→ Confirming correct user (waiting up to 20s).',
            GuideState.MOVING_TO_DESTINATION: '→ Moving to guide destination.',
            GuideState.VERIFYING_DESTINATION: '→ Checking destination validity.',
            GuideState.DONE:                  '→ Guide task finished.',
        }
        if state in messages:
            self._logger.info('[GuideFSM] %s', messages[state])

        # Start the timer when entering VERIFYING_USER.
        # (_start_verify_timer logs "[GuideFSM] Verifying user (timeout: 20s)")
        if state is GuideState.VERIFYING_USER:
            self._start_verify_timer()

        if state is GuideState.DONE:
            self._logger.info('[GuideFSM] Guide task complete.')

    def on_exit(self, state: GuideState) -> None:
        super().on_exit(state)
        # Cancel the timer unconditionally on exit — harmless for other states.
        if state is GuideState.VERIFYING_USER:
            self._cancel_verify_timer()

    # =========================================================================
    # Public interface (used by TopFSM)
    # =========================================================================

    @property
    def is_done(self) -> bool:
        """True when the FSM has reached its terminal DONE state."""
        return self._state is GuideState.DONE

    def reset(self) -> None:
        """Return to IDLE and cancel any running timer for safe reuse."""
        self._cancel_verify_timer()
        if self._state is not GuideState.IDLE:
            self.on_exit(self._state)
            self._state = GuideState.IDLE
            self.on_enter(self._state)
