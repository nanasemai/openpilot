"""Compact network controls with the native connection and authentication callbacks."""
import pyray as rl
from openpilot.selfdrive.ui.mici.layouts.settings.network.network_layout import NetworkLayoutMici
from openpilot.selfdrive.ui.mici.layouts.settings.network.wifi_ui import WifiButton
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wifi_manager import MeteredType, normalize_ssid
from openpilot.system.ui.widgets.compact import CompactButton, CompactInfoPage, CompactPage, CompactRow, CompactSelectPage, CompactSwipeList, resolve
from openpilot.system.ui.widgets.label import gui_label


class NetworkTogglePage(CompactPage):
  def __init__(self, owner, button, title):
    super().__init__(title)
    self.owner, self.button = owner, button
    self._toggle = self._child(CompactButton(lambda: tr('Disable') if button._checked else tr('Enable'),
                                           lambda: owner._toggle(button, active_page=self), primary=True))
    self._toggle.set_enabled(lambda: self.enabled and button.enabled and button.is_visible)

  def _update_state(self):
    self.owner._update_state()

  def _render(self, rect):
    rl.draw_rectangle_rec(rect, rl.BLACK)
    self._header.render(rl.Rectangle(rect.x, rect.y, rect.width, 56))
    gui_label(rl.Rectangle(rect.x + 24, rect.y + 72, rect.width - 48, 40),
              tr('Current State: {state}').format(state=tr('On') if self.button._checked else tr('Off')), 36,
              alignment=rl.GuiTextAlignment.TEXT_ALIGN_CENTER)
    self._toggle.render(rl.Rectangle(rect.x + 24, rect.y + 124, rect.width - 48, 88))


class NetworkToggleRow(CompactRow):
  def __init__(self, title, button, owner, **kwargs):
    super().__init__(title, callback=lambda: gui_app.push_widget(NetworkTogglePage(owner, button, title)),
                     checked=lambda: button._checked, enabled=lambda: button.enabled and button.is_visible, **kwargs)

  def _handle_mouse_release(self, pos):
    if resolve(self.available):
      self.callback()
    elif self.help_callback:
      self.help_callback()


class WifiRow(CompactRow):
  def __init__(self, button):
    super().__init__(lambda: normalize_ssid(button.network.ssid), button.get_value,
                     callback=button._click_callback, enabled=lambda: button.enabled)
    self.button = button
    self._forget = CompactButton(lambda: tr("Forget"), self._forget_network)
    self._forget.set_touch_valid_callback(self._touch_valid)

  def _value_rect(self):
    rect = super()._value_rect()
    if self.button._show_forget_btn:
      rect.width -= 88
    return rect

  def _forget_rect(self):
    return rl.Rectangle(self.rect.x + self.rect.width - 112, self.rect.y + self.rect.height - 64, 104, 56)

  def _forget_network(self):
    if self.button._show_forget_btn:
      self.button._forget_btn._handle_mouse_release(None)

  def _render(self, rect):
    super()._render(rect)
    if self.button._show_forget_btn:
      self._forget.set_enabled(self.enabled)
      self._forget.render(self._forget_rect())

  def _handle_mouse_release(self, pos):
    if self.button._show_forget_btn and rl.check_collision_point_rec(pos, self._forget_rect()):
      return  # The visible button handles this touch and shares the scroller's swipe guard.
    if self.button.enabled:
      self.button._click_callback()


class WifiPanel(CompactPage):
  def __init__(self, native):
    super().__init__(lambda: tr("Wi-Fi Networks"))
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self.native = native
    self._rows = {}

  def show_event(self):
    self.native.show_event()

  def _update_state(self):
    rows = []
    for button in self.native._scroller.items:
      if not isinstance(button, WifiButton):
        continue
      button._update_state()
      if button not in self._rows:
        self._rows[button] = WifiRow(button)
      rows.append(self._rows[button])
    if not rows:
      rows = [CompactRow(lambda: tr("searching for networks"))]
    self._list.set_items(rows)


class NetworkPanel(CompactPage):
  def __init__(self):
    super().__init__(lambda: tr("Network"))
    self._list = CompactSwipeList()
    self._list.set_enabled(lambda: self.enabled)
    self.native = NetworkLayoutMici()
    self._wifi = WifiPanel(self.native._wifi_ui)
    def cellular_info(title):
      gui_app.push_widget(CompactInfoPage(title, lambda: tr('Unavailable with the current cellular subscription.')))
    self._list.set_items([
      CompactRow(lambda: tr("Wi-Fi Networks"), self.native._wifi_button.get_value, lambda: gui_app.push_widget(self._wifi)),
      CompactRow(lambda: tr("Scan"), callback=self.native._wifi_manager._request_scan),
      CompactRow(lambda: tr("network usage"), self._metered_label, self._select_metered,
                 enabled=lambda: self.native._network_metered_btn.enabled),
      NetworkToggleRow(lambda: tr("enable tethering"), self.native._tethering_toggle_btn, self),
      CompactRow(lambda: tr("tethering password"), callback=self.native._tethering_password_btn._click_callback,
                 enabled=lambda: self.native._tethering_password_btn.enabled),
      NetworkToggleRow(lambda: tr("enable roaming"), self.native._roaming_btn, self,
                        help_callback=lambda: cellular_info(lambda: tr('enable roaming'))),
      CompactRow(lambda: tr("apn settings"), lambda: ui_state.params.get("GsmApn") or tr("Automatic"), callback=self.native._apn_btn._click_callback,
                 enabled=lambda: self.native._apn_btn.enabled and self.native._apn_btn.is_visible,
                 help_callback=lambda: cellular_info(lambda: tr('apn settings'))),
      NetworkToggleRow(lambda: tr("cellular metered"), self.native._cellular_metered_btn, self,
                        help_callback=lambda: cellular_info(lambda: tr('cellular metered'))),
      CompactRow(lambda: tr("Hidden Network"), callback=self._connect_hidden),
    ])

  def _connect_hidden(self):
    from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog

    def enter_password(ssid):
      if not ssid:
        return
      gui_app.push_widget(BigInputDialog(lambda: tr('Enter password'), minimum_length=0,
                                         confirm_callback=lambda password: self.native._wifi_manager.connect_to_network(ssid, password, hidden=True)))

    if gui_app.get_active_widget() is self:
      gui_app.push_widget(BigInputDialog(lambda: tr('Enter SSID'), minimum_length=1, confirm_callback=enter_password))

  def show_event(self):
    self.native.show_event()

  def hide_event(self):
    self.native.hide_event()

  def _update_state(self):
    self.native.update_network_settings()
    self.native._wifi_button._update_state()
    self.native._roaming_btn.refresh()
    self.native._cellular_metered_btn.refresh()

  def _toggle(self, button, active_page=None):
    self._update_state()
    if button.enabled and button.is_visible and gui_app.get_active_widget() is (active_page or self):
      button._handle_mouse_release(None)

  def _metered_label(self):
    metered = self.native._wifi_manager.current_network_metered
    return tr("metered") if metered == MeteredType.YES else tr("unmetered") if metered == MeteredType.NO else tr("default")

  def _select_metered(self):
    self._update_state()
    if not self.native._network_metered_btn.enabled:
      return
    original_ssid = self.native._wifi_manager.wifi_state.ssid
    values = (MeteredType.UNKNOWN, MeteredType.YES, MeteredType.NO)
    options = [lambda: tr("default"), lambda: tr("metered"), lambda: tr("unmetered")]
    gui_app.push_widget(CompactSelectPage(lambda: tr("network usage"), options,
                                         lambda: values.index(self.native._wifi_manager.current_network_metered),
                                         lambda index: self.native._network_metered_btn._select_callback(
                                           self.native._network_metered_btn._options[index]),
                                         allowed=lambda _: self.native._network_metered_btn.enabled and
                                           self.native._wifi_manager.wifi_state.ssid == original_ssid,
                                         refresh=self._update_state))
