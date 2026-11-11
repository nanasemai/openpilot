"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import datetime
import os
import queue
import subprocess
import threading
import time
from html import escape
from pathlib import Path

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.layouts.settings.developer import DeveloperLayout
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths
from openpilot.system import usb_mount
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr, tr_noop
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.log_operations import scan_logs, delete_logs, file_identity
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import ButtonStyle
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import DualButtonAction, ListItem, button_item

from openpilot.system.ui.sunnypilot.widgets.html_render import HtmlModalSP
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp, button_item_sp, expandable_item_sp
from openpilot.system.ui.sunnypilot.widgets.progress_bar import progress_item

PREBUILT_PATH = os.path.join(Paths.comma_home(), "prebuilt") if PC else "/data/openpilot/prebuilt"

FORMAT_SCRIPT = os.path.join(BASEDIR, "sunnypilot", "tools", "format_swaglog.py")


def translate_usb_message(message):
  if isinstance(message, list):
    return "\n".join(translate_usb_message(item) for item in message)
  if not isinstance(message, usb_mount.UsbMessage):
    return str(message)
  return tr(message.template).format(**{key: translate_usb_message(value) if isinstance(value, (usb_mount.UsbMessage, list)) else value
                                       for key, value in message.values.items()})


class DeveloperLayoutSP(DeveloperLayout):
  def __init__(self):
    super().__init__()
    self.error_log_path = os.path.join(Paths.crash_log_root(), "error.log")
    self._error_log_snapshot = None
    self.swaglog_root = Paths.swaglog_root()
    self._is_release_branch: bool = self._is_release or ui_state.params.get_bool("IsReleaseSpBranch")
    self._is_development_branch: bool = ui_state.params.get_bool("IsTestedBranch") or ui_state.params.get_bool("IsDevelopmentBranch")
    self._format_running = False
    self._format_result = None
    self._last_format_result = None
    self._log_running = False
    self._log_events = queue.SimpleQueue()
    self._log_status = tr_noop("Ready")
    self._log_result = None
    self._pending_log_snapshot = None
    self._log_confirm_dialog = None
    self._last_usb_refresh = -1.0
    self._usb_events = queue.SimpleQueue()
    self._usb_refresh_running = False
    self._usb_task_running = False
    self._usb_scan_requested = False
    self._usb_generation = 0
    self._usb_mounted = False
    self._usb_status_message = usb_mount.UsbMessage("No USB detected")
    self._initialize_items()

    for item in self.items:
      self._scroller.add_widget(item)

  def _initialize_items(self):
    self.show_advanced_controls = toggle_item_sp(tr("Show Advanced Controls"),
                                                 tr("Toggle visibility of advanced sunnypilot controls.<br>This only changes the visibility of the toggles; " +
                                                    "it does not change the actual enabled/disabled state."), param="ShowAdvancedControls")

    self.enable_github_runner_toggle = toggle_item_sp(tr("GitHub Runner Service"), tr("Enables or disables the GitHub runner service."),
                                                      param="EnableGithubRunner")

    self.enable_copyparty_toggle = toggle_item_sp(tr("copyparty Service"),
                                                  tr("copyparty is a very capable file server, you can use it to download your routes, view your logs " +
                                                     "and even make some edits on some files from your browser. " +
                                                     "Requires you to connect to your comma locally via its IP address."), param="EnableCopyparty")

    self.prebuilt_toggle = toggle_item_sp(tr("Quickboot Mode"), "", param="QuickBootToggle", callback=self._on_prebuilt_toggled)

    self.error_log_btn = button_item(tr("Error Log"), tr("VIEW"), tr("View the error log for sunnypilot crashes."), callback=self._on_error_log_clicked)

    # Dual-button row: CLEAR + FORMAT for system logs
    logs_action = DualButtonAction(
      left_text=tr("CLEAR"),
      right_text=tr("FORMAT"),
      left_callback=self._on_clear_system_logs_clicked,
      right_callback=self._on_format_system_logs_clicked,
    )
    logs_action.left_button.set_button_style(ButtonStyle.LIST_ACTION)
    logs_action.right_button.set_button_style(ButtonStyle.LIST_ACTION)
    self.system_logs_item = ListItem(
      title=tr("System Logs"),
      description=tr("Clear or format swaglog files. Only available when offroad."),
      action_item=logs_action,
    )
    self._format_system_logs_btn = logs_action.right_button  # keep a reference for visibility
    self._log_status_item = progress_item(lambda: tr("System Log Status"))
    self._log_status_item.set_description(self._log_details)
    self._log_status_item.set_visible(False)

    # ── USB drive operations ─────────────────────────────────────────────
    # These only make sense with a stick plugged in, so they sit in a collapsed
    # group that is hidden outright when nothing is detected or mounted.
    # Initialize default values BEFORE creating the rows: TextAction resolves the
    # value lambda once at construction time to measure the text.
    self._usb_status_text = tr("No USB detected")
    self._usb_mount_btn_text = tr("MOUNT")
    self._usb_drives: list[dict] = []
    self._usb_visible = False
    self._usb_expanded = False

    self._usb_header = expandable_item_sp(
      title=lambda: tr("USB Drive"),
      value=lambda: self._usb_status_text,
      callback=self._on_usb_header_clicked,
    )
    self._usb_mount_item = button_item_sp(
      title=lambda: tr("Mount USB"),
      button_text=lambda: self._usb_mount_btn_text,
      description=tr("Mount the first detected FAT32 USB drive to /data/media/usb."),
      callback=self._on_usb_mount_clicked,
      indent=1,
    )
    self._usb_scan_item = button_item_sp(
      title=lambda: tr("Scan USB"),
      button_text=lambda: tr("SCAN"),
      description=tr("Re-scan USB drives and refresh status."),
      callback=self._on_usb_scan_clicked,
      indent=1,
    )
    self._usb_export_logs_item = button_item_sp(
      title=lambda: tr("Export Logs"),
      button_text=lambda: tr("EXPORT"),
      description=tr("Copy swaglog and crash logs to USB. USB must be mounted."),
      callback=self._on_usb_export_logs_clicked,
      indent=1,
    )
    self._usb_export_realdata_item = button_item_sp(
      title=lambda: tr("Export Realdata"),
      button_text=lambda: tr("EXPORT"),
      description=tr("Copy /data/media/0/realdata to USB. USB must be mounted. May take a while for large routes."),
      callback=self._on_usb_export_realdata_clicked,
      indent=1,
    )

    # Export progress bar – hidden until an export starts, updated by _update_state
    self._usb_export_progress_item = progress_item(tr("Exporting"), indent=1)
    self._usb_export_progress_item.set_visible(False)
    self._usb_exporting = False
    self._usb_export_done = False
    self._usb_export_result: tuple[bool, str] | None = None
    self._usb_export_pct = 0.0
    self._usb_export_msg = ""

    self.items: list = [self.show_advanced_controls, self.enable_github_runner_toggle, self.enable_copyparty_toggle,
                        self.prebuilt_toggle, self.error_log_btn, self.system_logs_item, self._log_status_item,
                        self._usb_header, self._usb_mount_item, self._usb_scan_item,
                        self._usb_export_logs_item, self._usb_export_realdata_item,
                        self._usb_export_progress_item]

  @staticmethod
  def _on_prebuilt_toggled(state):
    path = Path(PREBUILT_PATH)
    allowed = (ui_state.is_offroad() and ui_state.params.get_bool("DisableUpdates") and ui_state.params.get_bool("ShowAdvancedControls") and
               not any(ui_state.params.get_bool(key) for key in ("IsReleaseSpBranch", "IsTestedBranch", "IsDevelopmentBranch")))
    if allowed:
      try:
        path.touch(exist_ok=True) if state else path.unlink(missing_ok=True)
      except OSError as error:
        gui_app.push_widget(HtmlModalSP(text=escape(tr("Unable to change quickboot mode: {error}").format(error=error))))
    ui_state.params.put_bool("QuickBootToggle", path.exists(), block=True)

  def _on_delete_confirm(self, result):
    if result != DialogResult.CONFIRM or not ui_state.is_offroad() or self._error_log_snapshot is None:
      return
    try:
      if file_identity(os.lstat(self.error_log_path)) != self._error_log_snapshot:
        gui_app.push_widget(HtmlModalSP(text=tr("The error log changed. Open it again before deleting.")))
        return
      os.remove(self.error_log_path)
      self._error_log_snapshot = None
      gui_app.push_widget(HtmlModalSP(text=tr("Error log deleted.")))
    except OSError as error:
      gui_app.push_widget(HtmlModalSP(text=escape(tr("Unable to delete error log: {error}").format(error=error))))

  def _on_error_log_closed(self, result, log_exists):
    if result == DialogResult.CONFIRM and log_exists and ui_state.is_offroad():
      dialog2 = ConfirmDialog(tr("Would you like to delete this log?"), tr("Yes"), tr("No"), rich=False, callback=self._on_delete_confirm)
      gui_app.push_widget(dialog2)

  def _on_error_log_clicked(self):
    text = tr("No error log found.")
    self._error_log_snapshot = None
    try:
      with open(self.error_log_path) as file:
        info = os.fstat(file.fileno())
        self._error_log_snapshot = file_identity(info)
        text = f"<b>{datetime.datetime.fromtimestamp(info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}</b><br><br>"
        text += escape(file.read()).replace("\n", "<br>")
    except FileNotFoundError:
      pass
    except OSError as error:
      text = escape(tr("Unable to read error log: {error}").format(error=error))
    dialog = HtmlModalSP(text=text, callback=lambda result: self._on_error_log_closed(result, os.path.exists(self.error_log_path)))
    gui_app.push_widget(dialog)

  def _on_clear_system_logs_clicked(self):
    if not ui_state.is_offroad():
      dialog = HtmlModalSP(text=tr("System log operations are only available when offroad."))
      gui_app.push_widget(dialog)
      return
    if self._log_running or self._format_running or self._pending_log_snapshot is not None:
      return
    self._log_running = True
    self._log_result = None
    self._last_format_result = None
    self._log_status = tr_noop("Scanning system logs")
    threading.Thread(target=self._scan_system_logs_worker, daemon=True).start()

  def _scan_system_logs_worker(self):
    try:
      self._log_events.put(("scan", scan_logs(self.swaglog_root)))
    except OSError as error:
      self._log_events.put(("scan_error", str(error)))

  def _on_clear_system_logs_confirm(self, result):
    snapshot, self._pending_log_snapshot = self._pending_log_snapshot, None
    self._log_confirm_dialog = None
    if snapshot is None or result != DialogResult.CONFIRM or not ui_state.is_offroad():
      self._log_status = tr_noop("Log cleanup cancelled")
      return
    if self._log_running or self._format_running:
      return
    self._log_running = True
    self._log_status = tr_noop("Deleting system logs")
    threading.Thread(target=self._delete_system_logs_worker, args=(snapshot,), daemon=True).start()

  def _delete_system_logs_worker(self, snapshot):
    self._log_events.put(("deleted", delete_logs(snapshot)))

  def _log_details(self):
    if self._last_format_result is not None:
      return self._format_result_text(self._last_format_result)
    if self._log_result is None:
      return tr("Only unchanged log files shown in the confirmation will be deleted. New or modified logs are kept.")
    if isinstance(self._log_result, str):
      return escape(tr("Error: {error}").format(error=self._log_result))
    result = self._log_result
    text = tr("Cleared {deleted}/{total} system log files.").format(deleted=result.deleted, total=result.total)
    if result.changed:
      text += "<br>" + tr("{count} changed or missing files were skipped.").format(count=result.changed)
    if result.errors:
      text += "<br>" + tr("Some files could not be deleted. Retry after checking the error details.")
      text += "<br><br>" + "<br>".join(escape(error) for error in result.errors)
    return text

  def _process_log_events(self):
    if self._pending_log_snapshot is not None and not gui_app.widget_in_stack(self._log_confirm_dialog):
      self._pending_log_snapshot = None
      self._log_confirm_dialog = None
      self._log_status = tr_noop("Log cleanup cancelled")
    while not self._log_events.empty():
      kind, result = self._log_events.get()
      self._log_running = False
      if kind == "scan":
        if not result.files:
          self._log_status = tr_noop("No swaglog files found.")
        elif not ui_state.is_offroad():
          self._log_status = tr_noop("Log cleanup cancelled")
        else:
          self._pending_log_snapshot = result
          self._log_status = tr_noop("Waiting for log cleanup confirmation")
          prompt = tr("{count} swaglog file(s) found, {size} total.<br><br>Are you sure you want to delete them?").format(
            count=len(result.files), size=self._format_size(result.size))
          self._log_confirm_dialog = ConfirmDialog(prompt, tr("Delete All"), rich=True, callback=self._on_clear_system_logs_confirm)
          gui_app.push_widget(self._log_confirm_dialog)
      elif kind == "scan_error":
        self._log_result = result
        self._log_status = tr_noop("Unable to scan system logs")
        gui_app.push_widget(HtmlModalSP(text=self._log_details))
      elif kind == "deleted":
        self._log_result = result
        self._log_status = tr_noop("Log cleanup incomplete") if result.errors or result.changed else tr_noop("Log cleanup completed")
        gui_app.push_widget(HtmlModalSP(text=self._log_details))

  def _on_format_system_logs_clicked(self):
    """Run the format_swaglog script and show the result."""
    if not ui_state.is_offroad():
      dialog = HtmlModalSP(text=tr("System log operations are only available when offroad."))
      gui_app.push_widget(dialog)
      return
    if not os.path.exists(FORMAT_SCRIPT):
      dialog = HtmlModalSP(text=tr("Format script not found: {path}").format(path=FORMAT_SCRIPT))
      gui_app.push_widget(dialog)
      return

    if self._format_running or self._log_running or self._pending_log_snapshot is not None:
      return
    self._format_running = True
    self._log_result = None
    self._last_format_result = None
    self._log_status = tr_noop("Formatting system logs")
    threading.Thread(target=self._format_system_logs_worker, daemon=True).start()

  def _format_system_logs_worker(self):
    # Keep subprocess I/O off the UI thread. Only _update_state opens the result.
    try:
      self._format_result = self._format_system_logs_text()
    finally:
      self._format_running = False

  def _format_system_logs_text(self):
    try:
      result = subprocess.run(["python3", FORMAT_SCRIPT], capture_output=True, text=True, timeout=120)

      if result.returncode == 0:
        # Parse output file path from script's stdout: "输出: /path/to/file (N 行)"
        output_info = None
        for line in result.stdout.strip().split("\n"):
          if line.startswith("输出: "):
            path_str = line[4:].rsplit(" (", 1)[0].strip()
            out_path = Path(path_str)
            if out_path.exists():
              size_str = self._format_size(out_path.stat().st_size)
              output_info = (out_path.name, size_str)
            break

        return {"status": "completed", "output": output_info, "stdout": result.stdout.strip()}
      else:
        return {"status": "failed", "code": result.returncode, "stderr": result.stderr[:1000]}

    except subprocess.TimeoutExpired:
      return {"status": "timeout"}
    except Exception as e:
      return {"status": "error", "error": str(e)}

  @staticmethod
  def _format_result_text(result):
    if not isinstance(result, dict):
      return str(result)
    if result["status"] == "completed":
      text = "<b>" + tr("Format completed successfully.") + "</b>"
      if result["output"] is not None:
        name, size = result["output"]
        text += f"<br><br>{tr('Output')}: <b>{escape(name)}</b> ({escape(size)})"
      return text + "<br><br>" + escape(result["stdout"]).replace("\n", "<br>")
    if result["status"] == "failed":
      return tr("Format failed (exit code {code}).").format(code=result["code"]) + "<br><br>" + escape(result["stderr"])
    if result["status"] == "timeout":
      return tr("Format timed out after 120 seconds.")
    return escape(tr("Error running format script: {error}").format(error=result["error"]))

  @staticmethod
  def _format_size(bytes_val):
    for unit in ("B", "KB", "MB", "GB"):
      if bytes_val < 1024:
        return f"{bytes_val:.1f} {unit}"
      bytes_val /= 1024
    return f"{bytes_val:.1f} TB"

  def _update_state(self):
    super()._update_state()
    self._process_log_events()
    self._log_status_item.set_visible(self._log_status != "Ready")
    self._log_status_item.action_item.update(0, tr(self._log_status))
    self._process_usb_events()
    if self._format_result is not None:
      result, self._format_result = self._format_result, None
      self._last_format_result = result
      self._log_status = tr_noop("Format completed successfully.") if isinstance(result, dict) and result["status"] == "completed" else \
                         tr_noop("Formatting result")
      gui_app.push_widget(HtmlModalSP(text=lambda: self._format_result_text(result)))
    disable_updates = ui_state.params.get_bool("DisableUpdates")
    show_advanced = ui_state.params.get_bool("ShowAdvancedControls")

    if (prebuilt_file := os.path.exists(PREBUILT_PATH)) != ui_state.params.get_bool("QuickBootToggle"):
      ui_state.params.put_bool("QuickBootToggle", prebuilt_file)
      self.prebuilt_toggle.action_item.set_state(prebuilt_file)

    self.prebuilt_toggle.set_visible(show_advanced and not (self._is_release_branch or self._is_development_branch))
    self.prebuilt_toggle.action_item.set_enabled(disable_updates and ui_state.is_offroad())

    if disable_updates:
      self.prebuilt_toggle.set_description(tr("When toggled on, this creates a prebuilt file to allow accelerated boot times. When toggled off, it " +
                                              "removes the prebuilt file so compilation of locally edited cpp files can be made."))
    else:
      self.prebuilt_toggle.set_description(tr("Quickboot mode requires updates to be disabled.<br>Enable 'Disable Updates' in the Software panel first."))

    self.enable_copyparty_toggle.set_visible(show_advanced)
    self.enable_github_runner_toggle.set_visible(show_advanced and not self._is_release_branch)
    self.error_log_btn.set_visible(not self._is_release_branch)

    # System log operations are offroad-only
    is_offroad = ui_state.is_offroad()
    log_available = is_offroad and not self._format_running and not self._log_running and self._pending_log_snapshot is None
    self.system_logs_item.action_item.left_button.set_enabled(log_available)
    self.system_logs_item.action_item.right_button.set_enabled(log_available)

    # USB operations: refresh state, then only offer the group while a drive is present
    now = time.monotonic()
    if now - self._last_usb_refresh >= 1:
      self._refresh_usb_state()
      self._last_usb_refresh = now
    self._usb_status_text = translate_usb_message(self._usb_status_message)
    self._usb_mount_btn_text = tr("UNMOUNT") if self._usb_mounted else tr("MOUNT")
    busy = self._usb_exporting or self._usb_task_running
    self._usb_mount_item.action_item.set_enabled(not busy)
    self._usb_scan_item.action_item.set_enabled(not self._usb_task_running)
    for item in (self._usb_export_logs_item, self._usb_export_realdata_item):
      item.action_item.set_enabled(self._usb_mounted and not busy)
    self._usb_visible = self._usb_mounted or bool(self._usb_drives) or busy
    self._usb_header.set_visible(self._usb_visible)
    children_visible = self._usb_visible and self._usb_expanded
    for item in (self._usb_mount_item, self._usb_scan_item,
                 self._usb_export_logs_item, self._usb_export_realdata_item):
      item.set_visible(children_visible)

    # Update export progress bar visibility and display
    if self._usb_export_done and self._usb_export_result is not None:
      ok, msg = self._usb_export_result
      self._usb_export_progress_item.set_visible(False)
      self._usb_exporting = False
      self._usb_export_done = False
      self._usb_export_pct = 0.0
      self._usb_export_msg = ""
      self._usb_export_result = None
      gui_app.push_widget(ConfirmDialog(
        tr("{status}: {message}").format(status=tr("Success") if ok else tr("Failed"), message=translate_usb_message(msg)),
        tr("OK"), cancel_text=""
      ))
    elif self._usb_exporting:
      self._usb_export_progress_item.set_visible(self._usb_visible)
      text = f"{int(self._usb_export_pct)}% - {translate_usb_message(self._usb_export_msg)}" if self._usb_export_msg else f"{int(self._usb_export_pct)}%"
      self._usb_export_progress_item.action_item.update(self._usb_export_pct, text, show_progress=True)
    else:
      self._usb_export_progress_item.set_visible(False)

  # ── USB drive state ────────────────────────────────────────────────────────
  def _refresh_usb_state(self):
    """lsblk may take seconds; collect its result without blocking rendering."""
    if self._usb_refresh_running or self._usb_task_running:
      return
    self._usb_refresh_running = True
    threading.Thread(target=self._read_usb_state, args=(self._usb_generation,), daemon=True).start()

  def _read_usb_state(self, generation):
    try:
      drives = usb_mount.get_usb_drives()
      mounted = usb_mount.is_mounted(usb_mount.MOUNT_DIR)
      device = usb_mount.get_mount_device(usb_mount.MOUNT_DIR) if mounted else None
      self._usb_events.put(("refresh", (generation, drives, mounted, device)))
    except Exception as error:
      self._usb_events.put(("refresh_error", usb_mount.UsbMessage("USB scan failed: {error}", error=str(error))))

  def _apply_usb_state(self, drives, mounted, device):
    self._usb_drives, self._usb_mounted = drives, mounted

    if mounted:
      self._usb_status_message = usb_mount.UsbMessage("Mounted: {device}", device=device or "?")
    elif self._usb_drives:
      d = self._usb_drives[0]
      fs = d["fstype"].upper()
      if fs == "VFAT":
        self._usb_status_message = usb_mount.UsbMessage("Detected: {device} ({size})", device=d['device'], size=d['size'])
      else:
        self._usb_status_message = usb_mount.UsbMessage("{device} {filesystem} (needs FAT32)", device=d['device'], filesystem=fs)
    else:
      self._usb_status_message = usb_mount.UsbMessage("No USB detected")

    # Hide the whole group when there is nothing to mount or export to
    self._usb_visible = mounted or bool(self._usb_drives)

  def _process_usb_events(self):
    while not self._usb_events.empty():
      kind, data = self._usb_events.get_nowait()
      if kind == "refresh":
        self._usb_refresh_running = False
        generation, drives, mounted, device = data
        if generation == self._usb_generation:
          self._apply_usb_state(drives, mounted, device)
          if self._usb_scan_requested:
            self._usb_scan_requested = False
            self._show_usb_scan_result()
        else:
          self._last_usb_refresh = -1.0
      elif kind == "refresh_error":
        self._usb_refresh_running = False
        self._usb_status_message = data
        if self._usb_scan_requested:
          self._usb_scan_requested = False
          gui_app.push_widget(ConfirmDialog(translate_usb_message(data), tr("OK"), cancel_text=""))
      elif kind == "mount":
        self._usb_task_running = False
        self._last_usb_refresh = -1.0
        gui_app.push_widget(ConfirmDialog(translate_usb_message(data.message), tr("OK"), cancel_text=""))
      elif kind == "progress":
        self._usb_export_pct, self._usb_export_msg = data
      elif kind == "export":
        self._usb_export_result = data
        self._usb_exporting = False
        self._usb_export_done = True

  def _on_usb_header_clicked(self):
    self._usb_expanded = not self._usb_expanded

  def _on_usb_mount_clicked(self):
    """Toggle mount/unmount of the USB drive at /data/media/usb."""
    if self._usb_exporting or self._usb_task_running:
      return
    self._usb_task_running = True
    self._usb_generation += 1
    self._usb_mount_item.action_item.set_enabled(False)
    threading.Thread(target=self._do_usb_mount, args=(list(self._usb_drives),), daemon=True).start()

  def _do_usb_mount(self, drives):
    try:
      if usb_mount.is_mounted(usb_mount.MOUNT_DIR):
        result = usb_mount.unmount_usb(usb_mount.MOUNT_DIR)
      else:
        drives = drives or usb_mount.get_usb_drives()
        if not drives:
          result = usb_mount.MountResult(False, usb_mount.UsbMessage("No USB drive detected."))
        elif drives[0]["fstype"] != "vfat":
          result = usb_mount.MountResult(False, usb_mount.UsbMessage(
            "Only FAT32 USB drives are supported.\nCurrent: {fs}\n\nPlease format to FAT32 first.", fs=drives[0]["fstype"].upper()))
        else:
          result = usb_mount.mount_usb(drives[0]["device"], fstype="vfat")
    except Exception as error:
      result = usb_mount.MountResult(False, usb_mount.UsbMessage("USB operation failed: {error}", error=str(error)))
    self._usb_events.put(("mount", result))

  def _on_usb_scan_clicked(self):
    """Re-scan USB drives and refresh status."""
    self._usb_scan_requested = True
    self._refresh_usb_state()

  def _show_usb_scan_result(self):
    if self._usb_drives:
      lines = []
      for d in self._usb_drives:
        mp = usb_mount.get_mount_status(d["device"])
        mount_txt = f" -> {mp}" if mp else tr(" (not mounted)")
        lines.append(f"{d['device']} {d['size']} {d['fstype'].upper()}{mount_txt}")
      text = f"<b>{tr('USB drives found')}: {len(self._usb_drives)}</b><br><br>" + "<br>".join(lines)
    else:
      text = tr("No USB drives detected.")
    gui_app.push_widget(ConfirmDialog(text, tr("OK"), cancel_text="", rich=True))

  def _on_usb_export_logs_clicked(self):
    self._start_usb_export(usb_mount.export_logs)

  def _start_usb_export(self, exporter):
    if self._usb_exporting or self._usb_task_running:
      return
    if not usb_mount.is_mounted(usb_mount.MOUNT_DIR):
      gui_app.push_widget(ConfirmDialog(
        tr("USB is not mounted. Please mount it first."),
        tr("OK"), cancel_text=""
      ))
      return

    # Disable export buttons while in progress
    self._usb_export_logs_item.action_item.set_enabled(False)
    self._usb_export_realdata_item.action_item.set_enabled(False)
    self._usb_exporting = True
    self._usb_export_done = False
    self._usb_export_pct = 0.0
    self._usb_export_msg = ""

    threading.Thread(target=self._do_usb_export, args=(exporter,), daemon=True).start()

  def _do_usb_export(self, exporter):
    try:
      result = exporter(usb_mount.MOUNT_DIR, progress_callback=lambda pct, msg: self._usb_events.put(("progress", (pct, msg))))
    except Exception as error:
      result = (False, usb_mount.UsbMessage("USB export failed: {error}", error=str(error)))
    self._usb_events.put(("export", result))

  def _on_usb_export_realdata_clicked(self):
    self._start_usb_export(usb_mount.export_realdata)
