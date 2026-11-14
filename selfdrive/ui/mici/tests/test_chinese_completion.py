"""Check Chinese setup/recovery labels without installing, erasing or rebooting."""
import pytest
import pyray as rl
from openpilot.system.ui.lib.multilang import tr
from openpilot.selfdrive.ui.mici.tests.test_settings import state, window  # noqa: F401


class OfflineWifiView:
  def render(self, *_):
    pass


def isolate_wifi(module, monkeypatch):
  monkeypatch.setattr(module, 'WifiManager', lambda: None)
  monkeypatch.setattr(module, 'WifiManagerUI', lambda *_: OfflineWifiView())


@pytest.mark.parametrize('mode', [0, 1])
@pytest.mark.parametrize('state_value', [0, 1, 2, 3])
def test_reset_chinese_explanations_and_buttons(mode, state_value):
  from openpilot.system.ui.tici_reset import Reset, ResetMode, ResetState
  page = Reset(ResetMode(mode))
  page._reset_state = ResetState(state_value)
  text = page._get_body_text()
  assert any('\u4e00' <= char <= '\u9fff' for char in text)
  assert 'reset' not in text.casefold() and 'confirm' not in text.casefold()
  assert page._cancel_button._label._text == tr('Cancel')
  assert page._confirm_button._label._text == tr('Confirm')
  assert page._reboot_button._label._text == tr('Reboot')


def test_setup_static_chinese_labels_and_warning(monkeypatch):
  from openpilot.system.ui import tici_setup as module
  isolate_wifi(module, monkeypatch)
  page = module.Setup()
  assert page._low_voltage_title_label._text == '警告：电压过低'
  assert page._software_selection_custom_software_button._label._text == '自定义软件'
  assert page._getting_started_title_label._text == '开始设置'
  assert page._download_failed_title_label._text == '下载失败'
  assert '未经 comma 测试' in page._custom_software_warning_body_label._text
  assert 'https://flash.comma.ai' in page._custom_software_warning_body_label._text
  assert page._downloading_body_label._text == '正在下载…'


@pytest.mark.parametrize('connected,wifi,expected', [(False, False, '等待网络连接'), (True, False, '不连接 Wi-Fi，继续'), (True, True, '继续')])
def test_setup_network_status_remains_chinese(monkeypatch, connected, wifi, expected):
  from openpilot.system.ui import tici_setup as module
  isolate_wifi(module, monkeypatch)
  page = module.Setup()
  if connected:
    page.network_connected.set()
  if wifi:
    page.wifi_connected.set()
  rl.begin_drawing()
  page.render_network_setup(rl.Rectangle(0, 0, 2160, 1080))
  rl.end_drawing()
  assert page._network_setup_continue_button._label._text == expected


@pytest.mark.parametrize('message,expected', [('Loading...', None), ('Downloading...', '正在下载…'),
                                            ('Installing system', '正在安装 system'), ('Update failed', '更新失败')])
def test_updater_chinese_progress_retains_partition_identifier(monkeypatch, message, expected):
  from openpilot.system.ui import tici_updater as module
  isolate_wifi(module, monkeypatch)
  page = module.Updater('/not-run', '/not-run')
  page.progress_text = message
  assert page.translated_progress() == (tr(message) if expected is None else expected)
  assert page._install_button._label._text == '安装'
  assert page._wifi_button._label._text == '连接 Wi-Fi'


def test_device_information_version_fields_are_chinese(monkeypatch):
  from openpilot.selfdrive.ui.widgets.device_info import DeviceInfoWidget
  monkeypatch.setenv('GIT_BRANCH', 'sp-dev-c4')
  monkeypatch.setenv('GIT_COMMIT', '12345678abcdef')
  page = DeviceInfoWidget()
  lines = dict(page._get_info_lines())
  assert lines['· 分支'] == 'sp-dev-c4'
  assert lines['· 提交'] == '12345678'
  assert '· 本地修改' in lines
  rl.begin_drawing()
  page.render(rl.Rectangle(0, 0, 2160, 1080))
  rl.end_drawing()


def test_map_state_uses_geographic_translation():
  assert tr('State') == '州/省'
