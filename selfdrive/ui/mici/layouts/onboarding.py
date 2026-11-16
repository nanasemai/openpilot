import math
import weakref
import numpy as np
import qrcode
import pyray as rl
from collections.abc import Callable
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.button import SmallCircleIconButton
from openpilot.system.ui.widgets.scroller import NavScroller, Scroller
from openpilot.system.ui.widgets.nav_widget import NavWidget
from openpilot.system.ui.mici_setup import GreyBigButton, BigPillButton
from openpilot.system.ui.widgets.label import gui_label
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.version import terms_version, training_version, terms_version_sp
from openpilot.system.version import sunnylink_consent_version, sunnylink_consent_declined
from openpilot.selfdrive.ui.ui_state import ui_state, device
from openpilot.selfdrive.ui.mici.widgets.dialog import BigConfirmationCircleButton
from openpilot.selfdrive.ui.mici.onroad.driver_state import DriverStateRenderer
from openpilot.selfdrive.ui.mici.onroad.driver_camera_dialog import BaseDriverCameraDialog
from openpilot.selfdrive.ui.sunnypilot.mici.layouts.onboarding import SunnylinkConsentPage


class DriverCameraSetupDialog(BaseDriverCameraDialog):
  def __init__(self):
    super().__init__()
    self.driver_state_renderer = DriverStateRenderer(inset=True)
    self.driver_state_renderer.set_rect(rl.Rectangle(0, 0, 120, 120))
    self.driver_state_renderer.load_icons()
    self.driver_state_renderer.set_force_active(True)

  def _render(self, rect):
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    self._camera_view._render(rect)

    if not self._camera_view.frame:
      gui_label(rect, tr("camera starting"), font_size=64, font_weight=FontWeight.BOLD,
                alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)
      rl.end_scissor_mode()
      return

    # Position dmoji on opposite side from driver
    is_rhd = self.driver_state_renderer.is_rhd
    self.driver_state_renderer.set_position(
      rect.x + 8 if is_rhd else rect.x + rect.width - self.driver_state_renderer.rect.width - 8,
      rect.y + 8,
    )
    self.driver_state_renderer.render()

    self._draw_face_detection(rect)

    rl.end_scissor_mode()


class TrainingGuidePreDMTutorial(NavScroller):
  def __init__(self, continue_callback: Callable[[], None]):
    super().__init__()

    continue_button = BigPillButton(tr("next"))
    continue_button.set_click_callback(continue_callback)

    self._scroller.add_widgets([
      GreyBigButton(tr("driver monitoring\ncheck"), tr("scroll to continue"),
                    gui_app.texture("icons_mici/setup/green_dm.png", 64, 64)),
      GreyBigButton("", tr("Next, we'll check if comma four can detect the driver properly.")),
      GreyBigButton("", tr("sunnypilot uses the cabin camera to check if the driver is distracted.")),
      GreyBigButton("", tr("If it does not have a clear view of the driver, unplug and remount before continuing.")),
      continue_button,
    ])

  def show_event(self):
    super().show_event()
    # Get driver monitoring model ready for next step
    ui_state.params.put_bool("IsDriverViewEnabled", True, block=True)

  def hide_event(self):
    super().hide_event()
    ui_state.params.put_bool("IsDriverViewEnabled", False, block=True)


class DMBadFaceDetected(NavScroller):
  def __init__(self):
    super().__init__()

    back_button = BigPillButton(tr("back"))
    back_button.set_click_callback(self.dismiss)

    self._scroller.add_widgets([
      GreyBigButton(tr("looking for driver"), tr("make sure comma\nfour can see your face"),
                    gui_app.texture("icons_mici/setup/orange_dm.png", 64, 64)),
      GreyBigButton("", tr("Remount if your face is blocked, or driver monitoring has difficulty tracking your face.")),
      back_button,
    ])


class TrainingGuideDMTutorial(NavWidget):
  PROGRESS_DURATION = 4
  LOOKING_THRESHOLD_DEG = 30.0

  def __init__(self, continue_callback: Callable[[], None], timeout_owner: Widget | None = None):
    super().__init__()
    self._dm_open = False
    self._opened_frame = 0
    self._previous_timeout: int | None = None
    self._timeout_owner = weakref.ref(timeout_owner) if timeout_owner is not None else None

    self._back_button = SmallCircleIconButton(gui_app.texture("icons_mici/setup/driver_monitoring/dm_question.png", 28, 48))
    self._back_button.set_click_callback(lambda: gui_app.push_widget(self._bad_face_page))
    self._back_button.set_touch_valid_callback(lambda: self.enabled and not self.is_dismissing)  # for nav stack
    self._good_button = SmallCircleIconButton(gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 42, 42))
    self._good_button.set_touch_valid_callback(lambda: self.enabled and not self.is_dismissing)  # for nav stack

    self._good_button.set_click_callback(continue_callback)
    self._good_button.set_enabled(False)

    self._progress = FirstOrderFilter(0.0, 0.5, 1 / gui_app.target_fps)
    self._dialog = DriverCameraSetupDialog()
    self._bad_face_page = DMBadFaceDetected()

  def show_event(self):
    super().show_event()
    self._dm_open = True
    self._opened_frame = getattr(ui_state.sm, 'frame', 0)
    self._previous_timeout = device._override_interactive_timeout
    self._dialog.show_event()
    device.add_interactive_timeout_callback(self._on_timeout)
    self._progress.x = 0.0
    self._good_button.set_enabled(False)

  def hide_event(self):
    super().hide_event()
    self.close()

  def close(self):
    if self._dm_open:
      self._dm_open = False
      device.remove_interactive_timeout_callback(self._on_timeout)
      self._dialog.hide_event()
      if self._timeout_owner is None or gui_app.widget_in_stack(self._timeout_owner()):
        device.set_override_interactive_timeout(self._previous_timeout)
    self._dialog.close()

  def _on_timeout(self):
    if self._dm_open:
      ui_state.params.put_bool("IsDriverViewEnabled", False, block=True)

  def _update_state(self):
    if not self._dm_open:
      return
    super()._update_state()
    if not self._dm_open:
      return
    if device.awake and not ui_state.params.get_bool("IsDriverViewEnabled"):
      ui_state.params.put_bool("IsDriverViewEnabled", True)

    sm = ui_state.sm
    if (self._dialog._camera_view.frame is None or
        sm.recv_frame.get("driverMonitoringState", 0) <= self._opened_frame or
        sm.recv_frame.get("driverStateV2", 0) <= self._opened_frame):
      self._progress.x = 0.0
      self._good_button.set_enabled(False)
      return

    dm_state = sm["driverMonitoringState"]
    driver_data = self._dialog.driver_state_renderer.get_driver_data()

    if len(driver_data.faceOrientation) == 3:
      pitch, yaw, _ = driver_data.faceOrientation
      looking_center = abs(math.degrees(pitch)) < self.LOOKING_THRESHOLD_DEG and abs(math.degrees(yaw)) < self.LOOKING_THRESHOLD_DEG
    else:
      looking_center = False

    # stay at 100% once reached
    in_bad_face = gui_app.get_active_widget() == self._bad_face_page
    if ((dm_state.visionPolicyState.faceDetected and looking_center) or self._progress.x > 0.99) and not in_bad_face:
      slow = self._progress.x < 0.25
      duration = self.PROGRESS_DURATION * 2 if slow else self.PROGRESS_DURATION
      self._progress.x += 1.0 / (duration * gui_app.target_fps)
      self._progress.x = min(1.0, self._progress.x)
    else:
      self._progress.update(0.0)

    self._good_button.set_enabled(self._progress.x >= 0.999)

  def _render(self, _):
    if not self._dm_open:
      return
    self._dialog.render(self._rect)

    gradient_y = int(self._rect.y + self._rect.height - 80)
    gradient_h = int(self._rect.y) + int(self._rect.height) - gradient_y
    rl.draw_rectangle_gradient_v(int(self._rect.x), gradient_y,
                                 int(self._rect.width), gradient_h, rl.BLANK, rl.BLACK)

    # draw white ring around dm icon to indicate progress
    ring_thickness = 8

    # DM icon is 120x120, positioned on opposite side from driver
    dm_size = 120
    is_rhd = self._dialog.driver_state_renderer._is_rhd
    dm_center_x = (self._rect.x + dm_size / 2 + 8) if is_rhd else (self._rect.x + self._rect.width - dm_size / 2 - 8)
    dm_center_y = self._rect.y + dm_size / 2 + 8
    icon_edge_radius = dm_size / 2
    outer_radius = icon_edge_radius + 1  # 2px outward from icon edge
    inner_radius = outer_radius - ring_thickness  # Inset by ring_thickness
    start_angle = 90.0  # Start from bottom
    end_angle = start_angle + self._progress.x * 360.0  # Clockwise

    # Fade in alpha
    current_angle = end_angle - start_angle
    alpha = int(np.interp(current_angle, [0.0, 45.0], [0, 255]))

    # White to green
    color_t = np.clip(np.interp(current_angle, [45.0, 360.0], [0.0, 1.0]), 0.0, 1.0)
    r = int(np.interp(color_t, [0.0, 1.0], [255, 0]))
    g = int(np.interp(color_t, [0.0, 1.0], [255, 255]))
    b = int(np.interp(color_t, [0.0, 1.0], [255, 64]))
    ring_color = rl.Color(r, g, b, alpha)

    rl.draw_ring(
      rl.Vector2(dm_center_x, dm_center_y),
      inner_radius,
      outer_radius,
      start_angle,
      end_angle,
      36,
      ring_color,
    )

    if self._dialog._camera_view.frame:
      self._back_button.render(rl.Rectangle(
        self._rect.x + 8,
        self._rect.y + self._rect.height - self._back_button.rect.height,
        self._back_button.rect.width,
        self._back_button.rect.height,
      ))

      self._good_button.render(rl.Rectangle(
        self._rect.x + self._rect.width - self._good_button.rect.width - 8,
        self._rect.y + self._rect.height - self._good_button.rect.height,
        self._good_button.rect.width,
        self._good_button.rect.height,
      ))

    # rounded border
    rl.begin_scissor_mode(int(self._rect.x), int(self._rect.y), int(self._rect.width), int(self._rect.height))
    rl.draw_rectangle_rounded_lines_ex(self._rect, 0.2 * 1.02, 10, 50, rl.BLACK)
    rl.end_scissor_mode()


class TrainingGuideRecordFront(NavScroller):
  def __init__(self, continue_callback: Callable[[], None]):
    super().__init__()

    def on_accept():
      ui_state.params.put_bool("RecordFront", True)
      continue_callback()

    def on_decline():
      ui_state.params.put_bool("RecordFront", False)
      continue_callback()

    self._accept_button = BigConfirmationCircleButton(tr("allow data uploading"), gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64),
                                                      on_accept, exit_on_confirm=False)

    self._decline_button = BigConfirmationCircleButton(tr("no, don't upload"), gui_app.texture("icons_mici/setup/cancel.png", 64, 64), on_decline,
                                                       exit_on_confirm=False)

    sharing_card = GreyBigButton("", tr("Sharing your data with comma helps improve openpilot and sunnypilot for everyone."))
    sharing_card.set_rect(rl.Rectangle(0, 0, 476, 210))

    self._scroller.add_widgets([
      GreyBigButton(tr("driver camera data"), tr("scroll to continue"),
                    gui_app.texture("icons_mici/setup/green_dm.png", 64, 64)),
      GreyBigButton("", tr("do you want to share video data for training?")),
      sharing_card,
      self._accept_button,
      self._decline_button,
    ])


class TrainingGuideAttentionNotice(Scroller):
  def __init__(self, continue_callback: Callable[[], None]):
    super().__init__()

    continue_button = BigPillButton(tr("next"))
    continue_button.set_click_callback(continue_callback)

    self._scroller.add_widgets([
      GreyBigButton(tr("what is sunnypilot?"), tr("scroll to continue"),
                    gui_app.texture("icons_mici/setup/green_info.png", 64, 64)),
      GreyBigButton("", tr("1. sunnypilot is a driver assistance system.")),
      GreyBigButton("", tr("2. You must pay attention at all times.")),
      GreyBigButton("", tr("3. You must be ready to take over at any time.")),
      GreyBigButton("", tr("4. You are fully responsible for driving the car.")),
      continue_button,
    ])


class TrainingGuide(NavWidget):
  def __init__(self, completed_callback: Callable[[], None], timeout_owner: Widget | None = None):
    super().__init__()

    self._steps = [
      TrainingGuideAttentionNotice(continue_callback=lambda: gui_app.push_widget(self._steps[1])),
      TrainingGuidePreDMTutorial(continue_callback=lambda: gui_app.push_widget(self._steps[2])),
      TrainingGuideDMTutorial(continue_callback=lambda: gui_app.push_widget(self._steps[3]),
                              timeout_owner=timeout_owner if timeout_owner is not None else self),
      TrainingGuideRecordFront(continue_callback=completed_callback),
    ]

    self._child(self._steps[0])
    self._steps[0].set_enabled(lambda: self.enabled and not self.is_dismissing)  # for nav stack

  def hide_event(self):
    super().hide_event()
    self._steps[2].close()

  def _render(self, _):
    self._steps[0].render(self._rect)


class QRCodeWidget(Widget):
  def __init__(self, url: str, size: int = 170):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, size, size))
    self._size = size
    self._url = url
    self._qr_texture: rl.Texture | None = None
    self._generate_qr(url)

  def show_event(self):
    super().show_event()
    if self._qr_texture is None:
      self._generate_qr(self._url)

  def hide_event(self):
    super().hide_event()
    self.close()

  def close(self):
    if self._qr_texture and self._qr_texture.id != 0 and rl.is_window_ready():
      rl.unload_texture(self._qr_texture)
    self._qr_texture = None

  def _generate_qr(self, url: str):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)

    pil_img = qr.make_image(fill_color="black", back_color="white").convert('RGBA')
    img_array = np.array(pil_img, dtype=np.uint8)

    rl_image = rl.Image()
    rl_image.data = rl.ffi.cast("void *", img_array.ctypes.data)
    rl_image.width = pil_img.width
    rl_image.height = pil_img.height
    rl_image.mipmaps = 1
    rl_image.format = rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8

    self._qr_texture = rl.load_texture_from_image(rl_image)
    self._qr_modules = len(qr.get_matrix())

  def _render(self, _):
    if self._qr_texture:
      size = max(1, self._size // self._qr_modules) * self._qr_modules
      destination = rl.Rectangle(round(self._rect.x + (self._size - size) / 2),
                                 round(self._rect.y + (self._size - size) / 2), size, size)
      rl.draw_rectangle_rec(rl.Rectangle(self._rect.x, self._rect.y, self._size, self._size), rl.WHITE)
      rl.draw_texture_pro(self._qr_texture, rl.Rectangle(0, 0, self._qr_texture.width, self._qr_texture.height),
                          destination, rl.Vector2(0, 0), 0, rl.WHITE)

  def __del__(self):
    self.close()


class TermsPage(Scroller):
  def __init__(self, on_accept, on_decline):
    super().__init__()

    self._accept_button = BigConfirmationCircleButton(tr("accept\nterms"),
                                                      gui_app.texture("icons_mici/setup/driver_monitoring/dm_check.png", 64, 64), on_accept)
    self._decline_button = BigConfirmationCircleButton(tr("decline &\nuninstall"), gui_app.texture("icons_mici/setup/cancel.png", 64, 64), on_decline,
                                                       red=True, exit_on_confirm=False)

    self._terms_header = GreyBigButton(tr("terms of\nservice"), tr("scroll to continue"),
                                       gui_app.texture("icons_mici/setup/green_info.png", 64, 64))
    self._must_accept_card = GreyBigButton("", tr("You must accept the Terms of Service to use sunnypilot."))
    self._terms_link_card = GreyBigButton(tr("swipe for QR code"), tr("or visit sunnypilot.ai/terms"),
                                          gui_app.texture("icons_mici/setup/small_slider/slider_arrow.png", 64, 56, flip_x=True))
    self._terms_link_card._sub_label.set_font_size(28)

    self._scroller.add_widgets([
      self._terms_header,
      self._terms_link_card,
      QRCodeWidget("https://sunnypilot.ai/terms"),
      self._must_accept_card,
      self._accept_button,
      self._decline_button,
    ])

  def _render(self, _):
    rl.draw_rectangle_rec(self._rect, rl.BLACK)
    super()._render(_)


class OnboardingWindow(Widget):
  def __init__(self, completed_callback: Callable[[], None]):
    super().__init__()
    self._completed_callback = completed_callback
    self._accepted_terms: bool = (ui_state.params.get("HasAcceptedTerms") == terms_version and
                                  ui_state.params.get("HasAcceptedTermsSP") == terms_version_sp)
    self._training_done: bool = ui_state.params.get("CompletedTrainingVersion") == training_version
    self._sunnylink_consent_done: bool = ui_state.params.get("CompletedSunnylinkConsentVersion") in {
      sunnylink_consent_version, sunnylink_consent_declined
    }

    self.set_rect(rl.Rectangle(0, 0, gui_app.width, gui_app.height))

    # Windows — all pushed onto nav stack, _terms is always rendered as base layer
    self._terms = TermsPage(on_accept=self._on_terms_accepted, on_decline=self._on_uninstall)
    self._terms.set_enabled(lambda: self.enabled)  # for nav stack

    self._sunnylink_consent = SunnylinkConsentPage(
      on_accept=self._on_sunnylink_accepted,
      on_decline=self._on_sunnylink_declined,
    )

    self._training_guide = TrainingGuide(completed_callback=self._on_completed_training, timeout_owner=self)
    self._training_guide.set_enabled(lambda: self.enabled)  # for nav stack

    self._needs_initial_push = False

  def _on_uninstall(self):
    ui_state.params.put_bool("DoUninstall", True, block=True)

  def show_event(self):
    super().show_event()
    device.set_override_interactive_timeout(300)
    device.set_offroad_brightness(100)
    self._needs_initial_push = True

  def hide_event(self):
    super().hide_event()
    # FIXME: when nav stack sends hide event to widget 2 below on push, this needs to be moved
    device.set_override_interactive_timeout(None)
    device.set_offroad_brightness(None)

  @property
  def completed(self) -> bool:
    return self._accepted_terms and self._sunnylink_consent_done and self._training_done

  def close(self):
    ui_state.params.put_bool("IsDriverViewEnabled", False)
    self._completed_callback()

  def _on_terms_accepted(self):
    ui_state.params.put("HasAcceptedTerms", terms_version, block=True)
    ui_state.params.put("HasAcceptedTermsSP", terms_version_sp, block=True)
    self._accepted_terms = True
    if not self._sunnylink_consent_done:
      gui_app.push_widget(self._sunnylink_consent)
    elif not self._training_done:
      gui_app.push_widget(self._training_guide)
    else:
      self.close()

  def _on_sunnylink_accepted(self):
    ui_state.params.put("CompletedSunnylinkConsentVersion", sunnylink_consent_version, block=True)
    ui_state.params.put_bool("SunnylinkEnabled", True)
    self._sunnylink_consent_done = True
    if not self._training_done:
      gui_app.push_widget(self._training_guide)
    else:
      self.close()

  def _on_sunnylink_declined(self):
    ui_state.params.put("CompletedSunnylinkConsentVersion", sunnylink_consent_declined, block=True)
    ui_state.params.put_bool("SunnylinkEnabled", False)
    self._sunnylink_consent_done = True
    if not self._training_done:
      gui_app.push_widget(self._training_guide)
    else:
      self.close()

  def _on_completed_training(self):
    ui_state.params.put("CompletedTrainingVersion", training_version, block=True)
    self._training_done = True
    self.close()

  def _render(self, _):
    rl.draw_rectangle_rec(self._rect, rl.BLACK)

    # Deferred from show_event to avoid nested push_widget re-enable bug
    if self._needs_initial_push:
      self._needs_initial_push = False
      if self._accepted_terms and not self._sunnylink_consent_done:
        gui_app.push_widget(self._sunnylink_consent)
      elif self._accepted_terms and self._sunnylink_consent_done and not self._training_done:
        gui_app.push_widget(self._training_guide)

    self._terms.render(self._rect)
