"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import abc
from openpilot.selfdrive.ui.ui_state import ui_state


class BrandSettings(abc.ABC):
  def __init__(self):
    self.items = []

  @staticmethod
  def is_current(brand: str) -> bool:
    bundle = ui_state.params.get("CarPlatformBundle")
    if bundle is not None:
      return isinstance(bundle, dict) and bundle.get("brand") == brand
    return ui_state.CP is not None and ui_state.CP.brand == brand and ui_state.CP.carFingerprint != "MOCK"

  @abc.abstractmethod
  def update_settings(self) -> None:
    """Update the settings based on the current vehicle brand."""
