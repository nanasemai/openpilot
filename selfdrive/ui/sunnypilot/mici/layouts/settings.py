"""Six C4 setting groups, retaining the complete C3X controls."""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.ui_state import OnroadTimerStatus
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.compact import CompactButton, CompactPage, CompactRow, CompactSwipeList
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel

MENU_GROUPS = {
  'device': (tr_noop('Device'), ('device', 'trips')),
  'driving': (tr_noop('Driving Assistance'), ('toggles', 'steering', 'cruise')),
  'display': (tr_noop('Display'), ('display', 'visuals')),
  'vehicle': (tr_noop('Vehicle & Models'), ('vehicle', 'models')),
  'connections': (tr_noop('Network & Connections'), ('network', 'sunnylink', 'osm', 'firehose')),
  'maintenance': (tr_noop('Software & Debugging'), ('software', 'developer')),
}
GROUPS = tuple(MENU_GROUPS.values())
CATEGORY_GROUP = {category: group for group, (_, categories) in MENU_GROUPS.items() for category in categories}
TITLES = {
  "toggles": tr_noop("Toggles"), "steering": tr_noop("Steering"), "cruise": tr_noop("Cruise"),
  "models": tr_noop("Models"), "vehicle": tr_noop("Vehicle"), "display": tr_noop("Display"),
  "visuals": tr_noop("Visuals"), "device": tr_noop("Device"), "trips": tr_noop("Trips"),
  "network": tr_noop("Network"), "sunnylink": tr_noop("sunnylink"), "osm": tr_noop("Offline Maps"),
  "firehose": tr_noop("Firehose Mode"), "software": tr_noop("Software"), "developer": tr_noop("Developer"),
}
MENU_ORDER = tuple(MENU_GROUPS)


class SettingsTools(CompactButton):
  def __init__(self, remote, search):
    super().__init__(lambda: tr('ADB / SSH'), lambda: None)
    self._remote = self._child(CompactButton(lambda: tr('ADB / SSH'), remote))
    self._search = self._child(CompactButton(lambda: tr('Search'), search))
    for button in (self._remote, self._search):
      button.set_enabled(lambda: self.enabled)

  def _render(self, rect):
    self._remote.render(rl.Rectangle(rect.x, rect.y, rect.width - 84, rect.height))
    self._search.render(rl.Rectangle(rect.x + rect.width - 76, rect.y, 76, rect.height))


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
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import Favorites
    self._favorites = Favorites()
    self._parameters = {}
    self._search_page = None
    self._groups = {}
    self.menu_keys = MENU_ORDER
    entries = [(lambda key=key: tr(MENU_GROUPS[key][0]), lambda key=key: self.open_group(key))
               for key in self.menu_keys]
    super().__init__(lambda: tr('Settings'))
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self.buttons = [CompactRow(text, lambda key=key: self._group_description(key),
                               callback=callback, title_size=52)
                    for key, (text, callback) in zip(self.menu_keys, entries, strict=True)]
    for button in self.buttons:
      button.set_click_callback(button.callback)
    self._list.set_items(self.buttons)
    self._panels = {}
    self._header.action_width = 244
    self._header.action = SettingsTools(lambda: self.open_parameters('remote'), lambda: self.open_search(False))

  @staticmethod
  def _group_description(key):
    if key == 'connections':
      return tr('Wi-Fi · Remote Access · Maps · Uploads')
    return ' · '.join(tr(TITLES[category]) for category in MENU_GROUPS[key][1])

  @staticmethod
  def _show_page(panel):
    if gui_app.widget_in_stack(panel):
      gui_app.pop_widgets_to(panel, instant=True)
      panel.refresh()
    else:
      gui_app.push_widget(panel)

  def focus_category(self, key):
    self._list.focus_item(self.buttons[self.menu_keys.index(CATEGORY_GROUP.get(key, key))])

  def open_group(self, key, category=None, focus_key=None):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_group import SettingsGroup
    if key not in self._groups:
      self._groups[key] = SettingsGroup(self, key)
    panel = self._groups[key]
    if category or focus_key:
      panel.focus_setting(category, focus_key)
    self._show_page(panel)

  def open_setting(self, category, focus_key=None):
    if category == 'remote':
      self.open_parameters(category, focus_key)
    else:
      self.open_group(CATEGORY_GROUP[category], category, focus_key)

  def show_event(self):
    super().show_event()
    ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.PAUSE)

  def hide_event(self):
    super().hide_event()
    ui_state.reset_onroad_sleep_timer(OnroadTimerStatus.RESUME)

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
    self._show_page(panel)

  def open_search(self, favorites_only=None):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ParameterSearch
    if self._search_page is None:
      self._search_page = ParameterSearch(self)
    if favorites_only is not None and favorites_only != self._search_page.favorites_only:
      self._search_page.favorites_only = favorites_only
      self._search_page._list.page = 0
    self._show_page(self._search_page)

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
