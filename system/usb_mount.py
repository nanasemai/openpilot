"""USB drive detection, mounting, and export helpers.

The `comma` user is not privileged, so every operation that touches the kernel
or a block device must go through `sudo` (passwordless sudo is available).
Callers get an explicit `(ok, message)` back so the UI never reports success for
a failed mount.
"""

import os
import re
import shutil
import subprocess
from typing import NamedTuple


MOUNT_DIR = "/data/media/usb"
AUTOMOUNT_LOG = os.path.join(MOUNT_DIR, "mount.log")
MOUNT_OPTS = "nodev,noexec,nosuid,uid=1000,gid=1000"

DEFAULT_TIMEOUT = 15


class MountResult(NamedTuple):
  ok: bool
  message: str


def _run(cmd: list[str], timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
  return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _sudo(cmd: list[str], timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
  return _run(["sudo", *cmd], timeout=timeout)


def _log(msg: str) -> None:
  try:
    with open(AUTOMOUNT_LOG, "a") as f:
      f.write(msg.rstrip("\n") + "\n")
  except OSError:
    pass


def get_usb_drives() -> list[dict]:
  """List partitions on removable USB disks with size/FS/UUID."""
  drives = []
  try:
    result = _run(["lsblk", "-d", "-o", "NAME,TYPE,RM", "-r"])
    if result.returncode != 0:
      return drives
    removable = {
      line.split()[0]
      for line in result.stdout.strip().split("\n")
      if len(line.split()) >= 3 and line.split()[0] not in ("NAME",) and line.split()[-1] == "1"
    }
    if not removable:
      return drives

    for disk in sorted(removable):
      part_result = _run(["lsblk", f"/dev/{disk}", "-o", "NAME,SIZE,FSTYPE,UUID", "-r"])
      if part_result.returncode != 0:
        continue
      for line in part_result.stdout.strip().split("\n")[1:]:
        parts = line.split()
        if len(parts) < 4 or not parts[0].startswith(f"{disk}"):
          continue
        if parts[0] == disk:  # skip the disk row itself
          continue
        drives.append({
          "device": f"/dev/{parts[0]}",
          "name": parts[0],
          "size": parts[1],
          "fstype": parts[2] if parts[2] else "none",
          "uuid": parts[3] if parts[3] else "none",
        })
  except (OSError, subprocess.SubprocessError, ValueError):
    pass
  return drives


def get_removable_partitions() -> set[str]:
  """Set of /dev/... paths for partitions on removable (RM=1) disks."""
  return {d["device"] for d in get_usb_drives()}


def is_removable_device(device: str) -> bool:
  """Read the kernel's `removable` flag. No subprocess, so it is cheap to call
  per mount candidate.

  A "/dev/sd*" prefix check is not enough: the eMMC boot card is itself
  `/dev/sda*`, so it would otherwise be mistaken for a USB drive.
  """
  name = os.path.basename(device)
  # `removable` only exists on the whole-disk sysfs entry, not on partitions,
  # so /dev/sdg1 must be resolved to the sdg disk.
  disk = re.sub(r"\d+$", "", name)
  try:
    with open(f"/sys/block/{disk}/removable") as f:
      return f.read().strip() == "1"
  except OSError:
    return False


def get_mount_status(device: str) -> str | None:
  """Return the mount point for a device, or None.

  Matches on the exact device field, not a substring, so `/dev/sdg1` cannot
  match `/dev/sdg11`.
  """
  try:
    with open("/proc/mounts") as f:
      for line in f:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == device:
          return parts[1]
  except OSError:
    pass
  return None


def get_mount_device(path: str) -> str | None:
  """Return the device backing a path, or None.

  Picks the most specific mount point. `/proc/mounts` lists parents before
  children, so a naive first match would resolve `/data/media/usb` to `/data`'s
  device (`/dev/sda12`) instead of the USB partition.
  """
  try:
    with open("/proc/mounts") as f:
      best_dev, best_len = None, -1
      for line in f:
        parts = line.split()
        if len(parts) < 2:
          continue
        mp = parts[1]
        if path == mp or path.startswith(mp + "/"):
          if len(mp) > best_len:
            best_dev, best_len = parts[0], len(mp)
      return best_dev
  except OSError:
    pass
  return None


def is_mounted(path: str = MOUNT_DIR) -> bool:
  """True if `path` is itself a mount point, not merely inside one.

  An exact match on /proc/mounts is required: `/data/media/usb` sits inside
  the `/data` mount, so a prefix match would report it as mounted before it
  ever was.
  """
  try:
    with open("/proc/mounts") as f:
      for line in f:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == path:
          return True
  except OSError:
    pass
  return False


def ensure_mount_dirs(mount_dir: str = MOUNT_DIR) -> None:
  os.makedirs(mount_dir, exist_ok=True)


def mount_usb(device: str, mount_dir: str = MOUNT_DIR, fstype: str = "vfat") -> MountResult:
  """Mount a FAT32 partition via sudo. Returns (ok, message)."""
  ensure_mount_dirs(mount_dir)

  if is_mounted(mount_dir):
    dev = get_mount_device(mount_dir)
    if dev == device:
      return MountResult(True, f"Already mounted at {mount_dir}")
    return MountResult(False, f"{mount_dir} is already in use by {dev}")

  cmd = ["mount", "-t", fstype, device, mount_dir, "-o", MOUNT_OPTS]
  try:
    result = _sudo(cmd)
  except (OSError, subprocess.SubprocessError) as e:
    return MountResult(False, f"{type(e).__name__}: {e}")

  if result.returncode != 0:
    err = (result.stderr or result.stdout or "").strip().replace("\n", " ")
    _log(f"FAIL mount {device} -> {mount_dir}: {err}")
    return MountResult(False, f"{err} (rc={result.returncode})")

  ensure_mount_dirs(mount_dir)
  _log(f"OK mount {device} -> {mount_dir}")
  return MountResult(True, f"Mounted {device} at {mount_dir}")


def unmount_usb(mount_dir: str = MOUNT_DIR) -> MountResult:
  if not is_mounted(mount_dir):
    return MountResult(True, f"{mount_dir} is not mounted")
  try:
    result = _sudo(["umount", mount_dir])
  except (OSError, subprocess.SubprocessError) as e:
    return MountResult(False, f"{type(e).__name__}: {e}")
  if result.returncode != 0:
    err = (result.stderr or result.stdout or "").strip().replace("\n", " ")
    return MountResult(False, f"{err} (rc={result.returncode})")
  _log(f"OK umount {mount_dir}")
  return MountResult(True, f"Unmounted {mount_dir}")


def unmount_device(device: str) -> MountResult:
  mount_point = get_mount_status(device)
  if mount_point is None:
    return MountResult(True, f"{device} is not mounted")
  return unmount_usb(mount_point)


def format_drive(device: str) -> MountResult:
  """Format a whole partition as FAT32. Unmounts it first if mounted."""
  mount_point = get_mount_status(device)
  if mount_point:
    unmount_usb(mount_point)
  try:
    result = _sudo(["mkfs.vfat", "-F", "32", device], timeout=180)
  except (OSError, subprocess.SubprocessError) as e:
    return MountResult(False, f"{type(e).__name__}: {e}")
  if result.returncode != 0:
    err = (result.stderr or result.stdout or "").strip().replace("\n", " ")
    return MountResult(False, f"{err} (rc={result.returncode})")
  _log(f"OK format {device} -> FAT32")
  return MountResult(True, f"Formatted {device} as FAT32")


# ── Export helpers ────────────────────────────────────────────────────────────
# Source directories on the device. All paths that exist at call time are
# exported; missing ones are skipped silently (e.g. no /data/log on PC).
LOG_SOURCES = [
  ("/data/log", "swaglog"),                  # main daemon logs
  ("/data/community/crashes", "crashlog"),   # crash reports
]
REALDATA_SRC = "/data/media/0/realdata"


def _copy_tree_with_progress(src: str, dst: str, progress_callback=None) -> tuple[bool, str]:
  """Copy a directory tree with per-file progress reporting.

  progress_callback(done, total, filename) is called after each file is copied.
  """
  # Count files first so the callback can report percentages
  file_count = 0
  for _dirpath, _dirnames, filenames in os.walk(src):
    file_count += len(filenames)

  done = 0
  try:
    if progress_callback and file_count > 0:
      progress_callback(0, file_count, os.path.basename(src))

    for dirpath, dirnames, filenames in os.walk(src):
      rel = os.path.relpath(dirpath, src)
      dst_dir = os.path.join(dst, rel) if rel != '.' else dst
      os.makedirs(dst_dir, exist_ok=True)

      for fname in filenames:
        src_file = os.path.join(dirpath, fname)
        dst_file = os.path.join(dst_dir, fname)

        if os.path.islink(src_file):
          try:
            os.symlink(os.readlink(src_file), dst_file)
          except OSError:
            pass
        else:
          shutil.copy2(src_file, dst_file)

        done += 1
        if progress_callback and file_count > 0:
          progress_callback(done, file_count, fname)

    return True, f"Copied {file_count} files"
  except (OSError, shutil.Error) as e:
    return False, f"{type(e).__name__}: {e}"


def _safe_copy(src: str, dst_dir: str, progress_callback=None) -> tuple[bool, str]:
  """Copy a file or directory tree to dst_dir.

  progress_callback(done, total, message) is called per file for directories,
  or once with (1, 1, basename) for individual files.
  """
  try:
    if os.path.isfile(src):
      shutil.copy2(src, os.path.join(dst_dir, os.path.basename(src)))
      if progress_callback:
        progress_callback(1, 1, os.path.basename(src))
      return True, f"Copied {os.path.basename(src)}"
    elif os.path.isdir(src):
      dst = os.path.join(dst_dir, os.path.basename(src.rstrip("/")))
      if os.path.exists(dst):
        shutil.rmtree(dst)
      return _copy_tree_with_progress(src, dst, progress_callback)
    else:
      return False, f"Source not found: {src}"
  except (OSError, shutil.Error) as e:
    return False, f"{type(e).__name__}: {e}"


def export_logs(dest_dir: str = MOUNT_DIR, progress_callback=None) -> tuple[bool, str]:
  """Export all log directories to dest_dir/logs/. Skips missing sources."""
  if not os.path.isdir(dest_dir):
    return False, f"Destination not mounted: {dest_dir}"

  target = os.path.join(dest_dir, "logs")
  os.makedirs(target, exist_ok=True)

  sources = [(src, label) for src, label in LOG_SOURCES if os.path.exists(src)]
  if not sources:
    return False, "No log sources found"

  total_sources = len(sources)
  results = []
  any_ok = False

  for idx, (src, label) in enumerate(sources):
    def _src_cb(done, total, fname, idx=idx, label=label, total_sources=total_sources):
      if progress_callback:
        overall_pct = ((idx + done / max(total, 1)) / total_sources) * 100
        progress_callback(overall_pct, f"{label}: {fname}")

    ok, msg = _safe_copy(src, target, progress_callback=_src_cb)
    results.append(f"{src} -> {msg}")
    any_ok = any_ok or ok

  if not any_ok:
    return False, "All copies failed:\n" + "\n".join(results)
  ok_count = len([r for r in results if 'Copied' in r])
  return True, f"Exported {ok_count}/{total_sources} sources"


def export_realdata(dest_dir: str = MOUNT_DIR, progress_callback=None) -> tuple[bool, str]:
  """Export the realdata directory (route files) to dest_dir/realdata/."""
  if not os.path.isdir(dest_dir):
    return False, f"Destination not mounted: {dest_dir}"
  if not os.path.isdir(REALDATA_SRC):
    return False, f"Realdata source not found: {REALDATA_SRC}"

  target = os.path.join(dest_dir, "realdata")
  os.makedirs(target, exist_ok=True)

  def _cb(done, total, fname):
    if progress_callback:
      progress_callback((done / max(total, 1)) * 100, f"realdata: {fname}")

  return _safe_copy(REALDATA_SRC, target, progress_callback=_cb)
