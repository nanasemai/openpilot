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


class VisualsLayoutMici(Scroller):
  def __init__(self, back_callback=None):
    super().__init__(horizontal=False)
    self._back_callback = back_callback

    self._toggle_defs = {
      "BlindSpot": tr("show blind spot warnings"),
      "TorqueBar": tr("steering arc"),
      "RainbowMode": tr("enable tesla rainbow mode"),
      "StandstillTimer": tr("enable standstill timer"),
      "RoadNameToggle": tr("display road name"),
      "GreenLightAlert": tr("green traffic light alert (beta)"),
      "LeadDepartAlert": tr("lead departure alert (beta)"),
      "TrueVEgoUI": tr("speedometer: always display true speed"),
      "HideVEgoUI": tr("speedometer: hide from onroad screen"),
      "ShowTurnSignals": tr("display turn signals"),
      "RocketFuel": tr("real-time acceleration bar"),
    }

    self._toggles = {}
    widgets = []
    for param, title in self._toggle_defs.items():
      toggle = BigParamControl(title, param)
      self._toggles[param] = toggle
      widgets.append(toggle)

    self._scroller.add_widgets(widgets)

  def _render(self, _):
    rl.draw_rectangle(0, 0, int(gui_app.width), int(gui_app.height), rl.Color(30, 30, 30, 255))
    super()._render(_)