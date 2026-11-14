"""Native device operations and compact views of non-list settings."""
import os
from openpilot.common.time_helpers import system_time_valid
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.compact import CompactPage, CompactRow, CompactActionRow, CompactInfoPage, CompactSwipeList
from openpilot.system.ui.widgets.list_view import button_item, text_item
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.device import DeviceLayoutSP
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.trips import TripsLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.vehicle import VehicleLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.sunnylink import SunnylinkLayout
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.cruise import CruiseLayout
from openpilot.selfdrive.ui.mici.layouts.settings.device import MiciFccModal, ReviewTrainingGuide, ReviewTermsPage
from openpilot.selfdrive.ui.mici.onroad.driver_camera_dialog import DriverCameraDialog
from openpilot.selfdrive.ui.mici.widgets.pairing_dialog import PairingDialog
from openpilot.common.basedir import BASEDIR
from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog


class DeviceController(DeviceLayoutSP):
  def __init__(self):
    super().__init__()
    self._pair_device_btn.callback = self._open_pairing
    self._driver_cam_btn.callback = self._open_driver_camera
    self._scroller.add_widget(button_item(lambda: tr("Terms & Conditions"), lambda: tr("VIEW"),
                                         callback=lambda: gui_app.push_widget(ReviewTermsPage())))

  @staticmethod
  def _open_pairing():
    if ui_state.prime_state.is_paired():
      return
    if not system_time_valid():
      gui_app.push_widget(alert_dialog(tr("Please connect to Wi-Fi to complete initial pairing.")))
    elif ui_state.params.get("DongleId") in (None, "", UNREGISTERED_DONGLE_ID):
      gui_app.push_widget(alert_dialog(tr("Device must be registered with the comma.ai backend to pair.")))
    else:
      gui_app.push_widget(PairingDialog())

  @staticmethod
  def _open_driver_camera():
    if ui_state.is_offroad() and not os.getenv("DISABLE_DRIVER"):
      gui_app.push_widget(DriverCameraDialog())

  def _on_regulatory(self):
    if not ui_state.is_offroad():
      return
    if self._fcc_dialog is None:
      self._fcc_dialog = MiciFccModal(file_path=f"{BASEDIR}/selfdrive/assets/offroad/mici_fcc.html")
    gui_app.push_widget(self._fcc_dialog)

  def _on_review_training_guide(self):
    if not ui_state.is_offroad():
      return
    panel = gui_app.get_active_widget()
    gui_app.push_widget(ReviewTrainingGuide(completed_callback=lambda: gui_app.pop_widgets_to(panel)))


class VehicleController(VehicleLayout):
  PARAMETER_KEYS = {
    'hyundai': {'longitudinal_tuning_item': 'HyundaiLongitudinalTuning'},
    'subaru': {'stop_and_go_toggle': 'SubaruStopAndGo', 'stop_and_go_manual_parking_brake_toggle': 'SubaruStopAndGoManualParkingBrake'},
    'tesla': {'coop_steering_toggle': 'TeslaCoopSteering'},
    'toyota': {'enforce_stock_longitudinal': 'ToyotaEnforceStockLongitudinal', 'stop_and_go_hack': 'ToyotaStopAndGoHack',
               'auto_lock': 'ToyotaDoorAutoLockUnlock'},
  }

  def __init__(self):
    super().__init__()
    self._vehicle_item._c4_param_key = 'CarPlatformBundle'
    self._legend_item = text_item(lambda: tr("Vehicle fingerprint status"), self._status)

  @staticmethod
  def _status():
    if (bundle := ui_state.params.get("CarPlatformBundle")) is not None:
      name = bundle.get("name") if isinstance(bundle, dict) else None
      return tr("Manually selected fingerprint") if isinstance(name, str) and name else tr("Invalid manual vehicle selection")
    if ui_state.CP is not None and ui_state.CP.carFingerprint != "MOCK":
      return tr("Fingerprinted automatically")
    return tr("Not fingerprinted or manually selected")

  def _update_state(self):
    super()._update_state()
    for attribute, key in self.PARAMETER_KEYS.get(self._current_brand, {}).items():
      getattr(self._brand_settings, attribute)._c4_param_key = key
    self._scroller._items = [item for item in self._scroller._items if item is not self._legend_widget]
    if self._legend_item not in self._scroller._items:
      self._scroller._items.insert(1, self._legend_item)


class CruiseController(CruiseLayout):
  def _update_state(self):
    super()._update_state()
    if ui_state.CP is None or ui_state.CP_SP is None:
      for item in (self.custom_acc_toggle, self.dec_toggle, self.accel_profile_selector,
                   self.apm_toggle, self.scc_v_toggle, self.scc_m_toggle, self.htd_toggle, self.htd_angle_threshold,
                   self.custom_acc_short_increment, self.custom_acc_long_increment):
        item.action_item.set_enabled(False)


class SunnylinkController(SunnylinkLayout):
  def _initialize_items(self):
    from openpilot.system.ui.widgets.list_view import ListItem
    items = super()._initialize_items()
    self._sunnylink_toggle.action_item.toggle.param_key = None
    from openpilot.system.ui.sunnypilot.widgets.progress_bar import progress_item
    self._transfer_item = progress_item(lambda: tr("Backup & Restore Status"))
    self._transfer_item.set_description(self._transfer_detail)
    self._intro_item = button_item(lambda: tr('About sunnylink'), lambda: tr('VIEW'), callback=self._show_intro)
    return [self._intro_item, text_item(lambda: tr("Dongle ID"), self._get_sunnylink_dongle_id),
            self._transfer_item] + [item for item in items if isinstance(item, ListItem)]

  @staticmethod
  def _show_intro():
    gui_app.push_widget(CompactInfoPage(lambda: tr('About sunnylink'), lambda:
      tr('For secure backup, restore, and remote configuration') + '\n\n' +
      tr("Sponsorship isn't required for basic backup/restore") + '\n' + tr('Click the Sponsor button for more details')))

  def handle_backup_restore_progress(self):
    super().handle_backup_restore_progress()
    self._transfer_item.action_item.update(self._transfer_progress, self._transfer_status(),
                                            show_progress=self._transfer_seen_running or self._transfer_progress > 0)

  def _handle_pair_btn(self, sponsor_pairing=False):
    from openpilot.selfdrive.ui.sunnypilot.mici.widgets.sunnylink_pairing_dialog import SunnylinkPairingDialog
    from openpilot.sunnypilot.sunnylink.api import UNREGISTERED_SUNNYLINK_DONGLE_ID
    from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
    if ui_state.params.get("SunnylinkDongleId") in (None, UNREGISTERED_SUNNYLINK_DONGLE_ID):
      gui_app.push_widget(alert_dialog(tr("sunnylink Dongle ID not found. ") + tr("Please reboot and try again.")))
    else:
      gui_app.push_widget(SunnylinkPairingDialog(sponsor_pairing))

  def _sunnylink_toggle_callback(self, state):
    from openpilot.system.version import sunnylink_consent_version
    from openpilot.system.ui.widgets import DialogResult
    from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
    accepted = ui_state.params.get("CompletedSunnylinkConsentVersion") == sunnylink_consent_version
    if state and not accepted:
      self._sunnylink_toggle.action_item.set_state(False)

      def confirm(result):
        if result == DialogResult.CONFIRM and ui_state.is_offroad():
          ui_state.params.put("CompletedSunnylinkConsentVersion", sunnylink_consent_version, block=True)
          ui_state.params.put_bool("SunnylinkEnabled", True, block=True)
        self._sunnylink_toggle.action_item.set_state(ui_state.params.get_bool("SunnylinkEnabled"))

      gui_app.push_widget(ConfirmDialog(tr("sunnylink enables secured remote access to your comma device from anywhere, " +
                                          "including settings management, remote monitoring, real-time dashboard, etc.") + '\n\n' +
                                        tr("sunnylink is designed to be enabled as part of sunnypilot's core functionality. " +
                                           "If sunnylink is disabled, features such as settings management, remote monitoring, " +
                                           "real-time dashboards will be unavailable."),
                                        tr("Enable sunnylink"), callback=confirm))
    else:
      ui_state.params.put_bool("SunnylinkEnabled", state, block=True)

  def _backup_handler(self, result):
    if ui_state.is_offroad() and ui_state.params.get_bool("SunnylinkEnabled"):
      super()._backup_handler(result)

  def _restore_handler(self, result):
    if ui_state.is_offroad() and ui_state.params.get_bool("SunnylinkEnabled"):
      super()._restore_handler(result)


class TripsPanel(CompactPage):
  def __init__(self):
    super().__init__(lambda: tr("Trips"))
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self.controller = TripsLayout()
    self._list.set_items(self.setting_rows())

  def setting_rows(self):
    return [
      CompactActionRow(lambda: tr("Refresh Trip Statistics"), self.controller.status, self.controller.request_refresh,
                 help_callback=lambda: gui_app.push_widget(CompactInfoPage(lambda: tr("Refresh Trip Statistics"), self.controller.status)),
                 enabled=lambda: ui_state.is_offroad() and not self.controller._loading),
      *[
      CompactRow(lambda period=period, title=title: tr(period) + " · " + tr(title),
                 lambda key=key, field=field: self._value(key, field))
      for key, period in (("all", "ALL TIME"), ("week", "PAST WEEK"))
      for field, title in (("routes", "Drives"), ("distance", "Distance"), ("minutes", "Hours"))
      ],
    ]

  def _value(self, key, field):
    from openpilot.common.constants import CV
    data = self.controller._stats.get(key)
    if not data:
      return tr("N/A")
    value = data.get(field, 0)
    if field == "distance":
      return f"{int(value * CV.MPH_TO_KPH) if ui_state.is_metric else int(value)} " + (tr("KM") if ui_state.is_metric else tr("Miles"))
    if field == "minutes":
      return f"{value / 60:.1f} " + tr("Hours")
    return str(value)


class FirehosePanel(CompactPage):
  def __init__(self):
    super().__init__(lambda: tr("Firehose Mode"))
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    from openpilot.selfdrive.ui.mici.layouts.settings.firehose import FirehoseLayoutBase
    self.controller = FirehoseLayoutBase()
    self._list.set_items(self.setting_rows())

  def setting_rows(self):
    from openpilot.selfdrive.ui.mici.layouts.settings.firehose import DESCRIPTION, INSTRUCTIONS_INTRO, FAQ_ITEMS
    return [
      CompactRow(lambda: tr("Status"), lambda: self.controller._get_status()[0],
                 callback=lambda: gui_app.push_widget(CompactInfoPage(lambda: tr("Status"), lambda: self.controller._get_status()[0]))),
      CompactRow(lambda: tr("Training Data Contributions"),
                 lambda: str(self.controller._segment_count) if self.controller._stats_available else tr("N/A"),
                 callback=lambda: gui_app.push_widget(CompactInfoPage(lambda: tr("Training Data Contributions"), self.controller.contribution_text))),
      CompactActionRow(lambda: tr("Refresh Training Statistics"), self.controller.statistics_status, self.controller.request_refresh,
                 help_callback=lambda: gui_app.push_widget(CompactInfoPage(lambda: tr("Refresh Training Statistics"), self.controller.statistics_status)),
                 enabled=lambda: ui_state.is_offroad() and not self.controller._stats_loading),
      CompactRow(lambda: tr("Description"), callback=lambda: gui_app.push_widget(CompactInfoPage(lambda: tr("Firehose Mode"), lambda: tr(DESCRIPTION)))),
      CompactRow(lambda: tr("Instructions"), callback=lambda: gui_app.push_widget(CompactInfoPage(lambda: tr("Instructions"), lambda: tr(INSTRUCTIONS_INTRO)))),
      *[CompactRow(lambda q=q: tr(q),
                   callback=lambda q=q, a=a: gui_app.push_widget(CompactInfoPage(lambda: tr(q), lambda: tr(a)))) for q, a in FAQ_ITEMS],
    ]
