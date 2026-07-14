"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

# Acceleration Profile (SPAccelProfile): 0 standard, 1 eco, 2 sport, 3 comfort
ACCEL_PROFILE_LABELS = ["标准", "节能", "运动", "舒适"]

# Read params at low frequency since they rarely change
UPDATE_INTERVAL = 30  # frames (~1.5s at 20fps)


class _Chip(Widget):
  """A single clickable label chip that cycles through the values of an int param."""

  LABEL_SIZE = 30
  VALUE_SIZE = 40
  PADDING_X = 24
  PADDING_Y = 14
  GAP = 8

  def __init__(self, title: str, labels: list[str], param: str):
    super().__init__()
    self._params = Params()
    self._title = title
    self._labels = labels
    self._param = param
    self._value = 0
    self._frame = 0

    self._font_semi_bold = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_bold = gui_app.font(FontWeight.BOLD)

  def _read_value(self) -> None:
    try:
      val = self._params.get(self._param, return_default=True)
      self._value = int(val) % len(self._labels)
    except (TypeError, ValueError):
      self._value = 0

  def _update_state(self) -> None:
    # Low frequency polling; params rarely change and backend updates sync back here
    if self._frame % UPDATE_INTERVAL == 0:
      self._read_value()
    self._frame += 1

  def _handle_mouse_release(self, mouse_pos: MousePos) -> None:
    super()._handle_mouse_release(mouse_pos)
    self._value = (self._value + 1) % len(self._labels)
    self._params.put(self._param, self._value)

  def measure(self) -> rl.Vector2:
    title_w = measure_text_cached(self._font_semi_bold, self._title, self.LABEL_SIZE).x
    value_w = measure_text_cached(self._font_bold, self._labels[self._value], self.VALUE_SIZE).x
    width = max(title_w, value_w) + self.PADDING_X * 2
    height = self.LABEL_SIZE + self.VALUE_SIZE + self.GAP + self.PADDING_Y * 2
    return rl.Vector2(width, height)

  def _render(self, rect: rl.Rectangle) -> None:
    bg = rl.Color(0, 0, 0, 140 if self.is_pressed else 100)
    rl.draw_rectangle_rounded(rect, 0.25, 10, bg)

    title_text = self._title
    title_w = measure_text_cached(self._font_semi_bold, title_text, self.LABEL_SIZE).x
    title_pos = rl.Vector2(rect.x + (rect.width - title_w) / 2, rect.y + self.PADDING_Y)
    rl.draw_text_ex(self._font_semi_bold, title_text, title_pos, self.LABEL_SIZE, 0, rl.Color(200, 200, 200, 255))

    value_text = self._labels[self._value]
    value_w = measure_text_cached(self._font_bold, value_text, self.VALUE_SIZE).x
    value_pos = rl.Vector2(rect.x + (rect.width - value_w) / 2, rect.y + self.PADDING_Y + self.LABEL_SIZE + self.GAP)
    rl.draw_text_ex(self._font_bold, value_text, value_pos, self.VALUE_SIZE, 0, rl.WHITE)


class DriveStyleRenderer(Widget):
  """Bottom-left Acceleration Profile chip.

  Clickable to cycle its value, effective immediately (backend polls the param).
  Positioned above the bottom developer UI bar to avoid overlap.
  """

  MARGIN = 30
  BOTTOM_BAR_HEIGHT = 61

  def __init__(self):
    super().__init__()
    self._accel_chip = self._child(_Chip("加速", ACCEL_PROFILE_LABELS, "SPAccelProfile"))

  def _render(self, rect: rl.Rectangle) -> None:
    if not ui_state.has_longitudinal_control:
      return

    accel_size = self._accel_chip.measure()

    x = rect.x + self.MARGIN
    # Bottom anchored, above the developer UI bottom bar
    bottom = rect.y + rect.height - self.MARGIN - self.BOTTOM_BAR_HEIGHT

    accel_rect = rl.Rectangle(x, bottom - accel_size.y, accel_size.x, accel_size.y)
    self._accel_chip.render(accel_rect)

  def user_interacting(self) -> bool:
    return self._accel_chip.is_pressed
