"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.common.params import Params


class LatControlTorqueExtOverride:
  # Re-read the enable flag on this cadence rather than every tick, to keep the
  # Params() lookup off the hot path. The values themselves are applied every tick.
  PARAM_POLL_FRAMES = 300

  def __init__(self, CP):
    self.CP = CP
    self.params = Params()
    self.torque_override_enabled = self.params.get_bool("TorqueParamsOverrideEnabled")
    self.frame = -1

  def update_override_torque_params(self, torque_params) -> bool:
    # No EnforceTorqueControl gate: V0 is the default controller for every torque car
    # while that flag is False by default, so gating silently disabled the override.
    # Re-applied every tick because controlsd rewrites these from liveTorqueParameters.
    self.frame += 1
    if self.frame % self.PARAM_POLL_FRAMES == 0:
      self.torque_override_enabled = self.params.get_bool("TorqueParamsOverrideEnabled")

    if not self.torque_override_enabled:
      return False

    torque_params.latAccelFactor = float(self.params.get("TorqueParamsOverrideLatAccelFactor", return_default=True))
    torque_params.friction = float(self.params.get("TorqueParamsOverrideFriction", return_default=True))
    return True
