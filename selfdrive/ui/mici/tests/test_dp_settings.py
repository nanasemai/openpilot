"""Real small-display controls, with temporary params and offline device services."""

import pyray as rl
import pytest
import requests
from cereal import car

from openpilot.common.params import Params
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.mici.layouts.settings.firehose import FirehoseLayoutBase
from openpilot.system.ui.lib.application import gui_app, MouseEvent, FontWeight
from openpilot.system.ui.lib.multilang import multilang, tr
from openpilot.system.ui.lib.wifi_manager import WifiManager, WifiState, MeteredType
from openpilot.system.ui.widgets.compact import CompactPage, CompactNumberPage, CompactSelectPage, resolve
from dragonpilot.settings import SETTINGS
from dragonpilot.selfdrive.ui.mici.layouts.settings import SettingsLayout, SettingsLeaf, TogglePage
from dragonpilot.selfdrive.ui.mici.layouts.settings_menu import ROOT, NODES, PATHS, ROUTES, supports_mici


@pytest.fixture(scope='module', autouse=True)
def window():
  gui_app.init_window('DP C4 menus')
  yield
  gui_app.close()


@pytest.fixture
def state(monkeypatch):
  with OpenpilotPrefix():
    monkeypatch.setattr(ui_state, 'params', Params())
    monkeypatch.setattr(ui_state, 'update_params', lambda: None)
    monkeypatch.setattr(ui_state, 'started', False)
    monkeypatch.setattr(ui_state, 'is_release', False)
    monkeypatch.setattr(ui_state, 'has_longitudinal_control', True)
    monkeypatch.setattr(ui_state, 'CP', car.CarParams.new_message(brand='toyota', carFingerprint='MOCK', openpilotLongitudinalControl=True))
    monkeypatch.setattr(WifiManager, '_initialize', lambda s: None)
    monkeypatch.setattr(WifiManager, 'set_active', lambda *a: None)
    monkeypatch.setattr(WifiManager, 'set_ipv4_forward', lambda *a: None)
    monkeypatch.setattr(FirehoseLayoutBase, '_update_loop', lambda s: None)
    def offline(*a, **kw):
      raise requests.ConnectionError('Offline menu tests')
    monkeypatch.setattr(requests.Session, 'request', offline)
    monkeypatch.setattr(requests, 'request', offline)
    monkeypatch.setattr(multilang, '_language', 'zh-CHS')
    multilang.setup()
    gui_app.push_widget(CompactPage('Home'))
    root = SettingsLayout()
    root.open_from_home()
    yield root
    while len(gui_app._nav_stack) > 1:
      gui_app.pop_widget()


def draw(widget):
  rl.begin_drawing()
  rl.clear_background(rl.BLACK)
  widget.render(rl.Rectangle(0, 0, 536, 240))
  rl.end_drawing()


def enter(root, node):
  gui_app.pop_widgets_to(root, instant=True)
  for key in PATHS[node][1:]:
    root.open_menu(key)
  page = gui_app.get_active_widget()
  draw(page)
  draw(page)
  assert page.node.key == node
  return page


def row_for(page, key):
  return next(r for r in page.ref_rows.values() if r._c4_ref.key == key)


def open_row(page, key):
  row = row_for(page, key)
  page._list.focus_item(row)
  draw(page)
  row.callback()
  return gui_app.get_active_widget()


def test_feature_catalog_coverage():
  supported = {i['key'] for section in SETTINGS for i in section['settings'] if supports_mici(i)}
  routed = {r.key for node in NODES.values() for r in node.items if r.source == 'dp'} - {'btn_reset_dp_conf'}
  assert supported == routed
  assert len(ROUTES) == len(set(ROUTES))
  assert [node.key for node in ROOT.children][:4] == ['toggles', 'steering', 'cruise', 'vehicle']
  assert 'dp_ui_lead' not in routed  # This feature explicitly excludes MICI.
  assert 'dp_dev_model_selected' not in routed  # Vehicle selector is a native action, not a driving model.


@pytest.mark.parametrize('node', [n.key for n in NODES.values() if n.key != 'root'])
def test_every_menu_renders_and_has_no_search(state, node):
  page = enter(state, node)
  draw(page)
  assert 'Search' not in str(resolve(page._header.action.text))
  if isinstance(page, SettingsLeaf):
    assert all(r._c4_ref.id in ROUTES for r in page.ref_rows.values())
    for row in page._list.visible_items:
      page._list.focus_item(row)
      draw(page)
      assert row.rect.width >= 500
      assert row.rect.height >= 160
      assert str(resolve(row.title)).strip()


@pytest.mark.parametrize('brand', ['toyota', 'honda', 'hyundai', 'volkswagen', 'subaru', 'mazda', 'nissan', 'ford', 'tesla'])
def test_vehicle_and_longitudinal_conditions_refresh(state, brand):
  page = enter(state, 'vehicle')
  ui_state.CP = car.CarParams.new_message(brand=brand, carFingerprint='MOCK', openpilotLongitudinalControl=True)
  page.refresh()
  actual = {row._c4_ref.key for row in page.ref_rows.values() if row.is_visible and row._c4_ref.source == 'dp'}
  expected = {i['key'] for s in SETTINGS for i in s['settings'] if i.get('brands') == [brand] and s['title'] in ('Toyota / Lexus', 'Honda', 'VAG')}
  assert actual == expected
  cruise = enter(state, 'longitudinal')
  assert cruise.ref_rows
  ui_state.CP.openpilotLongitudinalControl = False
  cruise.refresh()
  assert not cruise.ref_rows


@pytest.mark.parametrize('key,node,value,expected', [
  ('dp_lat_offset_cm', 'lateral', '-7', -7),
  ('dp_lat_lca_speed', 'lane', '25', 25),
  ('dp_lat_lca_auto_sec', 'lane', '1.5', 1.5),
  ('dp_dev_delay_loggerd', 'logging', '15', 15),
])
def test_numeric_input_default_and_undo(state, key, node, value, expected):
  page = enter(state, node)
  editor = open_row(page, key)
  assert isinstance(editor, CompactNumberPage)
  before = ui_state.params.get(key)
  editor.submit_input(value)
  assert ui_state.params.get(key) == expected
  editor.undo()
  assert ui_state.params.get(key) == before
  editor.restore_default()
  assert ui_state.params.get(key) == ui_state.params.get_default_value(key)
  draw(editor)


def test_open_numeric_editor_respects_changed_prerequisite(state):
  page = enter(state, 'lane')
  editor = open_row(page, 'dp_lat_lca_auto_sec')
  assert isinstance(editor, CompactNumberPage)
  before = ui_state.params.get('dp_lat_lca_auto_sec')
  ui_state.params.put('dp_lat_lca_speed', 0, block=True)
  editor.submit_input('2')
  assert ui_state.params.get('dp_lat_lca_auto_sec') == before
  assert not editor.allowed()


def test_personality_and_dp_selectors_use_original_callbacks(state):
  page = enter(state, 'basic')
  editor = open_row(page, 'LongitudinalPersonality')
  assert isinstance(editor, CompactSelectPage)
  editor._rows[2].callback()
  assert ui_state.params.get('LongitudinalPersonality') == 2
  page = enter(state, 'visuals')
  editor = open_row(page, 'dp_ui_display_mode')
  editor._rows[1].callback()
  assert ui_state.params.get('dp_ui_display_mode') == 1


def test_adb_and_ssh_are_cards_with_state_guards(state):
  page = enter(state, 'remote')
  assert {r._c4_ref.key for r in page.ref_rows.values()} == {'adb', 'ssh', 'keys'}
  editor = open_row(page, 'adb')
  assert isinstance(editor, TogglePage)
  editor._toggle._click_callback()
  assert ui_state.params.get_bool('AdbEnabled')
  ui_state.started = True
  editor._toggle._click_callback()
  assert ui_state.params.get_bool('AdbEnabled')
  page = enter(state, 'remote')
  editor = open_row(page, 'ssh')
  editor._toggle._click_callback()
  assert ui_state.params.get_bool('SshEnabled')


def test_vehicle_selector_uses_compact_native_selection(state):
  ui_state.params.put('dp_dev_model_list', {'Toyota': ['Model A', 'Model B']}, block=True)
  page = enter(state, 'vehicle')
  dialog = open_row(page, 'vehicle')
  draw(dialog)
  assert dialog._compact_page is not None
  dialog._compact_select('Toyota')
  dialog = gui_app.get_active_widget()
  draw(dialog)
  dialog._compact_select('Model B')
  assert ui_state.params.get('dp_dev_model_selected', block=True) == 'Model B'
  assert ui_state.params.get_bool('OnroadCycleRequested')


def test_directory_favorites_and_reopen_start_at_first_menu(state):
  page = enter(state, 'lateral')
  row = row_for(page, 'dp_lat_offset_cm')
  state.toggle_favorite(row._c4_ref)
  assert row._c4_ref.id in ui_state.params.get('dp_ui_settings_favorites')
  state.open_favorites()
  favorite = gui_app.get_active_widget()
  favorite.buttons[0]._click_callback()
  page = gui_app.get_active_widget()
  assert page.node.key == 'lateral'
  assert page._list.visible_items[page._list.page]._c4_ref.key == 'dp_lat_offset_cm'
  page.open_directory()
  assert str(resolve(gui_app.get_active_widget()._header.title)).startswith(tr('Directory'))
  gui_app.pop_widgets_to(state, instant=True)
  state._list.page = 10
  state.open_from_home()
  assert state._list.page == 0
  assert all(p._list.page == 0 for p in state._pages.values())


def test_home_callback_and_native_confirmation(state):
  calls = []
  state.set_home_callback(lambda: calls.append('home'))
  state._header.action._click_callback()
  assert calls == ['home']
  page = enter(state, 'power')
  dialog = open_row(page, 'power')
  draw(dialog)
  assert dialog._compact_view is not None
  assert not ui_state.params.get_bool('DoReboot')


def test_swipe_changes_page_without_opening_card(state, monkeypatch):
  draw(state)
  buttons = state._list.visible_items
  start = rl.Vector2(400, 130)
  end = rl.Vector2(240, 130)
  events = [MouseEvent(start, 0, True, False, True, 1.0),
            MouseEvent(end, 0, False, True, False, 1.2)]
  monkeypatch.setattr(gui_app, '_mouse_events', events)
  draw(state)
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  for _ in range(100):
    draw(state)
  assert state._list.page == 1
  assert gui_app.get_active_widget() is state
  assert state._list.visible_items == buttons


@pytest.mark.parametrize('identifier', list(ROUTES))
def test_every_setting_editor_or_description(state, identifier):
  source, key, _ = identifier.split(':')
  if key.startswith('dp_toyota'):
    brand = 'toyota'
  elif key.startswith('dp_honda'):
    brand = 'honda'
  elif key.startswith('dp_vag'):
    brand = 'volkswagen'
  else:
    brand = 'toyota'
  ui_state.CP = car.CarParams.new_message(brand=brand, carFingerprint='MOCK', openpilotLongitudinalControl=True, alphaLongitudinalAvailable=True)
  ui_state.params.put_bool('UpdateAvailable', True, block=True)
  ui_state.started = key == 'onroad'
  page = enter(state, ROUTES[identifier])
  row = page.ref_rows[identifier]
  assert row.is_visible
  page._list.focus_item(row)
  draw(page)
  if source == 'dp' and key != 'btn_reset_dp_conf' or source == 'toggles' or source == 'developer' and key not in ('keys', 'errors'):
    row.callback()
  else:
    row.help_callback()
  editor = gui_app.get_active_widget()
  assert editor is not page
  draw(editor)
  action = editor._header.action
  assert action is None or str(resolve(action.text)) != tr('Search')
  if isinstance(editor, CompactNumberPage):
    assert editor.action.min_value <= editor.action.current_value <= editor.action.max_value
    assert editor.action.value_change_step > 0


def test_network_metering_keeps_enum_when_language_changes(state, monkeypatch):
  page = enter(state, 'wifi')
  controller = state.source('network')
  wm = controller.native._wifi_manager
  wm._wifi_state = WifiState(ssid='Example Wi-Fi')
  controller.native._network_metered_btn.set_enabled(True)
  calls = []
  monkeypatch.setattr(wm, 'set_current_network_metered', calls.append)
  editor = open_row(page, 'usage')
  assert isinstance(editor, CompactSelectPage)
  multilang._language = 'en'
  multilang.setup()
  editor._rows[2].callback()
  assert calls == [MeteredType.NO]


def test_desktop_dialogs_keep_the_large_display_renderer(state, monkeypatch):
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
  from openpilot.system.ui.widgets.html_render import HtmlModal
  monkeypatch.setattr(gui_app, 'big_ui', lambda: True)
  for dialog in (ConfirmDialog('Example', 'OK'), MultiOptionDialog('Example', ['A', 'B']), HtmlModal(text='Example')):
    draw(dialog)
    assert getattr(dialog, '_compact_view', getattr(dialog, '_compact_page', None)) is None


def test_main_screen_gear_and_home_return_to_the_first_menu(state, monkeypatch):
  from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
  from openpilot.selfdrive.ui.mici.layouts.onboarding import OnboardingWindow
  monkeypatch.setattr(OnboardingWindow, 'completed', property(lambda self: True))
  main = MiciMainLayout()
  draw(main)
  main._home_layout._on_settings_click()
  settings = main._settings_layout
  assert gui_app.get_active_widget() is settings
  settings._list.page = 10
  settings.open_menu('developer')
  settings.open_menu('remote')
  gui_app.pop_widgets_to(settings, instant=True)
  settings._header.action._click_callback()
  assert gui_app.get_active_widget() is main
  main._home_layout._on_settings_click()
  assert gui_app.get_active_widget() is settings
  assert settings._list.page == 0
  assert all(page._list.page == 0 for page in settings._pages.values())
  gui_app.remove_nav_stack_tick(main._handle_transitions)


def test_chinese_fonts_include_new_menus_and_vehicle_selector(state):
  gui_app.on_language_changed('zh-CHS')
  labels = [tr(n.title) for n in NODES.values()]
  labels += [tr(key) for key in ('Settings', 'On', 'Off', 'Select a Make', 'Select a Model', 'Directory', 'Favorites')]
  labels += ['★-·']
  for weight in (FontWeight.NORMAL, FontWeight.BOLD, FontWeight.ROMAN):
    font = gui_app.font(weight)
    glyphs = {font.glyphs[i].value for i in range(font.glyphCount)}
    missing = {c for text in labels for c in text if not c.isspace() and ord(c) not in glyphs}
    assert not missing, (weight, missing)
