"""Shallow C4 parameter lists, preserving the shared controllers' edit policy."""
from html import escape

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_panel import SettingsPanel
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.compact import (
  ACCENT, MUTED, PANEL, CompactButton, CompactInfoButton, CompactInfoPage, CompactSwipeList, CompactPage, CompactRow,
  resolve, translation_source,
)
from openpilot.system.ui.widgets.label import UnifiedLabel, gui_label
from openpilot.system.ui.widgets.list_view import MultipleButtonAction, ToggleAction
from openpilot.system.ui.sunnypilot.widgets.option_control import OptionControlSP

PARAMETER_TITLES = {
  'steering': tr_noop('Steering'), 'lane': tr_noop('Lane Change'), 'torque': tr_noop('Torque Parameters'),
  'cruise': tr_noop('Cruise'), 'models': tr_noop('Models'), 'display': tr_noop('Display'),
  'vehicle': tr_noop('Vehicle'), 'toggles': tr_noop('Toggles'),
}
SECONDARY_PARAMETERS = {
  'remote': tr_noop('ADB / SSH'), 'visuals': tr_noop('Visuals'), 'developer': tr_noop('Developer'),
  'device': tr_noop('Device'), 'software': tr_noop('Software'), 'osm': tr_noop('Offline Maps'), 'sunnylink': tr_noop('sunnylink'),
}
ALL_PARAMETER_TITLES = PARAMETER_TITLES | SECONDARY_PARAMETERS
DEPENDENCIES = {
  'BlinkerMinLateralControlSpeed': ('BlinkerPauseLateralControl', True, tr_noop('Enable Pause Lateral Control with Blinker first.')),
  'BlinkerLateralReengageDelay': ('BlinkerPauseLateralControl', True, tr_noop('Enable Pause Lateral Control with Blinker first.')),
  'MadsMainCruiseAllowed': ('Mads', True, tr_noop('Enable MADS first.')),
  'MadsUnifiedEngagementMode': ('Mads', True, tr_noop('Enable MADS first.')),
  'MadsSteeringMode': ('Mads', True, tr_noop('Enable MADS first.')),
  'TorqueParamsOverrideEnabled': ('CustomTorqueParams', True, tr_noop('Enable Custom Torque Params first.')),
  'TorqueParamsOverrideLatAccelFactor': ('CustomTorqueParams', True, tr_noop('Enable Custom Torque Params first.')),
  'TorqueParamsOverrideFriction': ('CustomTorqueParams', True, tr_noop('Enable Custom Torque Params first.')),
  'CustomAccShortPressIncrement': ('CustomAccIncrementsEnabled', True, tr_noop('Enable Custom ACC Increments first.')),
  'CustomAccLongPressIncrement': ('CustomAccIncrementsEnabled', True, tr_noop('Enable Custom ACC Increments first.')),
  'dp_htd_turn_angle_threshold': ('dp_htd_enabled', True, tr_noop('Enable Hands-on Turn Detection first.')),
  'LaneTurnValue': ('LaneTurnDesire', True, tr_noop('Enable Use Lane Turn Desires first.')),
  'LagdToggleDelay': ('LagdToggle', False, tr_noop('Disable Live Learning Steer Delay first.')),
  'LiveTorqueParamsRelaxedToggle': ('LiveTorqueParamsToggle', True, tr_noop('Enable Self-Tune first.')),
}


def parameter_key(item):
  action = getattr(item, 'action_item', None)
  key = getattr(action.toggle, 'param_key', None) if isinstance(action, ToggleAction) else getattr(action, 'param_key', None)
  return getattr(item, '_c4_param_key', None) or key


class Favorites:
  def __init__(self):
    self.params = Params()

  def read(self):
    value = self.params.get('C4FavoriteSettings')
    if value is None:
      return []
    if not isinstance(value, list) or any(not isinstance(key, str) for key in value):
      raise ValueError('Invalid favorites data')
    return value

  def contains(self, key):
    try:
      return key in self.read()
    except ValueError:
      return False

  def toggle(self, key):
    # Re-read before each edit to retain unrecognized/external entries.
    values = self.read()
    values = [value for value in values if value != key] if key in values else [*values, key]
    self.params.put('C4FavoriteSettings', values, block=True)


class ParameterTools(CompactButton):
  """Keep search and favorites reachable from the parameter header."""
  def __init__(self, search, favorites, selected=lambda: False):
    super().__init__('', lambda: None)
    self._search = self._child(CompactButton(lambda: tr('Search'), search))
    self._favorites = self._child(CompactButton('★', favorites))
    self.selected = selected
    for button in (self._search, self._favorites):
      button.set_enabled(lambda: self.enabled)

  def _render(self, rect):
    self._favorites.primary = bool(self.selected())
    self._search.render(rl.Rectangle(rect.x, rect.y, rect.width - 64, rect.height))
    self._favorites.render(rl.Rectangle(rect.x + rect.width - 56, rect.y, 56, rect.height))


class ParameterRow(CompactRow):
  """A full-width browse card; changing a toggle requires its separate large control."""
  def __init__(self, *args, reason=lambda: '', favorite=None, toggle_favorite=None, browse_only=False, **kwargs):
    super().__init__(*args, row_height=164, title_size=40, **kwargs)
    self.reason, self.favorite, self.toggle_favorite = reason, favorite, toggle_favorite
    self.browse_only = browse_only
    self._value_label = UnifiedLabel('', font_size=36, scroll=True)
    self._tap_start = None
    self._tap_cancelled = False

  def set_parent_rect(self, rect):
    super().set_parent_rect(rect)
    self._rect.width, self._rect.height = rect.width, rect.height

  def _switch_touch_rect(self):
    return self.rect

  def _handle_mouse_press(self, pos):
    self._tap_start = (pos.x, pos.y)
    self._tap_cancelled = False

  def _handle_mouse_event(self, event):
    if self._tap_start:
      x, y = self._tap_start
      if (event.pos.x - x) ** 2 + (event.pos.y - y) ** 2 > 12 ** 2:
        self._tap_cancelled = True

  def hide_event(self):
    super().hide_event()
    self._tap_start = None
    self._tap_cancelled = False

  def _render(self, rect):
    from openpilot.system.ui.lib.wrap_text import wrap_text
    available = bool(resolve(self.available))
    color = rl.WHITE if available else MUTED
    rl.draw_rectangle_rounded(rect, 0.15, 10, PANEL)
    title_width = self._title_width()
    title = str(resolve(self.title))
    lines = wrap_text(gui_app.font(), title, 40, int(title_width))
    gui_label(rl.Rectangle(rect.x + 24, rect.y + 8, title_width, 44), lines[0] if lines else '', 40, color)
    if len(lines) > 1:
      overflow = title.strip()[len(lines[0]):].lstrip()
      if overflow != self._overflow_title.text:
        self._overflow_title.set_text(overflow)
        self._overflow_title.reset_scroll()
      self._overflow_title.set_text_color(color)
      self._overflow_title.render(rl.Rectangle(rect.x + 24, rect.y + 52, title_width, 44))
    if not available and not self.browse_only:
      value = tr('Unavailable')
    elif self.checked is not None:
      value = tr('On') if bool(resolve(self.checked)) else tr('Off')
    else:
      value = str(resolve(self.value))
    if self._value_label.text != value:
      self._value_label.set_text(value)
      self._value_label.reset_scroll()
    self._value_label.set_text_color(ACCENT if available and self.checked is not None and resolve(self.checked) else color)
    self._value_label.render(rl.Rectangle(rect.x + 24, rect.y + rect.height - 48, rect.width - 88, 44))
    if self.callback:
      center = rl.Vector2(rect.x + rect.width - 32, rect.y + rect.height - 26)
      rl.draw_line_ex(rl.Vector2(center.x - 5, center.y - 12), rl.Vector2(center.x + 5, center.y), 4, MUTED)
      rl.draw_line_ex(rl.Vector2(center.x + 5, center.y), rl.Vector2(center.x - 5, center.y + 12), 4, MUTED)

  def _handle_mouse_release(self, pos):
    if self._tap_cancelled:
      self._tap_start = None
      return
    self._tap_start = None
    super()._handle_mouse_release(pos)


class ParameterTogglePage(CompactPage):
  def __init__(self, owner, item, title, description):
    super().__init__(title)
    self.owner, self.item = owner, item
    self._status = ''
    self._toggle = self._child(CompactButton(lambda: tr('Disable') if self.item.action_item.get_state() else tr('Enable'),
                                           self.change, primary=True))
    self._toggle.set_enabled(lambda: self.enabled and self.owner._item_available(self.item))
    self._header.action = CompactButton(lambda: tr('Description'), description)

  def _update_state(self):
    self.owner.refresh()

  def change(self):
    if gui_app.get_active_widget() is self and self.owner._item_available(self.item):
      self.owner._toggle(self.item, active_page=self)
      self._status = self.owner._notification

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    self._header.render(rl.Rectangle(rect.x, rect.y, rect.width, 56))
    gui_label(rl.Rectangle(rect.x + 24, rect.y + 64, rect.width - 48, 40),
              tr('Current State: {state}').format(state=tr('On') if self.item.action_item.get_state() else tr('Off')), 36,
              alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)
    self._toggle.render(rl.Rectangle(rect.x + 24, rect.y + 112, rect.width - 48, 88))
    status = self._status or (self.owner._unavailable_reason(self.item) if not self.owner._item_available(self.item) else '')
    gui_label(rl.Rectangle(rect.x + 16, rect.y + rect.height - 32, rect.width - 32, 28), status, 22, MUTED,
              alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)


class ParameterActionRow(ParameterRow):
  """Keep an action's status and description accessible before it is invoked."""
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._info = self._child(CompactInfoButton(lambda: self.help_callback() if self.help_callback else None))
    self._info.set_enabled(lambda: self.enabled)
    self._info.set_touch_valid_callback(self._touch_valid)

  def _title_width(self):
    return super()._title_width() - 72

  def _info_rect(self):
    return rl.Rectangle(self.rect.x + self.rect.width - 80, self.rect.y, 80, 80)

  def _render(self, rect):
    super()._render(rect)
    self._info.set_parent_rect(self._parent_rect or rect)
    self._info.render(self._info_rect())

  def _handle_mouse_release(self, pos):
    if not rl.check_collision_point_rec(pos, self._info_rect()):
      super()._handle_mouse_release(pos)


class ParameterPanel(SettingsPanel):
  def __init__(self, kind, controller, favorites, search):
    super().__init__(ALL_PARAMETER_TITLES[kind], controller)
    self.kind, self.favorites = kind, favorites
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self._header.position = None
    self._header.action_width = 184
    self._header.action = ParameterTools(lambda: search(False), lambda: search(True))
    self._owners = {}
    self._focus_key = None
    self._controllers = [controller]
    self._excluded = set()
    if kind in ('developer', 'remote'):
      for key, attribute in (('AdbEnabled', '_adb_toggle'), ('SshEnabled', '_ssh_toggle'), ('GithubSshKeys', '_ssh_keys'),
                             ('ShowDebugInfo', '_ui_debug_toggle'), ('ForceOnroad', '_force_onroad_toggle'),
                             ('EnableLivestream', '_enable_livestream_toggle'), ('JoystickDebugMode', '_joystick_toggle'),
                             ('LongitudinalManeuverMode', '_long_maneuver_toggle'), ('LateralManeuverMode', '_lat_maneuver_toggle'),
                             ('AlphaLongitudinalEnabled', '_alpha_long_toggle')):
        getattr(controller, attribute)._c4_param_key = key
    if kind == 'toggles':
      for key, item in controller._toggles.items():
        item._c4_param_key = key
    if kind == 'software':
      controller.disable_updates_toggle._c4_param_key = 'DisableUpdates'
    if kind == 'sunnylink':
      controller._sunnylink_toggle._c4_param_key = 'SunnylinkEnabled'
    if kind in ('steering', 'lane', 'torque'):
      self._excluded = {controller._mads_settings_button, controller._lane_change_settings_button, controller._torque_customization_button}
      if kind == 'steering':
        self._controllers.append(controller._mads_settings_layout)
      else:
        self._controllers.append(controller._lane_change_settings_layout if kind == 'lane' else controller._torque_control_layout)
    elif kind == 'cruise':
      limit = controller._speed_limit_layout
      self._excluded = {controller.sla_settings_button, limit._source_button}
      self._controllers.extend([limit, limit._policy_layout])

  def go_back(self):
    gui_app.pop_widget()

  def show_event(self):
    for controller in self._controllers:
      controller.show_event()
    self.refresh()

  def hide_event(self):
    self._list.hide_event()
    for controller in reversed(self._controllers):
      controller.hide_event()

  def refresh(self):
    for controller in self._controllers:
      self._refresh_controller(controller)
    visible_controllers = self._controllers[1:] if self.kind == 'lane' else self._controllers
    self._source_items = []
    for controller in visible_controllers:
      for item in controller._scroller._items:
        if item in self._excluded or not hasattr(item, 'action_item'):
          continue
        if self.kind == 'remote' and item not in (self.controller._adb_toggle, self.controller._ssh_toggle, self.controller._ssh_keys):
          continue
        # The torque page includes its prerequisite switch, without duplicating steering controls.
        if self.kind == 'torque' and controller is self.controller and item is not controller._torque_control_toggle:
          continue
        self._owners[item] = controller
        self._source_items.append(item)
    rows = []
    for item in self._source_items:
      if item not in self._rows:
        self._rows[item] = self._make_rows(item)
      rows.extend(self._rows[item])
    self._list.set_items(rows)
    if gui_app.get_active_widget() is self:
      for item in self._source_items:
        action = item.action_item
        if hasattr(action, 'present_error'):
          action.present_error()

  def _unavailable_reason(self, item):
    key = parameter_key(item)
    dependency = DEPENDENCIES.get(key)
    if dependency and ui_state.params.get_bool(dependency[0]) != dependency[1]:
      return tr(dependency[2])
    if key == 'SpeedLimitValueOffset' and ui_state.params.get('SpeedLimitOffsetType', return_default=True) == 0:
      return tr('Choose a Speed Limit Offset first.')
    owner = self._owners.get(item)
    if owner is not None and owner is getattr(self.controller, '_mads_settings_layout', None) and not ui_state.is_offroad():
      return tr('Park the vehicle to change this setting.')
    if owner is not None and owner is getattr(self.controller, '_torque_control_layout', None):
      if not self.controller._torque_control_toggle.action_item.get_state():
        return tr('Enable Enforce Torque Lateral Control first.')
      if ui_state.CP is None:
        return tr('Start the vehicle to check vehicle compatibility.')
      from cereal import car
      if ui_state.CP.steerControlType == car.CarParams.SteerControlType.angle:
        return tr('Unavailable for this vehicle.')
    action = item.action_item
    if not item.enabled or (action is not None and not action.enabled):
      return tr('Park the vehicle to change this setting.') if not ui_state.is_offroad() else tr('Check vehicle compatibility and prerequisites.')
    if key == 'QuickBootToggle':
      if not ui_state.params.get_bool('ShowAdvancedControls'):
        return tr('Enable Show Advanced Controls first.')
      if self.controller._is_release_branch or self.controller._is_development_branch:
        return tr('Unavailable on this software branch.')
    if key == 'EnableGithubRunner' and self.controller._is_release_branch:
      return tr('Unavailable on this software branch.')
    # Lift presentation gating only. Controller availability and feature prerequisites still apply.
    if not item.is_visible and key not in ('LaneTurnValue', 'LagdToggleDelay', 'DisableUpdates', 'EnableCopyparty', 'EnableGithubRunner'):
      return tr('Check vehicle compatibility and prerequisites.')
    return ''

  def _item_available(self, item):
    return item in self._source_items and not self._unavailable_reason(item)

  def _make_rows(self, item):
    originals = super()._make_rows(item)
    action, key = item.action_item, parameter_key(item)
    configurable = isinstance(action, (ToggleAction, MultipleButtonAction, OptionControlSP))
    result = []
    for row in originals:
      def toggle_favorite(key=key):
        try:
          self.favorites.toggle(key)
          self._notify(tr('Saved'))
        except (OSError, ValueError) as error:
          self._notify(tr('Unable to save setting: {error}').format(error=error))
      def help_page(row=row, toggle_favorite=toggle_favorite):
        reason = self._unavailable_reason(item)
        if reason:
          gui_app.push_widget(CompactInfoPage(row.title, lambda: escape(reason) + '<br><br>' + tr(item.description), rich=True))
        elif row.help_callback:
          row.help_callback()
        page = gui_app.get_active_widget()
        if key and isinstance(page, CompactInfoPage):
          page._header.action_width = 176
          page._header.action = CompactButton(lambda: tr('Remove from Favorites') if self.favorites.contains(key) else tr('Add to Favorites'),
                                              toggle_favorite)
      def open_detail(row=row, help_page=help_page):
        if isinstance(action, ToggleAction):
          gui_app.push_widget(ParameterTogglePage(self, item, row.title, help_page))
        elif row.callback:
          row.callback()
          page = gui_app.get_active_widget()
          if hasattr(page, '_help'):
            page._help.set_click_callback(help_page)
      row_type = ParameterRow if configurable else ParameterActionRow
      converted = row_type(row.title, row.value, open_detail if row.callback else None, help_page, row.checked, enabled=row.available,
                           visible=True if configurable else lambda row=row: row.is_visible,
                           reason=lambda: self._unavailable_reason(item))
      result.append(converted)
    return result

  def focus_parameter(self, key):
    self._focus_key = key

  def _render(self, rect):
    from openpilot.system.ui.widgets.compact import BACKGROUND
    rl.draw_rectangle_rec(rect, BACKGROUND)
    self._header.render(rl.Rectangle(rect.x, rect.y, rect.width, 56))
    if self._focus_key:
      for item, rows in self._rows.items():
        if parameter_key(item) == self._focus_key:
          self._list.focus_item(rows[0])
          break
      self._focus_key = None
    self._list.render(rl.Rectangle(rect.x, rect.y + 56, rect.width, rect.height - 56))
    if self._notification and rl.get_time() < self._notification_until:
      rl.draw_rectangle_rec(rl.Rectangle(rect.x + 12, rect.y + 48, rect.width - 24, 28), PANEL)
      gui_label(rl.Rectangle(rect.x + 16, rect.y + 48, rect.width - 32, 28), self._notification, 22)


class ParameterSearch(CompactPage):
  def __init__(self, root):
    super().__init__(lambda: tr('Search Parameters'), horizontal=False)
    self.root = root
    self._list = self._child(CompactSwipeList())
    self._list.set_enabled(lambda: self.enabled)
    self.query = ''
    self.favorites_only = False
    self._header.action_width = 184
    self._header.action = ParameterTools(self.search, self.toggle_filter, lambda: self.favorites_only)
    self._entries = []
    self._result_rows = {}
    self._empty_row = ParameterRow(lambda: tr('No matching options'), callback=self.search, browse_only=True)
    self._refresh_entries()

  def _refresh_entries(self):
    self._entries = []
    seen = set()
    for kind in ALL_PARAMETER_TITLES:
      panel = self.root.parameter_panel(kind)
      panel.refresh()
      for item in panel._source_items:
        key = parameter_key(item)
        if key and key not in seen:
          seen.add(key)
          source = translation_source(item.title)
          self._entries.append((kind, key, source, panel._rows[item][0]))

  def toggle_filter(self):
    self.favorites_only = not self.favorites_only
    self._list.page = 0
    self.refresh()

  def search(self):
    from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
    def result(status, query):
      if status == DialogResult.CONFIRM:
        self.query = query.strip()
        self.refresh()
        self._list.page = 0
    InputDialogSP(tr('Search Parameters'), current_text=self.query, callback=result).show()

  def matching_entries(self):
    return [entry for entry in self._entries
            if self.query.casefold() in (entry[1] + ' ' + entry[2] + ' ' + str(resolve(entry[3].title)) + ' ' + tr(ALL_PARAMETER_TITLES[entry[0]])).casefold()
            and (not self.favorites_only or self.root._favorites.contains(entry[1]))]

  def refresh(self):
    self._refresh_entries()
    rows = []
    for entry in self.matching_entries():
      identity = (entry[0], entry[1], entry[3])
      if identity not in self._result_rows:
        self._result_rows[identity] = ParameterRow(lambda entry=entry: str(resolve(entry[3].title)),
                                                  lambda entry=entry: tr(ALL_PARAMETER_TITLES[entry[0]]),
                                                  callback=lambda entry=entry: self.open_result(entry), browse_only=True)
      rows.append(self._result_rows[identity])
    self._list.set_items(rows or [self._empty_row])

  def toggle_favorite(self, key):
    try:
      self.root._favorites.toggle(key)
      self.refresh()
    except (OSError, ValueError) as error:
      from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
      gui_app.push_widget(alert_dialog(tr('Unable to save setting: {error}').format(error=error)))

  def show_event(self):
    self.refresh()

  def open_result(self, entry):
    self.root.open_parameters(entry[0], entry[1])

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    self._header.title = lambda: tr('Favorites') if self.favorites_only else tr('Search Parameters')
    self._header.render(rl.Rectangle(rect.x, rect.y, rect.width, 56))
    self._list.render(rl.Rectangle(rect.x, rect.y + 56, rect.width, rect.height - 56))
