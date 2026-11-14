"""Physical thresholds survive display-unit changes and legacy migration."""
from pathlib import Path

import pytest
from cereal import car
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.sunnypilot.speed_settings import ensure_speed_settings, change_offset_type, speed_kph
from openpilot.sunnypilot.selfdrive.controls.lib.blinker_pause_lateral import BlinkerPauseLateral
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.speed_limit_resolver import SpeedLimitResolver


@pytest.mark.parametrize('metric', [True, False])
@pytest.mark.parametrize('offset_type', [0, 1, 2])
def test_migration_is_idempotent_and_preserves_legacy_physical_values(metric, offset_type):
  params = Params()
  params.put_bool('IsMetric', metric, block=True)
  params.put('BlinkerMinLateralControlSpeed', 20, block=True)
  params.put('SpeedLimitOffsetType', offset_type, block=True)
  params.put('SpeedLimitValueOffset', -3, block=True)
  previous = speed_kph(params, 'BlinkerMinLateralControlSpeed', metric)
  ensure_speed_settings(params)
  assert params.get_bool('SpeedSettingsInKph')
  assert params.get('BlinkerMinLateralControlSpeed') == pytest.approx(previous)
  expected_offset = -3 * (CV.MPH_TO_KPH if not metric and offset_type == 1 else 1)
  assert params.get('SpeedLimitValueOffset') == pytest.approx(expected_offset)
  snapshot = params.get('BlinkerMinLateralControlSpeed'), params.get('SpeedLimitValueOffset')
  for units in (not metric, metric):
    params.put_bool('IsMetric', units, block=True)
    ensure_speed_settings(params)
    assert (params.get('BlinkerMinLateralControlSpeed'), params.get('SpeedLimitValueOffset')) == snapshot


@pytest.mark.parametrize('metric,paused', [(True, False), (False, True)])
def test_actual_blinker_controller_is_invariant_after_unit_toggle(metric, paused):
  params = Params()
  params.put_bool('IsMetric', metric, block=True)
  params.put_bool('BlinkerPauseLateralControl', True, block=True)
  params.put('BlinkerMinLateralControlSpeed', 20, block=True)
  params.put('BlinkerLateralReengageDelay', 0, block=True)
  cs = car.CarState.new_message(vEgo=8, leftBlinker=True)
  controller = BlinkerPauseLateral()
  controller.get_params()
  assert controller.update(cs) is paused
  ensure_speed_settings(params)
  for units in (metric, not metric, metric):
    params.put_bool('IsMetric', units, block=True)
    controller.get_params()
    assert controller.update(cs) is paused


@pytest.mark.parametrize('metric', [True, False])
@pytest.mark.parametrize('mode', [1, 2])
def test_real_fixed_and_percentage_offset_are_invariant_after_unit_toggle(metric, mode):
  params = Params()
  params.put_bool('IsMetric', metric, block=True)
  params.put('SpeedLimitOffsetType', mode, block=True)
  params.put('SpeedLimitValueOffset', 3, block=True)
  resolver = SpeedLimitResolver()
  resolver.speed_limit = 20
  before = resolver._get_speed_limit_offset()
  ensure_speed_settings(params)
  for units in (metric, not metric, metric):
    params.put_bool('IsMetric', units, block=True)
    resolver.frame = 0
    resolver.update_params()
    assert resolver._get_speed_limit_offset() == pytest.approx(before)


@pytest.mark.parametrize('metric', [True, False])
def test_offset_mode_transition_preserves_display_number(metric):
  params = Params()
  params.put_bool('IsMetric', metric, block=True)
  params.put('SpeedLimitOffsetType', 2, block=True)
  params.put('SpeedLimitValueOffset', -3, block=True)
  factor = 1 if metric else CV.MPH_TO_KPH
  change_offset_type(params, 1)
  assert params.get('SpeedLimitValueOffset') == pytest.approx(-3 * factor)
  change_offset_type(params, 2)
  assert params.get('SpeedLimitValueOffset') == pytest.approx(-3)


def test_migration_rolls_back_even_when_marker_write_fails_after_replacement():
  params = Params()
  params.put_bool('IsMetric', False, block=True)
  params.put('BlinkerMinLateralControlSpeed', 20, block=True)
  class FailingParams:
    def __getattr__(self, name):
      return getattr(params, name)
    def put_bool(self, key, value, **kwargs):
      params.put_bool(key, value, **kwargs)
      if key == 'SpeedSettingsInKph':
        raise OSError('simulated fsync failure')
  with pytest.raises(OSError):
    ensure_speed_settings(FailingParams())
  assert params.get('SpeedSettingsInKph') is None
  assert params.get('BlinkerMinLateralControlSpeed') == 20
  ensure_speed_settings(params)
  assert params.get('BlinkerMinLateralControlSpeed') == pytest.approx(20 * CV.MPH_TO_KPH)


@pytest.mark.parametrize('key,value,boolean', [('SshEnabled', True, True), ('LateralPositionOffset', 2, False)])
def test_synchronous_write_failure_is_reported(key, value, boolean):
  params = Params()
  destination = Path(params.get_param_path(key))
  destination.mkdir()
  with pytest.raises(OSError):
    (params.put_bool if boolean else params.put)(key, value, block=True)
  assert destination.is_dir()
