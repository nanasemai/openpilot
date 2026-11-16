"""Exercise display parameters, timeouts and wake input without changing host display hardware."""
from types import SimpleNamespace

import pytest

from openpilot.common.params import Params
from openpilot.selfdrive.ui import ui_state as state_module
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.display import OnroadBrightness
from openpilot.selfdrive.ui.sunnypilot.ui_state import DeviceSP, UIStateSP, OnroadTimerStatus, ONROAD_BRIGHTNESS_TIMER_PAUSED
from openpilot.system.ui.lib.application import gui_app, MouseEvent, MousePos


@pytest.fixture
def display_state(monkeypatch):
  state = state_module.ui_state
  values = {
    'params': Params(), 'CP': None, 'CP_SP': None, 'started': True, 'ignition': True,
    'light_sensor': 0, 'onroad_brightness': 0, 'onroad_brightness_timer_param': 15,
    'onroad_brightness_timer': 0, 'custom_interactive_timeout': 0, '_sp_initialized': False,
    '_enforce_constraints': lambda: None,
  }
  for key, value in values.items():
    monkeypatch.setattr(state, key, value)
  monkeypatch.setattr(gui_app, 'sunnypilot_ui', lambda: True)
  monkeypatch.setattr(gui_app, 'big_ui', lambda: False)
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  monkeypatch.setattr(gui_app, '_should_render', True)
  return state


@pytest.fixture
def display_device(display_state, monkeypatch):
  now = [100.0]
  monkeypatch.setattr(state_module.time, 'monotonic', lambda: now[0])
  monkeypatch.setattr(state_module, 'PC', False)
  power = []
  monkeypatch.setattr(state_module.HARDWARE, 'set_display_power', power.append)
  device = state_module.Device()
  monkeypatch.setattr(device, '_start_brightness_thread', lambda: None)
  return device, now, power


def events(pressed=False, released=False, down=False, slot=0):
  return MouseEvent(MousePos(100, 100), slot, pressed, released, down, 0)


def test_boot_display_mode_is_available_before_first_parameter_refresh():
  initial = UIStateSP()
  assert initial.boot_offroad_mode == initial.params.get('DeviceBootMode', return_default=True)
  DeviceSP._set_awake(True, initial)


def test_brightness_parameters_restart_timer_only_when_changed(display_state):
  state = display_state
  state.params.put('OnroadScreenOffBrightness', 12, block=True)
  state.params.put('OnroadScreenOffTimer', 30, block=True)
  UIStateSP.update_params(state)
  assert state.onroad_brightness_timer == 30 * gui_app.target_fps
  state.update_onroad_brightness(False)
  remaining = state.onroad_brightness_timer
  UIStateSP.update_params(state)
  assert state.onroad_brightness_timer == remaining
  state.params.put('OnroadScreenOffTimer', 60, block=True)
  UIStateSP.update_params(state)
  assert state.onroad_brightness_timer == 60 * gui_app.target_fps
  state.params.put('OnroadScreenOffBrightness', int(OnroadBrightness.AUTO_DARK), block=True)
  UIStateSP.update_params(state)
  assert state.onroad_brightness_timer == 15 * gui_app.target_fps
  assert DeviceSP.set_min_onroad_brightness(state, 30) == 10


def test_brightness_parameter_changes_preserve_pause_until_driving_view_returns(display_state):
  state = display_state
  state.reset_onroad_sleep_timer(OnroadTimerStatus.PAUSE)
  state.params.put('OnroadScreenOffBrightness', int(OnroadBrightness.SCREEN_OFF), block=True)
  state.params.put('OnroadScreenOffTimer', 5, block=True)
  UIStateSP.update_params(state)
  assert state.onroad_brightness_timer == ONROAD_BRIGHTNESS_TIMER_PAUSED
  state.update_onroad_brightness(False)
  assert state.onroad_brightness_timer == ONROAD_BRIGHTNESS_TIMER_PAUSED
  assert DeviceSP.set_onroad_brightness(state, True, 65) == 65
  state.reset_onroad_sleep_timer(OnroadTimerStatus.RESUME)
  assert state.onroad_brightness_timer == 5 * gui_app.target_fps


@pytest.mark.parametrize('brightness,expected', [(0, 65), (1, 65), (2, 0), (3, 5), (12, 50), (22, 100)])
def test_brightness_expiry_and_restoration_use_actual_stored_values(display_state, brightness, expected):
  state = display_state
  state.onroad_brightness = brightness
  state.onroad_brightness_timer = 1
  assert DeviceSP.set_onroad_brightness(state, True, 65) == 65
  state.update_onroad_brightness(False)
  assert DeviceSP.set_onroad_brightness(state, True, 65) == expected
  state.started = False
  assert DeviceSP.set_onroad_brightness(state, True, 65) == 65


def test_alerts_restore_screen_and_restart_delay(display_state, monkeypatch):
  state = display_state
  monkeypatch.setattr(state, 'sm', SimpleNamespace(recv_frame={'carState': 100}))
  monkeypatch.setattr(state, 'started_frame', 1)
  state.onroad_brightness = OnroadBrightness.SCREEN_OFF
  assert DeviceSP.set_onroad_brightness(state, True, 65) == 0
  state.onroad_brightness_handle_alerts(state, object())
  assert state.onroad_brightness_timer == 15 * gui_app.target_fps
  assert DeviceSP.set_onroad_brightness(state, True, 65) == 65
  state.onroad_brightness_handle_alerts(state, None)
  assert state.onroad_brightness_timer == 15 * gui_app.target_fps - 1


@pytest.mark.parametrize('brightness', [1, 2, 12])
def test_touch_before_expiry_restarts_brightness_delay_without_consuming_input(display_state, display_device, brightness):
  device, _, _ = display_device
  display_state.onroad_brightness = brightness
  display_state.onroad_brightness_timer = 1
  touch = events(pressed=True, down=True)
  gui_app._mouse_events = [touch]
  device.handle_mouse_events()
  assert gui_app.mouse_events == [touch]
  assert display_state.onroad_brightness_timer == 15 * gui_app.target_fps


@pytest.mark.parametrize('brightness', [1, 2, 12])
def test_dimmed_wake_consumes_press_hold_and_release_then_accepts_next_touch(display_state, display_device, brightness):
  device, now, _ = display_device
  display_state.onroad_brightness = brightness
  gui_app._mouse_events = [events(pressed=True, down=True)]
  device.handle_mouse_events()
  assert gui_app.mouse_events == []
  assert display_state.onroad_brightness_timer == 15 * gui_app.target_fps
  assert device._interaction_time == now[0] + 5
  for touch in (events(down=True), events(released=True)):
    gui_app._mouse_events = [touch]
    device.handle_mouse_events()
    assert gui_app.mouse_events == []
  next_touch = [events(pressed=True, down=True), events(released=True)]
  gui_app._mouse_events = next_touch.copy()
  device.handle_mouse_events()
  assert gui_app.mouse_events == next_touch


def test_batched_wake_and_multiple_touch_slots_are_consumed_through_release(display_state, display_device):
  device, _, _ = display_device
  display_state.onroad_brightness = OnroadBrightness.SCREEN_OFF
  gui_app._mouse_events = [events(pressed=True, down=True), events(pressed=True, down=True, slot=1), events(released=True)]
  device.handle_mouse_events()
  assert gui_app.mouse_events == []
  assert device._wake_touch_slots == {1}
  gui_app._mouse_events = [events(released=True, slot=1)]
  device.handle_mouse_events()
  assert gui_app.mouse_events == []
  assert device._wake_touch_slots == set()


def test_automatic_mode_accepts_first_touch(display_state, display_device):
  device, _, _ = display_device
  touch = [events(pressed=True, down=True), events(released=True)]
  gui_app._mouse_events = touch.copy()
  device.handle_mouse_events()
  assert gui_app.mouse_events == touch
  assert display_state.onroad_brightness_timer == 0


@pytest.mark.parametrize('wake', [False, True])
def test_motionless_hold_keeps_timeouts_alive_until_release(display_state, display_device, wake):
  device, now, _ = display_device
  display_state.onroad_brightness = OnroadBrightness.SCREEN_OFF
  display_state.onroad_brightness_timer = 0 if wake else 1
  gui_app._mouse_events = [events(pressed=True, down=True)]
  device.handle_mouse_events()
  device.update()
  for _ in range(3):
    now[0] += 30
    display_state.onroad_brightness_timer = 1
    gui_app._mouse_events = []
    device.handle_mouse_events()
    device.update()
    assert device._interaction_time == now[0] + 5
    assert not device._prev_timed_out
    assert display_state.onroad_brightness_timer == 15 * gui_app.target_fps
  gui_app._mouse_events = [events(released=True)]
  device.handle_mouse_events()
  assert device._touch_down_slots == set()
  gui_app._mouse_events = []
  now[0] += 6
  device.handle_mouse_events()
  device.update()
  assert device._prev_timed_out


def test_live_interactivity_timeout_restarts_and_emits_once_at_new_deadline(display_state, display_device):
  device, now, _ = display_device
  callbacks = []
  device.add_interactive_timeout_callback(lambda: callbacks.append(now[0]))
  device.update()
  assert device._interaction_time == 105
  now[0] = 102
  display_state.custom_interactive_timeout = 90
  device.update()
  assert device._interaction_time == 192
  now[0] = 110
  device.update()
  assert callbacks == []
  assert device._interaction_time == 192
  now[0] = 193
  device.update()
  device.update()
  assert callbacks == [193]
  assert device.awake
  display_state.custom_interactive_timeout = 10
  device.update()
  assert device._interaction_time == 203
  assert not device._prev_timed_out
  now[0] = 204
  device.update()
  assert callbacks == [193, 204]


def test_default_timeout_tracks_ignition_and_screen_size(display_state, display_device, monkeypatch):
  device, now, _ = display_device
  display_state.ignition = False
  device.update()
  assert device._interaction_time == now[0] + 30
  now[0] += 1
  display_state.ignition = True
  device.update()
  assert device._interaction_time == now[0] + 5
  monkeypatch.setattr(gui_app, 'big_ui', lambda: True)
  device.update()
  assert device._interaction_time == now[0] + 10


def test_training_timeout_override_survives_settings_changes_and_restores(display_state, display_device):
  device, now, _ = display_device
  device.set_override_interactive_timeout(300)
  display_state.custom_interactive_timeout = 90
  device.update()
  assert device.interactive_timeout == 300
  assert device._interaction_time == now[0] + 300
  device.set_override_interactive_timeout(None)
  assert device.interactive_timeout == 90
  assert device._interaction_time == now[0] + 90


def test_timeout_callbacks_can_unregister_without_skipping_other_callbacks(display_device):
  device, now, _ = display_device
  invoked = []

  def first():
    invoked.append('first')
    device.remove_interactive_timeout_callback(first)

  def second():
    invoked.append('second')

  device.add_interactive_timeout_callback(first)
  device.add_interactive_timeout_callback(first)
  device.add_interactive_timeout_callback(second)
  device.update()
  now[0] += device.interactive_timeout + 1
  device.update()
  assert invoked == ['first', 'second']
  assert device._interactive_timeout_callbacks == [second]
  device.remove_interactive_timeout_callback(first)
  device.remove_interactive_timeout_callback(second)
  assert device._interactive_timeout_callbacks == []


def test_parked_timeout_powers_off_and_touch_restores_power_before_brightness(display_state, display_device):
  device, now, power = display_device
  display_state.started = False
  display_state.ignition = False
  device.update()
  assert device._brightness_target > 0
  now[0] += 31
  device.update()
  assert not device.awake
  assert power == [False]
  assert device._brightness_target == 0
  assert not gui_app._should_render
  gui_app._mouse_events = [events(pressed=True, down=True), events(released=True)]
  device.handle_mouse_events()
  assert device.awake
  assert power == [False, True]
  assert gui_app._should_render
  assert gui_app.mouse_events == []
  device.update()
  assert device._brightness_target > 0


def test_display_device_sends_only_changed_brightness_targets(display_state, display_device):
  device, _, _ = display_device
  display_state.onroad_brightness = 12
  device.update()
  assert device._brightness_target == 50
  device._brightness_event.clear()
  device.update()
  assert not device._brightness_event.is_set()
  display_state.onroad_brightness = OnroadBrightness.SCREEN_OFF
  device.update()
  assert device._brightness_target == 0
  assert device._brightness_event.is_set()
