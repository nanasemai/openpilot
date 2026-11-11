"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import base64
from urllib.parse import urlencode

import pyray as rl
from openpilot.selfdrive.ui.mici.widgets.pairing_dialog import PairingDialog
from openpilot.sunnypilot.sunnylink.api import SunnylinkApi, UNREGISTERED_SUNNYLINK_DONGLE_ID, API_HOST
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.nav_widget import NavWidget


class SunnylinkPairingDialog(PairingDialog):
  """Dialog for device pairing with QR code."""

  def __init__(self, sponsor_pairing: bool = False):
    PairingDialog.__init__(self)
    self._sponsor_pairing = sponsor_pairing
    self._pair_label.set_text(lambda: (tr("PAIR") + "\nsunnylink") if self._sponsor_pairing else (tr("SPONSOR") + "\nsunnypilot"))

  def _get_pairing_url(self) -> str:
    if not self._sponsor_pairing:
      return "https://github.com/sponsors/sunnyhaibin"
    sl_dongle_id = self._params.get("SunnylinkDongleId")
    if not sl_dongle_id or sl_dongle_id == UNREGISTERED_SUNNYLINK_DONGLE_ID:
      raise ValueError("Device is not registered with sunnylink")
    token = SunnylinkApi(sl_dongle_id).get_token()
    if not isinstance(token, str) or not token.strip():
      raise ValueError("Pairing token is unavailable")
    payload = base64.b64encode(f"1|{sl_dongle_id}|{token}".encode()).decode()
    return f"{API_HOST}/sso?{urlencode({'state': payload})}"

  def _pairing_identity(self) -> str | None:
    return self._params.get("SunnylinkDongleId") if self._sponsor_pairing else None

  def _update_state(self):
    if self._pairing_open:
      NavWidget._update_state(self)


if __name__ == "__main__":
  gui_app.init_window("pairing device")
  pairing = SunnylinkPairingDialog(sponsor_pairing=True)
  try:
    for _ in gui_app.render():
      result = pairing.render(rl.Rectangle(0, 0, gui_app.width, gui_app.height))
      if result != -1:
        break
  finally:
    del pairing
