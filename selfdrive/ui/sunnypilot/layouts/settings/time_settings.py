from openpilot.system.timezone_list import TZ_LIST, tz_name
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, option_item_sp
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller


class TimeSettingsLayout(Widget):
  def __init__(self):
    super().__init__()
    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self._show_time_toggle = toggle_item_sp(
      title=lambda: tr("Show Date and Time"),
      description=lambda: tr("Display the current date and time at the top center of the onroad screen."),
      param="dp_show_date_time",
      initial_state=True
    )
    self._timezone_item = option_item_sp(
      title=lambda: tr("Timezone"),
      param="Timezone",
      min_value=0,
      max_value=len(TZ_LIST) - 1,
      value_change_step=1,
      label_callback=lambda v: tz_name(v),
      inline=True
    )
    return [self._show_time_toggle, self._timezone_item]

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
