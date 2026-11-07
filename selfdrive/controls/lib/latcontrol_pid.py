import math

from cereal import log
from openpilot.selfdrive.controls.lib.latcontrol import LatControl
from openpilot.common.pid import PIDController


class LatControlPID(LatControl):
  def __init__(self, CP, CP_SP, CI, dt):
    super().__init__(CP, CP_SP, CI, dt)
    # Some PID platforms don't define a kd table. np.interp raises on an empty
    # breakpoint array, so fall back to an all-zero table (k_d == 0, no damping)
    # rather than crashing. Platforms that set kdV keep their tuning.
    kdBP, kdV = CP.lateralTuning.pid.kdBP, CP.lateralTuning.pid.kdV
    if len(kdBP) == 0 or len(kdV) == 0:
      kdBP, kdV = [0.], [0.]
    self.pid = PIDController((CP.lateralTuning.pid.kpBP, CP.lateralTuning.pid.kpV),
                             (CP.lateralTuning.pid.kiBP, CP.lateralTuning.pid.kiV),
                             k_d=(kdBP, kdV),
                             pos_limit=self.steer_max, neg_limit=-self.steer_max)
    self.ff_factor = CP.lateralTuning.pid.kf
    self.get_steer_feedforward = CI.get_steer_feedforward_function()
    # First-order low-pass on steering rate for the D term. The EPS angle-rate
    # signal carries enough sensor noise that an unfiltered derivative chatters
    # the actuator; this keeps the ~4.5 Hz damping band while rolling off
    # higher-frequency noise. alpha=0.5 @100Hz -> ~15 Hz cutoff.
    self._lp_alpha = 0.5
    self._rate_lp = 0.0

  def update(self, active, CS, VM, params, steer_limited_by_safety, desired_curvature, calibrated_pose, curvature_limited, lat_delay):
    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steeringAngleDeg = float(CS.steeringAngleDeg)
    pid_log.steeringRateDeg = float(CS.steeringRateDeg)

    angle_steers_des_no_offset = math.degrees(VM.get_steer_from_curvature(-desired_curvature, CS.vEgo, params.roll))
    angle_steers_des = angle_steers_des_no_offset + params.angleOffsetDeg
    error = angle_steers_des - CS.steeringAngleDeg

    pid_log.steeringAngleDesiredDeg = angle_steers_des
    pid_log.angleError = error
    if not active:
      output_torque = 0.0
      pid_log.active = False

    else:
      # offset does not contribute to resistive torque
      ff = self.ff_factor * self.get_steer_feedforward(angle_steers_des_no_offset, CS.vEgo)
      freeze_integrator = steer_limited_by_safety or CS.steeringPressed or CS.vEgo < 5

      # Derivative (damping) term. error = angle_desired - angle_actual, so
      # d(error)/dt ~= -steeringRateDeg when the path is smooth. Negating the
      # measured rate makes the D term oppose wheel motion (damping), which adds
      # phase margin against the low-speed limit cycle. Platforms without a kd
      # table have k_d == 0, so this path is inert for them.
      self._rate_lp = self._lp_alpha * CS.steeringRateDeg + (1.0 - self._lp_alpha) * self._rate_lp
      error_rate = -self._rate_lp

      output_torque = self.pid.update(error,
                                error_rate=error_rate,
                                feedforward=ff,
                                speed=CS.vEgo,
                                freeze_integrator=freeze_integrator)

      pid_log.active = True
      pid_log.p = float(self.pid.p)
      pid_log.i = float(self.pid.i)
      pid_log.f = float(self.pid.f)
      pid_log.output = float(output_torque)
      pid_log.saturated = bool(self._check_saturation(self.steer_max - abs(output_torque) < 1e-3, CS, steer_limited_by_safety, curvature_limited))

    return output_torque, angle_steers_des, pid_log
