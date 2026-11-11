"""Settings backup requests retain failures and report partial restoration truthfully."""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from cereal import custom
from openpilot.common.params import Params
from openpilot.sunnypilot.sunnylink.backups import manager as backup_manager


@pytest.fixture
def manager(monkeypatch):
  manager = backup_manager.BackupManagerSP.__new__(backup_manager.BackupManagerSP)
  manager.params = Params()
  manager.device_id = 'test-device'
  manager.backup_status = manager.restore_status = custom.BackupManagerSP.Status.idle
  manager.progress = 0
  manager.operation = None
  manager.last_error = ''
  manager._session = None
  manager.api = SimpleNamespace(api_get=lambda *args, **kwargs: None, get_token=lambda: 'test-token')
  reports = []
  monkeypatch.setattr(manager, '_report_status', lambda: reports.append((manager.backup_status, manager.restore_status,
                                                                       manager.progress, manager.last_error)))
  manager.reports = reports
  monkeypatch.setattr(backup_manager, 'encrypt_compressed_data', lambda data, **kwargs: data)
  return manager


@pytest.mark.parametrize('success', [False, True])
def test_backup_failure_clears_error_on_retry_and_reports_real_result(manager, monkeypatch, success):
  manager.last_error = 'old failure'
  manager.restore_status = custom.BackupManagerSP.Status.failed
  monkeypatch.setattr(manager.api, 'api_get', lambda *args, **kwargs: success)
  assert asyncio.run(manager.create_backup()) is success
  assert manager.reports[0][0] == custom.BackupManagerSP.Status.inProgress
  assert manager.reports[0][1] == custom.BackupManagerSP.Status.idle
  assert manager.reports[0][2:] == (0, '')
  assert manager.backup_status == (custom.BackupManagerSP.Status.completed if success else custom.BackupManagerSP.Status.failed)
  assert manager.progress == (100 if success else 75)
  assert manager.last_error == ('' if success else 'Failed to upload backup')


def test_restore_applies_supported_settings_but_reports_partial_failure(manager, monkeypatch):
  config = {'ONROADUPLOADS': base64.b64encode(b'True').decode(),
            'InteractivityTimeout': base64.b64encode(b'invalid integer').decode(),
            'unknown-setting': base64.b64encode(b'ignored').decode()}
  response = SimpleNamespace(json=lambda: {'config': 'encrypted-settings'})
  monkeypatch.setattr(manager.api, 'api_get', lambda *args, **kwargs: response)
  monkeypatch.setattr(backup_manager, 'decrypt_compressed_data', lambda *args: json.dumps(config))
  assert not asyncio.run(manager.restore_backup())
  assert manager.params.get_bool('OnroadUploads')
  assert manager.params.get('InteractivityTimeout') is None
  assert manager.restore_status == custom.BackupManagerSP.Status.failed
  assert manager.last_error == 'Failed to restore 1 settings'
  assert manager.progress == 75


def test_restore_retry_saves_settings_before_reporting_completed(manager, monkeypatch):
  config = {'InteractivityTimeout': base64.b64encode(b'80').decode()}
  monkeypatch.setattr(manager.api, 'api_get', lambda *args, **kwargs: SimpleNamespace(json=lambda: {'config': 'encrypted'}))
  monkeypatch.setattr(backup_manager, 'decrypt_compressed_data', lambda *args: json.dumps(config))
  manager.last_error = 'Failed to restore 1 settings'
  manager.backup_status = custom.BackupManagerSP.Status.failed
  assert asyncio.run(manager.restore_backup())
  assert manager.params.get('InteractivityTimeout') == 80
  assert manager.reports[0][1] == custom.BackupManagerSP.Status.inProgress
  assert manager.reports[0][0] == custom.BackupManagerSP.Status.idle
  assert manager.reports[0][2:] == (0, '')
  assert manager.restore_status == custom.BackupManagerSP.Status.completed
  assert manager.last_error == '' and manager.progress == 100


@pytest.mark.parametrize('data,expected', [
  (None, 'No backup found for device test-device'),
  ({'config': ''}, 'Empty backup configuration'),
  ({'config': 'encrypted'}, 'Failed to decrypt backup configuration'),
])
def test_restore_failures_keep_specific_reason(manager, monkeypatch, data, expected):
  monkeypatch.setattr(manager.api, 'api_get', lambda *args, **kwargs: SimpleNamespace(json=lambda: data) if data is not None else None)
  monkeypatch.setattr(backup_manager, 'decrypt_compressed_data', lambda *args: None)
  assert not asyncio.run(manager.restore_backup())
  assert manager.restore_status == custom.BackupManagerSP.Status.failed
  assert manager.last_error == expected


class EndIterations(BaseException):
  pass


@pytest.mark.parametrize('kind,success', [('backup', True), ('backup', False), ('restore', True), ('restore', False)])
def test_manager_consumes_request_once_and_keeps_terminal_status_across_ticks(manager, monkeypatch, kind, success):
  calls, ticks = [], []
  async def transfer(*args):
    calls.append(kind)
    setattr(manager, kind + '_status', custom.BackupManagerSP.Status.completed if success else custom.BackupManagerSP.Status.failed)
    manager.progress = 100 if success else 50
    manager.last_error = '' if success else 'network error'
    return success
  monkeypatch.setattr(manager, 'create_backup' if kind == 'backup' else 'restore_backup', transfer)
  def tick():
    ticks.append(True)
    if len(ticks) == 3:
      raise EndIterations
  monkeypatch.setattr(backup_manager, 'Ratekeeper', lambda *args, **kwargs: SimpleNamespace(keep_time=tick))
  key = 'BackupManager_CreateBackup' if kind == 'backup' else 'BackupManager_RestoreVersion'
  manager.params.put(key, True if kind == 'backup' else 'latest', block=True)
  with pytest.raises(EndIterations):
    asyncio.run(manager.main_thread())
  assert calls == [kind]
  assert manager.params.get(key) is None
  index = 0 if kind == 'backup' else 1
  assert all(report[index] == (custom.BackupManagerSP.Status.completed if success else custom.BackupManagerSP.Status.failed)
             for report in manager.reports)
  assert all(report[2:] == (100 if success else 50, '' if success else 'network error') for report in manager.reports)
