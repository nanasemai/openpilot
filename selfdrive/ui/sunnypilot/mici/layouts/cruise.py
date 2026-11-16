"""Complete small-display cruise settings, sharing policy with the large display."""
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_controllers import CruiseController
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel
from openpilot.system.ui.lib.application import gui_app


class CruiseLayoutMici(SettingsPanel):
  def __init__(self, back_callback=None):
    super().__init__('Cruise', CruiseController())
    self._return_callback = back_callback or gui_app.pop_widget

  def go_back(self):
    if len(self._chain()) > 1:
      super().go_back()
    else:
      self._return_callback()
