"""Exercise real exports in temporary directories, without mounting block devices."""
import subprocess
from pathlib import Path

import pytest

from openpilot.system import usb_mount


def test_mount_success_keeps_cli_text_and_translation_fields(tmp_path, monkeypatch):
  monkeypatch.setattr(usb_mount, 'is_mounted', lambda _: False)
  commands = []
  def sudo(command):
    commands.append(command)
    return subprocess.CompletedProcess(command, 0, '', '')
  monkeypatch.setattr(usb_mount, '_sudo', sudo)
  result = usb_mount.mount_usb('/dev/mock1', str(tmp_path))
  assert result.ok
  assert result.message == f'Mounted /dev/mock1 at {tmp_path}'
  assert isinstance(result.message, str)
  assert result.message.template == 'Mounted {device} at {path}'
  assert commands[0][:4] == ['mount', '-t', 'vfat', '/dev/mock1']


def test_export_logs_copies_both_sources_and_reports_progress(tmp_path, monkeypatch):
  source = tmp_path / 'sources'
  source.mkdir()
  sources = []
  for name in ('swaglog', 'crashlog'):
    folder = source / name
    folder.mkdir()
    (folder / 'sample.log').write_text(name)
    sources.append((str(folder), name))
  destination = tmp_path / 'usb'
  destination.mkdir()
  monkeypatch.setattr(usb_mount, 'LOG_SOURCES', sources)
  progress = []
  ok, message = usb_mount.export_logs(str(destination), lambda pct, text: progress.append((pct, text)))
  assert ok and message == 'Exported 2/2 sources'
  for _folder, name in sources:
    assert (destination / 'logs' / name / 'sample.log').read_text() == name
  assert progress[-1][0] == 100
  assert all(isinstance(text, usb_mount.UsbMessage) for _, text in progress)


def test_partial_export_is_not_reported_as_success(tmp_path, monkeypatch):
  sources = [(str(tmp_path / name), name) for name in ('swaglog', 'crashlog')]
  for path, _ in sources:
    Path(path).mkdir()
  monkeypatch.setattr(usb_mount, 'LOG_SOURCES', sources)
  def copy(source, target, progress_callback=None):
    if source == sources[0][0]:
      return True, usb_mount.UsbMessage('Copied {count} files', count=1)
    return False, usb_mount.UsbMessage('USB copy failed: {error}', error='Copied.log: permission denied')
  monkeypatch.setattr(usb_mount, '_safe_copy', copy)
  ok, message = usb_mount.export_logs(str(tmp_path))
  assert not ok
  assert message.values['count'] == 1 and message.values['total'] == 2
  assert 'Copied.log: permission denied' in message


def test_route_export_copies_files_and_keeps_source_intact(tmp_path, monkeypatch):
  source = tmp_path / 'source' / 'realdata'
  route = source / 'route-0'
  route.mkdir(parents=True)
  (route / 'rlog.zst').write_bytes(b'route data')
  destination = tmp_path / 'usb'
  destination.mkdir()
  monkeypatch.setattr(usb_mount, 'REALDATA_SRC', str(source))
  progress = []
  ok, message = usb_mount.export_realdata(str(destination), lambda pct, text: progress.append((pct, text)))
  assert ok and message == 'Copied 1 files'
  assert (destination / 'realdata' / 'realdata' / 'route-0' / 'rlog.zst').read_bytes() == b'route data'
  assert (route / 'rlog.zst').read_bytes() == b'route data'
  assert progress[-1][0] == 100


@pytest.mark.parametrize('exporter', [usb_mount.export_logs, usb_mount.export_realdata])
def test_missing_destination_reports_failure(tmp_path, exporter):
  ok, message = exporter(str(tmp_path / 'missing'))
  assert not ok
  assert message.template == 'Destination not mounted: {path}'
