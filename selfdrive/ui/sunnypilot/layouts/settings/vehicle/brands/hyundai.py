"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle.brands.base import BrandSettings
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import multiple_button_item_sp
from opendbc.car.hyundai.values import CAR, UNSUPPORTED_LONGITUDINAL_CAR


class HyundaiSettings(BrandSettings):
  def __init__(self):
    super().__init__()
    self.alpha_long_available = False

    tuning_texts = [lambda: tr("Off"), lambda: tr("Dynamic"), lambda: tr("Predictive")]
    self.longitudinal_tuning_item = multiple_button_item_sp(lambda: tr("Custom Longitudinal Tuning"), "", tuning_texts,
                                                            button_width=300, callback=self._on_tuning_selected,
                                                            inline=False)
    self.items = [self.longitudinal_tuning_item]

  def _on_tuning_selected(self, index):
    self.update_settings()
    if self.longitudinal_tuning_item.is_visible and self.longitudinal_tuning_item.action_item.enabled and index in (0, 1, 2):
      ui_state.params.put("HyundaiLongitudinalTuning", index, block=True)
      self.longitudinal_tuning_item.action_item.set_selected_button(index)

  def update_settings(self):
    self.alpha_long_available = False
    bundle = ui_state.params.get("CarPlatformBundle")
    if isinstance(bundle, dict) and bundle.get("brand") == "hyundai":
      platform = bundle.get("platform")
      car_platform = CAR.__members__.get(platform) if isinstance(platform, str) else None
      self.alpha_long_available = car_platform is not None and car_platform not in set().union(*UNSUPPORTED_LONGITUDINAL_CAR.values())
    elif bundle is None and ui_state.CP is not None and ui_state.CP.brand == "hyundai":
      self.alpha_long_available = ui_state.CP.alphaLongitudinalAvailable

    tuning_param = int(ui_state.params.get("HyundaiLongitudinalTuning") or "0")
    long_enabled = ui_state.has_longitudinal_control

    long_tuning_descs = [
      tr("Your vehicle will use the Default longitudinal tuning."),
      tr("Your vehicle will use the Dynamic longitudinal tuning."),
      tr("Your vehicle will use the Predictive longitudinal tuning."),
    ]
    long_tuning_desc = long_tuning_descs[tuning_param] if 0 <= tuning_param < len(long_tuning_descs) else long_tuning_descs[0]

    longitudinal_tuning_disabled = not ui_state.is_offroad() or not long_enabled
    if longitudinal_tuning_disabled:
      if not ui_state.is_offroad():
        long_tuning_desc = tr("This feature is unavailable while the car is onroad.")
      elif not long_enabled:
        long_tuning_desc = tr("This feature is unavailable because sunnypilot Longitudinal Control (Alpha) is not enabled.")

    self.longitudinal_tuning_item.action_item.set_enabled(self.is_current("hyundai") and self.alpha_long_available and not longitudinal_tuning_disabled)
    self.longitudinal_tuning_item.set_description(long_tuning_desc)
    self.longitudinal_tuning_item.show_description(True)
    self.longitudinal_tuning_item.action_item.set_selected_button(tuning_param)
    self.longitudinal_tuning_item.set_visible(self.alpha_long_available)
