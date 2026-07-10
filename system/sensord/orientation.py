import os

from openpilot.common.swaglog import cloudlog

# Maps the raw IMU chip axes (x, y, z) to the openpilot device frame (forward, right, down).
# Each 3x3 matrix left-multiplies the raw [x, y, z] vector. All entries are 0/±1, so every
# preset is a pure rotation (signed axis permutation, determinant +1).
#
# The device frame is defined by the *camera* (forward-facing), not the IMU, so it does not
# change when you remount the device as long as the camera still points forward. Only the
# physical orientation of the IMU chip relative to that frame changes, which is exactly what
# these presets correct for.
#
# The accelerometer and gyroscope live on the same chip and MUST use the same preset.
IMU_ORIENTATIONS = {
  # Factory comma three vertical mount. Matches the historical [y, -x, z] mapping.
  #   forward = y, right = -x, down = z
  "default":   ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
  # Chip face pointing down (device remounted flat, camera still forward).
  # This is "default" with an extra -90 deg rotation about the device right axis.
  #   forward = -z, right = -x, down = y
  "chip_down": ((0, 0, -1), (-1, 0, 0), (0, 1, 0)),
  # Chip face pointing up. "default" with an extra +90 deg rotation about the right axis.
  #   forward = z, right = -x, down = -y
  "chip_up":   ((0, 0, 1), (-1, 0, 0), (0, -1, 0)),
}

DEFAULT_ORIENTATION = "default"

# Where users set the mounting orientation. This file is on the user-accessible media
# partition (reachable over USB / file manager), so changing the mount only requires editing
# a small text file whose content is one of IMU_ORIENTATIONS ("default"/"chip_down"/
# "chip_up"). The value is read once at process startup; a reboot applies a change, which
# matches the fact that the physical mounting only changes when the device is re-installed.
ORIENTATION_FILE = "/data/media/0/imu_orientation"


def load_orientation() -> str:
  # Priority: IMU_ORIENTATION env var (handy for tests/overrides) > file > default.
  val = os.getenv("IMU_ORIENTATION")
  source = "env"
  if val is None:
    source = "file"
    try:
      with open(ORIENTATION_FILE) as f:
        val = f.read()
    except FileNotFoundError:
      return DEFAULT_ORIENTATION
    except Exception:
      cloudlog.exception(f"failed to read {ORIENTATION_FILE}, using {DEFAULT_ORIENTATION}")
      return DEFAULT_ORIENTATION

  val = val.strip().lower()
  if val not in IMU_ORIENTATIONS:
    cloudlog.error(f"invalid IMU orientation {val!r} from {source}, using {DEFAULT_ORIENTATION}")
    return DEFAULT_ORIENTATION
  return val


IMU_ORIENTATION = load_orientation()
