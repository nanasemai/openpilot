"""Touch controls for the 536 x 240 display. Values and policy belong to their callers."""
from collections.abc import Callable
from html import escape

import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, gui_app, MousePos
from openpilot.system.ui.lib.multilang import multilang, tr
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.html_render import ElementType, HtmlRenderer
from openpilot.system.ui.widgets.label import gui_label, UnifiedLabel
from openpilot.system.ui.widgets.scroller import Scroller

HEADER_HEIGHT = 56
ROW_HEIGHT = 168
CARD_WIDTH = 402
TEXT_SIZE = 32
TITLE_SIZE = 44
BACKGROUND = rl.Color(8, 9, 11, 255)
PANEL = rl.Color(16, 18, 22, 255)
MUTED = rl.Color(158, 168, 183, 255)
ACCENT = rl.Color(120, 172, 255, 255)


def resolve(value):
  return value() if callable(value) else value


def translation_source(text: str) -> str:
  """Retain the original key of static labels when their owner was built in Chinese."""
  if text in multilang._translations:
    return text
  return next((key for key, value in multilang._translations.items() if value == text), text)


class CompactButton(Widget):
  def __init__(self, text, callback: Callable, primary: bool = False):
    super().__init__()
    self.text = text
    self.primary = primary
    self.set_click_callback(callback)

  def _render(self, rect):
    color = rl.Color(55, 111, 184, 255) if self.primary else rl.Color(47, 55, 67, 255)
    if self.is_pressed and self.enabled:
      color = rl.Color(68, 90, 123, 255)
    rl.draw_rectangle_rounded(rect, 0.25, 8, color)
    text = str(resolve(self.text))
    measured = measure_text_cached(gui_app.font(), text, TEXT_SIZE).x
    font_size = min(TEXT_SIZE, max(28, int(TEXT_SIZE * (rect.width - 16) / max(1, measured))))
    gui_label(rl.Rectangle(rect.x + 8, rect.y, rect.width - 16, rect.height), text, font_size,
              rl.WHITE if self.enabled else MUTED, alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)


class CompactBackButton(CompactButton):
  def _render(self, rect):
    center = rl.Vector2(rect.x + rect.width / 2, rect.y + rect.height / 2)
    rl.draw_line_ex(rl.Vector2(center.x + 6, center.y - 14), rl.Vector2(center.x - 8, center.y), 4, rl.WHITE)
    rl.draw_line_ex(rl.Vector2(center.x - 8, center.y), rl.Vector2(center.x + 6, center.y + 14), 4, rl.WHITE)


class CompactHeader(Widget):
  def __init__(self, title, back: Callable):
    super().__init__()
    self.title = title
    self._back = CompactBackButton("", back)
    self._back.set_enabled(lambda: self.enabled)
    self.action = None
    self.action_width = 112
    self.position = None
    self._title_label = UnifiedLabel(lambda: str(resolve(self.title)), font_size=TEXT_SIZE, font_weight=FontWeight.BOLD,
                                     alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_MIDDLE, scroll=True)
    self._title_state = None

  def show_event(self):
    self._title_label.reset_scroll()

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, PANEL)
    self._back.render(rl.Rectangle(rect.x, rect.y, 72, rect.height))
    reserve = self.action_width if self.action else 80 if self.position and resolve(self.position) else 0
    if self.action:
      width = measure_text_cached(gui_app.font(), str(resolve(self.action.text)), TEXT_SIZE).x + 24
      reserve = min(rect.width - 244, max(reserve, width))
    title_rect = rl.Rectangle(rect.x + 80, rect.y, rect.width - 92 - reserve, rect.height)
    title_state = (str(resolve(self.title)), multilang.language, title_rect.width)
    if self._title_state != title_state:
      self._title_label.reset_scroll()
      self._title_state = title_state
    self._title_label.render(title_rect)
    if self.action:
      self.action.set_enabled(self.enabled)
      self.action.render(rl.Rectangle(rect.x + rect.width - reserve, rect.y + 2, reserve - 8, rect.height - 4))
    elif reserve:
      gui_label(rl.Rectangle(rect.x + rect.width - 80, rect.y, 72, rect.height), str(resolve(self.position)), 24, MUTED,
                alignment=rl.GuiTextAlignment.TEXT_ALIGN_RIGHT)


class CompactList(Scroller):
  def __init__(self, horizontal=True):
    super().__init__(horizontal=horizontal, spacing=20 if horizontal else 0, pad=20 if horizontal else 0,
                     scroll_indicator=False, edge_shadows=horizontal)
    self.horizontal = horizontal
    self._scroller.set_reset_scroll_at_show(False)
    self._scroller.set_enabled(lambda: self.enabled)

  def set_items(self, items):
    if items == self._scroller.items:
      return
    self._scroller.items.clear()
    self._scroller.add_widgets(items)

  def focus_item(self, item):
    if self.horizontal and item.is_visible and item in self._scroller.items:
      scroll = self._scroller.scroll_panel
      offset = scroll.get_offset() + self.rect.x + 20 - item.rect.x
      minimum = min(0, self.rect.width - self._scroller.content_size)
      scroll.set_offset(max(minimum, min(0, offset)))

  @property
  def position(self):
    items = [item for item in self._scroller.items if item.is_visible]
    if not self.horizontal or len(items) < 2:
      return ""
    center = self.rect.x + self.rect.width / 2
    index = min(range(len(items)), key=lambda i: abs(items[i].rect.x + items[i].rect.width / 2 - center))
    return f"{index + 1}/{len(items)}"

  def _render(self, rect):
    viewport = rl.Rectangle(rect.x, rect.y, rect.width if self.horizontal else rect.width - 6, rect.height)
    for item in self._scroller.items:
      item.set_parent_rect(viewport)
    self._scroller.render(viewport)
    size = self._scroller.content_size
    if not self.horizontal and size > rect.height:
      height = max(18, rect.height * rect.height / size)
      ratio = max(0, min(1, -self._scroller.scroll_panel.get_offset() / (size - rect.height)))
      rl.draw_rectangle_rec(rl.Rectangle(rect.x + rect.width - 4, rect.y + ratio * (rect.height - height), 3, height), MUTED)


class CompactRow(Widget):
  def __init__(self, title, value="", callback=None, help_callback=None, checked=None, enabled=True, visible=True,
               font_weight=FontWeight.NORMAL, row_height=ROW_HEIGHT, title_size=TITLE_SIZE,
               value_alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT, progress=None):
    super().__init__()
    self.title, self.value = title, value
    self.callback, self.help_callback, self.checked = callback, help_callback, checked
    self.available = enabled
    self.font_weight = font_weight
    self.row_height = row_height
    self.title_size = title_size
    self.value_alignment = value_alignment
    self.progress = progress
    self.set_visible(visible)
    self._rect.height = row_height
    self._overflow_title = UnifiedLabel("", font_size=title_size, font_weight=font_weight, scroll=True)

  def set_parent_rect(self, rect):
    super().set_parent_rect(rect)
    self._rect.width = min(CARD_WIDTH, rect.width - 40)
    self._rect.height = min(self.row_height, rect.height - 12)

  def _title_width(self):
    return self.rect.width - 48

  def _switch_touch_rect(self):
    return rl.Rectangle(self.rect.x + self.rect.width - 112, self.rect.y + self.rect.height - 64, 112, 64)

  def _value_rect(self):
    return rl.Rectangle(self.rect.x + 24, self.rect.y + self.rect.height - 56, self.rect.width - 72, 48)

  def _render(self, rect):
    font = gui_app.font(self.font_weight)
    title = str(resolve(self.title))
    value = str(resolve(self.value))
    lines = wrap_text(font, title, self.title_size, max(1, int(self._title_width())))
    unavailable = not resolve(self.available)
    color = MUTED if unavailable else rl.WHITE
    rl.draw_rectangle_rounded(rect, 0.20, 12, rl.Color(37, 43, 53, 255) if self.is_pressed else PANEL)
    has_footer = self.checked is not None or bool(value) or unavailable
    line_height = self.title_size + 4
    y = rect.y + 12 if has_footer else rect.y + (rect.height - min(2, len(lines)) * line_height) / 2
    gui_label(rl.Rectangle(rect.x + 24, y, self._title_width(), line_height), lines[0] if lines else "", self.title_size,
              color, font_weight=self.font_weight)
    if len(lines) > 1:
      remaining = title.strip()[len(lines[0]):].lstrip() if title.strip().startswith(lines[0]) else " ".join(lines[1:])
      if remaining != self._overflow_title.text:
        self._overflow_title.set_text(remaining)
        self._overflow_title.reset_scroll()
      self._overflow_title.set_text_color(color)
      self._overflow_title.render(rl.Rectangle(rect.x + 24, y + line_height, self._title_width(), line_height))
    if self.checked is not None:
      switch = rl.Rectangle(rect.x + rect.width - 102, rect.y + rect.height - 54, 82, 46)
      checked = bool(resolve(self.checked))
      rl.draw_rectangle_rounded(switch, 1, 10, ACCENT if checked and resolve(self.available) else rl.Color(65, 71, 82, 255))
      rl.draw_circle_v(rl.Vector2(switch.x + (59 if checked else 23), switch.y + 23), 18, color)
      gui_label(rl.Rectangle(rect.x + 24, rect.y + rect.height - 56, rect.width - 144, 48),
                tr("Unavailable") if unavailable else tr("On") if checked else tr("Off"), TEXT_SIZE, color)
    else:
      value_rect = self._value_rect()
      gui_label(value_rect, value or (tr("Unavailable") if unavailable else ""), TEXT_SIZE, color, alignment=self.value_alignment)
      if self.callback:
        center = rl.Vector2(rect.x + rect.width - 16, rect.y + rect.height / 2)
        rl.draw_line_ex(rl.Vector2(center.x - 4, center.y - 10), rl.Vector2(center.x + 4, center.y), 3, MUTED)
        rl.draw_line_ex(rl.Vector2(center.x + 4, center.y), rl.Vector2(center.x - 4, center.y + 10), 3, MUTED)
    progress = resolve(self.progress)
    if progress is not None:
      bar = rl.Rectangle(rect.x + 24, rect.y + rect.height - 6, rect.width - 48, 4)
      rl.draw_rectangle_rec(bar, rl.Color(65, 71, 82, 255))
      rl.draw_rectangle_rec(rl.Rectangle(bar.x, bar.y, bar.width * max(0, min(100, progress)) / 100, bar.height), ACCENT)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    action_hit = self.checked is None or rl.check_collision_point_rec(mouse_pos, self._switch_touch_rect())
    if action_hit and resolve(self.available) and self.callback:
      self.callback()
    elif self.help_callback:
      self.help_callback()


class CompactInfoButton(Widget):
  def __init__(self, callback):
    super().__init__()
    self.set_click_callback(callback)

  def _render(self, rect):
    center = rl.Vector2(rect.x + rect.width / 2, rect.y + rect.height / 2)
    if self.is_pressed:
      rl.draw_circle_v(center, 28, rl.Color(47, 55, 67, 255))
    rl.draw_circle_lines(int(center.x), int(center.y), 18, MUTED)
    rl.draw_circle_v(rl.Vector2(center.x, center.y - 8), 2, MUTED)
    rl.draw_line_ex(rl.Vector2(center.x, center.y - 1), rl.Vector2(center.x, center.y + 10), 3, MUTED)


class CompactActionRow(CompactRow):
  """Keep information available independently of an action or its enabled state."""
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._info = self._child(CompactInfoButton(lambda: self.help_callback() if self.help_callback else None))
    self._info.set_touch_valid_callback(self._touch_valid)

  def _title_width(self):
    return super()._title_width() - 56

  def _info_rect(self):
    return rl.Rectangle(self.rect.x + self.rect.width - 70, self.rect.y, 64, 64)

  def _render(self, rect):
    super()._render(rect)
    self._info.set_enabled(self.enabled)
    self._info.set_parent_rect(self._parent_rect or rect)
    self._info.render(self._info_rect())

  def _handle_mouse_release(self, mouse_pos):
    if rl.check_collision_point_rec(mouse_pos, self._info_rect()):
      return
    super()._handle_mouse_release(mouse_pos)


class CompactText(Widget):
  def __init__(self, text, rich: bool = False):
    super().__init__()
    self.text, self.rich = text, rich
    self._previous = None
    self._html = HtmlRenderer(text="", text_size={ElementType.P: TEXT_SIZE})

  def set_parent_rect(self, rect):
    super().set_parent_rect(rect)
    self._rect.width = rect.width
    text = str(resolve(self.text) or "")
    if text != self._previous:
      self._html.parse_html_content(text if self.rich else escape(text).replace("\n", "<br>"))
      self._previous = text
    self._rect.height = self._html.get_total_height(int(rect.width)) + 16

  def _render(self, rect):
    self._html.render(rl.Rectangle(rect.x, rect.y + 8, rect.width, rect.height - 8))


class CompactPage(Widget):
  def __init__(self, title, back=None, horizontal=True):
    super().__init__()
    self._header = CompactHeader(title, back or gui_app.pop_widget)
    self._header.set_enabled(lambda: self.enabled)
    self._list = CompactList(horizontal=horizontal)
    self._list.set_enabled(lambda: self.enabled)
    self._header.position = lambda: self._list.position

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, BACKGROUND)
    self._header.render(rl.Rectangle(rect.x, rect.y, rect.width, HEADER_HEIGHT))
    self._list.render(rl.Rectangle(rect.x, rect.y + HEADER_HEIGHT, rect.width, rect.height - HEADER_HEIGHT))


class CompactInfoPage(CompactPage):
  def __init__(self, title, text, rich: bool = False):
    super().__init__(title, horizontal=False)
    self._list.set_items([CompactText(lambda: f"<b>{escape(str(resolve(title)))}</b><br>{resolve(text) or ''}" if rich else
                                       f"{resolve(title)}\n\n{resolve(text) or ''}", rich)])


class CompactConfirmView(Widget):
  """Render the existing dialog's callbacks, keeping confirmation/cancellation semantics."""
  def __init__(self, title, text, confirm_text, cancel_text, confirm, cancel, rich=False):
    super().__init__()
    self._header = CompactHeader(title, cancel)
    self._list = CompactList(horizontal=False)
    self._list.set_items([CompactText(text, rich)])
    self._confirm = CompactButton(confirm_text, confirm, primary=True)
    self._cancel = CompactButton(cancel_text, cancel)
    self.cancel_text = cancel_text
    for widget in (self._header, self._list, self._confirm, self._cancel):
      widget.set_enabled(lambda: self.enabled)

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, BACKGROUND)
    self._header.render(rl.Rectangle(rect.x, rect.y, rect.width, HEADER_HEIGHT))
    self._list.render(rl.Rectangle(rect.x, rect.y + HEADER_HEIGHT, rect.width, rect.height - HEADER_HEIGHT - 76))
    width = (rect.width - 36) / 2 if resolve(self.cancel_text) else rect.width - 24
    if resolve(self.cancel_text):
      self._cancel.render(rl.Rectangle(rect.x + 12, rect.y + rect.height - 70, width, 64))
    self._confirm.render(rl.Rectangle(rect.x + rect.width - width - 12, rect.y + rect.height - 70, width, 64))


class CompactNumberPage(CompactPage):
  def __init__(self, title, action, refresh: Callable, help_text):
    super().__init__(title)
    self.action, self.refresh = action, refresh
    self.allowed = lambda: self.action.enabled and self.action.is_visible
    self._minus = CompactButton("−", lambda: self.change(-1))
    self._plus = CompactButton("+", lambda: self.change(1))
    self._help = CompactButton(lambda: tr("Description"), lambda: gui_app.push_widget(CompactInfoPage(title, help_text, True)))
    self._header.action = self._help

  def change(self, direction):
    self.refresh()
    if self.allowed() and gui_app.get_active_widget() is self:
      value = max(self.action.min_value, min(self.action.max_value, self.action.current_value + direction * self.action.value_change_step))
      self.action.set_value(value)

  def _update_state(self):
    self.refresh()

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, BACKGROUND)
    self._header.render(rl.Rectangle(rect.x, rect.y, rect.width, HEADER_HEIGHT))
    value = self.action.get_displayed_value()
    gui_label(rl.Rectangle(rect.x + 110, rect.y + HEADER_HEIGHT + 12, rect.width - 220, 88), value, 48,
              alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)
    bounds = tr("Range: {minimum}–{maximum}").format(minimum=self._display(self.action.min_value), maximum=self._display(self.action.max_value))
    step_text = tr("Step: {step}").format(step=self.action.format_step())
    for index, line in enumerate((bounds, step_text)):
      gui_label(rl.Rectangle(rect.x + 16, rect.y + HEADER_HEIGHT + 112 + index * 32, rect.width - 32, 32),
                line, 28, MUTED, alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)
    for button, x, allowed in ((self._minus, rect.x + 12, self.action.current_value > self.action.min_value),
                               (self._plus, rect.x + rect.width - 100, self.action.current_value < self.action.max_value)):
      button.set_enabled(self.enabled and self.allowed() and allowed)
      button.render(rl.Rectangle(x, rect.y + HEADER_HEIGHT + 12, 88, 88))
    self._help.set_enabled(self.enabled)

  def _display(self, value):
    return self.action.format_value(value)


class CompactSelectPage(CompactPage):
  def __init__(self, title, choices, selected, choose, allowed=lambda _: True, refresh=lambda: None, help_text=None, searchable=False, search_terms=None):
    super().__init__(title)
    self.refresh = refresh
    self.choices = choices
    self._selected = selected
    self._focus_current = True
    self._query = ""
    self._search_language = multilang.language
    self._search_terms = search_terms or [""] * len(choices)
    self._rows = [
      CompactRow(lambda text=text: str(resolve(text)), value=lambda index=index: "✓" if index == selected() else "",
                 callback=lambda index=index: self._select(index, choose, allowed), enabled=lambda index=index: allowed(index),
                 help_callback=lambda: gui_app.push_widget(CompactInfoPage(title, help_text, True)) if help_text else None)
      for index, text in enumerate(choices)
    ]
    self._list.set_items(self._rows)
    if searchable:
      self._header.action = CompactButton(lambda: tr("Search"), self._search)
    elif help_text:
      self._header.action = CompactButton(lambda: tr("Description"), lambda: gui_app.push_widget(CompactInfoPage(title, help_text, True)))

  def _search(self):
    from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
    from openpilot.system.ui.widgets import DialogResult

    def result(status, query):
      if status == DialogResult.CONFIRM:
        self._query = query
        self._filter_rows()
        self._list._scroller.scroll_panel.set_offset(0)

    InputDialogSP(tr("Search"), current_text=self._query, callback=result).show()

  def _filter_rows(self):
    self._search_language = multilang.language
    rows = [row for row, terms in zip(self._rows, self._search_terms, strict=True)
            if self._query.casefold() in (str(resolve(row.title)) + " " + str(resolve(terms))).casefold()]
    self._list.set_items(rows or [CompactRow(lambda: tr("No matching options"), callback=self._search)])

  def _render(self, rect):
    if self._query and self._search_language != multilang.language:
      self._filter_rows()
    super()._render(rect)
    if self._focus_current:
      self._focus_current = False
      index = self._selected()
      if 0 <= index < len(self._rows):
        self._list.focus_item(self._rows[index])

  def _select(self, index, choose, allowed):
    self.refresh()
    if allowed(index) and gui_app.get_active_widget() is self:
      choose(index)
      gui_app.pop_widget()

  def _update_state(self):
    self.refresh()
