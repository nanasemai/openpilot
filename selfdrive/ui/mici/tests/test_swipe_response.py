"""Short swipes follow the finger, settle quickly, and never invoke settings."""
import pytest
import pyray as rl

from openpilot.system.ui.lib.application import gui_app, MouseEvent, MousePos
from openpilot.system.ui.widgets.compact import CompactPage, CompactRow, CompactSwipeList
from openpilot.selfdrive.ui.mici.tests.test_settings import state, window, draw  # noqa: F401


@pytest.fixture
def pager(monkeypatch):
  monkeypatch.setattr(rl, 'get_frame_time', lambda: 1 / 60)
  calls = []
  page = CompactPage('Settings')
  page._list = CompactSwipeList()
  page._list.set_enabled(lambda: page.enabled)
  page._list.set_items([CompactRow(str(index), callback=lambda: calls.append(True)) for index in range(6)])
  gui_app.push_widget(page)
  draw(page)
  return page, calls


def touch(x, t, y=150, down=False, up=False, slot=0):
  return MouseEvent(MousePos(x, y), slot, down, up, not up, t)


def frame(page, monkeypatch, events=()):
  monkeypatch.setattr(gui_app, '_mouse_events', list(events))
  draw(page)


def settle(page, monkeypatch, frames=24):
  for _ in range(frames):
    frame(page, monkeypatch)
  offset = page._list._scroller.scroll_panel.get_offset()
  assert abs(offset + page._list.page * 536) < 1


def test_first_drag_sample_moves_card_immediately(pager, monkeypatch):
  page, calls = pager
  frame(page, monkeypatch, [touch(350, 0, down=True)])
  frame(page, monkeypatch, [touch(334, .1)])
  assert page._list._scroller.scroll_panel.get_offset() == pytest.approx(-16)
  assert calls == []


@pytest.mark.parametrize('batched', [False, True])
@pytest.mark.parametrize('direction', [-1, 1])
def test_short_slow_swipe_changes_one_page_even_with_only_down_move_up(pager, monkeypatch, batched, direction):
  page, calls = pager
  page._list.page = 2
  frame(page, monkeypatch)
  events = [touch(250, 0, down=True), touch(250 + direction * 32, .2), touch(250 + direction * 64, .5, up=True)]
  for batch in ([events] if batched else [[event] for event in events]):
    frame(page, monkeypatch, batch)
  settle(page, monkeypatch)
  assert page._list.page == 2 - direction
  assert calls == []


@pytest.mark.parametrize('distance,duration,expected', [(40, .08, 1), (40, .6, 0), (8, .01, 0), (24, .01, 0)])
def test_deliberate_short_flick_is_distinct_from_slow_motion_and_finger_jitter(pager, monkeypatch, distance, duration, expected):
  page, calls = pager
  events = [touch(350, 0, down=True), touch(350 - distance / 2, duration / 2), touch(350 - distance, duration, up=True)]
  frame(page, monkeypatch, events)
  settle(page, monkeypatch)
  assert page._list.page == expected
  if distance > 12:
    assert calls == []


@pytest.mark.parametrize('positions', [(350, 375, 350), (350, 342, 350), (350, 200, 350)])
def test_drag_out_and_back_does_not_change_page_or_click(pager, monkeypatch, positions):
  page, calls = pager
  events = [touch(x, i * .2, down=i == 0, up=i == len(positions) - 1) for i, x in enumerate(positions)]
  frame(page, monkeypatch, events)
  settle(page, monkeypatch)
  assert page._list.page == 0
  if max(positions) - min(positions) > 12:
    assert calls == []


def test_vertical_drag_never_changes_horizontal_page_or_clicks(pager, monkeypatch):
  page, calls = pager
  events = [touch(250, 0, down=True), touch(210, .1, y=100), touch(170, .2, y=60, up=True)]
  frame(page, monkeypatch, events)
  settle(page, monkeypatch)
  assert page._list.page == 0
  assert calls == []


@pytest.mark.parametrize('start,distance,expected', [(0, 100, 0), (5, -100, 5), (2, -1100, 3)])
def test_edges_are_bounded_and_a_single_gesture_never_skips_multiple_pages(pager, monkeypatch, start, distance, expected):
  page, calls = pager
  page._list.page = start
  frame(page, monkeypatch)
  events = [touch(350, 0, down=True), touch(350 + distance / 2, .1), touch(350 + distance, .2, up=True)]
  frame(page, monkeypatch, events)
  settle(page, monkeypatch)
  assert page._list.page == expected
  assert calls == []


def test_tap_still_opens_a_card_once(pager, monkeypatch):
  page, calls = pager
  frame(page, monkeypatch, [touch(250, 0, down=True), touch(250, .1, up=True)])
  assert calls == [True]


def test_disabled_pager_ignores_a_swipe(pager, monkeypatch):
  page, calls = pager
  page.set_enabled(False)
  frame(page, monkeypatch, [touch(350, 0, down=True), touch(270, .1), touch(190, .2, up=True)])
  settle(page, monkeypatch)
  assert page._list.page == 0 and calls == []


def test_next_swipe_can_interrupt_settling_and_advance_the_next_page(pager, monkeypatch):
  page, calls = pager
  for t in (0, .2):
    frame(page, monkeypatch, [touch(350, t, down=True), touch(318, t + .05), touch(286, t + .1, up=True)])
  settle(page, monkeypatch)
  assert page._list.page == 2 and calls == []


def test_tap_during_animation_cannot_open_a_card_or_cancel_the_previous_swipe(pager, monkeypatch):
  page, calls = pager
  frame(page, monkeypatch, [touch(350, 0, down=True), touch(318, .05), touch(286, .1, up=True)])
  frame(page, monkeypatch, [touch(250, .12, down=True), touch(250, .16, up=True)])
  settle(page, monkeypatch)
  assert page._list.page == 1 and calls == []


def test_secondary_touch_does_not_move_pages_or_invoke_actions(pager, monkeypatch):
  page, calls = pager
  frame(page, monkeypatch, [touch(350, 0, down=True, slot=1), touch(270, .1, slot=1), touch(190, .2, up=True, slot=1)])
  settle(page, monkeypatch)
  assert page._list.page == 0 and calls == []


def test_hiding_during_settling_preserves_the_requested_page(pager, monkeypatch):
  page, calls = pager
  frame(page, monkeypatch, [touch(350, 0, down=True), touch(318, .05), touch(286, .1, up=True)])
  page._list.hide_event()
  page._list.show_event()
  settle(page, monkeypatch)
  assert page._list.page == 1 and calls == []


def test_swipe_can_start_on_the_page_indicator(pager, monkeypatch):
  page, calls = pager
  frame(page, monkeypatch, [touch(350, 0, y=232, down=True), touch(318, .2, y=232), touch(286, .5, y=232, up=True)])
  settle(page, monkeypatch)
  assert page._list.page == 1 and calls == []


def test_actual_main_and_secondary_settings_accept_short_swipes_without_writing(monkeypatch):
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP
  from openpilot.selfdrive.ui.ui_state import ui_state
  monkeypatch.setattr(rl, 'get_frame_time', lambda: 1 / 60)
  root = SettingsLayoutSP()
  gui_app.push_widget(root)
  frame(root, monkeypatch)
  events = [touch(350, 0, down=True), touch(318, .2), touch(286, .5, up=True)]
  frame(root, monkeypatch, events)
  settle(root, monkeypatch)
  assert root._list.page == 1 and gui_app.get_active_widget() is root
  root.buttons[1]._click_callback()
  group = gui_app.get_active_widget()
  group.focus_setting('steering', 'Mads')
  frame(group, monkeypatch)
  index = group._list.page
  before = ui_state.params.get_bool('Mads')
  frame(group, monkeypatch, events)
  settle(group, monkeypatch)
  assert group._list.page == index + 1
  assert gui_app.get_active_widget() is group
  assert ui_state.params.get_bool('Mads') == before
