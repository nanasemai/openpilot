"""Semantic routes to the complete shared C3X controls on the small C4 display."""
from dataclasses import dataclass

from openpilot.system.ui.lib.multilang import tr_noop
from openpilot.system.ui.widgets.compact import translation_source


@dataclass(frozen=True)
class SettingRef:
  category: str
  selector: str
  row: int = 0

  @property
  def key(self):
    aliases = {'network': {'n:roaming': 'GsmRoaming', 'n:apn': 'GsmApn', 'n:metered': 'GsmMetered'},
               'steering': {'a:_torque_control_layout._torque_control_versions': 'TorqueControlTune'}}
    if self.selector.startswith('p:'):
      return self.selector[2:]
    return aliases.get(self.category, {}).get(self.selector, f'c4:{self.category}:{self.selector}:{self.row}')

  def find_item(self, panel):
    kind, value = self.selector.split(':', 1)
    if kind == 'a':
      target = panel.controller
      for attribute in value.split('.'):
        target = getattr(target, attribute, None)
      return target if target in panel._source_items else None
    for item in panel._source_items:
      if kind == 't' and translation_source(item.title) == value:
        return item
      action = item.action_item
      toggle = getattr(action, 'toggle', None)
      key = getattr(item, '_c4_param_key', None) or getattr(toggle, 'param_key', None) or getattr(action, 'param_key', None)
      if kind == 'p' and key == value:
        return item
    return None


@dataclass(frozen=True)
class MenuNode:
  key: str
  title: str
  children: tuple = ()
  items: tuple = ()


def named_row(name, row):
  row._c4_setting_id = name
  return row


def folder(key, title, *children):
  return MenuNode(key, tr_noop(title), children=children)


def leaf(key, title, *items):
  return MenuNode(key, tr_noop(title), items=items)


MENU_TREE = folder('root', tr_noop('Settings'),
  folder('toggles', tr_noop('Toggles'),
    leaf('basic', tr_noop('Everyday Driving'),
      SettingRef('toggles', 'p:OpenpilotEnabledToggle'),
      SettingRef('toggles', 'p:ExperimentalMode'),
      SettingRef('toggles', 'p:DisengageOnAccelerator'),
      SettingRef('toggles', 'p:LongitudinalPersonality'),
      SettingRef('toggles', 'p:IsLdwEnabled'),
      SettingRef('toggles', 'p:IsMetric'),
    ),
    leaf('monitoring', tr_noop('Driver Monitoring'),
      SettingRef('toggles', 'p:AlwaysOnDM'),
      SettingRef('toggles', 'p:DisableDriverMonitoringCamera'),
      SettingRef('toggles', 'p:RecordFront'),
      SettingRef('toggles', 'p:RecordAudio'),
    ),
  ),
  folder('steering', tr_noop('Steering'),
    leaf('lateral', tr_noop('Steering Basics'),
      SettingRef('steering', 'p:NeuralNetworkLateralControl'),
      SettingRef('steering', 'p:LateralPositionOffset'),
    ),
    leaf('mads', tr_noop('MADS Engagement'),
      SettingRef('steering', 'p:Mads'),
      SettingRef('steering', 'p:MadsMainCruiseAllowed'),
      SettingRef('steering', 'p:MadsUnifiedEngagementMode'),
      SettingRef('steering', 'p:MadsSteeringMode'),
    ),
    leaf('lane', tr_noop('Lane Change & Blinkers'),
      SettingRef('steering', 'p:AutoLaneChangeTimer'),
      SettingRef('steering', 'p:AutoLaneChangeBsmDelay'),
      SettingRef('steering', 'p:RoadEdgeLcaBlindspot'),
      SettingRef('steering', 'p:BlinkerPauseLateralControl'),
      SettingRef('steering', 'p:BlinkerMinLateralControlSpeed'),
      SettingRef('steering', 'p:BlinkerLateralReengageDelay'),
    ),
    leaf('torque', tr_noop('Torque Tuning'),
      SettingRef('steering', 'p:EnforceTorqueControl'),
      SettingRef('steering', 'a:_torque_control_layout._torque_control_versions'),
      SettingRef('steering', 'p:LiveTorqueParamsToggle'),
      SettingRef('steering', 'p:LiveTorqueParamsRelaxedToggle'),
      SettingRef('steering', 'p:CustomTorqueParams'),
      SettingRef('steering', 'p:TorqueParamsOverrideEnabled'),
      SettingRef('steering', 'p:TorqueParamsOverrideLatAccelFactor'),
      SettingRef('steering', 'p:TorqueParamsOverrideFriction'),
    ),
  ),
  folder('cruise', tr_noop('Cruise'),
    leaf('cruise_mode', tr_noop('Cruise Modes'),
      SettingRef('cruise', 'p:IntelligentCruiseButtonManagement'),
      SettingRef('cruise', 'p:DynamicExperimentalControl'),
    ),
    leaf('corners', tr_noop('Curve Control'),
      SettingRef('cruise', 'p:SmartCruiseControlVision'),
      SettingRef('cruise', 'p:SmartCruiseControlMap'),
      SettingRef('cruise', 'p:dp_htd_enabled'),
      SettingRef('cruise', 'p:dp_htd_turn_angle_threshold'),
    ),
    leaf('acceleration', tr_noop('Speed & Acceleration'),
      SettingRef('cruise', 'p:CustomAccIncrementsEnabled'),
      SettingRef('cruise', 'p:CustomAccShortPressIncrement'),
      SettingRef('cruise', 'p:CustomAccLongPressIncrement'),
      SettingRef('cruise', 'p:SPAccelProfile'),
      SettingRef('cruise', 'p:SPAccelProfileModeEnabled'),
    ),
    leaf('speed_limit', tr_noop('Speed Limit Settings'),
      SettingRef('cruise', 'p:SpeedLimitMode'),
      SettingRef('cruise', 'p:SpeedLimitOffsetType'),
      SettingRef('cruise', 'p:SpeedLimitValueOffset'),
      SettingRef('cruise', 'p:SpeedLimitPolicy'),
    ),
  ),
  leaf('vehicle', tr_noop('Vehicle'),
    SettingRef('vehicle', 'p:CarPlatformBundle'),
    SettingRef('vehicle', 'a:_legend_item'),
    SettingRef('vehicle', 'p:HyundaiLongitudinalTuning'),
    SettingRef('vehicle', 'p:SubaruStopAndGo'),
    SettingRef('vehicle', 'p:SubaruStopAndGoManualParkingBrake'),
    SettingRef('vehicle', 'p:TeslaCoopSteering'),
    SettingRef('vehicle', 'p:ToyotaEnforceStockLongitudinal'),
    SettingRef('vehicle', 'p:ToyotaStopAndGoHack'),
    SettingRef('vehicle', 'p:ToyotaDoorAutoLockUnlock'),
  ),
  folder('models', tr_noop('Models'),
    leaf('model_choice', tr_noop('Model Selection'),
      SettingRef('models', 'a:current_model_item'),
      SettingRef('models', 'a:refresh_item'),
      SettingRef('models', 'a:clear_cache_item'),
    ),
    leaf('downloads', tr_noop('Model Downloads'),
      SettingRef('models', 'a:cancel_download_item'),
      SettingRef('models', 'a:retry_download_item'),
      SettingRef('models', 'a:download_request_item'),
      SettingRef('models', 'a:supercombo_label'),
      SettingRef('models', 'a:vision_label'),
      SettingRef('models', 'a:policy_label'),
      SettingRef('models', 'a:off_policy_label'),
      SettingRef('models', 'a:on_policy_label'),
    ),
    leaf('planning', tr_noop('Planning Parameters'),
      SettingRef('models', 'p:LaneTurnDesire'),
      SettingRef('models', 'p:LaneTurnValue'),
      SettingRef('models', 'p:LagdToggle'),
      SettingRef('models', 'p:LagdToggleDelay'),
    ),
  ),
  folder('device', tr_noop('Device'),
    leaf('use', tr_noop('Language & Use'),
      SettingRef('device', 't:Change Language'),
      SettingRef('device', 'p:DeviceBootMode'),
      SettingRef('device', 'p:MaxTimeOffroad'),
      SettingRef('device', 'p:AudibleAlertMode'),
    ),
    leaf('calibration', tr_noop('Calibration & Device'),
      SettingRef('device', 'a:_reset_calib_btn'),
      SettingRef('device', 'a:_driver_cam_btn'),
      SettingRef('device', 't:Dongle ID'),
      SettingRef('device', 't:Serial'),
      SettingRef('device', 'a:_pair_device_btn'),
      SettingRef('device', 'a:_reg_and_training'),
      SettingRef('device', 'a:_reg_and_training', 1),
      SettingRef('device', 't:Terms & Conditions'),
    ),
    leaf('power', tr_noop('Power & Privacy'),
      SettingRef('device', 'a:_power_buttons'),
      SettingRef('device', 'a:_power_buttons', 1),
      SettingRef('device', 'p:OffroadMode'),
      SettingRef('device', 'p:dp_dev_disable_connect'),
      SettingRef('device', 'a:_onroad_uploads_and_reset_settings'),
      SettingRef('device', 'a:_onroad_uploads_and_reset_settings', 1),
    ),
  ),
  folder('network', tr_noop('Network'),
    leaf('wifi', tr_noop('Wireless Networks'),
      SettingRef('network', 'n:wifi'),
      SettingRef('network', 'n:scan'),
      SettingRef('network', 'n:usage'),
      SettingRef('network', 'n:hidden'),
    ),
    leaf('hotspot', tr_noop('Hotspot Sharing'),
      SettingRef('network', 'n:tethering'),
      SettingRef('network', 'n:password'),
    ),
    leaf('cellular', tr_noop('Cellular Network'),
      SettingRef('network', 'n:roaming'),
      SettingRef('network', 'n:apn'),
      SettingRef('network', 'n:metered'),
    ),
  ),
  folder('sunnylink', tr_noop('sunnylink'),
    leaf('account', tr_noop('Connection & Account'),
      SettingRef('sunnylink', 'a:_intro_item'),
      SettingRef('sunnylink', 't:Dongle ID'),
      SettingRef('sunnylink', 'p:SunnylinkEnabled'),
      SettingRef('sunnylink', 'a:_sponsor_btn'),
      SettingRef('sunnylink', 'a:_pair_btn'),
      SettingRef('sunnylink', 'p:EnableSunnylinkUploader'),
    ),
    leaf('backup', tr_noop('Backup & Restore'),
      SettingRef('sunnylink', 'a:_transfer_item'),
      SettingRef('sunnylink', 'a:_sunnylink_backup_restore_buttons'),
      SettingRef('sunnylink', 'a:_sunnylink_backup_restore_buttons', 1),
    ),
  ),
  leaf('software', tr_noop('Software'),
    SettingRef('software', 'a:_onroad_label'),
    SettingRef('software', 'a:_version_item'),
    SettingRef('software', 'a:_download_btn'),
    SettingRef('software', 'a:_install_btn'),
    SettingRef('software', 'a:_branch_btn'),
    SettingRef('software', 'a:_uninstall_btn'),
    SettingRef('software', 'p:DisableUpdates'),
  ),
  folder('visuals', tr_noop('Visuals'),
    leaf('hud', tr_noop('Driving Information'),
      SettingRef('visuals', 'p:TrueVEgoUI'),
      SettingRef('visuals', 'p:HideVEgoUI'),
      SettingRef('visuals', 'a:_chevron_info'),
      SettingRef('visuals', 'p:DevUIInfo'),
      SettingRef('visuals', 'p:RocketFuel'),
      SettingRef('visuals', 'p:TorqueBar'),
    ),
    leaf('alerts', tr_noop('Visuals & Alerts'),
      SettingRef('visuals', 'p:BlindSpot'),
      SettingRef('visuals', 'p:RainbowMode'),
      SettingRef('visuals', 'p:StandstillTimer'),
      SettingRef('visuals', 'p:RoadNameToggle'),
      SettingRef('visuals', 'p:GreenLightAlert'),
      SettingRef('visuals', 'p:LeadDepartAlert'),
      SettingRef('visuals', 'p:ShowTurnSignals'),
    ),
  ),
  folder('display', tr_noop('Display'),
    leaf('screen', tr_noop('Brightness & Sleep'),
      SettingRef('display', 'p:OnroadScreenOffBrightness'),
      SettingRef('display', 'p:OnroadScreenOffTimer'),
      SettingRef('display', 'p:InteractivityTimeout'),
    ),
    leaf('clock', tr_noop('Date & Timezone'),
      SettingRef('display', 'p:dp_show_date_time'),
      SettingRef('display', 'p:Timezone'),
    ),
  ),
  leaf('osm', tr_noop('OSM'),
    SettingRef('osm', 'a:_mapd_version'),
    SettingRef('osm', 'a:_delete_maps_btn'),
    SettingRef('osm', 'a:_progress'),
    SettingRef('osm', 'a:_update_btn'),
    SettingRef('osm', 'a:_country_btn'),
    SettingRef('osm', 'a:_state_btn'),
  ),
  leaf('trips', tr_noop('Trips'),
    SettingRef('trips', 'n:refresh'),
    SettingRef('trips', 'n:all.routes'),
    SettingRef('trips', 'n:all.distance'),
    SettingRef('trips', 'n:all.minutes'),
    SettingRef('trips', 'n:week.routes'),
    SettingRef('trips', 'n:week.distance'),
    SettingRef('trips', 'n:week.minutes'),
  ),
  folder('firehose', tr_noop('Firehose'),
    leaf('firehose_stats', tr_noop('Operation & Statistics'),
      SettingRef('firehose', 'n:status'),
      SettingRef('firehose', 'n:contributions'),
      SettingRef('firehose', 'n:refresh'),
    ),
    leaf('firehose_help', tr_noop('Help & Questions'),
      SettingRef('firehose', 'n:description'),
      SettingRef('firehose', 'n:instructions'),
      SettingRef('firehose', 'n:faq.driving'),
      SettingRef('firehose', 'n:faq.uploads'),
      SettingRef('firehose', 'n:faq.usb'),
      SettingRef('firehose', 'n:faq.software'),
    ),
  ),
  folder('developer', tr_noop('Developer'),
    leaf('remote', tr_noop('ADB / SSH'),
      SettingRef('developer', 'p:AdbEnabled'),
      SettingRef('developer', 'p:SshEnabled'),
      SettingRef('developer', 'p:GithubSshKeys'),
    ),
    leaf('debug', tr_noop('Debugging & Controls'),
      SettingRef('developer', 'p:JoystickDebugMode'),
      SettingRef('developer', 'p:LongitudinalManeuverMode'),
      SettingRef('developer', 'p:LateralManeuverMode'),
      SettingRef('developer', 'p:AlphaLongitudinalEnabled'),
      SettingRef('developer', 'p:ShowDebugInfo'),
      SettingRef('developer', 'p:ForceOnroad'),
      SettingRef('developer', 'p:EnableLivestream'),
      SettingRef('developer', 'p:ShowAdvancedControls'),
    ),
    folder('diagnostics', tr_noop('Logs & Services'),
      leaf('logs', tr_noop('Logs & Diagnostics'),
        SettingRef('developer', 'a:error_log_btn'),
        SettingRef('developer', 'a:system_logs_item'),
        SettingRef('developer', 'a:system_logs_item', 1),
        SettingRef('developer', 'a:_log_status_item'),
      ),
      leaf('usb', tr_noop('USB Export'),
        SettingRef('developer', 'a:_usb_header'),
        SettingRef('developer', 'a:_usb_mount_item'),
        SettingRef('developer', 'a:_usb_scan_item'),
        SettingRef('developer', 'a:_usb_export_logs_item'),
        SettingRef('developer', 'a:_usb_export_realdata_item'),
        SettingRef('developer', 'a:_usb_export_realdata_logs_item'),
        SettingRef('developer', 'a:_usb_export_progress_item'),
      ),
      leaf('services', tr_noop('System Services'),
        SettingRef('developer', 'p:EnableGithubRunner'),
        SettingRef('developer', 'p:EnableCopyparty'),
        SettingRef('developer', 'p:QuickBootToggle'),
      ),
    ),
  ),
)

NODES = {}
PATHS = {}
SETTING_ROUTES = {}


def _index(node, path=()):
  NODES[node.key] = node
  PATHS[node.key] = (*path, node.key)
  for item in node.items:
    if item.key in SETTING_ROUTES:
      raise ValueError(f'Duplicate setting route: {item.key}')
    SETTING_ROUTES[item.key] = node.key
  for child in node.children:
    _index(child, PATHS[node.key])


_index(MENU_TREE)
