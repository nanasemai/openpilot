"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import requests
import threading
import math
import pyray as rl

from openpilot.common.api import api_get
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.lib.api_helpers import get_token
from openpilot.selfdrive.ui.ui_state import ui_state, device
from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget


class TripsLayout(Widget):
  PARAM_KEY = "ApiCache_DriveStats"
  UPDATE_INTERVAL = 30  # seconds

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._session = requests.Session()
    self._status = tr_noop("Drive statistics unavailable")
    self._loading = False
    self._refresh_event = threading.Event()
    self._stats = self._get_stats()
    if self._stats:
      self._status = tr_noop("Cached drive statistics")

    self._icon_distance = gui_app.texture("icons/road.png", 100, 100, keep_aspect_ratio=True)
    self._icon_drives = gui_app.texture("icons_mici/wheel.png", 80, 80, keep_aspect_ratio=True)
    self._icon_hours = gui_app.texture("../../sunnypilot/selfdrive/assets/icons/clock.png", 80, 80, keep_aspect_ratio=True)

    self._running = True
    self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
    self._update_thread.start()

  def __del__(self):
    self._running = False
    self._refresh_event.set()
    try:
      if self._update_thread and self._update_thread.is_alive():
        self._update_thread.join(timeout=1.0)
    except Exception:
      pass

  def _get_stats(self):
    try:
      stats = self._params.get(self.PARAM_KEY)
      if stats is None:
        return {}
      return self._validate_stats(stats)
    except ValueError:
      self._status = tr_noop("Invalid drive statistics data")
      cloudlog.exception("Failed to decode drive stats")
      return {}

  @staticmethod
  def _validate_stats(stats):
    if not isinstance(stats, dict) or not any(period in stats for period in ("all", "week")):
      raise ValueError("Missing drive statistics periods")
    result = {}
    for period in ("all", "week"):
      if period not in stats:
        continue
      data = stats[period]
      if not isinstance(data, dict):
        raise ValueError("Invalid drive statistics period")
      values = {}
      for field in ("routes", "distance", "minutes"):
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
          raise ValueError("Invalid drive statistics value")
        if field == "routes" and int(value) != value:
          raise ValueError("Invalid route count")
        values[field] = int(value) if field == "routes" else value
      result[period] = values
    return result

  def request_refresh(self):
    if not self._loading and ui_state.is_offroad():
      self._refresh_event.set()

  def status(self):
    return tr(self._status)

  def _fetch_drive_stats(self):
    self._loading = True
    try:
      dongle_id = self._params.get("DongleId")
      if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
        self._status = tr_noop("Device is not registered")
        return
      self._status = tr_noop("Fetching drive statistics")
      identity_token = get_token(dongle_id)
      response = api_get(f"v1.1/devices/{dongle_id}/stats", access_token=identity_token, session=self._session)
      if response.status_code == 200:
        data = self._validate_stats(response.json())
        self._params.put(self.PARAM_KEY, data, block=True)
        self._stats = data
        self._status = tr_noop("Drive statistics updated")
      else:
        self._status = tr_noop("Unable to fetch drive statistics")
    except ValueError:
      self._status = tr_noop("Invalid drive statistics data")
      cloudlog.exception("Invalid drive statistics response")
    except Exception as e:
      self._status = tr_noop("Unable to fetch drive statistics")
      cloudlog.error(f"Failed to fetch drive stats: {e}")
    finally:
      self._loading = False

  def _update_loop(self):
    while self._running:
      self._refresh_event.clear()
      if ui_state.is_offroad() and device._awake:
        self._fetch_drive_stats()
      self._refresh_event.wait(self.UPDATE_INTERVAL)

  def _render_stat_group(self, x, y, width, height, title, data, is_metric):
    # Card Background
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, width, height), 0.05, 10, rl.Color(30, 30, 30, 255))

    # Title
    title_font = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(title_font, title, rl.Vector2(x + 60, y + 30), 50 * FONT_SCALE, 0, rl.Color(200, 200, 200, 255))

    # Internal content area
    # Center the content block (Icon + Value + Unit) vertically
    content_y = y + (height / 2) - (140 * FONT_SCALE)
    col_width = width / 3

    # Values
    number_font = gui_app.font(FontWeight.BOLD)
    unit_font = gui_app.font(FontWeight.NORMAL)
    number_base_size = 92
    unit_base_size = 55
    number_size = number_base_size * FONT_SCALE
    unit_size = unit_base_size * FONT_SCALE
    color_unit = rl.Color(160, 160, 160, 255)

    routes = int(data.get("routes", 0))
    distance = data.get("distance", 0)
    distance_str = str(int(distance * CV.MPH_TO_KPH)) if is_metric else str(int(distance))
    hours = int(data.get("minutes", 0) / 60)

    dist_unit = tr("KM") if is_metric else tr("Miles")

    def draw_col(col_idx, icon, value, unit):
      col_x = x + (col_width * col_idx)
      center_x = col_x + (col_width / 2)

      # Icon
      icon_x = center_x - (icon.width / 2)
      icon_y = content_y + 60
      rl.draw_texture_ex(icon, rl.Vector2(icon_x, icon_y), 0.0, 1.0, rl.WHITE)

      # Value
      val_size = measure_text_cached(number_font, value, number_base_size)
      rl.draw_text_ex(number_font, value, rl.Vector2(center_x - val_size.x / 1.65, content_y + 145 * FONT_SCALE), number_size, 0, rl.WHITE)

      # Unit
      unit_size_vec = measure_text_cached(unit_font, unit, unit_base_size)
      rl.draw_text_ex(unit_font, unit, rl.Vector2(center_x - unit_size_vec.x / 1.65, content_y + 255 * FONT_SCALE), unit_size, 0, color_unit)

    draw_col(0, self._icon_drives, str(routes), tr("Drives"))
    draw_col(1, self._icon_distance, distance_str, dist_unit)
    draw_col(2, self._icon_hours, str(hours), tr("Hours"))

    return y + height

  def _render(self, rect: rl.Rectangle):
    x = rect.x
    y = rect.y
    w = rect.width

    spacing = 30
    available_h = rect.height - 30
    card_height = available_h / 2

    is_metric = self._params.get_bool("IsMetric")

    all_time = self._stats.get("all", {})
    week = self._stats.get("week", {})

    y = self._render_stat_group(x, y, w, card_height, tr("ALL TIME"), all_time, is_metric)
    y += spacing
    y = self._render_stat_group(x, y, w, card_height, tr("PAST WEEK"), week, is_metric)
