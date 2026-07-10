"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.widgets.button import BigParamControl
from openpilot.system.ui.lib.multilang import tr


class DisplayLayoutMici(NavScroller):
  def __init__(self, back_callback=None):
    super().__init__()
    self._back_callback = back_callback
    # Switch to vertical layout after init (bypasses NavWidget MRO issue)
    self._scroller._horizontal = False
    self._scroller.scroll_panel._horizontal = False

    # Note: OnroadScreenOffBrightness and InteractivityTimeout are integer params,
    # not boolean toggles. MICI has no slider control yet, so they are omitted.
    self._scroller.add_widgets([])