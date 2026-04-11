"""
top_fsm.py — Supervisor FSM (TopFSM).

Responsibilities
----------------
1. Own the global robot state (TopState).
2. Instantiate and own all Sub FSMs.
3. Activate the correct Sub FSM based on the incoming task type.
4. Ensure only ONE Sub FSM is running at a time.
5. Enforce the three-zone battery policy (see below).
6. Queue incoming TASK_ASSIGNED events that arrive during CHARGING when
   the battery is below the resume threshold.
7. Delegate events to the active Sub FSM.
8. Detect Sub FSM completion (is_done) and return to MOVE_TO_WAITING.

Battery policy (three zones)
-----------------------------
CRITICAL  battery < BATT_CRITICAL (20 %)
    Immediately interrupts any running task and forces CHARGING.
    No tasks are started or queued until the battery rises.

LOW       BATT_CRITICAL ≤ battery < BATT_RESUME (60 %)
    While in CHARGING: tasks are queued but NOT executed.
    While running a task: the task continues (it was started at a higher
    level; CRITICAL preemption is the only forced stop).

NORMAL    battery ≥ BATT_RESUME (60 %)
    Full task execution. If in CHARGING and tasks are queued, the FSM
    leaves charging and starts the next task immediately.
    If in CHARGING with no tasks and battery ≥ BATT_IDLE (80 %),
    the FSM exits charging and transitions to IDLE.

State transitions driven by battery
------------------------------------
ANY_STATE          → CHARGING        battery drops below BATT_CRITICAL
CHARGING           → <task state>    battery ≥ BATT_RESUME AND task queued
CHARGING           → IDLE            battery ≥ BATT_IDLE   AND no tasks
<task state>       → CHARGING        battery drops below BATT_CRITICAL
                                      (handled as an override in _handle_event)

Architecture
------------
                    ┌─────────────────────────────────────────────┐
 External events ──►│                  TopFSM                     │
                    │  state: TopState  (CHARGING / IDLE / …)     │
                    │                                             │
                    │  _active_sub ──► DeliveryFSM  ◄── events   │
                    │              or  PickupFSM                  │
                    │              or  FollowFSM                  │
                    │              or  GuideFSM                   │
                    └─────────────────────────────────────────────┘

TopFSM does NOT inherit from BaseFSM because it orchestrates Sub FSMs
rather than being a peer FSM. It exposes the same update() interface so
the ROS2 node can call it uniformly.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from .delivery_fsm import DeliveryFSM
from .events import Event, TaskType
from .follow_fsm import FollowFSM
from .guide_fsm import GuideFSM
from .pickup_fsm import PickupFSM
from .states import TopState

logger = logging.getLogger(__name__)

# ── Battery thresholds (0–100 scale) — edit here to tune policy ──────────────
# Force CHARGING from any state when battery falls below this.
BATT_CRITICAL: float = 20.0

# While in CHARGING, accept and start queued tasks once battery reaches this.
# Also: a new TASK_ASSIGNED during CHARGING is started immediately (not queued)
# when the current battery level is at or above this threshold.
BATT_RESUME: float = 60.0

# While in CHARGING with NO pending tasks, exit to IDLE once battery reaches this.
# (Opportunistic charging: charge up to 80 % when idle, then stop.)
BATT_IDLE: float = 80.0

# Map TopState → Sub FSM class for clean lookup
_TASK_STATE_TO_FSM: dict[TopState, type] = {
    TopState.DELIVERY: DeliveryFSM,
    TopState.PICKUP:   PickupFSM,
    TopState.FOLLOW:   FollowFSM,
    TopState.GUIDE:    GuideFSM,
}

# Map TaskType enum → TopState
_TASK_TYPE_TO_STATE: dict[TaskType, TopState] = {
    TaskType.DELIVERY: TopState.DELIVERY,
    TaskType.PICKUP:   TopState.PICKUP,
    TaskType.FOLLOW:   TopState.FOLLOW,
    TaskType.GUIDE:    TopState.GUIDE,
}


class TopFSM:
    """
    Supervisor FSM — the single entry point for all external events.

    Usage
    -----
    top = TopFSM(initial_state=TopState.IDLE)
    top.set_battery(75.0)
    top.update(Event.TASK_ASSIGNED, {"task_type": TaskType.DELIVERY})
    top.update(Event.ARRIVED)
    ...
    print(top.state)          # TopState.DELIVERY
    print(top.sub_state)      # DeliveryState.MOVING_TO_DROP  (or None)
    """

    def __init__(self, initial_state: TopState = TopState.IDLE) -> None:
        self._state: TopState = initial_state
        self._battery: float = 100.0

        # Active Sub FSM — None when no task is running
        self._active_sub: DeliveryFSM | PickupFSM | FollowFSM | GuideFSM | None = None

        # Task queue — stores (task_type, payload) tuples received during CHARGING
        self._task_queue: deque[tuple[TaskType, dict]] = deque()

        # Pre-instantiated Sub FSMs (one per type, reused via reset())
        self._sub_fsms: dict[TopState, Any] = {
            TopState.DELIVERY: DeliveryFSM(),
            TopState.PICKUP:   PickupFSM(),
            TopState.FOLLOW:   FollowFSM(),
            TopState.GUIDE:    GuideFSM(),
        }

        logger.info('[TopFSM] Initialised in state %s', self._state.name)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> TopState:
        """Current top-level state."""
        return self._state

    @property
    def sub_state(self):
        """Current state of the active Sub FSM, or None if no Sub FSM is running."""
        return self._active_sub.state if self._active_sub else None

    @property
    def battery(self) -> float:
        return self._battery

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_battery(self, level: float) -> None:
        """
        Update the cached battery level and apply the battery policy.

        Call this from the ROS2 node whenever a new battery reading arrives
        (e.g., from /battery_state).  All threshold logic is centralised in
        ``_evaluate_battery_policy()`` — do not add inline conditions here.
        """
        self._battery = max(0.0, min(100.0, level))
        self._evaluate_battery_policy()

    def _evaluate_battery_policy(self) -> None:
        """
        Central battery-policy enforcement. Called every time the battery
        level changes (via set_battery).

        Three-zone logic
        ----------------
        CRITICAL  (< BATT_CRITICAL = 20 %)
            Force CHARGING from any state, deactivating any running Sub FSM.

        LOW  (BATT_CRITICAL ≤ battery < BATT_RESUME = 60 %)
            No automatic state changes.  Tasks already running continue;
            incoming tasks are queued inside _handle_charging().

        NORMAL  (battery ≥ BATT_RESUME = 60 %)
            If currently CHARGING AND tasks are queued → start the first task.
            If currently CHARGING AND no tasks AND battery ≥ BATT_IDLE (80 %)
              → opportunistic charge complete, transition to IDLE.
        """
        bat = self._battery
        s = self._state

        # ── CRITICAL: force charging from any non-charging state ──────────────
        if bat < BATT_CRITICAL and s is not TopState.CHARGING:
            logger.warning(
                '[TopFSM] CRITICAL battery (%.1f %%) — interrupting %s → CHARGING.',
                bat, s.name,
            )
            self._deactivate_sub()
            self._transition(TopState.CHARGING)
            return

        # ── NORMAL zone, currently charging: decide whether to exit ───────────
        if s is not TopState.CHARGING:
            return  # nothing to do outside CHARGING in the normal zone

        if bat >= BATT_RESUME and self._task_queue:
            # Battery sufficient and work is waiting — leave charger, run task.
            logger.info(
                '[TopFSM] Battery at %.1f %% (≥ RESUME %.0f %%) with queued tasks'
                ' — leaving CHARGING to start task.',
                bat, BATT_RESUME,
            )
            self._drain_task_queue()

        elif bat >= BATT_IDLE and not self._task_queue:
            # Opportunistic charge complete, nothing to do — go idle.
            logger.info(
                '[TopFSM] Battery at %.1f %% (≥ IDLE %.0f %%), no pending tasks'
                ' — leaving CHARGING → IDLE.',
                bat, BATT_IDLE,
            )
            self._transition(TopState.IDLE)

    def update(self, event: Event, payload: dict[str, Any] | None = None) -> bool:
        """
        Feed an event into the supervisor.

        Returns True if the top-level state changed.
        """
        payload = payload or {}
        prev = self._state

        self._handle_event(event, payload)

        # After delegating to sub FSM, check if it reached its terminal state.
        self._check_sub_completion()

        return self._state is not prev

    # ------------------------------------------------------------------
    # Internal event dispatch
    # ------------------------------------------------------------------

    def _handle_event(self, event: Event, payload: dict[str, Any]) -> None:
        """
        Route the event to the state-specific handler.

        Battery-level transitions are handled exclusively by
        _evaluate_battery_policy() (called from set_battery()).
        Event-based BATTERY_LOW / BATTERY_OK signals from external sources
        (e.g. a ROS topic) are still accepted for compatibility but the
        canonical path is through set_battery().
        """
        s = self._state

        # ── External BATTERY_LOW event (e.g. from /fsm/event topic) ──────────
        # Mirrors what _evaluate_battery_policy does for the CRITICAL zone so
        # that event-driven and polling-driven callers behave identically.
        if event is Event.BATTERY_LOW and s is not TopState.CHARGING:
            logger.warning(
                '[TopFSM] BATTERY_LOW event received (%.1f %%) — interrupting %s → CHARGING.',
                self._battery, s.name,
            )
            self._deactivate_sub()
            self._transition(TopState.CHARGING)
            return

        # ── State-specific dispatch ───────────────────────────────────────────
        if s is TopState.CHARGING:
            self._handle_charging(event, payload)

        elif s is TopState.MOVE_TO_WAITING:
            self._handle_move_to_waiting(event, payload)

        elif s is TopState.IDLE:
            self._handle_idle(event, payload)

        elif s in _TASK_STATE_TO_FSM:
            self._handle_task_state(event, payload)

    def _handle_charging(self, event: Event, payload: dict) -> None:
        """
        Handle events while in CHARGING state.

        TASK_ASSIGNED
            battery ≥ BATT_RESUME (60 %) → start task immediately (leave charger)
            battery <  BATT_RESUME        → queue task for later

        BATTERY_OK  (external event, for compatibility)
            Treated as a hint that charging is sufficient.
            The canonical exit is driven by _evaluate_battery_policy().
        """
        if event is Event.BATTERY_OK:
            # External hint — re-run policy evaluation to decide what to do.
            self._evaluate_battery_policy()

        elif event is Event.TASK_ASSIGNED:
            task_type = payload.get('task_type')
            if not task_type:
                return

            if self._battery >= BATT_RESUME:
                # Sufficient battery — leave charger and start the task now.
                logger.info(
                    '[TopFSM] Charging (%.1f %% ≥ RESUME %.0f %%) — starting %s task immediately.',
                    self._battery, BATT_RESUME, task_type.name,
                )
                self._start_task_from_payload(payload)
            else:
                # Battery too low — queue and wait for BATT_RESUME.
                logger.info(
                    '[TopFSM] Charging (%.1f %% < RESUME %.0f %%) — queuing %s task.',
                    self._battery, BATT_RESUME, task_type.name,
                )
                self._task_queue.append((task_type, payload))

    def _handle_move_to_waiting(self, event: Event, payload: dict) -> None:
        if event is Event.ARRIVED:
            self._transition(TopState.IDLE)
            # Drain the task queue now that we're back at the waiting position.
            self._drain_task_queue()
        elif event is Event.TASK_ASSIGNED:
            # Redirect to IDLE handler — accept the task immediately.
            self._start_task_from_payload(payload)

    def _handle_idle(self, event: Event, payload: dict) -> None:
        if event is Event.TASK_ASSIGNED:
            self._start_task_from_payload(payload)

    def _handle_task_state(self, event: Event, payload: dict) -> None:
        """Delegate the event to the active Sub FSM."""
        if self._active_sub is not None:
            self._active_sub.update(event, payload)
        # Task cancellation is handled inside the Sub FSM (→ DONE).
        # _check_sub_completion() will catch is_done and clean up.

    # ------------------------------------------------------------------
    # Sub FSM management
    # ------------------------------------------------------------------

    def _start_task_from_payload(self, payload: dict) -> None:
        """Activate the Sub FSM matching the task_type in the payload."""
        task_type: TaskType | None = payload.get('task_type')
        if task_type is None:
            logger.warning('[TopFSM] TASK_ASSIGNED received with no task_type — ignored.')
            return

        top_state = _TASK_TYPE_TO_STATE.get(task_type)
        if top_state is None:
            logger.error('[TopFSM] Unknown task_type %s — ignored.', task_type)
            return

        self._activate_sub(top_state, payload)

    def _activate_sub(self, top_state: TopState, payload: dict) -> None:
        """Reset and activate the Sub FSM for the given top_state."""
        self._deactivate_sub()

        sub = self._sub_fsms[top_state]
        sub.reset()
        self._active_sub = sub
        self._transition(top_state)

        # Immediately send TASK_ASSIGNED to the Sub FSM so it starts.
        self._active_sub.update(Event.TASK_ASSIGNED, payload)
        logger.info('[TopFSM] %s Sub FSM activated.', top_state.name)

    def _deactivate_sub(self) -> None:
        """Stop and discard the currently active Sub FSM (if any)."""
        if self._active_sub is not None:
            logger.info(
                '[TopFSM] Deactivating %s Sub FSM.',
                type(self._active_sub).__name__,
            )
            self._active_sub = None

    def _check_sub_completion(self) -> None:
        """
        If the active Sub FSM has reached its terminal (DONE) state, deactivate
        it and choose the next top-level state based on current battery level.

        battery < BATT_CRITICAL → CHARGING  (critical: dock immediately)
        otherwise               → MOVE_TO_WAITING  (normal task-complete flow)
        """
        if self._active_sub is None or not self._active_sub.is_done:
            return

        sub_name = type(self._active_sub).__name__
        self._deactivate_sub()

        if self._battery < BATT_CRITICAL:
            logger.warning(
                '[TopFSM] %s finished but battery critical (%.1f %%) → CHARGING.',
                sub_name, self._battery,
            )
            self._transition(TopState.CHARGING)
        else:
            logger.info('[TopFSM] %s finished → MOVE_TO_WAITING.', sub_name)
            self._transition(TopState.MOVE_TO_WAITING)

    def _drain_task_queue(self) -> None:
        """Process the first queued task (FIFO) after returning to IDLE."""
        if self._task_queue:
            task_type, payload = self._task_queue.popleft()
            logger.info(
                '[TopFSM] Draining task queue — starting queued %s task.',
                task_type.name,
            )
            self._start_task_from_payload(payload)

    # ------------------------------------------------------------------
    # State transition
    # ------------------------------------------------------------------

    def _transition(self, new_state: TopState) -> None:
        if new_state is self._state:
            return
        logger.info(
            '[TopFSM] %s → %s', self._state.name, new_state.name
        )
        self._state = new_state

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return a snapshot of the current FSM status for logging / publishing."""
        bat = self._battery
        if bat < BATT_CRITICAL:
            zone = 'CRITICAL'
        elif bat < BATT_RESUME:
            zone = 'LOW'
        else:
            zone = 'NORMAL'

        return {
            'top_state':    self._state.name,
            'sub_state':    self._active_sub.state.name if self._active_sub else None,
            'sub_fsm':      type(self._active_sub).__name__ if self._active_sub else None,
            'battery':      round(bat, 1),
            'battery_zone': zone,
            'queued_tasks': len(self._task_queue),
        }

    def __repr__(self) -> str:
        return (
            f'TopFSM(state={self._state.name}, '
            f'sub={type(self._active_sub).__name__ if self._active_sub else "None"}, '
            f'battery={self._battery:.0f}%)'
        )
