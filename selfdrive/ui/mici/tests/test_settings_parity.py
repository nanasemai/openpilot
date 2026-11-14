"""Compare the small-screen adapter against the registered C3X settings and all brands."""
import ast
import importlib
from pathlib import Path

import pytest

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP, MENU_ORDER
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ParameterPanel, ParameterSearch, parameter_key
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.factory import BrandSettingsFactory
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wifi_manager import WifiManager
from openpilot.system.ui.widgets.compact import CompactInfoPage, resolve
from openpilot.system.ui.widgets.list_view import ListItem, ToggleAction, MultipleButtonAction, DualButtonAction
from openpilot.system.ui.sunnypilot.widgets.option_control import OptionControlSP
from openpilot.selfdrive.ui.mici.tests.test_settings import state, window, draw  # noqa: F401
from openpilot.selfdrive.ui.mici.tests.test_parameter_navigation import horizontal_swipe, swipe, tap

REFERENCE = Path(__file__).resolve().parents[2] / 'sunnypilot/layouts/settings/settings.py'


def registered_controllers():
  """Read the actual C3X registration without constructing its full-screen navigation."""
  tree = ast.parse(REFERENCE.read_text())
  imports = {name.asname or name.name: (node.module, name.name) for node in tree.body if isinstance(node, ast.ImportFrom)
             for name in node.names}
  registration = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign) and
                      any(isinstance(target, ast.Attribute) and target.attr == '_panels' for target in node.targets))
  return {key.attr.lower(): imports[value.args[1].func.id] for key, value in zip(registration.keys, registration.values, strict=True)}


def signature(item):
  action = item.action_item
  options = ()
  if isinstance(action, MultipleButtonAction):
    options = tuple(tr(str(resolve(label))) for label in action.buttons)
  elif isinstance(action, OptionControlSP):
    options = (action.param_key, action.min_value, action.max_value, action.value_change_step, action.use_float_scaling,
               tuple((action.value_map or {}).items()))
  elif isinstance(action, DualButtonAction):
    options = tuple(tr(str(resolve(button._label._text))) for button in (action.left_button, action.right_button))
  return type(action).__name__, item.title, options


def children(controller):
  yield controller
  for attribute in ('_mads_settings_layout', '_lane_change_settings_layout', '_torque_control_layout', '_speed_limit_layout', '_policy_layout'):
    if child := getattr(controller, attribute, None):
      yield from children(child)


@pytest.fixture(autouse=True)
def isolated_network(monkeypatch):
  monkeypatch.setattr(WifiManager, 'set_ipv4_forward', lambda *_: None)
  monkeypatch.setattr(WifiManager, 'set_active', lambda *_: None)


def home():
  page = SettingsLayoutSP()
  gui_app.push_widget(page)
  draw(page)
  return page


def test_every_registered_c3x_destination_is_on_home():
  page = home()
  assert len(registered_controllers()) == 15
  assert tuple(registered_controllers()) == page.menu_keys
  assert len(page.buttons) == 15


@pytest.mark.parametrize('kind', MENU_ORDER)
def test_c3x_category_touch_opens_secondary_settings_and_remembers_menu_page(kind, monkeypatch):
  root = home()
  root.focus_category(kind)
  draw(root)
  index = root.menu_keys.index(kind)
  assert root._list.page == index
  button = root.buttons[index]
  assert button.rect.width >= 500 and button.rect.height == 164
  tap(root, button.rect, monkeypatch)
  page = gui_app.get_active_widget()
  assert page is not root
  assert page._list.horizontal
  if kind not in ('network', 'trips', 'firehose'):
    assert isinstance(page, ParameterPanel) and page.kind == kind
  gui_app.pop_widget()
  draw(root)
  assert gui_app.get_active_widget() is root
  assert root._list.page == index


def test_steering_subsections_stay_in_the_secondary_page_with_c3x_order():
  root = home()
  root.open_more_panel('steering')
  panel = gui_app.get_active_widget()
  controller = panel.controller
  expected = []
  for item in controller._scroller._items:
    if item in panel._child_panels:
      expected.extend(child for child in panel._child_panels[item]._scroller._items if isinstance(child, ListItem))
    elif isinstance(item, ListItem):
      expected.append(item)
  assert panel._source_items == expected
  assert 'lane' not in root.menu_keys and 'torque' not in root.menu_keys
  for key, section in (('MadsSteeringMode', 'Customize MADS'), ('AutoLaneChangeTimer', 'Lane Change'),
                       ('TorqueParamsOverrideFriction', 'Torque Parameters')):
    panel.focus_parameter(key)
    draw(panel)
    assert tr(section) in str(resolve(panel._header.title))
    assert any(parameter_key(item) == key for item in panel._source_items)


def test_home_search_is_a_direct_shortcut_and_opens_the_existing_category(monkeypatch):
  root = home()
  tap(root, root._header.action._search.rect, monkeypatch)
  search = gui_app.get_active_widget()
  assert isinstance(search, ParameterSearch)
  search.query = 'TorqueParamsOverrideFriction'
  search.refresh()
  entries = search.matching_entries()
  assert len(entries) == 1 and entries[0][0] == 'steering'
  search.open_result(entries[0])
  page = gui_app.get_active_widget()
  assert isinstance(page, ParameterPanel) and page.kind == 'steering'


def test_offroad_mode_stays_in_device_settings_and_search():
  root = home()
  root.open_more_panel('device')
  panel = gui_app.get_active_widget()
  assert panel._rows[panel.controller._always_offroad_btn][0].is_visible
  root.open_search()
  search = gui_app.get_active_widget()
  search.query = 'OffroadMode'
  assert [(entry[0], entry[1]) for entry in search.matching_entries()] == [('device', 'OffroadMode')]


@pytest.mark.parametrize('kind', ['device', 'sunnylink', 'toggles', 'software', 'models', 'steering', 'cruise', 'visuals', 'display', 'osm', 'developer'])
def test_c3x_settings_actions_options_and_ranges_are_preserved(kind):
  module, name = registered_controllers()[kind]
  reference = getattr(importlib.import_module(module), name)()
  for controller in children(reference):
    controller._update_state()
  root = home()
  panels = [root.parameter_panel(key) for key in (('steering', 'lane', 'torque') if kind == 'steering' else (kind,))]
  for panel in panels:
    panel.refresh()
  adapted = {signature(item) for panel in panels for item in panel._source_items}
  excluded = set().union(*(panel._excluded for panel in panels))
  # Submenu buttons are replaced by direct home destinations; their child controls must match.
  submenu_titles = {item.title for item in excluded}
  expected = {signature(item) for controller in children(reference) for item in controller._scroller._items
              if isinstance(item, ListItem) and item.title not in submenu_titles}
  assert expected <= adapted, expected - adapted
  for panel in panels:
    for item in panel._source_items:
      assert panel._rows[item], item.title
      if isinstance(item.action_item, (ToggleAction, MultipleButtonAction, OptionControlSP)):
        assert all(row.is_visible for row in panel._rows[item]), item.title


@pytest.mark.parametrize('brand', list(BrandSettingsFactory._BRAND_MAP))
def test_all_c3x_vehicle_brand_controls_and_options_remain_available(brand):
  ui_state.params.put('CarPlatformBundle', {'brand': brand, 'name': 'parity-test'}, block=True)
  reference = BrandSettingsFactory.create_brand_settings(brand)
  root = home()
  panel = root.parameter_panel('vehicle')
  panel.refresh()
  expected = {signature(item) for item in reference.items if isinstance(item, ListItem)}
  actual = {signature(item) for item in panel._source_items}
  assert expected <= actual, expected - actual
  assert all(panel._rows[item] for item in panel._source_items)
  assert all(parameter_key(item) for item in panel._source_items if isinstance(item.action_item, (ToggleAction, MultipleButtonAction, OptionControlSP)))


def test_advanced_controls_are_discoverable_with_prerequisite_explanations():
  ui_state.params.put_bool('ShowAdvancedControls', False, block=True)
  root = home()
  for kind, keys in (('software', ('DisableUpdates',)), ('developer', ('QuickBootToggle', 'EnableCopyparty', 'EnableGithubRunner'))):
    panel = root.parameter_panel(kind)
    panel.refresh()
    for key in keys:
      item = next(item for item in panel._source_items if parameter_key(item) == key)
      assert panel._rows[item][0].is_visible
      if not panel._item_available(item):
        assert panel._unavailable_reason(item)
  root.open_search()
  search = gui_app.get_active_widget()
  search.query = 'DisableUpdates'
  assert [entry[1] for entry in search.matching_entries()] == ['DisableUpdates']


@pytest.mark.parametrize('password', ['', 'hidden-password'])
def test_hidden_wifi_connect_and_cancel_preserve_c3x_behavior(password, monkeypatch):
  root = home()
  root.open_panel('network')
  panel = gui_app.get_active_widget()
  calls = []
  monkeypatch.setattr(panel.native._wifi_manager, 'connect_to_network', lambda *args, **kwargs: calls.append((args, kwargs)))
  hidden = next(row for row in panel._list.items if resolve(row.title) == tr('Hidden Network'))
  hidden.callback()
  gui_app.pop_widget()
  assert calls == []
  hidden.callback()
  ssid = gui_app.get_active_widget()
  ssid._keyboard.set_text('Hidden AP')
  monkeypatch.setattr(ssid, 'dismiss', lambda callback: (gui_app.pop_widget(), callback()))
  ssid._confirm_callback()
  gui_app.pop_widget()
  assert calls == []
  hidden.callback()
  ssid = gui_app.get_active_widget()
  ssid._keyboard.set_text('Hidden AP')
  monkeypatch.setattr(ssid, 'dismiss', lambda callback: (gui_app.pop_widget(), callback()))
  ssid._confirm_callback()
  dialog = gui_app.get_active_widget()
  dialog._keyboard.set_text(password)
  monkeypatch.setattr(dialog, 'dismiss', lambda callback: (gui_app.pop_widget(), callback()))
  dialog._confirm_callback()
  assert calls == [(('Hidden AP', password), {'hidden': True})]


def test_network_browse_and_swipe_require_large_editor_to_change_roaming(monkeypatch):
  from openpilot.selfdrive.ui.lib.prime_state import PrimeType
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.network import NetworkTogglePage
  monkeypatch.setattr(ui_state.prime_state, 'get_type', lambda: PrimeType.NONE)
  root = home()
  root.open_panel('network')
  panel = gui_app.get_active_widget()
  row = panel._list.items[5]
  panel._list.focus_item(row)
  draw(panel)
  before = ui_state.params.get_bool('GsmRoaming')
  horizontal_swipe(panel, (480, 425, 250, 80, 80, 80), monkeypatch)
  assert gui_app.get_active_widget() is panel
  assert ui_state.params.get_bool('GsmRoaming') == before
  panel._list.focus_item(row)
  draw(panel)
  tap(panel, row.rect, monkeypatch)
  detail = gui_app.get_active_widget()
  assert isinstance(detail, NetworkTogglePage)
  assert detail._toggle.rect.width >= 480 and detail._toggle.rect.height >= 88
  assert ui_state.params.get_bool('GsmRoaming') == before
  tap(detail, detail._toggle.rect, monkeypatch)
  assert ui_state.params.get_bool('GsmRoaming') != before


def test_cellular_options_remain_visible_when_subscription_disallows_editing(monkeypatch):
  from openpilot.selfdrive.ui.lib.prime_state import PrimeType
  monkeypatch.setattr(ui_state.prime_state, 'get_type', lambda: PrimeType.MAGENTA)
  root = home()
  root.open_panel('network')
  panel = gui_app.get_active_widget()
  draw(panel)
  for index in (5, 6, 7):
    row = panel._list.items[index]
    assert row.is_visible and not resolve(row.available)
    row.help_callback()
    assert isinstance(gui_app.get_active_widget(), CompactInfoPage)
    gui_app.pop_widget()


def test_network_contains_every_c3x_advanced_setting_and_wifi_metered_choices():
  root = home()
  root.open_panel('network')
  panel = gui_app.get_active_widget()
  labels = {str(resolve(row.title)) for row in panel._list.items}
  assert {tr(text) for text in ('enable tethering', 'tethering password', 'enable roaming', 'apn settings',
                              'cellular metered', 'network usage', 'Hidden Network')} <= labels
  assert panel.native._roaming_btn.param == 'GsmRoaming'
  assert panel.native._cellular_metered_btn.param == 'GsmMetered'


def test_sunnylink_introduction_and_complete_consent_are_accessible():
  root = home()
  root.open_parameters('sunnylink')
  panel = gui_app.get_active_widget()
  panel._rows[panel.controller._intro_item][0].callback()
  info = gui_app.get_active_widget()
  assert isinstance(info, CompactInfoPage)
  text = str(resolve(info._list._scroller.items[0].text))
  assert tr("Sponsorship isn't required for basic backup/restore") in text
  gui_app.pop_widget()
  panel._toggle(panel.controller._sunnylink_toggle)
  consent = gui_app.get_active_widget()
  draw(consent)
  text = str(resolve(consent._compact_view._list._scroller.items[0].text))
  assert '远程监控' in text and '实时仪表盘' in text
  assert consent._compact_view._list._scroller.content_size > consent._compact_view._list.rect.height
  consent._cancel_button_callback()
  assert not ui_state.params.get_bool('SunnylinkEnabled')
  assert ui_state.params.get('CompletedSunnylinkConsentVersion') is None


def test_actions_keep_separate_description_access_before_execution(monkeypatch):
  root = home()
  root.open_parameters('device')
  panel = gui_app.get_active_widget()
  row = panel._rows[panel.controller._reset_calib_btn][0]
  panel._list.focus_item(row)
  draw(panel)
  tap(panel, row._info.rect, monkeypatch)
  assert isinstance(gui_app.get_active_widget(), CompactInfoPage)
  assert ui_state.params.get('OnroadCycleRequested') is None


def test_category_button_drags_cannot_open_a_menu(monkeypatch):
  root = home()
  area = root.buttons[0].rect
  x, y = area.x + area.width / 2, area.y + area.height / 2
  swipe(root, x, (y, y + 22, y, y), monkeypatch)
  assert gui_app.get_active_widget() is root
  horizontal_swipe(root, (x, x + 22, x, x), monkeypatch)
  assert gui_app.get_active_widget() is root
  assert root._list.page == 0


def test_search_focus_on_first_visit_opens_exact_parameter():
  root = home()
  root.open_parameters('display', 'OnroadScreenOffBrightness')
  panel = gui_app.get_active_widget()
  draw(panel)
  item = next(item for item in panel._source_items if parameter_key(item) == 'OnroadScreenOffBrightness')
  row = panel._rows[item][0]
  assert panel._list.visible_items[panel._list.page] is row
  assert row.rect.x == 12 and row.rect.y == 56


def test_parameter_search_updates_after_vehicle_brand_changes():
  root = home()
  root.open_search()
  search = gui_app.get_active_widget()
  previous = set()
  for brand in ('toyota', 'subaru'):
    ui_state.params.put('CarPlatformBundle', {'brand': brand, 'name': 'search-test'}, block=True)
    search.refresh()
    vehicle = root.parameter_panel('vehicle')
    expected = {parameter_key(item) for item in vehicle._source_items if parameter_key(item)}
    actual = {entry[1] for entry in search._entries if entry[0] == 'vehicle'}
    assert expected and expected == actual
    assert not (previous - expected) & actual
    previous = expected


@pytest.mark.parametrize('text', ['Swipe left or right', 'About sunnylink', 'Enable Show Advanced Controls first.',
                                 'Unavailable on this software branch.'])
def test_new_labels_have_chinese_translation_and_font_glyphs(text):
  translated = tr(text)
  assert translated != text
  font = gui_app.font()
  glyphs = {font.glyphs[index].value for index in range(font.glyphCount)}
  assert all(char.isspace() or ord(char) in glyphs for char in translated)
