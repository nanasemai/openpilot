"""Operate on the exact regular log files shown in a settings confirmation."""
import os
import stat
from dataclasses import dataclass


@dataclass(frozen=True)
class LogFile:
  name: str
  identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class LogSnapshot:
  root: str
  directory: tuple[int, int]
  files: tuple[LogFile, ...]

  @property
  def size(self):
    return sum(file.identity[2] for file in self.files)


@dataclass(frozen=True)
class LogDeleteResult:
  total: int
  deleted: int
  changed: int
  errors: tuple[str, ...]


def file_identity(info):
  return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def scan_logs(root: str) -> LogSnapshot:
  fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
  try:
    info = os.fstat(fd)
    files = []
    with os.scandir(fd) as entries:
      for entry in entries:
        if entry.name.startswith('swaglog.') and entry.is_file(follow_symlinks=False):
          files.append(LogFile(entry.name, file_identity(entry.stat(follow_symlinks=False))))
    return LogSnapshot(root, (info.st_dev, info.st_ino), tuple(sorted(files, key=lambda file: file.name)))
  finally:
    os.close(fd)


def delete_logs(snapshot: LogSnapshot) -> LogDeleteResult:
  deleted = changed = 0
  errors = []
  try:
    fd = os.open(snapshot.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
      info = os.fstat(fd)
      if (info.st_dev, info.st_ino) != snapshot.directory:
        return LogDeleteResult(len(snapshot.files), 0, len(snapshot.files), ())
      for file in snapshot.files:
        try:
          info = os.stat(file.name, dir_fd=fd, follow_symlinks=False)
          if not stat.S_ISREG(info.st_mode) or file_identity(info) != file.identity:
            changed += 1
            continue
          os.unlink(file.name, dir_fd=fd)
          deleted += 1
        except FileNotFoundError:
          changed += 1
        except OSError as error:
          errors.append(f'{file.name}: {error}')
    finally:
      os.close(fd)
  except OSError as error:
    errors.append(str(error))
  return LogDeleteResult(len(snapshot.files), deleted, changed, tuple(errors))
