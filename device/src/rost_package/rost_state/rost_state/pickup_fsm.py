"""
pickup_fsm.py — One-pass dish collection FSM.

Task flow
---------
                  TASK_ASSIGNED
    IDLE ─────────(dish_count)──────────► MOVING_TO_USER
                                                │ ARRIVED
                                                ▼
                                         VERIFYING_USER
                                          │          │
                                USER_CONFIRMED    USER_NOT_MATCH
                                          │          │
                                          ▼          └──► MOVING_TO_USER  (retry)
                                   COLLECTING_ITEMS
                                          │ TASK_COMPLETED
                                          │  → request battery status
                                          ▼
                                WAITING_BATTERY_CHECK
                                          │ BATTERY_STATUS
                                          │
                         battery < 0.2  ──┤
                      OR dish_count ≥ 5   │
                              │           │ else
                              ▼           ▼
                       MOVING_TO_SINK   DONE
                              │ ARRIVED
                              ▼
                       CLEANING_SINK
                              │ TASK_COMPLETED
                              ▼
                            DONE

Any state: TASK_CANCELLED → DONE

Design constraints
------------------
* dish_count is provided once at TASK_ASSIGNED and never changes.
* battery_level is NOT known at task start — it is requested after
  collection completes and arrives via Event.BATTERY_STATUS.
* VERIFYING_USER waits for an explicit USER_CONFIRMED or USER_NOT_MATCH
  event; USER_NOT_MATCH retries navigation (loops back to MOVING_TO_USER).
* Battery is NEVER checked before COLLECTING_ITEMS finishes.
* No loops except the explicit USER_NOT_MATCH retry.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

from .base_fsm import BaseFSM
from .events import Event

# Thresholds for the post-collection routing decision
_BATTERY_LOW_THRESHOLD: float = 0.2   # go to sink if battery ≤ this
_DISH_COUNT_HIGH: int = 5             # go to sink if dishes ≥ this


class PickupState(Enum):
    """Private states of the one-pass dish-collection FSM."""

    IDLE = auto()
    MOVING_TO_USER = auto()
    VERIFYING_USER = auto()
    COLLECTING_ITEMS = auto()
    WAITING_BATTERY_CHECK = auto()
    MOVING_TO_SINK = auto()
    CLEANING_SINK = auto()
    DONE = auto()


class PickupFSM(BaseFSM):
    """
    One-pass dish collection FSM with user verification.

    The robot travels to the user, verifies the requester identity,
    collects all dishes in a single pass, then decides — based on
    battery level and dish count — whether to visit the sink for
    cleaning before finishing.

    USER_NOT_MATCH in VERIFYING_USER sends the robot back to MOVING_TO_USER
    for a retry (re-request loop).

    Internal state
    --------------
    _dish_count    : int           Set from TASK_ASSIGNED payload; never changes.
    _battery_level : float | None  Set from BATTERY_STATUS payload; None until received.

    Usage (from TopFSM)
    -------------------
    fsm.update(Event.TASK_ASSIGNED,  {"task_type": TaskType.PICKUP, "dish_count": 3})
    fsm.update(Event.ARRIVED)
    fsm.update(Event.USER_CONFIRMED)
    fsm.update(Event.TASK_COMPLETED)                     # collection done
    # — node now sends a battery-status request to hardware —
    fsm.update(Event.BATTERY_STATUS, {"battery_level": 0.45})
    fsm.update(Event.ARRIVED)        # only if routed to sink
    fsm.update(Event.TASK_COMPLETED) # only if routed to sink
    """

    def __init__(self) -> None:
        self._dish_count: int = 0
        self._battery_level: float | None = None
        super().__init__(PickupState.IDLE)

    # =========================================================================
    # Transition table
    # =========================================================================

    def _handle_event(self, event: Event, payload: dict[str, Any]) -> None:
        s = self._state

        # ── Global: cancellation from any state ───────────────────────────────
        if event is Event.TASK_CANCELLED:
            self.transition(PickupState.DONE)
            return

        # ── State-specific transitions ────────────────────────────────────────
        if s is PickupState.IDLE:
            if event is Event.TASK_ASSIGNED:
                self._dish_count = int(payload.get('dish_count', 0))
                self.transition(PickupState.MOVING_TO_USER)

        elif s is PickupState.MOVING_TO_USER:
            if event is Event.ARRIVED:
                self.transition(PickupState.VERIFYING_USER)
            elif event is Event.OBSTACLE_DETECTED:
                self._logger.warning('[PickupFSM] Obstacle en route to user — waiting.')
            elif event is Event.TIMEOUT:
                self._logger.warning('[PickupFSM] Navigation to user timed out.')
                self.transition(PickupState.DONE)

        elif s is PickupState.VERIFYING_USER:
            if event is Event.USER_CONFIRMED:
                self._logger.info('[PickupFSM] User confirmed — proceeding to collect.')
                self.transition(PickupState.COLLECTING_ITEMS)
            elif event is Event.USER_NOT_MATCH:
                self._logger.warning(
                    '[PickupFSM] User identity mismatch — retrying navigation (재요청 루프).'
                )
                self.transition(PickupState.MOVING_TO_USER)
            elif event is Event.TIMEOUT:
                self._logger.warning('[PickupFSM] User verification timed out.')
                self.transition(PickupState.DONE)

        elif s is PickupState.COLLECTING_ITEMS:
            if event is Event.TASK_COMPLETED:
                self._logger.info(
                    '[PickupFSM] Collection finished | dishes=%d', self._dish_count
                )
                self.transition(PickupState.WAITING_BATTERY_CHECK)
                # Signal to the external system that we need a battery reading.
                # The ROS2 node observes this state and publishes the request.
                self._request_battery_status()
            elif event is Event.TIMEOUT:
                self._logger.warning('[PickupFSM] Collection timed out.')
                self.transition(PickupState.DONE)

        elif s is PickupState.WAITING_BATTERY_CHECK:
            if event is Event.BATTERY_STATUS:
                self._battery_level = float(payload.get('battery_level', 1.0))
                self._logger.info(
                    '[PickupFSM] Battery received: %.2f', self._battery_level
                )
                self._route_after_collection()
            elif event is Event.TIMEOUT:
                self._logger.warning(
                    '[PickupFSM] Battery status timed out — routing to sink as precaution.'
                )
                self._battery_level = 0.0   # assume worst case
                self._route_after_collection()

        elif s is PickupState.MOVING_TO_SINK:
            if event is Event.ARRIVED:
                self.transition(PickupState.CLEANING_SINK)
            elif event is Event.OBSTACLE_DETECTED:
                self._logger.warning('[PickupFSM] Obstacle en route to sink — waiting.')
            elif event is Event.TIMEOUT:
                self._logger.warning('[PickupFSM] Navigation to sink timed out.')
                self.transition(PickupState.DONE)

        elif s is PickupState.CLEANING_SINK:
            if event is Event.TASK_COMPLETED:
                self.transition(PickupState.DONE)
            elif event is Event.TIMEOUT:
                self._logger.warning('[PickupFSM] Sink cleaning timed out.')
                self.transition(PickupState.DONE)

        # PickupState.DONE is terminal — TopFSM detects is_done and resets.

    # =========================================================================
    # Routing helper
    # =========================================================================

    def _route_after_collection(self) -> None:
        """
        Decide post-collection destination based on battery_level and dish_count.

        Conditions that require a sink visit:
          • battery_level < 0.2  (low battery → clean now before docking)
          • dish_count   ≥ 5     (too many dishes to defer cleaning)

        Otherwise the task ends immediately.
        """
        low_battery = (
            self._battery_level is not None
            and self._battery_level < _BATTERY_LOW_THRESHOLD
        )
        many_dishes = self._dish_count >= _DISH_COUNT_HIGH

        if low_battery or many_dishes:
            reason = []
            if low_battery:
                reason.append(f'low battery ({self._battery_level:.2f})')
            if many_dishes:
                reason.append(f'many dishes ({self._dish_count})')
            self._logger.info(
                '[PickupFSM] → MOVING_TO_SINK (reason: %s)', ', '.join(reason)
            )
            self.transition(PickupState.MOVING_TO_SINK)
        else:
            self._logger.info(
                '[PickupFSM] → DONE (few dishes=%d & sufficient battery=%.2f)',
                self._dish_count,
                self._battery_level if self._battery_level is not None else 1.0,
            )
            self.transition(PickupState.DONE)

    def _request_battery_status(self) -> None:
        """
        Hook called when the FSM enters WAITING_BATTERY_CHECK.

        The default implementation just logs the request. Override this in a
        subclass or connect it to a ROS2 publisher in the node layer by
        observing the WAITING_BATTERY_CHECK state transition.

        The ROS2 node pattern (in fsm_node.py):
            if changed and fsm.sub_state == PickupState.WAITING_BATTERY_CHECK:
                self._battery_request_pub.publish(Empty())
        """
        self._logger.info(
            '[PickupFSM] Requesting battery status from external system.'
        )

    # =========================================================================
    # Lifecycle hooks
    # =========================================================================

    def on_enter(self, state: PickupState) -> None:
        super().on_enter(state)
        messages = {
            PickupState.MOVING_TO_USER:       '→ 수거 요청자 위치 이동.',
            PickupState.VERIFYING_USER:       '→ 수거 요청자 확인.',
            PickupState.COLLECTING_ITEMS:     '→ 그릇 수거.',
            PickupState.WAITING_BATTERY_CHECK: '→ 배터리 상태 대기 중...',
            PickupState.MOVING_TO_SINK:       '→ 설거지장으로 이동.',
            PickupState.CLEANING_SINK:        '→ 설거지 제거 중.',
            PickupState.DONE:                 '→ 수거 종료.',
        }
        if state in messages:
            self._logger.info('[PickupFSM] %s', messages[state])

    def on_exit(self, state: PickupState) -> None:
        super().on_exit(state)

    # =========================================================================
    # Public interface (used by TopFSM)
    # =========================================================================

    @property
    def is_done(self) -> bool:
        """True when the FSM has reached its terminal DONE state."""
        return self._state is PickupState.DONE

    @property
    def dish_count(self) -> int:
        """Number of dishes for the current task (set at TASK_ASSIGNED)."""
        return self._dish_count

    @property
    def battery_level(self) -> float | None:
        """
        Battery level received after collection (0.0 – 1.0).
        None if BATTERY_STATUS has not arrived yet.
        """
        return self._battery_level

    def reset(self) -> None:
        """Return to IDLE and clear per-task state for reuse."""
        if self._state is not PickupState.IDLE:
            self.on_exit(self._state)
            self._state = PickupState.IDLE
            self.on_enter(self._state)
        self._dish_count = 0
        self._battery_level = None
