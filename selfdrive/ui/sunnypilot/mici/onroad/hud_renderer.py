"""Small-screen driving overlays, with alerts taking priority over optional metrics."""
import time

import pyray as rl

from openpilot.common.constants import CV
from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer
from openpilot.selfdrive.ui.sunnypilot.onroad.blind_spot_indicators import BlindSpotIndicators
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.timezone_list import now_in_timezone
from openpilot.system.ui.widgets.label import gui_label


class HudRendererSP(HudRenderer):
  def __init__(self):
    super().__init__()
    self.blind_spot_indicators = BlindSpotIndicators()
    self._standstill_since = None
    self._notice_until = 0
    self._notice = ''

  def _update_state(self) -> None:
    super()._update_state()
    if ui_state.sm.recv_frame['carState'] < ui_state.started_frame:
      self._standstill_since = None
      self._notice_until = 0
      self._notice = ''
      self.blind_spot_indicators.reset()
      return
    self.blind_spot_indicators.update()
    cs = ui_state.sm['carState']
    conversion = CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH
    if ui_state.true_v_ego_ui:
      self.speed = max(0, cs.vEgo * conversion)
    now = time.monotonic()
    if ui_state.started and cs.standstill:
      if self._standstill_since is None:
        self._standstill_since = now
    else:
      self._standstill_since = None
    alerts = ui_state.sm['longitudinalPlanSP'].e2eAlerts
    if not ui_state.started or (self._notice and not ui_state.params.get_bool(self._notice)):
      self._notice_until = 0
      self._notice = ''
    if ui_state.started and alerts.greenLightAlert and ui_state.params.get_bool('GreenLightAlert'):
      self._notice = 'GreenLightAlert'
      self._notice_until = now + 3
    elif ui_state.started and alerts.leadDepartAlert and ui_state.params.get_bool('LeadDepartAlert'):
      self._notice = 'LeadDepartAlert'
      self._notice_until = now + 3

  def _render(self, rect: rl.Rectangle) -> None:
    # Keep the native wheel, set-speed and blind-spot warning placement.
    if ui_state.torque_bar and self._can_draw_top_icons:
      bottom = 24 if ui_state.developer_ui in (1, 3) else 0
      self._torque_bar.render(rl.Rectangle(rect.x, rect.y, rect.width, rect.height - bottom))
    if self.is_cruise_set:
      self._draw_set_speed(rect)
    self._draw_steering_wheel(rect)
    self.blind_spot_indicators.render(rect)
    if self._can_draw_top_icons and not self.drawing_top_icons():
      self._draw_optional(rect)

  def _draw_optional(self, rect):
    if ui_state.sm.recv_frame['carState'] < ui_state.started_frame:
      return
    cs = ui_state.sm['carState']
    if not ui_state.hide_v_ego_ui:
      label = f'{round(self.speed)} ' + (tr('km/h') if ui_state.is_metric else tr('mph'))
      self._label(rl.Rectangle(rect.x + rect.width - 106, rect.y + 8, 96, 32), label, 22)
    if ui_state.params.get_bool('dp_show_date_time'):
      self._label(rl.Rectangle(rect.x + 112, rect.y + 8, rect.width - 226, 26), now_in_timezone(ui_state.params).strftime('%Y-%m-%d %H:%M:%S'), 16)
    if ui_state.road_name_toggle:
      road = ui_state.sm['liveMapDataSP'].roadName
      if road:
        self._label(rl.Rectangle(rect.x + 112, rect.y + 40, rect.width - 226, 26), road, 18)
    if ui_state.turn_signals:
      for left, active in ((True, cs.leftBlinker), (False, cs.rightBlinker)):
        if active and int(time.monotonic() * 2) % 2 == 0:
          x = rect.x + (84 if left else rect.width - 84)
          direction = -1 if left else 1
          rl.draw_line_ex(rl.Vector2(x - direction * 12, rect.y + 80), rl.Vector2(x + direction * 12, rect.y + 80), 5, rl.GREEN)
          rl.draw_line_ex(rl.Vector2(x + direction * 12, rect.y + 80), rl.Vector2(x, rect.y + 70), 5, rl.GREEN)
          rl.draw_line_ex(rl.Vector2(x + direction * 12, rect.y + 80), rl.Vector2(x, rect.y + 90), 5, rl.GREEN)
    if ui_state.rocket_fuel:
      height = max(-60, min(60, cs.aEgo * 20))
      rl.draw_rectangle_rec(rl.Rectangle(rect.x + 8, rect.y + rect.height / 2 - max(0, height), 6, abs(height)),
                            rl.GREEN if height >= 0 else rl.RED)
    now = time.monotonic()
    if now < self._notice_until and self._notice and ui_state.params.get_bool(self._notice):
      text = tr('GREEN\nLIGHT') if self._notice == 'GreenLightAlert' else tr('LEAD VEHICLE\nDEPARTING')
      self._label(rl.Rectangle(rect.x + 116, rect.y + 90, rect.width - 232, 40), text.replace('\n', ' '), 22)
    elif ui_state.standstill_timer and self._standstill_since is not None:
      seconds = int(now - self._standstill_since)
      self._label(rl.Rectangle(rect.x + rect.width / 2 - 50, rect.y + 94, 100, 30), f'{seconds // 60}:{seconds % 60:02}', 22)
    if ui_state.developer_ui in (1, 3):
      text = f'{tr("Acceleration")}: {cs.aEgo:.2f} m/s²  ·  {tr("Steering Angle")}: {cs.steeringAngleDeg:.1f}°'
      self._label(rl.Rectangle(rect.x + 108, rect.y + rect.height - 28, rect.width - 124, 24), text, 16)
    if ui_state.developer_ui in (2, 3) and not self.blind_spot_indicators.detected:
      lead = ui_state.sm['radarState'].leadOne
      distance = lead.dRel if ui_state.is_metric else lead.dRel * 3.28084
      relative_speed = lead.vRel * (CV.MS_TO_KPH if ui_state.is_metric else CV.MS_TO_MPH)
      distance_unit = 'm' if ui_state.is_metric else 'ft'
      speed_unit = tr('km/h') if ui_state.is_metric else tr('mph')
      text = (f'{tr("Distance")}: {distance:.0f} {distance_unit}\n' +
              f'{tr("Relative Speed")}: {relative_speed:.0f} {speed_unit}') if lead.status else tr('No Lead Vehicle')
      self._label(rl.Rectangle(rect.x + rect.width - 180, rect.y + 144, 168, 26), text.split('\n')[0], 16)
      if '\n' in text:
        self._label(rl.Rectangle(rect.x + rect.width - 180, rect.y + 170, 168, 26), text.split('\n')[1], 16)

  @staticmethod
  def _label(rect, text, size):
    rl.draw_rectangle_rounded(rect, 0.2, 8, rl.Color(0, 0, 0, 150))
    gui_label(rl.Rectangle(rect.x + 4, rect.y, rect.width - 8, rect.height), text, size,
              alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)

  def _has_blind_spot_detected(self) -> bool:
    return self.blind_spot_indicators.detected
