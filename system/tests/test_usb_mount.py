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
  (route / 'fcamera.hevc').write_bytes(b'video data')
  destination = tmp_path / 'usb'
  destination.mkdir()
  monkeypatch.setattr(usb_mount, 'REALDATA_SRC', str(source))
  progress = []
  ok, message = usb_mount.export_realdata(str(destination), lambda pct, text: progress.append((pct, text)))
  assert ok and message == 'Copied 2 files'
  assert (destination / 'realdata' / 'realdata' / 'route-0' / 'rlog.zst').read_bytes() == b'route data'
  assert (destination / 'realdata' / 'realdata' / 'route-0' / 'fcamera.hevc').read_bytes() == b'video data'
  assert (route / 'rlog.zst').read_bytes() == b'route data'
  assert progress[-1][0] == 100


def test_route_log_export_skips_videos_and_keeps_all_log_formats(tmp_path, monkeypatch):
  source = tmp_path / 'source' / 'realdata'
  route = source / 'route-0'
  route.mkdir(parents=True)
  logs = ('rlog', 'qlog', 'rlog.zst', 'qlog.zst', 'rlog.bz2', 'qlog.bz2')
  videos = ('fcamera.hevc', 'dcamera.hevc', 'ecamera.hevc', 'qcamera.ts', 'preview.mp4', 'rlog.zst.lock')
  for name in logs + videos:
    (route / name).write_bytes(name.encode())
  destination = tmp_path / 'usb'
  destination.mkdir()
  monkeypatch.setattr(usb_mount, 'REALDATA_SRC', str(source))
  progress = []
  ok, message = usb_mount.export_realdata_logs(str(destination), lambda pct, text: progress.append((pct, text)))
  assert ok and message == 'Copied 6 files'
  target = destination / 'realdata_logs' / 'route-0'
  assert {file.name for file in target.iterdir()} == set(logs)
  assert all((target / name).read_bytes() == name.encode() for name in logs)
  assert all((route / name).exists() for name in videos)
  assert [pct for pct, _ in progress] == [0, *[done / len(logs) * 100 for done in range(1, len(logs) + 1)]]


def test_route_log_export_with_only_videos_reports_no_logs(tmp_path, monkeypatch):
  source = tmp_path / 'realdata'
  source.mkdir()
  (source / 'fcamera.hevc').write_bytes(b'video')
  destination = tmp_path / 'usb'
  destination.mkdir()
  monkeypatch.setattr(usb_mount, 'REALDATA_SRC', str(source))
  ok, message = usb_mount.export_realdata_logs(str(destination))
  assert not ok and message == 'No route log files found'
  assert not (destination / 'realdata_logs').exists()


@pytest.mark.parametrize('exporter', [usb_mount.export_logs, usb_mount.export_realdata, usb_mount.export_realdata_logs])
def test_missing_destination_reports_failure(tmp_path, exporter):
  ok, message = exporter(str(tmp_path / 'missing'))
  assert not ok
  assert message.template == 'Destination not mounted: {path}'


@pytest.mark.parametrize(('exporter', 'folder'), [
  (usb_mount.export_logs, 'logs'),
  (usb_mount.export_realdata, 'realdata'),
  (usb_mount.export_realdata_logs, 'realdata_logs'),
])
def test_export_removes_existing_folder_before_copying(tmp_path, monkeypatch, exporter, folder):
  source = tmp_path / 'source' / 'realdata'
  route = source / 'route-0'
  route.mkdir(parents=True)
  (route / 'rlog.zst').write_bytes(b'new log')
  monkeypatch.setattr(usb_mount, 'REALDATA_SRC', str(source))
  monkeypatch.setattr(usb_mount, 'LOG_SOURCES', [(str(source), 'swaglog')])
  destination = tmp_path / 'usb'
  old = destination / folder / 'obsolete-route' / 'old.log'
  old.parent.mkdir(parents=True)
  old.write_bytes(b'old export')
  unrelated = destination / 'keep.txt'
  unrelated.write_bytes(b'other data')
  copy = usb_mount.shutil.copy2
  copied = []

  def checked_copy(src, dst):
    assert not old.exists()
    copied.append(Path(dst))
    return copy(src, dst)

  monkeypatch.setattr(usb_mount.shutil, 'copy2', checked_copy)
  ok, _message = exporter(str(destination))
  assert ok and len(copied) == 1
  assert copied[0].read_bytes() == b'new log'
  assert not old.parent.exists()
  assert unrelated.read_bytes() == b'other data'
  assert (route / 'rlog.zst').read_bytes() == b'new log'


@pytest.mark.parametrize(('exporter', 'folder'), [
  (usb_mount.export_logs, 'logs'),
  (usb_mount.export_realdata, 'realdata'),
  (usb_mount.export_realdata_logs, 'realdata_logs'),
])
def test_failed_export_cleanup_does_not_start_copying(tmp_path, monkeypatch, exporter, folder):
  source = tmp_path / 'realdata'
  source.mkdir()
  (source / 'rlog.zst').write_bytes(b'new log')
  monkeypatch.setattr(usb_mount, 'REALDATA_SRC', str(source))
  monkeypatch.setattr(usb_mount, 'LOG_SOURCES', [(str(source), 'swaglog')])
  destination = tmp_path / 'usb'
  old = destination / folder / 'old.log'
  old.parent.mkdir(parents=True)
  old.write_bytes(b'old export')
  copied = []

  def fail_cleanup(path):
    raise PermissionError('Cannot delete previous export')

  monkeypatch.setattr(usb_mount.shutil, 'rmtree', fail_cleanup)
  monkeypatch.setattr(usb_mount.shutil, 'copy2', lambda *args: copied.append(args))
  ok, message = exporter(str(destination))
  assert not ok and 'Cannot delete previous export' in message
  assert not copied
  assert old.read_bytes() == b'old export'
