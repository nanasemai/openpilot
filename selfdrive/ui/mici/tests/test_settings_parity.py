"""Compare the small-screen adapter against the registered C3X settings and all brands."""
import ast
import importlib
from pathlib import Path

import pytest

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP, MENU_ORDER, MENU_GROUPS, TITLES
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ParameterSearch, parameter_key
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_group import SettingsGroup, SettingsLeaf
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.factory import BrandSettingsFactory
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_menu import NODES, PATHS
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
               tuple((action.value_map or {}).items()), action.params.get_default_value(action.param_key))
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


def test_every_registered_c3x_destination_has_its_own_home_menu():
  page = home()
  assert len(registered_controllers()) == 15
  categories = [category for _, members in MENU_GROUPS.values() for category in members]
  assert len(categories) == len(set(categories)) == 15
  assert set(registered_controllers()) == set(categories)
  assert page.menu_keys == ('toggles', 'steering', 'cruise', 'vehicle', 'models', 'device', 'network', 'sunnylink',
                            'software', 'visuals', 'display', 'osm', 'trips', 'firehose', 'developer')
  assert tuple(node.key for node in NODES['root'].children) == page.menu_keys
  assert [str(resolve(button.title)) for button in page.buttons] == [tr(TITLES[key]) for key in page.menu_keys]
  assert len(page.buttons) == 15
  for node in NODES.values():
    for ref in node.items:
      assert PATHS[node.key][1] == ref.category


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
  assert page.kind == kind
  if NODES[kind].children:
    assert isinstance(page, SettingsGroup)
    assert [str(resolve(button.title)) for button in page.buttons] == [tr(child.title) for child in NODES[kind].children]
    assert len(page.buttons) == len(NODES[kind].children)
  else:
    assert isinstance(page, SettingsLeaf)
    assert set(page.panels) == {kind}
  gui_app.pop_widget()
  draw(root)
  assert gui_app.get_active_widget() is root
  assert root._list.page == index

  # Entering settings again from home starts at the first category.
  tap(root, root._header._back.rect, monkeypatch)
  assert not gui_app.widget_in_stack(root)
  gui_app.push_widget(root)
  draw(root)
  assert gui_app.get_active_widget() is root
  assert root._list.page == 0


@pytest.mark.parametrize('nested', [False, True])
def test_home_gear_reopens_settings_at_first_menu(nested, monkeypatch):
  from types import SimpleNamespace
  import pyray as rl
  from openpilot.selfdrive.ui.mici.layouts.home import MiciHomeLayout
  from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
  from openpilot.selfdrive.ui.ui_state import device
  from openpilot.system.ui.widgets.compact import CompactPage

  home_widget = MiciHomeLayout()
  gui_app.push_widget(home_widget)
  settings = home()
  main = SimpleNamespace(
    _home_layout=home_widget, _settings_layout=settings,
    _alerts_layout=SimpleNamespace(active_alerts=lambda: 0, max_severity=lambda: 0),
    _car_onroad_layout=CompactPage('onroad'), _body_onroad_layout=CompactPage('body'),
    _scroll_to=lambda widget: None, _on_interactive_timeout=lambda: None, _on_body_changed=lambda: None,
  )
  monkeypatch.setattr(device, 'add_interactive_timeout_callback', lambda callback: None)
  monkeypatch.setattr(ui_state, 'add_on_body_changed_callbacks', lambda callback: None)
  MiciMainLayout._setup_callbacks(main)
  settings._list.page = len(settings.menu_keys) - 1
  if nested:
    settings.open_setting('steering', 'LateralPositionOffset')
  gui_app.pop_widgets_to(home_widget, instant=True)
  draw(home_widget)
  tap(home_widget, rl.Rectangle(32, 192, 48, 48), monkeypatch)
  assert gui_app.get_active_widget() is settings
  assert settings._list.page == 0
  assert settings._list.visible_items[0] is settings.buttons[0]


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


def test_favorites_from_steering_open_the_existing_category(monkeypatch):
  root = home()
  root._favorites.toggle('TorqueParamsOverrideFriction')
  root.open_group('steering')
  group = gui_app.get_active_widget()
  draw(group)
  tap(group, group._header.action._favorites.rect, monkeypatch)
  search = gui_app.get_active_widget()
  assert isinstance(search, ParameterSearch)
  search.query = 'TorqueParamsOverrideFriction'
  search.refresh()
  entries = search.matching_entries()
  assert len(entries) == 1 and entries[0][0] == 'steering'
  search.open_result(entries[0])
  page = gui_app.get_active_widget()
  assert isinstance(page, SettingsLeaf) and page.kind == 'torque'
  draw(page)
  row = page._list.visible_items[page._list.page]
  category, item = page._row_sources[row]
  assert category == 'steering' and parameter_key(item) == 'TorqueParamsOverrideFriction'


def test_favorites_from_group_establish_parent_path_and_focus_exact_leaf(monkeypatch):
  root = home()
  root._favorites.toggle('SpeedLimitMode')
  root.open_group('cruise')
  group = gui_app.get_active_widget()
  draw(group)
  tap(group, group._header.action._favorites.rect, monkeypatch)
  search = gui_app.get_active_widget()
  search.query = 'SpeedLimitMode'
  search.refresh()
  search.open_result(search.matching_entries()[0])
  page = gui_app.get_active_widget()
  assert isinstance(page, SettingsLeaf) and page.kind == 'speed_limit'
  assert gui_app._nav_stack.count(group) == 1
  assert [widget.kind for widget in gui_app._nav_stack if isinstance(widget, (SettingsGroup, SettingsLeaf))] == list(PATHS[page.kind][1:])
  draw(page)
  category, item = page._row_sources[page._list.visible_items[page._list.page]]
  assert category == 'cruise' and parameter_key(item) == 'SpeedLimitMode'
  assert not gui_app.widget_in_stack(search)


def test_favorites_shortcut_reuses_the_list_already_below_another_group(monkeypatch):
  root = home()
  root._favorites.toggle('LateralPositionOffset')
  root.open_search()
  search = gui_app.get_active_widget()
  search.query = 'LateralPositionOffset'
  search.refresh()
  search.open_result(search.matching_entries()[0])
  group = gui_app.get_active_widget()
  draw(group)
  tap(group, group._header.action._favorites.rect, monkeypatch)
  assert gui_app.get_active_widget() is search
  assert gui_app._nav_stack.count(search) == 1


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
  reachable = set()
  for node in NODES.values():
    if any(ref.category == kind for ref in node.items):
      root.open_menu(node.key)
      page = gui_app.get_active_widget()
      reachable.update(signature(item) for (category, item), rows in page._rows.items() if category == kind and rows)
      gui_app.pop_widget()
  assert expected <= reachable, expected - reachable



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
  root.open_menu('vehicle')
  group = gui_app.get_active_widget()
  assert expected <= {signature(item) for (category, item), rows in group._rows.items() if category == 'vehicle' and rows}


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
@pytest.mark.parametrize('grouped', [False, True])
def test_hidden_wifi_connect_and_cancel_preserve_c3x_behavior(password, grouped, monkeypatch):
  root = home()
  root.open_menu('wifi') if grouped else root.open_panel('network')
  page = gui_app.get_active_widget()
  panel = page.panels['network'] if grouped else page
  calls = []
  monkeypatch.setattr(panel.native._wifi_manager, 'connect_to_network', lambda *args, **kwargs: calls.append((args, kwargs)))
  hidden = next(row for row in page._list.items if resolve(row.title) == tr('Hidden Network'))
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


@pytest.mark.parametrize('grouped', [False, True])
def test_network_browse_and_swipe_require_large_editor_to_change_roaming(grouped, monkeypatch):
  from openpilot.selfdrive.ui.lib.prime_state import PrimeType
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.network import NetworkTogglePage
  monkeypatch.setattr(ui_state.prime_state, 'get_type', lambda: PrimeType.NONE)
  root = home()
  root.open_menu('cellular') if grouped else root.open_panel('network')
  panel = gui_app.get_active_widget()
  row = panel._list.items[0 if grouped else 5]
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


def test_grouped_actions_execute_with_the_original_confirmation_and_reject_stale_callbacks(monkeypatch):
  from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
  root = home()
  root.open_menu('power')
  group = gui_app.get_active_widget()
  item = group.panels['device'].controller._power_buttons
  row = group._rows['device', item][0]
  group._list.focus_item(row)
  draw(group)
  tap(group, row.rect, monkeypatch)
  dialog = gui_app.get_active_widget()
  assert isinstance(dialog, ConfirmDialog)
  assert ui_state.params.get('DoReboot') is None
  dialog._cancel_button_callback()
  draw(group)
  assert group._list.visible_items[group._list.page] is row
  gui_app.pop_widget()
  row.callback()
  assert gui_app.get_active_widget() is root
  assert ui_state.params.get('DoReboot') is None


def test_grouped_parameter_taps_and_swipes_keep_large_editors_and_return_position(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ParameterTogglePage
  ui_state.params.put_bool('Mads', True, block=True)
  root = home()
  root.open_setting('steering', 'Mads')
  group = gui_app.get_active_widget()
  draw(group)
  row = group._list.visible_items[group._list.page]
  position = group._list.page
  horizontal_swipe(group, (480, 425, 250, 80, 80, 80), monkeypatch)
  assert gui_app.get_active_widget() is group
  assert ui_state.params.get_bool('Mads')
  group._list.focus_item(row)
  draw(group)
  tap(group, row.rect, monkeypatch)
  detail = gui_app.get_active_widget()
  assert isinstance(detail, ParameterTogglePage)
  assert ui_state.params.get_bool('Mads')
  tap(detail, detail._toggle.rect, monkeypatch)
  assert not ui_state.params.get_bool('Mads')
  gui_app.pop_widget()
  draw(group)
  assert group._list.page == position
  root.open_setting('cruise', 'SpeedLimitMode')
  page = gui_app.get_active_widget()
  draw(page)
  assert tr('Speed Limit Settings') == str(resolve(page._header.title))
  assert page._row_sources[page._list.visible_items[page._list.page]][0] == 'cruise'


@pytest.mark.parametrize('kind', ('wifi', 'hotspot', 'cellular', 'trips', 'firehose_stats', 'firehose_help'))
def test_native_controls_are_preserved_in_short_categorized_lists(kind):
  root = home()
  root.open_menu(kind)
  page = gui_app.get_active_widget()
  assert len(page._list.items) <= 8
  category = NODES[kind].items[0].category
  original = {row._c4_setting_id: row for row in page.panels[category]._list.items}
  for ref, row in page._ref_rows.items():
    assert str(resolve(row.title)) == str(resolve(original[ref.selector[2:]].title))
    page._list.focus_item(row)
    draw(page)
    assert row.rect.width >= 500 and row.rect.height == 164


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
    actual = {entry[1] for entry in search._entries if entry[0] == 'vehicle' and not entry[1].startswith('c4:')}
    assert expected and expected == actual
    assert not (previous - expected) & actual
    previous = expected


@pytest.mark.parametrize('text', ['Home', 'Swipe left or right', 'About sunnylink', 'Enable Show Advanced Controls first.',
                                 'Unavailable on this software branch.', 'Driving Assistance', 'Vehicle & Models',
                                 'Network & Connections', 'Software & Debugging', 'Wi-Fi · Remote Access · Maps · Uploads'])
def test_new_labels_have_chinese_translation_and_font_glyphs(text):
  translated = tr(text)
  assert translated != text
  font = gui_app.font()
  glyphs = {font.glyphs[index].value for index in range(font.glyphCount)}
  assert all(char.isspace() or ord(char) in glyphs for char in translated)
