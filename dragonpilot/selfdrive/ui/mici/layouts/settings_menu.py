"""Routes for the DP features actually supported by the mici display."""
from dataclasses import dataclass, field
from dragonpilot.settings import SETTINGS
from openpilot.system.ui.lib.multilang import tr_noop


@dataclass(frozen=True)
class SettingRef:
  source: str
  key: str
  row: int = 0

  @property
  def id(self):
    return f'{self.source}:{self.key}:{self.row}'


@dataclass
class MenuNode:
  key: str
  title: str
  children: list = field(default_factory=list)
  items: list = field(default_factory=list)


def named_row(name, row):
  row._c4_setting_id = name
  return row


def leaf(key, title, source, *keys):
  return MenuNode(key, title, items=[SettingRef(source, k) for k in keys])


ROOT = MenuNode('root', tr_noop('Settings'), children=[
  MenuNode('toggles', tr_noop('Basic Toggles'), children=[
    leaf('basic', tr_noop('Everyday Driving'), 'toggles', 'OpenpilotEnabledToggle', 'ExperimentalMode',
         'DisengageOnAccelerator', 'LongitudinalPersonality', 'IsLdwEnabled', 'IsMetric'),
    leaf('monitoring', tr_noop('Driver Monitoring'), 'toggles', 'AlwaysOnDM', 'DisableDriverMonitoringCamera', 'RecordFront', 'RecordAudio'),
  ]),
  MenuNode('steering', tr_noop('Steering'), children=[MenuNode('lateral', tr_noop('Steering Basics')), MenuNode('lane', tr_noop('Lane Change & Blinkers'))]),
  MenuNode('cruise', tr_noop('Cruise'), children=[MenuNode('longitudinal', tr_noop('Cruise Modes')), MenuNode('radar', tr_noop('Radar'))]),
  leaf('vehicle', tr_noop('Vehicle'), 'device', 'vehicle', 'fingerprint'),
  MenuNode('device', tr_noop('Device'), children=[
    leaf('use', tr_noop('Language & Use'), 'device', 'language'),
    leaf('calibration', tr_noop('Calibration & Device'), 'device', 'calibration', 'driver_camera',
         'dongle', 'serial', 'pair', 'training', 'regulatory', 'terms'),
    MenuNode('power', tr_noop('Power & Privacy'), items=[SettingRef('device', 'power'), SettingRef('device', 'power', 1), SettingRef('device', 'on_off_road')]),
  ]),
  MenuNode('network', tr_noop('Network'), children=[
    leaf('wifi', tr_noop('Wireless Networks'), 'network', 'wifi', 'scan', 'usage', 'hidden'),
    leaf('hotspot', tr_noop('Hotspot Sharing'), 'network', 'tethering', 'password'),
    leaf('cellular', tr_noop('Cellular Network'), 'network', 'roaming', 'apn', 'metered'),
  ]),
  leaf('software', tr_noop('Software'), 'software', 'onroad', 'version', 'download', 'install', 'branch', 'uninstall'),
  MenuNode('visuals', tr_noop('Visuals')),
  MenuNode('services', tr_noop('Data & Services'), children=[
    MenuNode('remote_services', tr_noop('Remote Services')),
    leaf('logging', tr_noop('Logging & Privacy'), 'toggles', 'DisableLogging'),
    leaf('reset', tr_noop('Reset DP Settings'), 'dp', 'btn_reset_dp_conf'),
  ]),
  MenuNode('firehose', tr_noop('Firehose'), children=[
    leaf('firehose_stats', tr_noop('Operation & Statistics'), 'firehose', 'status', 'contributions'),
    leaf('firehose_help', tr_noop('Help & Questions'), 'firehose', 'description', 'instructions', 'faq.driving', 'faq.uploads', 'faq.usb', 'faq.software'),
  ]),
  MenuNode('developer', tr_noop('Developer'), children=[
    leaf('remote', tr_noop('ADB / SSH'), 'developer', 'adb', 'ssh', 'keys'),
    leaf('debug', tr_noop('Debugging & Controls'), 'developer', 'joystick', 'longitudinal', 'lateral', 'alpha', 'debug', 'errors'),
  ]),
])
NODES, PATHS, ROUTES = {}, {}, {}


def index(node, path=()):
  NODES[node.key] = node
  PATHS[node.key] = (*path, node.key)
  for child in node.children:
    index(child, PATHS[node.key])


index(ROOT)
NODES['software'].items.append(SettingRef('toggles', 'DisableUpdates'))
SUPPORTED_TYPES = {'toggle_item', 'spin_button_item', 'double_spin_button_item', 'text_spin_button_item'}


def supports_mici(setting):
  if setting['type'] not in SUPPORTED_TYPES:
    return False
  expression = setting.get('condition')
  if not expression:
    return True
  for brand in ('', 'toyota', 'honda', 'hyundai', 'volkswagen', 'mazda', 'subaru', 'ford', 'nissan'):
    try:
      if eval(expression, {'__builtins__': {}}, dict(LITE=False, MICI=True, DASHY=False, IS_RELEASE=False,
                                                   brand=brand, openpilotLongitudinalControl=True)):
        return True
    except (NameError, SyntaxError, TypeError):
      continue
  return False


def dp_route(section, key):
  if section in ('Toyota / Lexus', 'Honda', 'HKG', 'VAG', 'Mazda'):
    return 'vehicle'
  if section == 'Lateral':
    return 'lane' if key.startswith('dp_lat_lca') or 'road_edge' in key else 'lateral'
  if section == 'Longitudinal' or key.startswith('dp_lon_'):
    return 'radar' if 'radar' in key else 'longitudinal'
  if section == 'UI':
    return 'visuals'
  if section == 'Device':
    if key in ('dp_dev_dashy', 'dp_dev_opview'):
      return 'remote_services'
    if key in ('dp_dev_disable_connect', 'dp_dev_delay_loggerd'):
      return 'logging'
    return 'power' if 'shutdown' in key else 'use'
  return 'debug'


for section in SETTINGS:
  for setting in section['settings']:
    if supports_mici(setting):
      NODES[dp_route(section['title'], setting['key'])].items.append(SettingRef('dp', setting['key']))
for node in NODES.values():
  for ref in node.items:
    if ref.id in ROUTES:
      raise ValueError(f'Duplicate C4 route: {ref.id}')
    ROUTES[ref.id] = node.key
