#!/usr/bin/env python3
"""One-shot IMU mounting-orientation self-check.

Why this is a standalone script
-------------------------------
The IMU mounting orientation is fixed once the device is installed, so it only needs to be
verified for a short window right after boot, not continuously. Keeping it out of the sensor
driver means the 104 Hz driver hot path stays exactly as upstream (zero added cost), and the
check can simply exit when it is done.

What it does
------------
sensord already rotates the raw IMU axes into the openpilot device frame [forward, right,
down] using the configured IMU_ORIENTATION preset. If that preset is correct, the published
`accelerometer` reading of gravity lands on the +down axis (~+9.81 m/s^2, see the gravity
model in selfdrive/locationd/models/pose_kf.py). This script subscribes to `accelerometer`,
recovers the true gravity direction, and checks which preset it actually corresponds to. The
result (configured vs. detected orientation and whether they match) is written to the
`IMUOrientationCheck` param, which the calibration info in Settings > Device displays. This
keeps the check quiet and non-intrusive: it never interrupts driving, the user just sees the
status next to the other calibration details.

Rejecting disturbances
----------------------
An accelerometer measures gravity's reaction plus the vehicle's own motion. The motion term
(accel / brake / cornering / vibration) is zero-mean over time; gravity is the only
persistent component. Three layers isolate it:
  1. Magnitude gate: only use samples where |a| ~= g, dropping hard-dynamics transients.
  2. Low-pass (EMA): averages the residual zero-mean motion out of the gated stream.
  3. Confirmation: require a sustained, consistent detection before concluding.
"""
import json
import math

import cereal.messaging as messaging
from cereal.services import SERVICE_LIST
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.sensord.orientation import IMU_ORIENTATION, IMU_ORIENTATIONS

GRAVITY = 9.81
PARAM_KEY = "IMUOrientationCheck"


def _matmul_t(a, b):
  # a @ b^T  for 3x3 tuples/lists of rows -> tuple of rows
  return tuple(tuple(sum(a[i][k] * b[j][k] for k in range(3)) for j in range(3)) for i in range(3))



# The configured preset rotates raw -> device. To learn the *true* mounting from a device-frame
# reading we compare that reading against where gravity would sit for each candidate preset,
# expressed relative to the configured one: rel = candidate . configured^-1 (= candidate @ cfg^T).
_CONFIGURED_ROT = IMU_ORIENTATIONS[IMU_ORIENTATION]
_REL_ROTS = {name: _matmul_t(rot, _CONFIGURED_ROT) for name, rot in IMU_ORIENTATIONS.items()}

ACC_NORM_TOL = 1.0                       # keep sample only if | |a| - g | < this (m/s^2)
TAU_S = 10.0                             # low-pass time constant (s of gated data)
MIN_GATED_S = 8.0                        # gated data required before deciding
DOWN_MIN = 9.0                           # gravity projection on down axis to accept a preset
OFF_AXIS_MAX = 2.0                       # other components must stay small
CONFIRM_S = 5.0                          # sustained consistent detection to conclude
STARTUP_WINDOW_S = 180.0                 # give up ~3 min after boot regardless


def detect(g_dev) -> str | None:
  # g_dev is the converged gravity vector in the (configured) device frame. Find the preset
  # whose relative rotation maps it onto +down.
  for name, rel in _REL_ROTS.items():
    fwd = rel[0][0] * g_dev[0] + rel[0][1] * g_dev[1] + rel[0][2] * g_dev[2]
    right = rel[1][0] * g_dev[0] + rel[1][1] * g_dev[1] + rel[1][2] * g_dev[2]
    down = rel[2][0] * g_dev[0] + rel[2][1] * g_dev[1] + rel[2][2] * g_dev[2]
    if down > DOWN_MIN and abs(fwd) < OFF_AXIS_MAX and abs(right) < OFF_AXIS_MAX:
      return name
  return None


def write_result(detected: str | None) -> None:
  # Store the check result for the calibration info UI. status:
  #   "match"    - detected orientation equals the configured one
  #   "mismatch" - detected a different orientation (user should fix mount / IMU_ORIENTATION)
  #   "unknown"  - could not determine within the startup window (not shown as an error)
  if detected is None:
    status = "unknown"
  elif detected == IMU_ORIENTATION:
    status = "match"
  else:
    status = "mismatch"
  result = {"status": status, "configured": IMU_ORIENTATION, "detected": detected}
  Params().put(PARAM_KEY, json.dumps(result))
  cloudlog.warning(f"IMU orientation check: {result}")


def main() -> None:
  freq = SERVICE_LIST['accelerometer'].frequency
  alpha = 1.0 / (TAU_S * freq)
  min_gated = int(MIN_GATED_S * freq)
  confirm_count = int(CONFIRM_S * freq)
  max_seen = int(STARTUP_WINDOW_S * freq)

  sm = messaging.SubMaster(['accelerometer'])
  g_est: list[float] | None = None
  gated = 0
  seen = 0
  streak = 0

  while seen < max_seen:
    sm.update(100)
    if not sm.updated['accelerometer']:
      continue
    seen += 1

    acc = sm['accelerometer'].acceleration
    if not acc.status:
      continue
    v = list(acc.v)

    # Layer 1: magnitude gate.
    if abs(math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) - GRAVITY) > ACC_NORM_TOL:
      continue

    # Layer 2: low-pass toward the steady gravity direction.
    if g_est is None:
      g_est = v[:]
    else:
      g_est[0] += alpha * (v[0] - g_est[0])
      g_est[1] += alpha * (v[1] - g_est[1])
      g_est[2] += alpha * (v[2] - g_est[2])
    gated += 1
    if gated < min_gated:
      continue

    # Layer 3: confirm a consistent detection before concluding.
    detected = detect(g_est)
    if detected is None:
      streak = 0
      continue
    streak += 1
    if streak < confirm_count:
      continue

    write_result(detected)
    return

  # Inconclusive within the startup window (e.g. never got enough steady driving).
  write_result(None)
  cloudlog.info("IMU orientation check inconclusive within startup window; stopping")


if __name__ == "__main__":
  main()
