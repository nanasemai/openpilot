"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from enum import IntEnum

from openpilot.system.timezone_list import TZ_LIST, tz_name
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.sunnypilot.widgets.list_view import option_item_sp, toggle_item_sp
from openpilot.sunnypilot.system.params_migration import ONROAD_BRIGHTNESS_TIMER_VALUES


class OnroadBrightness(IntEnum):
  AUTO = 0
  AUTO_DARK = 1
  SCREEN_OFF = 2


def duration_label(seconds):
  if seconds < 60:
    return tr("{seconds} s").format(seconds=seconds)
  minutes, remainder = divmod(seconds, 60)
  if remainder:
    return tr("{minutes} min {seconds} s").format(minutes=minutes, seconds=remainder)
  return tr("{minutes} min").format(minutes=minutes)


class DisplayLayout(Widget):
  def __init__(self):
    super().__init__()

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._onroad_brightness = option_item_sp(
      param="OnroadScreenOffBrightness",
      title=lambda: tr("Onroad Brightness"),
      description=lambda: tr("Choose automatic brightness, a darker automatic mode, screen off, or a fixed brightness. " +
                             "Touching a dimmed screen restores normal brightness; the first touch only wakes the screen. " +
                             "Alerts also restore normal brightness. Dark automatic mode returns after 15 seconds without interaction."),
      min_value=0,
      max_value=22,
      value_change_step=1,
      label_callback=lambda value: self.update_onroad_brightness(value),
      inline=True
    )
    self._onroad_brightness_timer = option_item_sp(
      param="OnroadScreenOffTimer",
      title=lambda: tr("Onroad Brightness Delay"),
      description=lambda: tr("Delay before applying the selected brightness after the last screen interaction. " +
                             "The countdown pauses outside the driving view and restarts when you return. " +
                             "This delay is unavailable in automatic brightness modes."),
      min_value=0,
      max_value=15,
      value_change_step=1,
      value_map=ONROAD_BRIGHTNESS_TIMER_VALUES,
      label_callback=duration_label,
      inline=True
    )
    self._interactivity_timeout = option_item_sp(
      param="InteractivityTimeout",
      title=lambda: tr("Interactivity Timeout"),
      description=lambda: tr("Time without screen interaction before leaving settings, or turning off the screen while parked. " +
                             "Changes apply immediately and restart the timeout.") +
                             ("<br><br>" + tr("On the small display, settings stay open while the vehicle is at standstill.") if not gui_app.big_ui() else ""),
      min_value=0,
      max_value=120,
      value_change_step=10,
      label_callback=lambda value: tr("Default") if not value else duration_label(value),
      inline=True
    )
    self._show_time_toggle = toggle_item_sp(
      title=lambda: tr("Show Date and Time"),
      description=lambda: tr("Display the current date and time at the top center of the onroad screen."),
      param="dp_show_date_time",
      initial_state=True
    )
    self._timezone_item = option_item_sp(
      title=lambda: tr("Timezone"),
      description=lambda: tr("The onroad clock uses the selected timezone immediately. The system timezone is updated within one minute. " +
                             "Daylight saving time is applied automatically where available."),
      param="Timezone",
      min_value=0,
      max_value=len(TZ_LIST) - 1,
      value_change_step=1,
      label_callback=lambda v: tr(tz_name(v)),
      inline=True
    )
    items = [
      self._onroad_brightness,
      self._onroad_brightness_timer,
      self._interactivity_timeout,
      self._show_time_toggle,
      self._timezone_item,
    ]
    return items

  @staticmethod
  def update_onroad_brightness(val):
    if val == OnroadBrightness.AUTO:
      return tr("Auto (Default)")

    if val == OnroadBrightness.AUTO_DARK:
      return tr("Auto (Dark)")

    if val == OnroadBrightness.SCREEN_OFF:
      return tr("Screen Off")

    return f"{(val - 2) * 5} %"

  def _update_state(self):
    super()._update_state()

    brightness_val = self._onroad_brightness.action_item.current_value
    self._onroad_brightness_timer.action_item.set_enabled(brightness_val not in (OnroadBrightness.AUTO, OnroadBrightness.AUTO_DARK))

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
