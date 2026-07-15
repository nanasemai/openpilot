"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl
from openpilot.system.ui.lib.multilang import tr


class SteeringLayoutMici(NavScroller):
  def __init__(self, back_callback=None):
    super().__init__()
    self._back_callback = back_callback
    # Switch to vertical layout after init (bypasses NavWidget MRO issue)
    self._scroller._horizontal = False
    self._scroller.scroll_panel._horizontal = False

    self._mads_toggle = BigParamControl(tr("modular assistive driving system (MADS)"), "Mads")
    self._blinker_pause_toggle = BigParamControl(tr("pause lateral control with blinker"), "BlinkerPauseLateralControl")
    self._nnlc_toggle = BigParamControl(tr("neural network lateral control (NNLC)"), "NeuralNetworkLateralControl")
    self._blindspot_toggle = BigParamControl(tr("show blind spot warnings"), "BlindSpot")
    self._lane_turn_toggle = BigParamControl(tr("use lane turn intent"), "LaneTurnDesire")
    self._lagd_toggle = BigParamControl(tr("real-time steering lag learning"), "LagdToggle")
    self._road_edge_toggle = BigParamControl(tr("road edge detection"), "RoadEdgeLcaBlindspot")

    self._scroller.add_widgets([
      self._mads_toggle,
      self._blinker_pause_toggle,
      self._nnlc_toggle,
      self._blindspot_toggle,
      self._lane_turn_toggle,
      self._lagd_toggle,
      self._road_edge_toggle,
    ])