"""Complete settings navigation for the C4 display."""
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.ui_state import OnroadTimerStatus
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.compact import CompactButton, CompactGridPage, CompactPage, CompactRow
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


class SettingsLayoutSP(CompactGridPage):
  def __init__(self):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import Favorites, PARAMETER_TITLES
    self._favorites = Favorites()
    self._parameters = {}
    self._search_page = None
    self.menu_keys = tuple(PARAMETER_TITLES) + ('network', 'device', 'software', 'developer', 'visuals', 'osm', 'sunnylink', 'trips', 'firehose')
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ALL_PARAMETER_TITLES
    entries = [(lambda key=key: tr(ALL_PARAMETER_TITLES.get(key, TITLES.get(key, key))), lambda key=key: self.open_more_panel(key))
               for key in self.menu_keys]
    entries += [(lambda: tr('Search Parameters'), self.open_search), (lambda: tr('Favorites'), lambda: self.open_search(True)),
                (lambda: tr('Exit Offroad') if ui_state.always_offroad else tr('Offroad Mode'), self._handle_always_offroad)]
    super().__init__(lambda: tr("Settings"), entries, button_paging=True)
    self._category = 0
    self._panels = {}
    self._categories = [CompactPage(lambda name=name: tr(name)) for name, _ in GROUPS]
    self._header.action_width = 168
    self._header.action = CompactButton(lambda: tr('ADB / SSH'), lambda: self.open_parameters('remote'))
    more_keys = ("visuals", "device", "network", "software", "developer", "sunnylink", "osm", "trips", "firehose")
    self._more = CompactGridPage(lambda: tr("More"), [(lambda key=key: tr(TITLES[key]), lambda key=key: self.open_more_panel(key))
                                                     for key in more_keys])
    self._more._header.action_width = 152
    self._more._header.action = CompactButton(lambda: tr("Exit Offroad") if ui_state.always_offroad else tr("Offroad Mode"), self._handle_always_offroad)
    for page, (_, keys) in zip(self._categories, GROUPS, strict=True):
      page._list.set_items([CompactRow(lambda key=key: tr(TITLES[key]), callback=lambda key=key: self.open_panel(key), title_size=52)
                            for key in keys])

  def show_event(self):
    super().show_event()
    ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.PAUSE)

  def hide_event(self):
    super().hide_event()
    ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.RESUME)

  def _set_category(self, index):
    self._category = index
    gui_app.push_widget(self._categories[index])

  def open_panel(self, key):
    if key not in self._panels:
      self._panels[key] = make_panel(key)
    gui_app.push_widget(self._panels[key])

  def open_more_panel(self, key):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import SECONDARY_PARAMETERS
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import PARAMETER_TITLES
    self.open_parameters(key) if key in PARAMETER_TITLES or key in SECONDARY_PARAMETERS else self.open_panel(key)

  def parameter_panel(self, kind):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ParameterPanel
    if kind not in self._parameters:
      key = 'steering' if kind in ('lane', 'torque') else 'developer' if kind == 'remote' else kind
      if key not in self._panels:
        self._panels[key] = make_panel(key)
      self._parameters[kind] = ParameterPanel(kind, self._panels[key].controller, self._favorites, self.open_search)
    return self._parameters[kind]

  def open_parameters(self, kind, focus_key=None):
    panel = self.parameter_panel(kind)
    if focus_key:
      panel.focus_parameter(focus_key)
    gui_app.push_widget(panel)

  def open_search(self, favorites_only=None):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ParameterSearch
    if self._search_page is None:
      self._search_page = ParameterSearch(self)
    if favorites_only is not None and favorites_only != self._search_page.favorites_only:
      self._search_page.favorites_only = favorites_only
      self._search_page._list.page = 0
    gui_app.push_widget(self._search_page)

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
