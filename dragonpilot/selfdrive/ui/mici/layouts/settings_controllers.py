"""Small-screen presentation of DP's existing controllers and callbacks."""
import os

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.layouts.settings.device import DeviceLayout
from openpilot.selfdrive.ui.layouts.settings.developer import DeveloperLayout
from openpilot.selfdrive.ui.layouts.settings.software import SoftwareLayout
from openpilot.selfdrive.ui.layouts.settings.toggles import TogglesLayout
from openpilot.selfdrive.ui.mici.layouts.settings.device import MiciFccModal, ReviewTermsPage, ReviewTrainingGuide
from openpilot.selfdrive.ui.mici.layouts.settings.firehose import FirehoseLayoutBase, DESCRIPTION, INSTRUCTIONS_INTRO, FAQ_ITEMS
from openpilot.selfdrive.ui.mici.onroad.driver_camera_dialog import DriverCameraDialog
from openpilot.selfdrive.ui.mici.widgets.pairing_dialog import PairingDialog
from openpilot.selfdrive.ui.mici.widgets.dialog import BigInputDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets.confirm_dialog import alert_dialog
from openpilot.system.ui.widgets.list_view import button_item, text_item
from openpilot.selfdrive.ui.widgets.ssh_key import SshKeyActionState
from dragonpilot.settings import SETTINGS
from dragonpilot.selfdrive.ui.layouts.settings.dragonpilot import DragonpilotLayout
from openpilot.system.ui.widgets.compact import CompactInfoPage, CompactRow


class DpController(DragonpilotLayout):
  _blocking_param_writes = True
  def _check_condition(self, expression):
    if not expression:
      return True
    context = dict(LITE=False, MICI=True, DASHY=False, IS_RELEASE=ui_state.is_release,
                   brand=self._brand, openpilotLongitudinalControl=self._openpilot_longitudinal_control)
    try:
      return bool(eval(expression, {'__builtins__': {}}, context))
    except (NameError, SyntaxError, TypeError):
      return False

  def refresh(self):
    self._refresh_visibility()
    self._update_toggles()
    for section in SETTINGS:
      for setting in section['settings']:
        item = self._toggles.get(setting['key'])
        if item is not None and setting.get('depends_on'):
          item.action_item.set_enabled(self._eval_depends_on(setting['depends_on']))


class TogglesController(TogglesLayout):
  def refresh(self):
    self._update_toggles()
    self._update_state()
    if ui_state.CP is None:
      for key in ('ExperimentalMode', 'LongitudinalPersonality'):
        self._toggles[key].action_item.set_enabled(False)


class DeviceController(DeviceLayout):
  def _initialize_items(self):
    items = super()._initialize_items()
    self._pair_device_btn.callback = self._pair
    for item in items:
      if item.title == tr('Driver Camera'):
        item.callback = self._driver_camera
    self._terms = button_item(lambda: tr('Terms & Conditions'), lambda: tr('VIEW'), callback=lambda: gui_app.push_widget(ReviewTermsPage()))
    self._fingerprint = text_item(lambda: tr('Vehicle fingerprint status'), self._fingerprint_status)
    return items + [self._terms, self._fingerprint]

  @staticmethod
  def _fingerprint_status():
    selected = ui_state.params.get('dp_dev_model_selected')
    if selected:
      return selected
    if ui_state.CP is not None:
      return ui_state.CP.carFingerprint
    return tr('[AUTO DETECT]')

  def _pair(self):
    from openpilot.common.time_helpers import system_time_valid
    from openpilot.system.athena.registration import UNREGISTERED_DONGLE_ID
    if ui_state.prime_state.is_paired():
      return
    if not system_time_valid():
      gui_app.push_widget(alert_dialog(tr('Please connect to Wi-Fi to complete initial pairing.')))
    elif ui_state.params.get('DongleId') in (None, '', UNREGISTERED_DONGLE_ID):
      gui_app.push_widget(alert_dialog(tr('Device must be registered with the comma.ai backend to pair.')))
    else:
      gui_app.push_widget(PairingDialog())

  @staticmethod
  def _driver_camera():
    if ui_state.is_offroad() and not os.getenv('DISABLE_DRIVER'):
      gui_app.push_widget(DriverCameraDialog())

  def _on_regulatory(self):
    if ui_state.is_offroad():
      gui_app.push_widget(MiciFccModal(file_path=f'{BASEDIR}/selfdrive/assets/offroad/mici_fcc.html'))

  def _on_review_training_guide(self):
    if ui_state.is_offroad():
      owner = gui_app.get_active_widget()
      gui_app.push_widget(ReviewTrainingGuide(completed_callback=lambda: gui_app.pop_widgets_to(owner)))

  def refresh(self):
    self._update_state()
    self._offroad_transition()


class DeveloperController(DeveloperLayout):
  def _on_show_last_errors(self):
    if not ui_state.params.get('dp_dev_last_log'):
      gui_app.push_widget(CompactInfoPage(lambda: tr('Show Last Errors'), lambda: tr('No active tasks')))
    else:
      super()._on_show_last_errors()

  def edit_ssh_keys(self):
    action = self._ssh_keys.action_item
    action._refresh_state()
    if action._state == SshKeyActionState.LOADING:
      return
    if action._state == SshKeyActionState.REMOVE:
      action._handle_button_click()
      return
    def submit(username):
      username = username.strip()
      if username:
        action._state = SshKeyActionState.LOADING
        action._fetcher.fetch(username, action._on_fetch_response)
    gui_app.push_widget(BigInputDialog(tr('Enter your GitHub username'), confirm_callback=submit))

  def refresh(self):
    self._update_toggles()
    self._ssh_keys.action_item._update_state()


class SoftwareController(SoftwareLayout):
  def refresh(self):
    self._update_state()


class FirehoseController(FirehoseLayoutBase):
  def rows(self):
    from dragonpilot.selfdrive.ui.mici.layouts.settings_menu import named_row
    rows = [
      ('status', lambda: tr('Status'), lambda: self._get_status()[0], lambda: self._get_status()[0]),
      ('contributions', lambda: tr('Training Data Contributions'), lambda: str(self._segment_count),
       lambda: tr('{} segments of your driving is in the training dataset so far.').format(self._segment_count)),
      ('description', lambda: tr('Description'), '', lambda: tr(DESCRIPTION)),
      ('instructions', lambda: tr('Instructions'), '', lambda: tr(INSTRUCTIONS_INTRO)),
    ]
    rows += [(key, lambda question=question: tr(question), '', lambda answer=answer: tr(answer))
             for key, (question, answer) in zip(('faq.driving', 'faq.uploads', 'faq.usb', 'faq.software'), FAQ_ITEMS, strict=True)]
    return [named_row(key, CompactRow(title, value,
            callback=lambda title=title, text=text: gui_app.push_widget(CompactInfoPage(title, text))))
            for key, title, value, text in rows]

  def refresh(self):
    pass


DEVICE_NAMES = dict(vehicle='Vehicle Model', on_off_road='On/Off Road', dongle='Dongle ID', serial='Serial',
                    pair='Pair Device', driver_camera='Driver Camera', calibration='Reset Calibration',
                    training='Review Training Guide', regulatory='Regulatory', language='Change Language',
                    terms='Terms & Conditions', fingerprint='Vehicle fingerprint status')
DEVELOPER_ATTRIBUTES = dict(adb='_adb_toggle', ssh='_ssh_toggle', keys='_ssh_keys', joystick='_joystick_toggle',
                            longitudinal='_long_maneuver_toggle', lateral='_lat_maneuver_toggle', alpha='_alpha_long_toggle', debug='_ui_debug_toggle')
SOFTWARE_ATTRIBUTES = dict(onroad='_onroad_label', version='_version_item', download='_download_btn', install='_install_btn', branch='_branch_btn')


def source_item(controller, ref):
  if ref.source in ('toggles', 'dp'):
    return controller._toggles.get(ref.key)
  if ref.source == 'device':
    if ref.key == 'power':
      return controller._power_off_btn
    return next((item for item in controller._scroller._items if item.title == tr(DEVICE_NAMES[ref.key])), None)
  if ref.source == 'developer':
    if ref.key == 'errors':
      return controller._scroller._items[-1]
    return getattr(controller, DEVELOPER_ATTRIBUTES[ref.key])
  if ref.source == 'software':
    if ref.key == 'uninstall':
      return controller._scroller._items[-1]
    return getattr(controller, SOFTWARE_ATTRIBUTES[ref.key])
  return None
