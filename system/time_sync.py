"""NTP fallback time sync module.

Provides `ensure_time_valid()` which checks if the system time is reasonable
and syncs it via NTP if needed. Called by the screen recorder before starting
and by timed.py at boot.

Sync priority: NTP servers → LastValidTime param → no-op.

`get_ntp_time()` talks real NTP over UDP. The previous implementation fetched
`https://<ntp-host>` and read the HTTP `Date` header, which never works: those
hosts only listen on UDP/123, so every sync attempt failed and fell through to
the (empty) LastValidTime param.
"""

from __future__ import annotations

import datetime
import os
import socket
import struct
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from openpilot.common.swaglog import cloudlog

if TYPE_CHECKING:
  from openpilot.common.params import Params


DEFAULT_NTP_SERVERS = [
  "ntp.aliyun.com",
  "ntp.tencent.com",
  "pool.ntp.org",
  "cn.ntp.org.cn",
  "ntp.ntsc.ac.cn",
]

MIN_DATE_UTC = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)
MAX_DATE_UTC = datetime.datetime(2040, 1, 1, tzinfo=datetime.UTC)
REQUEST_TIMEOUT = 3.0
# Beyond this much drift the clock is considered wrong even though it is
# still "valid" by the MIN_DATE_UTC check.
DEFAULT_MAX_DRIFT_S = 30.0

# NTP started counting from 1900-01-01. Servers in the current era (1900-2036)
# return the seconds as a plain 32-bit value, so they must NOT be remapped via
# the era bit: bit 30 of the seconds field is an ordinary bit, and treating it
# as an era marker shifts the result by 34 years.
NTP_EPOCH_UTC = datetime.datetime(1900, 1, 1, tzinfo=datetime.UTC)
NTP_PACKET_SIZE = 48
NTP_PORT = 123
# NTP request: LI=0, VN=3, Mode=3 (client)
NTP_REQUEST = b"\x1b" + b"\x00" * (NTP_PACKET_SIZE - 1)


def get_ntp_time_udp(server: str, timeout: float = REQUEST_TIMEOUT) -> datetime.datetime | None:
  """Query one NTP server over UDP and return the server's UTC time."""
  try:
    addr = socket.getaddrinfo(server, NTP_PORT, socket.AF_INET, socket.SOCK_DGRAM)
    if not addr:
      return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
      sock.sendto(NTP_REQUEST, (addr[0][4][0], NTP_PORT))
      raw, _ = sock.recvfrom(NTP_PACKET_SIZE)
    finally:
      sock.close()
    if len(raw) < 48:
      return None
    # Field 3 is the transmit timestamp (seconds, fraction).
    secs = struct.unpack("!I", raw[40:44])[0]
    frac = struct.unpack("!I", raw[44:48])[0]
    delta = secs + frac / (2 ** 32)
  except (OSError, TimeoutError):
    return None

  # Servers in the current era return plain seconds from 1900, so the seconds
  # field overflows in 2036. Try that first, then the post-overflow reading.
  # Range-checking (not comparing against the local clock) keeps this usable
  # when the local clock is broken, which is the case we are syncing for.
  for offset in (0, 2 ** 32):
    dt = NTP_EPOCH_UTC + datetime.timedelta(seconds=offset + delta)
    if MIN_DATE_UTC < dt < MAX_DATE_UTC:
      return dt
  return None


def get_ntp_time(servers: list[str] | None = None) -> datetime.datetime | None:
  """Try to get time from NTP servers over UDP."""
  servers = servers or DEFAULT_NTP_SERVERS
  for server in servers:
    ts = get_ntp_time_udp(server)
    if ts is not None and ts > MIN_DATE_UTC:
      return ts
  return None


def set_system_time(dt: datetime.datetime, source: str) -> bool:
  """Set system time to the given UTC datetime."""
  if dt <= MIN_DATE_UTC:
    cloudlog.warning(f"[time_sync] invalid time from {source}: {dt}")
    return False
  ts = dt.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")

  # `date -s` interprets the string in the process timezone. Without TZ=UTC the
  # UTC string above would be read as local time (CST on the car), shifting the
  # clock by 8 hours.
  env = {**os.environ, "TZ": "UTC"}
  for cmd in (["date", "-s", ts], ["sudo", "date", "-s", ts]):
    try:
      rc = subprocess.run(cmd, env=env, capture_output=True, timeout=5)
      if rc.returncode == 0:
        cloudlog.info(f"[time_sync] system time set from {source}: {ts}")
        return True
    except (OSError, subprocess.SubprocessError):
      continue
  cloudlog.warning(f"[time_sync] failed to set system time from {source}: {ts}")
  return False


def save_last_valid_time(dt: datetime.datetime, params: Params) -> None:
  try:
    ts = int(dt.timestamp())
    if ts > 0:
      params.put("LastValidTime", str(ts))
  except (ValueError, TypeError, OSError):
    pass


def get_last_valid_time(params: Params) -> datetime.datetime | None:
  v = params.get("LastValidTime")
  if not v:
    return None
  try:
    return datetime.datetime.fromtimestamp(int(v), datetime.UTC) + datetime.timedelta(minutes=5)
  except (ValueError, TypeError):
    return None


def get_ntp_servers(params: Params) -> list[str]:
  v = params.get("TimeSyncNtpServers")
  if v:
    return [s.strip() for s in v.split(",") if s.strip()]
  return DEFAULT_NTP_SERVERS


def is_time_valid() -> bool:
  """Check if system time is after MIN_DATE_UTC."""
  return datetime.datetime.now(datetime.UTC) > MIN_DATE_UTC


def ensure_time_valid(params: Params | None = None,
                      logger: Callable[[str], None] | None = None) -> bool:
  """Ensure system time is valid. Returns True if time was already valid or was synced.

  Called before screen recording starts. If system time is invalid (e.g.,
  after cold boot), attempts NTP sync, then falls back to LastValidTime.
  """
  params = params or __import__("openpilot.common.params", fromlist=["Params"]).Params()
  log = logger or cloudlog.info

  if is_time_valid():
    save_last_valid_time(datetime.datetime.now(datetime.UTC), params)
    return True

  log("[time_sync] system time invalid, attempting NTP sync")

  ntp_time = get_ntp_time(get_ntp_servers(params))
  if ntp_time and set_system_time(ntp_time, "NTP"):
    save_last_valid_time(ntp_time, params)
    return True

  last_time = get_last_valid_time(params)
  if last_time and set_system_time(last_time, "LastValidTime"):
    save_last_valid_time(last_time, params)
    return True

  log("[time_sync] all sync sources failed, time may be incorrect")
  return False


def sync_if_drifted(params: Params | None = None,
                    max_drift_s: float = DEFAULT_MAX_DRIFT_S) -> bool:
  """Correct the clock if it is plausible but has drifted from NTP.

  `ensure_time_valid()` returns early as soon as the clock is past MIN_DATE_UTC,
  which leaves a clock that is "reasonable" but hours off. Used by timed.py on
  a periodic timer.
  """
  params = params or __import__("openpilot.common.params", fromlist=["Params"]).Params()

  ntp_time = get_ntp_time(get_ntp_servers(params))
  if ntp_time is None:
    return False

  drift = abs((datetime.datetime.now(datetime.UTC) - ntp_time).total_seconds())
  if drift <= max_drift_s:
    save_last_valid_time(datetime.datetime.now(datetime.UTC), params)
    return False

  cloudlog.warning(f"[time_sync] clock drift of {drift:.1f}s detected, correcting")
  if set_system_time(ntp_time, "NTP drift"):
    save_last_valid_time(ntp_time, params)
    return True
  return False
