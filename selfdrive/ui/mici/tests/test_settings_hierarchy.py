"""Verify every shared control has a short route and safe large-touch navigation."""
import pytest

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import MENU_GROUPS
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_group import SettingsGroup, SettingsLeaf, SettingsDirectory
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_menu import NODES, PATHS, SETTING_ROUTES
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.factory import BrandSettingsFactory
from openpilot.selfdrive.ui.mici.tests.test_settings import state, window, draw  # noqa: F401
from openpilot.selfdrive.ui.mici.tests.test_settings_parity import home, isolated_network  # noqa: F401
from openpilot.selfdrive.ui.mici.tests.test_parameter_navigation import tap, horizontal_swipe, swipe
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.compact import resolve, CompactNumberPage
from openpilot.system.ui.widgets.list_view import DualButtonAction


@pytest.mark.parametrize('kind', [key for key, node in NODES.items() if node.children and key != 'root'])
def test_categories_use_one_large_card_per_swipe_and_drags_cannot_open_them(kind, monkeypatch):
  root = home()
  root.open_menu(kind)
  page = gui_app.get_active_widget()
  draw(page)
  assert isinstance(page, SettingsGroup)
  assert len(page.buttons) <= 4 and page._list.page_count == len(page.buttons)
  for index, button in enumerate(page.buttons):
    page._list.page = index
    draw(page)
    assert button.rect.width == 512 and button.rect.height == 164
  page._list.page = 0
  draw(page)
  horizontal_swipe(page, (480, 425, 250, 80, 80, 80), monkeypatch)
  assert gui_app.get_active_widget() is page and page._list.page == 1
  area = page.buttons[1].rect
  swipe(page, area.x + 30, (area.y + 30, area.y + 52, area.y + 30, area.y + 30), monkeypatch)
  assert gui_app.get_active_widget() is page
  tap(page, area, monkeypatch)
  child = gui_app.get_active_widget()
  assert child.kind == page.node.children[1].key
  gui_app.pop_widget()
  draw(page)
  assert gui_app.get_active_widget() is page and page._list.page == 1


@pytest.mark.parametrize('brand', list(BrandSettingsFactory._BRAND_MAP))
def test_every_c3x_source_row_has_exactly_one_short_leaf_for_each_brand(brand):
  ui_state.params.put('CarPlatformBundle', {'brand': brand, 'name': 'coverage'}, block=True)
  root = home()
  sources = {category: root.source_panel(category) for _, categories in MENU_GROUPS.values() for category in categories}
  expected = set()
  for category, panel in sources.items():
    panel._update_state()
    if hasattr(panel, '_source_items'):
      for item in panel._source_items:
        for index, row in enumerate(panel._rows[item]):
          if isinstance(item.action_item, DualButtonAction) and not str(resolve(row.title)) and not row.is_visible:
            continue
          expected.add((category, item, index))
    else:
      expected.update((category, row._c4_setting_id, 0) for row in panel._list.items)
  actual = []
  for node in NODES.values():
    if node.children:
      continue
    root.open_menu(node.key)
    page = gui_app.get_active_widget()
    assert len(page._ref_rows) <= 8, node.key
    assert len(PATHS[node.key]) <= 5
    for ref, row in page._ref_rows.items():
      category, item = page._row_sources[row]
      actual.append((category, item if item is not None else ref.selector[2:], ref.row))
      assert SETTING_ROUTES[ref.key] == node.key
    gui_app.pop_widget()
  assert len(actual) == len(set(actual))
  assert set(actual) == expected, (expected - set(actual), set(actual) - expected)


def test_directory_uses_one_card_per_swipe_and_jumps_to_exact_parameter(monkeypatch):
  root = home()
  root.open_setting('steering', 'TorqueParamsOverrideFriction')
  leaf = gui_app.get_active_widget()
  draw(leaf)
  assert isinstance(leaf, SettingsLeaf) and leaf.kind == 'torque'
  index = leaf._list.page
  tap(leaf, leaf._header.action._directory.rect, monkeypatch)
  directory = gui_app.get_active_widget()
  assert isinstance(directory, SettingsDirectory) and directory._list.page_count == 8
  assert directory._list.page == index
  assert directory.buttons[index].rect.height == 164
  directory._list.page = 1
  draw(directory)
  tap(directory, directory.buttons[1].rect, monkeypatch)
  assert gui_app.get_active_widget() is leaf
  assert leaf._list.page == 1
  assert leaf._list.visible_items[1] is list(leaf._ref_rows.values())[1]
  assert ui_state.params.get('TorqueControlTune') is None


def test_numeric_editor_and_directory_return_preserve_position(monkeypatch):
  root = home()
  root.open_setting('steering', 'LateralPositionOffset')
  leaf = gui_app.get_active_widget()
  draw(leaf)
  position = leaf._list.page
  tap(leaf, leaf._list.visible_items[position].rect, monkeypatch)
  assert isinstance(gui_app.get_active_widget(), CompactNumberPage)
  gui_app.pop_widget()
  draw(leaf)
  assert leaf._list.page == position
  leaf.open_directory()
  gui_app.pop_widget()
  draw(leaf)
  assert leaf._list.page == position


def test_shared_controller_ownership_and_stale_actions_cannot_escape_leaf():
  root = home()
  root.open_menu('power')
  power = gui_app.get_active_widget()
  panel = power.panels['device']
  action = next(row for ref, row in power._ref_rows.items() if ref.selector == 'a:_power_buttons')
  root.open_menu('use')
  use = gui_app.get_active_widget()
  assert use.panels['device'] is panel
  assert panel._navigation_owner is use
  root.open_search()
  assert panel._navigation_owner is None
  gui_app.pop_widget()
  assert panel._navigation_owner is use
  action.callback()
  assert gui_app.get_active_widget() is use
  assert ui_state.params.get('DoReboot') is None


def test_actions_and_native_network_options_are_searchable_in_chinese_and_english():
  root = home()
  root.open_search()
  search = gui_app.get_active_widget()
  for query, leaf in (('重启', 'power'), ('Reboot', 'power'), ('隐藏网络', 'wifi'),
                      ('Hidden Network', 'wifi'), ('TorqueControlTune', 'torque')):
    search.query = query
    search.refresh()
    matches = search.matching_entries()
    assert matches, query
    assert any(SETTING_ROUTES[entry[1]] == leaf for entry in matches)


@pytest.mark.parametrize('node', tuple(NODES.values()), ids=lambda node: node.key)
def test_all_new_menu_labels_have_chinese_and_font_glyphs(node):
  translated = tr(node.title)
  assert translated != node.title or node.title in ('ADB / SSH', 'sunnylink', 'OSM', 'Firehose')
  font = gui_app.font()
  glyphs = {font.glyphs[index].value for index in range(font.glyphCount)}
  assert all(char.isspace() or ord(char) in glyphs for char in translated)


def test_menu_labels_survive_translation_extraction():
  from pathlib import Path
  from openpilot.selfdrive.ui.translations.potools import extract_strings
  source = 'selfdrive/ui/sunnypilot/mici/layouts/settings_menu.py'
  entries = extract_strings([source], str(Path.cwd()))
  assert {node.title for node in NODES.values()} <= {entry.msgid for entry in entries}


def test_network_callbacks_live_through_subpages_and_stop_after_last_leaf(monkeypatch):
  root = home()
  root.open_menu('wifi')
  wifi = gui_app.get_active_widget()
  panel = wifi.panels['network']
  callback = panel.native._wifi_manager.process_callbacks
  assert gui_app._nav_stack_ticks.count(callback) == 1
  root.open_menu('cellular')
  cellular = gui_app.get_active_widget()
  assert cellular.panels['network'] is panel
  assert gui_app._nav_stack_ticks.count(callback) == 1
  gui_app.pop_widget()
  assert panel._navigation_owner is wifi
  assert gui_app._nav_stack_ticks.count(callback) == 1
  gui_app.pop_widget()
  assert callback not in gui_app._nav_stack_ticks


def test_each_system_log_action_can_be_favorited_without_running_it(monkeypatch):
  root = home()
  root.open_menu('logs')
  leaf = gui_app.get_active_widget()
  refs = [ref for ref in leaf._ref_rows if ref.selector == 'a:system_logs_item']
  assert len(refs) == 2
  for ref in refs:
    row = leaf._ref_rows[ref]
    leaf._list.focus_item(row)
    draw(leaf)
    tap(leaf, row._info.rect, monkeypatch)
    info = gui_app.get_active_widget()
    tap(info, info._header.action.rect, monkeypatch)
    assert root._favorites.contains(ref.key)
    gui_app.pop_widget()
  assert set(root._favorites.read()) == {ref.key for ref in refs}
  assert not leaf.panels['developer'].controller._log_running
  assert not leaf.panels['developer'].controller._format_running
