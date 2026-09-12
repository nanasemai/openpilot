import os
import time
from enum import Enum, auto

from openpilot.common.params import Params


# --- System and Safety Constants ---
LOG_PATH = "/data/media/0/realdata/debug.log"
PARAM_REFRESH_SEC = 2.0
MIN_SPEED_MS = 0.1
# [Safety Lock 4] Maximum speed limit, ~35 km/h.
# Above this speed, a 90-degree turn is dangerous; HTD refuses to act.
MAX_SPEED_MS = 9.72


def _log(message: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f} {message}\n")
    except Exception:
        pass


class HTDState(Enum):
    INACTIVE = auto()
    MANUAL_TURN = auto()
    RAMPING = auto()


class HumanTurnDetection:
    def __init__(self) -> None:
        self._params = Params()
        self._last_params_read = 0.0

        # --- 1. UI Control Parameters (read from Params) ---
        self._enabled = False
        self._angle_threshold_deg = 60.0

        # --- 2. Built-in System Parameters (not from Params) ---
        self._angle_release_deg = 20.0
        self._torque_start_nm = 2.0
        self._torque_release_nm = 0.6
        # Safety angle lock: used only for soft resume priority, not a hard block
        self._resume_angle_lock_deg = 40.0
        # Max additional wait before forced resume when driver still holds wheel
        self._ramping_max_multiplier = 2.0

        # --- 3. State and Timers ---
        self._state: HTDState = HTDState.INACTIVE
        self._state_change_time = 0.0
        self._trigger_start_time = 0.0

        # --- 4. Vehicle Dynamic Data Cache ---
        self._last_angle_raw = 0.0
        self._last_torque_raw = 0.0
        self._last_angle = 0.0
        self._last_torque = 0.0
        self._last_pressed = False

        # --- 5. Runtime Temporary Variables ---
        self._max_turn_angle = 0.0
        self._dynamic_delay = 0.5

    def _read_params(self) -> None:
        """Periodically update external configuration parameters."""
        now = time.monotonic()
        if now - self._last_params_read < PARAM_REFRESH_SEC:
            return

        self._last_params_read = now
        self._enabled = self._params.get_bool("dp_htd_enabled")
        self._angle_threshold_deg = self._get_float("dp_htd_turn_angle_threshold", 60.0)

    def _transition(self, new_state: HTDState, reason: str) -> None:
        """Handle state transitions and log them."""
        if new_state == self._state:
            return

        self._state = new_state
        self._state_change_time = time.monotonic()
        _log(
            f"HTD {new_state.name} reason={reason} angle={self._last_angle:.1f} "
            f"torque={self._last_torque:.2f} pressed={self._last_pressed} delay={self._dynamic_delay:.2f}"
        )

    def update(
        self,
        lat_active: bool,
        cruise_enabled: bool,
        steering_angle_deg: float,
        steering_torque_nm: float,
        v_ego: float,
        steering_pressed: bool = False,
    ) -> tuple[bool, HTDState]:

        self._read_params()

        # --- Update vehicle dynamic data ---
        self._last_angle_raw = steering_angle_deg
        self._last_torque_raw = steering_torque_nm
        self._last_angle = abs(steering_angle_deg)
        self._last_torque = abs(steering_torque_nm)
        self._last_pressed = steering_pressed

        # --- Guard Clauses ---
        # Skip lat_active check when HTD is already in an active state to avoid
        # feedback loop: HTD disables lat -> get_lat_active() returns False ->
        # guard clause fires -> HTD resets but lat still disabled.
        if self._state in (HTDState.MANUAL_TURN, HTDState.RAMPING):
            is_invalid_condition = (
                not self._enabled or
                cruise_enabled or
                not (MIN_SPEED_MS <= v_ego <= MAX_SPEED_MS)
            )
        else:
            is_invalid_condition = (
                not self._enabled or
                cruise_enabled or
                not lat_active or
                not (MIN_SPEED_MS <= v_ego <= MAX_SPEED_MS)
            )

        if is_invalid_condition:
            if self._state != HTDState.INACTIVE:
                self._transition(HTDState.INACTIVE, "disabled_or_invalid_condition")
            self._trigger_start_time = 0.0
            return True, self._state

        # --- State Machine Logic ---
        if self._state == HTDState.INACTIVE:
            if self._should_trigger():
                self._max_turn_angle = self._last_angle
                self._transition(HTDState.MANUAL_TURN, "trigger")
                return False, self._state

        elif self._state == HTDState.MANUAL_TURN:
            self._max_turn_angle = max(self._max_turn_angle, self._last_angle)
            if self._should_release():
                # Calculate dynamic delay (0.5 ~ 1.0 seconds)
                calculated_delay = self._max_turn_angle / 270.0
                self._dynamic_delay = max(0.5, min(calculated_delay, 1.0))
                self._transition(HTDState.RAMPING, "release")
            return False, self._state

        elif self._state == HTDState.RAMPING:
            # retrigger check at top of RAMPING
            if self._should_trigger():
                self._trigger_start_time = 0.0
                self._transition(HTDState.MANUAL_TURN, "retrigger")
                return False, self._state

            elapsed = time.monotonic() - self._state_change_time
            if elapsed >= self._dynamic_delay:
                # Driver released wheel -> resume immediately regardless of angle
                if not self._last_pressed or self._last_angle <= self._resume_angle_lock_deg:
                    self._max_turn_angle = 0.0
                    self._transition(HTDState.INACTIVE, "resume")
                    return True, self._state

                # Driver still holding wheel and angle high -> wait one more
                # dynamic_delay cycle, then force resume to avoid indefinite lock
                if elapsed >= self._dynamic_delay * self._ramping_max_multiplier:
                    self._max_turn_angle = 0.0
                    self._transition(HTDState.INACTIVE, "resume_forced")
                    return True, self._state

            return False, self._state

        # Default (should never reach here)
        return True, self._state

    def _should_trigger(self) -> bool:
        """Determine whether to trigger manual turn state."""
        direction_match = (self._last_angle_raw * self._last_torque_raw) > 0
        condition_met = (
            self._last_pressed
            and direction_match
            and self._last_torque >= self._torque_start_nm
            and self._last_angle >= self._angle_threshold_deg
        )

        if condition_met:
            if self._trigger_start_time == 0.0:
                self._trigger_start_time = time.monotonic()
            elif time.monotonic() - self._trigger_start_time >= 0.1:
                return True
        else:
            self._trigger_start_time = 0.0

        return False

    def _should_release(self) -> bool:
        """Determine whether to release manual turn state."""
        # Path A: Steering wheel returned and torque near zero
        perfect_return = (
            self._last_torque <= self._torque_release_nm
            and self._last_angle <= self._angle_release_deg
        )
        # Path B: Driver released the steering wheel
        hands_off = not self._last_pressed

        release_condition = perfect_return or hands_off

        if release_condition:
            self._trigger_start_time = 0.0

        return release_condition

    def _get_float(self, key: str, default: float) -> float:
        """Safely get a float from Params."""
        try:
            val = self._params.get(key)
            return float(val) if val is not None else default
        except Exception:
            return default

    @property
    def enabled(self) -> bool:
        return self._enabled
