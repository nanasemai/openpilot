"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl
import re
import time
from html import escape, unescape
from cereal import custom
from openpilot.selfdrive.ui.sunnypilot.layouts.onboarding import SunnylinkConsentPage
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.sunnylink.api import UNREGISTERED_SUNNYLINK_DONGLE_ID
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.system.ui.sunnypilot.widgets.list_view import button_item_sp
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp
from openpilot.system.ui.sunnypilot.widgets.sunnylink_pairing_dialog import SunnylinkPairingDialog
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.button import ButtonStyle, Button
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog, ConfirmDialog
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.list_view import dual_button_item
from openpilot.system.ui.widgets.scroller_tici import Scroller, LineSeparator
from openpilot.system.version import sunnylink_consent_version

SPONSOR_TIERS = {
  "FREE": tr_noop("Free"), "NOVICE": tr_noop("Novice"), "SUPPORTER": tr_noop("Supporter"),
  "CONTRIBUTOR": tr_noop("Contributor"), "BENEFACTOR": tr_noop("Benefactor"), "GUARDIAN": tr_noop("Guardian"),
}
TRANSFER_ERRORS = (tr_noop("Failed to upload backup"), tr_noop("Empty backup configuration"),
                   tr_noop("Failed to decrypt backup configuration"))


class SunnylinkHeader(Widget):
  def __init__(self):
    super().__init__()

    self._title = UnifiedLabel(
      text=tr("🚀 sunnylink 🚀"),
      font_size=90,
      font_weight=FontWeight.AUDIOWIDE,
      text_color=rl.WHITE,
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
      alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_TOP,
      wrap_text=False,
      elide=False
    )

    self._description = UnifiedLabel(
      text=tr("For secure backup, restore, and remote configuration"),
      font_size=40,
      font_weight=FontWeight.NORMAL,
      text_color=rl.Color(0, 255, 0, 255),  # Green
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
      alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_TOP,
      wrap_text=True,
      elide=False
    )

    self._sponsor_msg = UnifiedLabel(
      text=tr("Sponsorship isn't required for basic backup/restore") + "\n" +
           tr("Click the Sponsor button for more details"),
      font_size=35,
      font_weight=FontWeight.NORMAL,
      text_color=rl.Color(255, 165, 0, 255),  # Orange
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
      alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_TOP,
      wrap_text=True,
      elide=False
    )

    self._padding = 20
    self._spacing = 10

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)

    content_width = int(parent_rect.width - (self._padding * 2))

    title_height = self._title.get_content_height(content_width)
    desc_height = self._description.get_content_height(content_width)
    sponsor_height = self._sponsor_msg.get_content_height(content_width)

    total_height = (self._padding + title_height + self._spacing +
                    desc_height + self._spacing + sponsor_height + self._padding)

    self._rect.width = parent_rect.width
    self._rect.height = total_height

  def _render(self, rect: rl.Rectangle):
    content_width = rect.width - (self._padding * 2)
    current_y = rect.y + self._padding

    # Render title
    title_height = self._title.get_content_height(int(content_width))
    title_rect = rl.Rectangle(rect.x + self._padding, current_y, content_width, title_height)
    self._title.render(title_rect)
    current_y += title_height + self._spacing

    # Render description
    desc_height = self._description.get_content_height(int(content_width))
    desc_rect = rl.Rectangle(rect.x + self._padding, current_y, content_width, desc_height)
    self._description.render(desc_rect)
    current_y += desc_height + self._spacing

    # Render sponsor message
    sponsor_height = self._sponsor_msg.get_content_height(int(content_width))
    sponsor_rect = rl.Rectangle(rect.x + self._padding, current_y, content_width, sponsor_height)
    self._sponsor_msg.render(sponsor_rect)


class SunnylinkDescriptionItem(Widget):
  def __init__(self):
    super().__init__()
    self._description = UnifiedLabel(
      text="",
      font_size=40,
      font_weight=FontWeight.NORMAL,
      text_color=rl.WHITE,
      alignment=rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
      alignment_vertical=rl.GuiTextAlignmentVertical.TEXT_ALIGN_TOP,
      wrap_text=True,
      elide=False,
    )
    self._padding = 20

  def set_parent_rect(self, parent_rect: rl.Rectangle) -> None:
    super().set_parent_rect(parent_rect)
    desc_height = self._description.get_content_height(int(parent_rect.width)) + self._padding * 2

    self._rect.width = parent_rect.width
    self._rect.height = desc_height

  def set_text(self, text: str):
    self._description.set_text(text)

  def set_color(self, color: rl.Color):
    self._description.set_text_color(color)

  def _render(self, rect: rl.Rectangle):
    content_width = rect.width - (self._padding * 2)

    desc_height = self._description.get_content_height(int(content_width))
    desc_rect = rl.Rectangle(rect.x + self._padding, rect.y, content_width, desc_height)
    self._description.render(desc_rect)


class SunnylinkLayout(Widget):
  TRANSFER_WAIT_TIMEOUT = 30

  def __init__(self):
    super().__init__()

    self._sunnylink_pairing_dialog: SunnylinkPairingDialog | None = None
    self._restore_in_progress = False
    self._backup_in_progress = False
    self._sunnylink_enabled = ui_state.params.get("SunnylinkEnabled")
    self._transfer_kind = None
    self._transfer_message = tr_noop("Ready")
    self._transfer_progress = 0
    self._transfer_error = ""
    self._transfer_wait_started = None
    self._transfer_seen_running = False
    self._transfer_baseline = None
    self._transfer_frame = None
    self._restore_restart_pending = False

    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=False, spacing=0)

  def _initialize_items(self):
    self._sunnylink_toggle = toggle_item_sp(
      title=lambda: tr("Enable sunnylink"),
      description=lambda: tr("This is the master switch, it will allow you to cutoff any sunnylink requests should you want to do that."),
      param="SunnylinkEnabled",
      callback=self._sunnylink_toggle_callback
    )

    self._sunnylink_description = SunnylinkDescriptionItem()
    self._sunnylink_description.set_visible(False)

    self._sponsor_btn = button_item_sp(
      title=lambda: tr("Sponsor Status"),
      button_text=lambda: tr("SPONSOR"),
      description=lambda: tr(
        "Become a sponsor of sunnypilot to get early access to sunnylink features when they become available."),
      callback=lambda: self._handle_pair_btn(False)
    )
    self._pair_btn = button_item_sp(
      title=lambda: tr("Pair GitHub Account"),
      button_text=lambda: tr("Not Paired"),
      description=lambda: tr(
        "Pair your GitHub account to grant your device sponsor benefits, including API access on sunnylink."),
      callback=lambda: self._handle_pair_btn(True)
    )
    self._sunnylink_uploader_toggle = toggle_item_sp(
      title=lambda: tr("Enable sunnylink uploader (infrastructure test)"),
      description=lambda: tr("Enable sunnylink uploader to allow sunnypilot to upload your driving data to sunnypilot servers. ") +
                  tr("(Only for highest tiers, and does NOT bring ANY benefit to you yet. We are just testing data volume.)"),
      param="EnableSunnylinkUploader"
    )
    self._sunnylink_backup_restore_buttons = dual_button_item(
      description="",
      left_text=lambda: tr("Backup Settings"),
      right_text=lambda: tr("Restore Settings"),
      left_callback=self._handle_backup_btn,
      right_callback=self._handle_restore_btn
    )
    self._backup_btn: Button = self._sunnylink_backup_restore_buttons.action_item.left_button  # store for easy individual access
    self._restore_btn: Button = self._sunnylink_backup_restore_buttons.action_item.right_button
    self._backup_btn.set_button_style(ButtonStyle.NORMAL)
    self._restore_btn.set_button_style(ButtonStyle.PRIMARY)

    items = [
      SunnylinkHeader(),
      LineSeparator(),
      self._sunnylink_toggle,
      self._sunnylink_description,
      LineSeparator(),
      self._sponsor_btn,
      LineSeparator(),
      self._pair_btn,
      LineSeparator(),
      self._sunnylink_uploader_toggle,
      LineSeparator(),
      self._sunnylink_backup_restore_buttons
    ]
    return items

  @staticmethod
  def _get_sunnylink_dongle_id() -> str:
    return ui_state.params.get("SunnylinkDongleId") or tr("N/A")

  def _handle_pair_btn(self, sponsor_pairing: bool = False):
    sunnylink_dongle_id = self._get_sunnylink_dongle_id()
    if sunnylink_dongle_id == UNREGISTERED_SUNNYLINK_DONGLE_ID:
      gui_app.push_widget(alert_dialog(message=tr("sunnylink Dongle ID not found. ") +
                                                     tr("This may be due to weak internet connection or sunnylink registration issue. ") +
                                                     tr("Please reboot and try again.")))
    elif not self._sunnylink_pairing_dialog:
      self._sunnylink_pairing_dialog = SunnylinkPairingDialog(sponsor_pairing)
      gui_app.push_widget(self._sunnylink_pairing_dialog)

  def _handle_backup_btn(self):
    if not self._can_start_transfer("backup"):
      return
    backup_dialog = ConfirmDialog(text=tr("Are you sure you want to backup your current sunnypilot settings?"), confirm_text=tr("Backup"),
                                  callback=self._backup_handler)
    gui_app.push_widget(backup_dialog)

  def _handle_restore_btn(self):
    if self._restore_restart_pending:
      self._show_restore_restart()
      return
    if not self._can_start_transfer("restore"):
      return
    restore_dialog = ConfirmDialog(text=tr("Are you sure you want to restore the last backed up sunnypilot settings?"),
                                   confirm_text=tr("Restore"), callback=self._restore_handler)
    gui_app.push_widget(restore_dialog)

  def _backup_handler(self, dialog_result: int):
    if dialog_result == DialogResult.CONFIRM:
      self._start_transfer("backup")

  def _restore_handler(self, dialog_result: int):
    if dialog_result == DialogResult.CONFIRM:
      self._start_transfer("restore")

  @staticmethod
  def _transfer_snapshot(kind):
    manager = ui_state.sm["backupManagerSP"]
    return (getattr(manager, kind + "Status"), getattr(manager, kind + "Progress"), manager.lastError)

  @staticmethod
  def _transfer_service_alive():
    return getattr(ui_state.sm, "alive", {}).get("backupManagerSP", True)

  @staticmethod
  def _backend_busy():
    manager = ui_state.sm["backupManagerSP"]
    return SunnylinkLayout._transfer_service_alive() and (manager.backupStatus == custom.BackupManagerSP.Status.inProgress or
                                                         manager.restoreStatus == custom.BackupManagerSP.Status.inProgress)

  @staticmethod
  def _transfer_pending(kind):
    return (ui_state.params.get_bool("BackupManager_CreateBackup") if kind == "backup" else
            bool(ui_state.params.get("BackupManager_RestoreVersion")))

  def _waiting_timed_out(self):
    return (self._transfer_wait_started is not None and not self._transfer_seen_running and
            time.monotonic() - self._transfer_wait_started >= self.TRANSFER_WAIT_TIMEOUT)

  def _can_start_transfer(self, kind):
    if not ui_state.is_offroad() or not ui_state.params.get_bool("SunnylinkEnabled") or self._restore_restart_pending:
      return False
    if self._backend_busy():
      return False
    if self._backup_in_progress or self._restore_in_progress:
      return self._transfer_kind == kind and self._waiting_timed_out()
    return not (self._transfer_pending("backup") or self._transfer_pending("restore"))

  def _start_transfer(self, kind):
    if not self._can_start_transfer(kind):
      return
    self._transfer_kind = kind
    self._transfer_baseline = self._transfer_snapshot(kind)
    self._transfer_frame = getattr(ui_state.sm, "recv_frame", {}).get("backupManagerSP")
    self._transfer_wait_started = time.monotonic()
    self._transfer_seen_running = False
    self._transfer_progress = 0
    self._transfer_error = ""
    self._transfer_message = tr_noop("Waiting for backup service") if kind == "backup" else tr_noop("Waiting for restore service")
    self._sunnylink_description.set_visible(False)
    self._backup_in_progress = kind == "backup"
    self._restore_in_progress = kind == "restore"
    self._backup_btn.set_enabled(False)
    self._restore_btn.set_enabled(False)
    if kind == "backup":
      ui_state.params.put_bool("BackupManager_CreateBackup", True, block=True)
    else:
      ui_state.params.put("BackupManager_RestoreVersion", "latest", block=True)

  def _transfer_status(self):
    return tr(self._transfer_message).format(progress=int(self._transfer_progress))

  def _transfer_detail(self):
    error = self._transfer_error
    if not error:
      return tr("Backup and restore run in the background. If the service does not respond, retry after the waiting timeout.")
    if match := re.fullmatch(r"Failed to restore (\d+) settings", error):
      error = tr("Failed to restore {count} settings").format(count=match[1])
    elif match := re.fullmatch(r"No backup found for device (.+)", error):
      error = tr("No backup found for device {device}").format(device=match[1])
    else:
      error = tr(error)
    return escape(tr("Error: {error}").format(error=error))

  def _show_restore_restart(self):
    def restart(result):
      if result == DialogResult.CONFIRM and ui_state.is_offroad():
        gui_app.request_close()
    gui_app.push_widget(ConfirmDialog(tr("Settings restored. Confirm to restart the interface."), tr("Restart Interface"), callback=restart))

  def handle_backup_restore_progress(self):
    # Requests remain set until the backend finishes. Ignore old terminal messages
    # while waiting for a new operation; both progress fields share one value.
    if not (self._backup_in_progress or self._restore_in_progress or self._restore_restart_pending):
      if self._transfer_pending("backup") or self._transfer_pending("restore") or self._backend_busy():
        manager = ui_state.sm["backupManagerSP"]
        kind = "backup" if (self._transfer_pending("backup") or
                            (not self._transfer_pending("restore") and manager.backupStatus == custom.BackupManagerSP.Status.inProgress)) else "restore"
        self._transfer_kind = kind
        self._backup_in_progress, self._restore_in_progress = kind == "backup", kind == "restore"
        self._transfer_wait_started = time.monotonic()
        self._transfer_seen_running = False
        self._transfer_baseline = self._transfer_snapshot(kind)
        self._transfer_frame = getattr(ui_state.sm, "recv_frame", {}).get("backupManagerSP")
        self._transfer_message = tr_noop("Waiting for backup service") if kind == "backup" else tr_noop("Waiting for restore service")
    if self._backup_in_progress or self._restore_in_progress:
      kind = self._transfer_kind or ("backup" if self._backup_in_progress else "restore")
      status, progress, error = snapshot = self._transfer_snapshot(kind)
      frame = getattr(ui_state.sm, "recv_frame", {}).get("backupManagerSP")
      pending = self._transfer_pending(kind)
      live = self._transfer_service_alive()
      running = status == custom.BackupManagerSP.Status.inProgress and live
      fresh = live and (snapshot != self._transfer_baseline or (frame is not None and frame != self._transfer_frame))
      if not live and self._transfer_seen_running:
        self._transfer_seen_running = False
        self._transfer_wait_started = time.monotonic()
        self._transfer_message = tr_noop("Waiting for backup service") if kind == "backup" else tr_noop("Waiting for restore service")
      if running:
        self._transfer_seen_running = True
        self._transfer_progress = max(0, min(100, progress))
        self._transfer_message = tr_noop("Backing up {progress}%") if kind == "backup" else tr_noop("Restoring {progress}%")
      elif live and not pending and (self._transfer_seen_running or fresh):
        failed = status == custom.BackupManagerSP.Status.failed
        completed = (status == custom.BackupManagerSP.Status.completed or
                     (status == custom.BackupManagerSP.Status.idle and progress == 100))
        if failed or completed:
          self._backup_in_progress = self._restore_in_progress = False
          self._transfer_kind = None
          self._transfer_wait_started = None
          self._transfer_progress = max(0, min(100, progress))
          self._transfer_error = error if failed else ""
          if failed:
            self._transfer_message = tr_noop("Backup Failed") if kind == "backup" else tr_noop("Restore Failed")
          elif kind == "backup":
            self._transfer_message = tr_noop("Settings backup completed.")
            gui_app.push_widget(alert_dialog(tr(self._transfer_message)))
          else:
            self._transfer_message = tr_noop("Settings restored. Confirm to restart the interface.")
            self._restore_restart_pending = True
            self._show_restore_restart()
      if not self._transfer_seen_running and pending:
        self._transfer_baseline, self._transfer_frame = snapshot, frame
      if self._waiting_timed_out():
        self._transfer_message = tr_noop("Backup service did not respond. Retry available.") if kind == "backup" else \
                                 tr_noop("Restore service did not respond. Retry available.")
    self._backup_btn.set_enabled(self._can_start_transfer("backup"))
    self._restore_btn.set_enabled(self._can_start_transfer("restore") or (self._restore_restart_pending and ui_state.is_offroad()))
    self._backup_btn.set_text(tr("Retry Backup") if self._transfer_message == "Backup Failed" or
                              (self._transfer_kind == "backup" and self._waiting_timed_out()) else
                              self._transfer_status() if self._backup_in_progress else tr("Backup Settings"))
    self._restore_btn.set_text(tr("Restart Interface") if self._restore_restart_pending else
                               tr("Retry Restore") if self._transfer_message == "Restore Failed" or
                               (self._transfer_kind == "restore" and self._waiting_timed_out()) else
                               self._transfer_status() if self._restore_in_progress else tr("Restore Settings"))
    if self._transfer_message in ("Backup Failed", "Restore Failed"):
      self._sunnylink_description.set_text(self._transfer_status() + "\n" + unescape(self._transfer_detail()))
      self._sunnylink_description.set_color(rl.Color(255, 165, 0, 255))
      self._sunnylink_description.set_visible(True)

  def _sunnylink_toggle_callback(self, state: bool):
    sl_consent: bool = ui_state.params.get("CompletedSunnylinkConsentVersion") == sunnylink_consent_version
    sl_enabled: bool = ui_state.params.get_bool("SunnylinkEnabled")

    if state and not sl_consent and not sl_enabled:
      def on_consent_done():
        enabled = ui_state.params.get_bool("SunnylinkEnabled")
        self._update_description(enabled)
        gui_app.pop_widget()

      sl_terms_dlg = SunnylinkConsentPage(done_callback=on_consent_done)
      gui_app.push_widget(sl_terms_dlg)
    else:
      ui_state.params.put_bool("SunnylinkEnabled", state)
      self._update_description(state)

  def _update_description(self, state: bool):
    if state:
      description = tr(
        "Welcome back!! We're excited to see you've enabled sunnylink again!")
      color = rl.Color(0, 255, 0, 255)  # Green
    else:
      description = ("😢 " + tr("Not going to lie, it's sad to see you disabled sunnylink") +
                     tr(", but we'll be here when you're ready to come back."))
      color = rl.Color(255, 165, 0, 255)  # Orange
    self._sunnylink_description.set_text(description)
    self._sunnylink_description.set_color(color)
    self._sunnylink_description.set_visible(True)
    self._sunnylink_toggle.show_description(False)

  def _update_state(self):
    super()._update_state()
    self._sunnylink_enabled = ui_state.params.get_bool("SunnylinkEnabled")
    self._sunnylink_toggle.set_right_value(tr("Dongle ID") + ": " + self._get_sunnylink_dongle_id())
    self._sunnylink_toggle.action_item.set_enabled(not ui_state.is_onroad())
    self._sunnylink_toggle.action_item.set_state(self._sunnylink_enabled)
    self._sunnylink_uploader_toggle.action_item.set_enabled(self._sunnylink_enabled)
    self.handle_backup_restore_progress()

    sponsor_btn_text = tr("THANKS ♥") if ui_state.sunnylink_state.is_sponsor() else tr("SPONSOR")
    tier = ui_state.sunnylink_state.get_sponsor_tier().name
    tier_name = tr(SPONSOR_TIERS.get(tier, tier))
    self._sponsor_btn.action_item.set_text(sponsor_btn_text)
    self._sponsor_btn.action_item.set_value(tier_name, ui_state.sunnylink_state.get_sponsor_tier_color())
    self._sponsor_btn.action_item.set_enabled(self._sunnylink_enabled)

    pair_btn_text = tr("Paired") if ui_state.sunnylink_state.is_paired() else tr("Not Paired")
    self._pair_btn.action_item.set_text(pair_btn_text)
    self._pair_btn.action_item.set_enabled(self._sunnylink_enabled)

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    super().show_event()
    ui_state.sunnylink_state.set_settings_open(True)
    self._scroller.show_event()
    self._sunnylink_description.set_visible(False)

  def hide_event(self):
    super().hide_event()
    ui_state.sunnylink_state.set_settings_open(False)
