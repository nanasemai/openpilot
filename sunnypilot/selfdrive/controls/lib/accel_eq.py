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
"""

import os

import numpy as np

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from opendbc.car.interfaces import ACCEL_MAX

PRESETS_KEY = "SPAccelProfile"
PROFILES_KEY = "SPAccelProfiles"

# Preset ID -> name mapping (INT params for UI compatibility)
PRESET_IDS = {
  0: "standard",
  1: "eco",
  2: "sport",
  3: "comfort",
  4: "custom",
}

DEFAULT_PRESET_ID = 0
STOCK_NAME = "standard"

# Built-in presets: {name: {bp (speed breakpoints m/s), v (max accel m/s^2)}}
ACCEL_PRESETS = {
  "standard": {
    "bp": [0., 10.0, 25., 40.],
    "v": [1.6, 1.2, 0.8, 0.6],
  },
  "eco": {
    "bp": [0., 10.0, 25., 40.],
    "v": [1.2, 0.9, 0.6, 0.4],
  },
  "sport": {
    "bp": [0., 10.0, 25., 40.],
    "v": [2.0, 1.6, 1.2, 0.9],
  },
  "comfort": {
    "bp": [0., 10.0, 25., 40.],
    "v": [1.4, 1.1, 0.7, 0.5],
  },
}

# "custom" (id=4) reads from the SPAccelProfiles JSON param

SPEED_CEIL = 60.0
MIN_GAP = 0.5
MIN_PTS = 2
MAX_PTS = 12
MAX_ACCEL_CEIL = ACCEL_MAX


def _validate_curve(curve, ceil):
  """Return a sorted, clamped (bp, v) tuple, or None if unusable."""
  if not isinstance(curve, dict):
    return None
  bp, v = curve.get("bp"), curve.get("v")
  if not isinstance(bp, list) or not isinstance(v, list):
    return None
  if len(bp) != len(v) or not (MIN_PTS <= len(bp) <= MAX_PTS):
    return None
  try:
    pairs = sorted(((float(b), float(a)) for b, a in zip(bp, v, strict=True)), key=lambda p: p[0])
  except (TypeError, ValueError):
    return None
  if not all(np.isfinite(b) and np.isfinite(a) for b, a in pairs):
    return None
  out_bp, out_v = [], []
  for b, a in pairs:
    b = min(max(b, 0.0), SPEED_CEIL)
    if out_bp and b - out_bp[-1] < MIN_GAP:
      return None
    out_bp.append(b)
    out_v.append(min(max(a, 0.0), ceil))
  return out_bp, out_v


class AccelEq:
  def __init__(self, stock_bp, stock_v, params=None):
    self._stock_bp, self._stock_v = list(stock_bp), list(stock_v)
    self._params = params if params is not None else Params()
    self._last_preset_id = None
    self._last_mtime_profile = None
    self._custom_doc = None
    self._max_bp, self._max_v = list(stock_bp), list(stock_v)

  def _mtime(self, key):
    try:
      return os.stat(self._params.get_param_path(key)).st_mtime
    except OSError:
      return None

  def _preset_id_to_name(self, preset_id):
    return PRESET_IDS.get(preset_id, STOCK_NAME)

  def maybe_refresh(self):
    """Check for param changes and update the active curve if needed."""
    raw = self._params.get(PRESETS_KEY, return_default=True)
    try:
      preset_id = int(raw)
    except (TypeError, ValueError):
      preset_id = DEFAULT_PRESET_ID

    changed = preset_id != self._last_preset_id
    self._last_preset_id = preset_id

    preset_name = self._preset_id_to_name(preset_id)

    if preset_name == "custom":
      mtime = self._mtime(PROFILES_KEY)
      profile_changed = mtime != self._last_mtime_profile
      self._last_mtime_profile = mtime
      if changed or profile_changed:
        self._reload_custom()
    elif changed:
      self._apply_preset(preset_name)

  def _apply_preset(self, name):
    """Apply a built-in preset curve."""
    preset = ACCEL_PRESETS.get(name)
    if preset is not None:
      self._max_bp, self._max_v = list(preset["bp"]), list(preset["v"])
    else:
      cloudlog.warning(f"AccelEq: unknown preset '{name}', falling back to stock")
      self._max_bp, self._max_v = list(self._stock_bp), list(self._stock_v)

  def _reload_custom(self):
    """Read and parse the custom JSON profile."""
    try:
      raw = self._params.get(PROFILES_KEY)
      if raw:
        import json
        data = json.loads(raw)
        mc = _validate_curve(data.get("max") if isinstance(data, dict) else data, MAX_ACCEL_CEIL)
        if mc is not None:
          self._max_bp, self._max_v = mc
          return
        cloudlog.warning("AccelEq: invalid custom profile")
    except Exception as e:
      cloudlog.warning(f"AccelEq: failed to read custom profile, using stock: {e}")
    self._max_bp, self._max_v = list(self._stock_bp), list(self._stock_v)

  def max_accel(self, v_ego):
    return float(np.interp(v_ego, self._max_bp, self._max_v))

  @property
  def active_preset_name(self):
    return self._preset_id_to_name(self._last_preset_id) if self._last_preset_id is not None else STOCK_NAME
