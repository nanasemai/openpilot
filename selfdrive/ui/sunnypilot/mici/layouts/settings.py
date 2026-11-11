"""Complete settings navigation for the C4 display."""
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.ui_state import OnroadTimerStatus
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.compact import CompactButton, CompactPage, CompactRow
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel

GROUPS = (
  (tr_noop("Driving"), ("toggles", "steering", "cruise", "models", "vehicle")),
  (tr_noop("Display"), ("display", "visuals")),
  (tr_noop("Device"), ("device", "trips")),
  (tr_noop("Connections"), ("network", "sunnylink", "osm", "firehose")),
  (tr_noop("Maintenance"), ("software", "developer")),
)
TITLES = {
  "toggles": tr_noop("Toggles"), "steering": tr_noop("Steering"), "cruise": tr_noop("Cruise"),
  "models": tr_noop("Models"), "vehicle": tr_noop("Vehicle"), "display": tr_noop("Display"),
  "visuals": tr_noop("Visuals"), "device": tr_noop("Device"), "trips": tr_noop("Trips"),
  "network": tr_noop("Network"), "sunnylink": tr_noop("sunnylink"), "osm": tr_noop("Offline Maps"),
  "firehose": tr_noop("Firehose Mode"), "software": tr_noop("Software"), "developer": tr_noop("Developer"),
}


def make_panel(key):
  from openpilot.selfdrive.ui.layouts.settings.toggles import TogglesLayout
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.steering import SteeringLayout
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.models import ModelsLayout
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.display import DisplayLayout
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.visuals import VisualsLayout
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.osm import OSMLayout
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.software import SoftwareLayoutSP
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.developer import DeveloperLayoutSP
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_controllers import (
    DeviceController, VehicleController, SunnylinkController, CruiseController, TripsPanel, FirehosePanel,
  )
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.network import NetworkPanel

  controllers = {
    "toggles": TogglesLayout, "steering": SteeringLayout, "cruise": CruiseController, "models": ModelsLayout,
    "vehicle": VehicleController, "display": DisplayLayout, "visuals": VisualsLayout, "device": DeviceController,
    "osm": OSMLayout, "software": SoftwareLayoutSP, "developer": DeveloperLayoutSP, "sunnylink": SunnylinkController,
  }
  if key == "trips":
    return TripsPanel()
  if key == "firehose":
    return FirehosePanel()
  if key == "network":
    return NetworkPanel()
  return SettingsPanel(TITLES[key], controllers[key]())


class SettingsLayoutSP(CompactPage):
  def __init__(self):
    super().__init__(lambda: tr("Settings"))
    self._category = 0
    self._panels = {}
    self._categories = [CompactPage(lambda name=name: tr(name)) for name, _ in GROUPS]
    self._list.set_items([CompactRow(lambda name=name: tr(name), callback=lambda index=index: self._set_category(index), title_size=52)
                          for index, (name, _) in enumerate(GROUPS)])
    self._header.action_width = 152
    self._header.action = CompactButton(lambda: tr("Exit Offroad") if ui_state.always_offroad else tr("Offroad Mode"), self._handle_always_offroad)
    for page, (_, keys) in zip(self._categories, GROUPS, strict=True):
      page._list.set_items([CompactRow(lambda key=key: tr(TITLES[key]), callback=lambda key=key: self.open_panel(key), title_size=52)
                            for key in keys])

  def show_event(self):
    ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.PAUSE)

  def hide_event(self):
    ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.RESUME)

  def _set_category(self, index):
    self._category = index
    gui_app.push_widget(self._categories[index])

  def open_panel(self, key):
    if key not in self._panels:
      self._panels[key] = make_panel(key)
    gui_app.push_widget(self._panels[key])

  def _handle_always_offroad(self):
    if ui_state.engaged:
      gui_app.push_widget(alert_dialog(tr("Disengage to Enter Always Offroad Mode")))
      return
    enabled = not ui_state.always_offroad

    def confirm(result):
      if result == DialogResult.CONFIRM and not ui_state.engaged:
        ui_state.params.put_bool("OffroadMode", enabled, block=True)
        ui_state.always_offroad = enabled

    gui_app.push_widget(ConfirmDialog(tr("Are you sure you want to enter Always Offroad mode?") if enabled else
                                      tr("Are you sure you want to exit Always Offroad mode?"), tr("Confirm"), callback=confirm))
