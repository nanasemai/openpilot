from cereal import log
import os

from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl, BigMultiParamToggle
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.layouts.settings.common import restart_needed_callback
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr, tr_noop

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants


class TogglesLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._personality_toggle = BigMultiParamToggle(tr("driving personality"), "LongitudinalPersonality", [tr("aggressive"), tr("standard"), tr("relaxed")])
    self._experimental_btn = BigParamControl(tr("experimental mode"), "ExperimentalMode")
    is_metric_toggle = BigParamControl(tr("use metric units"), "IsMetric")
    ldw_toggle = BigParamControl(tr("lane departure warnings"), "IsLdwEnabled")
    disengage_on_accel = BigParamControl(tr("disengage on accelerator pedal"), "DisengageOnAccelerator")
    always_on_dm_toggle = BigParamControl(tr("always-on driver monitor"), "AlwaysOnDM")
    disable_driver_cam = BigParamControl(tr("disable driver monitoring camera"), "DisableDriverMonitoringCamera", toggle_callback=restart_needed_callback)
    disable_ssh_toggle = BigParamControl(tr("disable remote connection"), "SshEnabled")
    lane_turn_desire = BigParamControl(tr("use lane turn intent"), "LaneTurnDesire")
    lagd_toggle = BigParamControl(tr("real-time steering lag learning"), "LagdToggle")
    road_edge_toggle = BigParamControl(tr("road edge detection"), "RoadEdgeLcaBlindspot")
    dynamic_exp_toggle = BigParamControl(tr("dynamic experimental control"), "DynamicExperimentalControl")
    htd_toggle = BigParamControl(tr("human turn detection (HID)"), "dp_htd_enabled")
    auto_aggressive_toggle = BigParamControl(tr("auto aggressive mode"), "SPAccelProfileModeEnabled")
    quickboot_toggle = BigParamControl(tr("quickboot mode"), "QuickBootToggle")
    disable_updates_toggle = BigParamControl(tr("disable updates"), "DisableUpdates")
    record_front = BigParamControl(tr("record & upload driver camera"), "RecordFront", toggle_callback=restart_needed_callback)
    record_mic = BigParamControl(tr("record & upload mic audio"), "RecordAudio", toggle_callback=restart_needed_callback)
    enable_openpilot = BigParamControl(tr("enable sunnypilot"), "OpenpilotEnabledToggle", toggle_callback=restart_needed_callback)

    disable_driver = bool(os.getenv("DISABLE_DRIVER"))
    if disable_driver:
      always_on_dm_toggle.set_visible(False)
      record_front.set_visible(False)
      disable_driver_cam.set_visible(False)

    self._scroller.add_widgets([
      self._personality_toggle,
      self._experimental_btn,
      is_metric_toggle,
      ldw_toggle,
      disengage_on_accel,
      always_on_dm_toggle,
      disable_driver_cam,
      disable_ssh_toggle,
      lane_turn_desire,
      lagd_toggle,
      road_edge_toggle,
      dynamic_exp_toggle,
      htd_toggle,
      auto_aggressive_toggle,
      quickboot_toggle,
      disable_updates_toggle,
      record_front,
      record_mic,
      enable_openpilot,
    ])

    # Toggle lists
    self._refresh_toggles = (
      ("ExperimentalMode", self._experimental_btn),
      ("IsMetric", is_metric_toggle),
      ("IsLdwEnabled", ldw_toggle),
      ("DisengageOnAccelerator", disengage_on_accel),
      ("AlwaysOnDM", always_on_dm_toggle),
      ("DisableDriverMonitoringCamera", disable_driver_cam),
      ("SshEnabled", disable_ssh_toggle),
      ("LaneTurnDesire", lane_turn_desire),
      ("LagdToggle", lagd_toggle),
      ("RoadEdgeLcaBlindspot", road_edge_toggle),
      ("DynamicExperimentalControl", dynamic_exp_toggle),
      ("dp_htd_enabled", htd_toggle),
      ("SPAccelProfileModeEnabled", auto_aggressive_toggle),
      ("QuickBootToggle", quickboot_toggle),
      ("DisableUpdates", disable_updates_toggle),
      ("RecordFront", record_front),
      ("RecordAudio", record_mic),
      ("OpenpilotEnabledToggle", enable_openpilot),
    )

    enable_openpilot.set_enabled(lambda: not ui_state.engaged)
    record_front.set_enabled(False if ui_state.params.get_bool("RecordFrontLock") else (lambda: not ui_state.engaged))
    record_mic.set_enabled(lambda: not ui_state.engaged)

    if ui_state.params.get_bool("ShowDebugInfo"):
      gui_app.set_show_touches(True)
      gui_app.set_show_fps(True)

    ui_state.add_engaged_transition_callback(self._update_toggles)

  def _update_state(self):
    super()._update_state()

    if ui_state.sm.updated["selfdriveState"]:
      personality = PERSONALITY_TO_INT[ui_state.sm["selfdriveState"].personality]
      if personality != ui_state.personality and ui_state.started:
        self._personality_toggle.set_value(self._personality_toggle._options[personality])
      ui_state.personality = personality

  def show_event(self):
    super().show_event()
    self._update_toggles()

  def _update_toggles(self):
    ui_state.update_params()

    # CP gating for experimental mode
    if ui_state.CP is not None:
      if ui_state.has_longitudinal_control:
        self._experimental_btn.set_visible(True)
        self._personality_toggle.set_visible(True)
      else:
        # no long for now
        self._experimental_btn.set_visible(False)
        self._experimental_btn.set_checked(False)
        self._personality_toggle.set_visible(False)
        ui_state.params.remove("ExperimentalMode")

    # Refresh toggles from params to mirror external changes
    for key, item in self._refresh_toggles:
      item.set_checked(ui_state.params.get_bool(key))
