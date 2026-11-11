"""C4 views of the same setting controls and policy used by the large display."""
from html import escape
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.compact import (
  CompactPage, CompactRow, CompactActionRow, CompactInfoPage, CompactNumberPage, CompactSelectPage, translation_source, resolve,
)
from openpilot.system.ui.widgets.list_view import ListItem, ToggleAction, MultipleButtonAction, ButtonAction, TextAction, DualButtonAction
from openpilot.system.ui.sunnypilot.widgets.list_view import ExpandableItemSP, SimpleButtonActionSP
from openpilot.system.ui.sunnypilot.widgets.option_control import OptionControlSP
from openpilot.system.ui.sunnypilot.widgets.progress_bar import ProgressBarAction

# Each value is a real controller attribute. The existing callbacks select its enum.
SUBPANELS = {
  "MADS": "_mads_settings_layout",
  "LANE_CHANGE": "_lane_change_settings_layout",
  "TORQUE_CONTROL": "_torque_control_layout",
  "SLA": "_speed_limit_layout",
  "POLICY": "_policy_layout",
}
SUBTITLES = {
  "MADS": "Customize MADS", "LANE_CHANGE": "Customize Lane Change", "TORQUE_CONTROL": "Customize Torque Params",
  "SLA": "Speed Limit", "POLICY": "Speed Limit Source",
}


class SettingsPanel(CompactPage):
  def __init__(self, title: str, controller):
    super().__init__(lambda: tr(title), self.go_back)
    self.title = title
    self.controller = controller
    self._rows = {}
    self._lists = {controller: self._list}
    self._active = controller
    self._source_items = []

  def _chain(self):
    chain = [self.controller]
    while (name := getattr(getattr(chain[-1], "_current_panel", None), "name", "")) in SUBPANELS:
      child = getattr(chain[-1], SUBPANELS[name], None)
      if child is None:
        break
      chain.append(child)
    return chain

  def go_back(self):
    chain = self._chain()
    if len(chain) > 1:
      chain[-1]._back_button._click_callback()
    else:
      gui_app.pop_widget()

  def show_event(self):
    self.controller.show_event()
    self.refresh()

  def hide_event(self):
    self.controller.hide_event()

  def refresh(self):
    chain = self._chain()
    for controller in chain:
      scroller = getattr(controller, "_scroller", None)
      if scroller:
        for item in scroller._items:
          action = getattr(item, "action_item", None)
          if action is not None:
            action._update_state()
          if isinstance(action, ToggleAction) and getattr(action.toggle, "param_key", None):
            action.set_state(action.toggle.params.get_bool(action.toggle.param_key))
          if isinstance(action, MultipleButtonAction) and getattr(action, "param_key", None):
            value = action.params.get(action.param_key, return_default=True)
            if value is not None:
              action.set_selected_button(int(value))
          if isinstance(action, OptionControlSP):
            raw_value = action.params.get(action.param_key, return_default=True)
            if raw_value is not None:
              if action.value_map:
                value = next((key for key, value in action.value_map.items() if value == raw_value), action.current_value)
              else:
                value = int(round(float(raw_value) * (100 if action.use_float_scaling else 1)))
              action.current_value = max(action.min_value, min(action.max_value, value))
      controller._update_state()
    active = chain[-1]
    if active is not self._active:
      from openpilot.system.ui.widgets.compact import CompactList
      self._active = active
      if active not in self._lists:
        self._lists[active] = CompactList()
        active.show_event()
      self._list = self._lists[active]
      self._list.set_enabled(lambda: self.enabled)
    name = getattr(getattr(chain[-2], "_current_panel", None), "name", "") if len(chain) > 1 else ""
    self._header.title = lambda: tr(SUBTITLES.get(name, self.title))
    items = active._scroller._items
    self._source_items = items
    rows = []
    for item in items:
      if not isinstance(item, ListItem):
        continue  # Separators use row borders; custom information is supplied by its controller below.
      if item not in self._rows:
        self._rows[item] = self._make_rows(item)
      rows.extend(self._rows[item])
    self._list.set_items(rows)
    if gui_app.get_active_widget() is self:
      for item in items:
        action = getattr(item, "action_item", None)
        if hasattr(action, "present_error"):
          action.present_error()

  def _update_state(self):
    self.refresh()

  def _item_available(self, item):
    action = item.action_item
    return (item in self._source_items and item.is_visible and item.enabled and
            (action is None or action.enabled))

  def _invoke(self, item, callback, extra_allowed=lambda: True):
    self.refresh()
    if self._item_available(item) and extra_allowed() and callback is not None and gui_app.get_active_widget() is self:
      callback()

  def _make_rows(self, item):
    action = item.action_item
    source_title = translation_source(item.title)
    initial_title = item.title
    initial_description = item.description
    description_source = translation_source(initial_description)

    def title():
      return tr(source_title) if item.title == initial_title else tr(item.title)

    def available():
      return self._item_available(item)

    def help_text(fallback=True):
      self.refresh()
      if item.description_opened_callback:
        item.description_opened_callback()
      description = tr(description_source) if item.description == initial_description else tr(item.description)
      if not fallback:
        return description
      return description or (tr("This setting is currently unavailable. Check vehicle compatibility and device state.")
                                      if not available() else tr("Setting Description"))

    def help_page():
      gui_app.push_widget(CompactInfoPage(title, help_text, rich=True))

    def visible():
      return item.is_visible
    if isinstance(action, DualButtonAction):
      return [CompactRow(lambda button=button: (title() + " · " if title() else "") + tr(str(resolve(button._label._text))),
                         callback=lambda button=button: self._invoke(item, button._click_callback, lambda: button.enabled and button.is_visible),
                         help_callback=help_page, enabled=lambda button=button: item.enabled and action.enabled and button.enabled,
                         visible=lambda button=button: item.is_visible and button.is_visible)
              for button in (action.left_button, action.right_button)]
    if isinstance(action, ToggleAction):
      return [CompactRow(title, callback=lambda: self._toggle(item), help_callback=help_page, checked=action.get_state,
                         enabled=available, visible=visible)]
    if isinstance(action, OptionControlSP):
      return [CompactRow(title, action.get_displayed_value,
                         lambda: self._open_number(item, title, help_text), help_page, enabled=available, visible=visible)]
    if isinstance(action, MultipleButtonAction):
      sources = [text if callable(text) else translation_source(text) for text in action.buttons]
      return [CompactRow(title, lambda: tr(str(resolve(sources[action.selected_button])))
                           if 0 <= action.selected_button < len(sources) else tr("Default"),
                         lambda: self._open_enum(item, title), help_page, enabled=available, visible=visible)]
    if isinstance(item, ExpandableItemSP):
      return [CompactRow(title, lambda: tr(item.right_value), lambda: self._invoke(item, item.callback), help_page, enabled=available, visible=visible)]
    if isinstance(action, SimpleButtonActionSP):
      button_text = action.button_action._label._text
      label = button_text if callable(button_text) else translation_source(button_text)
      return [CompactRow(lambda: title() or tr(str(resolve(label))), lambda: tr(str(resolve(label))) if title() else "",
                         callback=lambda: self._invoke(item, action.button_action._click_callback),
                         help_callback=help_page, enabled=available, visible=visible)]
    if isinstance(action, ButtonAction):
      initial_text, initial_value = action.text, action.value
      text_source, value_source = translation_source(initial_text), translation_source(initial_value)
      def button_value():
        value, text = action.value, action.text
        return (tr(value_source) if value == initial_value else tr(value)) or (tr(text_source) if text == initial_text else tr(text))
      def button_info():
        def detail():
          description = help_text(fallback=False)
          return escape(button_value()) + ("<br><br>" + description if description else "")
        gui_app.push_widget(CompactInfoPage(title, detail, rich=True))
      return [CompactActionRow(title, button_value, lambda: self._invoke(item, item.callback), button_info, enabled=available, visible=visible)]
    if isinstance(action, TextAction):
      initial_text = action.text
      text_source = translation_source(initial_text)
      def info_value():
        return tr(text_source) if action.text == initial_text else tr(action.text)
      def info():
        gui_app.push_widget(CompactInfoPage(title, lambda: escape(info_value()) + "<br><br>" + help_text(), rich=True))
      return [CompactRow(title, info_value, info, info, visible=visible)]
    if isinstance(action, ProgressBarAction):
      def progress_info():
        gui_app.push_widget(CompactInfoPage(title, lambda: escape(tr(action.text)) + "<br><br>" + help_text(), rich=True))
      return [CompactRow(title, lambda: tr(action.text), progress_info, progress_info, visible=visible,
                         progress=lambda: action.progress if action.show_progress else None)]
    # SSH keys use their own fetcher and button callback, never a generic parameter write.
    if action is not None and hasattr(action, "_handle_button_click"):
      return [CompactRow(title, lambda: action.get_status(),
                         lambda: self._invoke(item, action._handle_button_click, lambda: getattr(action, "_state", None).name != "LOADING"),
                         help_page, enabled=lambda: available() and getattr(action, "_state", None).name != "LOADING", visible=visible)]
    return [CompactRow(title, callback=help_page, help_callback=help_page, visible=visible)]

  def _toggle(self, item):
    self.refresh()
    action = item.action_item
    if self._item_available(item) and gui_app.get_active_widget() is self:
      toggle = action.toggle
      toggle.set_enabled(True)
      toggle._handle_mouse_release(None)
      # List callbacks are independent of the toggle's state callback.
      if item.callback:
        item.callback()

  def _open_number(self, item, title, help_text):
    action = item.action_item
    def allowed():
      return self._item_available(item)
    # Maps have explicit legal indices; timezone and brightness are practical selection lists.
    if action.value_map or action.param_key in ("Timezone", "OnroadScreenOffBrightness", "AutoLaneChangeTimer"):
      keys = list(action.value_map) if action.value_map else list(range(action.min_value, action.max_value + 1))
      choices = [lambda key=key: self._option_label(action, key) for key in keys]
      from openpilot.system.timezone_list import tz_name
      search_terms = [tz_name(key) for key in keys] if action.param_key == "Timezone" else None
      gui_app.push_widget(CompactSelectPage(title, choices, lambda: keys.index(action.current_value),
                                           lambda index: action.set_value(keys[index]), lambda _: allowed(), self.refresh,
                                           help_text=help_text, searchable=action.param_key == "Timezone", search_terms=search_terms))
    else:
      page = CompactNumberPage(title, action, self.refresh, help_text)
      page.allowed = allowed
      gui_app.push_widget(page)

  @staticmethod
  def _option_label(action, key):
    value = action.value_map[key] if action.value_map else key
    return tr(action.label_callback(value)) if action.label_callback else str(value)

  def _open_enum(self, item, title):
    action = item.action_item

    def allowed(index):
      return (self._item_available(item) and
              (getattr(action, "enabled_buttons", None) is None or index in action.enabled_buttons))

    def choose(index):
      action.set_selected_button(index)
      if action.callback:
        action.callback(index)
      if getattr(action, "param_key", None):
        action.params.put(action.param_key, index, block=True)

    sources = [text if callable(text) else translation_source(text) for text in action.buttons]
    choices = [lambda text=text: tr(str(resolve(text))) for text in sources]
    gui_app.push_widget(CompactSelectPage(title, choices, action.get_selected_button, choose, allowed, self.refresh,
                                         help_text=lambda: tr(item.description)))
