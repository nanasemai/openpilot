"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import datetime
import glob
import os
import subprocess
from pathlib import Path

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.layouts.settings.developer import DeveloperLayout
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.button import ButtonStyle
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import DualButtonAction, ListItem, button_item

from openpilot.system.ui.sunnypilot.widgets.html_render import HtmlModalSP
from openpilot.system.ui.sunnypilot.widgets.list_view import toggle_item_sp

PREBUILT_PATH = os.path.join(Paths.comma_home(), "prebuilt") if PC else "/data/openpilot/prebuilt"

FORMAT_SCRIPT = os.path.join(BASEDIR, "sunnypilot", "tools", "format_swaglog.py")


class DeveloperLayoutSP(DeveloperLayout):
  def __init__(self):
    super().__init__()
    self.error_log_path = os.path.join(Paths.crash_log_root(), "error.log")
    self.swaglog_root = Paths.swaglog_root()
    self._is_release_branch: bool = self._is_release or ui_state.params.get_bool("IsReleaseSpBranch")
    self._is_development_branch: bool = ui_state.params.get_bool("IsTestedBranch") or ui_state.params.get_bool("IsDevelopmentBranch")
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

    self.items: list = [self.show_advanced_controls, self.enable_github_runner_toggle, self.enable_copyparty_toggle,
                        self.prebuilt_toggle, self.error_log_btn, self.system_logs_item,]

  @staticmethod
  def _on_prebuilt_toggled(state):
    if state:
      Path(PREBUILT_PATH).touch(exist_ok=True)
    else:
      os.remove(PREBUILT_PATH)
    ui_state.params.put_bool("QuickBootToggle", state)

  def _on_delete_confirm(self, result):
    if result == DialogResult.CONFIRM:
      if os.path.exists(self.error_log_path):
        os.remove(self.error_log_path)

  def _on_error_log_closed(self, result, log_exists):
    if result == DialogResult.CONFIRM and log_exists:
      dialog2 = ConfirmDialog(tr("Would you like to delete this log?"), tr("Yes"), tr("No"), rich=False, callback=self._on_delete_confirm)
      gui_app.push_widget(dialog2)

  def _on_error_log_clicked(self):
    text = ""
    if os.path.exists(self.error_log_path):
      text = f"<b>{datetime.datetime.fromtimestamp(os.path.getmtime(self.error_log_path)).strftime('%d-%b-%Y %H:%M:%S').upper()}</b><br><br>"
      try:
        with open(self.error_log_path) as file:
          text += file.read()
      except Exception:
        pass
    dialog = HtmlModalSP(text=text, callback=lambda result: self._on_error_log_closed(result, os.path.exists(self.error_log_path)))
    gui_app.push_widget(dialog)

  def _on_clear_system_logs_clicked(self):
    if not ui_state.is_offroad():
      dialog = HtmlModalSP(text=tr("System log operations are only available when offroad."))
      gui_app.push_widget(dialog)
      return
    log_files = sorted(glob.glob(os.path.join(self.swaglog_root, "swaglog.*")))
    if not log_files:
      dialog = HtmlModalSP(text=tr("No swaglog files found."))
      gui_app.push_widget(dialog)
      return

    file_count = len(log_files)
    size_total = sum(os.path.getsize(f) for f in log_files)
    prompt = (tr("{count} swaglog file(s) found, {size} total.<br><br>"
                 "Are you sure you want to delete them?").format(count=file_count, size=self._format_size(size_total)))
    dialog = ConfirmDialog(prompt, tr("Delete All"), tr("Cancel"), rich=True, callback=self._on_clear_system_logs_confirm)
    gui_app.push_widget(dialog)

  def _on_clear_system_logs_confirm(self, result):
    if result != DialogResult.CONFIRM:
      return
    log_files = sorted(glob.glob(os.path.join(self.swaglog_root, "swaglog.*")))
    deleted = 0
    for f in log_files:
      try:
        os.remove(f)
        deleted += 1
      except Exception:
        pass
    dialog = HtmlModalSP(text=tr("{count} swaglog file(s) cleared.").format(count=deleted))
    gui_app.push_widget(dialog)

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

    try:
      result = subprocess.run(["python3", FORMAT_SCRIPT], capture_output=True, text=True, timeout=120)

      if result.returncode == 0:
        # Parse output file path from script's stdout: "输出: /path/to/file (N 行)"
        output_info = ""
        for line in result.stdout.strip().split("\n"):
          if line.startswith("输出: "):
            path_str = line[4:].rsplit(" (", 1)[0].strip()
            out_path = Path(path_str)
            if out_path.exists():
              size_str = self._format_size(out_path.stat().st_size)
              output_info = f"<br><br>{tr('Output')}: <b>{out_path.name}</b> ({size_str})"
            break

        lines = result.stdout.strip().replace("\n", "<br>")
        text = f"<b>{tr('Format completed successfully.')}</b>{output_info}<br><br>{lines}"
        dialog = HtmlModalSP(text=text)
      else:
        error_msg = tr("Format failed (exit code {code}).").format(code=result.returncode)
        if result.stderr:
          error_msg += f"<br><br>{result.stderr[:1000]}"
        dialog = HtmlModalSP(text=error_msg)

    except subprocess.TimeoutExpired:
      dialog = HtmlModalSP(text=tr("Format timed out after 120 seconds."))
    except Exception as e:
      dialog = HtmlModalSP(text=tr("Error running format script: {error}").format(error=str(e)))

    gui_app.push_widget(dialog)

  @staticmethod
  def _format_size(bytes_val):
    for unit in ("B", "KB", "MB", "GB"):
      if bytes_val < 1024:
        return f"{bytes_val:.1f} {unit}"
      bytes_val /= 1024
    return f"{bytes_val:.1f} TB"

  def _update_state(self):
    disable_updates = ui_state.params.get_bool("DisableUpdates")
    show_advanced = ui_state.params.get_bool("ShowAdvancedControls")

    if (prebuilt_file := os.path.exists(PREBUILT_PATH)) != ui_state.params.get_bool("QuickBootToggle"):
      ui_state.params.put_bool("QuickBootToggle", prebuilt_file)
      self.prebuilt_toggle.action_item.set_state(prebuilt_file)

    self.prebuilt_toggle.set_visible(show_advanced and not (self._is_release_branch or self._is_development_branch))
    self.prebuilt_toggle.action_item.set_enabled(disable_updates)

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
    self.system_logs_item.action_item.left_button.set_enabled(is_offroad)
    self.system_logs_item.action_item.right_button.set_enabled(is_offroad)
