"""One large card per page throughout the categorized C4 settings."""
import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.mici.layouts.parameters import ParameterActionRow, ParameterPanel, ParameterRow, ParameterTools
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings_menu import NODES
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.compact import (
  CompactButton, CompactInfoPage, CompactPage, CompactRow, CompactSwipeList, PANEL, resolve,
)
from openpilot.system.ui.widgets.label import gui_label


class SettingsMenuPage(CompactPage):
  def __init__(self, title):
    super().__init__(title)
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self.buttons = []

  def set_entries(self, entries):
    self.buttons = [CompactRow(title, hint, callback, title_size=44) for title, hint, callback in entries]
    self._list.set_items(self.buttons)

  def refresh(self):
    pass


class SettingsGroup(SettingsMenuPage):
  def __init__(self, root, kind):
    self.root, self.kind = root, kind
    self.node = NODES[kind]
    super().__init__(lambda: tr(self.node.title))
    self._header.action_width = 64
    self._header.action = ParameterTools(lambda: root.open_search(True))
    self.set_entries([(lambda child=child: tr(child.title), lambda child=child: self._hint(child),
                       lambda child=child: root.open_menu(child.key)) for child in self.node.children])

  @staticmethod
  def _hint(node):
    if node.children:
      return ' · '.join(tr(child.title) for child in node.children)
    return tr('Tap to view settings')


class SettingsDirectory(SettingsMenuPage):
  def __init__(self, leaf):
    self.leaf = leaf
    super().__init__(lambda: tr('Directory'))
    self._entries = []

  def show_event(self):
    super().show_event()
    self.refresh()

  def refresh(self):
    self.leaf.refresh()
    entries = [(ref, row) for ref, row in self.leaf._ref_rows.items() if row.is_visible]
    if entries != self._entries:
      self._entries = entries
      self.set_entries([(row.title, lambda index=index: tr('Option {number}').format(number=index + 1),
                         lambda ref=ref: self.open_entry(ref)) for index, (ref, row) in enumerate(entries)] or
                       [(lambda: tr('No active tasks'), '', lambda: gui_app.pop_widget())])
    current = self.leaf._list.page
    if entries and self._list.rect.width == 0:
      self._list.page = current

  def _update_state(self):
    self.refresh()

  def open_entry(self, ref):
    if gui_app.get_active_widget() is self:
      gui_app.pop_widgets_to(self.leaf, instant=True)
      self.leaf.focus_setting(ref.key)
      self.leaf.refresh()


class SettingsLeaf(CompactPage):
  def __init__(self, root, kind):
    self.root, self.kind = root, kind
    self.node = NODES[kind]
    super().__init__(lambda: tr(self.node.title))
    self.panels = {ref.category: root.source_panel(ref.category) for ref in self.node.items}
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self._header.action_width = 152
    self._header.action = ParameterTools(lambda: root.open_search(True), directory=self.open_directory)
    self._rows = {}
    self._row_sources = {}
    self._native_rows = {}
    self._ref_rows = {}
    self._focus = None
    self._directory = None
    self._empty = ParameterRow(lambda: tr('No active tasks'), callback=self.open_directory, browse_only=True)

  def set_enabled(self, enabled):
    super().set_enabled(enabled)
    if hasattr(self, 'panels'):
      for panel in self.panels.values():
        if self.enabled:
          panel._navigation_owner = self
        elif panel._navigation_owner is self:
          panel._navigation_owner = None

  def show_event(self):
    for panel in self.panels.values():
      users = getattr(panel, '_c4_navigation_users', set())
      panel._c4_navigation_users = users
      if not users:
        panel.show_event()
      users.add(self)
      panel._navigation_owner = self
    self.refresh()

  def hide_event(self):
    self._list.hide_event()
    for panel in reversed(tuple(self.panels.values())):
      panel._c4_navigation_users.discard(self)
      if not panel._c4_navigation_users:
        panel.hide_event()
      if panel._navigation_owner is self:
        panel._navigation_owner = None

  def _guard(self, ref, callback):
    def invoke():
      if gui_app.get_active_widget() is self:
        self.refresh()
        row = self._ref_rows.get(ref)
        if row is not None and row.is_visible:
          callback()
    return invoke

  def _native_row(self, ref, original):
    def save_favorite():
      try:
        self.root._favorites.toggle(ref.key)
      except (OSError, ValueError) as error:
        from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
        gui_app.push_widget(alert_dialog(tr('Unable to save setting: {error}').format(error=error)))

    def help_page():
      if original.help_callback and (ref.category != 'network' or not resolve(original.available)):
        original.help_callback()
      else:
        def detail():
          return (tr('On') if resolve(original.checked) else tr('Off')) if original.checked is not None else str(resolve(original.value))
        gui_app.push_widget(CompactInfoPage(original.title, detail))
      page = gui_app.get_active_widget()
      if isinstance(page, CompactInfoPage):
        page._header.action_width = 176
        page._header.action = CompactButton(
          lambda: tr('Remove from Favorites') if self.root._favorites.contains(ref.key) else tr('Add to Favorites'), save_favorite)

    return ParameterActionRow(original.title, original.value, original.callback, help_page, original.checked,
                              enabled=original.available, visible=lambda: original.is_visible)

  def refresh(self):
    for panel in self.panels.values():
      panel._update_state()
    rows, self._ref_rows = [], {}
    for ref in self.node.items:
      panel = self.panels[ref.category]
      item = None
      if isinstance(panel, ParameterPanel):
        item = ref.find_item(panel)
        if item is None:
          continue  # Vehicle-specific controls follow the selected brand.
        identity = (ref.category, item)
        if identity not in self._rows:
          self._rows[identity] = panel._make_rows(item)
        row = self._rows[identity][ref.row]
      else:
        if ref.category not in self._native_rows:
          self._native_rows[ref.category] = {row._c4_setting_id: row for row in panel.setting_rows()}
        original = self._native_rows[ref.category][ref.selector[2:]]
        if ref not in self._rows:
          self._rows[ref] = self._native_row(ref, original)
        row = self._rows[ref]
      if not hasattr(row, '_c4_leaf_bound'):
        row._c4_leaf_bound = True
        if row.callback:
          row.callback = self._guard(ref, row.callback)
        if row.help_callback:
          row.help_callback = self._guard(ref, row.help_callback)
      self._row_sources[row] = ref.category, item
      self._ref_rows[ref] = row
      rows.append(row)
    self._list.set_items(rows if any(row.is_visible for row in rows) else [self._empty])
    if self._focus:
      for ref, row in self._ref_rows.items():
        if ref.key == self._focus:
          self._list.focus_item(row)
          break
      self._focus = None

  def focus_setting(self, key):
    self._focus = key

  def open_directory(self):
    if gui_app.get_active_widget() is self:
      if self._directory is None:
        self._directory = SettingsDirectory(self)
      self._directory._list.page = self._list.page
      gui_app.push_widget(self._directory)

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
