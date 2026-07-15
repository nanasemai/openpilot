"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.system.ui.widgets.scroller import Scroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigToggle
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
import pyray as rl


class DisplayLayoutMici(Scroller):
  def __init__(self, back_callback=None):
    super().__init__(horizontal=False)
    self._back_callback = back_callback

    self._onroad_brightness = BigParamControl(tr("onroad brightness"), "OnroadScreenOffBrightness")
    self._interactivity_timeout = BigParamControl(tr("interactivity timeout"), "InteractivityTimeout")

    self._scroller.add_widgets([
      self._onroad_brightness,
      self._interactivity_timeout,
    ])

  def _render(self, _):
    rl.draw_rectangle(0, 0, int(gui_app.width), int(gui_app.height), rl.Color(30, 30, 30, 255))
    super()._render(_)