"""Capture real C4 setting widgets with an isolated parameter store and no vehicle."""
import argparse
import os
import subprocess
import types
from pathlib import Path
from tempfile import TemporaryDirectory

import pyray as rl
import pytest

from openpilot.common.params import Params
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import multilang
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog


def capture_c4_settings(output_dir, native=False):
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP, TITLES, make_panel
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.steering import PanelType
  from openpilot.system.ui.widgets.compact import CompactInfoPage

  output_dir.mkdir(parents=True, exist_ok=True)
  with OpenpilotPrefix(), TemporaryDirectory(prefix='c4-settings-') as scratch:
    ui_state.params = Params()
    ui_state.params.put_bool('ShowAdvancedControls', True, block=True)
    ui_state.params.put('LateralPositionOffset', 0, block=True)
    multilang._language = 'zh-CHS'
    multilang.setup()
    gui_app.init_window('C4 settings captures')
    if native:
      from openpilot.selfdrive.ui.mici.layouts.settings.settings import SettingsLayout
      from openpilot.selfdrive.ui.mici.layouts.settings.toggles import TogglesLayoutMici
      root = SettingsLayout()
    else:
      root = SettingsLayoutSP()
    gui_app.push_widget(root)

    def capture(widget, name):
      from openpilot.system.ui.widgets.nav_widget import NavWidget
      for _ in range(40 if native or isinstance(widget, NavWidget) else 4):
        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        widget.render(rl.Rectangle(0, 0, 536, 240))
        rl.end_drawing()
      if name is None:
        return
      target = output_dir / f'{name}.png'
      rl.take_screenshot(os.path.relpath(target.resolve()))
      if not target.exists():
        raise RuntimeError(f'Could not capture {target}')

    def focus(panel, item):
      panel.refresh()
      capture(panel, None)
      rows = [row for row in panel._list._scroller.items if row.is_visible]
      row = panel._rows[item][0]
      offset = -sum(previous.rect.width + 20 for previous in rows[:rows.index(row)])
      minimum = min(0, panel._list.rect.width - panel._list._scroller.content_size)
      panel._list._scroller.scroll_panel.set_offset(max(minimum, offset))

    capture(root, 'home')
    if native:
      toggles = TogglesLayoutMici()
      gui_app.push_widget(toggles)
      capture(toggles, 'toggles')
      gui_app.pop_widget()
      path = 'selfdrive/ui/sunnypilot/mici/layouts/steering.py'
      module = types.ModuleType('original_c4_steering')
      source = subprocess.check_output(['git', 'show', f'fcb67b6:{path}'], text=True)
      exec(compile(source, path, 'exec'), module.__dict__)
      steering = module.SteeringLayoutMici()
      gui_app.push_widget(steering)
      capture(steering, 'steering')
      gui_app.close()
      return
    root._set_category(0)
    capture(gui_app.get_active_widget(), 'driving_category')
    gui_app.pop_widget()
    for key in TITLES:
      panel = make_panel(key)
      gui_app.push_widget(panel)
      capture(panel, key)
      if key == 'device':
        capture_device_settings(panel, capture, focus)
        capture_pairing_settings(panel, capture)
      if key == 'visuals':
        controller = panel.controller
        for param in ('HideVEgoUI', 'ShowTurnSignals'):
          focus(panel, controller._toggles[param])
          capture(panel, 'visuals_' + param.lower())
        ui_state.params.put('ChevronInfo', 3, block=True)
        focus(panel, controller._chevron_info)
        capture(panel, 'visuals_chevron_unavailable')
        ui_state.has_longitudinal_control = True
        focus(panel, controller._chevron_info)
        capture(panel, 'visuals_chevron_saved_time')
        panel._open_enum(controller._chevron_info, lambda controller=controller: controller._chevron_info.title)
        capture(gui_app.get_active_widget(), 'visuals_chevron_options')
        gui_app.pop_widget()
        focus(panel, controller._dev_ui_info)
        capture(panel, 'visuals_developer_mode')
        panel._open_enum(controller._dev_ui_info, lambda controller=controller: controller._dev_ui_info.title)
        picker = gui_app.get_active_widget()
        capture(picker, None)
        picker._list.focus_item(picker._list._scroller.items[3])
        capture(picker, 'visuals_developer_both')
        gui_app.pop_widget()
        ui_state.params.remove('ChevronInfo')
        ui_state.has_longitudinal_control = False
      if key == 'vehicle':
        from cereal import car
        previous_cp = ui_state.CP
        selector = panel.controller._platform_selector
        selector._on_clicked()
        picker = gui_app.get_active_widget()
        capture(picker, 'vehicle_makes')
        if hasattr(picker, '_on_search_confirm'):
          picker._on_search_clicked()
          capture(gui_app.get_active_widget(), 'vehicle_search_keyboard')
          gui_app.pop_widget()
          picker._on_search_confirm(DialogResult.CONFIRM, 'Toyota Corolla 2021')
          capture(picker, None)
          leaf = next(row for row, item in zip(picker._compact_page._list._scroller.items, picker.visible_items, strict=True)
                      if not item.is_folder)
          picker._compact_page._list.focus_item(leaf)
          capture(picker, 'vehicle_search_results')
          leaf.callback()
          capture(picker, 'vehicle_picker_confirmation')
          picker._compact_confirm._click_callback()
          capture(gui_app.get_active_widget(), 'vehicle_apply_confirmation')
          confirm_list = gui_app.get_active_widget()._compact_view._list
          confirm_list._scroller.scroll_panel.set_offset(confirm_list.rect.height - confirm_list._scroller.content_size)
          capture(gui_app.get_active_widget(), 'vehicle_apply_detail')
          gui_app.get_active_widget()._confirm_button_callback()
          capture(panel, 'vehicle_manual_selection')
          selector._on_clicked()
          capture(gui_app.get_active_widget(), 'vehicle_remove_confirmation')
          confirm_list = gui_app.get_active_widget()._compact_view._list
          confirm_list._scroller.scroll_panel.set_offset(confirm_list.rect.height - confirm_list._scroller.content_size)
          capture(gui_app.get_active_widget(), 'vehicle_remove_detail')
          gui_app.get_active_widget()._confirm_button_callback()
        else:
          gui_app.get_active_widget()._confirm_button_callback()
        for brand in ('toyota', 'subaru', 'tesla', 'hyundai'):
          ui_state.CP = car.CarParams.new_message(brand=brand, openpilotLongitudinalControl=True, alphaLongitudinalAvailable=True)
          ui_state.has_longitudinal_control = True
          panel.refresh()
          focus(panel, panel.controller._brand_items[0])
          capture(panel, f'vehicle_{brand}')
        ui_state.CP = previous_cp
        ui_state.has_longitudinal_control = False
        panel.refresh()
      if key == 'steering':
        for child in (PanelType.MADS, PanelType.LANE_CHANGE, PanelType.TORQUE_CONTROL):
          panel.controller._set_current_panel(child)
          capture(panel, child.name.lower())
        panel.controller._set_current_panel(PanelType.STEERING)
        item = panel.controller._lat_position_offset
        panel._open_number(item, lambda item=item: item.title, lambda item=item: item.description)
        capture(gui_app.get_active_widget(), 'number')
        gui_app.pop_widget()
        help_page = CompactInfoPage(lambda item=item: item.title, lambda item=item: item.description, True)
        gui_app.push_widget(help_page)
        capture(help_page, 'description')
        gui_app.pop_widget()
      if key == 'display':
        brightness = panel.controller._onroad_brightness
        focus(panel, brightness)
        capture(panel, 'display_brightness_auto')
        panel._open_number(brightness, lambda brightness=brightness: brightness.title, lambda brightness=brightness: brightness.description)
        picker = gui_app.get_active_widget()
        capture(picker, None)
        picker._list.focus_item(picker._list._scroller.items[1])
        capture(picker, 'display_brightness_modes')
        picker._list._scroller.items[2].callback()
        focus(panel, brightness)
        capture(panel, 'display_brightness_screen_off')
        panel._rows[brightness][0].help_callback()
        help_page = gui_app.get_active_widget()
        capture(help_page, 'display_brightness_help')
        help_page._list._scroller.scroll_panel.set_offset(help_page._list.rect.height - help_page._list._scroller.content_size)
        capture(help_page, 'display_brightness_help_end')
        gui_app.pop_widget()
        delay = panel.controller._onroad_brightness_timer
        panel._open_number(delay, lambda delay=delay: delay.title, lambda delay=delay: delay.description)
        gui_app.get_active_widget()._list._scroller.items[5].callback()
        focus(panel, delay)
        capture(panel, 'display_brightness_delay_30_seconds')
        panel._rows[delay][0].help_callback()
        help_page = gui_app.get_active_widget()
        capture(help_page, 'display_brightness_delay_help')
        help_page._list._scroller.scroll_panel.set_offset(help_page._list.rect.height - help_page._list._scroller.content_size)
        capture(help_page, 'display_brightness_delay_help_end')
        gui_app.pop_widget()
        ui_state.params.put('OnroadScreenOffBrightness', 0, block=True)
        focus(panel, delay)
        capture(panel, 'display_brightness_delay_disabled')
        ui_state.params.put('InteractivityTimeout', 90, block=True)
        focus(panel, panel.controller._interactivity_timeout)
        capture(panel, 'display_timeout_90_seconds')
        panel._rows[panel.controller._interactivity_timeout][0].help_callback()
        help_page = gui_app.get_active_widget()
        capture(help_page, 'display_interactivity_help')
        help_page._list._scroller.scroll_panel.set_offset(help_page._list.rect.height - help_page._list._scroller.content_size)
        capture(help_page, 'display_interactivity_help_end')
        gui_app.pop_widget()
        ui_state.params.put('Timezone', 6, block=True)
        item = panel.controller._timezone_item
        panel.refresh()
        panel._open_number(item, lambda item=item: item.title, lambda item=item: item.description)
        picker = gui_app.get_active_widget()
        capture(picker, 'timezone')
        picker._query = 'Shanghai'
        picker._filter_rows()
        picker._list._scroller.scroll_panel.set_offset(0)
        capture(picker, 'timezone_english_search')
        picker._query = 'missing-zone'
        picker._filter_rows()
        capture(picker, 'timezone_no_results')
        gui_app.pop_widget()
        ui_state.params.remove('InteractivityTimeout')
        ui_state.params.remove('Timezone')
        ui_state.params.remove('OnroadScreenOffBrightness')
        ui_state.params.remove('OnroadScreenOffTimer')
      if key == 'firehose':
        panel.controller._segment_count = 123
        panel.controller._stats_available = True
        panel.controller._stats_status = 'Unable to fetch training statistics'
        capture(panel, 'firehose_status')
        row = panel._list._scroller.items[1]
        capture(panel, None)
        panel._list.focus_item(row)
        capture(panel, 'firehose_contributions')
        row.callback()
        capture(gui_app.get_active_widget(), 'firehose_contribution_detail')
        gui_app.pop_widget()
      if key == 'sunnylink':
        capture_pairing_settings(panel, capture, sunnylink=True)
        from cereal import custom
        previous_sm = ui_state.sm
        ui_state.sm = {'backupManagerSP': custom.BackupManagerSP.new_message()}
        ui_state.params.put_bool('SunnylinkEnabled', True, block=True)
        controller = panel.controller
        controller._start_transfer('backup')
        focus(panel, controller._transfer_item)
        capture(panel, 'backup_waiting')
        controller._transfer_wait_started -= controller.TRANSFER_WAIT_TIMEOUT + 1
        capture(panel, 'backup_wait_timeout')
        ui_state.sm['backupManagerSP'].backupStatus = 'inProgress'
        ui_state.sm['backupManagerSP'].backupProgress = 42
        capture(panel, 'backup_progress')
        ui_state.params.remove('BackupManager_CreateBackup')
        ui_state.sm['backupManagerSP'].backupStatus = 'failed'
        ui_state.sm['backupManagerSP'].lastError = 'Failed to upload backup'
        capture(panel, 'backup_failed')
        panel._rows[controller._transfer_item][0].callback()
        capture(gui_app.get_active_widget(), 'backup_error_detail')
        gui_app.pop_widget()
        controller._start_transfer('restore')
        ui_state.sm['backupManagerSP'].restoreStatus = 'inProgress'
        ui_state.sm['backupManagerSP'].restoreProgress = 20
        capture(panel, 'restore_progress')
        ui_state.params.remove('BackupManager_RestoreVersion')
        ui_state.sm['backupManagerSP'].restoreStatus = 'completed'
        ui_state.sm['backupManagerSP'].restoreProgress = 100
        panel.refresh()
        capture(gui_app.get_active_widget(), 'restore_restart')
        gui_app.get_active_widget()._cancel_button_callback()
        ui_state.sm = previous_sm
        ui_state.params.remove('SunnylinkEnabled')
      if key == 'network':
        from openpilot.selfdrive.ui.lib.prime_state import PrimeType
        previous_prime = ui_state.prime_state.get_type
        ui_state.prime_state.get_type = lambda: PrimeType.NONE
        try:
          ui_state.params.put('GsmApn', 'example.apn', block=True)
          capture(panel, None)
          panel._list.focus_item(panel._list._scroller.items[6])
          capture(panel, 'network_apn_value')
          panel.native._edit_apn()
          capture(gui_app.get_active_widget(), 'network_apn_editor')
          gui_app.pop_widget()
          ui_state.params.remove('GsmApn')
          capture(panel, 'network_apn_automatic')
          panel.native._wifi_manager._tethering_password = 'example-password'
          panel.native._tethering_password_btn._click_callback()
          capture(gui_app.get_active_widget(), 'network_hotspot_password_editor')
          gui_app.pop_widget()
        finally:
          ui_state.prime_state.get_type = previous_prime
        from openpilot.system.ui.lib.wifi_manager import Network, SecurityType
        manager = types.SimpleNamespace(networks=[Network('Home Wi-Fi', 90, SecurityType.WPA2, False)],
                                        connecting_to_ssid=None, connected_ssid='Home Wi-Fi',
                                        wifi_state=types.SimpleNamespace(ssid='Home Wi-Fi'),
                                        is_connection_saved=lambda _: True, set_active=lambda _: None,
                                        add_callbacks=lambda **kwargs: None, forget_connection=lambda _: None)
        from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import WifiUIMici
        from openpilot.selfdrive.ui.sunnypilot.mici.layouts.network import WifiPanel
        wifi = WifiPanel(WifiUIMici(manager))
        gui_app.push_widget(wifi)
        capture(wifi, 'wifi_connected')
        gui_app.pop_widget()
      if key == 'trips':
        panel.controller._stats = {'all': {'routes': 12, 'distance': 110, 'minutes': 420},
                                   'week': {'routes': 3, 'distance': 20, 'minutes': 80}}
        panel.controller._status = 'Unable to fetch drive statistics'
        capture(panel, 'trips_cached_failure')
      if key == 'device':
        panel.controller._reset_settings()
        capture(gui_app.get_active_widget(), 'reset_settings_first_confirmation')
        gui_app.get_active_widget()._confirm_button_callback()
        capture(gui_app.get_active_widget(), 'reset_settings_second_confirmation')
        gui_app.get_active_widget()._cancel_button_callback()
      if key == 'osm':
        controller = panel.controller
        controller._mem_params = Params(str(Path(scratch) / 'memory'))
        controller._show_region_dialog('Country', controller._country_btn, [('CN', 'China'), ('GE', 'Georgia'), ('US', 'United States')])
        picker = gui_app.get_active_widget()
        capture(picker, 'map_country_picker')
        picker._compact_page._list._scroller.items[0].callback()
        capture(picker, 'map_country_confirmation')
        picker._set_result(DialogResult.CANCEL)
        controller._show_region_dialog('State', controller._state_btn, [('CA', 'California'), ('GA', 'Georgia')])
        capture(gui_app.get_active_widget(), 'map_state_picker')
        gui_app.get_active_widget()._set_result(DialogResult.CANCEL)
        controller._show_region_dialog('State', controller._state_btn, [])
        capture(gui_app.get_active_widget(), 'map_region_failure')
        gui_app.get_active_widget()._cancel_button_callback()
        ui_state.params.put('OsmLocationName', 'CN', block=True)
        ui_state.params.put('OsmLocationTitle', 'China', block=True)
        ui_state.params.put('OSMDownloadProgress', {'total_files': 10, 'downloaded_files': 4}, block=True)
        controller._mem_params.put('OSMDownloadLocations', {'nations': ['CN'], 'states': []}, block=True)
        controller._update_labels()
        focus(panel, controller._progress)
        capture(panel, 'map_download_progress')
        controller._mem_params.remove('OSMDownloadLocations')
        controller._update_labels()
        focus(panel, controller._progress)
        capture(panel, 'map_download_failure')
        focus(panel, controller._update_btn)
        capture(panel, 'map_download_retry')
        controller._deleting = True
        controller._update_labels()
        focus(panel, controller._delete_maps_btn)
        capture(panel, 'map_deleting')
        controller._deleting = False
        for param in ('OsmLocationName', 'OsmLocationTitle', 'OSMDownloadProgress'):
          ui_state.params.remove(param)
      if key == 'software':
        ui_state.params.put('UpdaterState', 'downloading...', block=True)
        panel.refresh()
        focus(panel, panel.controller._download_btn)
        capture(panel, 'software_downloading')
        ui_state.params.remove('UpdaterState')
      if key == 'toggles':
        focus(panel, panel.controller._toggles['ExperimentalMode'])
        capture(panel, 'experimental_unavailable')
      if key == 'developer':
        from openpilot.selfdrive.ui.widgets.ssh_key import SshKeyActionState
        action = panel.controller._ssh_keys.action_item
        focus(panel, panel.controller._ssh_keys)
        capture(panel, 'ssh_keys_empty')
        action._handle_button_click()
        capture(gui_app.get_active_widget(), 'ssh_username_editor')
        gui_app.pop_widget()
        fetcher = action._fetcher
        fetcher._generation += 1
        fetcher._busy = True
        fetcher._on_response = action._on_fetch_response
        action._state = SshKeyActionState.LOADING
        capture(panel, 'ssh_keys_loading')
        fetcher._results.put((fetcher._generation, 'example-user', fetcher.snapshot(), None,
                              "Unable to fetch SSH keys for user '{}'. Check the username and try again."))
        panel.refresh()
        capture(gui_app.get_active_widget(), 'ssh_keys_failed')
        gui_app.get_active_widget()._confirm_button_callback()
        fetcher._generation += 1
        fetcher._busy = True
        fetcher._on_response = action._on_fetch_response
        fetcher._results.put((fetcher._generation, 'example-user', fetcher.snapshot(), 'ssh-ed25519 example-public-key', None))
        panel.refresh()
        focus(panel, panel.controller._ssh_keys)
        capture(panel, 'ssh_keys_saved')
        action._handle_button_click()
        capture(gui_app.get_active_widget(), 'ssh_keys_remove_confirmation')
        gui_app.get_active_widget()._confirm_button_callback()
        from openpilot.selfdrive.ui.sunnypilot.layouts.settings.log_operations import scan_logs, LogDeleteResult
        controller = panel.controller
        log_root = Path(scratch) / 'logs'
        log_root.mkdir()
        (log_root / 'swaglog.1').write_text('sample system log')
        controller.swaglog_root = str(log_root)
        controller._log_status = 'Scanning system logs'
        controller._log_running = True
        focus(panel, controller._log_status_item)
        capture(panel, 'system_log_scanning')
        controller._log_events.put(('scan', scan_logs(str(log_root))))
        panel.refresh()
        capture(gui_app.get_active_widget(), 'system_log_confirmation')
        gui_app.get_active_widget()._cancel_button_callback()
        controller._log_events.put(('deleted', LogDeleteResult(3, 1, 1, ('swaglog.2: read-only filesystem',))))
        panel.refresh()
        capture(gui_app.get_active_widget(), 'system_log_partial_result')
        result_view = gui_app.get_active_widget()._compact_view
        result_view._list._scroller.scroll_panel.set_offset(result_view._list.rect.height - result_view._list._scroller.content_size)
        capture(gui_app.get_active_widget(), 'system_log_partial_detail')
        gui_app.get_active_widget()._ok_button._click_callback()
        focus(panel, controller._log_status_item)
        capture(panel, 'system_log_incomplete')
        controller.error_log_path = str(log_root / 'error.log')
        Path(controller.error_log_path).write_text('ValueError: <input> & data\nexample error detail')
        controller._on_error_log_clicked()
        capture(gui_app.get_active_widget(), 'error_log_literal_text')
        error_view = gui_app.get_active_widget()._compact_view
        error_view._list._scroller.scroll_panel.set_offset(error_view._list.rect.height - error_view._list._scroller.content_size)
        capture(gui_app.get_active_widget(), 'error_log_literal_detail')
        gui_app.get_active_widget()._ok_button._click_callback()
        gui_app.get_active_widget()._cancel_button_callback()
      gui_app.pop_widget()
    capture_visual_overlays(capture)
    confirm = ConfirmDialog('确认页示例。', '确认', rich=True, callback=lambda _: DialogResult.NO_ACTION)
    gui_app.push_widget(confirm)
    capture(confirm, 'confirmation')
    gui_app.pop_widget()
    from openpilot.system.ui.sunnypilot.widgets.tree_dialog import TreeOptionDialog, TreeFolder, TreeNode
    tree = TreeOptionDialog('Models', [TreeFolder('', [TreeNode('one', {'display_name': '示例模型 A'}),
                                                      TreeNode('two', {'display_name': '示例模型 B'})])],
                            current_ref='one', fav_param='ModelManager_Favs')
    gui_app.push_widget(tree)
    capture(tree, 'model_selection')
    tree._compact_page._list._scroller.items[1].callback()
    capture(tree, 'model_confirmation')
    gui_app.pop_widget()
    # Controlled USB state uses the real controller/cards, without mounting a drive.
    from openpilot.system import usb_mount
    panel = make_panel('developer')
    controller = panel.controller
    controller._refresh_usb_state = lambda: None
    controller._apply_usb_state([{'device': '/dev/example1', 'size': '8G', 'fstype': 'vfat'}], True, '/dev/example1')
    controller._usb_expanded = True
    gui_app.push_widget(panel)

    focus(panel, controller._usb_mount_item)
    capture(panel, 'usb_mount')
    controller._usb_exporting = True
    controller._usb_events.put(('progress', (42, usb_mount.UsbMessage('Route data: {filename}', filename='route/rlog.zst'))))
    focus(panel, controller._usb_export_progress_item)
    capture(panel, 'usb_progress')
    controller._usb_events.put(('export', (True, usb_mount.UsbMessage('Exported {count}/{total} sources', count=2, total=2))))
    panel.refresh()
    capture(gui_app.get_active_widget(), 'usb_result')
    gui_app.close()


def capture_device_settings(panel, capture, focus):
  """Capture real device controls and alert labels with controlled calibration/camera services."""
  from cereal import messaging
  from pytest import MonkeyPatch
  from openpilot.selfdrive.ui.mici.onroad import driver_camera_dialog as camera
  from openpilot.system.ui.widgets.compact import CompactInfoPage

  event = messaging.new_message('liveCalibration')
  event.liveCalibration.calStatus = 'calibrated'
  event.liveCalibration.rpyCalib = [0, 0.03, -0.02]
  ui_state.params.put('CalibrationParams', event.to_bytes(), block=True)
  for service, param, percentage in [('liveDelay', 'LiveDelay', 32), ('liveTorqueParameters', 'LiveTorqueParameters', 48)]:
    event = messaging.new_message(service)
    getattr(event, service).calPerc = percentage
    if service == 'liveTorqueParameters':
      event.liveTorqueParameters.useParams = True
    ui_state.params.put(param, event.to_bytes(), block=True)
  controller = panel.controller
  controller._update_calib_description()
  focus(panel, controller._reset_calib_btn)
  capture(panel, 'device_calibration')
  help_page = CompactInfoPage(lambda: controller._reset_calib_btn.title, lambda: controller._reset_calib_btn.description, True)
  gui_app.push_widget(help_page)
  capture(help_page, 'device_calibration_help')
  help_page._list._scroller.scroll_panel.set_offset(-140)
  capture(help_page, 'device_calibration_help_progress')
  help_page._list._scroller.scroll_panel.set_offset(help_page._list.rect.height - help_page._list._scroller.content_size)
  capture(help_page, 'device_calibration_help_end')
  gui_app.pop_widget()
  for method, name in [(controller._reset_calibration_prompt, 'calibration_reset'), (controller._reboot_prompt, 'reboot'),
                       (controller._power_off_prompt, 'power_off')]:
    method()
    dialog = gui_app.get_active_widget()
    capture(dialog, 'device_' + name + '_confirmation')
    dialog._cancel_button_callback()
  controller._show_language_dialog()
  capture(gui_app.get_active_widget(), 'device_languages')
  gui_app.get_active_widget()._set_result(DialogResult.CANCEL)

  class NoCamera:
    frame = None

    def __init__(self, *args):
      pass

    def _update_state(self):
      pass

    def _render(self, rect):
      pass

    def close(self):
      pass

  class AlertPreview(camera.DriverCameraDialog):
    def _render(self, rect):
      self._render_dm_alerts(rect)

  publisher = types.SimpleNamespace(send=lambda service, msg: None)
  with MonkeyPatch.context() as controlled:
    controlled.setattr(camera, 'DriverCameraView', NoCamera)
    controlled.setattr(camera.messaging, 'PubMaster', lambda services: publisher)
    controller._open_driver_camera()
    capture(gui_app.get_active_widget(), 'device_camera_starting')
    gui_app.pop_widget()
    dm = messaging.new_message('driverMonitoringState').driverMonitoringState
    controlled.setattr(ui_state, 'sm', {'driverMonitoringState': dm})
    view = AlertPreview()
    gui_app.push_widget(view)
    for policy in ('vision', 'wheeltouch'):
      dm.activePolicy = policy
      dm.visionPolicyState.awarenessPercent = 75
      dm.wheeltouchPolicyState.awarenessPercent = 80
      for level in ('one', 'two', 'three'):
        dm.alertLevel = level
        capture(view, f'device_camera_{policy}_{level}')
    gui_app.pop_widget()
    controlled.setattr(ui_state, 'sm', types.SimpleNamespace(recv_frame={'driverMonitoringState': 0}))
    controller._on_review_training_guide()
    guide = gui_app.get_active_widget()
    capture(guide, 'training_attention')

    def native_focus(page, index, name):
      capture(page, None)
      scroller = page._scroller
      visible = [item for item in scroller.items if item.is_visible]
      offset = -sum(item.rect.width + 20 for item in visible[:index])
      scroller.scroll_panel.set_offset(offset)
      capture(page, name)

    for index in range(1, 5):
      native_focus(guide._steps[0], index, f'training_attention_rule_{index}')
    gui_app.push_widget(guide._steps[1])
    capture(guide._steps[1], 'training_camera_intro')
    native_focus(guide._steps[1], 3, 'training_camera_remount')
    gui_app.push_widget(guide._steps[2])
    capture(guide._steps[2], 'training_camera_starting')
    gui_app.push_widget(guide._steps[2]._bad_face_page)
    capture(gui_app.get_active_widget(), 'training_camera_help')
    gui_app.pop_widget()
    gui_app.push_widget(guide._steps[3])
    capture(guide._steps[3], 'training_upload_intro')
    native_focus(guide._steps[3], 1, 'training_upload_question')
    native_focus(guide._steps[3], 2, 'training_upload_explanation')
    native_focus(guide._steps[3], 3, 'training_upload_allow')
    guide._steps[3]._accept_button._click_callback()
    capture(gui_app.get_active_widget(), 'training_upload_allow_confirmation')
    gui_app.pop_widget()
    native_focus(guide._steps[3], 4, 'training_upload_decline')
    guide._steps[3]._decline_button._click_callback()
    capture(gui_app.get_active_widget(), 'training_upload_decline_confirmation')
    gui_app.pop_widget()
    gui_app.pop_widgets_to(panel, instant=True)
    from openpilot.selfdrive.ui.mici.layouts.settings.device import ReviewTermsPage
    terms = ReviewTermsPage()
    gui_app.push_widget(terms)
    capture(terms, 'device_review_terms')
    native_focus(terms, 1, 'device_review_terms_qr')
    gui_app.pop_widget()
  for param in ('CalibrationParams', 'LiveDelay', 'LiveTorqueParameters'):
    ui_state.params.remove(param)


def capture_pairing_settings(panel, capture, sunnylink=False):
  """Capture pairing controls with example tokens; do not create real account credentials."""
  from pytest import MonkeyPatch
  from openpilot.selfdrive.ui.mici.widgets import pairing_dialog as comma
  from openpilot.selfdrive.ui.sunnypilot.mici.widgets import sunnylink_pairing_dialog as sunny
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts import settings_controllers as controllers
  state = {'token': 'example-pair-token'}
  previous = {param: ui_state.params.get(param) for param in ('DongleId', 'SunnylinkDongleId', 'SunnylinkEnabled')}
  ui_state.params.put('DongleId', 'example-device', block=True)
  ui_state.params.put('SunnylinkDongleId', 'example-sunnylink-device', block=True)
  ui_state.params.put_bool('SunnylinkEnabled', True, block=True)
  with MonkeyPatch.context() as controlled:
    controlled.setattr(comma, 'Api', lambda identity: types.SimpleNamespace(get_token=lambda *args: state['token']))
    controlled.setattr(sunny, 'SunnylinkApi', lambda identity: types.SimpleNamespace(get_token=lambda *args: state['token']))
    controlled.setattr(ui_state, 'prime_state', types.SimpleNamespace(is_paired=lambda: False))
    controlled.setattr(controllers, 'system_time_valid', lambda: True)
    prefix = 'pairing_sunnylink' if sunnylink else 'pairing_comma'
    if sunnylink:
      panel.controller._handle_pair_btn(True)
    else:
      panel.controller._open_pairing()
    dialog = gui_app.get_active_widget()
    capture(dialog, prefix)
    state['token'] = 'header.' + 'payload' * 32 + '.' + 'signature' * 38
    dialog._last_qr_generation = float('-inf')
    capture(dialog, prefix + '_long_token')
    state['token'] = None
    dialog._last_qr_generation = float('-inf')
    capture(dialog, prefix + '_error')
    state['token'] = 'recovered-example-token'
    dialog._retry_button._click_callback()
    capture(dialog, prefix + '_retry')
    gui_app.pop_widget()
    if sunnylink:
      panel.controller._handle_pair_btn(False)
      capture(gui_app.get_active_widget(), 'pairing_sponsorship')
      gui_app.pop_widget()
    else:
      ui_state.params.remove('DongleId')
      panel.controller._open_pairing()
      capture(gui_app.get_active_widget(), 'pairing_comma_registration_error')
      gui_app.get_active_widget()._confirm_button_callback()
      ui_state.params.put('DongleId', 'example-device', block=True)
      controlled.setattr(controllers, 'system_time_valid', lambda: False)
      panel.controller._open_pairing()
      capture(gui_app.get_active_widget(), 'pairing_comma_clock_error')
      gui_app.get_active_widget()._confirm_button_callback()
  for param, value in previous.items():
    if value is None:
      ui_state.params.remove(param)
    else:
      ui_state.params.put(param, value, block=True)


def capture_visual_overlays(capture):
  """Render real overlays on an empty canvas using controlled driving messages."""
  from cereal import car, messaging
  from openpilot.selfdrive.ui.ui_state import UIStatus
  from openpilot.selfdrive.ui.sunnypilot.ui_state import UIStateSP
  from openpilot.selfdrive.ui.sunnypilot.mici.onroad.hud_renderer import HudRendererSP
  from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer, LeadVehicle
  from openpilot.system.ui.widgets import Widget

  class Messages(dict):
    recv_frame = {'carState': 100}

  class Overlay(Widget):
    def __init__(self):
      super().__init__()
      self.hud = HudRendererSP()
      self.model = ModelRenderer()
      self.show_model = False
      self.model._lead_vehicles[0] = LeadVehicle(glow=[(301, 130), (268, 115), (235, 130)],
                                                chevron=[(292, 130), (268, 119), (244, 130)], fill_alpha=255)

    def _render(self, rect):
      if self.show_model:
        self.model.set_rect(rect)
        self.model._draw_lead_indicator()
      self.hud.render(rect)

  previous = {key: getattr(ui_state, key) for key in ('sm', 'started', 'started_frame', 'status', 'CP', 'has_longitudinal_control', 'is_metric')}
  services = ('carState', 'controlsState', 'selfdriveState', 'longitudinalPlanSP', 'liveMapDataSP', 'radarState',
              'onroadEvents', 'carOutput', 'carControl')
  ui_state.sm = Messages({service: getattr(messaging.new_message(service, size=0) if service == 'onroadEvents' else
                                           messaging.new_message(service), service) for service in services})
  cs = ui_state.sm['carState']
  cs.vCruiseCluster, cs.vEgoCluster, cs.vEgo, cs.aEgo, cs.steeringAngleDeg = 80, 12, 10, 1, 5
  lead = ui_state.sm['radarState'].leadOne
  lead.status, lead.dRel, lead.vRel = True, 30, -1
  ui_state.sm['liveMapDataSP'].roadName = '测试道路'
  ui_state.started, ui_state.started_frame, ui_state.status = True, 0, UIStatus.DISENGAGED
  ui_state.CP = car.CarParams.new_message(brand='toyota', openpilotLongitudinalControl=True, enableBsm=True)
  ui_state.has_longitudinal_control, ui_state.is_metric = True, True
  params = ('BlindSpot', 'TorqueBar', 'RainbowMode', 'StandstillTimer', 'RoadNameToggle', 'GreenLightAlert', 'LeadDepartAlert',
            'TrueVEgoUI', 'HideVEgoUI', 'ShowTurnSignals', 'RocketFuel', 'dp_show_date_time', 'DevUIInfo', 'ChevronInfo')
  saved_params = {param: ui_state.params.get(param) for param in params}
  for param in params[:12]:
    ui_state.params.put_bool(param, False, block=True)
  ui_state.params.put('DevUIInfo', 0, block=True)
  ui_state.params.put('ChevronInfo', 0, block=True)
  view = Overlay()
  gui_app.push_widget(view)
  try:
    def refresh():
      UIStateSP.update_params(ui_state)
    refresh()
    capture(view, 'visuals_hud_cluster_speed')
    ui_state.params.put_bool('TrueVEgoUI', True, block=True)
    refresh()
    capture(view, 'visuals_hud_true_speed')
    ui_state.params.put_bool('HideVEgoUI', True, block=True)
    refresh()
    capture(view, 'visuals_hud_speed_hidden')
    ui_state.params.put_bool('HideVEgoUI', False, block=True)
    ui_state.params.put('DevUIInfo', 3, block=True)
    ui_state.params.put_bool('RoadNameToggle', True, block=True)
    ui_state.params.put_bool('RocketFuel', True, block=True)
    refresh()
    capture(view, 'visuals_hud_debug_metric')
    ui_state.is_metric = False
    capture(view, 'visuals_hud_debug_imperial')
    ui_state.is_metric = True
    ui_state.params.put_bool('LeadDepartAlert', True, block=True)
    ui_state.sm['longitudinalPlanSP'].e2eAlerts.leadDepartAlert = True
    capture(view, 'visuals_hud_lead_notice')
    view.hud.set_can_draw_top_icons(False)
    capture(view, 'visuals_hud_alert_priority')
    view.hud.set_can_draw_top_icons(True)
    ui_state.sm['longitudinalPlanSP'].e2eAlerts.leadDepartAlert = False
    ui_state.params.put_bool('LeadDepartAlert', False, block=True)
    ui_state.params.put_bool('BlindSpot', True, block=True)
    cs.leftBlindspot, cs.rightBlindspot = True, True
    refresh()
    capture(view, 'visuals_hud_blind_spots')
    cs.leftBlindspot, cs.rightBlindspot = False, False
    ui_state.params.put_bool('BlindSpot', False, block=True)
    ui_state.params.put('DevUIInfo', 0, block=True)
    ui_state.params.put_bool('RoadNameToggle', False, block=True)
    ui_state.params.put_bool('RocketFuel', False, block=True)
    ui_state.params.put('ChevronInfo', 4, block=True)
    refresh()
    view.show_model = True
    capture(view, 'visuals_hud_chevron_all')
    ui_state.params.put('ChevronInfo', 0, block=True)
    refresh()
    capture(view, 'visuals_hud_chevron_off')
  finally:
    gui_app.pop_widget()
    for key, value in previous.items():
      setattr(ui_state, key, value)
    for param, value in saved_params.items():
      if value is None:
        ui_state.params.remove(param)
      else:
        ui_state.params.put(param, value, block=True)
    UIStateSP.update_params(ui_state)


def capture_selector_changes(output_dir):
  """Capture selector conflicts after rejecting the stale choice without requests."""
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import make_panel
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.models import ModelsLayout
  from openpilot.system.ui.widgets.compact import CompactPage

  output_dir.mkdir(parents=True, exist_ok=True)
  previous_language = multilang.language
  with OpenpilotPrefix(), pytest.MonkeyPatch.context() as patches:
    patches.setattr(ui_state, 'params', Params())
    patches.setattr(ui_state, 'started', False)
    patches.setattr(ui_state, 'force_onroad', False)
    patches.setattr(ModelsLayout, '_refresh_cache_size', lambda self: None)
    manager = custom.ModelManagerSP.new_message(availableBundles=[{
      'ref': 'example-model', 'index': 7, 'internalName': 'Example model', 'displayName': 'Example model'
    }])
    patches.setattr(ui_state, 'sm', {'modelManagerSP': manager})
    ui_state.params.put_bool('ShowAdvancedControls', True, block=True)
    multilang._language = 'zh-CHS'
    multilang.setup()
    gui_app.init_window('C4 selector changes')
    gui_app._nav_stack.clear()
    gui_app.push_widget(CompactPage('root'))

    def capture(widget, name):
      for _ in range(4):
        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        widget.render(rl.Rectangle(0, 0, 536, 240))
        rl.end_drawing()
      target = output_dir / f'{name}.png'
      rl.take_screenshot(os.path.relpath(target.resolve()))
      if not target.exists():
        raise RuntimeError(f'Could not capture {target}')

    try:
      for language in ('zh-CHS', 'en'):
        multilang._language = language
        multilang.setup()
        gui_app.on_language_changed(language)
        ui_state.sm = {'modelManagerSP': manager}
        panel = make_panel('models')
        gui_app.push_widget(panel)
        for state in ('removed', 'unavailable'):
          panel.controller._handle_current_model_clicked()
          picker = panel.controller.model_dialog
          picker.selection_ref = 'example-model'
          ui_state.sm = {'modelManagerSP': custom.ModelManagerSP.new_message() if state == 'removed' else None}
          picker._set_result(DialogResult.CONFIRM)
          dialog = gui_app.get_active_widget()
          assert isinstance(dialog, ConfirmDialog)
          capture(dialog, f'selector_model_{state}_{language}')
          scroll = dialog._compact_view._list
          scroll._scroller.scroll_panel.set_offset(scroll.rect.height - scroll._scroller.content_size)
          capture(dialog, f'selector_model_{state}_end_{language}')
          dialog._confirm_button_callback()
          ui_state.sm = {'modelManagerSP': manager}
        ui_state.sm = {'modelManagerSP': None}
        panel.refresh()
        panel._rows[panel.controller.current_model_item][0].help_callback()
        detail = gui_app.get_active_widget()
        capture(detail, f'selector_model_unavailable_help_{language}')
        scroll = detail._list
        scroll._scroller.scroll_panel.set_offset(scroll.rect.height - scroll._scroller.content_size)
        capture(detail, f'selector_model_unavailable_help_end_{language}')
        gui_app.pop_widget()
        gui_app.pop_widget()
        ui_state.params.put('UpdaterAvailableBranches', 'dev,release-mici', block=True)
        ui_state.params.put('UpdaterTargetBranch', 'dev', block=True)
        panel = make_panel('software')
        gui_app.push_widget(panel)
        panel.controller._on_select_branch()
        picker = panel.controller._branch_dialog
        picker.selection_ref = 'release-mici'
        ui_state.params.put('UpdaterAvailableBranches', 'dev', block=True)
        picker._set_result(DialogResult.CONFIRM)
        dialog = gui_app.get_active_widget()
        assert isinstance(dialog, ConfirmDialog)
        capture(dialog, f'selector_branch_changed_{language}')
        scroll = dialog._compact_view._list
        scroll._scroller.scroll_panel.set_offset(scroll.rect.height - scroll._scroller.content_size)
        capture(dialog, f'selector_branch_changed_end_{language}')
        dialog._confirm_button_callback()
        gui_app.pop_widget()
        assert ui_state.params.get('UpdaterTargetBranch') == 'dev'
        assert ui_state.params.get('ModelManager_DownloadIndex') is None
      assert not any(ui_state.params.get_bool(key) for key in ('DoReboot', 'DoUninstall'))
    finally:
      while len(gui_app._nav_stack) > 1:
        gui_app.pop_widget()
      gui_app.close()
      multilang._language = previous_language
      multilang.setup()


def capture_model_request_status(output_dir):
  """Render waiting/timeout/cancellation with real controls and isolated requests."""
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import make_panel
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.models import ModelsLayout
  from openpilot.system.ui.widgets.compact import CompactPage
  import time

  output_dir.mkdir(parents=True, exist_ok=True)
  previous_language = multilang.language
  with OpenpilotPrefix(), pytest.MonkeyPatch.context() as patches:
    patches.setattr(ui_state, 'params', Params())
    patches.setattr(ui_state, 'started', False)
    patches.setattr(ui_state, 'force_onroad', False)
    patches.setattr(ModelsLayout, '_refresh_cache_size', lambda self: None)
    requested = {'ref': 'example-requested', 'index': 9, 'internalName': 'Example requested model',
                 'displayName': 'Example requested model', 'status': 'downloaded',
                 'models': [{'type': 'supercombo', 'artifact': {'fileName': 'example.onnx',
                             'downloadProgress': {'status': 'downloaded', 'progress': 100}}}]}
    previous = {**requested, 'ref': 'example-previous', 'index': 7, 'internalName': 'Example previous model',
                'displayName': 'Example previous model', 'status': 'failed'}
    manager = custom.ModelManagerSP.new_message(selectedBundle=previous, availableBundles=[requested])
    patches.setattr(ui_state, 'sm', {'modelManagerSP': manager})
    ui_state.params.put_bool('ShowAdvancedControls', True, block=True)
    multilang._language = 'zh-CHS'
    multilang.setup()
    gui_app.init_window('C4 model waiting status')
    gui_app._nav_stack.clear()
    gui_app.push_widget(CompactPage('root'))

    def capture(widget, name=None):
      for _ in range(4):
        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        widget.render(rl.Rectangle(0, 0, 536, 240))
        rl.end_drawing()
      if name:
        target = output_dir / f'{name}.png'
        rl.take_screenshot(os.path.relpath(target.resolve()))
        if not target.exists():
          raise RuntimeError(f'Could not capture {target}')

    def focus(panel, item):
      capture(panel)
      panel._list.focus_item(panel._rows[item][0])

    try:
      panel = make_panel('models')
      gui_app.push_widget(panel)
      controller = panel.controller
      for language in ('zh-CHS', 'en'):
        multilang._language = language
        multilang.setup()
        gui_app.on_language_changed(language)
        ui_state.sm = {'modelManagerSP': manager}
        ui_state.params.put('ModelManager_DownloadIndex', 9, block=True)
        controller._download_request_index = None
        focus(panel, controller.download_request_item)
        capture(panel, f'model_request_waiting_{language}')
        panel._rows[controller.download_request_item][0].callback()
        detail = gui_app.get_active_widget()
        capture(detail, f'model_request_detail_{language}')
        scroll = detail._list._scroller
        scroll.scroll_panel.set_offset(detail._list.rect.height - scroll.content_size)
        capture(detail, f'model_request_detail_end_{language}')
        gui_app.pop_widget()
        controller._download_request_started = time.monotonic() - 31
        focus(panel, controller.download_request_item)
        capture(panel, f'model_request_timeout_{language}')
        panel._rows[controller.download_request_item][0].callback()
        capture(gui_app.get_active_widget(), f'model_request_timeout_detail_{language}')
        gui_app.pop_widget()
        # Reissue the same index without a render between cancellation and put.
        ui_state.params.remove('ModelManager_DownloadIndex')
        ui_state.params.put('ModelManager_DownloadIndex', 9, block=True)
        focus(panel, controller.download_request_item)
        capture(panel, f'model_request_quick_retry_{language}')
        from openpilot.system.ui.lib.multilang import tr
        assert controller.download_request_item.action_item.text == tr('Waiting for model service: {model}').format(
          model=requested['displayName'])
        ui_state.sm = {'modelManagerSP': None}
        controller._download_request_started = time.monotonic()
        focus(panel, controller.download_request_item)
        capture(panel, f'model_request_no_service_{language}')
        focus(panel, controller.cancel_download_item)
        capture(panel, f'model_request_cancel_{language}')
        panel._rows[controller.cancel_download_item][0].callback()
        assert ui_state.params.get('ModelManager_DownloadIndex') is None
        capture(panel, f'model_request_cancelled_{language}')
        ui_state.sm = {'modelManagerSP': manager}
        capture(panel)
        controller._retry_model_download()
        dialog = gui_app.get_active_widget()
        capture(dialog, f'model_request_retry_removed_{language}')
        scroll = dialog._compact_view._list._scroller
        scroll.scroll_panel.set_offset(dialog._compact_view._list.rect.height - scroll.content_size)
        capture(dialog, f'model_request_retry_removed_end_{language}')
        assert ui_state.params.get('ModelManager_DownloadIndex') is None
        gui_app.pop_widget()
      assert not any(ui_state.params.get_bool(key) for key in ('DoReboot', 'DoUninstall'))
    finally:
      while len(gui_app._nav_stack) > 1:
        gui_app.pop_widget()
      gui_app.close()
      multilang._language = previous_language
      multilang.setup()


def capture_action_information(output_dir):
  """Read update information through its real touch button without installing."""
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import make_panel
  from openpilot.system.ui.lib.application import MousePos, MouseEvent
  from openpilot.system.ui.widgets.compact import CompactPage, CompactInfoPage

  output_dir.mkdir(parents=True, exist_ok=True)
  previous_language = multilang.language
  with OpenpilotPrefix(), pytest.MonkeyPatch.context() as patches:
    patches.setattr(ui_state, 'params', Params())
    patches.setattr(ui_state, 'started', False)
    patches.setattr(ui_state, 'force_onroad', False)
    patches.setattr(gui_app, '_mouse_events', [])
    ui_state.params.put_bool('ShowAdvancedControls', True, block=True)
    ui_state.params.put_bool('UpdateAvailable', True, block=True)
    ui_state.params.put('UpdaterNewDescription', '2026.11 (example-mici-build-0123456789abcdef)', block=True)
    ui_state.params.put('UpdaterNewReleaseNotes', (
      '<h1>Example release notes</h1><ul><li>Improved settings navigation.</li><li>Updated display options.</li>' +
      ''.join(f'<li>Example change {index}: calibration and display behavior.</li>' for index in range(1, 12)) + '</ul>'
    ).encode(), block=True)
    ui_state.params.put('UpdaterTargetBranch', 'example-release-mici-with-a-long-branch-name', block=True)
    multilang._language = 'zh-CHS'
    multilang.setup()
    gui_app.init_window('C4 action information')
    gui_app._nav_stack.clear()
    gui_app.push_widget(CompactPage('root'))

    def render(widget):
      rl.begin_drawing()
      rl.clear_background(rl.BLACK)
      widget.render(rl.Rectangle(0, 0, 536, 240))
      rl.end_drawing()

    def capture(widget, name):
      for _ in range(4):
        render(widget)
      target = output_dir / f'{name}.png'
      rl.take_screenshot(os.path.relpath(target.resolve()))
      if not target.exists():
        raise RuntimeError(f'Could not capture {target}')

    try:
      panel = make_panel('software')
      gui_app.push_widget(panel)
      for language in ('zh-CHS', 'en'):
        multilang._language = language
        multilang.setup()
        gui_app.on_language_changed(language)
        for entry, item in [('install', panel.controller._install_btn), ('branch', panel.controller._branch_btn)]:
          render(panel)
          row = panel._rows[item][0]
          panel._list.focus_item(row)
          capture(panel, f'action_information_{entry}_card_{language}')
          icon = row._info.rect
          pos = MousePos(icon.x + icon.width / 2, icon.y + icon.height / 2)
          gui_app._mouse_events = [MouseEvent(pos, 0, True, False, True, 0), MouseEvent(pos, 0, False, True, False, .1)]
          render(panel)
          gui_app._mouse_events = []
          detail = gui_app.get_active_widget()
          assert isinstance(detail, CompactInfoPage)
          capture(detail, f'action_information_{entry}_detail_{language}')
          if entry == 'install':
            scroll = detail._list._scroller
            scroll.scroll_panel.set_offset(detail._list.rect.height - scroll.content_size)
            capture(detail, f'action_information_install_end_{language}')
          gui_app.pop_widget()
      assert not ui_state.params.get_bool('DoReboot')
      assert not ui_state.params.get_bool('DoUninstall')
    finally:
      while len(gui_app._nav_stack) > 1:
        gui_app.pop_widget()
      gui_app.close()
      multilang._language = previous_language
      multilang.setup()


def capture_status_details(output_dir):
  """Capture complete operation status and title text without service actions."""
  from cereal import custom
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import SettingsLayoutSP, make_panel
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.models import ModelsLayout
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.trips import TripsLayout
  from openpilot.selfdrive.ui.mici.layouts.settings.firehose import FirehoseLayoutBase
  from openpilot.system.ui.lib.application import MousePos, MouseEvent
  from openpilot.system.ui.widgets.compact import CompactPage, CompactInfoPage
  from openpilot.system.ui.widgets.label import ScrollState

  output_dir.mkdir(parents=True, exist_ok=True)
  previous_language = multilang.language
  with OpenpilotPrefix(), pytest.MonkeyPatch.context() as patches:
    patches.setattr(ui_state, 'params', Params())
    patches.setattr(ui_state, 'started', False)
    patches.setattr(ui_state, 'force_onroad', False)
    patches.setattr(ui_state, 'always_offroad', False)
    patches.setattr(ui_state, 'sm', {'modelManagerSP': custom.ModelManagerSP.new_message()})
    patches.setattr(ModelsLayout, '_refresh_cache_size', lambda self: None)
    patches.setattr(TripsLayout, '_update_loop', lambda self: None)
    patches.setattr(FirehoseLayoutBase, '_update_loop', lambda self: None)
    ui_state.params.put_bool('ShowAdvancedControls', True, block=True)
    ui_state.params.put_bool('BlinkerPauseLateralControl', True, block=True)
    ui_state.params.put_bool('dp_dev_disable_connect', True, block=True)
    multilang._language = 'zh-CHS'
    multilang.setup()
    gui_app.init_window('C4 complete status details')
    gui_app._nav_stack.clear()
    gui_app.push_widget(CompactPage('root'))

    def capture(widget, name):
      for _ in range(4):
        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        widget.render(rl.Rectangle(0, 0, 536, 240))
        rl.end_drawing()
      if name is None:
        return
      target = output_dir / f'{name}.png'
      rl.take_screenshot(os.path.relpath(target.resolve()))
      if not target.exists():
        raise RuntimeError(f'Could not capture {target}')

    try:
      for language in ('zh-CHS', 'en'):
        multilang._language = language
        multilang.setup()
        gui_app.on_language_changed(language)
        settings = SettingsLayoutSP()
        gui_app.push_widget(settings)
        capture(settings, f'header_shortcut_{language}')
        gui_app.pop_widget()
        panel = make_panel('steering')
        gui_app.push_widget(panel)
        panel._rows[panel.controller._blinker_control_options][0].callback()
        detail = gui_app.get_active_widget()
        capture(detail, f'header_numeric_start_{language}')
        label = detail._header._title_label
        if label._needs_scroll:
          label._scroll_state = ScrollState.SCROLLING
          label._scroll_offset = -max(0, label.text_width - label.rect.width)
        capture(detail, f'header_numeric_end_{language}')
        gui_app.pop_widget()
        gui_app.pop_widget()
        panel = make_panel('models')
        gui_app.push_widget(panel)
        controller = panel.controller
        controller._refresh_started = 0
        ui_state.params.put('ModelManager_LastSyncTime', 0, block=True)
        panel.refresh()
        panel._rows[controller.refresh_item][0].help_callback()
        capture(gui_app.get_active_widget(), f'model_refresh_status_detail_{language}')
        gui_app.pop_widget()
        controller._cache_request_started = 0
        ui_state.params.put_bool('ModelManager_ClearCache', True, block=True)
        panel.refresh()
        panel._rows[controller.clear_cache_item][0].help_callback()
        capture(gui_app.get_active_widget(), f'model_cache_status_detail_{language}')
        gui_app.pop_widget()
        gui_app.pop_widget()
        ui_state.params.remove('ModelManager_ClearCache')
        panel = make_panel('software')
        gui_app.push_widget(panel)
        panel.controller._updater_timeout = True
        panel.refresh()
        panel._rows[panel.controller._download_btn][0].help_callback()
        capture(gui_app.get_active_widget(), f'software_status_detail_{language}')
        gui_app.pop_widget()
        gui_app.pop_widget()
        for key, index, status_attr, loading_attr, waiting, failed in [
          ('trips', 0, '_status', '_loading', 'Fetching drive statistics', 'Unable to fetch drive statistics'),
          ('firehose', 2, '_stats_status', '_stats_loading', 'Fetching training statistics', 'Unable to fetch training statistics'),
        ]:
          panel = make_panel(key)
          gui_app.push_widget(panel)
          row = panel._list._scroller.items[index]
          for phase, status in [('waiting', waiting), ('failed', failed)]:
            setattr(panel.controller, status_attr, status)
            setattr(panel.controller, loading_attr, phase == 'waiting')
            panel.controller._refresh_event.clear()
            capture(panel, None)
            panel._list.focus_item(row)
            capture(panel, f'{key}_statistics_{phase}_card_{language}')
            icon = row._info.rect
            pos = MousePos(icon.x + icon.width / 2, icon.y + icon.height / 2)
            gui_app._mouse_events = [MouseEvent(pos, 0, True, False, True, 0), MouseEvent(pos, 0, False, True, False, .1)]
            capture(panel, None)
            gui_app._mouse_events = []
            detail = gui_app.get_active_widget()
            assert isinstance(detail, CompactInfoPage)
            capture(detail, f'{key}_statistics_{phase}_detail_{language}')
            assert not panel.controller._refresh_event.is_set()
            gui_app.pop_widget()
          gui_app.pop_widget()
    finally:
      while len(gui_app._nav_stack) > 1:
        gui_app.pop_widget()
      gui_app.close()
      multilang._language = previous_language
      multilang.setup()


def capture_numeric_units(output_dir):
  """Render actual numeric controls in Chinese/metric and English/imperial."""
  from cereal import car, custom
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import make_panel
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.models import ModelsLayout
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.steering import PanelType
  from openpilot.system.ui.widgets.compact import CompactPage

  output_dir.mkdir(parents=True, exist_ok=True)
  previous_language = multilang.language
  with OpenpilotPrefix(), pytest.MonkeyPatch.context() as patches:
    patches.setattr(ui_state, 'params', Params())
    patches.setattr(ui_state, 'started', False)
    patches.setattr(ui_state, 'force_onroad', False)
    patches.setattr(ui_state, 'is_metric', True)
    patches.setattr(ui_state, 'CP', car.CarParams.new_message(pcmCruise=False))
    patches.setattr(ui_state, 'CP_SP', custom.CarParamsSP.new_message())
    patches.setattr(ui_state, 'has_longitudinal_control', True)
    patches.setattr(ModelsLayout, '_refresh_cache_size', lambda self: None)
    for key in ('ShowAdvancedControls', 'BlinkerPauseLateralControl', 'LaneTurnDesire', 'EnforceTorqueControl',
                'CustomTorqueParams', 'CustomAccIncrementsEnabled', 'dp_htd_enabled'):
      ui_state.params.put_bool(key, True, block=True)
    multilang._language = 'zh-CHS'
    multilang.setup()
    gui_app.init_window('C4 numeric units')
    gui_app._nav_stack.clear()
    gui_app.push_widget(CompactPage('root'))

    def capture(widget, name):
      for _ in range(4):
        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        widget.render(rl.Rectangle(0, 0, 536, 240))
        rl.end_drawing()
      target = output_dir / f'{name}.png'
      rl.take_screenshot(os.path.relpath(target.resolve()))
      if not target.exists():
        raise RuntimeError(f'Could not capture {target}')

    scenarios = [
      ('blinker_speed', 'steering', '_blinker_control_options', 'BlinkerMinLateralControlSpeed', 25, None),
      ('blinker_delay', 'steering', '_blinker_reengage_delay', 'BlinkerLateralReengageDelay', 3, None),
      ('lane_offset', 'steering', '_lat_position_offset', 'LateralPositionOffset', -3, None),
      ('software_delay', 'models', 'delay_control', 'LagdToggleDelay', .2, None),
      ('torque_factor', 'steering', '_torque_lat_accel_factor', 'TorqueParamsOverrideLatAccelFactor', .25, PanelType.TORQUE_CONTROL),
      ('torque_friction', 'steering', '_torque_friction', 'TorqueParamsOverrideFriction', .1, PanelType.TORQUE_CONTROL),
      ('htd_angle', 'cruise', 'htd_angle_threshold', 'dp_htd_turn_angle_threshold', 60, None),
      ('acc_short', 'cruise', 'custom_acc_short_increment', 'CustomAccShortPressIncrement', 3, None),
      ('acc_long', 'cruise', 'custom_acc_long_increment', 'CustomAccLongPressIncrement', 5, None),
      ('limit_offset', 'cruise', '_speed_limit_value_offset', 'SpeedLimitValueOffset', -3, 'SLA'),
    ]
    try:
      for language, metric in [('zh-CHS', True), ('en', False)]:
        multilang._language = language
        multilang.setup()
        gui_app.on_language_changed(language)
        ui_state.is_metric = metric
        for name, key, attr, param, value, child in scenarios:
          ui_state.params.put(param, value, block=True)
          ui_state.params.put('SpeedLimitOffsetType', 1, block=True)
          panel = make_panel(key)
          gui_app.push_widget(panel)
          if child is not None:
            panel.controller._current_panel = type(panel.controller._current_panel).SLA if child == 'SLA' else child
            panel.refresh()
          item = getattr(panel._active, attr)
          panel._rows[item][0].callback()
          detail = gui_app.get_active_widget()
          assert detail is not panel
          saved = ui_state.params.get(param)
          capture(detail, f'numeric_{name}_{language}')
          if name == 'limit_offset':
            ui_state.params.put('SpeedLimitOffsetType', 2, block=True)
            capture(detail, f'numeric_limit_percent_{language}')
          assert ui_state.params.get(param) == saved
          gui_app.pop_widget()
          gui_app.pop_widget()
    finally:
      while len(gui_app._nav_stack) > 1:
        gui_app.pop_widget()
      gui_app.close()
      multilang._language = previous_language
      multilang.setup()


def capture_operation_confirmations(output_dir):
  """Capture shared maintenance controls without accepting their operations."""
  from openpilot.selfdrive.ui.sunnypilot.mici.layouts.settings import make_panel
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.models import ModelsLayout
  from openpilot.system.ui.widgets.compact import CompactPage

  output_dir.mkdir(parents=True, exist_ok=True)
  previous_language = multilang.language
  with OpenpilotPrefix(), pytest.MonkeyPatch.context() as patches:
    patches.setattr(ui_state, 'params', Params())
    patches.setattr(ui_state, 'started', False)
    patches.setattr(ui_state, 'force_onroad', False)
    patches.setattr(ModelsLayout, '_refresh_cache_size', lambda self: None)
    ui_state.params.put_bool('ShowAdvancedControls', True, block=True)
    multilang._language = 'zh-CHS'
    multilang.setup()
    gui_app.init_window('C4 maintenance confirmations')
    gui_app._nav_stack.clear()
    gui_app.push_widget(CompactPage('root'))

    def capture(widget, name):
      for _ in range(4):
        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        widget.render(rl.Rectangle(0, 0, 536, 240))
        rl.end_drawing()
      if name is not None:
        target = output_dir / f'{name}.png'
        rl.take_screenshot(os.path.relpath(target.resolve()))
        if not target.exists():
          raise RuntimeError(f'Could not capture {target}')

    try:
      panel = make_panel('software')
      gui_app.push_widget(panel)
      item = panel.controller._uninstall_btn
      for language in ('zh-CHS', 'en'):
        multilang._language = language
        multilang.setup()
        gui_app.on_language_changed(language)
        capture(panel, None)
        panel._list.focus_item(panel._rows[item][0])
        panel._rows[item][0].callback()
        dialog = gui_app.get_active_widget()
        assert isinstance(dialog, ConfirmDialog)
        capture(dialog, f'software_uninstall_confirmation_{language}')
        dialog._cancel_button_callback()
        ui_state.started = True
        capture(panel, f'software_uninstall_unavailable_{language}')
        panel._rows[item][0].help_callback()
        capture(gui_app.get_active_widget(), f'software_uninstall_help_{language}')
        gui_app.pop_widget()
        ui_state.started = False
        ModelsLayout._show_reset_params_dialog()
        dialog = gui_app.get_active_widget()
        assert isinstance(dialog, ConfirmDialog)
        capture(dialog, f'model_calibration_confirmation_{language}')
        dialog._cancel_button_callback()
      assert not any(ui_state.params.get_bool(key) for key in ('DoReboot', 'DoUninstall'))
    finally:
      while len(gui_app._nav_stack) > 1:
        gui_app.pop_widget()
      gui_app.close()
      multilang._language = previous_language
      multilang.setup()


def capture_native_device_confirmations(output_dir):
  """Open actual device buttons without accepting any operation."""
  from openpilot.selfdrive.ui.mici.layouts.settings.device import DeviceLayoutMici
  from openpilot.system.ui.widgets.compact import CompactPage

  output_dir.mkdir(parents=True, exist_ok=True)
  previous_language = multilang.language
  with OpenpilotPrefix(), pytest.MonkeyPatch.context() as patches:
    engaged = [False]
    patches.setattr(ui_state, 'params', Params())
    patches.setattr(ui_state, 'started', False)
    patches.setattr(ui_state, '_offroad_transition_callbacks', [])
    patches.setattr(type(ui_state), 'engaged', property(lambda self: engaged[0]))
    multilang._language = 'zh-CHS'
    multilang.setup()
    gui_app.init_window('C4 device confirmation captures')
    gui_app._nav_stack.clear()
    gui_app.push_widget(CompactPage('root'))
    try:
      panel = DeviceLayoutMici()
      gui_app.push_widget(panel)
      for language in ('zh-CHS', 'en'):
        multilang._language = language
        multilang.setup()
        gui_app.on_language_changed(language)
        for is_engaged in (False, True):
          engaged[0] = is_engaged
          for name, index in [('reset', -4), ('uninstall', -3), ('reboot', -2), ('power_off', -1)]:
            panel._scroller.items[index]._click_callback()
            dialog = gui_app.get_active_widget()
            for _ in range(40):
              rl.begin_drawing()
              rl.clear_background(rl.BLACK)
              dialog.render(rl.Rectangle(0, 0, 536, 240))
              rl.end_drawing()
            target = output_dir / f'native_device_{name}_{"engaged" if is_engaged else "confirmation"}_{language}.png'
            rl.take_screenshot(os.path.relpath(target.resolve()))
            if not target.exists():
              raise RuntimeError(f'Could not capture {target}')
            gui_app.pop_widget()
      assert not any(ui_state.params.get_bool(key) for key in ('DoReboot', 'DoShutdown', 'DoUninstall', 'OnroadCycleRequested'))
    finally:
      while len(gui_app._nav_stack) > 1:
        gui_app.pop_widget()
      gui_app.close()
      multilang._language = previous_language
      multilang.setup()


def capture_native_language_settings(output_dir):
  """Switch language through the actual native picker and capture cached pages."""
  from openpilot.selfdrive.ui.mici.layouts.settings.settings import SettingsLayout
  from openpilot.selfdrive.ui.mici.layouts.settings.firehose import FirehoseLayoutBase
  from openpilot.system.ui.lib.wifi_manager import WifiManager
  from openpilot.system.ui.widgets.compact import CompactPage

  output_dir.mkdir(parents=True, exist_ok=True)
  previous_language = multilang.language
  with OpenpilotPrefix(), pytest.MonkeyPatch.context() as patches:
    patches.setattr(ui_state, 'params', Params())
    patches.setattr(ui_state, 'started', False)
    patches.setattr(ui_state, '_offroad_transition_callbacks', [])
    patches.setattr(ui_state, '_engaged_transition_callbacks', [])
    patches.setattr(multilang, '_params', ui_state.params)
    patches.setattr(WifiManager, '_initialize', lambda self: None)
    patches.setattr(WifiManager, 'set_active', lambda *args: None)
    patches.setattr(WifiManager, 'set_ipv4_forward', lambda *args: None)
    patches.setattr(FirehoseLayoutBase, '_update_loop', lambda self: None)
    multilang._language = 'en'
    multilang.setup()
    gui_app.init_window('C4 native language switch')
    gui_app._nav_stack.clear()
    gui_app.push_widget(CompactPage('root'))

    def capture(widget, name, item_index=0):
      widget._scroller.set_reset_scroll_at_show(False)
      offset = -sum(item.rect.width + widget._scroller._spacing
                    for item in widget._scroller.items[:item_index] if item.is_visible)
      widget._scroller.scroll_panel.set_offset(offset)
      for _ in range(40):
        rl.begin_drawing()
        rl.clear_background(rl.BLACK)
        widget.render(rl.Rectangle(0, 0, 536, 240))
        rl.end_drawing()
      target = output_dir / f'native_language_{name}.png'
      rl.take_screenshot(os.path.relpath(target.resolve()))
      if not target.exists():
        raise RuntimeError(f'Could not capture {target}')

    try:
      settings = SettingsLayout()
      gui_app.push_widget(settings)
      settings._scroller.items[2]._click_callback()
      device_panel = gui_app.get_active_widget()
      for language, choice in [('zh-CHS', 1), ('en', 0)]:
        device_panel._show_language_dialog()
        gui_app.get_active_widget()._scroller.items[choice]._click_callback()
        assert gui_app.get_active_widget() is device_panel
        capture(device_panel, f'device_{language}', 6)
        gui_app.pop_widget()
        capture(settings, f'root_{language}')
        for index, name, item_index in [(0, 'toggles', 2), (1, 'network', 2), (5, 'developer', 2)]:
          settings._scroller.items[index]._click_callback()
          capture(gui_app.get_active_widget(), f'{name}_{language}', item_index)
          gui_app.pop_widget()
        settings._scroller.items[2]._click_callback()
        assert gui_app.get_active_widget() is device_panel
    finally:
      while len(gui_app._nav_stack) > 1:
        gui_app.pop_widget()
      gui_app.close()
      multilang._language = previous_language
      multilang.setup()


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--output', type=Path)
  parser.add_argument('--native', action='store_true', help='Capture the original C4 card layout for comparison')
  parser.add_argument('--native-confirmations', action='store_true', help='Capture device confirmations without accepting operations')
  parser.add_argument('--native-language', action='store_true', help='Capture cached native settings after switching language')
  parser.add_argument('--operation-confirmations', action='store_true', help='Capture shared maintenance confirmations without accepting operations')
  parser.add_argument('--numeric-units', action='store_true', help='Capture numeric settings with Chinese/metric and English/imperial units')
  parser.add_argument('--status-details', action='store_true', help='Capture complete status details and long header titles')
  parser.add_argument('--action-information', action='store_true', help='Capture version information and release notes through the actual info button')
  parser.add_argument('--model-request', action='store_true', help='Capture model request waiting, timeout and cancellation')
  parser.add_argument('--selector-changes', action='store_true', help='Capture model and branch changes while their selector is open')
  args = parser.parse_args()
  if args.selector_changes:
    capture_selector_changes(args.output or Path('docs/c4-settings/runtime'))
  elif args.model_request:
    capture_model_request_status(args.output or Path('docs/c4-settings/runtime'))
  elif args.action_information:
    capture_action_information(args.output or Path('docs/c4-settings/runtime'))
  elif args.status_details:
    capture_status_details(args.output or Path('docs/c4-settings/runtime'))
  elif args.numeric_units:
    capture_numeric_units(args.output or Path('docs/c4-settings/runtime'))
  elif args.operation_confirmations:
    capture_operation_confirmations(args.output or Path('docs/c4-settings/runtime'))
  elif args.native_language:
    capture_native_language_settings(args.output or Path('docs/c4-settings/runtime'))
  elif args.native_confirmations:
    capture_native_device_confirmations(args.output or Path('docs/c4-settings/runtime'))
  else:
    capture_c4_settings(args.output or Path('docs/c4-settings/native' if args.native else 'docs/c4-settings/runtime'), args.native)
