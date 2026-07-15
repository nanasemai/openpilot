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


class SteeringLayoutMici(Scroller):
  def __init__(self, back_callback=None):
    super().__init__(horizontal=False)
    self._back_callback = back_callback

    self._mads_toggle = BigParamControl(tr("modular assistive driving system (MADS)"), "Mads")
    self._blinker_pause_toggle = BigParamControl(tr("pause lateral control with blinker"), "BlinkerPauseLateralControl")
    self._enforce_torque_toggle = BigParamControl(tr("enforce torque lateral control"), "EnforceTorqueControl")
    self._nnlc_toggle = BigParamControl(tr("neural network lateral control (NNLC)"), "NeuralNetworkLateralControl")
    self._blindspot_toggle = BigParamControl(tr("show blind spot warnings"), "BlindSpot")
    self._lane_position_toggle = BigParamControl(tr("lane position offset"), "LateralPositionOffset")

    self._scroller.add_widgets([
      self._mads_toggle,
      self._blinker_pause_toggle,
      self._enforce_torque_toggle,
      self._nnlc_toggle,
      self._blindspot_toggle,
      self._lane_position_toggle,
    ])

  def _render(self, _):
    rl.draw_rectangle(0, 0, int(gui_app.width), int(gui_app.height), rl.Color(30, 30, 30, 255))
    super()._render(_)