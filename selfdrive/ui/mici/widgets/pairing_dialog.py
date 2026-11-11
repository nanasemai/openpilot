import pyray as rl
import qrcode
import numpy as np
import time
from urllib.parse import urlencode

from openpilot.common.api import Api
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.button import Button, ButtonStyle
from openpilot.system.ui.lib.multilang import tr


class PairingDialog(NavWidget):
  """Dialog for device pairing with QR code."""

  QR_REFRESH_INTERVAL = 300  # 5 minutes in seconds

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._qr_texture: rl.Texture | None = None
    self._qr_modules = 0
    self._last_qr_generation = float("-inf")
    self._qr_error = False
    self._pairing_open = False
    self._last_identity: str | None = None

    self._pair_label = UnifiedLabel(lambda: tr("PAIR") + "\ncomma connect", font_size=32, font_weight=FontWeight.BOLD)
    self._instruction_label = UnifiedLabel(lambda: tr("Unable to create QR code") if self._qr_error else tr("Scan with your phone"),
                                           font_size=28, font_weight=FontWeight.MEDIUM)
    self._retry_button = self._child(Button(lambda: tr("Retry"), click_callback=self._retry_qr,
                                            font_size=32, button_style=ButtonStyle.PRIMARY))
    self._retry_button.set_visible(lambda: self._qr_error)
    self._retry_button.set_touch_valid_callback(lambda: self._pairing_open and self.enabled and not self.is_dismissing)

  def show_event(self):
    super().show_event()
    self._pairing_open = True
    self._last_qr_generation = float("-inf")
    self._qr_error = False

  def hide_event(self):
    self._pairing_open = False
    super().hide_event()
    self.close()

  def close(self):
    if self._qr_texture and self._qr_texture.id != 0 and rl.is_window_ready():
      rl.unload_texture(self._qr_texture)
    self._qr_texture = None
    self._qr_modules = 0

  def _retry_qr(self):
    if self._pairing_open and self.enabled and self._qr_error and gui_app.get_active_widget() is self and not self.is_dismissing:
      self._last_qr_generation = float("-inf")

  def _pairing_identity(self) -> str | None:
    return self._params.get("DongleId")

  def _get_pairing_url(self) -> str:
    dongle_id = self._params.get("DongleId")
    if not dongle_id or dongle_id == UNREGISTERED_DONGLE_ID:
      raise ValueError("Device is not registered")
    token = Api(dongle_id).get_token({'pair': True})
    if not isinstance(token, str) or not token.strip():
      raise ValueError("Pairing token is unavailable")
    return f"https://connect.comma.ai/?{urlencode({'pair': token})}"

  def _generate_qr_code(self) -> None:
    try:
      qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
      qr.add_data(self._get_pairing_url())
      qr.make(fit=True)

      pil_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')
      img_array = np.array(pil_img, dtype=np.uint8)

      rl_image = rl.Image()
      rl_image.data = rl.ffi.cast("void *", img_array.ctypes.data)
      rl_image.width = pil_img.width
      rl_image.height = pil_img.height
      rl_image.mipmaps = 1
      rl_image.format = rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8

      texture = rl.load_texture_from_image(rl_image)
      if not texture.id:
        raise RuntimeError("QR texture could not be loaded")
      self.close()
      self._qr_texture = texture
      self._qr_modules = len(qr.get_matrix())
      rl.set_texture_filter(texture, rl.TextureFilter.TEXTURE_FILTER_POINT)
      self._qr_error = False
    except Exception:
      cloudlog.exception("Pairing QR code generation failed")
      self.close()
      self._qr_error = True

  def _check_qr_refresh(self) -> None:
    if self.is_dismissing:
      return
    current_time = time.monotonic()
    identity = self._pairing_identity()
    if identity != self._last_identity or current_time - self._last_qr_generation >= self.QR_REFRESH_INTERVAL:
      self._generate_qr_code()
      self._last_qr_generation = current_time
      self._last_identity = identity

  def _update_state(self):
    if not self._pairing_open:
      return
    super()._update_state()
    if ui_state.prime_state.is_paired() and gui_app.get_active_widget() is self and not self.is_dismissing:
      self.dismiss()

  def _render(self, rect: rl.Rectangle):
    if not self._pairing_open:
      return
    self._check_qr_refresh()

    qr_size = min(rect.height - 20, rect.width * 0.43)
    self._render_qr_code(rl.Rectangle(rect.x + 8, rect.y + 20, qr_size, qr_size))

    label_x = rect.x + qr_size + 28
    label_width = rect.width - (label_x - rect.x) - 12
    self._pair_label.render(rl.Rectangle(label_x, rect.y + 20, label_width, 80))
    self._instruction_label.render(rl.Rectangle(label_x, rect.y + 102, label_width, 66))
    self._retry_button.render(rl.Rectangle(label_x, rect.y + rect.height - 72, label_width, 64))

  def _render_qr_code(self, rect: rl.Rectangle) -> None:
    if not self._qr_texture:
      rl.draw_rectangle_rounded(rect, 0.08, 12, rl.Color(32, 32, 32, 255))
      return

    source = rl.Rectangle(0, 0, self._qr_texture.width, self._qr_texture.height)
    # Uniform whole pixels keep every QR module distinct on the small display.
    size = max(1, int(rect.width // self._qr_modules)) * self._qr_modules
    destination = rl.Rectangle(round(rect.x + (rect.width - size) / 2), round(rect.y + (rect.height - size) / 2), size, size)
    rl.draw_rectangle_rec(rect, rl.WHITE)
    rl.draw_texture_pro(self._qr_texture, source, destination, rl.Vector2(0, 0), 0, rl.WHITE)

  def __del__(self):
    self.close()


if __name__ == "__main__":
  gui_app.init_window("pairing device")
  pairing = PairingDialog()
  gui_app.push_widget(pairing)
  try:
    for _ in gui_app.render():
      pass
  finally:
    del pairing
