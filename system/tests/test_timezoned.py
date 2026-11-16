"""Timezone changes apply promptly, retain daylight-saving rules, and retry failures."""
import datetime
import subprocess
from types import SimpleNamespace

import pytest
from openpilot.common.params import Params
from openpilot.system import timezoned, timezone_list


@pytest.mark.parametrize('value,expected', [(None, 'Asia/Shanghai'), (6, 'America/New_York'),
                                          (-1, 'Asia/Shanghai'), (999, 'Asia/Shanghai'),
                                          ('Europe/London', 'Europe/London'), ('not-a-zone', 'Asia/Shanghai')])
def test_timezone_values_keep_real_identifiers(value, expected):
  params = SimpleNamespace(get=lambda _: value)
  assert timezone_list.get_timezone_from_params(params) == expected


@pytest.mark.parametrize('month,hour', [(1, 7), (7, 8)])
def test_running_clock_uses_selected_zone_and_daylight_saving(monkeypatch, month, hour):
  instant = datetime.datetime(2026, month, 10, 12, tzinfo=datetime.UTC)
  class FrozenDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
      return instant.astimezone(tz)
  monkeypatch.setattr(timezone_list.datetime, 'datetime', FrozenDatetime)
  params = Params()
  params.put('Timezone', 6, block=True)
  assert timezone_list.now_in_timezone(params).hour == hour
  params.put('Timezone', 0, block=True)
  assert timezone_list.now_in_timezone(params).hour == 20
  assert params.get('Timezone') == 0


@pytest.mark.parametrize('agnos', [False, True])
def test_system_timezone_commands_use_selected_zone(monkeypatch, agnos):
  commands = []
  monkeypatch.setattr(timezoned, 'AGNOS', agnos)
  monkeypatch.setattr(timezoned.subprocess, 'check_call', commands.append)
  assert timezoned.set_timezone('Asia/Shanghai')
  if agnos:
    assert len(commands) == 3
    assert '/usr/share/zoneinfo/Asia/Shanghai' in commands[0]
  else:
    assert commands == [['sudo', 'timedatectl', 'set-timezone', 'Asia/Shanghai']]


@pytest.mark.parametrize('error', [subprocess.CalledProcessError(1, ['sudo']), FileNotFoundError('missing executable')])
def test_system_timezone_failure_is_not_marked_applied(monkeypatch, error):
  def fail(command):
    raise error
  monkeypatch.setattr(timezoned.subprocess, 'check_call', fail)
  assert not timezoned.set_timezone('Asia/Shanghai')


class EndLoop(BaseException):
  pass


def test_timezone_service_applies_initial_zone_and_retries_after_failure(monkeypatch):
  ticks, calls = [], []
  value = [0]
  monkeypatch.setattr(timezoned, 'Params', lambda: SimpleNamespace(get=lambda _: value[0]))
  def apply(zone):
    calls.append(zone)
    return len(calls) != 1
  def sleep(seconds):
    assert seconds == 60
    ticks.append(True)
    if len(ticks) == 3:
      value[0] = 10
    if len(ticks) == 4:
      raise EndLoop
  monkeypatch.setattr(timezoned, 'set_timezone', apply)
  monkeypatch.setattr(timezoned.time, 'sleep', sleep)
  with pytest.raises(EndLoop):
    timezoned.main()
  assert calls == ['Asia/Shanghai', 'Asia/Shanghai', 'UTC']
