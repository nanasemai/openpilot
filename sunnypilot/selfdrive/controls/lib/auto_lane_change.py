"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import numpy as np

from cereal import log
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL

# Threshold: minimum lateral distance (meters) from car center to road edge
# to allow a lane change. Approx half lane width (~1.8m).
ROAD_EDGE_MIN_DISTANCE = 1.5


class AutoLaneChangeMode:
  OFF = -1
  NUDGE = 0  # default
  NUDGELESS = 1
  HALF_SECOND = 2
  ONE_SECOND = 3
  TWO_SECONDS = 4
  THREE_SECONDS = 5


AUTO_LANE_CHANGE_TIMER = {
  AutoLaneChangeMode.OFF: 0.0,            # Off
  AutoLaneChangeMode.NUDGE: 0.0,          # Nudge
  AutoLaneChangeMode.NUDGELESS: 0.05,     # Nudgeless
  AutoLaneChangeMode.HALF_SECOND: 0.5,    # 0.5-second delay
  AutoLaneChangeMode.ONE_SECOND: 1.0,     # 1-second delay
  AutoLaneChangeMode.TWO_SECONDS: 2.0,    # 2-second delay
  AutoLaneChangeMode.THREE_SECONDS: 3.0,  # 3-second delay
}

ONE_SECOND_DELAY = -1


def _road_edge_distance(road_edges, direction):
  """Calculate lateral distance from car center to the road edge on the lane change side.

  Args:
    road_edges: modelV2.roadEdges (list of 2 road edge polylines)
    direction: LaneChangeDirection (left or right)

  Returns:
    float: lateral distance in meters, or None if data unavailable
  """
  # road_edges[0] = left, road_edges[1] = right
  idx = 0 if direction == log.LaneChangeDirection.left else 1

  if len(road_edges) <= idx or len(road_edges[idx].x) == 0 or len(road_edges[idx].y) == 0:
    return None

  # Find the road edge y-value closest to x=0 (car's longitudinal position)
  xs = np.array(road_edges[idx].x)
  ys = np.array(road_edges[idx].y)

  # Interpolate y at x=0
  if xs[0] > 0 or xs[-1] < 0:
    return None  # road edge doesn't span the car's position

  y_at_car = float(np.interp(0.0, xs, ys))
  # For left edge (idx=0): distance = -y (since left edge y is negative)
  # For right edge (idx=1): distance = y (since right edge y is positive)
  if direction == log.LaneChangeDirection.left:
    return -y_at_car  # positive means room to the left
  else:
    return y_at_car   # positive means room to the right


class AutoLaneChangeController:
  def __init__(self, desire_helper):
    self.DH = desire_helper
    self.params = Params()

    self.lane_change_wait_timer = 0.0
    self.param_read_counter = 0
    self.lane_change_delay = 0.0

    self.lane_change_set_timer = self.params.get("AutoLaneChangeTimer", return_default=True)
    self.lane_change_bsm_delay = False
    self.road_edge_lca_blindspot = False

    self.prev_brake_pressed = False
    self.auto_lane_change_allowed = False
    self.prev_lane_change = False
    self.road_edge_blocked = False

    self.read_params()

  def reset(self) -> None:
    # Auto reset if parent state indicates we should
    if self.DH.lane_change_state == log.LaneChangeState.off and \
       self.DH.lane_change_direction == log.LaneChangeDirection.none:
      self.lane_change_wait_timer = 0.0
      self.prev_brake_pressed = False
      self.prev_lane_change = False
      self.road_edge_blocked = False

  def read_params(self) -> None:
    self.lane_change_bsm_delay = self.params.get_bool("AutoLaneChangeBsmDelay")
    self.lane_change_set_timer = self.params.get("AutoLaneChangeTimer", return_default=True)
    self.road_edge_lca_blindspot = self.params.get_bool("RoadEdgeLcaBlindspot")

  def update_params(self) -> None:
    if self.param_read_counter % 50 == 0:
      self.read_params()
    self.param_read_counter += 1

  def update_lane_change_timers(self, blindspot_detected: bool) -> None:
    self.lane_change_delay = AUTO_LANE_CHANGE_TIMER.get(self.lane_change_set_timer,
                                                        AUTO_LANE_CHANGE_TIMER[AutoLaneChangeMode.NUDGE])

    self.lane_change_wait_timer += DT_MDL

    if self.lane_change_bsm_delay and blindspot_detected and self.lane_change_delay > 0:
      if self.lane_change_delay == AUTO_LANE_CHANGE_TIMER[AutoLaneChangeMode.NUDGELESS]:
        self.lane_change_wait_timer = ONE_SECOND_DELAY
      else:
        self.lane_change_wait_timer = self.lane_change_delay + ONE_SECOND_DELAY

  def update_allowed(self) -> bool:
    if self.lane_change_set_timer in (AutoLaneChangeMode.OFF, AutoLaneChangeMode.NUDGE):
      return False

    if self.prev_brake_pressed:
      return False

    if self.prev_lane_change:
      return False

    return bool(self.lane_change_wait_timer > self.lane_change_delay)

  def _check_road_edge_blocked(self, road_edges, direction):
    """Check if road edge on the lane change side is too close."""
    if not self.road_edge_lca_blindspot or road_edges is None:
      return False

    distance = _road_edge_distance(road_edges, direction)
    if distance is None:
      return False

    return distance < ROAD_EDGE_MIN_DISTANCE

  def update_lane_change(self, blindspot_detected: bool, brake_pressed: bool,
                         road_edges=None) -> None:
    if brake_pressed and not self.prev_brake_pressed:
      self.prev_brake_pressed = brake_pressed

    # Combine blindspot detection with road edge detection
    self.road_edge_blocked = self._check_road_edge_blocked(road_edges, self.DH.lane_change_direction)
    combined_blindspot = blindspot_detected or self.road_edge_blocked

    self.update_lane_change_timers(combined_blindspot)

    self.auto_lane_change_allowed = self.update_allowed()

  def update_state(self):
    if self.DH.lane_change_state == log.LaneChangeState.laneChangeStarting:
      self.prev_lane_change = True

    self.reset()
