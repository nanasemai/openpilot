#!/usr/bin/env python3
import datetime
import subprocess
import threading
import time
from typing import NoReturn

import cereal.messaging as messaging
from openpilot.common.time_helpers import min_date, MAX_DATE, system_time_valid
from openpilot.common.swaglog import cloudlog
from openpilot.common.params import Params
from openpilot.common.gps import get_gps_location_service
from openpilot.system import time_sync


TIME_SYNC_RETRY_S = 60.0


def set_time(new_time, params: Params):
  diff = datetime.datetime.now() - new_time
  if abs(diff) < datetime.timedelta(seconds=10):
    cloudlog.debug(f"Time diff too small: {diff}")
    # Time is already close to the GPS truth, but this is still a valid time
    # observation — record it so a later cold boot (RTC reset to 1970, no
    # network) can recover instead of staying stuck.
    time_sync.save_last_valid_time(new_time, params)
    return

  # `new_time` is a naive *local* datetime, so it must be passed to `date -s`
  # without TZ=UTC. Adding TZ=UTC made the local string be read as UTC and
  # shifted the clock by the local offset (8 hours on the car).
  cloudlog.debug(f"Setting time to {new_time}")
  try:
    subprocess.run(f"date -s '{new_time}'", shell=True, check=True)
    # Persist the corrected time so the LastValidTime fallback in
    # time_sync.ensure_time_valid() has a value to restore from on the next
    # boot. `new_time` is naive local, so `.timestamp()` yields the correct
    # epoch and round-trips with get_last_valid_time()'s UTC read.
    time_sync.save_last_valid_time(new_time, params)
  except subprocess.CalledProcessError:
    cloudlog.exception("timed.failed_setting_time")


def sync_time_at_boot():
  """Run NTP sync in a daemon thread.

  timed only corrected time from the car's GPS, so on the test bench (no fix)
  the clock never left the 1970 RTC value. Sync is offloaded to a thread
  because it can block on network timeouts and timed must keep publishing the
  clocks message.
  """
  def _sync():
    try:
      time_sync.ensure_time_valid()
    except Exception:
      cloudlog.exception("timed.boot_time_sync_failed")
  threading.Thread(target=_sync, name="time_boot_sync", daemon=True).start()


def retry_time_sync(last_attempt: list[float]) -> None:
  """Re-check the clock periodically.

  GPS never reports a fix on the test bench, and AGNOS' own timesyncd can sit
  waiting on it, so the clock stays unusable. Run off the publish loop because
  an NTP attempt can block on network timeouts.
  """
  if time.monotonic() - last_attempt[0] < TIME_SYNC_RETRY_S:
    return
  last_attempt[0] = time.monotonic()

  def _sync():
    try:
      if not system_time_valid():
        time_sync.ensure_time_valid()
      else:
        time_sync.sync_if_drifted()
    except Exception:
      cloudlog.exception("timed.time_sync_failed")
  threading.Thread(target=_sync, name="time_sync_retry", daemon=True).start()


def main() -> NoReturn:
  """
    timed has two responsibilities:
    - getting the current time from GPS
    - publishing the time in the logs

    AGNOS will also use NTP to update the time.
  """

  params = Params()
  gps_location_service = get_gps_location_service(params)
  sync_time_at_boot()
  last_sync_attempt = [0.0]

  pm = messaging.PubMaster(['clocks'])
  sm = messaging.SubMaster([gps_location_service])
  while True:
    sm.update(1000)

    retry_time_sync(last_sync_attempt)

    msg = messaging.new_message('clocks')
    msg.valid = system_time_valid()
    msg.clocks.wallTimeNanos = time.time_ns()
    pm.send('clocks', msg)

    gps = sm[gps_location_service]
    gps_time = datetime.datetime.fromtimestamp(gps.unixTimestampMillis / 1000.)
    if not sm.updated[gps_location_service] or (time.monotonic() - sm.logMonoTime[gps_location_service] / 1e9) > 2.0:
      continue
    if not gps.hasFix:
      continue
    if gps_time < min_date() or gps_time > MAX_DATE:
      continue

    set_time(gps_time, params)
    time.sleep(10)

if __name__ == "__main__":
  main()
