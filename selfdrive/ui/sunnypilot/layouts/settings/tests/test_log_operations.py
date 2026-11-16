"""Log cleanup preserves files outside the confirmed snapshot and reports failures."""
import os

import pytest
from openpilot.selfdrive.ui.sunnypilot.layouts.settings import log_operations as logs


def test_scan_and_delete_use_confirmed_regular_files_only(tmp_path):
  root = tmp_path / 'logs'
  root.mkdir()
  (root / 'swaglog.1').write_text('first')
  (root / 'swaglog.2').write_text('second')
  (root / 'swaglog.directory').mkdir()
  external = tmp_path / 'outside'
  external.write_text('kept')
  (root / 'swaglog.link').symlink_to(external)
  (root / 'other.log').write_text('kept')
  snapshot = logs.scan_logs(str(root))
  assert {file.name for file in snapshot.files} == {'swaglog.1', 'swaglog.2'}
  assert snapshot.size == 11
  (root / 'swaglog.new').write_text('new after confirmation')
  result = logs.delete_logs(snapshot)
  assert result.deleted == result.total == 2
  assert not result.errors and result.changed == 0
  assert (root / 'swaglog.new').read_text() == 'new after confirmation'
  assert external.read_text() == 'kept'
  assert (root / 'other.log').read_text() == 'kept'
  assert (root / 'swaglog.link').is_symlink()


@pytest.mark.parametrize('change', ['append', 'replace', 'symlink', 'disappear'])
def test_changed_files_are_not_deleted(tmp_path, change):
  file = tmp_path / 'swaglog.1'
  file.write_text('original')
  snapshot = logs.scan_logs(str(tmp_path))
  outside = tmp_path / 'outside'
  outside.write_text('replacement')
  if change == 'append':
    file.write_text('appended')
  elif change == 'replace':
    file.unlink()
    outside.rename(file)
  elif change == 'symlink':
    file.unlink()
    file.symlink_to(outside)
  else:
    file.unlink()
  result = logs.delete_logs(snapshot)
  assert result.deleted == 0 and result.changed == 1
  assert not result.errors
  if change != 'disappear':
    assert file.exists()


def test_replaced_log_directory_keeps_new_directory_files(tmp_path):
  root = tmp_path / 'logs'
  root.mkdir()
  (root / 'swaglog.1').write_text('old')
  snapshot = logs.scan_logs(str(root))
  root.rename(tmp_path / 'old_logs')
  root.mkdir()
  (root / 'swaglog.1').write_text('new')
  result = logs.delete_logs(snapshot)
  assert result.changed == 1 and result.deleted == 0
  assert (root / 'swaglog.1').read_text() == 'new'
  assert (tmp_path / 'old_logs' / 'swaglog.1').exists()


def test_delete_failure_does_not_report_complete_and_retry_removes_remaining_file(tmp_path, monkeypatch):
  for name in ('swaglog.1', 'swaglog.2'):
    (tmp_path / name).write_text(name)
  snapshot = logs.scan_logs(str(tmp_path))
  original = os.unlink
  def unlink(name, **kwargs):
    if name == 'swaglog.2':
      raise PermissionError('read-only log')
    original(name, **kwargs)
  with monkeypatch.context() as changes:
    changes.setattr(logs.os, 'unlink', unlink)
    result = logs.delete_logs(snapshot)
  assert result.deleted == 1 and result.total == 2
  assert len(result.errors) == 1 and 'swaglog.2' in result.errors[0]
  assert (tmp_path / 'swaglog.2').exists()
  retry = logs.delete_logs(logs.scan_logs(str(tmp_path)))
  assert retry.deleted == retry.total == 1 and not retry.errors


def test_directory_symlink_is_not_scanned_or_deleted(tmp_path):
  root = tmp_path / 'real'
  root.mkdir()
  (root / 'swaglog.1').write_text('kept')
  alias = tmp_path / 'alias'
  alias.symlink_to(root, target_is_directory=True)
  with pytest.raises(OSError):
    logs.scan_logs(str(alias))
  snapshot = logs.scan_logs(str(root))
  altered = logs.LogSnapshot(str(alias), snapshot.directory, snapshot.files)
  result = logs.delete_logs(altered)
  assert result.errors and result.deleted == 0
  assert (root / 'swaglog.1').exists()
