import datetime
import pyray as rl
from openpilot.common.params import Params
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


REFRESH_INTERVAL = 60


class TimeDisplay(Widget):
  def __init__(self):
    super().__init__()
    self._font = gui_app.font(FontWeight.BOLD)
    self._params = Params()
    self._frame_count = 0
    self._last_text = ""
    self._enabled = True

  def _update_state(self):
    self._frame_count += 1
    self._enabled = self._params.get_bool("dp_show_date_time")
    if self._frame_count % REFRESH_INTERVAL == 0 or not self._last_text:
      self._last_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

  def _render(self, rect: rl.Rectangle) -> None:
    if not self._enabled:
      return

    text = self._last_text
    if not text:
      text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
      self._last_text = text

    tsz = measure_text_cached(self._font, text, 30)
    x = rect.x + rect.width / 2 - tsz.x / 2
    y = rect.y + 20
    rl.draw_text_ex(self._font, text, rl.Vector2(x, y), 30, 0, rl.Color(255, 255, 255, 200))

  def set_rect(self, rect: rl.Rectangle) -> None:
    self._rect = rect
