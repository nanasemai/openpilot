"""Render every C3 settings page after shared controller and widget changes."""
import pyray as rl
import pytest
import requests

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import multilang
from openpilot.system.ui.lib.wifi_manager import WifiManager
from openpilot.system.ui.widgets.compact import CompactPage


@pytest.mark.skipif(not gui_app.big_ui(), reason='Run with BIG=1 to check the C3 viewport')
def test_c3_settings_all_15_pages_render(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.settings import SettingsLayoutSP
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.trips import TripsLayout
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import TITLES

  monkeypatch.setattr(ui_state, 'params', Params())
  monkeypatch.setattr(ui_state, 'started', False)
  monkeypatch.setattr(ui_state, 'CP', None)
  monkeypatch.setattr(ui_state, 'CP_SP', None)
  monkeypatch.setattr(ui_state, 'has_longitudinal_control', False)
  monkeypatch.setattr(ui_state, '_enforce_constraints', lambda: None)
  monkeypatch.setattr(ui_state, '_offroad_transition_callbacks', [])
  monkeypatch.setattr(gui_app, 'sunnypilot_ui', lambda: True)
  monkeypatch.setattr(gui_app, '_mouse_events', [])
  monkeypatch.setattr(WifiManager, '_initialize', lambda self: None)
  monkeypatch.setattr(TripsLayout, '_update_loop', lambda self: None)

  def offline(*args, **kwargs):
    raise requests.ConnectionError('Controlled offline settings render')
  monkeypatch.setattr(requests, 'request', offline)
  monkeypatch.setattr(requests.Session, 'request', offline)
  ui_state.params.put_bool('ShowAdvancedControls', True, block=True)
  multilang._language = 'zh-CHS'
  multilang.setup()
  gui_app.init_window('C3 settings regression')
  gui_app._nav_stack.clear()
  gui_app.push_widget(CompactPage('root'))
  try:
    settings = SettingsLayoutSP()
    gui_app.push_widget(settings)
    assert {panel.name.lower() for panel in settings._panels} == set(TITLES)

    def render_settings():
      for _ in range(4):
        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        rl.rl_push_matrix()
        rl.rl_scalef(gui_app._scale, gui_app._scale, 1)
        settings.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
        rl.rl_pop_matrix()
        rl.end_drawing()

    for panel_type, info in settings._panels.items():
      settings.set_current_panel(panel_type)
      render_settings()
      assert info.instance.rect.width > 536
      assert info.instance.rect.height > 240

    # These shared subpages contain the numeric labels changed for C4.
    for name, child_name, child_attr in [('Steering', 'TORQUE_CONTROL', '_torque_control_layout'),
                                       ('Cruise', 'SLA', '_speed_limit_layout')]:
      panel_type, info = next((key, info) for key, info in settings._panels.items() if info.name == name)
      ui_state.params.put_bool('CustomTorqueParams', True, block=True)
      ui_state.params.put('SpeedLimitOffsetType', 1, block=True)
      settings.set_current_panel(panel_type)
      info.instance._set_current_panel(getattr(type(info.instance._current_panel), child_name))
      render_settings()
      child = getattr(info.instance, child_attr)
      assert child.rect.width > 536
      assert child.rect.height > 240
      if name == 'Cruise':
        assert child._speed_limit_value_offset.is_visible
        assert child._speed_limit_value_offset.title == multilang.tr('Speed Limit Offset Value')
  finally:
    while len(gui_app._nav_stack) > 1:
      gui_app.pop_widget()
    gui_app.close()
