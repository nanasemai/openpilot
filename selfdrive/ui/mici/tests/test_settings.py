"""Exercise the C4 settings with real controls and a 536 x 240 render surface."""
import pytest
import pyray as rl
import time
from cereal import car
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import multilang, tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.compact import CompactPage, CompactNumberPage, CompactSelectPage, HEADER_HEIGHT, resolve
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.sunnypilot.widgets.tree_dialog import TreeFolder, TreeNode, TreeOptionDialog
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import TITLES, GROUPS, make_panel
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.steering import PanelType


@pytest.fixture(scope='module', autouse=True)
def window():
  gui_app.init_window('C4 settings tests')
  yield
  gui_app.close()


@pytest.fixture(autouse=True)
def state(monkeypatch, openpilot_function_fixture):
  gui_app._nav_stack.clear()
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  monkeypatch.setattr(ui_state, 'params', Params())
  monkeypatch.setattr(ui_state, 'is_metric', True)
  ui_state.params.put_bool('IsMetric', True, block=True)
  monkeypatch.setattr(ui_state, 'started', False)
  monkeypatch.setattr(ui_state, 'force_onroad', False)
  monkeypatch.setattr(ui_state, 'CP', None)
  monkeypatch.setattr(ui_state, 'CP_SP', None)
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', False)
  monkeypatch.setattr(ui_state, 'has_icbm', False)
  monkeypatch.setattr(ui_state, 'update_params', lambda: None)
  ui_state.params.put_bool('ShowAdvancedControls', True, block=True)
  multilang._language = 'zh-CHS'
  multilang.setup()
  gui_app.on_language_changed('zh-CHS')
  gui_app.push_widget(CompactPage('root'))
  yield
  while len(gui_app._nav_stack) > 1:
    gui_app.pop_widget()


def draw(panel):
  rl.begin_drawing()
  panel.render(rl.Rectangle(0, 0, 536, 240))
  rl.end_drawing()


def wait_param(key, value):
  deadline = time.monotonic() + 1
  while time.monotonic() < deadline and ui_state.params.get(key) != value:
    time.sleep(0.01)
  assert ui_state.params.get(key) == value


@pytest.mark.parametrize('key', list(TITLES))
def test_all_pages_are_reachable_and_render(key):
  assert set(TITLES) == {key for _, keys in GROUPS for key in keys}
  panel = make_panel(key)
  gui_app.push_widget(panel)
  draw(panel)
  draw(panel)
  assert panel._header.rect.height == HEADER_HEIGHT
  if key not in ('network', 'sunnylink'):
    assert panel._list.rect.height == 240 - HEADER_HEIGHT
    assert panel._list.horizontal
    if key in ('trips', 'firehose'):
      assert panel._list.page_count == len(panel._list.visible_items)
      assert panel._list.visible_items[0].rect.width >= 500
    else:
      assert all(row.rect.width <= 402 for row in panel._list._scroller.items)


def test_steering_subpages_and_number_write():
  ui_state.params.put('LateralPositionOffset', 0, block=True)
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  controller = panel.controller
  controller._lane_change_settings_button.action_item.button_action._click_callback()
  draw(panel)
  assert panel._active is controller._lane_change_settings_layout
  panel.go_back()
  draw(panel)
  assert panel._active is controller
  item = controller._lat_position_offset
  panel._open_number(item, lambda: item.title, lambda: item.description)
  detail = gui_app.get_active_widget()
  assert isinstance(detail, CompactNumberPage)
  detail.change(-1)
  wait_param('LateralPositionOffset', -1)
  item.action_item.set_value(-15)
  detail.change(-1)
  wait_param('LateralPositionOffset', -15)
  gui_app.pop_widget()
  assert gui_app.get_active_widget() is panel
  controller._set_current_panel(PanelType.TORQUE_CONTROL)
  draw(panel)
  assert panel._active is controller._torque_control_layout


def test_numeric_mapping_uses_actual_seconds():
  ui_state.params.put('OnroadScreenOffBrightness', 22, block=True)
  panel = make_panel('display')
  gui_app.push_widget(panel)
  item = panel.controller._onroad_brightness_timer
  panel._open_number(item, lambda: item.title, lambda: item.description)
  detail = gui_app.get_active_widget()
  assert isinstance(detail, CompactSelectPage)
  detail._list._scroller.items[5].callback()
  wait_param('OnroadScreenOffTimer', 30)
  assert gui_app.get_active_widget() is panel


def test_stale_numeric_detail_cannot_write_when_source_disabled():
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  item = panel.controller._lat_position_offset
  panel._open_number(item, lambda: item.title, lambda: item.description)
  detail = gui_app.get_active_widget()
  item.action_item.set_enabled(False)
  before = item.action_item.current_value
  detail.change(1)
  assert item.action_item.current_value == before


def test_vehicle_gating_blocks_angle_control():
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  ui_state.CP = car.CarParams.new_message(steerControlType='angle')
  draw(panel)
  toggle = panel.controller._torque_control_toggle
  assert not toggle.action_item.enabled
  panel._toggle(toggle)
  assert not ui_state.params.get_bool('EnforceTorqueControl')


def test_confirm_cancel_and_accept_preserve_callback_semantics():
  results = []
  dialog = ConfirmDialog('<b>test</b><br>long content', 'OK', rich=True, callback=results.append)
  gui_app.push_widget(dialog)
  draw(dialog)
  dialog._compact_view._cancel._click_callback()
  assert results == [DialogResult.CANCEL]
  gui_app.push_widget(dialog)
  dialog._compact_view._confirm._click_callback()
  assert results == [DialogResult.CANCEL, DialogResult.CONFIRM]


def test_tree_selection_preserves_reference_and_favorite():
  results = []
  dialog = TreeOptionDialog('Models', [TreeFolder('', [TreeNode('model-1', {'display_name': 'One'}),
                                                     TreeNode('model-2', {'display_name': 'Two'})])],
                            fav_param='ModelManager_Favs', on_exit=results.append)
  gui_app.push_widget(dialog)
  draw(dialog)
  dialog._compact_page._list._scroller.items[1].callback()
  assert dialog.selection_ref == 'model-2'
  dialog._compact_confirm._click_callback()
  assert results == [DialogResult.CONFIRM]


def test_labels_switch_back_to_english_without_reconstructing():
  panel = make_panel('models')
  gui_app.push_widget(panel)
  row = panel._rows[panel.controller.lane_turn_desire_toggle][0]
  assert resolve(row.title) == tr('Use Lane Turn Desires')
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  assert resolve(row.title) == 'Use Lane Turn Desires'


def test_chinese_metered_selection_uses_enum(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts.settings.network.network_layout import NetworkLayoutMici
  from openpilot.system.ui.lib.wifi_manager import MeteredType
  panel = NetworkLayoutMici()
  values = []
  monkeypatch.setattr(panel._wifi_manager, 'set_current_network_metered', values.append)
  callback = panel._network_metered_btn._select_callback
  callback(panel._network_metered_btn._options[1])
  callback(panel._network_metered_btn._options[2])
  assert values == [MeteredType.YES, MeteredType.NO]


@pytest.fixture
def driving_state(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.mici.onroad.hud_renderer import HudRendererSP

  class Messages(dict):
    recv_frame = {'carState': 100}

  cs = SimpleNamespace(vCruiseCluster=80, vEgoCluster=12, vEgo=10, aEgo=1, steeringAngleDeg=5,
                       leftBlindspot=False, rightBlindspot=False, leftBlinker=False, rightBlinker=False, standstill=False)
  alerts = SimpleNamespace(greenLightAlert=False, leadDepartAlert=False)
  sm = Messages(carState=cs, controlsState=SimpleNamespace(deprecated=SimpleNamespace(vCruise=80)),
                selfdriveState=SimpleNamespace(enabled=False), longitudinalPlanSP=SimpleNamespace(e2eAlerts=alerts),
                liveMapDataSP=SimpleNamespace(roadName='测试道路'),
                radarState=SimpleNamespace(leadOne=SimpleNamespace(status=True, dRel=30, vRel=-1)))
  monkeypatch.setattr(ui_state, 'sm', sm)
  monkeypatch.setattr(ui_state, 'started_frame', 0)
  monkeypatch.setattr(ui_state, 'started', True)
  monkeypatch.setattr(ui_state, 'is_metric', True)
  monkeypatch.setattr(ui_state, 'true_v_ego_ui', False)
  monkeypatch.setattr(ui_state, 'hide_v_ego_ui', False)
  monkeypatch.setattr(ui_state, 'road_name_toggle', False)
  monkeypatch.setattr(ui_state, 'turn_signals', False)
  monkeypatch.setattr(ui_state, 'rocket_fuel', False)
  monkeypatch.setattr(ui_state, 'standstill_timer', False)
  monkeypatch.setattr(ui_state, 'developer_ui', 0)
  monkeypatch.setattr(ui_state, 'torque_bar', False)
  monkeypatch.setattr(ui_state, 'blindspot', False)
  renderer = HudRendererSP()
  yield renderer, cs, alerts


def test_speed_selection_and_hide_are_effective(driving_state, monkeypatch):
  renderer, _, _ = driving_state
  renderer._update_state()
  assert renderer.speed == pytest.approx(43.2)
  ui_state.true_v_ego_ui = True
  renderer._update_state()
  assert renderer.speed == pytest.approx(36)
  drawn = []
  monkeypatch.setattr(renderer, '_label', lambda rect, text, size: drawn.append(text))
  renderer._draw_optional(rl.Rectangle(0, 0, 476, 240))
  assert any('36' in text for text in drawn)
  drawn.clear()
  ui_state.hide_v_ego_ui = True
  renderer._draw_optional(rl.Rectangle(0, 0, 476, 240))
  assert not drawn


def test_optional_overlays_are_suppressed_during_alerts(driving_state, monkeypatch):
  renderer, _, _ = driving_state
  drawn = []
  monkeypatch.setattr(renderer, '_draw_optional', lambda rect: drawn.append('optional'))
  monkeypatch.setattr(renderer, '_draw_steering_wheel', lambda rect: None)
  monkeypatch.setattr(renderer._torque_bar, 'render', lambda rect: drawn.append('torque'))
  ui_state.torque_bar = True
  renderer.set_can_draw_top_icons(False)
  renderer._render(rl.Rectangle(0, 0, 476, 240))
  assert not drawn
  renderer.set_can_draw_top_icons(True)
  renderer._render(rl.Rectangle(0, 0, 476, 240))
  assert drawn == ['torque', 'optional']


def test_road_name_time_and_developer_modes_render(driving_state, monkeypatch):
  renderer, _, _ = driving_state
  drawn = []
  monkeypatch.setattr(renderer, '_label', lambda rect, text, size: drawn.append((rect, text)))
  ui_state.hide_v_ego_ui = True
  ui_state.road_name_toggle = True
  ui_state.developer_ui = 3
  ui_state.params.put_bool('dp_show_date_time', True, block=True)
  renderer._draw_optional(rl.Rectangle(0, 0, 476, 240))
  assert any(text == '测试道路' for _, text in drawn)
  assert any(tr('Acceleration') in text for _, text in drawn)
  assert any(tr('Distance') in text for _, text in drawn)
  assert all(rect.x >= 0 and rect.y >= 0 and rect.x + rect.width <= 476 and rect.y + rect.height <= 240 for rect, _ in drawn)


def test_green_light_notice_honors_setting(driving_state):
  renderer, _, alerts = driving_state
  alerts.greenLightAlert = True
  renderer._update_state()
  assert renderer._notice == ''
  ui_state.params.put_bool('GreenLightAlert', True, block=True)
  renderer._update_state()
  assert renderer._notice == 'GreenLightAlert'


@pytest.mark.parametrize('param', ['GreenLightAlert', 'LeadDepartAlert'])
def test_visual_notice_uses_current_language_and_clears_when_disabled(driving_state, monkeypatch, param):
  from openpilot.selfdrive.ui.sunnypilot.mici.onroad import hud_renderer
  renderer, _, alerts = driving_state
  now = [100.0]
  monkeypatch.setattr(hud_renderer.time, 'monotonic', lambda: now[0])
  setattr(alerts, 'greenLightAlert' if param == 'GreenLightAlert' else 'leadDepartAlert', True)
  ui_state.params.put_bool(param, True, block=True)
  renderer._update_state()
  assert renderer._notice == param
  drawn = []
  monkeypatch.setattr(renderer, '_label', lambda rect, text, size: drawn.append(text))
  text_source = 'GREEN\nLIGHT' if param == 'GreenLightAlert' else 'LEAD VEHICLE\nDEPARTING'
  renderer._draw_optional(rl.Rectangle(0, 0, 536, 240))
  assert tr(text_source).replace('\n', ' ') in drawn
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  drawn.clear()
  renderer._draw_optional(rl.Rectangle(0, 0, 536, 240))
  assert text_source.replace('\n', ' ') in drawn
  ui_state.params.put_bool(param, False, block=True)
  renderer._update_state()
  drawn.clear()
  renderer._draw_optional(rl.Rectangle(0, 0, 536, 240))
  assert text_source.replace('\n', ' ') not in drawn
  assert renderer._notice == ''
  assert renderer._notice_until == 0


def test_visual_notice_expiry_and_standstill_timer_reset(driving_state, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.mici.onroad import hud_renderer
  renderer, cs, alerts = driving_state
  now = [100.0]
  monkeypatch.setattr(hud_renderer.time, 'monotonic', lambda: now[0])
  cs.standstill = True
  ui_state.standstill_timer = True
  ui_state.params.put_bool('LeadDepartAlert', True, block=True)
  alerts.leadDepartAlert = True
  renderer._update_state()
  alerts.leadDepartAlert = False
  now[0] += 65
  renderer._update_state()
  texts = []
  monkeypatch.setattr(renderer, '_label', lambda rect, text, size: texts.append(text))
  renderer._draw_optional(rl.Rectangle(0, 0, 536, 240))
  assert '1:05' in texts
  assert tr('LEAD VEHICLE\nDEPARTING').replace('\n', ' ') not in texts
  cs.standstill = False
  renderer._update_state()
  assert renderer._standstill_since is None
  cs.standstill = True
  renderer._update_state()
  assert renderer._standstill_since == now[0]
  ui_state.started = False
  alerts.leadDepartAlert = True
  renderer._update_state()
  assert renderer._notice == ''
  assert renderer._standstill_since is None


def test_stale_vehicle_data_does_not_restore_speed_or_visual_notices(driving_state, monkeypatch):
  renderer, cs, alerts = driving_state
  cs.leftBlindspot = True
  cs.standstill = True
  ui_state.blindspot = True
  ui_state.true_v_ego_ui = True
  ui_state.params.put_bool('GreenLightAlert', True, block=True)
  alerts.greenLightAlert = True
  renderer._update_state()
  assert renderer.speed > 0
  assert renderer._notice
  assert renderer.blind_spot_indicators.detected
  monkeypatch.setattr(ui_state, 'started_frame', 101)
  renderer._update_state()
  assert renderer.speed == 0
  assert renderer._notice == ''
  assert renderer._standstill_since is None
  assert not renderer.blind_spot_indicators.detected
  texts = []
  monkeypatch.setattr(renderer, '_label', lambda *args: texts.append(args))
  renderer._draw_optional(rl.Rectangle(0, 0, 536, 240))
  assert not texts


@pytest.mark.parametrize('is_metric,distance,speed', [(True, '30 m', '-4 km/h'), (False, '98 ft', '-2 mph')])
def test_c4_right_debug_metrics_use_distance_and_relative_speed_units(driving_state, monkeypatch, is_metric, distance, speed):
  renderer, _, _ = driving_state
  ui_state.developer_ui = 2
  ui_state.is_metric = is_metric
  ui_state.hide_v_ego_ui = True
  texts = []
  monkeypatch.setattr(renderer, '_label', lambda rect, text, size: texts.append(text))
  renderer._draw_optional(rl.Rectangle(0, 0, 536, 240))
  assert any(distance in text for text in texts)
  assert any(speed in text and tr('Relative Speed') in text for text in texts)


def test_font_atlases_include_simplified_labels():
  import re
  from pathlib import Path
  from openpilot.common.basedir import BASEDIR
  for weight in ('Regular', 'Medium', 'SemiBold', 'Bold'):
    path = Path(BASEDIR) / f'selfdrive/assets/fonts/OpFont-{weight}-zh-CHS.fnt'
    glyphs = {int(value) for value in re.findall(r'char id=(\d+)', path.read_text())}
    assert set(map(ord, '设置维护离线模式阈值')) <= glyphs


def test_sunnylink_requires_confirm_before_enabling():
  panel = make_panel('sunnylink')
  gui_app.push_widget(panel)
  item = panel.controller._sunnylink_toggle
  panel._toggle(item)
  assert not ui_state.params.get_bool('SunnylinkEnabled')
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  dialog._cancel_button_callback()
  assert not ui_state.params.get_bool('SunnylinkEnabled')
  panel._toggle(item)
  gui_app.get_active_widget()._confirm_button_callback()
  wait_param('SunnylinkEnabled', True)


def test_network_retains_controls_and_metered_identity(monkeypatch):
  from openpilot.system.ui.lib.wifi_manager import MeteredType
  panel = make_panel('network')
  gui_app.push_widget(panel)
  draw(panel)
  assert panel._list.rect.height == 240 - HEADER_HEIGHT
  assert len(panel._list._scroller.items) >= 8
  values = []
  monkeypatch.setattr(panel.native._wifi_manager, 'set_current_network_metered', values.append)
  # The host has no Wi-Fi adapter. Isolate enum submission from asynchronous scans.
  monkeypatch.setattr(panel, '_update_state', lambda: None)
  panel.native._network_metered_btn.set_enabled(True)
  panel._select_metered()
  gui_app.get_active_widget()._list._scroller.items[2].callback()
  assert values == [MeteredType.NO]


@pytest.fixture
def ssh_panel(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.widgets import ssh_key
  jobs = []
  monkeypatch.setattr(ssh_key.threading, 'Thread',
                      lambda target, args, daemon: SimpleNamespace(start=lambda: jobs.append(lambda: target(*args))))
  panel = make_panel('developer')
  monkeypatch.setattr(panel.controller, '_refresh_usb_state', lambda: None)
  gui_app.push_widget(panel)
  return panel, panel.controller._ssh_keys.action_item, jobs


def test_ssh_key_input_cancel_and_external_state_refresh(ssh_panel):
  from openpilot.selfdrive.ui.widgets.ssh_key import SshKeyActionState
  panel, action, jobs = ssh_panel
  action._handle_button_click()
  dialog = gui_app.get_active_widget()
  assert dialog._hint_label.text == tr('Enter your GitHub username')
  gui_app.pop_widget()
  assert jobs == []
  assert action._state == SshKeyActionState.ADD
  ui_state.params.put('GithubUsername', 'external-user', block=True)
  ui_state.params.put('GithubSshKeys', 'ssh-ed25519 example-key', block=True)
  panel.refresh()
  assert action._state == SshKeyActionState.REMOVE
  assert action.get_status() == 'external-user'
  ui_state.params.remove('GithubSshKeys')
  panel.refresh()
  assert action._state == SshKeyActionState.ADD


@pytest.mark.parametrize('accept', [False, True])
def test_ssh_remove_confirmation_keeps_or_removes_exact_selection(ssh_panel, accept):
  from openpilot.selfdrive.ui.widgets.ssh_key import SshKeyActionState
  panel, action, _ = ssh_panel
  ui_state.params.put('GithubUsername', 'example-user', block=True)
  ui_state.params.put('GithubSshKeys', 'ssh-ed25519 example-key', block=True)
  panel.refresh()
  action._handle_button_click()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  assert 'example-user' in resolve(dialog._label._text)
  if accept:
    dialog._confirm_button_callback()
    assert ui_state.params.get('GithubSshKeys') is None
    assert ui_state.params.get('GithubUsername') is None
    assert action._state == SshKeyActionState.ADD
  else:
    dialog._cancel_button_callback()
    assert ui_state.params.get('GithubSshKeys') == 'ssh-ed25519 example-key'
    assert action._state == SshKeyActionState.REMOVE


def test_ssh_remove_confirm_does_not_clear_external_replacement(ssh_panel):
  panel, action, _ = ssh_panel
  ui_state.params.put('GithubUsername', 'original', block=True)
  ui_state.params.put('GithubSshKeys', 'ssh-ed25519 original-key', block=True)
  panel.refresh()
  action._handle_button_click()
  dialog = gui_app.get_active_widget()
  ui_state.params.put('GithubUsername', 'external', block=True)
  ui_state.params.put('GithubSshKeys', 'ssh-ed25519 external-key', block=True)
  dialog._confirm_button_callback()
  assert ui_state.params.get('GithubUsername') == 'external'
  assert ui_state.params.get('GithubSshKeys') == 'ssh-ed25519 external-key'


def test_ssh_remove_failure_reports_error_and_preserves_keys(ssh_panel, monkeypatch):
  panel, action, _ = ssh_panel
  ui_state.params.put('GithubUsername', 'example-user', block=True)
  ui_state.params.put('GithubSshKeys', 'ssh-ed25519 example-key', block=True)
  real_params = action._fetcher._params
  class ReadOnly:
    def get(self, key):
      return real_params.get(key)
    def remove(self, key):
      raise OSError('read-only store')
  monkeypatch.setattr(action._fetcher, '_params', ReadOnly())
  panel.refresh()
  action._handle_button_click()
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get('GithubSshKeys') == 'ssh-ed25519 example-key'
  assert tr('Unable to remove SSH keys. Try again.') in resolve(gui_app.get_active_widget()._label._text)


@pytest.mark.parametrize('username', ['path/user', 'https://github.com/user', 'name?query', 'name with space'])
def test_ssh_invalid_username_does_not_start_fetch(ssh_panel, username):
  _, action, jobs = ssh_panel
  action._submit_username(username)
  assert jobs == []
  assert tr('Enter a GitHub username using letters, numbers, or hyphens.') in resolve(gui_app.get_active_widget()._label._text)


def test_ssh_editor_does_not_override_keys_added_while_editing(ssh_panel):
  _, action, jobs = ssh_panel
  action._handle_button_click()
  ui_state.params.put('GithubUsername', 'external', block=True)
  ui_state.params.put('GithubSshKeys', 'ssh-ed25519 external-key', block=True)
  action._submit_username('new-user')
  assert jobs == []
  assert ui_state.params.get('GithubUsername') == 'external'


def test_ssh_loading_status_failure_and_retry_use_current_language(ssh_panel, monkeypatch):
  import requests
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.widgets import ssh_key
  panel, action, jobs = ssh_panel
  def fail(*args, **kwargs):
    raise requests.Timeout()
  monkeypatch.setattr(ssh_key.requests, 'get', fail)
  action._submit_username('example-user')
  assert action.get_status() == tr('Fetching SSH keys...')
  row = panel._rows[panel.controller._ssh_keys][0]
  assert not resolve(row.available)
  jobs.pop(0)()
  assert gui_app.get_active_widget() is panel
  panel.refresh()
  error = gui_app.get_active_widget()
  assert resolve(error._label._text) == tr('Request timed out')
  draw(error)
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(error)
  assert resolve(error._compact_view._list._scroller.items[0].text) == 'Request timed out'
  error._confirm_button_callback()
  monkeypatch.setattr(ssh_key.requests, 'get', lambda *args, **kwargs:
                      SimpleNamespace(text='ssh-ed25519 example-key', raise_for_status=lambda: None))
  action._submit_username('example-user')
  jobs.pop(0)()
  assert ui_state.params.get('GithubSshKeys') is None
  panel.refresh()
  assert ui_state.params.get('GithubSshKeys') == 'ssh-ed25519 example-key'
  assert resolve(row.value) == 'example-user'


def test_ssh_failure_waits_until_settings_return_and_is_shown_once(ssh_panel, monkeypatch):
  import requests
  from openpilot.selfdrive.ui.widgets import ssh_key
  panel, action, jobs = ssh_panel
  def fail(*args, **kwargs):
    raise requests.ConnectionError()
  monkeypatch.setattr(ssh_key.requests, 'get', fail)
  action._submit_username('example-user')
  gui_app.push_widget(CompactPage('other page'))
  other = gui_app.get_active_widget()
  jobs.pop(0)()
  panel.refresh()
  assert gui_app.get_active_widget() is other
  assert action._pending_error is not None
  gui_app.pop_widget()
  panel.refresh()
  error = gui_app.get_active_widget()
  assert isinstance(error, ConfirmDialog)
  assert action._pending_error is None
  error._confirm_button_callback()
  panel.refresh()
  assert gui_app.get_active_widget() is panel


def test_ssh_formatted_failure_and_remove_confirm_refresh_language(ssh_panel, monkeypatch):
  import requests
  from openpilot.selfdrive.ui.widgets import ssh_key
  panel, action, jobs = ssh_panel
  def fail(*args, **kwargs):
    raise requests.HTTPError()
  monkeypatch.setattr(ssh_key.requests, 'get', fail)
  action._submit_username('example-user')
  jobs.pop(0)()
  panel.refresh()
  dialog = gui_app.get_active_widget()
  draw(dialog)
  assert 'example-user' in resolve(dialog._label._text)
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(dialog)
  assert "Unable to fetch SSH keys for user 'example-user'." in resolve(dialog._compact_view._list._scroller.items[0].text)
  dialog._confirm_button_callback()
  ui_state.params.put('GithubUsername', 'example-user', block=True)
  ui_state.params.put('GithubSshKeys', 'ssh-ed25519 example-key', block=True)
  panel.refresh()
  action._handle_button_click()
  dialog = gui_app.get_active_widget()
  draw(dialog)
  assert resolve(dialog._label._text) == 'Remove SSH keys for example-user?'
  multilang._language = 'zh-CHS'
  multilang.setup()
  gui_app.on_language_changed('zh-CHS')
  draw(dialog)
  assert resolve(dialog._compact_view._list._scroller.items[0].text) == tr('Remove SSH keys for {username}?').format(username='example-user')


@pytest.mark.parametrize('text', ["'example-user'", '<input> & "quoted"', '<!-- literal comment -->',
                                '&lt;b&gt; remains literal', '<b>literal text</b>'])
def test_plain_confirmation_renders_entities_as_text_after_parsing(text, monkeypatch):
  from openpilot.system.ui.widgets.html_render import ElementType
  dialog = ConfirmDialog(text, tr('Confirm'))
  gui_app.push_widget(dialog)
  calls = []
  monkeypatch.setattr(rl, 'draw_text_ex', lambda font, value, *args: calls.append(value))
  draw(dialog)
  content = dialog._compact_view._list._scroller.items[0]._html
  assert ' '.join(element.content for element in content.elements if element.content) == text
  assert all(element.type == ElementType.P for element in content.elements)
  assert text in ' '.join(calls)


@pytest.fixture
def network_editor(monkeypatch):
  from openpilot.selfdrive.ui.lib.prime_state import PrimeType
  from openpilot.system.ui.lib.wifi_manager import WifiManager
  monkeypatch.setattr(WifiManager, 'set_active', lambda *args: None)
  panel = make_panel('network')
  prime = [PrimeType.NONE]
  monkeypatch.setattr(ui_state.prime_state, 'get_type', lambda: prime[0])
  gui_app.push_widget(panel)
  return panel, prime


@pytest.mark.parametrize('value', ['  internet  ', ''])
def test_apn_input_saves_trimmed_value_or_restores_automatic(network_editor, monkeypatch, value):
  panel, _ = network_editor
  ui_state.params.put('GsmApn', 'old-apn', block=True)
  panel.native._edit_apn()
  dialog = gui_app.get_active_widget()
  assert dialog._keyboard.text() == 'old-apn'
  dialog._keyboard.set_text(value)
  monkeypatch.setattr(dialog, 'dismiss', lambda callback: (gui_app.pop_widget(), callback()))
  dialog._confirm_callback()
  assert ui_state.params.get('GsmApn') == ('internet' if value else None)
  assert resolve(panel._list._scroller.items[6].value) == ('internet' if value else tr('Automatic'))


def test_apn_cancel_keeps_saved_value(network_editor):
  panel, _ = network_editor
  ui_state.params.put('GsmApn', 'old-apn', block=True)
  panel.native._edit_apn()
  gui_app.get_active_widget()._keyboard.set_text('new-apn')
  gui_app.pop_widget()
  assert ui_state.params.get('GsmApn') == 'old-apn'


@pytest.mark.parametrize('change', ['external', 'prime'])
def test_apn_pending_edit_rechecks_external_value_and_prime_restriction(network_editor, monkeypatch, change):
  from openpilot.selfdrive.ui.lib.prime_state import PrimeType
  panel, prime = network_editor
  ui_state.params.put('GsmApn', 'old-apn', block=True)
  panel.native._edit_apn()
  dialog = gui_app.get_active_widget()
  dialog._keyboard.set_text('new-apn')
  monkeypatch.setattr(dialog, 'dismiss', lambda callback: (gui_app.pop_widget(), callback()))
  if change == 'external':
    ui_state.params.put('GsmApn', 'external-apn', block=True)
  else:
    prime[0] = PrimeType.MAGENTA
  dialog._confirm_callback()
  assert ui_state.params.get('GsmApn') == ('external-apn' if change == 'external' else 'old-apn')


def test_hotspot_password_cancel_and_external_change_do_not_submit(network_editor, monkeypatch):
  panel, _ = network_editor
  manager = panel.native._wifi_manager
  monkeypatch.setattr(manager, '_tethering_password', 'old-password')
  calls = []
  monkeypatch.setattr(manager, 'set_tethering_password', calls.append)
  panel.native._tethering_password_btn._click_callback()
  dialog = gui_app.get_active_widget()
  assert dialog._keyboard.text() == 'old-password'
  gui_app.pop_widget()
  assert calls == []
  panel.native._tethering_password_btn._click_callback()
  dialog = gui_app.get_active_widget()
  dialog._keyboard.set_text('new-password')
  monkeypatch.setattr(dialog, 'dismiss', lambda callback: (gui_app.pop_widget(), callback()))
  manager._tethering_password = 'external-password'
  dialog._confirm_callback()
  assert calls == []


def test_hotspot_password_confirm_submits_once_and_disables_edit_until_update(network_editor, monkeypatch):
  panel, _ = network_editor
  manager = panel.native._wifi_manager
  monkeypatch.setattr(manager, '_tethering_password', 'old-password')
  calls = []
  monkeypatch.setattr(manager, 'set_tethering_password', calls.append)
  panel.native._tethering_password_btn._click_callback()
  dialog = gui_app.get_active_widget()
  dialog._keyboard.set_text('new-password')
  monkeypatch.setattr(dialog, 'dismiss', lambda callback: (gui_app.pop_widget(), callback()))
  dialog._confirm_callback()
  assert calls == ['new-password']
  assert not panel.native._tethering_password_btn.enabled
  panel.native._tethering_password_btn._click_callback()
  assert gui_app.get_active_widget() is panel
  panel.native._on_network_updated([])
  assert panel.native._tethering_password_btn.enabled


def test_network_metered_picker_does_not_change_new_connection(network_editor, monkeypatch):
  from openpilot.system.ui.lib.wifi_manager import MeteredType, WifiState, ConnectStatus
  panel, _ = network_editor
  manager = panel.native._wifi_manager
  monkeypatch.setattr(manager, '_wifi_state', WifiState(ssid='Original', status=ConnectStatus.CONNECTED))
  monkeypatch.setattr(manager, '_ipv4_address', '192.0.2.1')
  calls = []
  monkeypatch.setattr(manager, 'set_current_network_metered', calls.append)
  panel.native._on_network_updated([])
  panel._select_metered()
  picker = gui_app.get_active_widget()
  manager._wifi_state = WifiState(ssid='Changed', status=ConnectStatus.CONNECTED)
  picker._list._scroller.items[1].callback()
  assert calls == []
  assert gui_app.get_active_widget() is picker
  gui_app.pop_widget()
  panel._select_metered()
  gui_app.get_active_widget()._list._scroller.items[2].callback()
  assert calls == [MeteredType.NO]


def test_roaming_stale_button_rechecks_subscription_visibility(network_editor):
  from openpilot.selfdrive.ui.lib.prime_state import PrimeType
  panel, prime = network_editor
  ui_state.params.put_bool('GsmRoaming', False, block=True)
  panel._update_state()
  assert panel.native._roaming_btn.is_visible
  prime[0] = PrimeType.MAGENTA
  panel._toggle(panel.native._roaming_btn)
  assert not ui_state.params.get_bool('GsmRoaming')


def test_network_controller_refresh_never_runs_hidden_native_navigation(network_editor, monkeypatch):
  panel, _ = network_editor
  monkeypatch.setattr(panel.native, '_update_state', lambda: pytest.fail('hidden native navigation must not tick'))
  for _ in range(5):
    draw(panel)
    assert gui_app.get_active_widget() is panel


def test_known_chinese_ui_strings_are_translated():
  from pathlib import Path
  from openpilot.common.basedir import BASEDIR
  from openpilot.selfdrive.ui.translations.potools import extract_strings
  roots = ('selfdrive/ui/sunnypilot/mici', 'selfdrive/ui/mici', 'selfdrive/ui/sunnypilot/layouts/settings',
           'selfdrive/ui/layouts/settings', 'system/ui')
  files = [str(path.relative_to(BASEDIR)) for root in roots
           for path in (Path(BASEDIR) / root).rglob('*.py') if 'tests' not in path.parts]
  files.append('selfdrive/ui/widgets/ssh_key.py')
  missing = [entry.msgid for entry in extract_strings(files, BASEDIR)
             if entry.msgid not in multilang._translations and entry.msgid not in multilang._plurals]
  assert not missing


def test_all_simplified_translation_glyphs_exist():
  import re
  from pathlib import Path
  from openpilot.common.basedir import BASEDIR
  expected = {ord(c) for text in multilang._translations.values() for c in text if '\u4e00' <= c <= '\u9fff'}
  for weight in ('Regular', 'Medium', 'SemiBold', 'Bold'):
    path = Path(BASEDIR) / f'selfdrive/assets/fonts/OpFont-{weight}-zh-CHS.fnt'
    glyphs = {int(value) for value in re.findall(r'char id=(\d+)', path.read_text())}
    assert expected <= glyphs


def test_dynamic_overlay_unit_and_separator_glyphs_are_in_simplified_atlases():
  import re
  from pathlib import Path
  from openpilot.common.basedir import BASEDIR
  from openpilot.selfdrive.assets.fonts.process import _char_sets
  text = '1.00 m/s² · 5.0° · 30 m · 32 km/h · 3.0 s'
  required = {ord(character) for character in text}
  _, _, languages = _char_sets()
  assert required <= set(languages['zh-CHS'])
  for weight in ('Regular', 'Medium', 'SemiBold', 'Bold'):
    path = Path(BASEDIR) / f'selfdrive/assets/fonts/OpFont-{weight}-zh-CHS.fnt'
    glyphs = {int(value) for value in re.findall(r'char id=(\d+)', path.read_text())}
    assert required <= glyphs


@pytest.mark.parametrize('language', ['zh-CHS', 'en'])
def test_numeric_unit_glyphs_exist_in_all_active_font_weights(language):
  from openpilot.system.ui.lib.application import FontWeight
  multilang._language = language
  multilang.setup()
  gui_app.on_language_changed(language)
  for weight in (FontWeight.NORMAL, FontWeight.MEDIUM, FontWeight.BOLD, FontWeight.SEMI_BOLD, FontWeight.ROMAN):
    font = gui_app.font(weight)
    glyphs = {font.glyphs[index].value for index in range(font.glyphCount)}
    assert set(map(ord, 'm/s²°%−')) <= glyphs
    if language == 'zh-CHS':
      assert set(map(ord, '秒厘米')) <= glyphs


def test_scroll_position_survives_subpanel_and_detail():
  from openpilot.system.ui.lib.scroll_panel2 import ScrollState
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  draw(panel)
  scroll = panel._list._scroller.scroll_panel
  scroll.set_offset(-128)
  scroll._state = ScrollState.STEADY
  panel.controller._set_current_panel(PanelType.LANE_CHANGE)
  draw(panel)
  panel.go_back()
  draw(panel)
  assert panel._list._scroller.scroll_panel.get_offset() == pytest.approx(-128)


def test_touch_event_changes_only_the_switch(monkeypatch):
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  draw(panel)
  item = panel.controller._blinker_control_toggle
  row = panel._rows[item][0]
  # Render the specific row at a known viewport location; exercise Widget event dispatch.
  row.set_position(20, HEADER_HEIGHT + 8)
  row.set_parent_rect(rl.Rectangle(0, HEADER_HEIGHT, 536, 184))
  switch = row._switch_touch_rect()
  pos = MousePos(switch.x + switch.width / 2, switch.y + switch.height / 2)
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, True, False, True, 0), MouseEvent(pos, 0, False, True, False, 0.1)])
  row.render()
  wait_param('BlinkerPauseLateralControl', True)


def test_large_card_title_touch_opens_description_without_toggling(monkeypatch):
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  from openpilot.system.ui.widgets.compact import CompactInfoPage
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  draw(panel)
  item = panel.controller._blinker_control_toggle
  row = panel._rows[item][0]
  row.set_parent_rect(rl.Rectangle(0, HEADER_HEIGHT, 536, 184))
  row.set_position(20, HEADER_HEIGHT + 8)
  pos = MousePos(row.rect.x + 80, row.rect.y + 40)
  before = ui_state.params.get_bool('BlinkerPauseLateralControl')
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, True, False, True, 0),
                                               MouseEvent(pos, 0, False, True, False, 0.1)])
  row.render()
  assert isinstance(gui_app.get_active_widget(), CompactInfoPage)
  assert ui_state.params.get_bool('BlinkerPauseLateralControl') == before


def test_horizontal_swipe_moves_cards_without_toggling(monkeypatch):
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  draw(panel)
  before = ui_state.params.get_bool('Mads')
  events = [MouseEvent(MousePos(x, 200), 0, i == 0, i == 3, i < 3, i * 0.1)
            for i, x in enumerate((370, 300, 230, 160))]
  monkeypatch.setattr(gui_app, '_mouse_events', events)
  draw(panel)
  assert panel._list._scroller.scroll_panel.get_offset() < 0
  assert ui_state.params.get_bool('Mads') == before
  assert gui_app.get_active_widget() is panel


def test_home_swipe_navigation_preserves_parameter_scroll():
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP
  root = SettingsLayoutSP()
  gui_app.push_widget(root)
  draw(root)
  root.buttons[root.menu_keys.index('steering')]._click_callback()
  panel = gui_app.get_active_widget()
  draw(panel)
  panel._list.change_page(1)
  panel._rows[panel.controller._lat_position_offset][0].callback()
  assert isinstance(gui_app.get_active_widget(), CompactNumberPage)
  gui_app.pop_widget()
  draw(panel)
  assert panel._list.page == 1
  gui_app.pop_widget()
  draw(root)
  root.buttons[root.menu_keys.index('steering')]._click_callback()
  draw(panel)
  assert gui_app.get_active_widget() is panel
  assert panel._list.page == 1


def test_tree_confirmation_cancel_keeps_dialog_and_original_selection():
  nodes = [TreeNode('one', {'display_name': 'One'}), TreeNode('two', {'display_name': 'Two'})]
  results = []
  dialog = TreeOptionDialog('Models', [TreeFolder('', nodes)], current_ref='one', on_exit=results.append)
  gui_app.push_widget(dialog)
  draw(dialog)
  dialog._compact_page._list._scroller.items[1].callback()
  draw(dialog)
  assert dialog.selection_ref == 'two'
  assert not dialog._compact_page.enabled
  dialog._compact_confirm_view._cancel._click_callback()
  assert dialog.selection_ref == 'one'
  assert gui_app.get_active_widget() is dialog
  assert not results


def test_tree_rebuild_for_favorite_preserves_pending_selection():
  nodes = [TreeNode('one', {'display_name': 'One'}), TreeNode('two', {'display_name': 'Two'})]
  dialog = TreeOptionDialog('Models', [TreeFolder('', nodes)], current_ref='one', fav_param='ModelManager_Favs')
  dialog._select_node(nodes[1])
  dialog._toggle_favorite(nodes[1])
  assert dialog.selection_ref == 'two'
  assert dialog.selection == 'Two'
  assert dialog.current == 'One'


def test_tree_favorite_touch_matches_displayed_star():
  from openpilot.system.ui.lib.application import MousePos
  nodes = [TreeNode('one', {'display_name': 'One'}), TreeNode('two', {'display_name': 'Two'})]
  dialog = TreeOptionDialog('Models', [TreeFolder('', nodes)], current_ref='one', fav_param='ModelManager_Favs')
  gui_app.push_widget(dialog)
  draw(dialog)
  row = dialog._compact_page._list._scroller.items[0]
  touch = row._switch_touch_rect()
  row._handle_mouse_release(MousePos(touch.x + touch.width / 2, touch.y + touch.height / 2))
  assert 'one' in dialog.favorites
  assert dialog._compact_selection is None
  assert dialog.selection_ref == 'one'


def test_torque_float_scaling_is_preserved():
  ui_state.params.put_bool('EnforceTorqueControl', True, block=True)
  ui_state.params.put_bool('CustomTorqueParams', True, block=True)
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  panel.controller._set_current_panel(PanelType.TORQUE_CONTROL)
  draw(panel)
  item = panel._active._torque_friction
  item.action_item.set_value(10)
  panel._open_number(item, lambda: item.title, lambda: item.description)
  gui_app.get_active_widget().change(1)
  wait_param('TorqueParamsOverrideFriction', pytest.approx(0.11))


def test_standstill_timer_and_turn_indicators_are_effective(driving_state, monkeypatch):
  renderer, cs, _ = driving_state
  drawn = []
  lines = []
  monkeypatch.setattr(renderer, '_label', lambda rect, text, size: drawn.append(text))
  monkeypatch.setattr(rl, 'draw_line_ex', lambda *args: lines.append(args))
  ui_state.started = True
  ui_state.standstill_timer = True
  ui_state.hide_v_ego_ui = True
  cs.standstill = True
  renderer._update_state()
  renderer._draw_optional(rl.Rectangle(0, 0, 476, 240))
  assert '0:00' in drawn
  from openpilot.selfdrive.ui.sunnypilot.mici.onroad import hud_renderer
  monkeypatch.setattr(hud_renderer.time, 'monotonic', lambda: 2)
  ui_state.turn_signals = True
  cs.leftBlinker = True
  renderer._draw_optional(rl.Rectangle(0, 0, 476, 240))
  assert len(lines) == 3


def test_acceleration_bar_is_effective(driving_state, monkeypatch):
  renderer, _, _ = driving_state
  rectangles = []
  monkeypatch.setattr(rl, 'draw_rectangle_rec', lambda rect, color: rectangles.append(rect))
  monkeypatch.setattr(renderer, '_label', lambda *args: None)
  ui_state.rocket_fuel = True
  renderer._draw_optional(rl.Rectangle(0, 0, 476, 240))
  assert any(rect.width == 6 and rect.height == 20 for rect in rectangles)


def test_log_format_work_is_queued_and_result_shown_on_ui_thread(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import developer
  panel = make_panel('developer')
  gui_app.push_widget(panel)
  targets = []
  monkeypatch.setattr(developer.threading, 'Thread', lambda target, daemon: SimpleNamespace(start=lambda: targets.append(target)))
  monkeypatch.setattr(panel.controller, '_format_system_logs_text', lambda: 'finished')
  panel.controller._on_format_system_logs_clicked()
  assert gui_app.get_active_widget() is panel
  assert panel.controller._format_running
  assert len(targets) == 1
  targets[0]()
  assert gui_app.get_active_widget() is panel
  panel.refresh()
  assert gui_app.get_active_widget()._content.raw_text == 'finished'


def test_blindspot_setting_controls_warning_rendering(driving_state, monkeypatch):
  renderer, cs, _ = driving_state
  calls = []
  monkeypatch.setattr(rl, 'draw_texture_ex', lambda *args: calls.append(args))
  cs.leftBlindspot = True
  renderer.blind_spot_indicators.update()
  renderer.blind_spot_indicators.render(rl.Rectangle(0, 0, 476, 240))
  assert not calls
  ui_state.blindspot = True
  renderer.blind_spot_indicators.render(rl.Rectangle(0, 0, 476, 240))
  assert calls


def test_chevron_metrics_display_each_selected_measurement(driving_state, monkeypatch):
  from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer, LeadVehicle
  from openpilot.system.ui.widgets import label
  renderer = ModelRenderer()
  renderer.set_rect(rl.Rectangle(0, 0, 476, 240))
  renderer._lead_vehicles[0] = LeadVehicle(chevron=[(70, 100), (100, 90), (130, 100)])
  ui_state.sm['radarState'].leadOne.vLead = 9
  monkeypatch.setattr(ui_state, 'chevron_metrics', 4)
  texts = []
  monkeypatch.setattr(label, 'gui_label', lambda rect, text, *args, **kwargs: texts.append(text))
  renderer._draw_lead_indicator()
  assert texts and '30 m' in texts[0] and '32 km/h' in texts[0] and '3.0 s' in texts[0]


@pytest.mark.parametrize('mode', range(5))
@pytest.mark.parametrize('is_metric', [True, False])
def test_c4_chevron_measurements_match_shared_renderer_without_hiding_marker(driving_state, monkeypatch, mode, is_metric):
  from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer, LeadVehicle
  from openpilot.selfdrive.ui.sunnypilot.onroad.chevron_metrics import ChevronMetrics
  from openpilot.system.ui.widgets import label
  renderer = ModelRenderer()
  renderer.set_rect(rl.Rectangle(20, 10, 476, 240))
  renderer._lead_vehicles[0] = LeadVehicle(glow=[(70, 100), (100, 90), (130, 100)], chevron=[(70, 100), (100, 90), (130, 100)])
  ui_state.chevron_metrics = mode
  ui_state.is_metric = is_metric
  triangles, labels = [], []
  monkeypatch.setattr(rl, 'draw_triangle_fan', lambda *args: triangles.append(args))
  monkeypatch.setattr(label, 'gui_label', lambda rect, text, *args, **kwargs: labels.append((rect, text)))
  renderer._draw_lead_indicator()
  assert len(triangles) == 2
  expected = ChevronMetrics._build_text_lines(30, -1, 10)
  assert [text for _, text in labels] == ([' · '.join(expected)] if mode else [])
  for rect, _ in labels:
    assert rect.x >= 20 and rect.y >= 10 and rect.x + rect.width <= 496 and rect.y + rect.height <= 250


@pytest.mark.parametrize('mode', range(5))
def test_c4_model_render_keeps_lead_marker_in_every_metric_mode(driving_state, monkeypatch, mode):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.ui_state import UIStatus
  from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer, LeadVehicle
  from openpilot.system.ui.widgets import label
  renderer = ModelRenderer()
  renderer._longitudinal_control = True
  renderer._transform_dirty = False
  renderer._lead_vehicles[0] = LeadVehicle(glow=[(130, 100), (100, 90), (70, 100)],
                                          chevron=[(130, 100), (100, 90), (70, 100)], fill_alpha=255)
  sm = ui_state.sm
  sm['carOutput'] = SimpleNamespace(actuatorsOutput=SimpleNamespace(torque=0))
  sm['liveCalibration'] = SimpleNamespace(height=[1.22])
  sm['modelV2'] = SimpleNamespace()
  sm['selfdriveState'].experimentalMode = False
  sm.recv_frame.update(liveCalibration=100, modelV2=100)
  monkeypatch.setattr(sm, 'updated', {'carParams': False, 'modelV2': False, 'radarState': False}, raising=False)
  monkeypatch.setattr(sm, 'valid', {'radarState': True}, raising=False)
  monkeypatch.setattr(ui_state, 'status', UIStatus.DISENGAGED)
  monkeypatch.setattr(ui_state, 'chevron_metrics', mode)
  triangles, labels = [], []
  monkeypatch.setattr(rl, 'draw_triangle_fan', lambda *args: triangles.append(args))
  monkeypatch.setattr(label, 'gui_label', lambda rect, text, *args, **kwargs: labels.append(text))
  draw(renderer)
  assert len(triangles) == 2
  assert len(labels) == (1 if mode else 0)


def test_visual_chevron_selection_is_preserved_without_longitudinal_control(monkeypatch):
  ui_state.params.put('ChevronInfo', 3, block=True)
  panel = make_panel('visuals')
  gui_app.push_widget(panel)
  item = panel.controller._chevron_info
  for _ in range(3):
    panel.refresh()
  assert not item.action_item.enabled
  assert item.action_item.selected_button == 3
  assert ui_state.params.get('ChevronInfo') == 3
  panel.controller._on_chevron_info_selected(1)
  assert ui_state.params.get('ChevronInfo') == 3
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  panel.refresh()
  assert item.action_item.enabled
  assert resolve(panel._rows[item][0].value) == tr('Time')
  panel._open_enum(item, lambda: item.title)
  gui_app.get_active_widget()._list._scroller.items[4].callback()
  assert ui_state.params.get('ChevronInfo') == 4
  assert gui_app.get_active_widget() is panel


def test_visual_chevron_native_release_and_old_picker_recheck_longitudinal_control(monkeypatch):
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  ui_state.params.put('ChevronInfo', 3, block=True)
  panel = make_panel('visuals')
  gui_app.push_widget(panel)
  item = panel.controller._chevron_info
  panel._open_enum(item, lambda: item.title)
  picker = gui_app.get_active_widget()
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', False)
  picker._list._scroller.items[1].callback()
  assert ui_state.params.get('ChevronInfo') == 3
  gui_app.pop_widget()
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  panel.refresh()
  action = item.action_item
  action.set_rect(rl.Rectangle(0, 0, 1000, 150))
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', False)
  action._handle_mouse_release(rl.Vector2(300, 75))
  assert ui_state.params.get('ChevronInfo') == 3
  assert action.selected_button == 3
  assert not action.enabled


@pytest.mark.parametrize('param,value,expected', [('ChevronInfo', -1, 0), ('ChevronInfo', 10, 0),
                                                ('DevUIInfo', -1, 0), ('DevUIInfo', 10, 0)])
def test_invalid_visual_enum_displays_off_without_rewriting_saved_value(monkeypatch, param, value, expected):
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  ui_state.params.put(param, value, block=True)
  panel = make_panel('visuals')
  gui_app.push_widget(panel)
  item = panel.controller._chevron_info if param == 'ChevronInfo' else panel.controller._dev_ui_info
  panel.refresh()
  assert item.action_item.selected_button == expected
  assert resolve(panel._rows[item][0].value) == tr('Off')
  assert ui_state.params.get(param) == value


@pytest.mark.parametrize('param,attribute', [
  ('BlindSpot', 'blindspot'), ('TorqueBar', 'torque_bar'), ('RainbowMode', 'rainbow_path'),
  ('StandstillTimer', 'standstill_timer'), ('RoadNameToggle', 'road_name_toggle'),
  ('GreenLightAlert', None), ('LeadDepartAlert', None), ('TrueVEgoUI', 'true_v_ego_ui'),
  ('HideVEgoUI', 'hide_v_ego_ui'), ('ShowTurnSignals', 'turn_signals'), ('RocketFuel', 'rocket_fuel'),
])
def test_each_visual_toggle_saves_and_refreshes_running_state(monkeypatch, param, attribute):
  from openpilot.selfdrive.ui.sunnypilot.ui_state import UIStateSP
  monkeypatch.setattr(ui_state, '_enforce_constraints', lambda: None)
  ui_state.params.put_bool(param, False, block=True)
  panel = make_panel('visuals')
  gui_app.push_widget(panel)
  item = panel.controller._toggles[param]
  panel._toggle(item)
  wait_param(param, True)
  UIStateSP.update_params(ui_state)
  if attribute is not None:
    assert getattr(ui_state, attribute)
  assert item.action_item.get_state()
  ui_state.params.put_bool(param, False, block=True)
  panel.refresh()
  UIStateSP.update_params(ui_state)
  assert not item.action_item.get_state()
  if attribute is not None:
    assert not getattr(ui_state, attribute)


@pytest.mark.parametrize('mode', range(4))
def test_visual_developer_modes_save_exact_values_and_refresh_state(monkeypatch, mode):
  from openpilot.selfdrive.ui.sunnypilot.ui_state import UIStateSP
  monkeypatch.setattr(ui_state, '_enforce_constraints', lambda: None)
  panel = make_panel('visuals')
  gui_app.push_widget(panel)
  item = panel.controller._dev_ui_info
  panel._open_enum(item, lambda: item.title)
  gui_app.get_active_widget()._list._scroller.items[mode].callback()
  assert ui_state.params.get('DevUIInfo') == mode
  UIStateSP.update_params(ui_state)
  assert ui_state.developer_ui == mode
  assert gui_app.get_active_widget() is panel


def test_visual_chevron_default_and_saved_mode_are_gated_only_at_runtime(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.ui_state import UIStateSP
  monkeypatch.setattr(ui_state, '_enforce_constraints', lambda: None)
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  UIStateSP.update_params(ui_state)
  assert ui_state.params.get('ChevronInfo') is None
  assert ui_state.chevron_metrics == 4
  ui_state.params.put('ChevronInfo', 3, block=True)
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', False)
  UIStateSP.update_params(ui_state)
  assert ui_state.chevron_metrics == 0
  assert ui_state.params.get('ChevronInfo') == 3
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  UIStateSP.update_params(ui_state)
  assert ui_state.chevron_metrics == 3


def test_rainbow_setting_routes_to_rainbow_renderer(driving_state, monkeypatch):
  import numpy as np
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer
  renderer = ModelRenderer()
  renderer._path.projected_points = np.array([[0, 0], [1, 1]], dtype=np.float32)
  calls = []
  monkeypatch.setattr(renderer.rainbow_path, 'draw_rainbow_path', lambda *args: calls.append(args))
  monkeypatch.setattr(ui_state, 'rainbow_path', True)
  ui_state.sm['longitudinalPlan'] = SimpleNamespace(allowThrottle=True)
  renderer._draw_path(ui_state.sm)
  assert len(calls) == 1


def test_backup_failure_stays_visible_and_translates_after_language_change(monkeypatch):
  from cereal import custom
  panel = make_panel('sunnylink')
  gui_app.push_widget(panel)
  controller = panel.controller
  manager = custom.BackupManagerSP.new_message(backupStatus='failed')
  monkeypatch.setattr(ui_state, 'sm', {'backupManagerSP': manager})
  controller._backup_in_progress = True
  controller.handle_backup_restore_progress()
  controller.handle_backup_restore_progress()
  assert controller._transfer_status() == tr('Backup Failed')
  multilang._language = 'en'
  multilang.setup()
  assert controller._transfer_status() == 'Backup Failed'


@pytest.mark.parametrize('language', ['zh-CHS', 'en'])
@pytest.mark.parametrize('action_label', ['Description', 'Offroad Mode', 'Exit Offroad'])
def test_header_action_text_fits_without_eliding_and_touch_matches_button(monkeypatch, language, action_label):
  from openpilot.system.ui.widgets import compact
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  from openpilot.system.ui.lib.text_measure import measure_text_cached
  multilang._language = language
  multilang.setup()
  gui_app.on_language_changed(language)
  clicks = []
  page = CompactPage(lambda: tr('Settings'))
  page._header.action = compact.CompactButton(lambda: tr(action_label), lambda: clicks.append(True))
  gui_app.push_widget(page)
  labels = []
  real_label = compact.gui_label
  def label(rect, text, size, *args, **kwargs):
    labels.append((text, rect, size))
    real_label(rect, text, size, *args, **kwargs)
  monkeypatch.setattr(compact, 'gui_label', label)
  draw(page)
  action_text, rect, size = next(entry for entry in labels if entry[0] == tr(action_label))
  assert measure_text_cached(gui_app.font(), action_text, size).x <= rect.width
  button = page._header.action
  assert button.rect.height >= 52
  assert button.rect.width >= 104
  pos = MousePos(button.rect.x + button.rect.width / 2, button.rect.y + button.rect.height / 2)
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, True, False, True, 0), MouseEvent(pos, 0, False, True, False, .1)])
  draw(page)
  assert clicks == [True]


@pytest.mark.parametrize('language', ['zh-CHS', 'en'])
def test_long_header_title_keeps_full_text_and_updates_in_place(monkeypatch, language):
  from openpilot.system.ui.widgets.compact import CompactButton
  sources = ['Minimum Speed to Pause Lateral Control', 'Select Torque Control Tune Version']
  current_title = [sources[0]]
  page = CompactPage(lambda: tr(current_title[0]))
  page._header.action = CompactButton(lambda: tr('Description'), lambda: None)
  gui_app.push_widget(page)
  drawn = []
  real_draw = rl.draw_text_ex
  def record(font, text, *args):
    drawn.append(text)
    real_draw(font, text, *args)
  monkeypatch.setattr(rl, 'draw_text_ex', record)
  for target, source in [(language, sources[0]), ('en' if language == 'zh-CHS' else 'zh-CHS', sources[1])]:
    current_title[0] = source
    multilang._language = target
    multilang.setup()
    gui_app.on_language_changed(target)
    drawn.clear()
    draw(page)
    assert tr(source) in drawn
    assert not any(text.endswith('...') for text in drawn)


def test_header_scroll_resets_when_title_language_or_action_width_changes(monkeypatch):
  from openpilot.system.ui.widgets.compact import CompactButton
  from openpilot.system.ui.widgets.label import ScrollState
  current = ['Minimum Speed to Pause Lateral Control']
  clock = [10]
  monkeypatch.setattr(rl, 'get_time', lambda: clock[0])
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  page = CompactPage(lambda: tr(current[0]))
  page._header.action = CompactButton(lambda: tr('Description'), lambda: None)
  gui_app.push_widget(page)
  draw(page)
  title = page._header._title_label
  assert title._needs_scroll
  clock[0] = 13
  draw(page)
  draw(page)
  assert title._scroll_state == ScrollState.SCROLLING
  assert title._scroll_offset < 0
  current[0] = 'Select Torque Control Tune Version'
  draw(page)
  assert title._scroll_state == ScrollState.STARTING and title._scroll_offset == 0
  clock[0] = 16
  draw(page)
  draw(page)
  assert title._scroll_offset < 0
  page._header.action_width = 240
  draw(page)
  assert title._scroll_state == ScrollState.STARTING and title._scroll_offset == 0
  multilang._language = 'zh-CHS'
  multilang.setup()
  gui_app.on_language_changed('zh-CHS')
  draw(page)
  assert title._scroll_offset == 0
  assert title._cached_wrapped_lines == [tr(current[0])]


@pytest.mark.parametrize('operation', ['refresh', 'cache'])
def test_model_operation_detail_exposes_full_live_status_without_submitting(model_panel, monkeypatch, operation):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  clock = [100]
  monkeypatch.setattr(models.time, 'monotonic', lambda: clock[0])
  controller = model_panel.controller
  if operation == 'refresh':
    controller._refresh_models()
    item = controller.refresh_item
    waiting = 'Fetching Latest Models'
    timeout = 'Model list refresh has not completed. Check the network and retry.'
    request = 'ModelManager_LastSyncTime'
  else:
    controller._clear_cache()
    gui_app.get_active_widget()._confirm_button_callback()
    item = controller.clear_cache_item
    waiting = 'Waiting for model cache cleanup...'
    timeout = 'Model service has not completed the cache request. Retry.'
    request = 'ModelManager_ClearCache'
  row = model_panel._rows[item][0]
  assert not resolve(row.available)
  row._handle_mouse_release(rl.Vector2(row.rect.x + 100, row.rect.y + 100))
  detail = gui_app.get_active_widget()
  assert detail is not model_panel
  saved = ui_state.params.get(request)
  for language, timestamp, status in [('zh-CHS', 100, waiting), ('en', 131, timeout), ('zh-CHS', 131, timeout)]:
    clock[0] = timestamp
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    draw(detail)
    text = resolve(detail._list._scroller.items[0].text)
    assert tr(status) in text
    assert ui_state.params.get(request) == saved
  gui_app.pop_widget()
  assert gui_app.get_active_widget() is model_panel
  assert resolve(row.available)


def test_software_operation_detail_exposes_full_value_as_literal_text(monkeypatch):
  from openpilot.selfdrive.ui.layouts.settings import software
  signals = []
  monkeypatch.setattr(software.os, 'system', signals.append)
  panel = make_panel('software')
  gui_app.push_widget(panel)
  controller = panel.controller
  controller._on_download_update()
  draw(panel)
  row = panel._rows[controller._download_btn][0]
  row.help_callback()
  detail = gui_app.get_active_widget()
  draw(detail)
  assert tr('Waiting for update service...') in resolve(detail._list._scroller.items[0].text)
  assert len(signals) == 1
  ui_state.params.put('UpdaterState', '<update>&step', block=True)
  draw(detail)
  assert '&lt;update&gt;&amp;step' in resolve(detail._list._scroller.items[0].text)
  gui_app.pop_widget()
  assert gui_app.get_active_widget() is panel
  assert len(signals) == 1


def touch_action_info(row, monkeypatch):
  from openpilot.system.ui.lib.application import MousePos, MouseEvent
  row.set_parent_rect(rl.Rectangle(0, HEADER_HEIGHT, 536, 184))
  row.set_position(20, HEADER_HEIGHT + 8)
  rl.begin_drawing()
  row.render()
  rl.end_drawing()
  # The top right of an action card is a dedicated information touch target.
  pos = MousePos(row.rect.x + row.rect.width - 38, row.rect.y + 32)
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, True, False, True, 0),
                                               MouseEvent(pos, 0, False, True, False, .1)])
  rl.begin_drawing()
  row.render()
  rl.end_drawing()
  monkeypatch.setattr(gui_app, '_mouse_events', [])


@pytest.mark.parametrize('key,index,status_attr,loading_attr,waiting,failed,completed', [
  ('trips', 0, '_status', '_loading', 'Fetching drive statistics', 'Unable to fetch drive statistics', 'Drive statistics updated'),
  ('firehose', 2, '_stats_status', '_stats_loading', 'Fetching training statistics', 'Unable to fetch training statistics',
   'Training statistics updated'),
])
@pytest.mark.parametrize('busy', [False, True])
@pytest.mark.parametrize('language', ['zh-CHS', 'en'])
def test_statistics_info_touch_reads_live_status_without_refresh(request, monkeypatch, key, index, status_attr, loading_attr,
                                                               waiting, failed, completed, busy, language):
  from openpilot.system.ui.widgets.compact import CompactInfoPage
  panel = request.getfixturevalue('trips_panel' if key == 'trips' else 'firehose_panel')
  controller = panel.controller
  multilang._language = language
  multilang.setup()
  gui_app.on_language_changed(language)
  setattr(controller, status_attr, waiting if busy else failed)
  setattr(controller, loading_attr, busy)
  controller._refresh_event.clear()
  gui_app.push_widget(panel)
  draw(panel)
  row = panel._list._scroller.items[index]
  touch_action_info(row, monkeypatch)
  detail = gui_app.get_active_widget()
  assert isinstance(detail, CompactInfoPage)
  draw(detail)
  assert tr(waiting if busy else failed) in resolve(detail._list._scroller.items[0].text)
  assert not controller._refresh_event.is_set()
  # Completion and a language switch update the same open information page.
  setattr(controller, status_attr, completed)
  setattr(controller, loading_attr, False)
  multilang._language = 'en' if language == 'zh-CHS' else 'zh-CHS'
  multilang.setup()
  gui_app.on_language_changed(multilang.language)
  draw(detail)
  assert tr(completed) in resolve(detail._list._scroller.items[0].text)
  assert not controller._refresh_event.is_set()
  gui_app.pop_widget()
  assert gui_app.get_active_widget() is panel
  # Reading details leaves the original refresh action available on return.
  row.callback()
  assert controller._refresh_event.is_set()


@pytest.mark.parametrize('language', ['zh-CHS', 'en'])
def test_native_wifi_scanning_hint_updates_without_recreating(language):
  from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import ScanningButton
  multilang._language = language
  multilang.setup()
  gui_app.on_language_changed(language)
  button = ScanningButton()
  draw(button)
  assert button.get_value() == tr('searching for networks')
  multilang._language = 'en' if language == 'zh-CHS' else 'zh-CHS'
  multilang.setup()
  gui_app.on_language_changed(multilang.language)
  draw(button)
  assert button.get_value() == tr('searching for networks')


@pytest.mark.parametrize('language', ['zh-CHS', 'en'])
@pytest.mark.parametrize('entry', ['install', 'branch'])
def test_action_info_touch_reads_details_without_starting_operation(monkeypatch, language, entry):
  from openpilot.selfdrive.ui.layouts.settings import software
  from openpilot.system.ui.widgets.compact import CompactInfoPage
  signals = []
  monkeypatch.setattr(software.os, 'system', signals.append)
  multilang._language = language
  multilang.setup()
  gui_app.on_language_changed(language)
  ui_state.params.put_bool('UpdateAvailable', True, block=True)
  version = '2026.11-' + 'abcdef0123456789' * 4
  notes = 'Release notes\n' + '\n'.join(f'Change {index}: calibration and display' for index in range(14))
  ui_state.params.put('UpdaterNewDescription', version, block=True)
  ui_state.params.put('UpdaterNewReleaseNotes', notes.encode(), block=True)
  branch = 'release-mici-' + 'feature-' * 10
  ui_state.params.put('UpdaterTargetBranch', branch, block=True)
  panel = make_panel('software')
  gui_app.push_widget(panel)
  item = panel.controller._install_btn if entry == 'install' else panel.controller._branch_btn
  row = panel._rows[item][0]
  assert resolve(row.available)
  touch_action_info(row, monkeypatch)
  detail = gui_app.get_active_widget()
  assert isinstance(detail, CompactInfoPage)
  draw(detail)
  text = resolve(detail._list._scroller.items[0].text)
  assert (version if entry == 'install' else branch) in text
  if entry == 'install':
    assert 'Change 13' in text
    assert detail._list._scroller.content_size > detail._list.rect.height
    detail._list._scroller.scroll_panel.set_offset(detail._list.rect.height - detail._list._scroller.content_size)
    draw(detail)
    assert detail._list._scroller.scroll_panel.get_offset() < 0
  assert not ui_state.params.get_bool('DoReboot')
  assert not signals
  gui_app.pop_widget()
  assert gui_app.get_active_widget() is panel
  assert ui_state.params.get('UpdaterTargetBranch') == branch
  if entry == 'install':
    # The original card action remains usable after returning from its details.
    row.callback()
    assert ui_state.params.get_bool('DoReboot')


@pytest.mark.parametrize('operation', ['refresh', 'cache'])
@pytest.mark.parametrize('phase', ['waiting', 'retry'])
def test_model_retry_info_touch_keeps_request_and_does_not_open_confirmation(model_panel, monkeypatch, operation, phase):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  monkeypatch.setattr(models.time, 'monotonic', lambda: 100 if phase == 'waiting' else 131)
  controller = model_panel.controller
  if operation == 'refresh':
    controller._refresh_started = 100
    ui_state.params.put('ModelManager_LastSyncTime', 0, block=True)
    item = controller.refresh_item
    status = 'Fetching Latest Models' if phase == 'waiting' else 'Model list refresh has not completed. Check the network and retry.'
    request = 'ModelManager_LastSyncTime'
  else:
    controller._cache_request_started = 100
    ui_state.params.put_bool('ModelManager_ClearCache', True, block=True)
    item = controller.clear_cache_item
    status = 'Waiting for model cache cleanup...' if phase == 'waiting' else 'Model service has not completed the cache request. Retry.'
    request = 'ModelManager_ClearCache'
  model_panel.refresh()
  assert item.action_item.enabled == (phase == 'retry')
  before = ui_state.params.get(request)
  touch_action_info(model_panel._rows[item][0], monkeypatch)
  detail = gui_app.get_active_widget()
  from openpilot.system.ui.widgets.compact import CompactInfoPage
  assert isinstance(detail, CompactInfoPage)
  draw(detail)
  assert tr(status) in resolve(detail._list._scroller.items[0].text)
  assert ui_state.params.get(request) == before
  assert not ui_state.params.get('ModelManager_DownloadIndex')
  gui_app.pop_widget()
  assert gui_app.get_active_widget() is model_panel


@pytest.mark.parametrize('busy', [False, True])
def test_swiping_from_action_info_icon_does_not_open_details_or_run_action(monkeypatch, busy):
  from openpilot.system.ui.lib.application import MousePos, MouseEvent
  from openpilot.selfdrive.ui.layouts.settings import software
  calls = []
  monkeypatch.setattr(software.os, 'system', calls.append)
  ui_state.params.put('UpdaterState', 'downloading...' if busy else 'idle', block=True)
  panel = make_panel('software')
  gui_app.push_widget(panel)
  draw(panel)
  row = panel._rows[panel.controller._download_btn][0]
  panel._list.focus_item(row)
  draw(panel)
  x, y = row._info.rect.x + 32, row._info.rect.y + 32
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(MousePos(x - offset, y), 0, index == 0, index == 3, index < 3, index * .1)
                                               for index, offset in enumerate((0, 70, 140, 210))])
  draw(panel)
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  assert gui_app.get_active_widget() is panel
  assert not calls
  assert not ui_state.params.get_bool('DoReboot')


def test_readonly_information_page_displays_full_value():
  from openpilot.system.ui.widgets.list_view import text_item
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel
  from types import SimpleNamespace
  value = '0123456789' * 12
  item = text_item('Serial', value)
  controller = CompactPage('controller')
  controller._scroller = SimpleNamespace(_items=[item])
  panel = SettingsPanel('Device', controller)
  gui_app.push_widget(panel)
  row = panel._rows[item][0]
  row.callback()
  detail = gui_app.get_active_widget()
  assert value in resolve(detail._list._scroller.items[0].text)


def test_force_onroad_enters_small_display_view_without_ignition(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
  home, road = object(), object()
  result = []
  state = SimpleNamespace(_onboarding_window=object(), _prev_onroad=False, _onroad_time_delay=None,
                          _prev_standstill=False, _home_layout=home, _onroad_layout=road,
                          _scroll_to=lambda widget: result.append(widget))
  monkeypatch.setattr(ui_state, 'force_onroad', True)
  monkeypatch.setattr(ui_state, 'sm', {'carState': SimpleNamespace(standstill=True)})
  monkeypatch.setattr(gui_app, 'widget_in_stack', lambda _: False)
  monkeypatch.setattr(gui_app, 'pop_widgets_to', lambda widget, callback: callback())
  monkeypatch.setattr(rl, 'get_time', lambda: 5)
  MiciMainLayout._handle_transitions(state)
  assert state._prev_onroad
  assert state._onroad_time_delay == 5
  monkeypatch.setattr(rl, 'get_time', lambda: 8)
  MiciMainLayout._handle_transitions(state)
  assert result == [road]


def test_manual_vehicle_confirmation_uses_actual_offroad_state(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.platform_selector import PlatformSelector
  from types import SimpleNamespace
  selector = PlatformSelector()
  monkeypatch.setattr(ui_state, 'started', True)
  selector._on_platform_selected(SimpleNamespace(selection_ref='mock'), DialogResult.CONFIRM)
  dialog = gui_app.get_active_widget()
  assert tr('This setting will take effect once the device enters offroad state.') in dialog._html_renderer.raw_text
  assert 'mock' in dialog._html_renderer.raw_text


@pytest.fixture
def vehicle_catalog(tmp_path, monkeypatch):
  import json
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle import platform_selector
  path = tmp_path / 'vehicles.json'
  catalog = {'Toyota Corolla 2021': {'platform': 'TOYOTA_COROLLA_TSS2', 'brand': 'toyota', 'make': 'Toyota',
                                    'model': 'Corolla', 'year': ['2021'], 'package': 'All'}}
  path.write_text(json.dumps(catalog))
  monkeypatch.setattr(platform_selector, 'CAR_LIST_JSON_OUT', str(path))
  return path, catalog


@pytest.mark.parametrize('confirm', [False, True])
def test_manual_vehicle_removal_requires_confirmation_and_refreshes(vehicle_catalog, confirm):
  panel = make_panel('vehicle')
  gui_app.push_widget(panel)
  _, catalog = vehicle_catalog
  bundle = {**catalog['Toyota Corolla 2021'], 'name': 'Toyota Corolla 2021'}
  ui_state.params.put('CarPlatformBundle', bundle, block=True)
  panel.refresh()
  controller = panel.controller
  controller._platform_selector._on_clicked()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  assert 'Toyota Corolla 2021' in dialog._label._text
  assert ui_state.params.get('CarPlatformBundle') == bundle
  if confirm:
    dialog._confirm_button_callback()
    assert ui_state.params.get('CarPlatformBundle') is None
    assert controller._current_brand == ''
    assert controller._vehicle_item.title == tr('No vehicle selected')
  else:
    dialog._cancel_button_callback()
    assert ui_state.params.get('CarPlatformBundle') == bundle


@pytest.mark.parametrize('operation', ['select', 'remove'])
def test_vehicle_confirmation_preserves_external_selection(vehicle_catalog, operation):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.platform_selector import PlatformSelector
  selector = PlatformSelector()
  if operation == 'remove':
    ui_state.params.put('CarPlatformBundle', {'brand': 'toyota', 'name': 'Original'}, block=True)
    selector._on_clicked()
  else:
    selector._on_platform_selected(SimpleNamespace(selection_ref='Toyota Corolla 2021'), DialogResult.CONFIRM)
  dialog = gui_app.get_active_widget()
  replacement = {'brand': 'tesla', 'name': 'External selection'}
  ui_state.params.put('CarPlatformBundle', replacement, block=True)
  dialog._confirm_button_callback()
  assert ui_state.params.get('CarPlatformBundle') == replacement
  assert tr('Vehicle selection changed. Reopen the vehicle settings and try again.') in gui_app.get_active_widget()._label._text


def test_vehicle_picker_confirm_saves_catalog_bundle_and_updates_brand(vehicle_catalog):
  _, catalog = vehicle_catalog
  panel = make_panel('vehicle')
  gui_app.push_widget(panel)
  selector = panel.controller._platform_selector
  selector._on_clicked()
  picker = gui_app.get_active_widget()
  draw(picker)
  picker._compact_page._list._scroller.items[0].callback()
  draw(picker)
  picker._compact_page._list._scroller.items[1].callback()
  assert picker.selection_ref == 'Toyota Corolla 2021'
  assert ui_state.params.get('CarPlatformBundle') is None
  picker._compact_confirm._click_callback()
  confirm = gui_app.get_active_widget()
  assert 'Toyota Corolla 2021' in confirm._html_renderer.raw_text
  confirm._confirm_button_callback()
  assert ui_state.params.get('CarPlatformBundle') == {**catalog['Toyota Corolla 2021'], 'name': 'Toyota Corolla 2021'}
  assert panel.controller._current_brand == 'toyota'
  assert panel.controller._vehicle_item.title == 'Toyota Corolla 2021'
  panel.refresh()
  assert panel.controller._brand_items[0] in panel._source_items


@pytest.mark.parametrize('invalid', [None, '{', '{}', '{"bad": {}}',
                                   '{"bad": {"platform": "P", "make": "M", "brand": "B", "year": null}}'])
def test_vehicle_catalog_failure_can_retry_without_reopening_panel(vehicle_catalog, invalid):
  import json
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.platform_selector import PlatformSelector
  path, catalog = vehicle_catalog
  if invalid is None:
    path.unlink()
  else:
    path.write_text(invalid)
  selector = PlatformSelector()
  selector._on_clicked()
  assert tr('Unable to load the vehicle list. Check the installation and try again.') in gui_app.get_active_widget()._label._text
  assert not selector._platforms
  gui_app.pop_widget()
  path.write_text(json.dumps(catalog))
  selector._on_clicked()
  assert isinstance(gui_app.get_active_widget(), TreeOptionDialog)
  assert selector._platforms == catalog


@pytest.mark.parametrize('bundle', [[], {}, {'brand': [], 'name': []}])
def test_invalid_manual_vehicle_bundle_can_be_removed(vehicle_catalog, bundle):
  ui_state.params.put('CarPlatformBundle', bundle, block=True)
  panel = make_panel('vehicle')
  gui_app.push_widget(panel)
  panel.refresh()
  assert panel.controller._vehicle_item.title == tr('Invalid manual vehicle selection')
  assert panel.controller._current_brand == ''
  panel.controller._platform_selector._on_clicked()
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get('CarPlatformBundle') is None


def test_vehicle_search_prompts_use_current_language(vehicle_catalog, monkeypatch):
  from openpilot.system.ui.sunnypilot.widgets import tree_dialog
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.platform_selector import PlatformSelector
  prompts = []
  class CaptureInput:
    def __init__(self, title, sub_title, **kwargs):
      prompts.append((title, sub_title))
    def show(self):
      pass
  monkeypatch.setattr(tree_dialog, 'InputDialogSP', CaptureInput)
  PlatformSelector()._on_clicked()
  picker = gui_app.get_active_widget()
  picker._on_search_clicked()
  assert prompts[-1] == (tr('Search your vehicle'), tr('Enter model year (e.g., 2021) and model (Toyota Corolla):'))
  assert prompts[-1][0] != 'Search your vehicle'
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  picker._on_search_clicked()
  assert prompts[-1] == ('Search your vehicle', 'Enter model year (e.g., 2021) and model (Toyota Corolla):')


def test_old_numeric_detail_is_disabled_after_changing_subpage():
  ui_state.params.put('LateralPositionOffset', 0, block=True)
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  item = panel.controller._lat_position_offset
  panel._open_number(item, lambda: item.title, lambda: item.description)
  detail = gui_app.get_active_widget()
  panel.controller._set_current_panel(PanelType.LANE_CHANGE)
  detail.change(1)
  assert item not in panel._source_items
  assert ui_state.params.get('LateralPositionOffset') == 0


def test_old_brand_enum_does_not_save_after_brand_switch(monkeypatch):
  ui_state.CP = car.CarParams.new_message(brand='hyundai', alphaLongitudinalAvailable=True)
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  ui_state.params.put('HyundaiLongitudinalTuning', 0, block=True)
  panel = make_panel('vehicle')
  gui_app.push_widget(panel)
  item = panel.controller._brand_items[0]
  panel._open_enum(item, lambda: item.title)
  detail = gui_app.get_active_widget()
  ui_state.CP = car.CarParams.new_message(brand='tesla')
  detail._list._scroller.items[1].callback()
  assert ui_state.params.get('HyundaiLongitudinalTuning') == 0
  assert item not in panel._source_items


def test_removed_source_button_does_not_invoke_old_callback(monkeypatch):
  panel = make_panel('vehicle')
  gui_app.push_widget(panel)
  item = panel.controller._vehicle_item
  calls = []
  item.callback = lambda: calls.append(True)
  row = panel._rows[item][0]
  monkeypatch.setattr(panel.controller, '_update_state', lambda: None)
  panel.controller._scroller._items = []
  row.callback()
  assert calls == []


def test_external_numeric_values_refresh_without_writing_defaults():
  panel = make_panel('display')
  gui_app.push_widget(panel)
  ui_state.params.put('OnroadScreenOffTimer', 600, block=True)
  panel.refresh()
  assert panel.controller._onroad_brightness_timer.action_item.current_value == 15
  ui_state.params.put('InteractivityTimeout', 90, block=True)
  panel.refresh()
  assert panel.controller._interactivity_timeout.action_item.current_value == 90


def test_external_enum_values_refresh_and_selection_saves_before_return():
  panel = make_panel('device')
  gui_app.push_widget(panel)
  item = panel.controller._audible_alert_mode_item
  ui_state.params.put('AudibleAlertMode', 1, block=True)
  panel.refresh()
  assert item.action_item.selected_button == 1
  assert resolve(panel._rows[item][0].value) == tr('Warnings Only')
  panel._open_enum(item, lambda: item.title)
  gui_app.get_active_widget()._list._scroller.items[2].callback()
  assert ui_state.params.get('AudibleAlertMode') == 2
  assert gui_app.get_active_widget() is panel
  panel.refresh()
  assert item.action_item.selected_button == 2


@pytest.mark.parametrize('state', ['checking...', 'downloading...', 'finalizing update...'])
def test_updater_status_uses_current_language(state):
  panel = make_panel('software')
  gui_app.push_widget(panel)
  ui_state.params.put('UpdaterState', state, block=True)
  draw(panel)
  assert panel.controller._download_btn.action_item.value == tr(state)
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(panel)
  assert panel.controller._download_btn.action_item.value == state


def test_old_update_dates_do_not_use_english_month_names(monkeypatch):
  import datetime
  from openpilot.selfdrive.ui.layouts.settings import software
  date = datetime.datetime(2020, 1, 2, tzinfo=datetime.UTC)
  monkeypatch.setattr(software, 'system_time_valid', lambda: True)
  assert software.time_ago(date) == '2020-01-02'
  monkeypatch.setattr(software, 'system_time_valid', lambda: False)
  assert software.time_ago(date) == '2020-01-02'


def test_static_action_label_switches_language_without_rebuilding():
  from types import SimpleNamespace
  from openpilot.system.ui.widgets.list_view import button_item
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel
  item = button_item(tr('System Logs'), tr('CLEAR'))
  controller = CompactPage('controller')
  controller._scroller = SimpleNamespace(_items=[item])
  panel = SettingsPanel('Developer', controller)
  gui_app.push_widget(panel)
  draw(panel)
  row = panel._rows[item][0]
  assert resolve(row.value) == tr('CLEAR')
  multilang._language = 'en'
  multilang.setup()
  assert resolve(row.value) in ('CLEAR', 'Clear')


def test_usb_detection_runs_once_per_second(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import developer
  panel = make_panel('developer')
  gui_app.push_widget(panel)
  refreshes = []
  monkeypatch.setattr(panel.controller, '_refresh_usb_state', lambda: refreshes.append(True))
  panel.controller._last_usb_refresh = -1
  monkeypatch.setattr(developer.time, 'monotonic', lambda: 10)
  panel.refresh()
  panel.refresh()
  assert len(refreshes) == 1
  monkeypatch.setattr(developer.time, 'monotonic', lambda: 11)
  panel.refresh()
  assert len(refreshes) == 2


def developer_with_usb(monkeypatch):
  panel = make_panel('developer')
  controller = panel.controller
  monkeypatch.setattr(controller, '_refresh_usb_state', lambda: None)
  controller._apply_usb_state([{'device': '/dev/mock1', 'size': '8G', 'fstype': 'vfat'}], True, '/dev/mock1')
  controller._usb_expanded = True
  gui_app.push_widget(panel)
  draw(panel)
  return panel, controller


def test_usb_export_finishes_once_and_shows_translated_result(monkeypatch):
  from openpilot.system import usb_mount
  panel, controller = developer_with_usb(monkeypatch)
  controller._usb_exporting = True
  controller._usb_events.put(('progress', (100, usb_mount.UsbMessage('System logs: {filename}', filename='last.log'))))
  controller._usb_events.put(('export', (True, usb_mount.UsbMessage('Exported {count}/{total} sources', count=2, total=2))))
  draw(panel)
  result = gui_app.get_active_widget()
  assert isinstance(result, ConfirmDialog)
  assert '已导出 2/2 个来源' in result._html_renderer.raw_text
  draw(result)
  assert result._compact_view._list._scroller.content_size <= result._compact_view._list.rect.height
  assert not controller._usb_exporting and not controller._usb_export_done
  gui_app.pop_widget()
  draw(panel)
  assert gui_app.get_active_widget() is panel
  assert controller._usb_export_logs_item.action_item.enabled


def test_usb_export_exception_restores_controls_and_shows_failure(monkeypatch):
  panel, controller = developer_with_usb(monkeypatch)
  def failure(*args, **kwargs):
    raise OSError('read error')
  controller._usb_exporting = True
  controller._do_usb_export(failure)
  assert controller._usb_exporting  # The worker has not mutated UI state.
  draw(panel)
  result = gui_app.get_active_widget()
  assert isinstance(result, ConfirmDialog)
  assert 'USB 导出失败：read error' in result._html_renderer.raw_text
  assert controller._usb_export_logs_item.action_item.enabled


def test_usb_export_blocks_unmount_and_duplicate_export(monkeypatch):
  from openpilot.system import usb_mount
  panel, controller = developer_with_usb(monkeypatch)
  operations = []
  monkeypatch.setattr(usb_mount, 'unmount_usb', lambda *args: operations.append('unmount'))
  monkeypatch.setattr(usb_mount, 'export_logs', lambda *args, **kwargs: operations.append('export'))
  controller._usb_exporting = True
  draw(panel)
  assert not controller._usb_mount_item.action_item.enabled
  controller._on_usb_mount_clicked()
  controller._on_usb_export_logs_clicked()
  assert not operations


def test_usb_progress_card_has_bar_and_full_message(monkeypatch):
  from openpilot.system import usb_mount
  panel, controller = developer_with_usb(monkeypatch)
  controller._usb_exporting = True
  controller._usb_events.put(('progress', (37, usb_mount.UsbMessage('Route data: {filename}', filename='route/' + 'x' * 80))))
  draw(panel)
  row = panel._rows[controller._usb_export_progress_item][0]
  assert resolve(row.progress) == 37
  rectangles = []
  monkeypatch.setattr(rl, 'draw_rectangle_rec', lambda rect, color: rectangles.append((rect.width, rect.height)))
  row.render()
  assert any(height == 4 and width == pytest.approx((row.rect.width - 48) * .37) for width, height in rectangles)
  row.callback()
  info = gui_app.get_active_widget()
  assert '行程数据：route/' + 'x' * 80 in resolve(info._list._scroller.items[0].text)


def test_usb_snapshot_before_mount_cannot_overwrite_new_state(monkeypatch):
  _panel, controller = developer_with_usb(monkeypatch)
  controller._usb_generation = 1
  controller._usb_refresh_running = True
  controller._usb_events.put(('refresh', (0, [], False, None)))
  controller._process_usb_events()
  assert controller._usb_mounted
  assert not controller._usb_refresh_running
  assert controller._last_usb_refresh == -1


def test_usb_status_and_nested_errors_follow_language_switch(monkeypatch):
  from openpilot.system import usb_mount
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.developer import translate_usb_message
  panel, controller = developer_with_usb(monkeypatch)
  message = usb_mount.UsbMessage('Export incomplete: {count}/{total} sources copied.\n{details}', count=0, total=1,
                                 details=[usb_mount.UsbMessage('{path} -> {message}', path='/source',
                                          message=usb_mount.UsbMessage('USB copy failed: {error}', error='error'))])
  assert 'USB 复制失败' in translate_usb_message(message)
  assert '已挂载' in controller._usb_status_text
  multilang._language = 'en'
  multilang.setup()
  draw(panel)
  assert controller._usb_status_text == 'Mounted: /dev/mock1'
  assert 'USB copy failed: error' in translate_usb_message(message)


def test_usb_message_templates_remain_in_translation_extraction():
  from openpilot.common.basedir import BASEDIR
  from openpilot.selfdrive.ui.translations.potools import extract_strings
  files = ['system/usb_mount.py', 'selfdrive/ui/sunnypilot/layouts/settings/developer.py']
  entries = extract_strings(files, BASEDIR, extra_markers=('UsbMessage',))
  assert all(entry.msgid in multilang._translations for entry in entries)


def wait_for_usb_result(controller):
  deadline = time.monotonic() + 1
  while controller._usb_events.empty() and time.monotonic() < deadline:
    time.sleep(.01)
  assert not controller._usb_events.empty()


def test_slow_usb_scan_runs_in_background_while_page_renders(monkeypatch):
  import threading
  from openpilot.system import usb_mount
  entered, release = threading.Event(), threading.Event()
  drive = {'device': '/dev/mock1', 'size': '8G', 'fstype': 'vfat'}
  def scan():
    entered.set()
    assert release.wait(2)
    return [drive]
  monkeypatch.setattr(usb_mount, 'get_usb_drives', scan)
  monkeypatch.setattr(usb_mount, 'is_mounted', lambda _: False)
  panel = make_panel('developer')
  controller = panel.controller
  controller._refresh_usb_state()
  try:
    assert entered.wait(1)
    assert controller._usb_refresh_running
    gui_app.push_widget(panel)
    draw(panel)
    assert gui_app.get_active_widget() is panel
    assert controller._usb_drives == []
  finally:
    release.set()
  wait_for_usb_result(controller)
  controller._process_usb_events()
  assert controller._usb_drives == [drive]


def test_slow_usb_mount_finishes_on_ui_thread(monkeypatch):
  import threading
  from openpilot.system import usb_mount
  entered, release = threading.Event(), threading.Event()
  panel, controller = developer_with_usb(monkeypatch)
  monkeypatch.setattr(usb_mount, 'is_mounted', lambda _: False)
  def mount(device, fstype):
    entered.set()
    assert release.wait(2)
    return usb_mount.MountResult(True, usb_mount.UsbMessage('Mounted {device} at {path}', device=device, path='/usb'))
  monkeypatch.setattr(usb_mount, 'mount_usb', mount)
  controller._on_usb_mount_clicked()
  try:
    assert entered.wait(1)
    draw(panel)
    assert controller._usb_task_running
    assert gui_app.get_active_widget() is panel
  finally:
    release.set()
  wait_for_usb_result(controller)
  draw(panel)
  assert not controller._usb_task_running
  result = gui_app.get_active_widget()
  assert isinstance(result, ConfirmDialog)
  assert resolve(result._label._text) == '已将 /dev/mock1 挂载到 /usb'


def test_map_region_fetch_defers_widget_creation_to_ui_thread(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  panel = make_panel('osm')
  gui_app.push_widget(panel)
  controller = panel.controller
  monkeypatch.setattr(osm.requests, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None,
                                                                               json=lambda: {'CN': {'full_name': 'China'}}))
  controller._do_select_region('Country', controller._country_btn)
  assert gui_app.get_active_widget() is panel
  controller._update_state()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, TreeOptionDialog)
  assert dialog.folders[0].nodes[0].ref == 'CN'


def test_cruise_controls_are_disabled_until_vehicle_compatibility_is_known():
  ui_state.params.put_bool('CustomAccIncrementsEnabled', True, block=True)
  panel = make_panel('cruise')
  gui_app.push_widget(panel)
  assert not panel.controller.custom_acc_toggle.action_item.enabled
  assert not panel.controller.custom_acc_short_increment.action_item.enabled
  assert not panel.controller.accel_profile_selector.action_item.enabled


def test_long_press_increment_preserves_non_linear_storage_mapping():
  from cereal import custom
  ui_state.params.put_bool('CustomAccIncrementsEnabled', True, block=True)
  ui_state.CP = car.CarParams.new_message(openpilotLongitudinalControl=True, pcmCruise=False)
  ui_state.CP_SP = custom.CarParamsSP.new_message()
  ui_state.has_longitudinal_control = True
  panel = make_panel('cruise')
  gui_app.push_widget(panel)
  item = panel.controller.custom_acc_long_increment
  panel._open_number(item, lambda: item.title, lambda: item.description)
  gui_app.get_active_widget()._list._scroller.items[2].callback()
  wait_param('CustomAccLongPressIncrement', 10)


def test_mads_limited_platform_preserves_forced_modes():
  from openpilot.sunnypilot.mads.helpers import MadsSteeringModeOnBrake
  ui_state.params.put('CarPlatformBundle', {'brand': 'rivian'}, block=True)
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  panel.controller._set_current_panel(PanelType.MADS)
  draw(panel)
  child = panel._active
  assert not child._main_cruise_toggle.action_item.enabled
  assert not child._unified_engagement_toggle.action_item.enabled
  assert child._steering_mode.action_item.enabled_buttons == {MadsSteeringModeOnBrake.DISENGAGE}


def test_speed_limit_assist_remains_unavailable_for_disallowed_platform():
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.cruise import PanelType as CruisePanelType
  from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Mode
  ui_state.CP = car.CarParams.new_message(brand='rivian', openpilotLongitudinalControl=True)
  ui_state.CP_SP = custom.CarParamsSP.new_message()
  ui_state.has_longitudinal_control = True
  panel = make_panel('cruise')
  gui_app.push_widget(panel)
  panel.controller._set_current_panel(CruisePanelType.SLA)
  draw(panel)
  assert Mode.assist not in panel._active._speed_limit_mode.action_item.enabled_buttons


@pytest.fixture
def map_panel(monkeypatch, tmp_path):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  monkeypatch.setattr(osm, 'MAP_PATH', tmp_path / 'offline')
  # These state/interaction tests do not need disk scans. Separate tests below
  # exercise the scanner against real temporary directories.
  with monkeypatch.context() as setup:
    setup.setattr(osm.OSMLayout, '_update_map_size', lambda self: None)
    panel = make_panel('osm')
  monkeypatch.setattr(panel.controller, '_update_map_size', lambda: None)
  panel.controller._mem_params = Params(str(tmp_path / 'memory-params'))
  gui_app.push_widget(panel)
  return panel


def set_map_country(controller, country='CN', name='China'):
  controller._params.put('OsmLocationName', country, block=True)
  controller._params.put('OsmLocationTitle', name, block=True)
  controller._params.put_bool('OsmLocal', True, block=True)


@pytest.mark.parametrize('data', [{}, [], {'CN': {}}, {'CN': {'full_name': ''}}, {'CN': {'full_name': 2}}])
def test_map_malformed_region_data_offers_retry_without_all_states(map_panel, monkeypatch, data):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  monkeypatch.setattr(osm.requests, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None, json=lambda: data))
  controller._fetching_regions.add('State')
  controller._do_select_region('State', controller._state_btn)
  assert gui_app.get_active_widget() is map_panel
  controller._update_state()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  assert tr('Failed to fetch map regions. Check the network and retry.') in resolve(dialog._label._text)
  assert not controller._fetching_regions
  retries = []
  monkeypatch.setattr(controller, '_select_region', retries.append)
  dialog._confirm_button_callback()
  assert retries == ['State']


def test_map_http_failure_never_opens_state_picker(map_panel, monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  def check_status():
    raise osm.requests.HTTPError('503')
  monkeypatch.setattr(osm.requests, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=check_status,
                                                                               json=lambda: {'CA': {'full_name': 'California'}}))
  controller = map_panel.controller
  controller._pending_country = ('US', 'United States')
  controller._do_select_region('State', controller._state_btn)
  controller._update_state()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  dialog._cancel_button_callback()
  assert controller._pending_country is None
  assert not controller._params.get('OsmLocationName')


def test_map_fetch_runs_in_background_and_refresh_preserves_disabled_state(map_panel, monkeypatch):
  import threading
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  entered, release = threading.Event(), threading.Event()
  def get(*args, **kwargs):
    entered.set()
    assert release.wait(2)
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'CN': {'full_name': 'China'}})
  monkeypatch.setattr(osm.requests, 'get', get)
  controller = map_panel.controller
  controller._select_region('Country')
  try:
    assert entered.wait(1)
    draw(map_panel)
    assert gui_app.get_active_widget() is map_panel
    assert not controller._country_btn.action_item.enabled
    row = map_panel._rows[controller._country_btn][0]
    assert resolve(row.value) == tr('FETCHING...')
  finally:
    release.set()
  deadline = time.monotonic() + 1
  while controller._region_events.empty() and time.monotonic() < deadline:
    time.sleep(.01)
  assert not controller._region_events.empty()
  controller._update_state()
  assert isinstance(gui_app.get_active_widget(), TreeOptionDialog)
  assert not controller._fetching_regions


def test_map_us_selection_commits_only_after_state_and_download_confirmation(map_panel, monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  monkeypatch.setattr(osm.requests, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None,
                                                                               json=lambda: {'CA': {'full_name': 'California'}}))
  # Keep this selection-flow test deterministic; the separate test above
  # verifies the network thread and UI handoff.
  monkeypatch.setattr(controller, '_select_region', lambda kind: controller._do_select_region(kind, controller._state_btn))
  controller._show_region_dialog('Country', controller._country_btn, [('CN', 'China'), ('US', 'United States')])
  country = gui_app.get_active_widget()
  draw(country)
  country._compact_page._list._scroller.items[1].callback()
  draw(country)
  country._compact_confirm._click_callback()
  assert controller._params.get('OsmLocationName') == 'CN'
  assert controller._pending_country == ('US', 'United States')
  controller._update_state()
  state_dialog = gui_app.get_active_widget()
  draw(state_dialog)
  assert state_dialog.folders[0].nodes[0].ref == 'All'
  state_dialog._compact_page._list._scroller.items[1].callback()
  draw(state_dialog)
  state_dialog._compact_confirm._click_callback()
  assert controller._params.get('OsmLocationName') == 'US'
  assert controller._params.get('OsmLocationTitle') == 'United States'
  assert controller._params.get('OsmStateName') == 'CA'
  assert controller._params.get('OsmStateTitle') == 'California'
  assert controller._pending_country is None
  confirmation = gui_app.get_active_widget()
  assert isinstance(confirmation, ConfirmDialog)
  confirmation._cancel_button_callback()
  assert not controller._params.get_bool('OsmDbUpdatesCheck')
  controller._update_db()
  gui_app.get_active_widget()._confirm_button_callback()
  assert controller._params.get_bool('OsmDbUpdatesCheck')
  assert controller._download_state == 'waiting'


def test_map_cancel_state_selection_preserves_previous_country_and_state(map_panel):
  controller = map_panel.controller
  set_map_country(controller)
  controller._pending_country = ('US', 'United States')
  controller._show_region_dialog('State', controller._state_btn, [('CA', 'California')])
  gui_app.get_active_widget()._set_result(DialogResult.CANCEL)
  assert controller._params.get('OsmLocationName') == 'CN'
  assert not controller._params.get('OsmStateName')
  assert controller._pending_country is None


@pytest.mark.parametrize('region_type', ['Country', 'State', 'PendingUS'])
def test_map_old_region_confirmation_preserves_external_selection(map_panel, region_type):
  controller = map_panel.controller
  if region_type == 'Country':
    set_map_country(controller)
    controller._show_region_dialog('Country', controller._country_btn, [('GE', 'Georgia')])
  else:
    set_map_country(controller, 'US', 'United States')
    controller._params.put('OsmStateName', 'CA', block=True)
    if region_type == 'PendingUS':
      set_map_country(controller)
      controller._pending_country = ('US', 'United States')
    controller._show_region_dialog('State', controller._state_btn, [('GA', 'Georgia')])
  picker = gui_app.get_active_widget()
  picker.selection_ref = 'GE' if region_type == 'Country' else 'GA'
  if region_type == 'State':
    controller._params.put('OsmStateName', 'NY', block=True)
  else:
    set_map_country(controller, 'FR', 'France')
  before = {key: controller._params.get(key) for key in ('OsmLocationName', 'OsmStateName', 'OsmLocal')}
  picker._set_result(DialogResult.CONFIRM)
  assert {key: controller._params.get(key) for key in before} == before
  assert not controller._params.get_bool('OsmDbUpdatesCheck')
  assert controller._pending_country is None
  alert = gui_app.get_active_widget()
  assert isinstance(alert, ConfirmDialog)
  for language in ('zh-CHS', 'en'):
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    draw(alert)
    assert resolve(alert._compact_view._list._scroller.items[0].text) == tr(
      'Map settings changed. Reopen the map page and try again.')


@pytest.mark.parametrize('change', ['country', 'state', 'request', 'unchanged'])
def test_map_download_confirmation_uses_displayed_region_and_current_request(map_panel, change):
  controller = map_panel.controller
  set_map_country(controller, 'US', 'United States')
  controller._params.put('OsmStateName', 'CA', block=True)
  controller._params.put('OsmStateTitle', 'California', block=True)
  controller._params.put('OSMDownloadProgress', {'total_files': 2, 'downloaded_files': 1}, block=True)
  controller._update_labels()
  controller._update_db()
  confirmation = gui_app.get_active_widget()
  draw(confirmation)
  for language, labels in [('zh-CHS', ['美国', '加利福尼亚州', 'CA']), ('en', ['United States', 'California', 'CA'])]:
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    draw(confirmation)
    text = resolve(confirmation._compact_view._list._scroller.items[0].text)
    assert all(label in text for label in labels)
  if change == 'country':
    set_map_country(controller, 'CN', 'China')
  elif change == 'state':
    controller._params.put('OsmStateName', 'NY', block=True)
  elif change == 'request':
    controller._params.put_bool('OsmDbUpdatesCheck', True, block=True)
  confirmation._confirm_button_callback()
  if change == 'unchanged':
    assert controller._params.get_bool('OsmDbUpdatesCheck')
    assert controller._params.get('OSMDownloadProgress') is None
    assert gui_app.get_active_widget() is map_panel
  else:
    assert controller._params.get_bool('OsmDbUpdatesCheck') == (change == 'request')
    assert controller._params.get('OSMDownloadProgress') == {'total_files': 2, 'downloaded_files': 1}
    assert isinstance(gui_app.get_active_widget(), ConfirmDialog)


def test_map_old_wait_timeout_confirmation_preserves_reissued_request(map_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  controller._params.put_bool('OsmDbUpdatesCheck', True, block=True)
  controller._request_started = 0
  monkeypatch.setattr(osm, 'monotonic', lambda: 31)
  controller._update_labels()
  controller._update_db()
  confirmation = gui_app.get_active_widget()
  # Another entry reissued a request while the same timeout confirmation was open.
  controller._params.put_bool('OsmDbUpdatesCheck', True, block=True)
  progress = {'status': 'requested', 'total_files': 0, 'downloaded_files': 0, 'requested_at': 31}
  controller._params.put('OSMDownloadProgress', progress, block=True)
  confirmation._confirm_button_callback()
  assert controller._params.get_bool('OsmDbUpdatesCheck')
  assert controller._params.get('OSMDownloadProgress') == progress
  assert isinstance(gui_app.get_active_widget(), ConfirmDialog)


@pytest.mark.parametrize('external_change', ['country', 'download'])
def test_map_region_fetch_checks_context_before_presenting_picker(map_panel, monkeypatch, external_change):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  jobs = []
  monkeypatch.setattr(osm.threading, 'Thread', lambda target, args, daemon: SimpleNamespace(start=lambda: jobs.append(lambda: target(*args))))
  monkeypatch.setattr(osm.requests, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None,
                                                                               json=lambda: {'GE': {'full_name': 'Georgia'}}))
  controller._select_region('Country')
  if external_change == 'country':
    set_map_country(controller, 'FR', 'France')
  else:
    controller._params.put_bool('OsmDbUpdatesCheck', True, block=True)
  jobs[0]()
  controller._update_state()
  assert not controller._fetching_regions
  assert not controller._region_fetch_contexts
  assert isinstance(gui_app.get_active_widget(), ConfirmDialog)
  assert controller._params.get('OsmLocationName') == ('FR' if external_change == 'country' else 'CN')


def test_map_fetch_failure_hint_updates_language_and_old_retry_preserves_country(map_panel, monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  controller._show_region_dialog('Country', controller._country_btn, [], 'Empty map region data')
  failure = gui_app.get_active_widget()
  for language in ('zh-CHS', 'en'):
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    draw(failure)
    message = resolve(failure._compact_view._list._scroller.items[0].text)
    assert message == tr('Failed to fetch map regions. Check the network and retry.') + '\n\n' + tr('Empty map region data')
  jobs = []
  monkeypatch.setattr(osm.threading, 'Thread', lambda target, args, daemon: SimpleNamespace(start=lambda: jobs.append((target, args))))
  set_map_country(controller, 'FR', 'France')
  failure._confirm_button_callback()
  assert not jobs
  assert not controller._fetching_regions
  assert controller._params.get('OsmLocationName') == 'FR'
  assert isinstance(gui_app.get_active_widget(), ConfirmDialog)


@pytest.mark.parametrize('outcome', ['success', 'failure'])
def test_closed_map_page_discards_old_region_fetch_and_allows_new_fetch(map_panel, monkeypatch, outcome):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  jobs = []
  monkeypatch.setattr(osm.threading, 'Thread', lambda target, args, daemon: SimpleNamespace(start=lambda: jobs.append(lambda: target(*args))))
  response = {'data': {'GE': {'full_name': 'Georgia'}} if outcome == 'success' else {}}
  monkeypatch.setattr(osm.requests, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None, json=lambda: response['data']))
  controller._select_region('Country')
  assert len(jobs) == 1
  gui_app.pop_widget()
  jobs[0]()
  gui_app.push_widget(map_panel)
  draw(map_panel)
  assert gui_app.get_active_widget() is map_panel
  assert not controller._fetching_regions
  controller._select_region('Country')
  assert len(jobs) == 2
  response['data'] = {'CN': {'full_name': 'China'}}
  jobs[1]()
  draw(map_panel)
  assert isinstance(gui_app.get_active_widget(), TreeOptionDialog)
  assert [node.ref for node in gui_app.get_active_widget().folders[0].nodes] == ['CN']


def test_old_map_fetch_result_cannot_clear_new_fetch_state(map_panel, monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  jobs = []
  monkeypatch.setattr(osm.threading, 'Thread', lambda target, args, daemon: SimpleNamespace(start=lambda: jobs.append(lambda: target(*args))))
  monkeypatch.setattr(osm.requests, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None,
                                                                               json=lambda: {'CN': {'full_name': 'China'}}))
  controller._select_region('Country')
  gui_app.pop_widget()
  gui_app.push_widget(map_panel)
  controller._select_region('Country')
  assert len(jobs) == 2
  jobs[0]()
  draw(map_panel)
  assert gui_app.get_active_widget() is map_panel
  assert controller._fetching_regions == {'Country'}
  assert not controller._country_btn.action_item.enabled
  jobs[1]()
  draw(map_panel)
  assert not controller._fetching_regions
  assert isinstance(gui_app.get_active_widget(), TreeOptionDialog)


@pytest.mark.parametrize('dialog_kind', ['region', 'download', 'retry'])
@pytest.mark.parametrize('reopened', [False, True])
def test_old_map_callback_after_navigation_exit_does_not_start_an_operation(map_panel, monkeypatch, dialog_kind, reopened):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  jobs = []
  monkeypatch.setattr(osm.threading, 'Thread', lambda target, args, daemon: SimpleNamespace(start=lambda: jobs.append((target, args))))
  if dialog_kind == 'region':
    controller._show_region_dialog('Country', controller._country_btn, [('GE', 'Georgia')])
    dialog = gui_app.get_active_widget()
    dialog.selection_ref = 'GE'
    callback = dialog.on_exit
  elif dialog_kind == 'retry':
    controller._show_region_dialog('Country', controller._country_btn, [], 'Empty map region data')
    dialog = gui_app.get_active_widget()
    callback = dialog._callback
  else:
    controller._update_db()
    dialog = gui_app.get_active_widget()
    callback = dialog._callback
  gui_app.pop_widget()
  gui_app.pop_widget()
  if reopened:
    gui_app.push_widget(map_panel)
  active = gui_app.get_active_widget()
  callback(DialogResult.CONFIRM)
  assert gui_app.get_active_widget() is active
  assert controller._params.get('OsmLocationName') == 'CN'
  assert not controller._params.get_bool('OsmDbUpdatesCheck')
  assert not jobs


@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_map_fetch_results_keep_current_request_when_both_finish_before_render(map_panel, monkeypatch, order):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  jobs, response = [], {}
  monkeypatch.setattr(osm.threading, 'Thread', lambda target, args, daemon: SimpleNamespace(start=lambda: jobs.append(lambda: target(*args))))
  monkeypatch.setattr(osm.requests, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None, json=lambda: response.copy()))
  controller._select_region('Country')
  gui_app.pop_widget()
  gui_app.push_widget(map_panel)
  controller._select_region('Country')
  assert len(jobs) == 2
  for index in order:
    response.clear()
    response.update({'FR': {'full_name': 'France'}} if index == 0 else {'GE': {'full_name': 'Georgia'}})
    jobs[index]()
  draw(map_panel)
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, TreeOptionDialog)
  assert [node.ref for node in dialog.folders[0].nodes] == ['GE']
  assert not controller._fetching_regions
  assert controller._params.get('OsmLocationName') == 'CN'


def test_map_non_us_selection_clears_stale_state_and_ignores_old_state_dialog(map_panel):
  controller = map_panel.controller
  set_map_country(controller, 'US', 'United States')
  controller._params.put('OsmStateName', 'CA', block=True)
  controller._params.put('OsmStateTitle', 'California', block=True)
  countries = [TreeNode('CN', {'display_name': 'China'})]
  controller._handle_region_selection('Country', countries, 'OsmLocation', DialogResult.CONFIRM, 'CN')
  assert controller._params.get('OsmLocationName') == 'CN'
  assert not controller._params.get('OsmStateName')
  assert not controller._params.get('OsmStateTitle')
  states = [TreeNode('CA', {'display_name': 'California'})]
  controller._handle_region_selection('State', states, 'OsmState', DialogResult.CONFIRM, 'CA')
  assert not controller._params.get('OsmStateName')


def test_map_picker_localizes_names_searches_codes_and_updates_language(map_panel):
  controller = map_panel.controller
  controller._show_region_dialog('Country', controller._country_btn, [('CN', 'China'), ('GE', 'Georgia'), ('US', 'United States')])
  picker = gui_app.get_active_widget()
  draw(picker)
  assert resolve(picker._compact_page._list._scroller.items[0].title) == '中国 (CN)'
  picker._on_search_confirm(DialogResult.CONFIRM, '中国')
  assert [item.ref for item in picker.visible_items] == ['CN']
  picker._on_search_confirm(DialogResult.CONFIRM, 'us')
  assert [item.ref for item in picker.visible_items] == ['US']
  picker._on_search_confirm(DialogResult.CONFIRM, 'GE')
  draw(picker)
  picker._compact_page._list._scroller.items[0].callback()
  draw(picker)
  assert '格鲁吉亚' in resolve(picker._compact_confirm_view._list._scroller.items[0].text)
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(picker)
  assert picker.title == 'Select Country'
  assert resolve(picker._compact_page._list._scroller.items[0].title) == 'Georgia (GE)'
  assert resolve(picker._compact_confirm_view._list._scroller.items[0].text) == 'Georgia (GE)'
  assert picker._compact_confirm_view._confirm.enabled


def test_map_all_regions_have_contextual_chinese_translations():
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.osm import _region_names, region_display_name
  from openpilot.selfdrive.ui.translations.update_translations import extract_json_strings
  from openpilot.system.ui.lib.multilang import TRANSLATIONS_DIR
  entries = extract_json_strings(str(TRANSLATIONS_DIR / 'map_regions.json'))
  assert len(entries) == 229
  assert all(entry.msgid in multilang._translations for entry in entries)
  for entry in _region_names().values():
    if isinstance(entry, dict) and 'text' in entry:
      assert region_display_name(entry['kind'].title(), entry['ref'], entry['display_name']) != entry['display_name']
  assert region_display_name('Country', 'GE', 'Georgia') == '格鲁吉亚'
  assert region_display_name('State', 'GA', 'Georgia') == '佐治亚州'
  assert region_display_name('Country', 'XX', 'New country') == 'New country'


@pytest.mark.parametrize(('progress', 'active', 'pending', 'expected', 'percent'), [
  (None, False, False, 'idle', 0),
  (None, False, True, 'waiting', 0),
  ({'status': 'requested', 'total_files': 0, 'downloaded_files': 0}, True, False, 'downloading', 0),
  ({'total_files': 10, 'downloaded_files': 4}, True, False, 'downloading', 40),
  ({'total_files': 10, 'downloaded_files': 10}, False, False, 'completed', 100),
  ({'total_files': 10, 'downloaded_files': 4}, False, False, 'failed', 40),
  ({'status': 'requested', 'total_files': 0, 'downloaded_files': 0}, False, False, 'failed', 0),
  ({'status': 'invalid_request', 'total_files': 0, 'downloaded_files': 0}, False, False, 'failed', 0),
  ({'total_files': 'bad', 'downloaded_files': 2}, False, False, 'failed', 0),
])
def test_map_download_status_keeps_terminal_result_and_retries(map_panel, progress, active, pending, expected, percent):
  controller = map_panel.controller
  set_map_country(controller)
  if progress is not None:
    controller._params.put('OSMDownloadProgress', progress, block=True)
  if active:
    controller._mem_params.put('OSMDownloadLocations', {'nations': ['CN'], 'states': []}, block=True)
  controller._params.put_bool('OsmDbUpdatesCheck', pending, block=True)
  controller._update_labels()
  controller._update_labels()
  assert controller._download_state == expected
  assert controller._current_percent == percent
  assert controller._progress.is_visible == (expected != 'idle')
  if active or pending:
    assert not controller._update_btn.action_item.enabled
    assert not controller._delete_maps_btn.action_item.enabled
    assert not controller._country_btn.action_item.enabled
  if expected == 'failed':
    assert controller._update_btn.action_item.enabled
    assert controller._update_btn.action_item.text == tr('Retry')


def test_map_active_transfer_blocks_actions_and_stale_selection(map_panel):
  controller = map_panel.controller
  set_map_country(controller)
  controller._mem_params.put('OSMDownloadLocations', {'nations': ['CN'], 'states': []}, block=True)
  controller._update_labels()
  controller._update_db()
  controller._begin_update_request()
  controller._on_confirm_delete_maps()
  controller._select_region('Country')
  controller._handle_region_selection('Country', [TreeNode('GE', {'display_name': 'Georgia'})], 'OsmLocation', DialogResult.CONFIRM, 'GE')
  assert gui_app.get_active_widget() is map_panel
  assert not controller._params.get_bool('OsmDbUpdatesCheck')
  assert controller._params.get('OsmLocationName') == 'CN'
  assert not controller._deleting
  assert not controller._fetching_regions


def test_map_waiting_timeout_retry_resets_old_completion_without_unlocking_other_actions(map_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  controller._params.put('OSMDownloadProgress', {'total_files': 2, 'downloaded_files': 2}, block=True)
  controller._params.put_bool('OsmDbUpdatesCheck', True, block=True)
  controller._request_started = 0
  monkeypatch.setattr(osm, 'monotonic', lambda: 31)
  controller._update_labels()
  assert controller._download_state == 'waiting_timeout'
  assert controller._update_btn.action_item.enabled
  assert not controller._delete_maps_btn.action_item.enabled
  assert not controller._country_btn.action_item.enabled
  controller._update_db()
  gui_app.get_active_widget()._confirm_button_callback()
  assert controller._request_started == 31
  assert controller._params.get_bool('OsmDbUpdatesCheck')
  assert not controller._params.get('OSMDownloadProgress')
  assert controller._download_state == 'waiting'


def test_map_version_value_and_selected_country_refresh(map_panel):
  controller = map_panel.controller
  assert controller._mapd_version.action_item.text == tr('Loading...')
  controller._params.put('MapdVersion', '1.12.0', block=True)
  assert controller._mapd_version.action_item.text == '1.12.0'
  set_map_country(controller)
  controller._update_labels()
  assert controller._country_btn.action_item.value == '中国'
  multilang._language = 'en'
  multilang.setup()
  controller._last_map_size_update = time.monotonic()
  controller._last_language = 'zh-CHS'
  controller._update_state()
  assert controller._country_btn.action_item.value == 'China'


def test_map_deletion_cleans_params_after_page_exit_before_ui_event_processing(map_panel, monkeypatch, tmp_path):
  import threading
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  controller._params.put('OSMDownloadProgress', {'total_files': 1, 'downloaded_files': 1}, block=True)
  root = osm.MAP_PATH
  root.mkdir()
  (root / 'map.bin').write_bytes(b'map')
  entered, release = threading.Event(), threading.Event()
  real_remove = osm.shutil.rmtree
  def remove(path):
    entered.set()
    assert release.wait(2)
    real_remove(path)
  monkeypatch.setattr(osm.shutil, 'rmtree', remove)
  controller._on_confirm_delete_maps()
  try:
    assert entered.wait(1)
    draw(map_panel)
    assert resolve(map_panel._rows[controller._delete_maps_btn][0].value) == tr('DELETING...')
    gui_app.pop_widget()
    # The worker must use its captured Params rather than whichever store a
    # newly displayed page happens to expose.
    ui_state.params = Params(str(tmp_path / 'other-params'))
    ui_state.params.put('OsmLocationName', 'GE', block=True)
  finally:
    release.set()
  deadline = time.monotonic() + 1
  while controller._events.empty() and time.monotonic() < deadline:
    time.sleep(.01)
  assert not controller._events.empty()
  assert not root.exists()
  assert not controller._params.get('OsmLocationName')
  assert not controller._params.get('OSMDownloadProgress')
  assert not controller._params.get_bool('OsmLocal')
  assert ui_state.params.get('OsmLocationName') == 'GE'
  assert len(gui_app._nav_stack) == 1
  gui_app.push_widget(map_panel)
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  assert resolve(dialog._label._text) == tr('Downloaded maps deleted.')
  dialog._confirm_button_callback()
  controller._process_events()
  assert gui_app.get_active_widget() is map_panel
  assert not controller._deleting


def test_map_delete_error_restores_controls_and_retry_preserves_region(map_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  set_map_country(controller)
  osm.MAP_PATH.mkdir()
  def remove(path):
    raise OSError('disk error')
  monkeypatch.setattr(osm.shutil, 'rmtree', remove)
  controller._deleting = True
  controller._do_delete_maps()
  controller._process_events()
  assert not controller._deleting
  assert controller._delete_maps_btn.action_item.enabled
  assert controller._params.get('OsmLocationName') == 'CN'
  result = gui_app.get_active_widget()
  assert isinstance(result, ConfirmDialog)
  assert 'disk error' in resolve(result._label._text)
  retries = []
  monkeypatch.setattr(controller, '_on_confirm_delete_maps', lambda: retries.append(True))
  result._confirm_button_callback()
  assert retries == [True]
  controller._process_events()
  assert gui_app.get_active_widget() is map_panel


def test_map_size_scan_ignores_file_directory_and_root_symlinks(map_panel, tmp_path):
  controller = map_panel.controller
  root = tmp_path / 'maps'
  root.mkdir()
  (root / 'one').write_bytes(b'abc')
  (root / 'nested').mkdir()
  (root / 'nested' / 'two').write_bytes(b'12')
  external = tmp_path / 'external'
  external.mkdir()
  (external / 'large').write_bytes(b'ignored')
  (root / 'linked_dir').symlink_to(external, target_is_directory=True)
  (root / 'linked_file').symlink_to(external / 'large')
  controller.calculate_size(0, root)
  assert controller._events.get_nowait() == ('size', (0, 5, None))
  root_link = tmp_path / 'root-link'
  root_link.symlink_to(root, target_is_directory=True)
  controller.calculate_size(0, root_link)
  assert controller._events.get_nowait() == ('size', (0, 0, None))


def test_map_size_error_and_old_generation_do_not_publish_stale_size(map_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  controller = map_panel.controller
  controller._delete_maps_btn.action_item.set_value('old')
  def scan(path):
    raise OSError()
  osm.MAP_PATH.mkdir()
  monkeypatch.setattr(osm.os, 'scandir', scan)
  controller.calculate_size(0)
  controller._process_events()
  assert controller._delete_maps_btn.action_item.value == tr('Map size unavailable')
  controller._size_generation = 1
  controller._events.put(('size', (0, 1024, None)))
  controller._process_events()
  assert controller._delete_maps_btn.action_item.value == tr('Map size unavailable')


def test_map_size_scan_queues_one_rescan(map_panel, monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import osm
  # Restore scanning for this test; map_panel suppresses it for state tests.
  controller = map_panel.controller
  scans = []
  monkeypatch.setattr(osm.threading, 'Thread', lambda target, args, daemon: SimpleNamespace(start=lambda: scans.append((target, args))))
  monkeypatch.setattr(controller, '_update_map_size', lambda: osm.OSMLayout._update_map_size(controller))
  controller._update_map_size()
  controller._update_map_size()
  controller._update_map_size()
  assert len(scans) == 1
  assert controller._size_rescan_requested
  controller._events.put(('size', (0, 10, None)))
  controller._process_events()
  assert len(scans) == 2
  assert controller._size_scan_running
  assert not controller._size_rescan_requested


def test_disabled_card_keeps_operation_status_and_opens_reason(monkeypatch):
  from openpilot.system.ui.widgets import compact
  callbacks, reasons, labels = [], [], []
  row = compact.CompactRow('Maps', lambda: tr('DELETING...'), lambda: callbacks.append(True),
                           lambda: reasons.append(True), enabled=False)
  monkeypatch.setattr(compact, 'gui_label', lambda rect, text, *args, **kwargs: labels.append(text))
  row.set_rect(rl.Rectangle(0, 0, 402, 168))
  draw(row)
  assert tr('DELETING...') in labels
  row._handle_mouse_release(rl.Vector2(100, 100))
  assert callbacks == []
  assert reasons == [True]


@pytest.fixture
def model_panel(monkeypatch):
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  manager = custom.ModelManagerSP.new_message()
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': manager})
  with monkeypatch.context() as setup:
    setup.setattr(models.ModelsLayout, '_refresh_cache_size', lambda self: None)
    panel = make_panel('models')
  monkeypatch.setattr(panel.controller, '_refresh_cache_size', lambda: None)
  gui_app.push_widget(panel)
  return panel


def model_bundle(ref='test-model', status='downloaded'):
  return {'ref': ref, 'index': 7, 'internalName': 'Test Model', 'displayName': 'Test Model (2026-11-11)',
          'generation': 2, 'status': status,
          'models': [{'type': 'supercombo', 'artifact': {'fileName': 'model.onnx',
                      'downloadProgress': {'status': status, 'progress': 100 if status == 'downloaded' else 37}}}]}


@pytest.mark.parametrize(('status', 'text', 'show'), [('downloading', '37%', True), ('downloaded', 'ready', False),
                                                     ('cached', 'ready', False), ('failed', 'download failed', False)])
def test_model_component_status_and_failed_retry_persist(model_panel, monkeypatch, status, text, show):
  from cereal import custom
  bundle = model_bundle(status=status)
  manager = custom.ModelManagerSP.new_message(selectedBundle=bundle, availableBundles=[bundle]) if status in ('failed', 'downloading') else \
            custom.ModelManagerSP.new_message(activeBundle=bundle)
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': manager})
  controller = model_panel.controller
  draw(model_panel)
  draw(model_panel)
  action = controller.supercombo_label.action_item
  assert tr(text) in action.text
  assert action.show_progress == show
  if status == 'failed':
    assert controller.retry_download_item.is_visible
    controller._retry_model_download()
    assert controller._params.get('ModelManager_DownloadIndex') == 7
    draw(model_panel)
    assert not controller.current_model_item.action_item.enabled
    assert not controller.retry_download_item.action_item.enabled


def test_model_metadata_failure_is_visible(model_panel, monkeypatch):
  from cereal import custom
  bundle = model_bundle(status='failed')
  bundle['models'][0]['artifact']['downloadProgress']['status'] = 'notDownloading'
  bundle['models'][0]['metadata'] = {'fileName': 'model.pkl', 'downloadProgress': {'status': 'failed', 'progress': 0}}
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': custom.ModelManagerSP.new_message(selectedBundle=bundle)})
  draw(model_panel)
  assert tr('download failed') in model_panel.controller.supercombo_label.action_item.text


@pytest.mark.parametrize('previous', ['active', 'failed', 'empty', 'unavailable', 'unknown'])
def test_model_pending_request_reports_waiting_and_remains_cancellable(model_panel, monkeypatch, previous):
  from cereal import custom
  from openpilot.system.ui.widgets.compact import CompactInfoPage
  requested = model_bundle('requested-model', 'downloaded')
  requested['index'], requested['displayName'] = 9, 'Requested Model <2026>'
  manager = custom.ModelManagerSP.new_message(availableBundles=[requested])
  if previous == 'active':
    manager.activeBundle = model_bundle('previous-active', 'downloaded')
  elif previous == 'failed':
    manager.selectedBundle = model_bundle('previous-failed', 'failed')
  elif previous == 'unavailable':
    manager = None
  elif previous == 'unknown':
    manager = custom.ModelManagerSP.new_message()
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': manager})
  ui_state.params.put('ModelManager_DownloadIndex', 9, block=True)
  draw(model_panel)
  controller = model_panel.controller
  assert controller.cancel_download_item.is_visible
  known = previous not in ('unavailable', 'unknown')
  expected = tr('Waiting for model service: {model}').format(model='Requested Model <2026>') if known else \
             tr('Waiting for model service...')
  visible_statuses = [item.action_item.text for item in controller.items if item.is_visible and hasattr(item.action_item, 'text')]
  assert expected in visible_statuses
  waiting = controller.download_request_item
  assert waiting.is_visible
  assert waiting.action_item.text == expected
  assert not controller.supercombo_label.is_visible
  assert not controller.retry_download_item.is_visible
  assert not controller.current_model_item.action_item.enabled
  assert not controller.clear_cache_item.action_item.enabled
  model_panel._rows[waiting][0].callback()
  detail = gui_app.get_active_widget()
  assert isinstance(detail, CompactInfoPage)
  draw(detail)
  text = resolve(detail._list._scroller.items[0].text)
  assert ('Requested Model &lt;2026&gt;' in text) if known else tr('Waiting for model service...') in text
  assert ui_state.params.get('ModelManager_DownloadIndex') == 9
  gui_app.pop_widget()
  model_panel._rows[controller.cancel_download_item][0].callback()
  assert ui_state.params.get('ModelManager_DownloadIndex') is None
  draw(model_panel)
  assert not waiting.is_visible
  assert not controller.cancel_download_item.is_visible


@pytest.mark.parametrize('terminal', ['downloaded', 'failed', 'cancelled'])
def test_model_request_timeout_and_new_request_update_without_restart(model_panel, monkeypatch, terminal):
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  clock = [100]
  monkeypatch.setattr(models.time, 'monotonic', lambda: clock[0])
  first, second = model_bundle('first'), model_bundle('second')
  first['index'], second['index'] = 8, 9
  first['displayName'], second['displayName'] = 'First Model', 'Second Model'
  manager = custom.ModelManagerSP.new_message(availableBundles=[first, second])
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': manager})
  ui_state.params.put('ModelManager_DownloadIndex', 8, block=True)
  draw(model_panel)
  controller = model_panel.controller
  item = controller.download_request_item
  assert item.action_item.text == tr('Waiting for model service: {model}').format(model='First Model')
  clock[0] = 131
  draw(model_panel)
  assert item.action_item.text == tr('Model service has not started the download. Cancel and retry.')
  assert controller.cancel_download_item.is_visible
  assert ui_state.params.get('ModelManager_DownloadIndex') == 8
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(model_panel)
  assert item.action_item.text == 'Model service has not started the download. Cancel and retry.'
  ui_state.params.put('ModelManager_DownloadIndex', 9, block=True)
  draw(model_panel)
  assert item.action_item.text == 'Waiting for model service: Second Model'
  manager.selectedBundle = second
  manager.selectedBundle.status = 'downloading'
  manager.selectedBundle.models[0].artifact.downloadProgress.status = 'downloading'
  manager.selectedBundle.models[0].artifact.downloadProgress.progress = 37
  draw(model_panel)
  assert not item.is_visible
  assert controller.supercombo_label.is_visible
  assert '37% - Second Model' == controller.supercombo_label.action_item.text
  # A completed request returns to the active bundle, while a failed request stays retryable.
  ui_state.params.remove('ModelManager_DownloadIndex')
  if terminal == 'failed':
    manager.selectedBundle.status = 'failed'
    manager.selectedBundle.models[0].artifact.downloadProgress.status = 'failed'
  else:
    completed = second if terminal == 'downloaded' else first
    monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': custom.ModelManagerSP.new_message(activeBundle=completed)})
  draw(model_panel)
  assert not item.is_visible
  assert controller.retry_download_item.is_visible == (terminal == 'failed')
  if terminal == 'failed':
    assert 'download failed - Second Model' == controller.supercombo_label.action_item.text
  else:
    assert ('Second Model' if terminal == 'downloaded' else 'First Model') in controller.supercombo_label.action_item.text
    assert controller.current_model_item.action_item.enabled


def test_model_request_progress_from_other_bundle_does_not_replace_waiting(model_panel, monkeypatch):
  from cereal import custom
  previous = model_bundle('old', 'downloading')
  requested = model_bundle('new', 'downloaded')
  requested['index'], requested['displayName'] = 9, 'New Model'
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': custom.ModelManagerSP.new_message(selectedBundle=previous, availableBundles=[requested])})
  ui_state.params.put('ModelManager_DownloadIndex', 9, block=True)
  draw(model_panel)
  controller = model_panel.controller
  assert controller.download_request_item.is_visible
  assert controller.download_request_item.action_item.text == tr('Waiting for model service: {model}').format(model='New Model')
  assert not controller.supercombo_label.is_visible


def test_cancel_and_retry_same_model_starts_new_waiting_period(model_panel, monkeypatch):
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  clock = [100]
  monkeypatch.setattr(models.time, 'monotonic', lambda: clock[0])
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': custom.ModelManagerSP.new_message(availableBundles=[model_bundle()])})
  ui_state.params.put('ModelManager_DownloadIndex', 7, block=True)
  draw(model_panel)
  clock[0] = 131
  draw(model_panel)
  controller = model_panel.controller
  assert controller.download_request_item.action_item.text == tr('Model service has not started the download. Cancel and retry.')
  model_panel._rows[controller.cancel_download_item][0].callback()
  # A same-index retry must not inherit the old deadline even before another draw.
  ui_state.params.put('ModelManager_DownloadIndex', 7, block=True)
  draw(model_panel)
  assert controller.download_request_item.action_item.text == tr('Waiting for model service: {model}').format(model='Test Model (2026-11-11)')
  clock[0] = 160
  draw(model_panel)
  assert controller.download_request_item.action_item.text.startswith(tr('Waiting for model service: {model}').format(model='Test Model'))
  assert ui_state.params.get('ModelManager_DownloadIndex') == 7


def test_model_pending_request_can_be_cancelled_and_blocks_selection_and_cache(model_panel):
  controller = model_panel.controller
  controller._params.put('ModelManager_DownloadIndex', 7, block=True)
  draw(model_panel)
  assert controller.cancel_download_item.is_visible
  assert not controller.current_model_item.action_item.enabled
  assert not controller.clear_cache_item.action_item.enabled
  controller._handle_current_model_clicked()
  controller._clear_cache()
  assert gui_app.get_active_widget() is model_panel
  controller.cancel_download_item.callback()
  assert controller._params.get('ModelManager_DownloadIndex') is None
  draw(model_panel)
  assert controller.current_model_item.action_item.enabled


def test_model_selection_cancel_and_stale_onroad_confirmation_do_not_request_download(model_panel, monkeypatch):
  from cereal import custom
  manager = custom.ModelManagerSP.new_message(availableBundles=[model_bundle()])
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': manager})
  draw(model_panel)
  controller = model_panel.controller
  controller._handle_current_model_clicked()
  picker = controller.model_dialog
  assert isinstance(picker, TreeOptionDialog)
  picker._set_result(DialogResult.CANCEL)
  assert controller.model_dialog is None
  controller._handle_current_model_clicked()
  picker = controller.model_dialog
  picker.selection_ref = 'test-model'
  monkeypatch.setattr(ui_state, 'started', True)
  picker._set_result(DialogResult.CONFIRM)
  assert not controller._params.get('ModelManager_DownloadIndex')
  assert controller.model_dialog is None


def test_model_selection_uses_ref_and_writes_before_return(model_panel, monkeypatch):
  from cereal import custom
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': custom.ModelManagerSP.new_message(availableBundles=[model_bundle()])})
  draw(model_panel)
  controller = model_panel.controller
  controller._handle_current_model_clicked()
  picker = controller.model_dialog
  picker.selection_ref = 'test-model'
  picker._set_result(DialogResult.CONFIRM)
  assert controller._params.get('ModelManager_DownloadIndex') == 7
  assert controller.model_dialog is None


@pytest.mark.parametrize('change', ['reindexed', 'removed', 'unavailable', 'downloading'])
def test_model_retry_reads_latest_service_list(model_panel, monkeypatch, change):
  from cereal import custom
  failed = model_bundle(status='failed')
  original = custom.ModelManagerSP.new_message(selectedBundle=failed, availableBundles=[failed])
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': original})
  draw(model_panel)
  controller = model_panel.controller
  latest_bundle = model_bundle()
  latest_bundle['index'] = 11
  latest = custom.ModelManagerSP.new_message(selectedBundle=failed, availableBundles=[latest_bundle])
  if change == 'removed':
    latest = custom.ModelManagerSP.new_message(selectedBundle=failed)
  elif change == 'unavailable':
    latest = None
  elif change == 'downloading':
    latest.selectedBundle = model_bundle('other-model', 'downloading')
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': latest})
  controller._retry_model_download()
  assert ui_state.params.get('ModelManager_DownloadIndex') == (11 if change == 'reindexed' else None)
  if change in ('removed', 'unavailable'):
    dialog = gui_app.get_active_widget()
    assert isinstance(dialog, ConfirmDialog)
    for language in ('zh-CHS', 'en'):
      multilang._language = language
      multilang.setup()
      gui_app.on_language_changed(language)
      draw(dialog)
      assert resolve(dialog._compact_view._list._scroller.items[0].text) == tr(
        'Model list changed or the service is unavailable. Reopen the model selector and try again.')
  else:
    assert gui_app.get_active_widget() is model_panel


def test_external_same_model_retry_restarts_wait_without_intermediate_frame(model_panel, monkeypatch):
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  now = [100.0]
  monkeypatch.setattr(models.time, 'monotonic', lambda: now[0])
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': custom.ModelManagerSP.new_message(availableBundles=[model_bundle()])})
  ui_state.params.put('ModelManager_DownloadIndex', 7, block=True)
  draw(model_panel)
  now[0] += 31
  draw(model_panel)
  assert model_panel.controller.download_request_item.action_item.text == tr('Model service has not started the download. Cancel and retry.')
  ui_state.params.remove('ModelManager_DownloadIndex')
  ui_state.params.put('ModelManager_DownloadIndex', 7, block=True)
  draw(model_panel)
  assert model_panel.controller.download_request_item.action_item.text == tr('Waiting for model service: {model}').format(
    model=model_bundle()['displayName'])
  assert ui_state.params.get('ModelManager_DownloadIndex') == 7


@pytest.mark.parametrize('change', ['reindexed', 'removed', 'unavailable', 'downloading'])
def test_model_picker_confirmation_uses_current_service_list(model_panel, monkeypatch, change):
  from cereal import custom
  original = custom.ModelManagerSP.new_message(availableBundles=[model_bundle()])
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': original})
  draw(model_panel)
  controller = model_panel.controller
  controller._handle_current_model_clicked()
  picker = controller.model_dialog
  picker.selection_ref = 'test-model'
  latest_bundle = model_bundle()
  latest_bundle['index'] = 11
  latest = custom.ModelManagerSP.new_message(availableBundles=[latest_bundle])
  if change == 'removed':
    latest = custom.ModelManagerSP.new_message()
  elif change == 'unavailable':
    latest = None
  elif change == 'downloading':
    latest.selectedBundle = model_bundle('other-model', 'downloading')
  # The settings controller is hidden beneath the picker, so it has not rendered this message.
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': latest})
  picker._set_result(DialogResult.CONFIRM)
  assert controller.model_dialog is None
  assert ui_state.params.get('ModelManager_DownloadIndex') == (11 if change == 'reindexed' else None)
  if change in ('removed', 'unavailable'):
    dialog = gui_app.get_active_widget()
    assert isinstance(dialog, ConfirmDialog)
    assert resolve(dialog._label._text) == tr('Model list changed or the service is unavailable. Reopen the model selector and try again.')
    for language in ('zh-CHS', 'en'):
      multilang._language = language
      multilang.setup()
      gui_app.on_language_changed(language)
      draw(dialog)
      assert resolve(dialog._compact_view._list._scroller.items[0].text) == tr(
        'Model list changed or the service is unavailable. Reopen the model selector and try again.')
    dialog._confirm_button_callback()
    monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': original})
    draw(model_panel)
    controller._handle_current_model_clicked()
    assert isinstance(gui_app.get_active_widget(), TreeOptionDialog)
  else:
    assert gui_app.get_active_widget() is model_panel


def test_model_selector_does_not_open_using_stale_service_data(model_panel, monkeypatch):
  from cereal import custom
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': custom.ModelManagerSP.new_message(availableBundles=[model_bundle()])})
  draw(model_panel)
  controller = model_panel.controller
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': None})
  controller._handle_current_model_clicked()
  assert gui_app.get_active_widget() is model_panel
  draw(model_panel)
  assert not controller.current_model_item.action_item.enabled
  assert controller.current_model_item.description == tr('Model service is unavailable. Please try again.')


def test_model_default_software_delay_description_does_not_block_when_param_missing(model_panel, monkeypatch):
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(steerActuatorDelay=.3))
  model_panel.controller._update_lagd_description(False)
  assert '0.20 s' in model_panel.controller.lagd_toggle.description
  assert '0.50 s' in model_panel.controller.lagd_toggle.description


def test_model_refresh_waits_for_sync_and_keeps_timeout_retry(model_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  controller = model_panel.controller
  clock = [100]
  monkeypatch.setattr(models.time, 'monotonic', lambda: clock[0])
  controller._refresh_models()
  assert controller._params.get('ModelManager_LastSyncTime') == 0
  assert not controller.refresh_item.action_item.enabled
  clock[0] = 131
  controller._update_operations()
  assert controller.refresh_item.action_item.enabled
  assert controller.refresh_item.action_item.text == tr('Retry')
  assert tr('Model list refresh has not completed. Check the network and retry.') == controller.refresh_item.action_item.value
  # A late successful refresh must replace the timeout without another click.
  controller._params.put('ModelManager_LastSyncTime', 500, block=True)
  controller._update_operations()
  assert controller.refresh_item.action_item.value == tr('Model list refreshed.')
  controller._refresh_models()
  controller._params.put('ModelManager_LastSyncTime', 1000, block=True)
  controller._update_operations()
  assert controller._refresh_started is None
  assert controller.refresh_item.action_item.value == tr('Model list refreshed.')


def test_model_cache_confirm_cancel_wait_timeout_and_completion_rescan(model_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  controller = model_panel.controller
  clock = [100]
  monkeypatch.setattr(models.time, 'monotonic', lambda: clock[0])
  controller._clear_cache()
  gui_app.get_active_widget()._cancel_button_callback()
  assert not controller._params.get_bool('ModelManager_ClearCache')
  controller._clear_cache()
  gui_app.get_active_widget()._confirm_button_callback()
  assert controller._params.get_bool('ModelManager_ClearCache')
  assert controller.clear_cache_item.action_item.value == tr('Waiting for model cache cleanup...')
  assert not controller.clear_cache_item.action_item.enabled
  clock[0] = 131
  controller._update_operations()
  assert controller.clear_cache_item.action_item.enabled
  assert controller.clear_cache_item.action_item.text == tr('Retry')
  assert controller._params.get_bool('ModelManager_ClearCache')
  scans = []
  monkeypatch.setattr(controller, '_refresh_cache_size', lambda: scans.append(True))
  controller._params.remove('ModelManager_ClearCache')
  controller._update_operations()
  assert scans == [True]
  assert controller.clear_cache_item.action_item.enabled


def test_model_cache_scan_is_background_and_handles_directory_error(model_panel, monkeypatch):
  import threading
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import models
  controller = model_panel.controller
  entered, release = threading.Event(), threading.Event()
  def size():
    entered.set()
    assert release.wait(2)
    raise OSError()
  monkeypatch.setattr(controller, 'calculate_cache_size', size)
  models.ModelsLayout._refresh_cache_size(controller)
  try:
    assert entered.wait(1)
    draw(model_panel)
    models.ModelsLayout._refresh_cache_size(controller)
    assert controller._cache_scan_running
  finally:
    release.set()
  deadline = time.monotonic() + 1
  while controller._cache_events.empty() and time.monotonic() < deadline:
    time.sleep(.01)
  assert not controller._cache_events.empty()
  controller._update_operations()
  assert not controller._cache_scan_running
  assert controller.clear_cache_item.action_item.value == tr('Cache size unavailable')


@pytest.mark.parametrize('fetch_available', [False, True])
def test_software_download_action_uses_backend_state_and_preserves_waiting_and_timeout(monkeypatch, fetch_available):
  from openpilot.selfdrive.ui.layouts.settings import software
  signals = []
  clock = [100]
  monkeypatch.setattr(software.os, 'system', signals.append)
  monkeypatch.setattr(software.time, 'monotonic', lambda: clock[0])
  ui_state.params.put_bool('UpdaterFetchAvailable', fetch_available, block=True)
  panel = make_panel('software')
  gui_app.push_widget(panel)
  controller = panel.controller
  controller._download_btn.action_item.set_text('stale label')
  controller._on_download_update()
  assert len(signals) == 1
  assert ('SIGHUP' if fetch_available else 'SIGUSR1') in signals[0]
  draw(panel)
  assert not controller._download_btn.action_item.enabled
  assert controller._download_btn.action_item.value == tr('Waiting for update service...')
  controller._on_download_update()
  assert len(signals) == 1
  clock[0] = 111
  draw(panel)
  draw(panel)
  assert controller._download_btn.action_item.enabled
  assert controller._download_btn.action_item.value == tr('Update service did not respond. Retry.')


def test_software_branch_cancel_save_order_and_onroad_gating(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import software
  signals = []
  def signal(command):
    signals.append(ui_state.params.get('UpdaterTargetBranch'))
  monkeypatch.setattr(software.os, 'system', signal)
  ui_state.params.put('UpdaterAvailableBranches', 'dev,release-mici,example-prebuilt', block=True)
  ui_state.params.put('UpdaterTargetBranch', 'dev', block=True)
  panel = make_panel('software')
  gui_app.push_widget(panel)
  controller = panel.controller
  controller._on_select_branch()
  picker = controller._branch_dialog
  picker._set_result(DialogResult.CANCEL)
  assert ui_state.params.get('UpdaterTargetBranch') == 'dev'
  assert not signals
  controller._on_select_branch()
  picker = controller._branch_dialog
  picker.selection_ref = 'release-mici'
  picker._set_result(DialogResult.CONFIRM)
  assert signals == ['release-mici']
  controller._on_select_branch()
  picker = controller._branch_dialog
  picker.selection_ref = 'example-prebuilt'
  monkeypatch.setattr(ui_state, 'started', True)
  picker._set_result(DialogResult.CONFIRM)
  assert ui_state.params.get('UpdaterTargetBranch') == 'release-mici'
  assert len(signals) == 1


@pytest.mark.parametrize('change', ['removed', 'target_changed', 'reordered', 'updating'])
def test_branch_picker_confirmation_rechecks_current_available_branches(monkeypatch, change):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import software
  signals = []
  monkeypatch.setattr(software.os, 'system', lambda command: signals.append(ui_state.params.get('UpdaterTargetBranch')))
  ui_state.params.put('UpdaterAvailableBranches', 'dev,release-mici,example-prebuilt', block=True)
  ui_state.params.put('UpdaterTargetBranch', 'dev', block=True)
  panel = make_panel('software')
  gui_app.push_widget(panel)
  controller = panel.controller
  controller._on_select_branch()
  picker = controller._branch_dialog
  picker.selection_ref = 'release-mici'
  if change == 'removed':
    ui_state.params.put('UpdaterAvailableBranches', 'dev,example-prebuilt', block=True)
  elif change == 'target_changed':
    ui_state.params.put('UpdaterTargetBranch', 'example-prebuilt', block=True)
  elif change == 'reordered':
    ui_state.params.put('UpdaterAvailableBranches', 'example-prebuilt,release-mici,dev', block=True)
  else:
    ui_state.params.put('UpdaterState', 'downloading...', block=True)
  picker._set_result(DialogResult.CONFIRM)
  assert controller._branch_dialog is None
  assert signals == (['release-mici'] if change == 'reordered' else [])
  assert ui_state.params.get('UpdaterTargetBranch') == (
    'release-mici' if change == 'reordered' else 'example-prebuilt' if change == 'target_changed' else 'dev')
  if change in ('removed', 'target_changed'):
    dialog = gui_app.get_active_widget()
    assert isinstance(dialog, ConfirmDialog)
    assert resolve(dialog._label._text) == tr('Branch settings changed. Reopen the branch selector and try again.')
    dialog._confirm_button_callback()
    controller._on_select_branch()
    assert isinstance(gui_app.get_active_widget(), TreeOptionDialog)
  else:
    assert gui_app.get_active_widget() is panel


def test_software_disable_updates_confirm_keeps_proposal_and_rechecks_offroad(monkeypatch):
  panel = make_panel('software')
  gui_app.push_widget(panel)
  controller = panel.controller
  controller._on_disable_updates_toggled(True)
  panel.refresh()
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get_bool('DisableUpdates')
  assert ui_state.params.get_bool('DoReboot')
  ui_state.params.remove('DoReboot')
  controller._on_disable_updates_toggled(False)
  monkeypatch.setattr(ui_state, 'started', True)
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get_bool('DisableUpdates')
  assert not ui_state.params.get_bool('DoReboot')


@pytest.mark.parametrize('outcome', ['accept', 'cancel', 'started', 'force_onroad'])
def test_software_uninstall_confirmation_rechecks_vehicle_state(monkeypatch, outcome):
  panel = make_panel('software')
  gui_app.push_widget(panel)
  controller = panel.controller
  item = next(item for item in controller._scroller._items if item.title == tr('Uninstall'))
  model_request = ui_state.params.get('ModelManager_DownloadIndex')
  panel._rows[item][0].callback()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  draw(dialog)
  assert resolve(dialog._compact_view._confirm.text) == tr('Uninstall')
  if outcome in ('started', 'force_onroad'):
    monkeypatch.setattr(ui_state, outcome, True)
  if outcome == 'cancel':
    dialog._cancel_button_callback()
  else:
    dialog._confirm_button_callback()
  assert ui_state.params.get_bool('DoUninstall') == (outcome == 'accept')
  assert not ui_state.params.get_bool('DoReboot')
  assert ui_state.params.get('ModelManager_DownloadIndex') == model_request
  assert gui_app.get_active_widget() is panel


@pytest.mark.parametrize('vehicle_state', ['started', 'force_onroad'])
def test_software_uninstall_card_and_old_callback_follow_vehicle_state(monkeypatch, vehicle_state):
  from openpilot.system.ui.widgets.compact import CompactInfoPage
  panel = make_panel('software')
  gui_app.push_widget(panel)
  controller = panel.controller
  item = next(item for item in controller._scroller._items if item.title == tr('Uninstall'))
  row = panel._rows[item][0]
  monkeypatch.setattr(ui_state, vehicle_state, True)
  draw(panel)
  assert not resolve(row.available)
  assert not item.action_item.enabled
  row.help_callback()
  help_page = gui_app.get_active_widget()
  assert isinstance(help_page, CompactInfoPage)
  for language in ('zh-CHS', 'en', 'zh-CHS'):
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    draw(help_page)
    assert tr('Uninstalling is only available while the vehicle is off.') in resolve(help_page._list._scroller.items[0].text)
  gui_app.pop_widget()
  # A callback captured before the UI refresh also checks the current state.
  item.callback()
  assert gui_app.get_active_widget() is panel
  assert not ui_state.params.get_bool('DoUninstall')
  monkeypatch.setattr(ui_state, vehicle_state, False)
  draw(panel)
  assert resolve(row.available)
  row.callback()
  assert isinstance(gui_app.get_active_widget(), ConfirmDialog)


@pytest.mark.parametrize('outcome', ['accept', 'cancel', 'started', 'force_onroad'])
@pytest.mark.parametrize('selection', ['Default', 'test-model'])
def test_model_change_calibration_confirmation_rechecks_vehicle_state(model_panel, monkeypatch, selection, outcome):
  from cereal import custom
  manager = custom.ModelManagerSP.new_message(activeBundle=model_bundle('active-model'), availableBundles=[model_bundle()])
  manager.activeBundle.generation = 1
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': manager})
  saved = {'CalibrationParams': b'calibration', 'LiveTorqueParameters': b'torque', 'LiveDelay': b'delay'}
  for key, value in saved.items():
    ui_state.params.put(key, value, block=True)
  draw(model_panel)
  controller = model_panel.controller
  controller._handle_current_model_clicked()
  picker = controller.model_dialog
  picker.selection_ref = selection
  picker._set_result(DialogResult.CONFIRM)
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  request = ui_state.params.get('ModelManager_DownloadIndex')
  assert request == (7 if selection == 'test-model' else None)
  draw(dialog)
  assert resolve(dialog._compact_view._confirm.text) == tr('Reset Calibration')
  if outcome in ('started', 'force_onroad'):
    monkeypatch.setattr(ui_state, outcome, True)
  if outcome == 'cancel':
    dialog._cancel_button_callback()
  else:
    dialog._confirm_button_callback()
  for key, value in saved.items():
    assert ui_state.params.get(key) == (None if outcome == 'accept' and key != 'LiveDelay' else value)
  assert ui_state.params.get('ModelManager_DownloadIndex') == request
  assert gui_app.get_active_widget() is model_panel


@pytest.mark.parametrize('vehicle_state', ['started', 'force_onroad'])
def test_model_calibration_prompt_cannot_open_after_vehicle_state_change(model_panel, monkeypatch, vehicle_state):
  monkeypatch.setattr(ui_state, vehicle_state, True)
  model_panel.controller._show_reset_params_dialog()
  assert gui_app.get_active_widget() is model_panel


def test_toyota_confirm_rechecks_engagement_and_external_toggle_values(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.toyota import ToyotaSettings
  monkeypatch.setattr(type(ui_state), 'engaged', property(lambda self: engagement[0]))
  engagement = [False]
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(brand='toyota', openpilotLongitudinalControl=True))
  settings = ToyotaSettings()
  ui_state.params.put_bool('ToyotaDoorAutoLockUnlock', True, block=True)
  ui_state.params.put_bool('ToyotaStopAndGoHack', True, block=True)
  settings.update_settings()
  assert settings.auto_lock.action_item.get_state()
  assert settings.stop_and_go_hack.action_item.get_state()
  settings._on_enable_enforce_stock_longitudinal(True)
  engagement[0] = True
  gui_app.get_active_widget()._confirm_button_callback()
  assert not ui_state.params.get_bool('ToyotaEnforceStockLongitudinal')
  assert ui_state.params.get_bool('ToyotaStopAndGoHack')
  engagement[0] = False
  ui_state.params.put_bool('AlphaLongitudinalEnabled', True, block=True)
  settings._on_enable_enforce_stock_longitudinal(True)
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get_bool('ToyotaEnforceStockLongitudinal')
  assert not ui_state.params.get_bool('ToyotaStopAndGoHack')
  assert not ui_state.params.get_bool('AlphaLongitudinalEnabled')


def test_subaru_compatibility_is_reset_when_vehicle_becomes_unknown(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.subaru import SubaruSettings
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(brand='subaru', flags=0))
  settings = SubaruSettings()
  settings.update_settings()
  assert settings.has_stop_and_go
  monkeypatch.setattr(ui_state, 'CP', None)
  settings.update_settings()
  assert not settings.has_stop_and_go
  assert not settings.stop_and_go_toggle.action_item.enabled


@pytest.mark.parametrize('brand', ['hyundai', 'subaru'])
@pytest.mark.parametrize('platform', ['UNKNOWN_PLATFORM', []])
def test_unknown_manual_platform_disables_brand_controls(monkeypatch, brand, platform):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.factory import BrandSettingsFactory
  ui_state.params.put('CarPlatformBundle', {'name': 'Unknown', 'brand': brand, 'platform': platform}, block=True)
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  settings = BrandSettingsFactory.create_brand_settings(brand)
  settings.update_settings()
  assert all(not item.action_item.enabled for item in settings.items)
  if brand == 'hyundai':
    settings._on_tuning_selected(1)
    assert not ui_state.params.get('HyundaiLongitudinalTuning')
  else:
    settings._on_toggle_changed('SubaruStopAndGo', True)
    assert not ui_state.params.get_bool('SubaruStopAndGo')


@pytest.mark.parametrize('brand,param,item_name,callback', [
  ('tesla', 'TeslaCoopSteering', 'coop_steering_toggle', '_on_coop_steering'),
  ('subaru', 'SubaruStopAndGo', 'stop_and_go_toggle', '_on_toggle_changed'),
  ('subaru', 'SubaruStopAndGoManualParkingBrake', 'stop_and_go_manual_parking_brake_toggle', '_on_toggle_changed'),
])
def test_brand_toggles_refresh_external_values_and_block_stale_callbacks(monkeypatch, brand, param, item_name, callback):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.factory import BrandSettingsFactory
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(brand=brand))
  settings = BrandSettingsFactory.create_brand_settings(brand)
  item = getattr(settings, item_name)
  ui_state.params.put_bool(param, True, block=True)
  settings.update_settings()
  assert item.action_item.get_state()
  assert item.action_item.enabled
  def toggle(value):
    if brand == 'subaru':
      getattr(settings, callback)(param, value)
    else:
      getattr(settings, callback)(value)
  toggle(False)
  assert not ui_state.params.get_bool(param)
  assert not item.action_item.get_state()
  monkeypatch.setattr(ui_state, 'started', True)
  toggle(True)
  assert not ui_state.params.get_bool(param)
  monkeypatch.setattr(ui_state, 'started', False)
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(brand='toyota'))
  toggle(True)
  assert not ui_state.params.get_bool(param)
  assert not item.action_item.enabled


def test_hyundai_native_enum_release_does_not_save_after_brand_switch(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.hyundai import HyundaiSettings
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(brand='hyundai', alphaLongitudinalAvailable=True))
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  ui_state.params.put('HyundaiLongitudinalTuning', 0, block=True)
  settings = HyundaiSettings()
  settings.update_settings()
  action = settings.longitudinal_tuning_item.action_item
  action.set_rect(rl.Rectangle(0, 0, 900, 150))
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(brand='tesla'))
  action._handle_mouse_release(rl.Vector2(450, 75))
  assert ui_state.params.get('HyundaiLongitudinalTuning') == 0
  assert action.selected_button == 0
  assert not action.enabled


@pytest.mark.parametrize('callback,param', [('_on_enable_enforce_stock_longitudinal', 'ToyotaEnforceStockLongitudinal'),
                                          ('_on_enable_stop_and_go_hack', 'ToyotaStopAndGoHack')])
def test_toyota_pending_confirmation_cannot_save_after_brand_switch(monkeypatch, callback, param):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.toyota import ToyotaSettings
  monkeypatch.setattr(type(ui_state), 'engaged', property(lambda self: False))
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(brand='toyota', openpilotLongitudinalControl=True))
  settings = ToyotaSettings()
  getattr(settings, callback)(True)
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  assert not ui_state.params.get_bool(param)
  ui_state.params.put('CarPlatformBundle', {'name': 'Tesla', 'brand': 'tesla'}, block=True)
  dialog._confirm_button_callback()
  assert not ui_state.params.get_bool(param)
  assert not ui_state.params.get_bool('OnroadCycleRequested')


@pytest.fixture
def sunnylink_transfer(monkeypatch):
  from cereal import custom
  from types import SimpleNamespace
  class Messages(dict):
    recv_frame = {'backupManagerSP': 1}
  manager = custom.BackupManagerSP.new_message()
  sm = Messages(backupManagerSP=manager)
  monkeypatch.setattr(ui_state, 'sm', sm)
  monkeypatch.setattr(ui_state, 'sunnylink_state', SimpleNamespace(
    set_settings_open=lambda _: None, is_sponsor=lambda: False, is_paired=lambda: False,
    get_sponsor_tier=lambda: SimpleNamespace(name='FREE'), get_sponsor_tier_color=lambda: rl.WHITE))
  ui_state.params.put_bool('SunnylinkEnabled', True, block=True)
  panel = make_panel('sunnylink')
  gui_app.push_widget(panel)
  return panel, manager, sm


@pytest.mark.parametrize('kind', ['backup', 'restore'])
def test_sunnylink_wait_ignores_last_success_and_preserves_failure_retry(sunnylink_transfer, kind):
  panel, manager, sm = sunnylink_transfer
  controller = panel.controller
  setattr(manager, kind + 'Status', 'completed')
  setattr(manager, kind + 'Progress', 100)
  controller._start_transfer(kind)
  for frame in (2, 3):
    sm.recv_frame['backupManagerSP'] = frame
    controller.handle_backup_restore_progress()
    assert getattr(controller, '_' + kind + '_in_progress')
    assert controller._transfer_progress == 0
    assert controller._transfer_status() == tr('Waiting for ' + kind + ' service')
  setattr(manager, kind + 'Status', 'inProgress')
  setattr(manager, kind + 'Progress', 42)
  controller.handle_backup_restore_progress()
  assert controller._transfer_item.action_item.progress == 42
  assert not controller._backup_btn.enabled and not controller._restore_btn.enabled
  setattr(manager, kind + 'Status', 'failed')
  manager.lastError = 'Failed to upload backup' if kind == 'backup' else 'Failed to restore 2 settings'
  ui_state.params.remove('BackupManager_CreateBackup' if kind == 'backup' else 'BackupManager_RestoreVersion')
  controller.handle_backup_restore_progress()
  assert not getattr(controller, '_' + kind + '_in_progress')
  assert controller._transfer_status() == tr('Backup Failed' if kind == 'backup' else 'Restore Failed')
  assert controller._backup_btn.enabled and controller._restore_btn.enabled
  controller._transfer_item.action_item._update_state()
  panel.refresh()
  panel._rows[controller._transfer_item][0].callback()
  detail = gui_app.get_active_widget()
  text = resolve(detail._list._scroller.items[0].text)
  assert ('备份上传失败' if kind == 'backup' else '2 项设置恢复失败') in text
  multilang._language = 'en'
  multilang.setup()
  assert manager.lastError in controller._transfer_detail()
  gui_app.pop_widget()
  controller._start_transfer(kind)
  assert controller._transfer_error == ''
  assert controller._transfer_progress == 0
  assert getattr(controller, '_' + kind + '_in_progress')


@pytest.mark.parametrize('kind', ['backup', 'restore'])
def test_sunnylink_wait_timeout_retries_same_operation_only(sunnylink_transfer, monkeypatch, kind):
  panel, manager, _ = sunnylink_transfer
  controller = panel.controller
  clock = [100]
  monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
  controller._start_transfer(kind)
  clock[0] += controller.TRANSFER_WAIT_TIMEOUT + 1
  controller.handle_backup_restore_progress()
  own = controller._backup_btn if kind == 'backup' else controller._restore_btn
  other = controller._restore_btn if kind == 'backup' else controller._backup_btn
  assert own.enabled and not other.enabled
  assert controller._transfer_status() == tr(kind.capitalize() + ' service did not respond. Retry available.')
  own._click_callback()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  dialog._confirm_button_callback()
  assert not controller._waiting_timed_out()
  assert not controller._backup_btn.enabled and not controller._restore_btn.enabled
  setattr(manager, kind + 'Status', 'inProgress')
  clock[0] += 100
  controller.handle_backup_restore_progress()
  assert not own.enabled


def test_sunnylink_confirm_cancel_stale_onroad_and_duplicate_request(sunnylink_transfer, monkeypatch):
  panel, _, _ = sunnylink_transfer
  controller = panel.controller
  controller._handle_restore_btn()
  gui_app.get_active_widget()._cancel_button_callback()
  assert not ui_state.params.get('BackupManager_RestoreVersion')
  assert controller._restore_btn.enabled
  controller._handle_backup_btn()
  monkeypatch.setattr(ui_state, 'started', True)
  gui_app.get_active_widget()._confirm_button_callback()
  assert not ui_state.params.get_bool('BackupManager_CreateBackup')
  monkeypatch.setattr(ui_state, 'started', False)
  controller._start_transfer('backup')
  controller._start_transfer('restore')
  assert not ui_state.params.get('BackupManager_RestoreVersion')
  assert ui_state.params.get_bool('BackupManager_CreateBackup')


def test_sunnylink_fast_repeat_completion_requires_new_service_message(sunnylink_transfer):
  panel, manager, sm = sunnylink_transfer
  controller = panel.controller
  manager.backupStatus, manager.backupProgress = 'completed', 100
  controller._start_transfer('backup')
  controller.handle_backup_restore_progress()
  ui_state.params.remove('BackupManager_CreateBackup')
  controller.handle_backup_restore_progress()
  assert controller._backup_in_progress
  sm.recv_frame['backupManagerSP'] += 1
  controller.handle_backup_restore_progress()
  assert not controller._backup_in_progress
  assert isinstance(gui_app.get_active_widget(), ConfirmDialog)
  gui_app.get_active_widget()._confirm_button_callback()
  controller.handle_backup_restore_progress()
  assert gui_app.get_active_widget() is panel


def test_sunnylink_restore_restart_is_explicit_and_can_be_reopened(sunnylink_transfer, monkeypatch):
  panel, manager, _ = sunnylink_transfer
  controller = panel.controller
  closed = []
  monkeypatch.setattr(gui_app, 'request_close', lambda: closed.append(True))
  controller._start_transfer('restore')
  manager.restoreStatus = 'inProgress'
  controller.handle_backup_restore_progress()
  ui_state.params.remove('BackupManager_RestoreVersion')
  manager.restoreStatus, manager.restoreProgress = 'completed', 100
  controller.handle_backup_restore_progress()
  dialog = gui_app.get_active_widget()
  draw(dialog)
  assert dialog._compact_view._confirm.rect.height == 64
  dialog._cancel_button_callback()
  controller.handle_backup_restore_progress()
  assert not closed and controller._restore_btn.enabled
  assert not controller._backup_btn.enabled
  controller._restore_btn._click_callback()
  monkeypatch.setattr(ui_state, 'started', True)
  gui_app.get_active_widget()._confirm_button_callback()
  assert not closed
  monkeypatch.setattr(ui_state, 'started', False)
  controller._restore_btn._click_callback()
  gui_app.get_active_widget()._confirm_button_callback()
  assert closed == [True]


@pytest.mark.parametrize('tier', ['FREE', 'NOVICE', 'SUPPORTER', 'CONTRIBUTOR', 'BENEFACTOR', 'GUARDIAN'])
def test_sunnylink_sponsor_tier_tracks_language(sunnylink_transfer, monkeypatch, tier):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.sunnylink import SPONSOR_TIERS
  panel, _, _ = sunnylink_transfer
  monkeypatch.setattr(ui_state.sunnylink_state, 'get_sponsor_tier', lambda: SimpleNamespace(name=tier))
  panel.refresh()
  assert panel.controller._sponsor_btn.action_item.value == tr(SPONSOR_TIERS[tier])
  assert panel.controller._sponsor_btn.action_item.value != tier.capitalize()
  multilang._language = 'en'
  multilang.setup()
  panel.refresh()
  assert panel.controller._sponsor_btn.action_item.value == SPONSOR_TIERS[tier]


@pytest.fixture
def wifi_cards():
  from types import SimpleNamespace
  from openpilot.system.ui.lib.wifi_manager import Network, SecurityType
  from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import WifiUIMici
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.network import WifiPanel
  actions = []
  network = Network('Home', 90, SecurityType.WPA2, False)
  manager = SimpleNamespace(networks=[network], connecting_to_ssid=None, connected_ssid='Home',
                            wifi_state=SimpleNamespace(ssid='Home'), is_connection_saved=lambda _: True,
                            set_active=lambda _: None, add_callbacks=lambda **kwargs: None,
                            forget_connection=lambda ssid: actions.append(('forget', ssid)),
                            activate_connection=lambda ssid: actions.append(('connect', ssid)),
                            connect_to_network=lambda ssid, password: actions.append(('password', ssid, password)))
  native = WifiUIMici(manager)
  panel = WifiPanel(native)
  gui_app.push_widget(panel)
  draw(panel)
  draw(panel)
  return panel, manager, actions


def test_wifi_forget_has_visible_touch_target_and_preserves_connection_status(wifi_cards, monkeypatch):
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationDialog
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  panel, _, actions = wifi_cards
  row = panel._list._scroller.items[0]
  assert resolve(row.value) == tr('connected')
  assert row._forget.rect.width == 104 and row._forget.rect.height == 56
  assert row._value_rect().x + row._value_rect().width <= row._forget.rect.x
  assert resolve(row._forget.text) == tr('Forget')
  pos = MousePos(row._forget.rect.x + 20, row._forget.rect.y + 20)
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, True, False, True, 0),
                                               MouseEvent(pos, 0, False, True, False, 0.1)])
  row.render()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, BigConfirmationDialog)
  assert actions == []
  # Cancel by returning from the native slider page, then confirm a second request.
  gui_app.pop_widget()
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  row._forget._click_callback()
  gui_app.get_active_widget()._confirm_callback()
  assert actions == [('forget', 'Home')]
  panel._update_state()
  assert resolve(row.value) == tr('forgetting...')
  assert not row.button._show_forget_btn


def test_wifi_forget_swipe_does_not_open_confirmation(wifi_cards, monkeypatch):
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  panel, _, actions = wifi_cards
  row = panel._list._scroller.items[0]
  start = row._forget.rect.x + 35
  y = row._forget.rect.y + 20
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(MousePos(x, y), 0, i == 0, i == 3, i < 3, i * 0.1)
                                               for i, x in enumerate((start, start - 70, start - 140, start - 210))])
  draw(panel)
  assert panel._list._scroller.scroll_panel.get_offset() < 0
  assert gui_app.get_active_widget() is panel
  assert actions == []


def test_wifi_wrong_password_and_reconnect_use_native_callbacks(wifi_cards):
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
  panel, manager, actions = wifi_cards
  row = panel._list._scroller.items[0]
  manager.connected_ssid = None
  row.button.set_wrong_password()
  panel._update_state()
  assert resolve(row.value) == tr('wrong password')
  assert not row.button._show_forget_btn
  manager.is_connection_saved = lambda _: False
  row._handle_mouse_release(rl.Vector2(row.rect.x + 50, row.rect.y + 50))
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, BigInputDialog)
  assert actions == []
  panel.native._connect_with_password('Home', 'new-password')
  assert actions == [('password', 'Home', 'new-password')]
  gui_app.pop_widget()
  manager.is_connection_saved = lambda _: True
  row.button._wrong_password = False
  row._handle_mouse_release(rl.Vector2(row.rect.x + 50, row.rect.y + 50))
  assert actions[-1] == ('connect', 'Home')


@pytest.mark.parametrize('cancel_step', [1, 2])
def test_device_reset_cancel_at_each_confirmation_preserves_settings(monkeypatch, cancel_step):
  from openpilot.system.hardware import HARDWARE
  panel = make_panel('device')
  gui_app.push_widget(panel)
  reboots = []
  monkeypatch.setattr(HARDWARE, 'reboot', lambda: reboots.append(True))
  ui_state.params.put('InteractivityTimeout', 70, block=True)
  panel.controller._reset_settings()
  if cancel_step == 2:
    gui_app.get_active_widget()._confirm_button_callback()
  dialog = gui_app.get_active_widget()
  draw(dialog)
  assert dialog._compact_view._confirm.rect.height == 64
  dialog._cancel_button_callback()
  assert not reboots and ui_state.params.get('InteractivityTimeout') == 70


@pytest.mark.parametrize('onroad_step', [1, 2, 3])
def test_device_reset_rechecks_offroad_before_prompt_and_each_commit(monkeypatch, onroad_step):
  from openpilot.system.hardware import HARDWARE
  panel = make_panel('device')
  gui_app.push_widget(panel)
  reboots = []
  monkeypatch.setattr(HARDWARE, 'reboot', lambda: reboots.append(True))
  ui_state.params.put('InteractivityTimeout', 70, block=True)
  if onroad_step == 1:
    monkeypatch.setattr(ui_state, 'started', True)
  panel.controller._reset_settings()
  if onroad_step > 1:
    if onroad_step == 3:
      gui_app.get_active_widget()._confirm_button_callback()
    monkeypatch.setattr(ui_state, 'started', True)
    gui_app.get_active_widget()._confirm_button_callback()
  assert gui_app.get_active_widget() is panel
  assert not reboots and ui_state.params.get('InteractivityTimeout') == 70


def test_device_reset_double_confirmation_commits_and_reboots_once(monkeypatch):
  from openpilot.system.hardware import HARDWARE
  panel = make_panel('device')
  gui_app.push_widget(panel)
  reboots = []
  monkeypatch.setattr(HARDWARE, 'reboot', lambda: reboots.append(True))
  ui_state.params.put('InteractivityTimeout', 70, block=True)
  panel.controller._reset_settings()
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get('InteractivityTimeout') == 70
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get('InteractivityTimeout') is None
  assert reboots == [True]


def test_device_connect_disabling_blocks_uploads_even_from_stale_button():
  panel = make_panel('device')
  gui_app.push_widget(panel)
  controller = panel.controller
  uploads = controller._onroad_uploads_and_reset_settings.action_item.left_button
  ui_state.params.put_bool('OnroadUploads', True, block=True)
  ui_state.params.put_bool('dp_dev_disable_connect', True, block=True)
  controller._on_disable_connect_changed(True)
  assert not ui_state.params.get_bool('OnroadUploads')
  uploads._click_callback()
  assert not ui_state.params.get_bool('OnroadUploads')
  panel.refresh()
  assert not uploads.enabled
  ui_state.params.put_bool('dp_dev_disable_connect', False, block=True)
  uploads._click_callback()
  assert ui_state.params.get_bool('OnroadUploads')


@pytest.mark.parametrize('kind', ['backup', 'restore'])
def test_sunnylink_service_interruption_returns_to_wait_and_can_retry(sunnylink_transfer, monkeypatch, kind):
  panel, manager, sm = sunnylink_transfer
  sm.alive = {'backupManagerSP': True}
  controller = panel.controller
  clock = [100]
  monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
  controller._start_transfer(kind)
  setattr(manager, kind + 'Status', 'inProgress')
  setattr(manager, kind + 'Progress', 40)
  controller.handle_backup_restore_progress()
  sm.alive['backupManagerSP'] = False
  controller.handle_backup_restore_progress()
  assert not controller._transfer_seen_running
  assert controller._transfer_status() == tr('Waiting for ' + kind + ' service')
  clock[0] += controller.TRANSFER_WAIT_TIMEOUT + 1
  controller.handle_backup_restore_progress()
  assert controller._can_start_transfer(kind)
  controller._start_transfer(kind)
  sm.alive['backupManagerSP'] = True
  controller.handle_backup_restore_progress()
  assert controller._transfer_seen_running
  assert controller._transfer_progress == 40


def test_sunnylink_reopened_interface_adopts_pending_request(sunnylink_transfer):
  panel, manager, _ = sunnylink_transfer
  controller = panel.controller
  ui_state.params.put('BackupManager_RestoreVersion', 'latest', block=True)
  controller.handle_backup_restore_progress()
  assert controller._restore_in_progress
  assert controller._transfer_status() == tr('Waiting for restore service')
  manager.restoreStatus, manager.restoreProgress = 'inProgress', 25
  controller.handle_backup_restore_progress()
  assert controller._transfer_status() == tr('Restoring {progress}%').format(progress=25)


@pytest.fixture
def trips_panel(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import trips
  monkeypatch.setattr(trips.threading, 'Thread', lambda *args, **kwargs: SimpleNamespace(start=lambda: None, is_alive=lambda: False))
  return make_panel('trips')


@pytest.mark.parametrize('data', [[], 'broken', {'all': []}, {'all': {}},
                                 {'all': {'routes': 1, 'distance': None, 'minutes': 3}},
                                 {'all': {'routes': 1, 'distance': -1, 'minutes': 3}},
                                 {'all': {'routes': 1.5, 'distance': 1, 'minutes': 3}},
                                 {'all': {'routes': True, 'distance': 1, 'minutes': 3}}])
def test_trip_statistics_reject_malformed_cache_and_keep_page_usable(monkeypatch, data):
  import json
  from pathlib import Path
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import trips
  monkeypatch.setattr(trips.threading, 'Thread', lambda *args, **kwargs: SimpleNamespace(start=lambda: None, is_alive=lambda: False))
  Path(ui_state.params.get_param_path('ApiCache_DriveStats')).write_text(json.dumps(data))
  panel = make_panel('trips')
  gui_app.push_widget(panel)
  draw(panel)
  assert panel.controller._stats == {}
  assert panel.controller.status() == tr('Invalid drive statistics data')
  assert panel._value('all', 'distance') == tr('N/A')


@pytest.mark.parametrize('failure', ['http', 'invalid', 'exception'])
def test_trip_fetch_failure_preserves_last_valid_values_and_status_language(trips_panel, monkeypatch, failure):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import trips
  controller = trips_panel.controller
  stats = {'all': {'routes': 2, 'distance': 10, 'minutes': 90}, 'week': {'routes': 1, 'distance': 4, 'minutes': 30}}
  controller._stats = stats
  ui_state.params.put('ApiCache_DriveStats', stats, block=True)
  ui_state.params.put('DongleId', 'test-device', block=True)
  monkeypatch.setattr(trips, 'get_token', lambda _: 'test-token')
  def response(*args, **kwargs):
    if failure == 'exception':
      raise OSError('offline')
    return SimpleNamespace(status_code=503 if failure == 'http' else 200, json=lambda: {'all': {}})
  monkeypatch.setattr(trips, 'api_get', response)
  controller._fetch_drive_stats()
  expected = 'Invalid drive statistics data' if failure == 'invalid' else 'Unable to fetch drive statistics'
  assert controller.status() == tr(expected)
  assert controller._stats == stats
  assert ui_state.params.get('ApiCache_DriveStats') == stats
  assert not controller._loading
  multilang._language = 'en'
  multilang.setup()
  assert controller.status() == expected


def test_trip_statistics_refresh_saves_values_and_converts_units(trips_panel, monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import trips
  stats = {'all': {'routes': 3, 'distance': 10, 'minutes': 90}, 'week': {'routes': 1, 'distance': 2, 'minutes': 30}}
  ui_state.params.put('DongleId', 'test-device', block=True)
  monkeypatch.setattr(trips, 'get_token', lambda _: 'test-token')
  monkeypatch.setattr(trips, 'api_get', lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: stats))
  trips_panel.controller._fetch_drive_stats()
  assert ui_state.params.get('ApiCache_DriveStats') == stats
  assert trips_panel.controller.status() == tr('Drive statistics updated')
  monkeypatch.setattr(ui_state, 'is_metric', True)
  assert trips_panel._value('all', 'distance') == '16 ' + tr('KM')
  assert trips_panel._value('all', 'minutes') == '1.5 ' + tr('Hours')
  assert trips_panel._value('week', 'routes') == '1'
  monkeypatch.setattr(ui_state, 'is_metric', False)
  assert trips_panel._value('all', 'distance') == '10 ' + tr('Miles')
  trips_panel.controller.request_refresh()
  assert trips_panel.controller._refresh_event.is_set()
  trips_panel.controller._refresh_event.clear()
  monkeypatch.setattr(ui_state, 'started', True)
  trips_panel.controller.request_refresh()
  assert not trips_panel.controller._refresh_event.is_set()


def test_trip_unregistered_device_does_not_request_remote_statistics(trips_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import trips
  called = []
  monkeypatch.setattr(trips, 'api_get', lambda *args, **kwargs: called.append(True))
  trips_panel.controller._fetch_drive_stats()
  assert not called
  assert trips_panel.controller.status() == tr('Device is not registered')
  assert not trips_panel.controller._loading


def test_shared_large_display_backup_button_keeps_progress_and_failure(monkeypatch):
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.sunnylink import SunnylinkLayout
  manager = custom.BackupManagerSP.new_message()
  monkeypatch.setattr(ui_state, 'sm', {'backupManagerSP': manager})
  ui_state.params.put_bool('SunnylinkEnabled', True, block=True)
  controller = SunnylinkLayout()
  controller._start_transfer('backup')
  controller.handle_backup_restore_progress()
  assert resolve(controller._backup_btn._label._text) == tr('Waiting for backup service')
  manager.backupStatus, manager.backupProgress = 'inProgress', 75
  controller.handle_backup_restore_progress()
  assert resolve(controller._backup_btn._label._text) == tr('Backing up {progress}%').format(progress=75)
  manager.backupStatus = 'failed'
  ui_state.params.remove('BackupManager_CreateBackup')
  controller.handle_backup_restore_progress()
  controller.handle_backup_restore_progress()
  assert resolve(controller._backup_btn._label._text) == tr('Retry Backup')
  assert controller._transfer_status() == tr('Backup Failed')
  assert controller._sunnylink_description.is_visible
  assert controller._backup_btn.enabled


def test_sunnylink_error_details_can_scroll_to_the_last_line(sunnylink_transfer):
  panel, _, _ = sunnylink_transfer
  controller = panel.controller
  controller._transfer_message = 'Restore Failed'
  controller._transfer_error = 'Failed to restore 123 settings'
  panel.refresh()
  panel._rows[controller._transfer_item][0].callback()
  detail = gui_app.get_active_widget()
  draw(detail)
  scroller = detail._list._scroller
  assert scroller.content_size > detail._list.rect.height
  scroller.scroll_panel.set_offset(detail._list.rect.height - scroller.content_size)
  draw(detail)
  body = scroller.items[0]
  assert body.rect.y + body.rect.height <= 241
  assert '123 项设置恢复失败' in resolve(body.text)


@pytest.mark.parametrize('seconds,label', [(3, '3 s'), (30, '30 s'), (60, '1 min'), (90, '1 min 30 s'), (120, '2 min')])
def test_display_timeout_value_reports_exact_duration(seconds, label):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.display import duration_label
  expected = duration_label(seconds)
  assert expected != ''
  multilang._language = 'en'
  multilang.setup()
  assert duration_label(seconds) == label
  ui_state.params.put('InteractivityTimeout', seconds, block=True)
  panel = make_panel('display')
  gui_app.push_widget(panel)
  assert panel.controller._interactivity_timeout.action_item.get_displayed_value() == label


def test_timezone_selected_card_is_visible_and_english_search_works_in_chinese(monkeypatch):
  from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
  ui_state.params.put('Timezone', 6, block=True)
  panel = make_panel('display')
  gui_app.push_widget(panel)
  item = panel.controller._timezone_item
  panel._open_number(item, lambda: item.title, lambda: item.description)
  picker = gui_app.get_active_widget()
  draw(picker)
  draw(picker)
  selected = picker._rows[6]
  assert selected.rect.x >= 0 and selected.rect.x + selected.rect.width <= 536
  assert resolve(selected.value) == '✓'
  captured = []
  monkeypatch.setattr(InputDialogSP, 'show', lambda self: captured.append(self))
  picker._search()
  captured[-1].callback(DialogResult.CONFIRM, 'Shanghai')
  draw(picker)
  assert len(picker._list._scroller.items) == 1
  assert resolve(picker._list._scroller.items[0].title) == tr('Asia/Shanghai')
  picker._search()
  assert captured[-1].current_text == 'Shanghai'
  captured[-1].callback(DialogResult.CONFIRM, 'no-such-zone')
  draw(picker)
  assert resolve(picker._list._scroller.items[0].title) == tr('No matching options')
  assert ui_state.params.get('Timezone') == 6
  picker._search()
  captured[-1].callback(DialogResult.CONFIRM, '')
  assert len(picker._list._scroller.items) == 11
  picker._rows[0].callback()
  assert ui_state.params.get('Timezone') == 0
  assert gui_app.get_active_widget() is panel


def test_selected_language_visible_and_cancel_keeps_device_page():
  from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
  panel = make_panel('device')
  gui_app.push_widget(panel)
  panel.controller._show_language_dialog()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, MultiOptionDialog)
  draw(dialog)
  draw(dialog)
  index = list(multilang.languages).index(multilang.codes[multilang.language])
  row = dialog._compact_page._list._scroller.items[index]
  assert row.rect.x >= 0 and row.rect.x + row.rect.width <= 536
  dialog._set_result(DialogResult.CANCEL)
  assert multilang.language == 'zh-CHS'
  assert gui_app.get_active_widget() is panel


@pytest.mark.parametrize('operation,param', [('_reboot_prompt', 'DoReboot'), ('_power_off_prompt', 'DoShutdown')])
@pytest.mark.parametrize('outcome', ['accept', 'cancel', 'engage'])
def test_device_power_confirmation_rechecks_state_and_saves_before_return(monkeypatch, operation, param, outcome):
  engaged = [False]
  monkeypatch.setattr(type(ui_state), 'engaged', property(lambda self: engaged[0]))
  panel = make_panel('device')
  gui_app.push_widget(panel)
  getattr(panel.controller, operation)()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  if outcome == 'cancel':
    dialog._cancel_button_callback()
  else:
    engaged[0] = outcome == 'engage'
    dialog._confirm_button_callback()
  assert ui_state.params.get_bool(param) == (outcome == 'accept')
  assert gui_app.get_active_widget() is panel


def test_device_power_off_hidden_and_old_confirm_blocked_when_vehicle_starts(monkeypatch):
  panel = make_panel('device')
  gui_app.push_widget(panel)
  controller = panel.controller
  controller._power_off_prompt()
  dialog = gui_app.get_active_widget()
  monkeypatch.setattr(ui_state, 'started', True)
  panel.refresh()
  assert not controller._power_buttons.action_item.right_button.is_visible
  dialog._confirm_button_callback()
  assert not ui_state.params.get_bool('DoShutdown')
  controller._power_off_prompt()
  assert gui_app.get_active_widget() is panel


@pytest.mark.parametrize('outcome', ['accept', 'cancel', 'engage'])
def test_device_calibration_reset_removes_all_learning_only_after_confirmation(monkeypatch, outcome):
  params = ('CalibrationParams', 'LiveTorqueParameters', 'LiveParameters', 'LiveParametersV2', 'LiveDelay')
  for param in params:
    ui_state.params.put(param, {'test': 'calibration-data'} if param == 'LiveParameters' else b'test-calibration-data', block=True)
  saved = {param: ui_state.params.get(param) for param in params}
  engaged = [False]
  monkeypatch.setattr(type(ui_state), 'engaged', property(lambda self: engaged[0]))
  panel = make_panel('device')
  gui_app.push_widget(panel)
  panel.controller._reset_calibration_prompt()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  if outcome == 'cancel':
    dialog._cancel_button_callback()
  else:
    engaged[0] = outcome == 'engage'
    dialog._confirm_button_callback()
  assert ui_state.params.get_bool('OnroadCycleRequested') == (outcome == 'accept')
  for param in params:
    assert ui_state.params.get(param) == (None if outcome == 'accept' else saved[param])


@pytest.mark.parametrize('pitch,yaw', [(0.03, -0.02), (-0.03, 0.02), (float('nan'), 0.1)])
def test_calibration_description_shows_valid_angles_and_progress_in_current_language(pitch, yaw):
  from cereal import messaging
  import math
  event = messaging.new_message('liveCalibration')
  event.liveCalibration.calStatus = 'calibrated'
  event.liveCalibration.rpyCalib = [0, pitch, yaw]
  ui_state.params.put('CalibrationParams', event.to_bytes(), block=True)
  event = messaging.new_message('liveDelay')
  event.liveDelay.calPerc = 32
  ui_state.params.put('LiveDelay', event.to_bytes(), block=True)
  event = messaging.new_message('liveTorqueParameters')
  event.liveTorqueParameters.useParams = True
  event.liveTorqueParameters.calPerc = 48
  ui_state.params.put('LiveTorqueParameters', event.to_bytes(), block=True)
  panel = make_panel('device')
  gui_app.push_widget(panel)
  controller = panel.controller
  controller._update_calib_description()
  text = controller._reset_calib_btn.description
  assert '32%' in text and '48%' in text
  assert 'nan' not in text
  if math.isfinite(pitch):
    assert f'{abs(math.degrees(pitch)):.1f}°' in text
    assert (tr('down') if pitch > 0 else tr('up')) in text
    assert (tr('left') if yaw > 0 else tr('right')) in text
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  controller._update_calib_description()
  assert 'Steering lag calibration is 32% complete.' in controller._reset_calib_btn.description


@pytest.mark.parametrize('percentage', [-128, -1, 101, 127])
def test_calibration_progress_stays_within_zero_to_one_hundred(percentage):
  from cereal import messaging
  for service, param in [('liveDelay', 'LiveDelay'), ('liveTorqueParameters', 'LiveTorqueParameters')]:
    event = messaging.new_message(service)
    getattr(event, service).calPerc = percentage
    if service == 'liveTorqueParameters':
      event.liveTorqueParameters.useParams = True
    ui_state.params.put(param, event.to_bytes(), block=True)
  panel = make_panel('device')
  panel.controller._update_calib_description()
  text = panel.controller._reset_calib_btn.description
  if percentage < 0:
    assert text.count('0%') == 2
  else:
    assert tr('<br><br>Steering lag calibration is complete.') in text
    assert tr(' Steering torque response calibration is complete.') in text
  assert f'{percentage}%' not in text


def test_device_language_selection_saves_language_and_updates_existing_setting_rows(monkeypatch):
  monkeypatch.setattr(multilang, '_params', ui_state.params)
  panel = make_panel('device')
  gui_app.push_widget(panel)
  panel.controller._show_language_dialog()
  dialog = gui_app.get_active_widget()
  draw(dialog)
  languages = list(multilang.languages)
  english = next(name for name in languages if multilang.languages[name] == 'en')
  dialog._compact_page._list._scroller.items[languages.index(english)].callback()
  assert multilang.language == 'en'
  assert ui_state.params.get('LanguageSetting') == 'en'
  assert gui_app.get_active_widget() is panel
  assert resolve(panel._header.title) == 'Device'
  panel.controller._show_language_dialog()
  dialog = gui_app.get_active_widget()
  draw(dialog)
  chinese = next(name for name in languages if multilang.languages[name] == 'zh-CHS')
  dialog._compact_page._list._scroller.items[languages.index(chinese)].callback()
  assert ui_state.params.get('LanguageSetting') == 'zh-CHS'
  assert resolve(panel._header.title) == tr('Device')


@pytest.fixture
def camera_preview(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.onroad import driver_camera_dialog as camera
  from openpilot.selfdrive.ui.ui_state import device
  class FakeCamera:
    frame = None
    def __init__(self, *args):
      self.closed = 0
    def _update_state(self):
      pass
    def _render(self, rect):
      pass
    def close(self):
      self.closed += 1
  published = []
  monkeypatch.setattr(camera, 'DriverCameraView', FakeCamera)
  monkeypatch.setattr(camera.messaging, 'PubMaster', lambda services: SimpleNamespace(send=lambda service, msg: published.append(msg)))
  monkeypatch.setattr(device, '_interactive_timeout_callbacks', [])
  monkeypatch.setattr(device, '_override_interactive_timeout', None)
  monkeypatch.setattr(device, '_last_interactive_timeout', None)
  monkeypatch.setattr(device, '_interaction_time', -1)
  return camera, device, published


def test_driver_preview_registers_timeout_only_while_open_and_cleans_up(camera_preview):
  camera, device, published = camera_preview
  baseline = list(device._interactive_timeout_callbacks)
  for _ in range(3):
    preview = camera.DriverCameraDialog()
    view = preview._camera_view
    gui_app.push_widget(preview)
    assert ui_state.params.get_bool('IsDriverViewEnabled')
    assert device._override_interactive_timeout == 300
    assert len(device._interactive_timeout_callbacks) == len(baseline) + 1
    preview._on_timeout()
    assert not ui_state.params.get_bool('IsDriverViewEnabled')
    assert device._override_interactive_timeout is None
    assert device._interactive_timeout_callbacks == baseline
    assert view.closed == 1
    assert preview._camera_view is None
    assert published[-1].selfdriveState.alertSound == 'none'
  other = CompactPage('other')
  gui_app.push_widget(other)
  preview._on_timeout()
  assert gui_app.get_active_widget() is other


def test_driver_preview_leaves_on_vehicle_start_and_does_not_close_unrelated_page(camera_preview, monkeypatch):
  camera, device, _ = camera_preview
  preview = camera.DriverCameraDialog()
  gui_app.push_widget(preview)
  monkeypatch.setattr(ui_state, 'started', True)
  draw(preview)
  assert not gui_app.widget_in_stack(preview)
  assert not ui_state.params.get_bool('IsDriverViewEnabled')
  assert device._interactive_timeout_callbacks == []
  panel = make_panel('device')
  gui_app.push_widget(panel)
  panel.controller._open_driver_camera()
  assert gui_app.get_active_widget() is panel


def test_driver_preview_reopens_same_instance_with_fresh_camera(camera_preview):
  camera, device, _ = camera_preview
  preview = camera.DriverCameraDialog()
  gui_app.push_widget(preview)
  first_view = preview._camera_view
  gui_app.pop_widget()
  draw(preview)
  assert first_view.closed == 1
  gui_app.push_widget(preview)
  assert preview._camera_view is not first_view
  assert preview._camera_view.closed == 0
  assert ui_state.params.get_bool('IsDriverViewEnabled')
  assert device._interactive_timeout_callbacks == [preview._on_timeout]
  gui_app.pop_widget()
  assert device._interactive_timeout_callbacks == []


def test_driver_camera_close_releases_transport_shader_and_transition_callback(monkeypatch):
  from openpilot.selfdrive.ui.mici.onroad.driver_camera_dialog import DriverCameraView
  from msgq.visionipc import VisionStreamType
  monkeypatch.setattr(ui_state, '_offroad_transition_callbacks', [])
  for _ in range(3):
    view = DriverCameraView('camerad', VisionStreamType.VISION_STREAM_DRIVER)
    assert view._offroad_transition in ui_state._offroad_transition_callbacks
    assert view.client is not None and view.shader.id != 0
    view.close()
    view.close()
    assert ui_state._offroad_transition_callbacks == []
    assert view.client is None and view._target_client is None
    assert view.frame is None and view.shader.id == 0


@pytest.mark.parametrize('action', ['_open_driver_camera', '_on_regulatory', '_on_review_training_guide'])
def test_device_offroad_actions_recheck_vehicle_state(monkeypatch, action):
  panel = make_panel('device')
  gui_app.push_widget(panel)
  monkeypatch.setattr(ui_state, 'started', True)
  getattr(panel.controller, action)()
  assert gui_app.get_active_widget() is panel


def test_driver_preview_disabled_environment_blocks_direct_action(monkeypatch):
  panel = make_panel('device')
  gui_app.push_widget(panel)
  monkeypatch.setenv('DISABLE_DRIVER', '1')
  panel.controller._open_driver_camera()
  assert gui_app.get_active_widget() is panel


@pytest.mark.parametrize('vision', [False, True])
@pytest.mark.parametrize('level', ['one', 'two', 'three'])
def test_driver_preview_alert_levels_are_translated(camera_preview, monkeypatch, vision, level):
  from cereal import messaging
  camera, _, published = camera_preview
  preview = camera.DriverCameraDialog()
  gui_app.push_widget(preview)
  msg = messaging.new_message('driverMonitoringState')
  dm = msg.driverMonitoringState
  dm.activePolicy = 'vision' if vision else 'wheeltouch'
  dm.alertLevel = level
  dm.visionPolicyState.awarenessPercent = 75
  dm.wheeltouchPolicyState.awarenessPercent = 80
  monkeypatch.setattr(ui_state, 'sm', {'driverMonitoringState': dm})
  labels = []
  monkeypatch.setattr(camera, 'gui_label', lambda rect, text, **kwargs: labels.append(text))
  preview._render_dm_alerts(rl.Rectangle(0, 0, 536, 240))
  expected = tr('{action} - Level {level}').format(action=tr('Pay Attention') if vision else tr('Touch Wheel'),
                                                level={'one': 1, 'two': 2, 'three': 3}[level])
  assert expected in labels
  assert 'Level' not in expected and 'level' not in expected
  number = {'one': 1, 'two': 2, 'three': 3}[level]
  assert f'等级 {number}' in expected
  assert published[-1].selfdriveState.alertSound == {'one': 'none', 'two': 'promptDistracted', 'three': 'warningImmediate'}[level]
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  labels.clear()
  preview._render_dm_alerts(rl.Rectangle(0, 0, 536, 240))
  assert f'{"Pay Attention" if vision else "Touch Wheel"} - Level {number}' in labels


def test_numeric_range_and_step_use_display_units_without_parameter_writes(monkeypatch):
  from openpilot.system.ui.widgets import compact
  panel = make_panel('models')
  gui_app.push_widget(panel)
  item = panel.controller.lane_turn_value_control
  monkeypatch.setattr(ui_state, 'is_metric', True)
  action = item.action_item
  params_before = ui_state.params.get('LaneTurnValue')
  detail = CompactNumberPage('speed', action, lambda: None, '')
  labels = []
  monkeypatch.setattr(compact, 'gui_label', lambda rect, text, *args, **kwargs: labels.append(text))
  detail._render(rl.Rectangle(0, 0, 536, 240))
  assert tr('Range: {minimum}–{maximum}').format(minimum='8 km/h', maximum='32 km/h') in labels
  assert tr('Step: {step}').format(step='1.00 km/h') in labels
  assert ui_state.params.get('LaneTurnValue') == params_before
  monkeypatch.setattr(ui_state, 'is_metric', False)
  panel.refresh()
  labels.clear()
  detail._render(rl.Rectangle(0, 0, 536, 240))
  assert tr('Range: {minimum}–{maximum}').format(minimum='5 mph', maximum='20 mph') in labels
  assert tr('Step: {step}').format(step='1.00 mph') in labels


@pytest.mark.parametrize('setting', ['blinker_speed', 'blinker_delay', 'lane_offset', 'software_delay',
                                    'torque_factor', 'torque_friction', 'htd_angle', 'acc_short'])
def test_numeric_details_show_units_and_language_without_changing_storage(monkeypatch, setting):
  from openpilot.system.ui.widgets import compact
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.steering_sub_layouts.torque_settings import TorqueSettingsLayout
  ui_state.params.put_bool('BlinkerPauseLateralControl', True, block=True)
  ui_state.params.put_bool('LaneTurnDesire', True, block=True)
  ui_state.params.put_bool('EnforceTorqueControl', True, block=True)
  ui_state.params.put_bool('CustomTorqueParams', True, block=True)
  ui_state.params.put_bool('CustomAccIncrementsEnabled', True, block=True)
  ui_state.params.put_bool('dp_htd_enabled', True, block=True)
  ui_state.CP = car.CarParams.new_message(pcmCruise=False)
  from cereal import custom
  ui_state.CP_SP = custom.CarParamsSP.new_message()
  ui_state.has_longitudinal_control = True
  key, attr, param, stored, expected = {
    'blinker_speed': ('steering', '_blinker_control_options', 'BlinkerMinLateralControlSpeed', 25, ('25 {speed}', '0 {speed}', '255 {speed}', '5 {speed}')),
    'blinker_delay': ('steering', '_blinker_reengage_delay', 'BlinkerLateralReengageDelay', 3, ('3 {seconds}', '0 {seconds}', '10 {seconds}', '1 {seconds}')),
    'lane_offset': ('steering', '_lat_position_offset', 'LateralPositionOffset', -3, ('-3 {length}', '-15 {length}', '15 {length}', '1 {length}')),
    'software_delay': ('models', 'delay_control', 'LagdToggleDelay', .2, ('0.20 {seconds}', '0.05 {seconds}', '0.50 {seconds}', '0.01 {seconds}')),
    'torque_factor': ('torque', '_torque_lat_accel_factor', 'TorqueParamsOverrideLatAccelFactor', .25, ('0.25 m/s²', '0.01 m/s²', '5.00 m/s²', '0.01 m/s²')),
    'torque_friction': ('torque', '_torque_friction', 'TorqueParamsOverrideFriction', .1, ('0.10', '0.01', '1.00', '0.01')),
    'htd_angle': ('cruise', 'htd_angle_threshold', 'dp_htd_turn_angle_threshold', 60, ('60°', '30°', '120°', '5°')),
    'acc_short': ('cruise', 'custom_acc_short_increment', 'CustomAccShortPressIncrement', 3, ('3 {speed}', '1 {speed}', '10 {speed}', '1 {speed}')),
  }[setting]
  ui_state.params.put(param, stored, block=True)
  if key == 'torque':
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel
    panel = SettingsPanel('Customize Torque Params', TorqueSettingsLayout(lambda: None))
  else:
    panel = make_panel(key)
  gui_app.push_widget(panel)
  item = getattr(panel.controller, attr)
  row = panel._rows[item][0]
  row.callback()
  detail = gui_app.get_active_widget()
  assert isinstance(detail, CompactNumberPage)
  labels = []
  monkeypatch.setattr(compact, 'gui_label', lambda rect, text, *args, **kwargs: labels.append((text, rect, args)))
  saved = ui_state.params.get(param)
  for language, metric in [('zh-CHS', True), ('en', False), ('zh-CHS', False), ('en', True)]:
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    monkeypatch.setattr(ui_state, 'is_metric', metric)
    ui_state.params.put_bool('IsMetric', metric, block=True)
    labels.clear()
    draw(detail)
    units = {'seconds': '秒' if language == 'zh-CHS' else 's', 'length': '厘米' if language == 'zh-CHS' else 'cm',
             'speed': 'km/h' if metric else 'mph'}
    value, minimum, maximum, step = [label.format(**units) for label in expected]
    if setting == 'blinker_speed':
      value = f'{round(stored / (1 if metric else 1.609344) * 100) / 100:g} {units["speed"]}'
    text = [label for label, _, _ in labels]
    assert value in text
    assert tr('Range: {minimum}–{maximum}').format(minimum=minimum, maximum=maximum) in text
    assert tr('Step: {step}').format(step=step) in text
    from openpilot.system.ui.lib.text_measure import measure_text_cached
    for label, rect, args in labels:
      if label in (value, tr('Range: {minimum}–{maximum}').format(minimum=minimum, maximum=maximum), tr('Step: {step}').format(step=step)):
        assert measure_text_cached(gui_app.font(), label, args[0]).x <= rect.width
    assert ui_state.params.get(param) == saved
  detail.change(1)
  wait_param(param, pytest.approx(stored + (.01 if setting in ('software_delay', 'torque_factor', 'torque_friction') else
                                          5 if setting in ('blinker_speed', 'htd_angle') else 1)))


@pytest.mark.parametrize('offset_type', [1, 2])
def test_speed_limit_offset_card_has_title_units_and_live_detail(monkeypatch, offset_type):
  from openpilot.system.ui.widgets import compact
  ui_state.params.put('SpeedLimitOffsetType', offset_type, block=True)
  ui_state.params.put('SpeedLimitValueOffset', -3, block=True)
  panel = make_panel('cruise')
  gui_app.push_widget(panel)
  panel.controller._current_panel = type(panel.controller._current_panel).SLA
  draw(panel)
  item = panel._active._speed_limit_value_offset
  row = panel._rows[item][0]
  assert resolve(row.title) == tr('Speed Limit Offset Value')
  row.callback()
  detail = gui_app.get_active_widget()
  assert isinstance(detail, CompactNumberPage)
  labels = []
  monkeypatch.setattr(compact, 'gui_label', lambda rect, text, *args, **kwargs: labels.append(text))
  for language, metric in [('zh-CHS', True), ('en', False)]:
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    monkeypatch.setattr(ui_state, 'is_metric', metric)
    ui_state.params.put_bool('IsMetric', metric, block=True)
    labels.clear()
    draw(detail)
    unit = '%' if offset_type == 2 else (' km/h' if metric else ' mph')
    displayed = -3 if offset_type == 2 or metric else round(-3 / 1.609344 * 100) / 100
    assert f'{displayed:g}' + unit in labels
    assert tr('Step: {step}').format(step='1' + unit) in labels
    assert resolve(detail._header.title) == tr('Speed Limit Offset Value')
    assert ui_state.params.get('SpeedLimitValueOffset') == -3
  expected = detail.action.encode_value(detail.action.current_value + detail.action.value_change_step)
  detail.change(1)
  wait_param('SpeedLimitValueOffset', pytest.approx(expected))


@pytest.mark.parametrize('choice,stored', [(0, 1), (1, 5), (2, 10)])
def test_long_press_increment_labels_keep_units_and_non_linear_storage(monkeypatch, choice, stored):
  from cereal import custom
  ui_state.params.put_bool('CustomAccIncrementsEnabled', True, block=True)
  ui_state.CP = car.CarParams.new_message(pcmCruise=False)
  ui_state.CP_SP = custom.CarParamsSP.new_message()
  ui_state.has_longitudinal_control = True
  ui_state.params.put('CustomAccLongPressIncrement', 5, block=True)
  panel = make_panel('cruise')
  gui_app.push_widget(panel)
  item = panel.controller.custom_acc_long_increment
  panel._rows[item][0].callback()
  picker = gui_app.get_active_widget()
  assert isinstance(picker, CompactSelectPage)
  for language, metric in [('zh-CHS', True), ('en', False)]:
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    monkeypatch.setattr(ui_state, 'is_metric', metric)
    draw(picker)
    assert [resolve(row.title) for row in picker._rows] == [f'{value} ' + ('km/h' if metric else 'mph') for value in (1, 5, 10)]
    assert ui_state.params.get('CustomAccLongPressIncrement') == 5
  picker._rows[choice].callback()
  assert ui_state.params.get('CustomAccLongPressIncrement') == stored
  assert gui_app.get_active_widget() is panel


def test_timezone_entries_survive_translation_extraction():
  from openpilot.selfdrive.ui.translations.update_translations import extract_timezone_strings
  from openpilot.system.timezone_list import TZ_LIST
  entries = extract_timezone_strings()
  assert [entry.msgid for entry in entries] == TZ_LIST
  assert all(entry.msgid in multilang._translations for entry in entries)


def test_running_onroad_clock_changes_after_timezone_selection(driving_state, monkeypatch):
  import datetime
  from openpilot.system import timezone_list
  instant = datetime.datetime(2026, 11, 11, 12, 30, tzinfo=datetime.UTC)
  class FrozenDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
      return instant.astimezone(tz)
  monkeypatch.setattr(timezone_list.datetime, 'datetime', FrozenDatetime)
  renderer, _, _ = driving_state
  rendered = []
  monkeypatch.setattr(renderer, '_label', lambda rect, text, size: rendered.append(text))
  ui_state.params.put_bool('dp_show_date_time', True, block=True)
  ui_state.params.put('Timezone', 0, block=True)
  renderer._draw_optional(rl.Rectangle(0, 0, 476, 240))
  assert '2026-11-11 20:30:00' in rendered
  ui_state.params.put('Timezone', 6, block=True)
  rendered.clear()
  renderer._draw_optional(rl.Rectangle(0, 0, 476, 240))
  assert '2026-11-11 07:30:00' in rendered


@pytest.fixture
def firehose_panel(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.layouts.settings import firehose
  monkeypatch.setattr(firehose.threading, 'Thread', lambda *args, **kwargs: SimpleNamespace(start=lambda: None, is_alive=lambda: False))
  return make_panel('firehose')


@pytest.mark.parametrize('count', [0, 1, 123])
def test_firehose_contribution_card_preserves_count_and_translates_full_text(firehose_panel, count):
  panel = firehose_panel
  panel.controller._segment_count = count
  panel.controller._stats_available = True
  gui_app.push_widget(panel)
  draw(panel)
  row = panel._list._scroller.items[1]
  assert resolve(row.title) == tr('Training Data Contributions')
  assert resolve(row.value) == str(count)
  row.callback()
  detail = gui_app.get_active_widget()
  draw(detail)
  assert str(count) in resolve(detail._list._scroller.items[0].text)
  assert '训练' in panel.controller.contribution_text()
  multilang._language = 'en'
  multilang.setup()
  assert f'{count} segment' in panel.controller.contribution_text()


@pytest.mark.parametrize('data', [[], {'firehose': -1}, {'firehose': '2'}, {'firehose': True}, {}])
def test_firehose_invalid_cache_does_not_crash_or_invent_contributions(monkeypatch, data):
  import json
  from pathlib import Path
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.layouts.settings import firehose
  monkeypatch.setattr(firehose.threading, 'Thread', lambda *args, **kwargs: SimpleNamespace(start=lambda: None, is_alive=lambda: False))
  Path(ui_state.params.get_param_path('ApiCache_FirehoseStats')).write_text(json.dumps(data))
  panel = make_panel('firehose')
  gui_app.push_widget(panel)
  draw(panel)
  assert panel.controller.contribution_text() == tr('N/A')
  assert panel.controller.statistics_status() == tr('Invalid training statistics data')


@pytest.mark.parametrize('failure', ['http', 'invalid', 'exception'])
def test_firehose_failed_refresh_preserves_cached_count_and_allows_retry(firehose_panel, monkeypatch, failure):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.layouts.settings import firehose
  controller = firehose_panel.controller
  controller._segment_count, controller._stats_available = 7, True
  ui_state.params.put('ApiCache_FirehoseStats', {'firehose': 7}, block=True)
  ui_state.params.put('DongleId', 'test-device', block=True)
  monkeypatch.setattr(firehose, 'get_token', lambda _: 'test-token')
  def response(*args, **kwargs):
    if failure == 'exception':
      raise OSError('offline')
    return SimpleNamespace(status_code=503 if failure == 'http' else 200, json=lambda: {'firehose': -1})
  monkeypatch.setattr(firehose, 'api_get', response)
  controller._fetch_firehose_stats()
  assert controller._segment_count == 7
  assert controller._stats_available and not controller._stats_loading
  assert ui_state.params.get('ApiCache_FirehoseStats') == {'firehose': 7}
  controller.request_refresh()
  assert controller._refresh_event.is_set()
  expected = 'Invalid training statistics data' if failure == 'invalid' else 'Unable to fetch training statistics'
  assert controller.statistics_status() == tr(expected)
  multilang._language = 'en'
  multilang.setup()
  assert controller.statistics_status() == expected


def test_firehose_successful_refresh_publishes_saved_contributions(firehose_panel, monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.layouts.settings import firehose
  controller = firehose_panel.controller
  ui_state.params.put('DongleId', 'test-device', block=True)
  monkeypatch.setattr(firehose, 'get_token', lambda _: 'test-token')
  monkeypatch.setattr(firehose, 'api_get', lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: {'firehose': 14}))
  controller._fetch_firehose_stats()
  assert ui_state.params.get('ApiCache_FirehoseStats') == {'firehose': 14}
  assert controller._segment_count == 14
  assert controller.statistics_status() == tr('Training statistics updated')
  gui_app.push_widget(firehose_panel)
  draw(firehose_panel)
  assert resolve(firehose_panel._list._scroller.items[1].value) == '14'


def test_model_folder_and_default_labels_switch_language_without_rebuilding(model_panel, monkeypatch):
  from cereal import custom
  from openpilot.sunnypilot.models.default_model import DEFAULT_MODEL
  bundle = model_bundle()
  bundle['overrides'] = [{'key': 'folder', 'value': 'Release Models'}]
  manager = custom.ModelManagerSP.new_message(availableBundles=[bundle])
  monkeypatch.setattr(ui_state, 'sm', {'modelManagerSP': manager})
  ui_state.params.put('ModelManager_Favs', 'test-model', block=True)
  model_panel.refresh()
  model_panel.controller._handle_current_model_clicked()
  picker = gui_app.get_active_widget()
  draw(picker)
  rows = picker._compact_page._list._scroller.items
  assert any(tr('Favorites') in resolve(row.title) for row in rows)
  assert any(tr('Release Models') in resolve(row.title) for row in rows)
  assert any(resolve(row.title) == DEFAULT_MODEL + tr(' (Default)') for row in rows)
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(picker)
  assert any(resolve(row.title) == '+ Favorites' for row in rows)
  assert any('Release Models - Updated: 2026-11-11' in resolve(row.title) for row in rows)
  assert any(resolve(row.title) == DEFAULT_MODEL + ' (Default)' for row in rows)
  picker._on_search_confirm(DialogResult.CONFIRM, 'missing-model')
  draw(picker)
  assert any(resolve(row.title) == 'No matching options' for row in picker._compact_page._list._scroller.items)
  assert picker.selection_ref == 'Default'


def test_lane_change_modes_use_choice_cards_and_preserve_all_indices():
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  panel.controller._set_current_panel(PanelType.LANE_CHANGE)
  panel.refresh()
  item = panel._active._lane_change_timer
  for index in range(-1, 6):
    panel._open_number(item, lambda: item.title, lambda: item.description)
    picker = gui_app.get_active_widget()
    assert isinstance(picker, CompactSelectPage)
    assert len(picker._rows) == 7
    picker._rows[index + 1].callback()
    assert ui_state.params.get('AutoLaneChangeTimer') == index
    assert gui_app.get_active_widget() is panel
    assert item.action_item.get_displayed_value() == resolve(picker.choices[index + 1])


def test_torque_default_identity_and_value_survive_language_switch():
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.steering_sub_layouts.torque_settings import TorqueSettingsLayout
  controller = TorqueSettingsLayout(lambda: None)
  label, info = next(iter(controller.cached_torque_versions.items()))
  ui_state.params.put('TorqueControlTune', float(info['version']), block=True)
  controller._show_torque_version_dialog()
  picker = gui_app.get_active_widget()
  draw(picker)
  default = next(row for row in picker._compact_page._list._scroller.items if resolve(row.title) == tr('Default'))
  default.callback()
  assert picker.selection_ref == 'Default'
  multilang._language = 'en'
  multilang.setup()
  draw(picker)
  assert resolve(picker._compact_confirm_view._list._scroller.items[0].text) == 'Default'
  picker._compact_confirm_view._confirm._click_callback()
  assert ui_state.params.get('TorqueControlTune') is None
  controller._show_torque_version_dialog()
  picker = gui_app.get_active_widget()
  draw(picker)
  choice = next(row for row in picker._compact_page._list._scroller.items if resolve(row.title) == label)
  choice.callback()
  picker._compact_confirm_view._confirm._click_callback()
  assert ui_state.params.get('TorqueControlTune') == float(info['version'])


def test_static_information_value_and_full_detail_switch_language():
  from types import SimpleNamespace
  from openpilot.system.ui.widgets.list_view import text_item
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel
  item = text_item('Status', tr('Unavailable'))
  controller = CompactPage('controller')
  controller._scroller = SimpleNamespace(_items=[item])
  panel = SettingsPanel('Device', controller)
  gui_app.push_widget(panel)
  row = panel._rows[item][0]
  assert resolve(row.value) == tr('Unavailable')
  row.callback()
  detail = gui_app.get_active_widget()
  multilang._language = 'en'
  multilang.setup()
  assert resolve(row.value) == 'Unavailable'
  assert 'Unavailable' in resolve(detail._list._scroller.items[0].text)


def test_long_card_title_remeasures_fonts_when_language_changes(monkeypatch):
  from openpilot.system.ui.widgets.label import UnifiedLabel
  label = UnifiedLabel('A long model name with spaces', font_size=44)
  label.get_content_height(240)
  first_lines = label._cached_wrapped_lines
  assert label._cached_language == 'zh-CHS'
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  label.get_content_height(240)
  assert label._cached_language == 'en'
  assert label._cached_wrapped_lines is not first_lines


def test_disabled_setting_title_and_status_use_disabled_color(monkeypatch):
  from openpilot.system.ui.widgets import compact
  labels = []
  monkeypatch.setattr(compact, 'gui_label', lambda rect, text, size, color=rl.WHITE, **kwargs: labels.append((text, color)))
  row = compact.CompactRow('Unavailable setting', checked=lambda: False, enabled=False)
  row.set_parent_rect(rl.Rectangle(0, 0, 536, 184))
  row._render(row.rect)
  assert labels
  assert all(color.r == compact.MUTED.r and color.g == compact.MUTED.g for _, color in labels)


def test_sunnylink_consent_cancel_and_stale_confirm_preserve_saved_values(monkeypatch):
  from openpilot.system.version import sunnylink_consent_version
  panel = make_panel('sunnylink')
  gui_app.push_widget(panel)
  item = panel.controller._sunnylink_toggle
  panel._toggle(item)
  gui_app.get_active_widget()._cancel_button_callback()
  assert ui_state.params.get('CompletedSunnylinkConsentVersion') is None
  assert not ui_state.params.get_bool('SunnylinkEnabled')
  panel._toggle(item)
  monkeypatch.setattr(ui_state, 'started', True)
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get('CompletedSunnylinkConsentVersion') is None
  assert not ui_state.params.get_bool('SunnylinkEnabled')
  monkeypatch.setattr(ui_state, 'started', False)
  panel._toggle(item)
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get('CompletedSunnylinkConsentVersion') == sunnylink_consent_version
  assert ui_state.params.get_bool('SunnylinkEnabled')
  assert gui_app.get_active_widget() is panel


def test_confirm_text_and_buttons_follow_language_changes_after_creation():
  message = 'Are you sure you want to reset calibration?'
  dialog = ConfirmDialog(tr(message), tr('Reset'))
  gui_app.push_widget(dialog)
  draw(dialog)
  view = dialog._compact_view
  assert resolve(view._list._scroller.items[0].text) == tr(message)
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(dialog)
  assert resolve(view._list._scroller.items[0].text) == message
  assert resolve(view._confirm.text).casefold() == 'reset'
  assert resolve(view._cancel.text).casefold() == 'cancel'
  multilang._language = 'zh-CHS'
  multilang.setup()
  gui_app.on_language_changed('zh-CHS')
  draw(dialog)
  assert resolve(view._confirm.text) == tr('Reset')
  dialog.set_text(tr('Are you sure you want to reboot?'))
  draw(dialog)
  assert resolve(dialog._compact_view._list._scroller.items[0].text) == tr('Are you sure you want to reboot?')


def test_basic_restart_toggle_refreshes_engagement_and_blocks_stale_callback(monkeypatch):
  from types import SimpleNamespace
  panel = make_panel('toggles')
  gui_app.push_widget(panel)
  controller = panel.controller
  item = controller._toggles['RecordAudio']
  assert item.action_item.enabled
  monkeypatch.setattr(ui_state, 'sm', {'selfdriveState': SimpleNamespace(enabled=True),
                                     'selfdriveStateSP': SimpleNamespace(mads=SimpleNamespace(enabled=False))})
  monkeypatch.setattr(ui_state, 'started', True)
  controller._toggle_callback(True, 'RecordAudio')
  assert not ui_state.params.get_bool('RecordAudio')
  assert not ui_state.params.get_bool('OnroadCycleRequested')
  assert not item.action_item.enabled
  monkeypatch.setattr(ui_state, 'started', False)
  controller._toggle_callback(True, 'RecordAudio')
  assert ui_state.params.get_bool('RecordAudio')
  assert ui_state.params.get_bool('OnroadCycleRequested')
  assert item.action_item.get_state()


def test_basic_external_lock_disables_control_and_releases_without_rebuild():
  panel = make_panel('toggles')
  gui_app.push_widget(panel)
  controller = panel.controller
  ui_state.params.put_bool('RecordFrontLock', True, block=True)
  panel.refresh()
  assert not controller._toggles['RecordFront'].action_item.enabled
  controller._toggle_callback(True, 'RecordFront')
  assert not ui_state.params.get_bool('RecordFront')
  ui_state.params.put_bool('RecordFrontLock', False, block=True)
  panel.refresh()
  assert controller._toggles['RecordFront'].action_item.enabled
  controller._toggle_callback(True, 'RecordFront')
  assert ui_state.params.get_bool('RecordFront')


def test_experimental_mode_requires_known_longitudinal_support():
  panel = make_panel('toggles')
  gui_app.push_widget(panel)
  controller = panel.controller
  assert not controller._toggles['ExperimentalMode'].action_item.enabled
  assert not controller._long_personality_setting.action_item.enabled
  controller._handle_experimental_mode_toggle(True)
  assert gui_app.get_active_widget() is panel
  assert not ui_state.params.get_bool('ExperimentalMode')


@pytest.mark.parametrize('change', ['cancel', 'unknown', 'stock_acc'])
def test_experimental_confirmation_rechecks_vehicle_support_before_saving(monkeypatch, change):
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message())
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  panel = make_panel('toggles')
  gui_app.push_widget(panel)
  controller = panel.controller
  panel._toggle(controller._toggles['ExperimentalMode'])
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  assert not controller._toggles['ExperimentalMode'].action_item.get_state()
  assert not ui_state.params.get_bool('ExperimentalMode')
  if change == 'unknown':
    monkeypatch.setattr(ui_state, 'CP', None)
  elif change == 'stock_acc':
    monkeypatch.setattr(ui_state, 'has_longitudinal_control', False)
  dialog._cancel_button_callback() if change == 'cancel' else dialog._confirm_button_callback()
  assert not ui_state.params.get_bool('ExperimentalMode')
  assert not ui_state.params.get_bool('ExperimentalModeConfirmed')


def test_experimental_confirmation_and_external_personality_refresh(monkeypatch):
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message())
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  panel = make_panel('toggles')
  gui_app.push_widget(panel)
  controller = panel.controller
  panel._toggle(controller._toggles['ExperimentalMode'])
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get_bool('ExperimentalMode') and ui_state.params.get_bool('ExperimentalModeConfirmed')
  ui_state.params.put('LongitudinalPersonality', 2, block=True)
  panel.refresh()
  item = controller._long_personality_setting
  assert item.action_item.selected_button == 2
  assert resolve(panel._rows[item][0].value) == tr('Relaxed')
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', False)
  controller._set_longitudinal_personality(0)
  assert ui_state.params.get('LongitudinalPersonality') == 2


@pytest.mark.parametrize('change', ['cancel', 'engaged', 'unknown', 'unsupported'])
def test_alpha_long_confirmation_rechecks_state_and_keeps_cancelled_params(monkeypatch, change):
  from types import SimpleNamespace
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(alphaLongitudinalAvailable=True))
  panel = make_panel('developer')
  gui_app.push_widget(panel)
  controller = panel.controller
  panel._toggle(controller._alpha_long_toggle)
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  assert not controller._alpha_long_toggle.action_item.get_state()
  if change == 'engaged':
    monkeypatch.setattr(ui_state, 'sm', {'selfdriveState': SimpleNamespace(enabled=True),
                                       'selfdriveStateSP': SimpleNamespace(mads=SimpleNamespace(enabled=False))})
    monkeypatch.setattr(ui_state, 'started', True)
  elif change == 'unknown':
    monkeypatch.setattr(ui_state, 'CP', None)
  elif change == 'unsupported':
    monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(alphaLongitudinalAvailable=False))
  dialog._cancel_button_callback() if change == 'cancel' else dialog._confirm_button_callback()
  assert not ui_state.params.get_bool('AlphaLongitudinalEnabled')
  assert not ui_state.params.get_bool('OnroadCycleRequested')


def test_alpha_long_confirm_saves_and_maneuver_gating_recovers_when_vehicle_known(monkeypatch):
  panel = make_panel('developer')
  gui_app.push_widget(panel)
  controller = panel.controller
  assert not controller._lat_maneuver_toggle.action_item.enabled
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(alphaLongitudinalAvailable=True))
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
  panel.refresh()
  assert controller._lat_maneuver_toggle.action_item.enabled
  panel._toggle(controller._alpha_long_toggle)
  gui_app.get_active_widget()._confirm_button_callback()
  assert ui_state.params.get_bool('AlphaLongitudinalEnabled')
  assert ui_state.params.get_bool('OnroadCycleRequested')
  controller._on_long_maneuver_mode(True)
  assert ui_state.params.get_bool('LongitudinalManeuverMode')
  controller._on_lat_maneuver_mode(True)
  assert ui_state.params.get_bool('LateralManeuverMode')
  assert not ui_state.params.get_bool('LongitudinalManeuverMode')
  controller._on_joystick_debug_mode(True)
  assert ui_state.params.get_bool('JoystickDebugMode')
  assert not ui_state.params.get_bool('LateralManeuverMode')
  monkeypatch.setattr(ui_state, 'started', True)
  controller._on_long_maneuver_mode(True)
  controller._on_lat_maneuver_mode(True)
  assert not ui_state.params.get_bool('LongitudinalManeuverMode')
  assert not ui_state.params.get_bool('LateralManeuverMode')


def test_force_onroad_stale_callback_does_not_change_driving_state(monkeypatch):
  panel = make_panel('developer')
  gui_app.push_widget(panel)
  monkeypatch.setattr(ui_state, 'started', True)
  panel.controller._on_force_onroad(True)
  assert not ui_state.params.get_bool('ForceOnroad')
  assert not panel.controller._force_onroad_toggle.action_item.enabled


@pytest.fixture
def log_panel(monkeypatch, tmp_path):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import developer
  panel = make_panel('developer')
  controller = panel.controller
  monkeypatch.setattr(controller, '_refresh_usb_state', lambda: None)
  controller.swaglog_root = str(tmp_path)
  controller.error_log_path = str(tmp_path / 'error.log')
  jobs = []
  monkeypatch.setattr(developer.threading, 'Thread', lambda target, daemon, args=(): SimpleNamespace(start=lambda: jobs.append(lambda: target(*args))))
  gui_app.push_widget(panel)
  return panel, jobs, tmp_path


def test_log_scan_and_delete_run_in_background_with_ui_confirmation(log_panel):
  panel, jobs, root = log_panel
  (root / 'swaglog.1').write_text('first')
  controller = panel.controller
  controller._on_clear_system_logs_clicked()
  assert controller._log_running and len(jobs) == 1
  draw(panel)
  assert gui_app.get_active_widget() is panel
  assert not controller.system_logs_item.action_item.left_button.enabled
  jobs.pop(0)()
  assert gui_app.get_active_widget() is panel
  panel.refresh()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  (root / 'swaglog.new').write_text('after confirmation')
  dialog._confirm_button_callback()
  assert controller._log_running and len(jobs) == 1
  assert (root / 'swaglog.1').exists()
  jobs.pop(0)()
  assert gui_app.get_active_widget() is panel
  panel.refresh()
  assert not (root / 'swaglog.1').exists()
  assert (root / 'swaglog.new').read_text() == 'after confirmation'
  assert tr('Cleared {deleted}/{total} system log files.').format(deleted=1, total=1) in controller._log_details()
  gui_app.get_active_widget()._ok_button._click_callback()
  panel.refresh()
  assert controller.system_logs_item.action_item.left_button.enabled
  assert controller._log_status == 'Log cleanup completed'


@pytest.mark.parametrize('change', ['cancel', 'onroad'])
def test_log_confirmation_cancel_and_state_change_preserve_files(log_panel, monkeypatch, change):
  panel, jobs, root = log_panel
  (root / 'swaglog.1').write_text('kept')
  controller = panel.controller
  controller._on_clear_system_logs_clicked()
  jobs.pop(0)()
  panel.refresh()
  dialog = gui_app.get_active_widget()
  if change == 'cancel':
    dialog._cancel_button_callback()
  else:
    monkeypatch.setattr(ui_state, 'started', True)
    dialog._confirm_button_callback()
  assert not jobs
  assert (root / 'swaglog.1').read_text() == 'kept'
  assert controller._pending_log_snapshot is None
  assert controller._log_status == 'Log cleanup cancelled'


def test_log_scan_failure_unlocks_controls_and_language_refreshes_status(log_panel):
  panel, jobs, root = log_panel
  panel.controller.swaglog_root = str(root / 'missing')
  panel.controller._on_clear_system_logs_clicked()
  jobs.pop(0)()
  panel.refresh()
  assert not panel.controller._log_running
  assert tr('Error: {error}').split('{error}')[0] in panel.controller._log_details()
  assert panel.controller._log_status == 'Unable to scan system logs'
  gui_app.get_active_widget()._ok_button._click_callback()
  panel.refresh()
  row = panel._rows[panel.controller._log_status_item][0]
  assert resolve(row.value) == tr('Unable to scan system logs')
  multilang._language = 'en'
  multilang.setup()
  panel.refresh()
  assert resolve(row.value) == 'Unable to scan system logs'
  assert panel.controller.system_logs_item.action_item.left_button.enabled


def test_error_log_view_preserves_literal_text_and_changed_log_cannot_be_deleted(log_panel):
  panel, _, root = log_panel
  file = root / 'error.log'
  file.write_text('ValueError: <bad> & data\nsecond line')
  controller = panel.controller
  controller._on_error_log_clicked()
  modal = gui_app.get_active_widget()
  assert '&lt;bad&gt; &amp; data<br>second line' in modal._content.raw_text
  modal._ok_button._click_callback()
  confirm = gui_app.get_active_widget()
  assert isinstance(confirm, ConfirmDialog)
  file.write_text('new error after viewing')
  confirm._confirm_button_callback()
  assert file.read_text() == 'new error after viewing'
  assert gui_app.get_active_widget()._content.raw_text == tr('The error log changed. Open it again before deleting.')


def test_error_log_delete_failure_and_stale_onroad_confirmation_keep_file(log_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import developer
  panel, _, root = log_panel
  file = root / 'error.log'
  file.write_text('kept')
  controller = panel.controller
  controller._on_error_log_clicked()
  gui_app.get_active_widget()._ok_button._click_callback()
  monkeypatch.setattr(ui_state, 'started', True)
  gui_app.get_active_widget()._confirm_button_callback()
  assert file.exists()
  monkeypatch.setattr(ui_state, 'started', False)
  controller._on_error_log_clicked()
  gui_app.get_active_widget()._ok_button._click_callback()
  def remove(path):
    raise PermissionError('read-only')
  with monkeypatch.context() as change:
    change.setattr(developer.os, 'remove', remove)
    gui_app.get_active_widget()._confirm_button_callback()
  assert file.exists()
  assert 'read-only' in gui_app.get_active_widget()._content.raw_text


def test_quickboot_file_state_handles_absent_file_and_stale_prerequisites(log_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import developer
  panel, _, root = log_panel
  file = root / 'prebuilt'
  monkeypatch.setattr(developer, 'PREBUILT_PATH', str(file))
  ui_state.params.put_bool('DisableUpdates', True, block=True)
  for key in ('IsReleaseSpBranch', 'IsTestedBranch', 'IsDevelopmentBranch'):
    ui_state.params.put_bool(key, False, block=True)
  controller = panel.controller
  controller._on_prebuilt_toggled(False)
  assert not file.exists() and not ui_state.params.get_bool('QuickBootToggle')
  controller._on_prebuilt_toggled(True)
  assert file.exists() and ui_state.params.get_bool('QuickBootToggle')
  ui_state.params.put_bool('DisableUpdates', False, block=True)
  controller._on_prebuilt_toggled(False)
  assert file.exists() and ui_state.params.get_bool('QuickBootToggle')
  ui_state.params.put_bool('DisableUpdates', True, block=True)
  controller._on_prebuilt_toggled(False)
  assert not file.exists() and not ui_state.params.get_bool('QuickBootToggle')


def test_log_confirmation_removed_by_timeout_releases_controls(log_panel):
  panel, jobs, root = log_panel
  (root / 'swaglog.1').write_text('kept')
  controller = panel.controller
  controller._on_clear_system_logs_clicked()
  jobs.pop(0)()
  panel.refresh()
  assert isinstance(gui_app.get_active_widget(), ConfirmDialog)
  gui_app.pop_widget()
  panel.refresh()
  assert controller._pending_log_snapshot is None
  assert controller.system_logs_item.action_item.left_button.enabled
  assert (root / 'swaglog.1').exists()
  controller._on_clear_system_logs_clicked()
  assert len(jobs) == 1


def test_log_cleanup_partial_failure_reports_kept_files_and_allows_retry(log_panel, monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import log_operations
  panel, jobs, root = log_panel
  (root / 'swaglog.1').write_text('deleted')
  (root / 'swaglog.2').write_text('kept')
  controller = panel.controller
  controller._on_clear_system_logs_clicked()
  jobs.pop(0)()
  panel.refresh()
  gui_app.get_active_widget()._confirm_button_callback()
  original = log_operations.os.unlink
  def unlink(name, **kwargs):
    if name == 'swaglog.2':
      raise PermissionError('read-only')
    original(name, **kwargs)
  with monkeypatch.context() as change:
    change.setattr(log_operations.os, 'unlink', unlink)
    jobs.pop(0)()
  panel.refresh()
  assert controller._log_status == 'Log cleanup incomplete'
  assert 'read-only' in controller._log_details()
  assert 'swaglog.2' in controller._log_details()
  assert not (root / 'swaglog.1').exists() and (root / 'swaglog.2').exists()
  gui_app.get_active_widget()._ok_button._click_callback()
  panel.refresh()
  controller._on_clear_system_logs_clicked()
  jobs.pop(0)()
  panel.refresh()
  gui_app.get_active_widget()._confirm_button_callback()
  jobs.pop(0)()
  panel.refresh()
  assert controller._log_status == 'Log cleanup completed'
  assert not (root / 'swaglog.2').exists()


@pytest.mark.parametrize('status', ['completed', 'failed', 'timeout', 'error'])
def test_log_format_result_translates_on_ui_thread_and_preserves_literal_output(log_panel, monkeypatch, status):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import developer
  panel, jobs, _ = log_panel
  controller = panel.controller
  def run(*args, **kwargs):
    if status == 'timeout':
      raise developer.subprocess.TimeoutExpired('format', 120)
    if status == 'error':
      raise OSError('<read-only>')
    return SimpleNamespace(returncode=0 if status == 'completed' else 2, stdout='line <input> & output', stderr='<failed>')
  monkeypatch.setattr(developer.subprocess, 'run', run)
  controller._on_format_system_logs_clicked()
  assert controller._format_running and len(jobs) == 1
  jobs.pop(0)()
  assert gui_app.get_active_widget() is panel
  panel.refresh()
  modal = gui_app.get_active_widget()
  draw(modal)
  assert not controller._format_running
  message = modal._content.raw_text
  assert '<input>' not in message and '<read-only>' not in message
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(modal)
  assert modal._content.raw_text != message
  if status == 'completed':
    assert 'Format completed successfully.' in modal._content.raw_text
    assert '&lt;input&gt; &amp; output' in modal._content.raw_text
  elif status == 'failed':
    assert 'exit code 2' in modal._content.raw_text and '&lt;failed&gt;' in modal._content.raw_text
  elif status == 'timeout':
    assert '120 seconds' in modal._content.raw_text
  else:
    assert '&lt;read-only&gt;' in modal._content.raw_text
  modal._ok_button._click_callback()
  panel.refresh()
  assert controller.system_logs_item.action_item.right_button.enabled


def test_slow_log_scan_keeps_rendering_responsive(monkeypatch, tmp_path):
  import threading
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings import developer
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.log_operations import scan_logs
  panel = make_panel('developer')
  controller = panel.controller
  monkeypatch.setattr(controller, '_refresh_usb_state', lambda: None)
  controller.swaglog_root = str(tmp_path)
  (tmp_path / 'swaglog.1').write_text('kept')
  entered, release = threading.Event(), threading.Event()
  def slow_scan(root):
    entered.set()
    assert release.wait(2)
    return scan_logs(root)
  monkeypatch.setattr(developer, 'scan_logs', slow_scan)
  gui_app.push_widget(panel)
  controller._on_clear_system_logs_clicked()
  try:
    assert entered.wait(1)
    draw(panel)
    assert gui_app.get_active_widget() is panel
    assert controller._log_running
    assert not controller.system_logs_item.action_item.left_button.enabled
  finally:
    release.set()
  deadline = time.monotonic() + 2
  while controller._log_events.empty() and time.monotonic() < deadline:
    time.sleep(0.01)
  assert not controller._log_events.empty()
  panel.refresh()
  gui_app.get_active_widget()._cancel_button_callback()
  assert (tmp_path / 'swaglog.1').exists()


@pytest.mark.parametrize('stop_before_release', [False, True])
def test_batched_swipe_release_cannot_click_after_scroll_returns_to_steady(monkeypatch, stop_before_release):
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  from openpilot.system.ui.lib.scroll_panel2 import ScrollState
  panel = make_panel('steering')
  gui_app.push_widget(panel)
  draw(panel)
  scroll = panel._list._scroller.scroll_panel
  positions = (370, 300, 230, 230, 230, 230) if stop_before_release else (370, 300, 230, 160)
  events = [MouseEvent(MousePos(x, 200), 0, index == 0, index == len(positions) - 1, index < len(positions) - 1, index * 0.1)
            for index, x in enumerate(positions)]
  monkeypatch.setattr(gui_app, '_mouse_events', events)
  before = ui_state.params.get_bool('Mads')
  draw(panel)
  if stop_before_release:
    assert scroll.state == ScrollState.STEADY
  assert not scroll.is_touch_valid()
  assert gui_app.get_active_widget() is panel
  assert ui_state.params.get_bool('Mads') == before
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  draw(panel)
  assert scroll.is_touch_valid()


@pytest.mark.parametrize('screen_off', [False, True])
@pytest.mark.parametrize('separate_release', [False, True])
def test_input_callback_wakes_before_real_setting_widget_receives_touch(monkeypatch, screen_off, separate_release):
  from openpilot.selfdrive.ui import ui_state as state_module
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  panel = make_panel('visuals')
  gui_app.push_widget(panel)
  item = panel._source_items[0]
  row = panel._rows[item][0]
  draw(panel)
  panel._list.focus_item(row)
  draw(panel)
  switch = row._switch_touch_rect()
  pos = MousePos(switch.x + switch.width / 2, switch.y + switch.height / 2)
  touch = [MouseEvent(pos, 0, True, False, True, 0), MouseEvent(pos, 0, False, True, False, 0.1)]
  device = state_module.Device()
  device._awake = not screen_off
  monkeypatch.setattr(ui_state, 'started', True)
  monkeypatch.setattr(ui_state, 'onroad_brightness', 2)
  monkeypatch.setattr(ui_state, 'onroad_brightness_timer', 0)
  monkeypatch.setattr(ui_state, 'onroad_brightness_timer_param', 15)
  monkeypatch.setattr(state_module.HARDWARE, 'set_display_power', lambda _: None)
  monkeypatch.setattr(gui_app, 'sunnypilot_ui', lambda: True)
  monkeypatch.setattr(gui_app, '_should_render', not screen_off)
  monkeypatch.setattr(gui_app, '_input_callbacks', [])
  monkeypatch.setattr(gui_app, '_nav_stack_ticks', [])
  monkeypatch.setattr(gui_app, '_window_close_requested', False)
  monkeypatch.setattr(gui_app._mouse, '_handle_mouse_event', lambda: None)
  batches = [[touch[0]], [touch[0]._replace(left_pressed=False)], [touch[1]], touch.copy()] if separate_release else [touch.copy(), touch.copy()]
  monkeypatch.setattr(gui_app._mouse, 'get_events', lambda: batches.pop(0))
  gui_app.add_input_callback(device.handle_mouse_events)
  param = item.action_item.toggle.param_key
  before = ui_state.params.get_bool(param)
  frames = gui_app.render()
  try:
    assert next(frames)[0]
    assert gui_app.mouse_events == []
    assert not gui_app.last_mouse_event.left_down
    assert not gui_app.last_mouse_event.left_released
    assert ui_state.params.get_bool(param) == before
    assert device.awake
    if separate_release:
      for _ in range(2):
        assert next(frames)[0]
        assert gui_app.mouse_events == []
        assert ui_state.params.get_bool(param) == before
    assert next(frames)[0]
    assert gui_app.mouse_events == touch
    wait_param(param, not before)
  finally:
    gui_app._window_close_requested = True
    next(frames, None)


@pytest.mark.parametrize('standstill', [False, True])
def test_c4_interactivity_timeout_keeps_settings_at_standstill(monkeypatch, standstill):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui import ui_state as state_module
  from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
  panel = make_panel('display')
  gui_app.push_widget(panel)
  monkeypatch.setattr(ui_state, 'started', True)
  monkeypatch.setattr(ui_state, 'ignition', True)
  monkeypatch.setattr(ui_state, 'custom_interactive_timeout', 90)
  monkeypatch.setattr(ui_state, 'sm', {'carState': SimpleNamespace(standstill=standstill)})
  now = [100.0]
  monkeypatch.setattr(state_module.time, 'monotonic', lambda: now[0])
  monkeypatch.setattr(gui_app, 'widget_in_stack', lambda _: False)
  returns = []
  monkeypatch.setattr(gui_app, 'pop_widgets_to', lambda *args, **kwargs: returns.append(args[0]))
  main = SimpleNamespace(_onboarding_window=object(), _onroad_layout=object(), _scroll_to=lambda _: None)
  device = state_module.Device()
  monkeypatch.setattr(device, '_start_brightness_thread', lambda: None)
  monkeypatch.setattr(device, '_update_brightness', lambda: None)
  device.add_interactive_timeout_callback(lambda: MiciMainLayout._on_interactive_timeout(main))
  device.update()
  now[0] = 191
  device.update()
  assert returns == ([] if standstill else [main])


def test_c4_saved_display_parameters_reach_running_state_and_delay_controls(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.ui_state import UIStateSP, DeviceSP, OnroadTimerStatus
  panel = make_panel('display')
  gui_app.push_widget(panel)
  monkeypatch.setattr(ui_state, '_enforce_constraints', lambda: None)
  monkeypatch.setattr(ui_state, '_sp_initialized', False)
  monkeypatch.setattr(ui_state, 'onroad_brightness', 0)
  monkeypatch.setattr(ui_state, 'onroad_brightness_timer_param', 15)
  monkeypatch.setattr(ui_state, 'onroad_brightness_timer', 0)
  monkeypatch.setattr(ui_state, 'started', True)
  brightness = panel.controller._onroad_brightness
  panel._open_number(brightness, lambda: brightness.title, lambda: brightness.description)
  gui_app.get_active_widget()._list._scroller.items[12].callback()
  UIStateSP.update_params(ui_state)
  assert ui_state.onroad_brightness == 12
  panel.refresh()
  delay = panel.controller._onroad_brightness_timer
  assert delay.action_item.enabled
  panel._open_number(delay, lambda: delay.title, lambda: delay.description)
  gui_app.get_active_widget()._list._scroller.items[5].callback()
  UIStateSP.update_params(ui_state)
  assert ui_state.onroad_brightness_timer == 30 * gui_app.target_fps
  ui_state.onroad_brightness_timer = 0
  assert DeviceSP.set_onroad_brightness(ui_state, True, 65) == 50
  ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.PAUSE)
  panel._open_number(brightness, lambda: brightness.title, lambda: brightness.description)
  gui_app.get_active_widget()._list._scroller.items[0].callback()
  UIStateSP.update_params(ui_state)
  panel.refresh()
  assert not delay.action_item.enabled
  assert ui_state.onroad_brightness_timer == -1
  assert DeviceSP.set_onroad_brightness(ui_state, True, 65) == 65


def test_c4_settings_navigation_pauses_brightness_until_settings_exit(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP
  from openpilot.selfdrive.ui.sunnypilot.ui_state import DeviceSP, UIStateSP
  monkeypatch.setattr(ui_state, 'started', True)
  monkeypatch.setattr(ui_state, 'onroad_brightness', 2)
  monkeypatch.setattr(ui_state, 'onroad_brightness_timer_param', 5)
  monkeypatch.setattr(ui_state, 'onroad_brightness_timer', 0)
  monkeypatch.setattr(ui_state, '_enforce_constraints', lambda: None)
  monkeypatch.setattr(ui_state, '_sp_initialized', False)
  ui_state.params.put('OnroadScreenOffBrightness', 2, block=True)
  ui_state.params.put('OnroadScreenOffTimer', 5, block=True)
  settings = SettingsLayoutSP()
  gui_app.push_widget(settings)
  assert ui_state.onroad_brightness_timer == -1
  assert DeviceSP.set_onroad_brightness(ui_state, True, 65) == 65
  draw(settings)
  settings.focus_category('display')
  settings.buttons[settings.menu_keys.index('display')]._click_callback()
  panel = gui_app.get_active_widget()
  item = panel.controller._onroad_brightness
  panel._open_number(item, lambda: item.title, lambda: item.description)
  for _ in range(10):
    ui_state.update_onroad_brightness(False)
  UIStateSP.update_params(ui_state)
  assert ui_state.onroad_brightness_timer == -1
  gui_app.pop_widgets_to(settings, instant=True)
  assert gui_app.get_active_widget() is settings
  assert ui_state.onroad_brightness_timer == -1
  gui_app.pop_widget()
  assert ui_state.onroad_brightness_timer == 5 * gui_app.target_fps


@pytest.fixture
def pairing_services(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.widgets import pairing_dialog as comma
  from openpilot.selfdrive.ui.sunnypilot.mici.widgets import sunnylink_pairing_dialog as sunnylink
  tokens = {'comma': 'example-pair-token', 'sunnylink': 'example-sunnylink-token'}
  calls, unloaded = [], []
  now, paired = [100.0], [False]

  def api(service, identity):
    def get_token(*args):
      calls.append((service, identity, args))
      result = tokens[service]
      if isinstance(result, Exception):
        raise result
      return result
    return SimpleNamespace(get_token=get_token)

  monkeypatch.setattr(comma, 'Api', lambda identity: api('comma', identity))
  monkeypatch.setattr(sunnylink, 'SunnylinkApi', lambda identity: api('sunnylink', identity))
  monkeypatch.setattr(comma.time, 'monotonic', lambda: now[0])
  monkeypatch.setattr(ui_state, 'prime_state', SimpleNamespace(is_paired=lambda: paired[0]))
  unload = rl.unload_texture
  def unload_texture(texture):
    unloaded.append(texture.id)
    unload(texture)
  monkeypatch.setattr(rl, 'unload_texture', unload_texture)
  ui_state.params.put('DongleId', 'example-device', block=True)
  ui_state.params.put('SunnylinkDongleId', 'example-sunnylink-device', block=True)
  return SimpleNamespace(comma=comma, sunnylink=sunnylink, tokens=tokens, calls=calls, unloaded=unloaded, now=now, paired=paired)


def open_pairing(services, service):
  dialog = services.comma.PairingDialog() if service == 'comma' else services.sunnylink.SunnylinkPairingDialog(True)
  gui_app.push_widget(dialog)
  for _ in range(40):
    draw(dialog)
  return dialog


@pytest.mark.parametrize('service', ['comma', 'sunnylink'])
@pytest.mark.parametrize('failure', [RuntimeError('signing failed'), None, '', '   ', b'not-a-token'])
def test_pairing_token_failure_shows_error_and_can_retry(pairing_services, service, failure):
  services = pairing_services
  services.tokens[service] = failure
  dialog = open_pairing(services, service)
  assert dialog._qr_texture is None and dialog._qr_error
  assert dialog._retry_button.is_visible
  assert dialog._instruction_label._cached_text == tr('Unable to create QR code')
  assert len(services.calls) == 1
  draw(dialog)
  assert len(services.calls) == 1
  services.tokens[service] = 'new-example-token'
  dialog._retry_button._click_callback()
  draw(dialog)
  assert len(services.calls) == 2
  assert dialog._qr_texture.id > 0 and not dialog._qr_error
  assert not dialog._retry_button.is_visible
  assert dialog._instruction_label._cached_text == tr('Scan with your phone')


@pytest.mark.parametrize('service,param', [('comma', 'DongleId'), ('sunnylink', 'SunnylinkDongleId')])
@pytest.mark.parametrize('identity', [None, '', 'UnregisteredDevice'])
def test_pairing_registration_error_recovers_when_device_registers(pairing_services, service, param, identity):
  if identity is None:
    ui_state.params.remove(param)
  else:
    ui_state.params.put(param, identity, block=True)
  dialog = open_pairing(pairing_services, service)
  assert dialog._qr_texture is None and dialog._qr_error
  assert pairing_services.calls == []
  ui_state.params.put(param, 'new-registered-device', block=True)
  draw(dialog)
  assert dialog._qr_texture.id > 0 and not dialog._qr_error
  assert pairing_services.calls[0][1] == 'new-registered-device'


@pytest.mark.parametrize('service,param', [('comma', 'DongleId'), ('sunnylink', 'SunnylinkDongleId')])
def test_pairing_refreshes_at_deadline_and_when_identity_changes(pairing_services, service, param):
  services = pairing_services
  dialog = open_pairing(services, service)
  first_texture = dialog._qr_texture.id
  services.now[0] += 299
  draw(dialog)
  assert len(services.calls) == 1
  services.now[0] += 1
  draw(dialog)
  assert len(services.calls) == 2
  assert services.unloaded.count(first_texture) == 1
  ui_state.params.put(param, 'replacement-device', block=True)
  draw(dialog)
  assert len(services.calls) == 3 and services.calls[-1][1] == 'replacement-device'


def test_pairing_failed_refresh_removes_old_qr_and_hidden_dialog_does_not_generate(pairing_services):
  services = pairing_services
  dialog = open_pairing(services, 'comma')
  old_texture = dialog._qr_texture.id
  services.tokens['comma'] = RuntimeError('signing failed')
  services.now[0] += 300
  draw(dialog)
  assert dialog._qr_texture is None and dialog._qr_error
  assert services.unloaded.count(old_texture) == 1
  gui_app.pop_widget()
  services.now[0] += 300
  draw(dialog)
  dialog._retry_qr()
  assert len(services.calls) == 2


def test_pairing_retry_touch_recovers_without_dismissing_or_changing_parameters(pairing_services, monkeypatch):
  from openpilot.system.ui.lib.application import MouseEvent, MousePos
  services = pairing_services
  services.tokens['comma'] = None
  dialog = open_pairing(services, 'comma')
  rect = dialog._retry_button.rect
  position = MousePos(rect.x + rect.width / 2, rect.y + rect.height / 2)
  services.tokens['comma'] = 'recovered-token'
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(position, 0, True, False, True, 0),
                                                MouseEvent(position, 0, False, True, False, 0.1)])
  draw(dialog)
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  draw(dialog)
  assert not dialog._qr_error and dialog._qr_texture.id > 0
  assert gui_app.get_active_widget() is dialog and not dialog.is_dismissing
  assert ui_state.params.get('DongleId') == 'example-device'
  assert services.calls[-1] == ('comma', 'example-device', ({'pair': True},))


def test_pairing_texture_allocation_failure_recovers_on_retry(pairing_services, monkeypatch):
  load = rl.load_texture_from_image
  monkeypatch.setattr(rl, 'load_texture_from_image', lambda image: rl.Texture())
  dialog = open_pairing(pairing_services, 'comma')
  assert dialog._qr_texture is None and dialog._qr_error
  monkeypatch.setattr(rl, 'load_texture_from_image', load)
  dialog._retry_qr()
  draw(dialog)
  assert dialog._qr_texture.id > 0 and not dialog._qr_error


@pytest.mark.parametrize('service', ['comma', 'sunnylink'])
def test_pairing_exit_releases_qr_once_and_same_dialog_reopens(pairing_services, service):
  services = pairing_services
  dialog = open_pairing(services, service)
  texture_id = dialog._qr_texture.id
  gui_app.pop_widget()
  dialog.close()
  assert dialog._qr_texture is None
  assert services.unloaded.count(texture_id) == 1
  gui_app.push_widget(dialog)
  draw(dialog)
  assert dialog._qr_texture.id > 0
  assert len(services.calls) == 2


@pytest.mark.parametrize('service', ['comma', 'sunnylink'])
@pytest.mark.parametrize('long_token', [False, True])
def test_rendered_pairing_qr_decodes_to_expected_service_url(pairing_services, service, long_token):
  import base64
  from urllib.parse import parse_qs, urlsplit
  import cv2
  import numpy as np
  services = pairing_services
  if long_token:
    services.tokens[service] = 'header.' + 'payload' * 32 + '.' + 'signature' * 38
  open_pairing(services, service)
  image = rl.load_image_from_screen()
  try:
    rl.image_format(image, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
    rgba = np.frombuffer(rl.ffi.buffer(image.data, image.width * image.height * 4), dtype=np.uint8)
    rgba = rgba.reshape(image.height, image.width, 4)
    qr = cv2.cvtColor(rgba[20:240, 8:228], cv2.COLOR_RGBA2GRAY)
    # Repeat the original display pixels for the detector without smoothing or regenerating the code.
    qr = cv2.resize(qr, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    url, _, _ = cv2.QRCodeDetectorAruco().detectAndDecode(qr)
  finally:
    rl.unload_image(image)
  assert url
  query = parse_qs(urlsplit(url).query)
  if service == 'comma':
    assert urlsplit(url).netloc == 'connect.comma.ai'
    assert query['pair'] == [services.tokens[service]]
  else:
    assert urlsplit(url).netloc == urlsplit(services.sunnylink.API_HOST).netloc
    assert base64.b64decode(query['state'][0]).decode() == f'1|example-sunnylink-device|{services.tokens[service]}'


def test_sponsorship_qr_is_distinct_from_account_pairing_and_needs_no_token(pairing_services):
  services = pairing_services
  services.tokens['sunnylink'] = RuntimeError('signing failed')
  ui_state.params.remove('SunnylinkDongleId')
  dialog = services.sunnylink.SunnylinkPairingDialog(False)
  gui_app.push_widget(dialog)
  draw(dialog)
  assert dialog._get_pairing_url() == 'https://github.com/sponsors/sunnyhaibin'
  assert dialog._qr_texture.id > 0 and not dialog._qr_error
  assert services.calls == []


def test_pairing_error_labels_update_in_place_with_language(pairing_services):
  services = pairing_services
  services.tokens['comma'] = None
  dialog = open_pairing(services, 'comma')
  assert dialog._pair_label._cached_text == tr('PAIR') + '\ncomma connect'
  multilang._language = 'en'
  multilang.setup()
  gui_app.on_language_changed('en')
  draw(dialog)
  assert dialog._pair_label._cached_text == 'PAIR\ncomma connect'
  assert dialog._instruction_label._cached_text == 'Unable to create QR code'


def test_pairing_status_change_only_dismisses_own_active_dialog(pairing_services):
  services = pairing_services
  dialog = open_pairing(services, 'comma')
  other = CompactPage('other')
  gui_app.push_widget(other)
  services.paired[0] = True
  draw(dialog)
  assert gui_app.get_active_widget() is other
  assert not dialog.is_dismissing
  gui_app.pop_widget()
  draw(dialog)
  assert dialog.is_dismissing
  for _ in range(60):
    draw(dialog)
  assert not gui_app.widget_in_stack(dialog)
  assert dialog._qr_texture is None


@pytest.mark.parametrize('condition', ['clock', 'registration', 'paired', 'ready'])
def test_device_pairing_entry_rechecks_registration_clock_and_pairing(pairing_services, monkeypatch, condition):
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts import settings_controllers as controllers
  monkeypatch.setattr(controllers, 'system_time_valid', lambda: condition != 'clock')
  if condition == 'registration':
    ui_state.params.remove('DongleId')
  pairing_services.paired[0] = condition == 'paired'
  panel = make_panel('device')
  gui_app.push_widget(panel)
  panel.controller._open_pairing()
  active = gui_app.get_active_widget()
  if condition == 'paired':
    assert active is panel
  elif condition == 'ready':
    assert isinstance(active, pairing_services.comma.PairingDialog)
  else:
    assert isinstance(active, ConfirmDialog)


def test_review_training_camera_and_timeout_callbacks_exist_only_while_open(camera_preview, monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTrainingGuide
  _, device, _ = camera_preview
  monkeypatch.setattr(ui_state, '_offroad_transition_callbacks', [])
  for _ in range(3):
    guide = ReviewTrainingGuide(completed_callback=lambda: None)
    assert device._interactive_timeout_callbacks == []
    gui_app.push_widget(guide)
    assert device._override_interactive_timeout == 300
    assert ui_state._offroad_transition_callbacks == [guide._on_vehicle_state_changed]
    pre, tutorial = guide._steps[1:3]
    gui_app.push_widget(pre)
    assert ui_state.params.get_bool('IsDriverViewEnabled')
    gui_app.push_widget(tutorial)
    view = tutorial._dialog._camera_view
    assert device._interactive_timeout_callbacks == [tutorial._on_timeout]
    gui_app.pop_widget()
    assert not ui_state.params.get_bool('IsDriverViewEnabled')
    assert device._interactive_timeout_callbacks == []
    assert device._override_interactive_timeout == 300
    assert tutorial._dialog._camera_view is None and view.closed == 1
    gui_app.pop_widget()
    gui_app.pop_widget()
    assert ui_state._offroad_transition_callbacks == []
    assert device._override_interactive_timeout is None


def test_closed_training_timeout_cannot_disable_new_driver_preview(camera_preview):
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTrainingGuide
  camera, _, _ = camera_preview
  guide = ReviewTrainingGuide(completed_callback=lambda: None)
  gui_app.push_widget(guide)
  tutorial = guide._steps[2]
  gui_app.push_widget(tutorial)
  gui_app.pop_widget()
  gui_app.pop_widget()
  preview = camera.DriverCameraDialog()
  gui_app.push_widget(preview)
  tutorial._on_timeout()
  assert ui_state.params.get_bool('IsDriverViewEnabled')
  assert gui_app.get_active_widget() is preview


def test_training_reopen_requires_new_camera_check_and_resets_completion(camera_preview):
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTrainingGuide
  guide = ReviewTrainingGuide(completed_callback=lambda: None)
  gui_app.push_widget(guide)
  tutorial = guide._steps[2]
  gui_app.push_widget(tutorial)
  first_view = tutorial._dialog._camera_view
  tutorial._progress.x = 1
  tutorial._good_button.set_enabled(True)
  gui_app.pop_widget()
  draw(tutorial)
  gui_app.push_widget(tutorial)
  assert tutorial._dialog._camera_view is not first_view
  assert tutorial._progress.x == 0 and not tutorial._good_button.enabled
  assert ui_state.params.get_bool('IsDriverViewEnabled')


def test_review_training_vehicle_start_closes_all_steps_and_keeps_callback_dispatch(camera_preview, monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTrainingGuide
  _, device, _ = camera_preview
  monkeypatch.setattr(ui_state, '_offroad_transition_callbacks', [])
  monkeypatch.setattr(ui_state, '_started_prev', False)
  monkeypatch.setattr(ui_state, '_engaged_prev', False)
  for attribute in ('started_frame', 'started_time', 'status'):
    monkeypatch.setattr(ui_state, attribute, getattr(ui_state, attribute))
  monkeypatch.setattr(type(ui_state), 'engaged', property(lambda self: False))
  panel = make_panel('device')
  gui_app.push_widget(panel)
  # Isolate the review callback from the long-lived settings controller callbacks.
  ui_state._offroad_transition_callbacks.clear()
  guide = ReviewTrainingGuide(completed_callback=lambda: None)
  gui_app.push_widget(guide)
  for step in guide._steps[1:3]:
    gui_app.push_widget(step)
  gui_app.push_widget(guide._steps[2]._bad_face_page)
  invoked = []
  ui_state.add_offroad_transition_callback(lambda: invoked.append('after-training'))
  monkeypatch.setattr(ui_state, 'started', True)
  monkeypatch.setattr(ui_state, 'sm', SimpleNamespace(updated={'selfdriveState': False}, frame=2))
  ui_state._update_status()
  assert gui_app.get_active_widget() is panel
  assert not ui_state.params.get_bool('IsDriverViewEnabled')
  assert device._override_interactive_timeout is None
  assert device._interactive_timeout_callbacks == []
  assert guide._on_vehicle_state_changed not in ui_state._offroad_transition_callbacks
  assert invoked == ['after-training']


def test_training_parent_removed_first_still_cleans_camera_without_restoring_old_timeout(camera_preview):
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTrainingGuide
  _, device, _ = camera_preview
  guide = ReviewTrainingGuide(completed_callback=lambda: None)
  gui_app.push_widget(guide)
  tutorial = guide._steps[2]
  gui_app.push_widget(tutorial)
  view = tutorial._dialog._camera_view
  gui_app.pop_widget(len(gui_app._nav_stack) - 2)
  assert not tutorial._dm_open
  assert view.closed == 1 and tutorial._dialog._camera_view is None
  assert device._interactive_timeout_callbacks == []
  assert device._override_interactive_timeout is None
  draw(tutorial)
  gui_app.pop_widget()
  assert device._override_interactive_timeout is None


def test_training_retains_onboarding_timeout_when_guide_returns_to_its_owner(camera_preview):
  from openpilot.selfdrive.ui.mici.layouts.onboarding import TrainingGuide
  _, device, _ = camera_preview
  owner = CompactPage('onboarding')
  gui_app.push_widget(owner)
  device.set_override_interactive_timeout(300)
  guide = TrainingGuide(completed_callback=lambda: None, timeout_owner=owner)
  gui_app.push_widget(guide)
  gui_app.push_widget(guide._steps[2])
  gui_app.pop_widgets_to(owner, instant=True)
  assert gui_app.get_active_widget() is owner
  assert not ui_state.params.get_bool('IsDriverViewEnabled')
  assert device._interactive_timeout_callbacks == []
  assert device._override_interactive_timeout == 300


def test_training_pre_camera_back_disables_preview_and_review_terms_has_no_destructive_actions(camera_preview):
  from openpilot.selfdrive.ui.mici.layouts.onboarding import TrainingGuidePreDMTutorial
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTermsPage
  pre = TrainingGuidePreDMTutorial(continue_callback=lambda: None)
  gui_app.push_widget(pre)
  assert ui_state.params.get_bool('IsDriverViewEnabled')
  gui_app.pop_widget()
  assert not ui_state.params.get_bool('IsDriverViewEnabled')
  terms = ReviewTermsPage()
  gui_app.push_widget(terms)
  draw(terms)
  assert not terms._accept_button.is_visible and not terms._decline_button.is_visible
  assert not terms._must_accept_card.is_visible
  assert not ui_state.params.get_bool('DoUninstall')
  assert not ui_state.params.get('HasAcceptedTermsSP')
  gui_app.pop_widget()


def test_terms_qr_display_decodes_to_original_terms_url():
  import cv2
  import numpy as np
  from openpilot.selfdrive.ui.mici.layouts.onboarding import QRCodeWidget
  view = QRCodeWidget('https://sunnypilot.ai/terms')
  rl.begin_drawing()
  rl.clear_background(rl.BLACK)
  view.render(rl.Rectangle(16, 24, 170, 170))
  rl.end_drawing()
  image = rl.load_image_from_screen()
  try:
    rl.image_format(image, rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8)
    rgba = np.frombuffer(rl.ffi.buffer(image.data, image.width * image.height * 4), dtype=np.uint8)
    rgba = rgba.reshape(image.height, image.width, 4)
    qr = cv2.cvtColor(rgba[24:194, 16:186], cv2.COLOR_RGBA2GRAY)
    assert cv2.QRCodeDetector().detectAndDecode(qr)[0] == 'https://sunnypilot.ai/terms'
  finally:
    rl.unload_image(image)
    view.close()


@pytest.mark.parametrize('service', ['comma', 'sunnylink', 'sponsor'])
@pytest.mark.parametrize('language', ['zh-CHS', 'en'])
@pytest.mark.parametrize('failed', [False, True])
def test_pairing_service_name_and_status_fit_without_eliding(pairing_services, monkeypatch, service, language, failed):
  services = pairing_services
  multilang._language = language
  multilang.setup()
  gui_app.on_language_changed(language)
  if service == 'comma':
    dialog = services.comma.PairingDialog()
    brand = 'comma connect'
  else:
    dialog = services.sunnylink.SunnylinkPairingDialog(service == 'sunnylink')
    brand = 'sunnylink' if service == 'sunnylink' else 'sunnypilot'
  if failed:
    def unavailable():
      raise RuntimeError('controlled pairing failure')
    monkeypatch.setattr(dialog, '_get_pairing_url', unavailable)
  gui_app.push_widget(dialog)
  for _ in range(40):
    draw(dialog)
  header, status = dialog._pair_label, dialog._instruction_label
  assert brand in '\n'.join(header._cached_wrapped_lines)
  for label in (header, status):
    assert label.get_content_height(int(label.rect.width)) <= label.rect.height
    assert all('...' not in line for line in label._cached_wrapped_lines)
  assert header.rect.y + header.rect.height <= status.rect.y
  assert status.rect.y + status.rect.height <= dialog._retry_button.rect.y


@pytest.mark.parametrize('language', ['zh-CHS', 'en'])
def test_training_upload_and_terms_text_fit_beside_icons_without_clipping(language):
  from openpilot.selfdrive.ui.mici.layouts.onboarding import TrainingGuideRecordFront
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTermsPage
  multilang._language = language
  multilang.setup()
  gui_app.on_language_changed(language)
  record = TrainingGuideRecordFront(continue_callback=lambda: None)
  terms = ReviewTermsPage()
  try:
    for card in (*record._scroller.items[:3], terms._terms_link_card):
      rl.begin_drawing()
      card.render(rl.Rectangle(0, 0, card.rect.width, card.rect.height))
      rl.end_drawing()
      icon_left = card.rect.x + card.rect.width - 30 - (card._txt_icon.width if card._txt_icon else 0)
      for label in (card._label, card._sub_label):
        assert label.rect.x + label.rect.width <= icon_left
        assert label.get_content_height(int(label.rect.width)) <= label.rect.height
        assert all('...' not in line for line in label._cached_wrapped_lines)
  finally:
    terms.hide_event()


def test_review_terms_qr_is_released_on_exit_and_regenerated_on_reopen(pairing_services):
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTermsPage
  from openpilot.selfdrive.ui.mici.layouts.onboarding import QRCodeWidget
  terms = ReviewTermsPage()
  code = next(item for item in terms._scroller.items if isinstance(item, QRCodeWidget))
  gui_app.push_widget(terms)
  first_texture = code._qr_texture.id
  gui_app.pop_widget()
  assert code._qr_texture is None
  assert pairing_services.unloaded.count(first_texture) == 1
  gui_app.push_widget(terms)
  assert code._qr_texture.id > 0
  gui_app.pop_widget()
  code.close()
  assert code._qr_texture is None


@pytest.mark.parametrize('missing', ['camera', 'monitoring', 'driver'])
def test_training_check_waits_for_camera_and_messages_from_this_opening(camera_preview, monkeypatch, missing):
  from types import SimpleNamespace
  from cereal import messaging
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTrainingGuide
  class Messages(dict):
    frame = 100
    recv_frame = {'driverMonitoringState': 99, 'driverStateV2': 99}
  dm = messaging.new_message('driverMonitoringState').driverMonitoringState
  dm.visionPolicyState.faceDetected = True
  messages = Messages(driverMonitoringState=dm)
  monkeypatch.setattr(ui_state, 'sm', messages)
  guide = ReviewTrainingGuide(completed_callback=lambda: None)
  gui_app.push_widget(guide)
  tutorial = guide._steps[2]
  gui_app.push_widget(tutorial)
  draw(tutorial)
  monkeypatch.setattr(tutorial._dialog.driver_state_renderer, 'get_driver_data',
                      lambda: SimpleNamespace(faceOrientation=[0, 0, 0]))
  tutorial._dialog._camera_view.frame = None if missing == 'camera' else object()
  messages.frame = 101
  messages.recv_frame = {'driverMonitoringState': 99 if missing == 'monitoring' else 101,
                         'driverStateV2': 99 if missing == 'driver' else 101}
  for _ in range(400):
    tutorial._update_state()
  assert tutorial._progress.x == 0
  assert not tutorial._good_button.enabled
  tutorial._dialog._camera_view.frame = object()
  for _ in range(400):
    messages.frame += 1
    messages.recv_frame = {'driverMonitoringState': messages.frame, 'driverStateV2': messages.frame}
    tutorial._update_state()
  assert tutorial._progress.x == 1 and tutorial._good_button.enabled
  tutorial._dialog._camera_view.frame = None
  tutorial._update_state()
  assert tutorial._progress.x == 0 and not tutorial._good_button.enabled


def test_training_camera_dismiss_animation_does_not_reenable_or_read_closed_camera(camera_preview):
  from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTrainingGuide
  _, device, _ = camera_preview
  guide = ReviewTrainingGuide(completed_callback=lambda: None)
  gui_app.push_widget(guide)
  tutorial = guide._steps[2]
  gui_app.push_widget(tutorial)
  for _ in range(40):
    draw(tutorial)
  tutorial.dismiss()
  for _ in range(60):
    draw(tutorial)
  assert gui_app.get_active_widget() is guide
  assert not tutorial._dm_open and tutorial._dialog._camera_view is None
  assert not ui_state.params.get_bool('IsDriverViewEnabled')
  assert device._interactive_timeout_callbacks == []
  assert device._override_interactive_timeout == 300


@pytest.mark.parametrize('entry', ['shortcut', 'device'])
@pytest.mark.parametrize('initial', [False, True])
@pytest.mark.parametrize('outcome', ['accept', 'cancel', 'engage'])
def test_always_offroad_confirmation_persists_before_runtime_refresh(monkeypatch, entry, initial, outcome):
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP
  from openpilot.selfdrive.ui.sunnypilot.ui_state import UIStateSP
  stored = ui_state.params
  stored.put_bool('OffroadMode', initial, block=True)
  deferred = []

  class DeferredParams:
    def __getattr__(self, name):
      return getattr(stored, name)

    def put_bool(self, key, value, block=False):
      if block:
        return stored.put_bool(key, value, block=True)
      deferred.append((key, value))

  engaged = [False]
  monkeypatch.setattr(ui_state, 'params', DeferredParams())
  monkeypatch.setattr(ui_state, 'always_offroad', initial)
  monkeypatch.setattr(ui_state, '_enforce_constraints', lambda: None)
  monkeypatch.setattr(type(ui_state), 'engaged', property(lambda self: engaged[0]))
  panel = SettingsLayoutSP() if entry == 'shortcut' else make_panel('device')
  gui_app.push_widget(panel)
  target = panel if entry == 'shortcut' else panel.controller
  target._handle_always_offroad()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  if outcome == 'cancel':
    dialog._cancel_button_callback()
  else:
    engaged[0] = outcome == 'engage'
    dialog._confirm_button_callback()
  expected = not initial if outcome == 'accept' else initial
  assert stored.get_bool('OffroadMode') == expected
  assert deferred == []
  UIStateSP.update_params(ui_state)
  assert ui_state.always_offroad == expected
  assert gui_app.get_active_widget() is panel


@pytest.mark.parametrize('action, chinese', [('reset', '重置'), ('uninstall', '卸载'), ('reboot', '重启'), ('power off', '关机')])
@pytest.mark.parametrize('translated_input', [False, True])
@pytest.mark.parametrize('engaged', [False, True])
def test_native_device_confirmation_translates_action_and_refreshes_open_dialog(monkeypatch, action, chinese, translated_input, engaged):
  from openpilot.selfdrive.ui.mici.layouts.settings.device import EngagedConfirmationButton, EngagedConfirmationCircleButton
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigConfirmationDialog
  monkeypatch.setattr(type(ui_state), 'engaged', property(lambda self: engaged))
  icon = gui_app.texture('icons_mici/settings/device/power.png', 64, 66)
  calls = []
  action_text = tr(action) if translated_input else action
  if action in ('reset', 'uninstall'):
    button = EngagedConfirmationButton('device operation', action_text, icon, lambda: calls.append(action))
  else:
    button = EngagedConfirmationCircleButton(action_text, icon, lambda: calls.append(action), red=action == 'power off')
  for opening_language in ('zh-CHS', 'en'):
    multilang._language = opening_language
    multilang.setup()
    gui_app.on_language_changed(opening_language)
    button._click_callback()
    dialog = gui_app.get_active_widget()
    assert isinstance(dialog, BigDialog if engaged else BigConfirmationDialog)
    label = dialog._card._sub_label if engaged else dialog._slider._label
    for language_index, language in enumerate(('zh-CHS', 'en', 'zh-CHS')):
      multilang._language = language
      multilang.setup()
      gui_app.on_language_changed(language)
      for _ in range(40 if language_index == 0 else 4):
        draw(dialog)
      expected = ('请先退出接管再' + chinese if engaged else '滑动以\n' + chinese) if language == 'zh-CHS' else (
        'Disengage to ' + action if engaged else 'slide to\n' + action)
      assert label.text == expected
      assert label.text_width <= label.rect.width
      assert all('...' not in line for line in label._cached_wrapped_lines)
    gui_app.pop_widget()
  assert calls == []


@pytest.mark.parametrize('operation, index, param', [
  ('reset', -4, 'OnroadCycleRequested'), ('uninstall', -3, 'DoUninstall'), ('reboot', -2, 'DoReboot'), ('power off', -1, 'DoShutdown'),
])
@pytest.mark.parametrize('outcome', ['accept', 'cancel', 'engage', 'already_engaged'])
def test_native_device_confirmation_preserves_actual_operation_guards(monkeypatch, operation, index, param, outcome):
  from openpilot.selfdrive.ui.mici.layouts.settings.device import DeviceLayoutMici
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog, BigConfirmationDialog
  learning = ('CalibrationParams', 'LiveTorqueParameters', 'LiveParameters', 'LiveParametersV2', 'LiveDelay')
  for key in learning:
    ui_state.params.put(key, {'test': 'native-calibration'} if key == 'LiveParameters' else b'native-calibration', block=True)
  saved = {key: ui_state.params.get(key) for key in learning}
  engaged = [outcome == 'already_engaged']
  monkeypatch.setattr(type(ui_state), 'engaged', property(lambda self: engaged[0]))
  monkeypatch.setattr(ui_state, '_offroad_transition_callbacks', [])
  panel = DeviceLayoutMici()
  gui_app.push_widget(panel)
  panel._scroller.items[index]._click_callback()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, BigDialog if outcome == 'already_engaged' else BigConfirmationDialog)
  if outcome in ('accept', 'engage'):
    engaged[0] = outcome == 'engage'
    dialog._on_confirm()
    if operation == 'reset':
      for _ in range(100):
        draw(dialog)
        if gui_app.get_active_widget() is panel:
          break
      assert gui_app.get_active_widget() is panel
  else:
    gui_app.pop_widget()
  for flag in ('OnroadCycleRequested', 'DoUninstall', 'DoReboot', 'DoShutdown'):
    assert ui_state.params.get_bool(flag) == (flag == param and outcome == 'accept')
  for key in learning:
    assert ui_state.params.get(key) == (None if operation == 'reset' and outcome == 'accept' else saved[key])


@pytest.mark.parametrize('initial,target', [('zh-CHS', 'en'), ('en', 'zh-CHS')])
def test_native_language_selection_refreshes_root_and_cached_panels_without_recreating(monkeypatch, initial, target):
  from types import SimpleNamespace
  from openpilot.system.ui.lib.wifi_manager import WifiManager
  from openpilot.selfdrive.ui.mici.layouts.settings import firehose
  from openpilot.selfdrive.ui.mici.layouts.settings.settings import SettingsLayout
  from openpilot.selfdrive.ui.mici.layouts.settings.device import LanguageSelectionLayout, DeviceLayoutMici
  from openpilot.selfdrive.ui.mici.layouts.settings.network.network_layout import NetworkLayoutMici
  from openpilot.selfdrive.ui.mici.layouts.settings.toggles import TogglesLayoutMici
  from openpilot.selfdrive.ui.mici.layouts.settings.developer import DeveloperLayoutMici
  monkeypatch.setattr(WifiManager, '_initialize', lambda self: None)
  monkeypatch.setattr(WifiManager, 'set_active', lambda *args: None)
  monkeypatch.setattr(ui_state, '_offroad_transition_callbacks', [])
  monkeypatch.setattr(ui_state, '_engaged_transition_callbacks', [])
  monkeypatch.setattr(firehose.threading, 'Thread', lambda *args, **kwargs: SimpleNamespace(start=lambda: None, is_alive=lambda: False))
  monkeypatch.setattr(multilang, '_params', ui_state.params)
  multilang._language = initial
  multilang.setup()
  gui_app.on_language_changed(initial)
  root = SettingsLayout()
  gui_app.push_widget(root)
  panels = []
  for index in (0, 1, 4, 5):
    root._scroller.items[index]._click_callback()
    panels.append(gui_app.get_active_widget())
    gui_app.pop_widget()
  assert isinstance(panels[0], TogglesLayoutMici)
  assert isinstance(panels[1], NetworkLayoutMici)
  assert isinstance(panels[3], DeveloperLayoutMici)
  root._scroller.items[2]._click_callback()
  device_panel = gui_app.get_active_widget()
  assert isinstance(device_panel, DeviceLayoutMici)
  callbacks = (tuple(ui_state._offroad_transition_callbacks), tuple(ui_state._engaged_transition_callbacks))
  # Keep a real current value; a username is data even if it matches a UI label.
  panels[3]._ssh_keys_btn.set_value('reset')
  panels[0]._personality_toggle.set_value(tr('standard'))
  panels[1]._network_metered_btn.set_value(tr('metered'))
  device_panel._scroller.scroll_panel.set_offset(-422)
  root._scroller.scroll_panel.set_offset(-50)
  before_personality = ui_state.params.get('LongitudinalPersonality')
  gui_app.push_widget(LanguageSelectionLayout(device_panel))
  picker = gui_app.get_active_widget()
  picker._scroller.items[0 if target == 'en' else 1]._click_callback()
  assert gui_app.get_active_widget() is device_panel
  assert multilang.language == target
  assert ui_state.params.get('LanguageSetting') == target
  assert callbacks == (tuple(ui_state._offroad_transition_callbacks), tuple(ui_state._engaged_transition_callbacks))
  assert device_panel._scroller.scroll_panel.get_offset() == -422
  assert root._scroller.scroll_panel.get_offset() == -50
  assert ui_state.params.get('LongitudinalPersonality') == before_personality
  for index, source in [(0, 'toggles'), (1, 'network'), (2, 'device'), (4, 'firehose'), (5, 'developer')]:
    assert root._scroller.items[index].get_text() == tr(source)
  assert device_panel._scroller.items[-6].get_text() == tr('change language')
  assert panels[0]._personality_toggle._options == [tr('aggressive'), tr('standard'), tr('relaxed')]
  assert panels[1]._network_metered_btn._options == [tr('default'), tr('metered'), tr('unmetered')]
  assert panels[0]._personality_toggle.get_value() == tr('standard')
  assert panels[1]._network_metered_btn.get_value() == tr('metered')
  assert panels[1]._apn_btn.get_text() == tr('apn settings')
  assert panels[1]._apn_btn.get_value() == tr('edit')
  assert panels[3]._ssh_keys_btn.get_text() == tr('SSH keys')
  assert panels[3]._ssh_keys_btn.get_value() == 'reset'
  draw(device_panel._scroller.items[0])
  info = device_panel._scroller.items[0]
  assert info._dongle_id_label.text == tr('device id')
  assert info._serial_number_label.text == tr('serial')
  gui_app.pop_widget()
  for index, panel in zip((0, 1, 4, 5), panels, strict=True):
    root._scroller.items[index]._click_callback()
    assert gui_app.get_active_widget() is panel
    gui_app.pop_widget()


@pytest.mark.parametrize('languages', [('zh-CHS', 'en', 'zh-CHS'), ('en', 'zh-CHS', 'en')])
@pytest.mark.parametrize('index,metered', [(0, 0), (1, 1), (2, 2)])
def test_native_network_enum_keeps_selected_index_across_languages(network_editor, monkeypatch, languages, index, metered):
  panel, _ = network_editor
  calls = []
  monkeypatch.setattr(panel.native._wifi_manager, 'set_current_network_metered', calls.append)
  button = panel.native._network_metered_btn
  button.set_value(button._options[index])
  for language in languages:
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    button.refresh_options()
    assert button._options.index(button.get_value()) == index
    button._select_callback(button.get_value())
  assert [int(value) for value in calls] == [metered] * len(languages)


@pytest.mark.parametrize('editor,hint', [('apn', 'enter APN...'), ('hotspot', 'enter password...'), ('wifi', 'enter password...')])
def test_native_network_input_hint_refreshes_language_and_preserves_text(network_editor, editor, hint):
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
  panel, _ = network_editor
  if editor == 'apn':
    panel.native._edit_apn()
  elif editor == 'hotspot':
    panel.native._tethering_password_btn._click_callback()
  else:
    panel.native._wifi_ui._on_need_auth('reset', False)
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, BigInputDialog)
  for language in ('zh-CHS', 'en', 'zh-CHS'):
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    for _ in range(40):
      draw(dialog)
    assert dialog._hint_label.text == tr(hint)
    dialog._keyboard.set_text('reset1234')
    draw(dialog)
    assert dialog._keyboard.text() == 'reset1234'
    dialog._keyboard.set_text('')
  gui_app.pop_widget()
  assert gui_app.get_active_widget() is panel
  assert ui_state.params.get('GsmApn') is None


def test_native_username_hint_and_unset_state_follow_language_without_fetching(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts.settings import developer
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
  monkeypatch.setattr(ui_state, '_offroad_transition_callbacks', [])
  monkeypatch.setattr(developer, 'system_time_valid', lambda: True)
  panel = developer.DeveloperLayoutMici()
  gui_app.push_widget(panel)
  panel._ssh_keys_btn._click_callback()
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, BigInputDialog)
  for language in ('zh-CHS', 'en', 'zh-CHS'):
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    for _ in range(40):
      draw(dialog)
    assert dialog._hint_label.text == tr('enter GitHub username...')
    assert panel._ssh_keys_btn.get_value() == tr('Not set')
    dialog._keyboard.set_text('reset')
    draw(dialog)
    assert dialog._keyboard.text() == 'reset'
    dialog._keyboard.set_text('')
  gui_app.pop_widget()
  assert gui_app.get_active_widget() is panel
  assert ui_state.params.get('GithubSshKeys') is None


def test_native_title_remeasures_font_after_language_change(monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts.settings.toggles import TogglesLayoutMici
  monkeypatch.setattr(ui_state, '_engaged_transition_callbacks', [])
  panel = TogglesLayoutMici()
  button = panel._scroller.items[6]
  for language in ('zh-CHS', 'en', 'zh-CHS'):
    multilang._language = language
    multilang.setup()
    gui_app.on_language_changed(language)
    draw(button)
    assert button._label.text == tr('disable driver monitoring camera')
    assert button._label.font_size == (48 if len(button.get_text()) <= 18 else 42)


@pytest.fixture
def main_navigation(monkeypatch):
  from types import SimpleNamespace
  from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP
  from openpilot.system.ui.widgets.scroller import Scroller

  class Main(MiciMainLayout):
    def __init__(self):
      Scroller.__init__(self)
      self._onboarding_window = CompactPage('onboarding')
      self._prev_onroad = False
      self._prev_standstill = False
      self._onroad_time_delay = None
      self._home_layout = CompactPage('home')
      self._car_onroad_layout = CompactPage('car onroad')
      self._body_onroad_layout = CompactPage('body onroad')
      self.destinations = []

    def _scroll_to(self, layout):
      self.destinations.append(layout)

    def _render(self, rect):
      pass

  now = [100.0]
  messages = {'carState': SimpleNamespace(standstill=True)}
  monkeypatch.setattr(rl, 'get_time', lambda: now[0])
  monkeypatch.setattr(ui_state, 'sm', messages)
  monkeypatch.setattr(ui_state, 'is_body', False)
  main = Main()
  gui_app.push_widget(main)
  settings = SettingsLayoutSP()
  gui_app.push_widget(settings)
  settings.open_panel('steering')
  panel = gui_app.get_active_widget()
  return main, settings, panel, now, messages['carState']


def test_returning_offroad_cancels_pending_onroad_settings_exit(main_navigation, monkeypatch):
  main, _, panel, now, _ = main_navigation
  monkeypatch.setattr(ui_state, 'started', True)
  main._handle_transitions()
  assert main._onroad_time_delay == now[0]
  now[0] += 1
  monkeypatch.setattr(ui_state, 'started', False)
  main._handle_transitions()
  now[0] += 3
  main._handle_transitions()
  assert gui_app.get_active_widget() is panel
  assert main._onroad_time_delay is None
  assert main.destinations == [main._home_layout]


@pytest.mark.parametrize('trigger', ['delay', 'movement', 'timeout'])
@pytest.mark.parametrize('offroad_during_animation', [False, True])
def test_settings_input_dismiss_uses_vehicle_state_when_animation_finishes(main_navigation, monkeypatch, trigger, offroad_during_animation):
  from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
  main, _, panel, now, cs = main_navigation
  accepted = []
  cancelled = []
  dialog = BigInputDialog(tr('enter APN...'), 'unchanged', confirm_callback=accepted.append,
                          cancel_callback=lambda: cancelled.append(True))
  gui_app.push_widget(dialog)
  for _ in range(40):
    draw(dialog)
  monkeypatch.setattr(ui_state, 'started', True)
  main._handle_transitions()
  if trigger == 'delay':
    now[0] += 3
    main._handle_transitions()
  elif trigger == 'movement':
    cs.standstill = False
    main._handle_transitions()
  else:
    cs.standstill = False
    main._on_interactive_timeout()
  assert dialog.is_dismissing
  if offroad_during_animation:
    monkeypatch.setattr(ui_state, 'started', False)
    main._handle_transitions()
  for _ in range(100):
    draw(dialog)
    if gui_app.get_active_widget() is main:
      break
  assert gui_app.get_active_widget() is main
  assert accepted == []
  assert cancelled == [True]
  assert main.destinations[-1] is (main._home_layout if offroad_during_animation else main._onroad_layout)
  assert not gui_app.widget_in_stack(panel)


@pytest.mark.parametrize('leaf', ['numeric', 'confirmation'])
def test_onroad_exit_dismisses_nested_compact_settings_without_accepting(main_navigation, monkeypatch, leaf):
  main, _, panel, now, _ = main_navigation
  accepted = []
  if leaf == 'numeric':
    item = panel.controller._lat_position_offset
    panel._open_number(item, lambda: item.title, lambda: item.description)
  else:
    gui_app.push_widget(ConfirmDialog('confirm settings change', tr('Confirm'), callback=accepted.append))
  before = ui_state.params.get('LateralPositionOffset')
  monkeypatch.setattr(ui_state, 'started', True)
  main._handle_transitions()
  now[0] += 3
  main._handle_transitions()
  assert gui_app.get_active_widget() is main
  assert main.destinations == [main._onroad_layout]
  assert accepted == []
  assert ui_state.params.get('LateralPositionOffset') == before


def test_new_onroad_cycle_gets_full_settings_exit_delay(main_navigation, monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts.main import ONROAD_DELAY
  main, _, panel, now, _ = main_navigation
  monkeypatch.setattr(ui_state, 'started', True)
  main._handle_transitions()
  first_start = now[0]
  now[0] += 1
  monkeypatch.setattr(ui_state, 'started', False)
  main._handle_transitions()
  now[0] += 1
  monkeypatch.setattr(ui_state, 'started', True)
  main._handle_transitions()
  second_start = now[0]
  now[0] = first_start + ONROAD_DELAY + 0.01
  main._handle_transitions()
  assert gui_app.get_active_widget() is panel
  assert main._onroad_time_delay == second_start
  now[0] = second_start + ONROAD_DELAY + 0.01
  main._handle_transitions()
  assert gui_app.get_active_widget() is main
  assert main.destinations == [main._home_layout, main._onroad_layout]
