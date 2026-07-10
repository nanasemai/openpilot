"""
Copyright (c) 2021-, Rick Lan, dragonpilot community, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

AccelLogger (adapted from dragonpilot):
Logs the driver's natural acceleration — clean, free, straight-line manual
samples — to a CSV (columns: vEgo m/s, aEgo m/s²). Samples are buffered in RAM
and appended once a minute to spare the flash; up to FLUSH_DT of samples are
lost on an ungraceful shutdown, which is negligible for an aggregate.

The file is byte-capped: once it exceeds MAX_BYTES the previous copy is rotated
to LOG_PATH + ".1" (overwriting the older rotation) before appending continues.
Without this the file grows for the lifetime of the card and is shipped wholesale
by system/usb_mount.py:export_realdata, which copies all of /data/media/0/realdata.

Fully exception-isolated — it can never perturb the planner.
"""

from cereal import car
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_MDL
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
import os

V_MIN = 1.0          # m/s — exclude creep/stop
TTC_MIN = 0.5        # s   — lead must be at least this far in time
LAT_ACCEL_MAX = 1.0  # m/s² — exclude curves
FLUSH_DT = 60.0      # s   — append the buffer to disk at most this often
MAX_BYTES = 50 * 1024 * 1024   # rotate the csv once it grows past this

LOG_PATH = "/data/media/0/realdata/accel_log.csv"


def _should_log(long_off, gas, brake, blinker, in_drive, moving, a_ego, lead_ttc, lat_accel):
  """True only for a clean, free, straight-line human-acceleration sample."""
  return (long_off and gas and a_ego > 0.0
          and not brake and not blinker
          and in_drive and moving
          and lead_ttc > TTC_MIN and lat_accel < LAT_ACCEL_MAX)


class AccelLogger:
  def __init__(self, CP, path=None):
    self._CP = CP
    self._path = path if path is not None else LOG_PATH
    self._buf = []
    self._frames = 0
    self._flush_every = max(1, int(FLUSH_DT / DT_MDL))

  def _flush(self):
    rows, self._buf = self._buf, []
    try:
      log_dir = os.path.dirname(self._path)
      if not os.path.isdir(log_dir) or not os.access(log_dir, os.W_OK):
        return  # 静默跳过，不输出日志
      # Bound the file on the card. .1 is overwritten on every rotation, so the
      # pair never exceeds 2 * MAX_BYTES. Renaming rather than truncating keeps
      # the most recent MAX_BYTES in both copies for offline analysis.
      try:
        if os.path.getsize(self._path) > MAX_BYTES:
          os.replace(self._path, self._path + ".1")
      except FileNotFoundError:
        pass
      with open(self._path, "a") as f:
        f.writelines(f"{v:.3f},{a:.3f}\n" for v, a in rows)
    except Exception as e:
      cloudlog.warning(f"AccelLogger: write failed (dropped {len(rows)} rows): {e}")

  def update(self, sm):
    try:
      self._frames += 1
      cs = sm['carState']
      v_ego = cs.vEgo
      long_off = sm['controlsState'].longControlState == LongCtrlState.off
      in_drive = cs.gearShifter == car.CarState.GearShifter.drive
      moving = (not cs.standstill) and v_ego > V_MIN
      blinker = cs.leftBlinker or cs.rightBlinker
      # Subtract the calibrated wheel-angle offset: it is a static bias that
      # would otherwise make every sample look like it is being taken in a curve,
      # and it can never be negative inside abs(). Matches the same estimate in
      # longitudinal_planner.py:126 (limit_accel_in_turns) and controlsd.py:91.
      steer_angle_without_offset = cs.steeringAngleDeg - sm['liveParameters'].angleOffsetDeg
      lat_accel = abs(v_ego ** 2 * steer_angle_without_offset * CV.DEG_TO_RAD
                      / (self._CP.steerRatio * self._CP.wheelbase))
      lead = sm['radarState'].leadOne
      lead_ttc = (lead.dRel / max(v_ego, 0.1)) if lead.status else float('inf')

      if _should_log(long_off, cs.gasPressed, cs.brakePressed,
                     blinker, in_drive, moving, cs.aEgo, lead_ttc, lat_accel):
        self._buf.append((v_ego, cs.aEgo))

      if self._buf and self._frames % self._flush_every == 0:
        self._flush()
    except Exception as e:
      cloudlog.warning(f"AccelLogger.update failed (ignored): {e}")
