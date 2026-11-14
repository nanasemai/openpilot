"""Keep physical speed settings in km/h when display units change."""
from contextlib import contextmanager
import fcntl
import math
from pathlib import Path
import threading

from openpilot.common.constants import CV

_migration_lock = threading.RLock()
SPEED_KEYS = ('BlinkerMinLateralControlSpeed', 'SpeedLimitValueOffset')


@contextmanager
def speed_settings_lock(params):
  # Keep the mode/value pair consistent across the UI and control processes.
  path = Path(params.get_param_path()).parent / '.speed-settings.lock'
  with path.open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
      yield
    finally:
      fcntl.flock(lock, fcntl.LOCK_UN)


def read_speed_limit_settings(params):
  with speed_settings_lock(params):
    return (params.get_bool('IsMetric'), params.get('SpeedLimitOffsetType', return_default=True),
            params.get('SpeedLimitValueOffset', return_default=True), params.get_bool('SpeedSettingsInKph'))


def ensure_speed_settings(params):
  # Run before manager starts control processes. UI-only tools also initialize here.
  with _migration_lock, speed_settings_lock(params):
    if params.get_bool('SpeedSettingsInKph'):
      return
    old = {key: params.get(key) for key in (*SPEED_KEYS, 'SpeedSettingsInKph')}
    factor = 1 if params.get_bool('IsMetric') else CV.MPH_TO_KPH
    values = {'BlinkerMinLateralControlSpeed': float(params.get(SPEED_KEYS[0], return_default=True)) * factor}
    if params.get('SpeedLimitOffsetType', return_default=True) == 1:
      values['SpeedLimitValueOffset'] = float(params.get(SPEED_KEYS[1], return_default=True)) * factor
    try:
      for key, value in values.items():
        if not math.isfinite(value):
          raise ValueError('Invalid speed setting')
        params.put(key, value, block=True)
      params.put_bool('SpeedSettingsInKph', True, block=True)
    except Exception:
      # A write can report failure after replacing the destination (fsync error).
      params.remove('SpeedSettingsInKph') if old['SpeedSettingsInKph'] is None else params.put('SpeedSettingsInKph', old['SpeedSettingsInKph'], block=True)
      for key in values:
        params.remove(key) if old[key] is None else params.put(key, old[key], block=True)
      raise


def speed_display_factor(params):
  return 1 if params.get_bool('IsMetric') else CV.MPH_TO_KPH


def speed_kph(params, key, is_metric):
  value = float(params.get(key, return_default=True))
  return value if params.get_bool('SpeedSettingsInKph') else value * (1 if is_metric else CV.MPH_TO_KPH)


def configure_speed_action(action, percentage=False):
  ensure_speed_settings(action.params)

  def factor():
    if percentage and action.params.get('SpeedLimitOffsetType', return_default=True) != 1:
      return 1
    return speed_display_factor(action.params)

  action.value_from_storage = lambda value: int(round(float(value) / factor() * 100))
  action.value_to_storage = lambda value: value / 100 * factor()
  action.current_value = action.decode_value(action.params.get(action.param_key, return_default=True))


def change_offset_type(params, selected):
  ensure_speed_settings(params)
  with speed_settings_lock(params):
    previous = params.get('SpeedLimitOffsetType', return_default=True)
    if previous == selected:
      return
    old_value = float(params.get('SpeedLimitValueOffset', return_default=True))
    factor = speed_display_factor(params)
    display_value = old_value / factor if previous == 1 else old_value
    try:
      params.put('SpeedLimitValueOffset', display_value * factor if selected == 1 else display_value, block=True)
      params.put('SpeedLimitOffsetType', selected, block=True)
    except Exception:
      params.put('SpeedLimitValueOffset', old_value, block=True)
      params.put('SpeedLimitOffsetType', previous, block=True)
      raise
