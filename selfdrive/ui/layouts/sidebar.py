import pyray as rl
from dataclasses import dataclass
from collections.abc import Callable
from cereal import log
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

SIDEBAR_WIDTH = 300
METRIC_HEIGHT = 110
METRIC_WIDTH = 240
METRIC_MARGIN = 30
METRIC_START_Y = 290
FONT_SIZE = 35

# Temperature smoothing / sanity limits
MAX_VALID_TEMP = 120.0  # ignore obviously bad sensor readings above this
TEMP_FILTER_RC = 5.0    # low-pass time constant (seconds) to smooth startup spikes

SETTINGS_BTN = rl.Rectangle(50, 35, 200, 117)

NetworkType = log.DeviceState.NetworkType


# Color scheme
class Colors:
  WHITE = rl.WHITE
  WHITE_DIM = rl.Color(255, 255, 255, 85)
  GRAY = rl.Color(84, 84, 84, 255)

  # Status colors
  GOOD = rl.Color(0, 153, 102, 255)
  WARNING = rl.Color(218, 202, 37, 255)
  DANGER = rl.Color(201, 34, 49, 255)

  # UI elements
  METRIC_BORDER = rl.Color(255, 255, 255, 85)
  BUTTON_NORMAL = rl.WHITE
  BUTTON_PRESSED = rl.Color(255, 255, 255, 166)


NETWORK_TYPES = {
  NetworkType.none: tr_noop("--"),
  NetworkType.wifi: tr_noop("Wi-Fi"),
  NetworkType.ethernet: tr_noop("ETH"),
  NetworkType.cell2G: tr_noop("2G"),
  NetworkType.cell3G: tr_noop("3G"),
  NetworkType.cell4G: tr_noop("LTE"),
  NetworkType.cell5G: tr_noop("5G"),
}


@dataclass(slots=True)
class MetricData:
  label: str
  value: str
  color: rl.Color

  def update(self, label: str, value: str, color: rl.Color):
    self.label = label
    self.value = value
    self.color = color


class Sidebar(Widget):
  def __init__(self):
    Widget.__init__(self)
    self._net_type = NETWORK_TYPES.get(NetworkType.none)
    self._net_strength = 0

    self._panda_status = MetricData(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)
    self._temp_status = MetricData(tr_noop("TEMP"), tr_noop("GOOD"), Colors.GOOD)
    self._cpu_status = MetricData(tr_noop("CPU"), tr_noop("--"), Colors.GOOD)
    self._mem_status = MetricData(tr_noop("MEM"), tr_noop("--"), Colors.GOOD)
    self._disk_status = MetricData(tr_noop("DISK"), tr_noop("--"), Colors.GOOD)
    self._gps_status = MetricData(tr_noop("GPS"), tr_noop("SEARCH"), Colors.WARNING)
    self._recording_audio = False

    # Low-pass filter for CPU temperature to smooth out startup spikes
    self._temp_filter = FirstOrderFilter(0.0, TEMP_FILTER_RC, 1.0 / gui_app.target_fps, initialized=False)

    self._settings_img = gui_app.texture("images/button_settings.png", SETTINGS_BTN.width, SETTINGS_BTN.height)
    self._mic_img = gui_app.texture("icons/microphone.png", 30, 30)
    self._mic_indicator_rect = rl.Rectangle(0, 0, 0, 0)
    self._font_regular = gui_app.font(FontWeight.NORMAL)
    self._font_bold = gui_app.font(FontWeight.SEMI_BOLD)

    # Callbacks
    self._on_settings_click: Callable | None = None
    self._on_flag_click: Callable | None = None
    self._open_settings_callback: Callable | None = None

  def set_callbacks(self, on_settings: Callable | None = None, on_flag: Callable | None = None,
                    open_settings: Callable | None = None):
    self._on_settings_click = on_settings
    self._on_flag_click = on_flag
    self._open_settings_callback = open_settings

  def _render(self, rect: rl.Rectangle):
    # Background
    rl.draw_rectangle_rec(rect, rl.BLACK)

    self._draw_buttons(rect)
    self._draw_network_indicator(rect)
    self._draw_metrics(rect)

  def _update_state(self):
    sm = ui_state.sm

    self._recording_audio = ui_state.recording_audio
    self._update_panda_status()
    self._update_gps_status()

    if not sm.updated['deviceState']:
      return

    device_state = sm['deviceState']
    self._update_network_status(device_state)
    self._update_temperature_status(device_state)
    self._update_cpu_status(device_state)
    self._update_memory_status(device_state)
    self._update_disk_status(device_state)

  def _update_network_status(self, device_state):
    self._net_type = NETWORK_TYPES.get(device_state.networkType.raw, tr_noop("Unknown"))
    strength = device_state.networkStrength
    self._net_strength = max(0, min(5, strength.raw + 1)) if strength.raw > 0 else 0

  def _update_temperature_status(self, device_state):
    # Filter out invalid / obviously wrong sensor readings (e.g. startup spikes)
    temps = [t for t in device_state.cpuTempC if 0 < t < MAX_VALID_TEMP]
    if temps:
      raw_temp = sum(temps) / len(temps)
      cpu_temp = self._temp_filter.update(raw_temp)
    else:
      cpu_temp = self._temp_filter.x

    if cpu_temp >= 75.0:
      color = Colors.DANGER
    elif cpu_temp >= 60.0:
      color = Colors.WARNING
    else:
      color = Colors.GOOD
    self._temp_status.update(tr_noop("TEMP"), f"{cpu_temp:.1f}\u00b0C", color)

  def _update_cpu_status(self, device_state):
    usages = list(device_state.cpuUsagePercent)
    cpu_usage = sum(usages) / len(usages) if usages else 0.0

    if cpu_usage > 75:
      color = Colors.DANGER
    elif cpu_usage > 55:
      color = Colors.WARNING
    else:
      color = Colors.GOOD
    self._cpu_status.update(tr_noop("CPU"), f"{cpu_usage:.1f}%", color)

  def _update_memory_status(self, device_state):
    mem_usage = device_state.memoryUsagePercent

    if mem_usage > 85:
      color = Colors.DANGER
    elif mem_usage > 70:
      color = Colors.WARNING
    else:
      color = Colors.GOOD
    self._mem_status.update(tr_noop("MEM"), f"{mem_usage:.1f}%", color)

  def _update_disk_status(self, device_state):
    disk_usage = 100.0 - device_state.freeSpacePercent

    if disk_usage > 90:
      color = Colors.DANGER
    elif disk_usage > 80:
      color = Colors.WARNING
    else:
      color = Colors.GOOD
    self._disk_status.update(tr_noop("DISK"), f"{disk_usage:.1f}%", color)

  def _update_panda_status(self):
    if ui_state.panda_type == log.PandaState.PandaType.unknown:
      self._panda_status.update(tr_noop("NO"), tr_noop("PANDA"), Colors.DANGER)
    else:
      self._panda_status.update(tr_noop("VEHICLE"), tr_noop("ONLINE"), Colors.GOOD)

  def _update_gps_status(self):
    gps = ui_state.sm['gpsLocationExternal']
    if gps.hasFix:
      accuracy = min(99.0, gps.horizontalAccuracy)
      self._gps_status.update(tr_noop("GPS"), f"{accuracy:.2f} m", Colors.GOOD)
    else:
      self._gps_status.update(tr_noop("GPS"), tr_noop("SEARCH"), Colors.WARNING)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN):
      if self._on_settings_click:
        self._on_settings_click()
    elif self._recording_audio and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect):
      if self._open_settings_callback:
        self._open_settings_callback()

  def _draw_buttons(self, rect: rl.Rectangle):
    mouse_pos = rl.get_mouse_position()
    mouse_down = self.is_pressed and rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)

    # Settings button
    settings_down = mouse_down and rl.check_collision_point_rec(mouse_pos, SETTINGS_BTN)
    tint = Colors.BUTTON_PRESSED if settings_down else Colors.BUTTON_NORMAL
    rl.draw_texture_ex(self._settings_img, rl.Vector2(SETTINGS_BTN.x, SETTINGS_BTN.y), 0.0, 1.0, tint)

    # Microphone button
    if self._recording_audio:
      self._mic_indicator_rect = rl.Rectangle(rect.x + rect.width - 130, rect.y + 245, 75, 40)

      mic_pressed = mouse_down and rl.check_collision_point_rec(mouse_pos, self._mic_indicator_rect)
      bg_color = rl.Color(Colors.DANGER.r, Colors.DANGER.g, Colors.DANGER.b, int(255 * 0.65)) if mic_pressed else Colors.DANGER

      rl.draw_rectangle_rounded(self._mic_indicator_rect, 1, 10, bg_color)
      rl.draw_texture_ex(self._mic_img, rl.Vector2(self._mic_indicator_rect.x + (self._mic_indicator_rect.width - self._mic_img.width) / 2,
                         self._mic_indicator_rect.y + (self._mic_indicator_rect.height - self._mic_img.height) / 2), 0.0, 1.0, Colors.WHITE)

  def _draw_network_indicator(self, rect: rl.Rectangle):
    # Signal strength dots
    x_start = rect.x + 58
    y_pos = rect.y + 196
    dot_size = 27
    dot_spacing = 37

    for i in range(5):
      color = Colors.WHITE if i < self._net_strength else Colors.GRAY
      x = int(x_start + i * dot_spacing + dot_size // 2)
      y = int(y_pos + dot_size // 2)
      rl.draw_circle(x, y, dot_size // 2, color)

    # Network type text
    text_y = rect.y + 247
    text_pos = rl.Vector2(rect.x + 58, text_y)
    rl.draw_text_ex(self._font_regular, tr(self._net_type), text_pos, FONT_SIZE, 0, Colors.WHITE)

  def _draw_metrics(self, rect: rl.Rectangle):
    metrics = [
      self._panda_status,
      self._temp_status,
      self._cpu_status,
      self._mem_status,
      self._disk_status,
      self._gps_status,
    ]

    start_y = int(rect.y) + METRIC_START_Y
    bottom = int(rect.y + rect.height) - METRIC_MARGIN
    available_height = max(0, bottom - METRIC_HEIGHT - start_y)
    spacing = available_height / max(1, len(metrics) - 1)

    for idx, metric in enumerate(metrics):
      self._draw_metric(rect, metric, start_y + idx * spacing)

  def _draw_metric(self, rect: rl.Rectangle, metric: MetricData, y: float):
    metric_rect = rl.Rectangle(rect.x + METRIC_MARGIN, y, METRIC_WIDTH, METRIC_HEIGHT)
    # Draw colored left edge (clipped rounded rectangle)
    edge_rect = rl.Rectangle(metric_rect.x + 4, metric_rect.y + 4, 100, metric_rect.height - 8)
    rl.begin_scissor_mode(int(metric_rect.x + 4), int(metric_rect.y), 18, int(metric_rect.height))
    rl.draw_rectangle_rounded(edge_rect, 0.3, 10, metric.color)
    rl.end_scissor_mode()

    # Draw border
    rl.draw_rectangle_rounded_lines_ex(metric_rect, 0.3, 10, 2, Colors.METRIC_BORDER)

    # Draw label and value
    labels = [tr(metric.label), tr(metric.value)]
    text_y = metric_rect.y + (metric_rect.height / 2 - len(labels) * FONT_SIZE * FONT_SCALE)
    for text in labels:
      text_size = measure_text_cached(self._font_bold, text, FONT_SIZE)
      text_y += text_size.y
      text_pos = rl.Vector2(
        metric_rect.x + 22 + (metric_rect.width - 22 - text_size.x) / 2,
        text_y
      )
      rl.draw_text_ex(self._font_bold, text, text_pos, FONT_SIZE, 0, Colors.WHITE)
