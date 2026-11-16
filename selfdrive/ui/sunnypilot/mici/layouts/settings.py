"""The fifteen C3X settings categories with large C4 controls."""
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.ui_state import OnroadTimerStatus
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.compact import CompactButton, CompactPage, CompactRow, CompactSwipeList
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel

TITLES = {
  "toggles": tr_noop("Toggles"), "steering": tr_noop("Steering"), "cruise": tr_noop("Cruise"),
  "models": tr_noop("Models"), "vehicle": tr_noop("Vehicle"), "display": tr_noop("Display"),
  "visuals": tr_noop("Visuals"), "device": tr_noop("Device"), "trips": tr_noop("Trips"),
  "network": tr_noop("Network"), "sunnylink": tr_noop("sunnylink"), "osm": tr_noop("OSM"),
  "firehose": tr_noop("Firehose"), "software": tr_noop("Software"), "developer": tr_noop("Developer"),
}
MENU_ORDER = (
  'toggles', 'steering', 'cruise', 'vehicle', 'models',
  'device', 'network', 'sunnylink', 'software', 'visuals', 'display', 'osm', 'trips', 'firehose', 'developer',
)
MENU_GROUPS = {key: (TITLES[key], (key,)) for key in MENU_ORDER}
GROUPS = tuple(MENU_GROUPS.values())
CATEGORY_GROUP = {key: key for key in MENU_ORDER}


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
    self._leaves = {}
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
    self._header.action_width = 160
    self._header.action = CompactButton(lambda: tr('Home'), self.return_home)

  def return_home(self):
    if gui_app.widget_in_stack(self):
      index = gui_app._nav_stack.index(self)
      if index > 0:
        gui_app.pop_widgets_to(gui_app._nav_stack[index - 1], instant=True)

  @staticmethod
  def _group_description(key):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_menu import NODES
    node = NODES[key]
    return ' · '.join(tr(child.title) for child in node.children) if node.children else tr('Tap to view settings')

  @staticmethod
  def _show_page(panel):
    if gui_app.widget_in_stack(panel):
      gui_app.pop_widgets_to(panel, instant=True)
      panel.refresh()
    else:
      gui_app.push_widget(panel)

  def focus_category(self, key):
    self._list.focus_item(self.buttons[self.menu_keys.index(CATEGORY_GROUP.get(key, key))])

  def open_menu(self, key):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_group import SettingsGroup, SettingsLeaf
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_menu import NODES
    node = NODES[key]
    cache, factory = (self._groups, SettingsGroup) if node.children else (self._leaves, SettingsLeaf)
    if key not in cache:
      cache[key] = factory(self, key)
    self._show_page(cache[key])

  def open_group(self, key, category=None, focus_key=None):
    if category or focus_key:
      self.open_setting(category, focus_key)
    else:
      self.open_menu(key)

  def open_setting(self, category, focus_key=None):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_menu import NODES, PATHS, SETTING_ROUTES
    key = SETTING_ROUTES.get(focus_key)
    if key is None:
      key = next(node.key for node in NODES.values() if any(ref.category == category for ref in node.items))
    # Search and shortcuts establish the same parent path as normal category navigation.
    for ancestor in PATHS[key][1:]:
      self.open_menu(ancestor)
    if focus_key:
      self._leaves[key].focus_setting(focus_key)
      self._leaves[key].refresh()

  def source_panel(self, category):
    if category in ('network', 'trips', 'firehose'):
      if category not in self._panels:
        self._panels[category] = make_panel(category)
      return self._panels[category]
    return self.parameter_panel(category)

  def search_entries(self):
    from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_menu import NODES
    panels = {category: self.source_panel(category) for _, categories in MENU_GROUPS.values() for category in categories}
    for panel in panels.values():
      panel._update_state()
    entries = []
    for node in NODES.values():
      for ref in node.items:
        panel = panels[ref.category]
        if ref.selector.startswith('n:'):
          row = next(row for row in panel._list.items if row._c4_setting_id == ref.selector[2:])
        else:
          item = ref.find_item(panel)
          if item is None:
            continue
          row = panel._rows[item][ref.row]
        entries.append((ref.category, ref.key, node.title, row))
    return entries

  def show_event(self):
    super().show_event()
    self._list.page = 0
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
