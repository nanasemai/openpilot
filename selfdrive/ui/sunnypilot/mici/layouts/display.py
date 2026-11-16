"""Brightness, time and display timeout controls for the small display."""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.display import DisplayLayout
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel
from openpilot.system.ui.lib.application import gui_app


class DisplayLayoutMici(SettingsPanel):
  def __init__(self, back_callback=None):
    super().__init__('Display', DisplayLayout())
    self._return_callback = back_callback or gui_app.pop_widget

  def go_back(self):
    self._return_callback()
