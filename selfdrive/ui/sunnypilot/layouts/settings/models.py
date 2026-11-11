"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import os
import re
import time
import queue
import threading
import pyray as rl

from cereal import custom
from openpilot.sunnypilot.models.default_model import DEFAULT_MODEL
from openpilot.common.constants import CV
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog, alert_dialog
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.toggle import ON_COLOR

from openpilot.sunnypilot.models.runners.constants import CUSTOM_MODEL_PATH
from openpilot.system.ui.sunnypilot.lib.styles import style
from openpilot.system.ui.sunnypilot.lib.utils import NoElideButtonAction
from openpilot.system.ui.sunnypilot.widgets.list_view import ListItemSP, toggle_item_sp, option_item_sp
from openpilot.system.ui.sunnypilot.widgets.progress_bar import progress_item
from openpilot.system.ui.sunnypilot.widgets.tree_dialog import TreeOptionDialog, TreeNode, TreeFolder

if gui_app.sunnypilot_ui():
  from openpilot.system.ui.sunnypilot.widgets.list_view import button_item_sp as button_item


class ModelsLayout(Widget):
  def __init__(self):
    super().__init__()
    self.model_manager = None
    self.download_status = None
    self.prev_download_status = None
    self.model_dialog = None
    self.last_cache_calc_time = 0
    self._params = ui_state.params
    self._cache_events = queue.SimpleQueue()
    self._cache_scan_running = False
    self._cache_request_started = None
    self._cache_requested = False
    self._refresh_started = None
    self._refresh_sync = None
    self._download_request_index = None
    self._download_request_revision = None
    self._download_request_started = None

    self._initialize_items()

    self._refresh_cache_size()
    for ctrl, key, default in [(self.lane_turn_value_control, "LaneTurnValue", 1900), (self.delay_control, "LagdToggleDelay", 20)]:
      v = ui_state.params.get(key, return_default=True)
      ctrl.action_item.set_value(int(float(v) * 100) if v is not None else default)

    self._scroller = Scroller(self.items, line_separator=True, spacing=0)

  def _initialize_items(self):
    self.current_model_item = ListItemSP(
      title=lambda: tr("Current Model"),
      description="",
      action_item=NoElideButtonAction(lambda: tr("SELECT")),
      callback=self._handle_current_model_clicked
    )

    self.supercombo_label = progress_item(lambda: tr("Driving Model"))
    self.vision_label = progress_item(lambda: tr("Vision Model"))
    self.policy_label = progress_item(lambda: tr("Policy Model"))
    self.off_policy_label = progress_item(lambda: tr("Off-Policy Model"))
    self.on_policy_label = progress_item(lambda: tr("On-Policy Model"))
    self.download_request_item = progress_item(lambda: tr("Model Download Status"))
    self.download_request_item.set_description(lambda: tr("The model download request is saved. " +
                                                          "You can cancel it while waiting for the model service."))
    self.download_request_item.set_visible(False)

    self.refresh_item = ListItemSP(lambda: tr("Refresh Model List"), action_item=NoElideButtonAction(lambda: tr("REFRESH")),
                                  callback=self._refresh_models)

    self.clear_cache_item = ListItemSP(
      title=lambda: tr("Clear Model Cache"),
      description="",
      action_item=NoElideButtonAction(lambda: tr("CLEAR")),
      callback=self._clear_cache
    )

    self.cancel_download_item = button_item(lambda: tr("Cancel Download"), lambda: tr("Cancel"), "",
                                           self._cancel_model_download)
    self.retry_download_item = button_item(lambda: tr("Retry Model Download"), lambda: tr("Retry"), "", self._retry_model_download)
    self.retry_download_item.set_visible(False)

    self.lane_turn_value_control = option_item_sp(lambda: tr("Adjust Lane Turn Speed"), "LaneTurnValue", 500, 2000,
                                                  lambda: tr("Set the maximum speed for lane turn desires. Default is 19 mph."),
                                                  int(round(100 / CV.MPH_TO_KPH)), None, True, "", style.BUTTON_ACTION_WIDTH, None, True,
                                                  lambda v: f"{int(round(v / 100 * (CV.MPH_TO_KPH if ui_state.is_metric else 1)))}" +
                                                            f" {'km/h' if ui_state.is_metric else 'mph'}")
    self.lane_turn_value_control.action_item.step_label_callback = (
      lambda step: f"{step / 100 * (CV.MPH_TO_KPH if ui_state.is_metric else 1):.2f} " + (tr("km/h") if ui_state.is_metric else tr("mph"))
    )

    self.lane_turn_desire_toggle = toggle_item_sp(tr("Use Lane Turn Desires"),
                                                  tr("If you're driving at 20 mph (32 km/h) or below and have your blinker on," +
                                                     " the car will plan a turn in that direction at the nearest drivable path. " +
                                                     "This prevents situations (like at red lights) where the car might plan the wrong turn direction."),
                                                  param="LaneTurnDesire")

    self.delay_control = option_item_sp(tr("Adjust Software Delay"), "LagdToggleDelay", 5, 50,
                                        tr("Adjust the software delay when Live Learning Steer Delay is toggled off. The default software delay value is 0.2"),
                                        1, None, True, "", style.BUTTON_ACTION_WIDTH, None, True, lambda v: f"{v / 100:.2f} {tr('s')}")

    self.lagd_toggle = toggle_item_sp(tr("Live Learning Steer Delay"), "", param="LagdToggle")

    self.items = [self.current_model_item, self.cancel_download_item, self.retry_download_item, self.download_request_item,
                  self.supercombo_label, self.vision_label,
                  self.policy_label, self.off_policy_label, self.on_policy_label, self.refresh_item, self.clear_cache_item, self.lane_turn_desire_toggle,
                  self.lane_turn_value_control, self.lagd_toggle, self.delay_control]

  def _update_lagd_description(self, lagd_toggle: bool):
    desc = tr("Enable this for the car to learn and adapt its steering response time. Disable to use a fixed steering response time. " +
              "Keeping this on provides the stock openpilot experience.")
    if lagd_toggle:
      desc += f"<br>{tr('Live Steer Delay:')} {ui_state.sm['liveDelay'].lateralDelay:.3f} s"
    elif ui_state.CP is not None:
      _sw = self._params.get("LagdToggleDelay", return_default=True)
      sw = float(_sw) if _sw is not None else 0.2
      cp = ui_state.CP.steerActuatorDelay
      desc += f"<br>{tr('Actuator Delay:')} {cp:.2f} s + {tr('Software Delay:')} {sw:.2f} s = {tr('Total Delay:')} {cp + sw:.2f} s"
    self.lagd_toggle.set_description(desc)

  def _is_downloading(self):
    return (self.model_manager and self.model_manager.selectedBundle and
            self.model_manager.selectedBundle.status == custom.ModelManagerSP.DownloadStatus.downloading)

  def _download_pending(self):
    return self._is_downloading() or self._params.get("ModelManager_DownloadIndex") is not None

  @staticmethod
  def calculate_cache_size():
    cache_size = 0.0
    if os.path.exists(CUSTOM_MODEL_PATH) and not os.path.islink(CUSTOM_MODEL_PATH):
      with os.scandir(CUSTOM_MODEL_PATH) as entries:
        cache_size = sum(entry.stat(follow_symlinks=False).st_size for entry in entries if entry.is_file(follow_symlinks=False)) / (1024**2)
    return cache_size

  def _refresh_cache_size(self):
    if self._cache_scan_running:
      return
    self._cache_scan_running = True
    self.last_cache_calc_time = time.monotonic()
    def scan():
      try:
        self._cache_events.put((self.calculate_cache_size(), None))
      except OSError as error:
        self._cache_events.put((None, str(error)))
    threading.Thread(target=scan, daemon=True).start()

  def _refresh_models(self):
    if (not ui_state.is_offroad() or self._download_pending() or
        (self._refresh_started is not None and time.monotonic() - self._refresh_started < 30)):
      return
    self._refresh_sync = self._params.get("ModelManager_LastSyncTime")
    self._refresh_started = time.monotonic()
    self.refresh_item.action_item.set_text(tr("REFRESH"))
    self._params.put("ModelManager_LastSyncTime", 0, block=True)
    self._update_operations()

  def _retry_model_download(self):
    failed = self.model_manager.selectedBundle if self.model_manager else None
    selected_ref = failed.ref if failed and failed.status == custom.ModelManagerSP.DownloadStatus.failed else None
    self.model_manager = ui_state.sm["modelManagerSP"]
    if not ui_state.is_offroad() or self._download_pending() or not selected_ref:
      return
    bundle = (next((bundle for bundle in self.model_manager.availableBundles if bundle.ref == selected_ref), None)
              if self.model_manager else None)
    if bundle:
      self._params.put("ModelManager_DownloadIndex", bundle.index, block=True)
    else:
      gui_app.push_widget(alert_dialog(tr("Model list changed or the service is unavailable. Reopen the model selector and try again.")))

  def _cancel_model_download(self):
    self._params.remove("ModelManager_DownloadIndex")
    self._download_request_index = None
    self._download_request_revision = None
    self._download_request_started = None

  def _update_operations(self):
    pending = self._download_pending()
    cache_pending = self._params.get_bool("ModelManager_ClearCache")
    while not self._cache_events.empty():
      size, error = self._cache_events.get_nowait()
      self._cache_scan_running = False
      if not cache_pending:
        self.clear_cache_item.action_item.set_value(tr("Cache size unavailable") if error is not None else f"{size:.2f} MB")
    now = time.monotonic()
    if cache_pending:
      self._cache_requested = True
      if self._cache_request_started is None:
        self._cache_request_started = now
      timeout = now - self._cache_request_started >= 30
      self.clear_cache_item.action_item.set_value(tr("Model service has not completed the cache request. Retry.") if timeout else
                                                 tr("Waiting for model cache cleanup..."))
      self.clear_cache_item.action_item.set_text(tr("Retry") if timeout else tr("CLEAR"))
      self.clear_cache_item.action_item.set_enabled(ui_state.is_offroad() and not pending and timeout)
    else:
      if self._cache_requested:
        self._cache_requested = False
        self._cache_request_started = None
        self._refresh_cache_size()
      elif now - self.last_cache_calc_time >= 1:
        self._refresh_cache_size()
      self.clear_cache_item.action_item.set_text(tr("CLEAR"))
      self.clear_cache_item.action_item.set_enabled(ui_state.is_offroad() and not pending)
    if self._refresh_started is not None:
      synced = self._params.get("ModelManager_LastSyncTime")
      if synced and synced != self._refresh_sync:
        self._refresh_started = None
        self.refresh_item.action_item.set_value(tr("Model list refreshed."))
      elif now - self._refresh_started >= 30:
        self.refresh_item.action_item.set_value(tr("Model list refresh has not completed. Check the network and retry."))
        self.refresh_item.action_item.set_text(tr("Retry"))
      else:
        self.refresh_item.action_item.set_value(tr("Fetching Latest Models"))
    self.refresh_item.action_item.set_enabled(ui_state.is_offroad() and not pending and
                                              (self._refresh_started is None or now - self._refresh_started >= 30))

  def _clear_cache(self):
    if not ui_state.is_offroad() or self._download_pending():
      return
    def _callback(response):
      if response == DialogResult.CONFIRM and ui_state.is_offroad() and not self._download_pending():
        self._cache_request_started = time.monotonic()
        self._params.put_bool("ModelManager_ClearCache", True, block=True)
        self._update_operations()

    dialog = ConfirmDialog(tr("This will delete ALL downloaded models from the cache except the currently active model. Are you sure?"),
                           tr("Clear Cache"), callback=_callback)
    gui_app.push_widget(dialog)

  def _handle_bundle_download_progress(self):
    labels = {custom.ModelManagerSP.Model.Type.supercombo: self.supercombo_label,
              custom.ModelManagerSP.Model.Type.vision: self.vision_label,
              custom.ModelManagerSP.Model.Type.policy: self.policy_label,
              custom.ModelManagerSP.Model.Type.offPolicy: self.off_policy_label,
              custom.ModelManagerSP.Model.Type.onPolicy: self.on_policy_label}
    for label in labels.values():
      label.set_visible(False)
    self.cancel_download_item.set_visible(False)
    self.retry_download_item.set_visible(False)
    self.download_request_item.set_visible(False)

    request = self._params.get("ModelManager_DownloadIndex")
    revision = None
    if request is not None:
      try:
        stat = os.stat(self._params.get_param_path("ModelManager_DownloadIndex"))
        revision = (stat.st_dev, stat.st_ino, stat.st_mtime_ns)
      except FileNotFoundError:
        request = None
    if (request, revision) != (self._download_request_index, self._download_request_revision):
      self._download_request_index = request
      self._download_request_revision = revision
      self._download_request_started = time.monotonic() if request is not None else None
    self.cancel_download_item.set_visible(request is not None)
    self.retry_download_item.action_item.set_enabled(ui_state.is_offroad() and not self._download_pending())
    selected = self.model_manager.selectedBundle if self.model_manager and self.model_manager.selectedBundle.ref else None
    started = selected and selected.index == request and selected.status == custom.ModelManagerSP.DownloadStatus.downloading
    if request is not None and not started:
      requested = next((bundle for bundle in self.model_manager.availableBundles if bundle.index == request), None) if self.model_manager else None
      if requested is None and selected and selected.index == request:
        requested = selected
      if time.monotonic() - self._download_request_started >= 30:
        text = tr("Model service has not started the download. Cancel and retry.")
      else:
        text = tr("Waiting for model service: {model}").format(model=requested.displayName) if requested else tr("Waiting for model service...")
      self.download_request_item.set_visible(True)
      self.download_request_item.action_item.update(0, text, False, rl.GRAY)
      return

    bundle = selected if selected and selected.status in (custom.ModelManagerSP.DownloadStatus.downloading,
                                                         custom.ModelManagerSP.DownloadStatus.failed) else (
      self.model_manager.activeBundle if self.model_manager and self.model_manager.activeBundle.ref else None)
    if not bundle:
      return

    self.download_status = bundle.status
    status_changed = self.prev_download_status != self.download_status
    self.prev_download_status = self.download_status

    self.retry_download_item.set_visible(bool(selected) and selected.status == custom.ModelManagerSP.DownloadStatus.failed)

    if self.download_status == custom.ModelManagerSP.DownloadStatus.downloading:
      device._reset_interactive_timeout()

    for model in bundle.models:
      if label := labels.get(getattr(model.type, 'raw', model.type)):
        label.set_visible(True)
        p = model.artifact.downloadProgress
        if model.metadata.fileName and model.metadata.downloadProgress.status in (custom.ModelManagerSP.DownloadStatus.downloading,
                                                                                 custom.ModelManagerSP.DownloadStatus.failed):
          p = model.metadata.downloadProgress
        text, show, color = f"{tr('pending')} - {bundle.displayName}", False, rl.GRAY
        if p.status == custom.ModelManagerSP.DownloadStatus.downloading:
          text, show = f"{int(p.progress)}% - {bundle.displayName}", True
        elif p.status in (custom.ModelManagerSP.DownloadStatus.downloaded, custom.ModelManagerSP.DownloadStatus.cached):
          status_text = tr("from cache" if p.status == custom.ModelManagerSP.DownloadStatus.cached else "downloaded")
          text, color = f"{bundle.displayName} - {status_text if status_changed else tr('ready')}", ON_COLOR
        elif p.status == custom.ModelManagerSP.DownloadStatus.failed:
          text, color = f"{tr('download failed')} - {bundle.displayName}", rl.RED
        label.action_item.update(p.progress, text, show, color)

  @staticmethod
  def _show_reset_params_dialog():
    if not ui_state.is_offroad():
      return
    def _callback(response):
      if response == DialogResult.CONFIRM and ui_state.is_offroad():
        ui_state.params.remove("CalibrationParams")
        ui_state.params.remove("LiveTorqueParameters")
    msg = tr("Model download has started in the background. We suggest resetting calibration. Would you like to do that now?")
    dialog = ConfirmDialog(msg, tr("Reset Calibration"), callback=_callback)
    gui_app.push_widget(dialog)

  def _on_model_selected(self, result):
    dialog, self.model_dialog = self.model_dialog, None
    self.model_manager = ui_state.sm["modelManagerSP"]
    if result != DialogResult.CONFIRM or dialog is None or not ui_state.is_offroad() or self._download_pending():
      return
    selected_ref = dialog.selection_ref
    selected_bundle = (next((bundle for bundle in self.model_manager.availableBundles if bundle.ref == selected_ref), None)
                       if self.model_manager else None)
    if selected_ref == "Default":
      self._params.remove("ModelManager_ActiveBundle")
      self._show_reset_params_dialog()
    elif selected_bundle:
      self._params.put("ModelManager_DownloadIndex", selected_bundle.index, block=True)
      if self.model_manager.activeBundle.ref and selected_bundle.generation != self.model_manager.activeBundle.generation:
        self._show_reset_params_dialog()
    else:
      gui_app.push_widget(alert_dialog(tr("Model list changed or the service is unavailable. Reopen the model selector and try again.")))

  @staticmethod
  def _bundle_to_node(bundle):
    return TreeNode(bundle.ref, {'display_name': bundle.displayName, 'short_name': bundle.internalName})

  def _get_folders(self, favorites):
    bundles = self.model_manager.availableBundles
    folders = {}
    for bundle in bundles:
      folders.setdefault(next((ov_ride.value for ov_ride in bundle.overrides if ov_ride.key == "folder"), ""), []).append(bundle)

    folders_list = [TreeFolder("", [TreeNode("Default", {'display_name': DEFAULT_MODEL + tr(" (Default)"), 'short_name': "Default"})])]
    for folder, folder_bundles in sorted(folders.items(), key=lambda x: max((bundle.index for bundle in x[1]), default=-1), reverse=True):
      folder_bundles.sort(key=lambda bundle: bundle.index, reverse=True)
      date = m.group(1) if folder_bundles and (m := re.search(r'\(([^)]*)\)[^(]*$', folder_bundles[0].displayName)) else ""
      def display_name(folder=folder, date=date):
        return tr(folder) + (" - " + tr("Updated: {date}").format(date=date) if date else "")
      folders_list.append(TreeFolder(folder, [self._bundle_to_node(bundle) for bundle in folder_bundles], display_name))

    if favorites and (fav_bundles := [bundle for bundle in bundles if bundle.ref in favorites]):
      folders_list.insert(1, TreeFolder("Favorites", [self._bundle_to_node(bundle) for bundle in fav_bundles], lambda: tr("Favorites")))
    return folders_list

  def _handle_current_model_clicked(self):
    self.model_manager = ui_state.sm["modelManagerSP"]
    if not ui_state.is_offroad() or self._download_pending() or not self.model_manager:
      return
    favs = ui_state.params.get("ModelManager_Favs")
    favorites = set(favs.split(';')) if favs else set()
    folders_list = self._get_folders(favorites)

    active_ref = self.model_manager.activeBundle.ref if self.model_manager.activeBundle else "Default"
    self.model_dialog = TreeOptionDialog(lambda: tr("Select a Model"), folders_list, active_ref, "ModelManager_Favs",
                                         get_folders_fn=self._get_folders, on_exit=self._on_model_selected,
                                         display_func=lambda node: DEFAULT_MODEL + tr(" (Default)") if node.ref == "Default" else node.data['display_name'])
    gui_app.push_widget(self.model_dialog)

  def _update_state(self):
    advanced_controls: bool = ui_state.params.get_bool("ShowAdvancedControls")
    turn_desire: bool = ui_state.params.get_bool("LaneTurnDesire")
    live_delay: bool = ui_state.params.get_bool("LagdToggle")

    self.lane_turn_desire_toggle.action_item.set_state(turn_desire)
    self.lane_turn_value_control.set_visible(turn_desire and advanced_controls)
    self.lagd_toggle.action_item.set_state(live_delay)
    self.delay_control.set_visible(not live_delay and advanced_controls)
    new_step = int(round(100 / CV.MPH_TO_KPH)) if ui_state.is_metric else 100
    if self.lane_turn_value_control.action_item.value_change_step != new_step:
      self.lane_turn_value_control.action_item.value_change_step = new_step

    self._update_lagd_description(live_delay)
    self.model_manager = ui_state.sm["modelManagerSP"]
    self._handle_bundle_download_progress()
    self._update_operations()
    active_name = (self.model_manager.activeBundle.internalName if self.model_manager and self.model_manager.activeBundle.ref else
                   DEFAULT_MODEL + tr(" (Default)"))
    self.current_model_item.action_item.set_value(active_name)

    if not ui_state.is_offroad():
      self.current_model_item.action_item.set_enabled(False)
      self.current_model_item.set_description(tr("Only available when vehicle is off, or always offroad mode is on"))
    elif self._download_pending():
      self.current_model_item.action_item.set_enabled(False)
      self.current_model_item.set_description(tr("Wait for the current model download to finish, or cancel it first."))
    elif not self.model_manager:
      self.current_model_item.action_item.set_enabled(False)
      self.current_model_item.set_description(tr("Model service is unavailable. Please try again."))
    else:
      self.current_model_item.action_item.set_enabled(True)
      self.current_model_item.set_description("")

  def _render(self, rect):
    self._scroller.render(rect)

  def show_event(self):
    self._scroller.show_event()
