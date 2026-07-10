"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from cereal import car

from openpilot.common.params import Params

AudibleAlert = car.CarControl.HUDControl.AudibleAlert

# Alerts muted in "Warnings Only" mode (aligned with dragonpilot: only engage/disengage are silenced)
QUIET_MODE_MUTED = {
  AudibleAlert.engage,
  AudibleAlert.disengage,
}

# Audible Alert Mode (adapted from dragonpilot)
# 0 = Standard (all sounds)
# 1 = Warnings Only (no engage/disengage, warnings still play)
# 2 = Muted (no sounds at all)


class QuietMode:
  def __init__(self):
    self.params = Params()
    self._audible_alert_mode: int = 0
    self._frame = 0
    self._load_initial()

  def _load_initial(self):
    # Try the new AudibleAlertMode param first
    val = self.params.get("AudibleAlertMode")
    if val is not None:
      self._audible_alert_mode = int(val)
    else:
      # Backward compat: fall back to old QuietMode bool
      self._audible_alert_mode = 1 if self.params.get_bool("QuietMode") else 0

  def load_param(self) -> None:
    self._frame += 1
    if self._frame % 50 == 0:  # 2.5 seconds
      val = self.params.get("AudibleAlertMode")
      if val is not None:
        self._audible_alert_mode = int(val)
      else:
        self._audible_alert_mode = 1 if self.params.get_bool("QuietMode") else 0

  def should_play_sound(self, current_alert: int) -> bool:
    """
    Check if a sound should be played based on the Audible Alert Mode setting
    and the current alert.

    0 = Standard — play all sounds
    1 = Warnings Only — play all sounds except engage/disengage
    2 = Muted — no sounds at all
    """
    if current_alert == AudibleAlert.none:
      return False

    if self._audible_alert_mode == 2:
      return False

    if self._audible_alert_mode == 1:
      return current_alert not in QUIET_MODE_MUTED

    # Mode 0: standard
    return True
