"""
Copyright (c) 2026, Rick Lan
Copyright (c) 2025-, sunnypilot

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, and/or sublicense,
for non-commercial purposes only, subject to the following conditions:

- The above copyright notice and this permission notice shall be included in
  all copies or substantial portions of the Software.
- Commercial use (e.g. use in a product, service, or activity intended to
  generate revenue) is prohibited without explicit written permission from
  the copyright holder.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

Acceleration Profile Mode (APM) — automatically switches the driving personality to
aggressive when vehicle speed drops below a threshold. This helps maintain a tighter
following distance in stop-and-go traffic to prevent cut-ins.

Once engaged, it stays active until speed exceeds the deactivation threshold
(with hysteresis to prevent rapid toggling).
"""

from cereal import log

from openpilot.common.params import Params

# Speed thresholds (m/s)
APM_ACTIVATE_SPEED_MS = 60.0 * 1000.0 / 3600.0    # ~16.7 m/s — activate aggressive below this
APM_DEACTIVATE_SPEED_MS = 70.0 * 1000.0 / 3600.0  # ~19.4 m/s — restore user personality above this


class APM:
  """Automatically switches personality to aggressive at low speeds."""

  def __init__(self, params=None):
    self._params = params if params is not None else Params()
    self._active = False
    self._enabled = False

  def maybe_refresh(self):
    """Reload the APM toggle state from params."""
    self._enabled = self._params.get_bool("SPAccelProfileModeEnabled")

  def get_personality(self, v_ego, personality):
    """Override personality if APM is active.

    Args:
      v_ego: Current vehicle speed in m/s.
      personality: The user's selected personality.

    Returns:
      Aggressive personality if APM is active, otherwise the original personality.
    """
    if not self._enabled:
      return personality

    # Hysteresis to prevent rapid toggling
    if self._active:
      if v_ego > APM_DEACTIVATE_SPEED_MS:
        self._active = False
    else:
      if v_ego < APM_ACTIVATE_SPEED_MS:
        self._active = True

    if self._active:
      return log.LongitudinalPersonality.aggressive
    return personality
