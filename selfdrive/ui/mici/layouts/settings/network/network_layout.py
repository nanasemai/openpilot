from openpilot.system.ui.widgets.scroller import NavScroller
from openpilot.selfdrive.ui.mici.layouts.settings.network import WifiNetworkButton
from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import WifiUIMici
from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigMultiToggle, BigParamControl, BigToggle
from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.lib.prime_state import PrimeType
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wifi_manager import WifiManager, Network, MeteredType
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog


class NetworkLayoutMici(NavScroller):
  def __init__(self):
    super().__init__()

    self._wifi_manager = WifiManager()
    self._wifi_manager.set_active(False)
    self._wifi_ui = WifiUIMici(self._wifi_manager)

    self._wifi_manager.add_callbacks(
      networks_updated=self._on_network_updated,
    )

    # ******** Tethering ********
    def tethering_toggle_callback(checked: bool):
      self._tethering_toggle_btn.set_enabled(False)
      self._tethering_password_btn.set_enabled(False)
      self._network_metered_btn.set_enabled(False)
      self._wifi_manager.set_tethering_active(checked)

    self._tethering_toggle_btn = BigToggle(lambda: tr("enable tethering"), "", toggle_callback=tethering_toggle_callback)

    def tethering_password_callback(password: str, previous: str):
      if previous != self._wifi_manager.tethering_password:
        gui_app.push_widget(alert_dialog(tr("Hotspot password changed. Reopen the editor and try again.")))
        return
      if password and self._tethering_password_btn.enabled:
        self._tethering_toggle_btn.set_enabled(False)
        self._tethering_password_btn.set_enabled(False)
        self._wifi_manager.set_tethering_password(password)

    def tethering_password_clicked():
      if not self._tethering_password_btn.enabled:
        return
      tethering_password = self._wifi_manager.tethering_password
      dlg = BigInputDialog(lambda: tr("enter password..."), tethering_password, minimum_length=8,
                           confirm_callback=lambda password: tethering_password_callback(password, tethering_password))
      gui_app.push_widget(dlg)

    txt_tethering = gui_app.texture("icons_mici/settings/network/tethering.png", 64, 54)
    self._tethering_password_btn = BigButton(lambda: tr("tethering password"), "", txt_tethering)
    self._tethering_password_btn.set_click_callback(tethering_password_clicked)

    # ******** Network Metered ********
    def network_metered_callback(value: str):
      self._network_metered_btn.set_enabled(False)
      index = self._network_metered_btn._options.index(value)
      metered = (MeteredType.UNKNOWN, MeteredType.YES, MeteredType.NO)[index]
      self._wifi_manager.set_current_network_metered(metered)

    # TODO: signal for current network metered type when changing networks, this is wrong until you press it once
    # TODO: disable when not connected
    self._network_metered_btn = BigMultiToggle(lambda: tr("network usage"),
                                              [lambda: tr("default"), lambda: tr("metered"), lambda: tr("unmetered")],
                                              select_callback=network_metered_callback)
    self._network_metered_btn.set_enabled(False)

    self._wifi_button = WifiNetworkButton(self._wifi_manager)
    self._wifi_button.set_click_callback(lambda: gui_app.push_widget(self._wifi_ui))
    self._scan_button = BigButton(lambda: tr("Scan"))
    self._scan_button.set_click_callback(self._wifi_manager._request_scan)

    # ******** Advanced settings ********
    # ******** Roaming toggle ********
    self._roaming_btn = BigParamControl(lambda: tr("enable roaming"), "GsmRoaming")

    # ******** APN settings ********
    self._apn_btn = BigButton(lambda: tr("apn settings"), lambda: tr("edit"))
    self._apn_btn.set_click_callback(self._edit_apn)

    # ******** Cellular metered toggle ********
    self._cellular_metered_btn = BigParamControl(lambda: tr("cellular metered"), "GsmMetered")

    # Main scroller ----------------------------------
    self._scroller.add_widgets([
      self._wifi_button,
      self._scan_button,
      self._network_metered_btn,
      self._tethering_toggle_btn,
      self._tethering_password_btn,
      # /* Advanced settings
      self._roaming_btn,
      self._apn_btn,
      self._cellular_metered_btn,
      # */
    ])

  def _update_state(self):
    super()._update_state()
    self.update_network_settings()

  def update_network_settings(self):
    # If not using prime SIM, show GSM settings and enable IPv4 forwarding
    show_cell_settings = self._cell_settings_available()
    self._wifi_manager.set_ipv4_forward(show_cell_settings)
    self._roaming_btn.set_visible(show_cell_settings)
    self._apn_btn.set_visible(show_cell_settings)
    self._cellular_metered_btn.set_visible(show_cell_settings)

  def show_event(self):
    super().show_event()
    self._wifi_manager.set_active(True)

    # Process wifi callbacks while at any point in the nav stack
    gui_app.add_nav_stack_tick(self._wifi_manager.process_callbacks)

  def hide_event(self):
    super().hide_event()
    self._wifi_manager.set_active(False)

    gui_app.remove_nav_stack_tick(self._wifi_manager.process_callbacks)

  def _edit_apn(self):
    if not self._cell_settings_available():
      return
    previous_apn = ui_state.params.get("GsmApn")
    def update_apn(apn: str):
      if not self._cell_settings_available():
        return
      if ui_state.params.get("GsmApn") != previous_apn:
        gui_app.push_widget(alert_dialog(tr("APN changed. Reopen the editor and try again.")))
        return
      apn = apn.strip()
      if apn == "":
        ui_state.params.remove("GsmApn")
      else:
        ui_state.params.put("GsmApn", apn, block=True)

    current_apn = previous_apn or ""
    dlg = BigInputDialog(lambda: tr("enter APN..."), current_apn, minimum_length=0, confirm_callback=update_apn)
    gui_app.push_widget(dlg)

  @staticmethod
  def _cell_settings_available():
    return ui_state.prime_state.get_type() in (PrimeType.NONE, PrimeType.LITE)

  def _on_network_updated(self, networks: list[Network]):
    # Update tethering state
    tethering_active = self._wifi_manager.is_tethering_active()
    # TODO: use real signals (like activated/settings changed, etc.) to speed up re-enabling buttons
    self._tethering_toggle_btn.set_enabled(True)
    self._tethering_password_btn.set_enabled(True)
    self._network_metered_btn.set_enabled(lambda: not tethering_active and bool(self._wifi_manager.ipv4_address))
    self._tethering_toggle_btn.set_checked(tethering_active)

    # Update network metered
    self._network_metered_btn.set_value(
      {
        MeteredType.UNKNOWN: tr('default'),
        MeteredType.YES: tr('metered'),
        MeteredType.NO: tr('unmetered')
      }.get(self._wifi_manager.current_network_metered, tr('default')))
