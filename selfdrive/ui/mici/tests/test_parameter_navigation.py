"""Exercise shallow parameter access and safe editing on the small display."""
from pathlib import Path

import pytest
import pyray as rl
from cereal import car
from openpilot.common.constants import CV
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import PARAMETER_TITLES, ParameterPanel, ParameterTogglePage, parameter_key
from openpilot.system.ui.lib.application import gui_app, MouseEvent, MousePos
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.compact import CompactInfoPage, CompactNumberPage, RepeatButton, resolve
from openpilot.selfdrive.ui.mici.tests.test_settings import state, window, draw  # noqa: F401


@pytest.fixture(autouse=True)
def metric(state, monkeypatch):  # noqa: F811
  monkeypatch.setattr(ui_state, 'is_metric', True)
  ui_state.params.put_bool('IsMetric', True, block=True)


def root():
  widget = SettingsLayoutSP()
  gui_app.push_widget(widget)
  draw(widget)
  return widget


@pytest.mark.parametrize('kind', list(PARAMETER_TITLES))
def test_parameter_destinations_render_directly_from_home(kind):
  home = root()
  index = list(PARAMETER_TITLES).index(kind)
  home.buttons[index]._click_callback()
  page = gui_app.get_active_widget()
  assert isinstance(page, ParameterPanel)
  draw(page)
  assert not page._list.horizontal
  visible = page._list.visible_items[:1]
  assert all(row.rect.width >= 500 and row.rect.height == 144 for row in visible)
  assert len(visible) == 1
  assert all(row.rect.y >= 48 and row.rect.y + row.rect.height <= 192 for row in visible)
  assert page._list._previous.rect.height == 44 and page._list._next.rect.height == 44
  assert len(home.buttons) == 20
  assert len(home._list._scroller.items) == 5
  assert all(button.rect.height >= 80 and button.rect.width >= 180 for button in home.buttons[:4])


def test_two_click_numeric_access_and_scroll_survives_editor():
  home = root()
  home.buttons[0]._click_callback()
  panel = gui_app.get_active_widget()
  draw(panel)
  panel._list.change_page(1)
  item = panel.controller._lat_position_offset
  panel._rows[item][0].callback()
  assert isinstance(gui_app.get_active_widget(), CompactNumberPage)
  gui_app.pop_widget()
  draw(panel)
  assert panel._list.page == 1


@pytest.mark.parametrize('kind,key', [('steering', 'BlinkerMinLateralControlSpeed'), ('steering', 'MadsSteeringMode'),
                                     ('torque', 'TorqueParamsOverrideFriction'), ('cruise', 'SpeedLimitValueOffset'),
                                     ('models', 'LaneTurnValue'), ('models', 'LagdToggleDelay')])
def test_disabled_parameters_remain_visible_and_only_open_explanation(kind, key):
  ui_state.params.put_bool('Mads', False, block=True)
  ui_state.params.put_bool('BlinkerPauseLateralControl', False, block=True)
  ui_state.params.put_bool('LaneTurnDesire', False, block=True)
  ui_state.params.put_bool('LagdToggle', True, block=True)
  ui_state.params.put_bool('ShowAdvancedControls', False, block=True)
  ui_state.params.put('SpeedLimitOffsetType', 0, block=True)
  home = root()
  home.open_parameters(kind)
  panel = gui_app.get_active_widget()
  draw(panel)
  item = next(item for item in panel._source_items if parameter_key(item) == key)
  row = panel._rows[item][0]
  assert row.is_visible and not resolve(row.available)
  assert panel._unavailable_reason(item)
  before = ui_state.params.get(key)
  row._handle_mouse_release(MousePos(row.rect.x + 100, row.rect.y + 20))
  assert isinstance(gui_app.get_active_widget(), CompactInfoPage)
  assert ui_state.params.get(key) == before


def test_model_parameters_do_not_require_advanced_menu():
  ui_state.params.put_bool('ShowAdvancedControls', False, block=True)
  ui_state.params.put_bool('LaneTurnDesire', True, block=True)
  ui_state.params.put_bool('LagdToggle', False, block=True)
  home = root()
  home.open_parameters('models')
  panel = gui_app.get_active_widget()
  for item in (panel.controller.lane_turn_value_control, panel.controller.delay_control):
    assert not item.is_visible
    assert panel._item_available(item)
    panel._rows[item][0].callback()
    assert isinstance(gui_app.get_active_widget(), CompactNumberPage)
    gui_app.pop_widget()


def test_search_finds_chinese_english_and_key_without_writing():
  home = root()
  home.open_search()
  search = gui_app.get_active_widget()
  for query in (tr('Lane Position Offset'), 'Lane Position', 'LateralPositionOffset'):
    search.query = query
    search.refresh()
    assert len(search.matching_entries()) == 1
    entry = search.matching_entries()[0]
    before = ui_state.params.get('LateralPositionOffset')
    search.open_result(entry)
    panel = gui_app.get_active_widget()
    assert isinstance(panel, ParameterPanel)
    draw(panel)
    assert ui_state.params.get('LateralPositionOffset') == before
    row = next(rows[0] for item, rows in panel._rows.items() if parameter_key(item) == 'LateralPositionOffset')
    draw(panel)
    assert panel._list.rect.y <= row.rect.y + 1
    assert row.rect.y + row.rect.height <= panel._list.rect.y + panel._list.rect.height + 1
    gui_app.pop_widget()
  search.query = 'IsMetric'
  assert any(entry[1] == 'IsMetric' for entry in search.matching_entries())


def test_favorites_preserve_unknown_entries_and_fail_without_data_loss():
  home = root()
  ui_state.params.put('C4FavoriteSettings', ['future-key'], block=True)
  home._favorites.toggle('LateralPositionOffset')
  assert ui_state.params.get('C4FavoriteSettings') == ['future-key', 'LateralPositionOffset']
  home.open_search()
  search = gui_app.get_active_widget()
  search.toggle_filter()
  assert [entry[1] for entry in search.matching_entries()] == ['LateralPositionOffset']
  home._favorites.toggle('LateralPositionOffset')
  assert ui_state.params.get('C4FavoriteSettings') == ['future-key']
  ui_state.params.put('C4FavoriteSettings', {'unknown-format': ['future-key']}, block=True)
  with pytest.raises(ValueError):
    home._favorites.toggle('LateralPositionOffset')
  assert ui_state.params.get('C4FavoriteSettings') == {'unknown-format': ['future-key']}


def editor():
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  panel._rows[panel.controller._lat_position_offset][0].callback()
  return gui_app.get_active_widget(), panel


def test_input_default_undo_and_external_edit_protection():
  ui_state.params.put('LateralPositionOffset', 2, block=True)
  page, _ = editor()
  page.submit_input('-4')
  assert ui_state.params.get('LateralPositionOffset') == -4
  page.undo()
  assert ui_state.params.get('LateralPositionOffset') == 2
  page.restore_default()
  assert ui_state.params.get('LateralPositionOffset') == 0
  page.undo()
  assert ui_state.params.get('LateralPositionOffset') == 2
  for invalid in ('nan', 'Inf', '2.1', '1000', 'x'):
    page.submit_input(invalid)
    assert ui_state.params.get('LateralPositionOffset') == 2
  page.submit_input('3')
  ui_state.params.put('LateralPositionOffset', 8, block=True)
  page.undo()
  assert ui_state.params.get('LateralPositionOffset') == 8
  assert page._history is None


def test_stale_numeric_editor_cannot_write_after_prerequisite_changes():
  ui_state.params.put_bool('BlinkerPauseLateralControl', True, block=True)
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  panel._rows[panel.controller._blinker_control_options][0].callback()
  page = gui_app.get_active_widget()
  before = ui_state.params.get('BlinkerMinLateralControlSpeed')
  ui_state.params.put_bool('BlinkerPauseLateralControl', False, block=True)
  page.submit_input('50')
  assert ui_state.params.get('BlinkerMinLateralControlSpeed') == before


def test_number_write_failure_keeps_cache_and_reports_error():
  page, _ = editor()
  destination = Path(ui_state.params.get_param_path('LateralPositionOffset'))
  before = page.action.current_value
  destination.mkdir()
  page.submit_input('5')
  assert page.action.current_value == before
  assert page._status.startswith('保存失败')
  assert destination.is_dir()


def test_toggle_and_enum_failures_do_not_report_success():
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  item = panel.controller._blinker_control_toggle
  destination = Path(ui_state.params.get_param_path('BlinkerPauseLateralControl'))
  destination.mkdir()
  panel._toggle(item)
  assert panel._notification.startswith('保存失败')
  assert not item.action_item.get_state()


def test_direct_speed_input_uses_display_units_and_keeps_physical_storage(monkeypatch):
  ui_state.params.put_bool('BlinkerPauseLateralControl', True, block=True)
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  panel._rows[panel.controller._blinker_control_options][0].callback()
  page = gui_app.get_active_widget()
  ui_state.params.put_bool('IsMetric', False, block=True)
  monkeypatch.setattr(ui_state, 'is_metric', False)
  page.submit_input('20')
  assert ui_state.params.get('BlinkerMinLateralControlSpeed') == pytest.approx(20 * CV.MPH_TO_KPH)
  ui_state.params.put_bool('IsMetric', True, block=True)
  monkeypatch.setattr(ui_state, 'is_metric', True)
  draw(page)
  assert page.action.current_value == round(20 * CV.MPH_TO_KPH * 100)


def test_repeat_button_stops_on_release_disable_and_hidden(monkeypatch):
  calls = []
  now = [0.0]
  monkeypatch.setattr(rl, 'get_time', lambda: now[0])
  button = RepeatButton('+', lambda: calls.append(now[0]))
  rect = rl.Rectangle(0, 0, 88, 60)
  pos = MousePos(40, 30)
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, True, False, True, 0)])
  button.render(rect)
  assert len(calls) == 1
  now[0] = .5
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, False, False, True, .5)])
  button.render(rect)
  assert len(calls) == 2
  now[0] = .7
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, False, True, False, .7)])
  button.render(rect)
  assert len(calls) == 2
  button.set_enabled(False)
  button.render(rect)
  assert button._repeat_at is None
  button.hide_event()
  assert not button._press_started


def test_torque_and_mads_children_preserve_parent_restrictions(monkeypatch):
  ui_state.params.put_bool('EnforceTorqueControl', True, block=True)
  ui_state.params.put_bool('CustomTorqueParams', True, block=True)
  ui_state.params.put_bool('Mads', True, block=True)
  home = root()
  home.open_parameters('torque')
  panel = gui_app.get_active_widget()
  item = panel.controller._torque_control_layout._torque_friction
  assert not panel._item_available(item)
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(steerControlType='angle'))
  assert not panel._item_available(item)
  monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(steerControlType='torque'))
  panel.refresh()
  assert panel._item_available(item)
  gui_app.pop_widget()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  mads_item = panel.controller._mads_settings_layout._steering_mode
  monkeypatch.setattr(ui_state, 'started', True)
  assert not panel._item_available(mads_item)


def test_secondary_parameters_use_lists_and_participate_in_search():
  home = root()
  for key in ('visuals', 'developer'):
    home.open_more_panel(key)
    assert isinstance(gui_app.get_active_widget(), ParameterPanel)
    draw(gui_app.get_active_widget())
    gui_app.pop_widget()
  home.open_search()
  search = gui_app.get_active_widget()
  search.query = 'ShowAdvancedControls'
  assert len(search.matching_entries()) == 1


def test_search_favorite_failure_is_visible_and_preserves_invalid_data():
  home = root()
  home.open_search()
  search = gui_app.get_active_widget()
  ui_state.params.put('C4FavoriteSettings', {'future': True}, block=True)
  search.toggle_favorite('LateralPositionOffset')
  assert gui_app.get_active_widget() is not search
  assert ui_state.params.get('C4FavoriteSettings') == {'future': True}


def test_model_speed_direct_input_converts_display_kph_to_stored_mph():
  ui_state.params.put_bool('LaneTurnDesire', True, block=True)
  home = root()
  home.open_parameters('models')
  panel = gui_app.get_active_widget()
  panel._rows[panel.controller.lane_turn_value_control][0].callback()
  page = gui_app.get_active_widget()
  page.submit_input('20')
  assert ui_state.params.get('LaneTurnValue') == pytest.approx(round(20 / CV.MPH_TO_KPH * 100) / 100)


def test_number_page_hiding_cancels_repeat():
  page, _ = editor()
  page._plus._handle_mouse_press(None)
  assert page._plus._repeat_at is not None
  gui_app.pop_widget()
  assert page._plus._repeat_at is None


def settle(widget, monkeypatch):
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  monkeypatch.setattr(rl, 'get_frame_time', lambda: 1 / 60)
  for _ in range(90):
    draw(widget)


def swipe(widget, x, ys, monkeypatch):
  events = [MouseEvent(MousePos(x, y), 0, index == 0, index == len(ys) - 1, index < len(ys) - 1, index * .1)
            for index, y in enumerate(ys)]
  monkeypatch.setattr(gui_app, '_mouse_events', events)
  draw(widget)
  settle(widget, monkeypatch)


def test_grid_page_buttons_reach_every_menu_without_swiping(monkeypatch):
  home = root()
  for index in range(5):
    assert home._grid_page() == index
    tap(home, home._next.rect, monkeypatch)
  assert home._grid_page() == 4
  for _ in range(5):
    tap(home, home._previous.rect, monkeypatch)
  assert home._grid_page() == 0
  assert gui_app.get_active_widget() is home
  assert all(button.rect.height >= 80 for button in home.buttons[:4])


def test_all_original_main_menus_have_direct_home_entries():
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import TITLES
  home = root()
  assert set(TITLES) <= set(home.menu_keys)
  assert str(resolve(home._header.action.text)) == tr('ADB / SSH')
  for key in ('network', 'device', 'software', 'developer'):
    home.buttons[home.menu_keys.index(key)]._click_callback()
    assert gui_app.get_active_widget() is not home
    gui_app.pop_widget()


def test_parameter_swipe_from_switch_never_toggles_or_changes_page(monkeypatch):
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  draw(panel)
  before = ui_state.params.get_bool('Mads')
  swipe(panel, 440, (205, 180, 110, 62, 62), monkeypatch)
  assert gui_app.get_active_widget() is panel
  assert ui_state.params.get_bool('Mads') == before
  assert panel._list.page == 0


def test_list_tap_opens_large_toggle_control_without_writing(monkeypatch):
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  draw(panel)
  row = panel._rows[panel.controller._blinker_control_toggle][0]
  panel._list.focus_item(row)
  draw(panel)
  before = ui_state.params.get_bool('BlinkerPauseLateralControl')
  tap(panel, row.rect, monkeypatch)
  detail = gui_app.get_active_widget()
  assert isinstance(detail, ParameterTogglePage)
  assert ui_state.params.get_bool('BlinkerPauseLateralControl') == before
  assert detail._toggle.rect.width >= 480 and detail._toggle.rect.height >= 88
  tap(detail, detail._toggle.rect, monkeypatch)
  assert ui_state.params.get_bool('BlinkerPauseLateralControl') != before
  assert ui_state.params.get('C4FavoriteSettings') is None
  tap(detail, detail._header.action.rect, monkeypatch)
  info = gui_app.get_active_widget()
  assert isinstance(info, CompactInfoPage)
  tap(info, info._header.action.rect, monkeypatch)
  assert ui_state.params.get('C4FavoriteSettings') == ['BlinkerPauseLateralControl']


def tap(widget, area, monkeypatch):
  pos = MousePos(area.x + area.width / 2, area.y + area.height / 2)
  monkeypatch.setattr(gui_app, '_mouse_events', [MouseEvent(pos, 0, True, False, True, 1),
                                               MouseEvent(pos, 0, False, True, False, 1.1)])
  draw(widget)
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  draw(gui_app.get_active_widget())


def test_page_buttons_visit_all_cards_and_preserve_params(monkeypatch):
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  draw(panel)
  before = {parameter_key(item): ui_state.params.get(parameter_key(item))
            for item in panel._source_items if parameter_key(item)}
  seen = []
  for index in range(panel._list.page_count):
    assert panel._list.page == index
    current = panel._list.visible_items[index:index + 1]
    seen.extend(current)
    assert all(row.rect.y >= 48 and row.rect.y + row.rect.height <= 192 for row in current)
    tap(panel, panel._list._next.rect, monkeypatch)
  assert seen == panel._list.visible_items
  assert panel._list.page == panel._list.page_count - 1
  for _ in range(panel._list.page_count + 1):
    tap(panel, panel._list._previous.rect, monkeypatch)
  assert panel._list.page == 0
  assert all(ui_state.params.get(key) == value for key, value in before.items())
  assert gui_app.get_active_widget() is panel


def test_drag_on_parameter_card_cannot_open_or_change_a_setting(monkeypatch):
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  draw(panel)
  row = panel._rows[panel.controller._blinker_control_toggle][0]
  panel._list.focus_item(row)
  draw(panel)
  before = ui_state.params.get_bool('BlinkerPauseLateralControl')
  swipe(panel, row.rect.x + 100, (row.rect.y + 40, row.rect.y + 10, row.rect.y + 40, row.rect.y + 40), monkeypatch)
  assert ui_state.params.get_bool('BlinkerPauseLateralControl') == before
  assert ui_state.params.get('C4FavoriteSettings') is None
  assert gui_app.get_active_widget() is panel


def test_header_search_and_favorites_are_direct_and_return_to_same_page(monkeypatch):
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  draw(panel)
  panel._list.change_page(1)
  draw(panel)
  favorite = 'LateralPositionOffset'
  home._favorites.toggle(favorite)
  tap(panel, panel._header.action._favorites.rect, monkeypatch)
  search = gui_app.get_active_widget()
  assert search.favorites_only
  draw(search)
  assert [entry[1] for entry in search.matching_entries()] == [favorite]
  assert search._list.position == '1/1'
  gui_app.pop_widget()
  draw(panel)
  assert panel._list.page == 1
  tap(panel, panel._header.action._search.rect, monkeypatch)
  search = gui_app.get_active_widget()
  assert not search.favorites_only
  draw(search)
  assert len(search._list.visible_items) > 2


def test_favorite_filter_handles_empty_and_odd_last_page(monkeypatch):
  home = root()
  home.open_search()
  search = gui_app.get_active_widget()
  search.toggle_filter()
  draw(search)
  assert search._list.page_count == 1
  assert len(search._list.visible_items) == 1
  assert not search._list._previous.enabled and not search._list._next.enabled
  keys = [entry[1] for entry in search._entries[:3]]
  ui_state.params.put('C4FavoriteSettings', keys, block=True)
  search.refresh()
  draw(search)
  tap(search, search._list._next.rect, monkeypatch)
  assert search._list.page == 1
  tap(search, search._list._next.rect, monkeypatch)
  assert search._list.page == 2
  search.toggle_favorite(keys[2])
  draw(search)
  assert search._list.page == 1 and search._list.page_count == 2
  tap(search, search._list._next.rect, monkeypatch)
  assert search._list.page == 1


def test_numeric_row_body_opens_editor_without_favoriting(monkeypatch):
  home = root()
  home.open_parameters('steering')
  panel = gui_app.get_active_widget()
  draw(panel)
  row = panel._rows[panel.controller._lat_position_offset][0]
  panel._list.focus_item(row)
  draw(panel)
  before = ui_state.params.get('LateralPositionOffset')
  tap(panel, rl.Rectangle(row.rect.x + 16, row.rect.y + 4, 240, 56), monkeypatch)
  assert isinstance(gui_app.get_active_widget(), CompactNumberPage)
  assert ui_state.params.get('LateralPositionOffset') == before
  assert ui_state.params.get('C4FavoriteSettings') is None


@pytest.mark.parametrize('key', ['AdbEnabled', 'SshEnabled'])
def test_adb_and_ssh_are_direct_searchable_and_large_without_advanced_menu(key, monkeypatch):
  ui_state.params.put_bool('ShowAdvancedControls', False, block=True)
  ui_state.params.put_bool('AdbEnabled', True, block=True)
  ui_state.params.put_bool('SshEnabled', True, block=True)
  ui_state.params.put('GithubUsername', 'existing-user', block=True)
  ui_state.params.put('GithubSshKeys', 'ssh-ed25519 existing-key', block=True)
  home = root()
  tap(home, home._header.action.rect, monkeypatch)
  panel = gui_app.get_active_widget()
  assert panel.kind == 'remote'
  assert [parameter_key(item) for item in panel._source_items] == ['AdbEnabled', 'SshEnabled', 'GithubSshKeys']
  item = next(item for item in panel._source_items if parameter_key(item) == key)
  row = panel._rows[item][0]
  panel._list.focus_item(row)
  draw(panel)
  tap(panel, row.rect, monkeypatch)
  detail = gui_app.get_active_widget()
  assert isinstance(detail, ParameterTogglePage)
  assert ui_state.params.get_bool(key)
  tap(detail, detail._toggle.rect, monkeypatch)
  assert not ui_state.params.get_bool(key)
  assert ui_state.params.get('GithubUsername') == 'existing-user'
  assert ui_state.params.get('GithubSshKeys') == 'ssh-ed25519 existing-key'
  gui_app.pop_widget()
  gui_app.pop_widget()
  home.open_search()
  search = gui_app.get_active_widget()
  search.query = key
  assert [entry[1] for entry in search.matching_entries()] == [key]
  assert search.matching_entries()[0][0] == 'remote'
