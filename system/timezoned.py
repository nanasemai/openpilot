#!/usr/bin/env python3
"""Timezone service.

Reads the Timezone param and applies it to the system. Runs every 60 seconds.
GPS/IP-based timezone detection can be added in a future phase.
"""

import subprocess
import time
from typing import NoReturn

from openpilot.common.params import Params
from openpilot.system.hardware import AGNOS
from openpilot.common.swaglog import cloudlog
from openpilot.system.timezone_list import get_timezone_from_params


def set_timezone(timezone: str) -> None:
  if not timezone:
    return
  cloudlog.debug(f"Setting timezone to {timezone}")
  try:
    if AGNOS:
      tzpath = f"/usr/share/zoneinfo/{timezone}"
      subprocess.check_call(["sudo", "ln", "-snf", tzpath, "/data/etc/tmptime"])
      subprocess.check_call(["sudo", "mv", "/data/etc/tmptime", "/data/etc/localtime"])
      subprocess.check_call(["sudo", "bash", "-c", f"echo '{timezone}' > /data/etc/timezone"])
    else:
      subprocess.check_call(["sudo", "timedatectl", "set-timezone", timezone])
  except subprocess.CalledProcessError:
    cloudlog.exception(f"Error setting timezone to {timezone}")


def main() -> NoReturn:
  params = Params()
  current_tz = ""
  while True:
    time.sleep(60)
    tz = get_timezone_from_params(params)
    if tz and tz != current_tz:
      set_timezone(tz)
      current_tz = tz


if __name__ == "__main__":
  main()
