"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Scenario tests for Auto Lane Change: Road Edge Detection.

These tests simulate the model reporting a road edge too close to the vehicle on
the lane change side and verify:
  1. the road edge blocked flag is computed correctly (AutoLaneChangeController),
  2. a lane change (including a manual torque-initiated one) is intercepted
     (DesireHelper),
  3. the corresponding onroad event alert is wired up (EventsSP).
"""
from types import SimpleNamespace

from cereal import custom
from openpilot.common.params import Params
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.lib.desire_helper import DesireHelper, LaneChangeState, LaneChangeDirection
from openpilot.sunnypilot.selfdrive.controls.lib.auto_lane_change import AutoLaneChangeMode

EventNameSP = custom.OnroadEventSP.EventName

LANE_CHANGE_SPEED = 15.0  # m/s, comfortably above LANE_CHANGE_SPEED_MIN (~8.94 m/s)


def make_road_edges(left_y: float, right_y: float):
  """Build a fake modelV2.roadEdges structure.

  Each edge is a straight polyline spanning the car's longitudinal position (x=0).
  left_y/right_y are the lateral offsets (meters) of the left/right road edges.
  Left edge y is negative, right edge y is positive in the vehicle frame.
  """
  xs = [-10.0, 0.0, 10.0]
  left = SimpleNamespace(x=xs, y=[left_y] * 3)
  right = SimpleNamespace(x=xs, y=[right_y] * 3)
  return [left, right]


class DummyCarState:
  def __init__(self, vEgo=0.0, leftBlinker=False, rightBlinker=False, leftBlindspot=False,
               rightBlindspot=False, steeringPressed=False, steeringTorque=0.0, brakePressed=False):
    self.vEgo = vEgo
    self.leftBlinker = leftBlinker
    self.rightBlinker = rightBlinker
    self.leftBlindspot = leftBlindspot
    self.rightBlindspot = rightBlindspot
    self.steeringPressed = steeringPressed
    self.steeringTorque = steeringTorque
    self.brakePressed = brakePressed


class TestRoadEdgeDistance:
  """Unit tests for the road edge blocked flag in AutoLaneChangeController."""

  def setup_method(self):
    self.DH = DesireHelper()
    self.alc = self.DH.alc
    self.alc.lane_change_bsm_delay = False
    self.alc.lane_change_set_timer = AutoLaneChangeMode.NUDGELESS

  def test_flag_set_when_edge_close_left(self):
    """Left road edge within ROAD_EDGE_MIN_DISTANCE marks the change as blocked."""
    self.alc.road_edge_lca_blindspot = True
    self.DH.lane_change_direction = LaneChangeDirection.left
    edges = make_road_edges(left_y=-1.0, right_y=3.0)  # left distance = 1.0m < 1.5m
    self.alc.update_lane_change(blindspot_detected=False, brake_pressed=False, road_edges=edges)
    assert self.alc.road_edge_blocked

  def test_flag_set_when_edge_close_right(self):
    """Right road edge within ROAD_EDGE_MIN_DISTANCE marks the change as blocked."""
    self.alc.road_edge_lca_blindspot = True
    self.DH.lane_change_direction = LaneChangeDirection.right
    edges = make_road_edges(left_y=-3.0, right_y=1.0)  # right distance = 1.0m < 1.5m
    self.alc.update_lane_change(blindspot_detected=False, brake_pressed=False, road_edges=edges)
    assert self.alc.road_edge_blocked

  def test_flag_clear_when_edge_far(self):
    """A road edge farther than the threshold does not block the change."""
    self.alc.road_edge_lca_blindspot = True
    self.DH.lane_change_direction = LaneChangeDirection.left
    edges = make_road_edges(left_y=-3.0, right_y=3.0)  # left distance = 3.0m >= 1.5m
    self.alc.update_lane_change(blindspot_detected=False, brake_pressed=False, road_edges=edges)
    assert not self.alc.road_edge_blocked

  def test_flag_clear_when_toggle_off(self):
    """When the feature is disabled, even a very close edge is ignored."""
    self.alc.road_edge_lca_blindspot = False
    self.DH.lane_change_direction = LaneChangeDirection.left
    edges = make_road_edges(left_y=-0.5, right_y=3.0)  # very close but toggle off
    self.alc.update_lane_change(blindspot_detected=False, brake_pressed=False, road_edges=edges)
    assert not self.alc.road_edge_blocked

  def test_flag_clear_when_no_road_edges(self):
    """Missing road edge data must not block the change."""
    self.alc.road_edge_lca_blindspot = True
    self.DH.lane_change_direction = LaneChangeDirection.left
    self.alc.update_lane_change(blindspot_detected=False, brake_pressed=False, road_edges=None)
    assert not self.alc.road_edge_blocked

  def test_road_edge_delays_auto_lane_change_with_bsm_delay(self):
    """With BSM delay on, a close road edge behaves like a blindspot and delays the auto change."""
    self.alc.lane_change_bsm_delay = True
    self.alc.road_edge_lca_blindspot = True
    self.alc.lane_change_set_timer = AutoLaneChangeMode.NUDGELESS
    self.DH.lane_change_direction = LaneChangeDirection.left
    edges = make_road_edges(left_y=-1.0, right_y=3.0)

    self.alc.update_lane_change(blindspot_detected=False, brake_pressed=False, road_edges=edges)
    assert self.alc.road_edge_blocked
    assert not self.alc.auto_lane_change_allowed

    # Keep the edge close: auto lane change must remain disallowed.
    for _ in range(int(2.0 / DT_MDL)):
      self.alc.update_lane_change(blindspot_detected=False, brake_pressed=False, road_edges=edges)
    assert not self.alc.auto_lane_change_allowed


class TestRoadEdgeLaneChangeIntegration:
  """End-to-end DesireHelper tests: a manual (torque) lane change must be intercepted."""

  def _drive(self, dh, carstate, road_edges, steps=5):
    for _ in range(steps):
      dh.update(carstate, lateral_active=True, lane_change_prob=0.0, road_edges=road_edges)

  def test_manual_lane_change_blocked_by_road_edge(self):
    """Driver nudges the wheel left, but a close left road edge keeps us in preLaneChange."""
    Params().put_bool("RoadEdgeLcaBlindspot", True)
    dh = DesireHelper()
    dh.alc.lane_change_set_timer = AutoLaneChangeMode.NUDGE  # no auto change; isolate the torque path
    carstate = DummyCarState(vEgo=LANE_CHANGE_SPEED, leftBlinker=True,
                             steeringPressed=True, steeringTorque=1.0)
    edges = make_road_edges(left_y=-1.0, right_y=3.0)  # left edge too close

    self._drive(dh, carstate, edges)

    assert dh.alc.road_edge_blocked
    assert dh.lane_change_state == LaneChangeState.preLaneChange

  def test_manual_lane_change_allowed_when_edge_clear(self):
    """Same nudge, but with a clear road edge the lane change starts normally."""
    Params().put_bool("RoadEdgeLcaBlindspot", True)
    dh = DesireHelper()
    dh.alc.lane_change_set_timer = AutoLaneChangeMode.NUDGE
    carstate = DummyCarState(vEgo=LANE_CHANGE_SPEED, leftBlinker=True,
                             steeringPressed=True, steeringTorque=1.0)
    edges = make_road_edges(left_y=-3.0, right_y=3.0)  # left edge far enough

    self._drive(dh, carstate, edges)

    assert not dh.alc.road_edge_blocked
    assert dh.lane_change_state == LaneChangeState.laneChangeStarting


class TestRoadEdgeEventAlert:
  """Verify the road edge alert is registered and can be emitted."""

  def test_road_edge_event_registered(self):
    from openpilot.sunnypilot.selfdrive.selfdrived.events import EVENTS_SP
    from openpilot.sunnypilot.selfdrive.selfdrived.events_base import ET
    assert EventNameSP.laneChangeRoadEdge in EVENTS_SP
    assert ET.WARNING in EVENTS_SP[EventNameSP.laneChangeRoadEdge]

  def test_road_edge_event_produces_alert(self):
    from openpilot.sunnypilot.selfdrive.selfdrived.events import EventsSP
    from openpilot.sunnypilot.selfdrive.selfdrived.events_base import ET
    events_sp = EventsSP()
    events_sp.add(EventNameSP.laneChangeRoadEdge)
    alerts = events_sp.create_alerts([ET.WARNING])
    assert len(alerts) == 1
    assert alerts[0].alert_text_1  # non-empty alert text is shown to the driver

  def test_model_message_carries_flag(self):
    """The modelDataV2SP field selfdrived reads must round-trip the blocked flag."""
    msg = custom.ModelDataV2SP.new_message()
    msg.laneChangeEdgeBlocked = True
    assert msg.laneChangeEdgeBlocked
