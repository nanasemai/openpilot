"""Combine C3X categories into one secondary swipe list without another menu level."""
import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ParameterPanel, ParameterTools, parameter_key
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import MENU_GROUPS, TITLES, make_panel
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.compact import CompactPage, CompactSwipeList, PANEL
from openpilot.system.ui.widgets.label import gui_label


class SettingsGroup(CompactPage):
  def __init__(self, root, kind):
    super().__init__(lambda: tr(MENU_GROUPS[kind][0]))
    self.kind = kind
    self.panels = {}
    for category in MENU_GROUPS[kind][1]:
      if category in ('network', 'trips', 'firehose'):
        if category not in root._panels:
          root._panels[category] = make_panel(category)
        panel = root._panels[category]
      else:
        panel = root.parameter_panel(category)
      panel._navigation_owner = self
      self.panels[category] = panel
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self._header.position = None
    self._header.title = self._section_title
    self._header.action_width = 184
    self._header.action = ParameterTools(lambda: root.open_search(False), lambda: root.open_search(True))
    self._rows = {}
    self._row_sources = {}
    self._native_rows = {}
    self._focus = None

  def show_event(self):
    for panel in self.panels.values():
      panel.show_event()
    self.refresh()

  def hide_event(self):
    self._list.hide_event()
    for panel in reversed(tuple(self.panels.values())):
      panel.hide_event()

  def refresh(self):
    rows = []
    for category, panel in self.panels.items():
      panel._update_state()
      if isinstance(panel, ParameterPanel):
        for item in panel._source_items:
          identity = (category, item)
          if identity not in self._rows:
            # Fresh rows share the controller callbacks, but have only this list's touch guard.
            self._rows[identity] = panel._make_rows(item)
          for row in self._rows[identity]:
            self._row_sources[row] = category, item
          rows.extend(self._rows[identity])
      else:
        if category not in self._native_rows:
          self._native_rows[category] = panel.setting_rows()
        for row in self._native_rows[category]:
          self._row_sources[row] = category, None
        rows.extend(self._native_rows[category])
    self._list.set_items(rows)
    if self._focus:
      category, key = self._focus
      for row in self._list.visible_items:
        row_category, item = self._row_sources[row]
        if row_category == category and (key is None or (item is not None and parameter_key(item) == key)):
          self._list.focus_item(row)
          break
      self._focus = None

  def focus_setting(self, category, key=None):
    self._focus = category, key

  def _section_title(self):
    visible = self._list.visible_items
    if visible:
      category, item = self._row_sources[visible[self._list.page]]
      panel = self.panels[category]
      return panel.section_title(item) if isinstance(panel, ParameterPanel) else tr(TITLES[category])
    return tr(MENU_GROUPS[self.kind][0])

  def _update_state(self):
    self.refresh()

  def _render(self, rect):
    super()._render(rect)
    notifications = [panel for panel in self.panels.values() if isinstance(panel, ParameterPanel) and
                     panel._notification and rl.get_time() < panel._notification_until]
    if notifications:
      panel = max(notifications, key=lambda panel: panel._notification_until)
      rl.draw_rectangle_rec(rl.Rectangle(rect.x + 12, rect.y + 48, rect.width - 24, 28), PANEL)
      gui_label(rl.Rectangle(rect.x + 16, rect.y + 48, rect.width - 32, 28), panel._notification, 22)
