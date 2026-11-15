"""DP's categorized C4 settings, using its existing control policies."""
from decimal import Decimal
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.compact import (
  CompactActionRow, CompactButton, CompactGridPage, CompactInfoPage, CompactNumberPage, CompactPage,
  CompactRow, CompactSelectPage, CompactSwipeList, resolve,
)
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.widgets.list_view import (
  ToggleAction, MultipleButtonAction, ButtonAction, TextAction, DualButtonAction, BaseSpinBoxAction, TextSpinBoxAction,
)
from dragonpilot.selfdrive.ui.mici.layouts.network import NetworkPanel
from dragonpilot.selfdrive.ui.mici.layouts.settings_menu import ROOT, NODES, PATHS, ROUTES
from dragonpilot.selfdrive.ui.mici.layouts.settings_controllers import (
  DpController, DeviceController, DeveloperController, TogglesController, SoftwareController, FirehoseController, source_item,
)


class NumberAction:
  """Scale native DP numbers to exact integer editor units and retain its callback."""
  def __init__(self, leaf, ref, item):
    self.leaf, self.ref, self.item, self.native = leaf, ref, item, item.action_item
    self.params, self.param_key = ui_state.params, ref.key
    self.input_scale = 10 ** getattr(self.native, '_decimals', 0)
    self.min_value = int(Decimal(str(self.native._min_val)) * self.input_scale)
    self.max_value = int(Decimal(str(self.native._max_val)) * self.input_scale)
    self.value_change_step = int(Decimal(str(self.native._step)) * self.input_scale)

  @property
  def enabled(self):
    return self.leaf.available(self.ref, self.item)

  @property
  def is_visible(self):
    return self.enabled

  @property
  def current_value(self):
    return int(round(self.native.get_value() * self.input_scale))

  def format_value(self, value):
    if value == self.min_value and self.native._special_value_text:
      return self.native._special_value_text
    return f'{value / self.input_scale:g}{self.native._suffix}'

  def format_step(self):
    return f'{self.value_change_step / self.input_scale:g}{self.native._suffix}'

  def get_displayed_value(self):
    return self.format_value(self.current_value)

  def default_index(self):
    default = self.params.get_default_value(self.param_key)
    return None if default is None else int(round(float(default) * self.input_scale))

  def set_value(self, value):
    raw = value / self.input_scale if self.input_scale != 1 else int(value)
    self.native.set_value(raw)
    self.native._callback(raw)

  def restore_raw(self, raw):
    if raw is None:
      self.params.remove(self.param_key)
    else:
      self.set_value(int(round(float(raw) * self.input_scale)))


class TogglePage(CompactPage):
  def __init__(self, title, state, change, available, help_text):
    super().__init__(title)
    self.state = state
    self._toggle = self._child(CompactButton(lambda: tr('Disable') if state() else tr('Enable'), change, True))
    self._toggle.set_enabled(lambda: self.enabled and available())
    self._header.action = CompactButton(lambda: tr('Description'),
      lambda: gui_app.push_widget(CompactInfoPage(title, help_text, True)))

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    self._header.render(rl.Rectangle(rect.x, rect.y, rect.width, 56))
    gui_label(rl.Rectangle(rect.x + 12, rect.y + 76, rect.width - 24, 42),
              tr('Current State: {state}').format(state=tr('On') if self.state() else tr('Off')), 32,
              alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)
    self._toggle.render(rl.Rectangle(rect.x + 24, rect.y + 132, rect.width - 48, 88))


class MenuPage(CompactPage):
  def __init__(self, root, node):
    super().__init__(lambda: tr(node.title))
    self.root, self.node = root, node
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self._header.action_width = 64
    self._header.action = CompactButton('★', root.open_favorites)
    self._list.set_items([CompactRow(lambda child=child: tr(child.title),
      lambda child=child: ' · '.join(tr(n.title) for n in child.children) or tr('Tap to view settings'),
      lambda child=child: root.open_menu(child.key)) for child in node.children])


class ParameterTools(Widget):
  def __init__(self, leaf):
    super().__init__()
    self.text = ''
    self._directory = self._child(CompactButton(lambda: tr('Directory'), leaf.open_directory))
    self._favorites = self._child(CompactButton('★', leaf.root.open_favorites))

  def _render(self, rect):
    self._directory.set_enabled(self.enabled)
    self._favorites.set_enabled(self.enabled)
    self._directory.render(rl.Rectangle(rect.x, rect.y, rect.width - 64, rect.height))
    self._favorites.render(rl.Rectangle(rect.x + rect.width - 56, rect.y, 56, rect.height))


class SettingsLeaf(CompactPage):
  def __init__(self, root, node):
    super().__init__(lambda: tr(node.title))
    self.root, self.node = root, node
    self.controllers = {r.source: root.source(r.source) for r in node.items}
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self._header.action_width = 152
    self._header.action = ParameterTools(self)
    self._rows, self.ref_rows = {}, {}
    self._native_rows = {}
    self._native_wrappers = {}
    self.refresh()

  def show_event(self):
    for c in self.controllers.values():
      users = getattr(c, '_c4_users', set())
      c._c4_users = users
      if not users:
        c.show_event()
      users.add(self)
      c._navigation_owner = self
    self.refresh()

  def hide_event(self):
    self._list.hide_event()
    for c in self.controllers.values():
      c._c4_users.discard(self)
      if not c._c4_users:
        c.hide_event()

  def available(self, ref, item):
    controller = self.controllers[ref.source]
    return source_item(controller, ref) is item and item.is_visible and item.enabled

  def help_text(self, ref, item):
    self.refresh()
    if item.description_opened_callback:
      item.description_opened_callback()
    description = item.description
    if not self.available(ref, item):
      description = tr('This setting is currently unavailable. Check vehicle compatibility and device state.') + '\n\n' + description
    return description or tr('Setting Description')

  def help_page(self, ref, item):
    page = CompactInfoPage(lambda: item.title, lambda: self.help_text(ref, item), True)
    page._header.action_width = 176
    page._header.action = CompactButton(lambda: tr('Remove from Favorites') if self.root.favorite(ref) else tr('Add to Favorites'),
                                       lambda: self.root.toggle_favorite(ref))
    gui_app.push_widget(page)

  def invoke(self, ref, item, callback, extra=lambda: True):
    self.refresh()
    if self.available(ref, item) and extra() and callback is not None:
      callback()

  def open_item(self, ref, item):
    if gui_app.get_active_widget() is not self:
      return
    self.refresh()
    if not self.available(ref, item):
      self.help_page(ref, item)
      return
    a = item.action_item
    title, help_text = lambda: item.title, lambda: self.help_text(ref, item)
    if isinstance(a, ToggleAction):
      page = TogglePage(title, a.get_state, lambda: self.invoke(ref, item, lambda: a.toggle.set_state(not a.get_state()) or a.toggle._callback(a.get_state())),
                        lambda: self.available(ref, item), help_text)
    elif isinstance(a, TextSpinBoxAction):
      page = CompactSelectPage(title, a._options, a.get_index,
                               lambda i: self.invoke(ref, item, lambda: a.set_index(i) or a._callback(i)),
                               allowed=lambda _: self.available(ref, item), refresh=self.refresh, help_text=help_text)
    elif isinstance(a, MultipleButtonAction):
      page = CompactSelectPage(title, a.buttons, a.get_selected_button,
                               lambda i: self.invoke(ref, item, lambda: a.set_selected_button(i) or a.callback(i)),
                               allowed=lambda _: self.available(ref, item), refresh=self.refresh, help_text=help_text)
    elif isinstance(a, BaseSpinBoxAction):
      page = CompactNumberPage(title, NumberAction(self, ref, item), self.refresh, help_text)
    else:
      if ref.source == 'developer' and ref.key == 'keys':
        self.invoke(ref, item, self.controllers['developer'].edit_ssh_keys)
      elif isinstance(a, DualButtonAction):
        button = (a.left_button, a.right_button)[ref.row]
        self.invoke(ref, item, button._click_callback, lambda: button.enabled and button.is_visible)
      elif isinstance(a, TextAction) or a is None:
        self.help_page(ref, item)
      else:
        self.invoke(ref, item, item.callback)
      return
    gui_app.push_widget(page)

  def make_row(self, ref, item):
    a = item.action_item
    def title():
      return item.title
    checked, value = None, ''
    def extra_available():
      return True
    def visible():
      return item.is_visible
    if isinstance(a, ToggleAction):
      checked = a.get_state
    elif isinstance(a, MultipleButtonAction):
      def value():
        return str(resolve(a.buttons[a.get_selected_button()]))
    elif isinstance(a, BaseSpinBoxAction):
      value = a._get_display_text
    elif isinstance(a, DualButtonAction):
      button = (a.left_button, a.right_button)[ref.row]
      def title():
        return str(resolve(button._label._text))
      def extra_available():
        return button.enabled
      def visible():
        return item.is_visible and button.is_visible
    elif isinstance(a, ButtonAction):
      def value():
        return a.value or a.text
    elif isinstance(a, TextAction):
      def value():
        return a.text
    elif ref.source == 'developer' and ref.key == 'keys':
      def value():
        return ui_state.params.get('GithubUsername') or tr('Not set')
    row = CompactActionRow(title, value, lambda: self.open_item(ref, item), lambda: self.help_page(ref, item), checked,
                           enabled=lambda: self.available(ref, item) and extra_available(), visible=visible)
    row._c4_ref = ref
    return row

  def native_row(self, ref, original):
    def help_page():
      if ref.source == 'firehose':
        original.callback()
      elif original.help_callback:
        original.help_callback()
      else:
        def value():
          return (tr('On') if resolve(original.checked) else tr('Off')) if original.checked is not None else str(resolve(original.value))
        gui_app.push_widget(CompactInfoPage(original.title, value))
      page = gui_app.get_active_widget()
      if isinstance(page, CompactInfoPage):
        page._header.action_width = 176
        page._header.action = CompactButton(lambda: tr('Remove from Favorites') if self.root.favorite(ref) else tr('Add to Favorites'),
                                           lambda: self.root.toggle_favorite(ref))
    def invoke():
      if gui_app.get_active_widget() is self:
        self.refresh()
        if original.is_visible and resolve(original.available) and original.callback:
          original.callback()
        else:
          help_page()
    return CompactActionRow(original.title, original.value, invoke, help_page, original.checked,
                            enabled=original.available, visible=lambda: original.is_visible)

  def empty_reason(self):
    if ui_state.CP is None and any(r.source == 'dp' for r in self.node.items):
      return tr('Start the vehicle to load compatible settings.')
    if self.node.key == 'longitudinal':
      return tr('These settings require openpilot longitudinal control.')
    return tr('No settings available for this vehicle or state.')

  def refresh(self):
    for source, c in self.controllers.items():
      c._navigation_owner = self
      c._update_state() if source == 'network' else c.refresh()
    rows, self.ref_rows = [], {}
    for ref in self.node.items:
      c = self.controllers[ref.source]
      if ref.source in ('network', 'firehose'):
        if ref.source not in self._native_rows:
          self._native_rows[ref.source] = c.setting_rows() if ref.source == 'network' else c.rows()
        row = next((r for r in self._native_rows[ref.source] if r._c4_setting_id == ref.key), None)
        if row:
          if ref.id not in self._native_wrappers:
            self._native_wrappers[ref.id] = self.native_row(ref, row)
          row = self._native_wrappers[ref.id]
          row._c4_ref = ref
      else:
        item = source_item(c, ref)
        if item is None:
          continue
        identity = (ref.id, item)
        if identity not in self._rows:
          self._rows[identity] = self.make_row(ref, item)
        row = self._rows[identity]
      if row:
        rows.append(row)
        self.ref_rows[ref.id] = row
    self._list.set_items(rows or [CompactRow(self.empty_reason, callback=self.open_directory)])

  def _update_state(self):
    self.refresh()

  def open_directory(self):
    self.refresh()
    def choose(ref):
      gui_app.pop_widgets_to(self, instant=True)
      self._list.focus_item(self.ref_rows[ref.id])
    entries = [(row.title, lambda ref=row._c4_ref: choose(ref)) for row in self._list.visible_items if hasattr(row, '_c4_ref')]
    gui_app.push_widget(CompactGridPage(lambda: tr('Directory'), entries, button_paging=True))


class SettingsLayout(MenuPage):
  def __init__(self):
    self._sources, self._pages = {}, {}
    self._close_callback = None
    super().__init__(self, ROOT)
    self._header.action_width = 160
    self._header.action = CompactButton(lambda: tr('Home'), self.go_home)

  def set_home_callback(self, callback):
    self._close_callback = callback

  def go_home(self):
    if self._close_callback:
      self._close_callback()
    else:
      gui_app.pop_widgets_to(self, instant=True)
      gui_app.pop_widget()

  def open_from_home(self):
    self._list.page = 0
    for page in self._pages.values():
      page._list.page = 0
    gui_app.push_widget(self)

  def source(self, name):
    if name not in self._sources:
      self._sources[name] = dict(dp=DpController, toggles=TogglesController, device=DeviceController,
        developer=DeveloperController, software=SoftwareController, network=NetworkPanel, firehose=FirehoseController)[name]()
    return self._sources[name]

  def open_menu(self, key):
    if key not in self._pages:
      node = NODES[key]
      self._pages[key] = MenuPage(self, node) if node.children else SettingsLeaf(self, node)
    gui_app.push_widget(self._pages[key])

  def favorites(self):
    value = ui_state.params.get('dp_ui_settings_favorites')
    return value if isinstance(value, list) else []

  def favorite(self, ref):
    return ref.id in self.favorites()

  def toggle_favorite(self, ref):
    values = self.favorites()
    values.remove(ref.id) if ref.id in values else values.append(ref.id)
    ui_state.params.put('dp_ui_settings_favorites', values, block=True)

  def open_favorites(self):
    entries = []
    for identifier in self.favorites():
      key = ROUTES.get(identifier)
      if key is None:
        continue
      if key not in self._pages:
        self._pages[key] = SettingsLeaf(self, NODES[key])
      page = self._pages[key]
      page.refresh()
      row = page.ref_rows.get(identifier)
      if row is not None and row.is_visible:
        def choose(key=key, identifier=identifier):
          gui_app.pop_widgets_to(self, instant=True)
          for parent in PATHS[key][1:-1]:
            self.open_menu(parent)
          self.open_menu(key)
          self._pages[key]._list.focus_item(self._pages[key].ref_rows[identifier])
        entries.append((row.title, choose))
    gui_app.push_widget(CompactGridPage(lambda: tr('Favorites'), entries or [(lambda: tr('No favorites yet'), gui_app.pop_widget)], button_paging=True))
