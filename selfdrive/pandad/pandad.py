#!/usr/bin/env python3
# simple pandad wrapper that updates the panda first
import os
import usb1
import time
import signal
import subprocess

from panda_tici import Panda, PandaDFU, PandaProtocolMismatch, FW_PATH, McuType
from openpilot.common.basedir import BASEDIR
from openpilot.common.params import Params
from openpilot.system.hardware import HARDWARE
from openpilot.common.swaglog import cloudlog

from openpilot.sunnypilot.selfdrive.pandad.rivian_long_flasher import flash_rivian_long


def flash_panda(panda_serial: str) -> bool:
  """Flash panda if needed. Returns True if the panda is usable, False if incompatible."""
  panda = Panda(panda_serial)
  hw_type = panda.get_type()

  try:
    mcu_type = panda.get_mcu_type()
  except ValueError:
    cloudlog.warning(f"Panda {panda_serial} HW type {hw_type} unknown, skipping")
    panda.close()
    return False

  fw_fn = os.path.join(FW_PATH, mcu_type.config.app_fn)
  fw_sig = Panda.get_signature_from_firmware(fw_fn)
  internal_panda = panda.is_internal()

  panda_version = "bootstub" if panda.bootstub else panda.get_version()
  panda_sig = b"" if panda.bootstub else panda.get_signature()

  # 打印详细 panda 状态，方便刷机排查
  hw_type_names = {
    b'\x01': "WHITE_PANDA", b'\x02': "GREY_PANDA", b'\x03': "BLACK_PANDA",
    b'\x04': "PEDAL", b'\x05': "UNO", b'\x06': "DOS",
    b'\x07': "RED_PANDA", b'\x08': "RED_PANDA_V2", b'\x09': "TRES", b'\x0a': "CUATRO",
  }
  hw_name = hw_type_names.get(bytes(hw_type) if isinstance(hw_type, bytearray) else hw_type, f"UNKNOWN({hw_type.hex() if isinstance(hw_type, (bytes, bytearray)) else hw_type})")
  cloudlog.warning(f"===== Panda startup info =====")
  cloudlog.warning(f"  Serial:      {panda_serial}")
  cloudlog.warning(f"  HW type:     {hw_name}")
  cloudlog.warning(f"  MCU type:    {mcu_type.name}")
  cloudlog.warning(f"  Internal:    {internal_panda}")
  cloudlog.warning(f"  Bootstub:    {panda.bootstub}")
  cloudlog.warning(f"  Version:     {panda_version}")
  cloudlog.warning(f"  Signature:   {panda_sig.hex()[:16] if panda_sig else 'N/A'}")
  cloudlog.warning(f"  Expected:    {fw_sig.hex()[:16]}")
  cloudlog.warning(f"  Up to date:  {panda_sig == fw_sig}")
  cloudlog.warning(f"==============================")
  cloudlog.warning(f"Panda {panda_serial} connected, version: {panda_version}, "
                   f"signature {panda_sig.hex()[:16]}, expected {fw_sig.hex()[:16]}")

  if panda.bootstub or panda_sig != fw_sig:
    cloudlog.info("Panda firmware out of date, update required")
    panda.flash()
    cloudlog.info("Done flashing")

  if panda.bootstub:
    bootstub_version = panda.get_version()
    cloudlog.info(f"Flashed firmware not booting, flashing development bootloader. {bootstub_version=}, {internal_panda=}")
    if internal_panda:
      HARDWARE.recover_internal_panda()
    panda.recover(reset=(not internal_panda))
    cloudlog.info("Done flashing bootstub")

  if panda.bootstub:
    cloudlog.info("Panda still not booting, exiting")
    raise AssertionError

  panda_sig = panda.get_signature()
  if panda_sig != fw_sig:
    cloudlog.info("Version mismatch after flashing, exiting")
    raise AssertionError

  panda.close()
  return True


def main() -> None:
  # signal pandad to close the relay and exit
  def signal_handler(signum, frame):
    cloudlog.info(f"Caught signal {signum}, exiting")
    nonlocal do_exit
    do_exit = True
    if process is not None:
      process.send_signal(signal.SIGINT)

  process = None
  do_exit = False
  signal.signal(signal.SIGINT, signal_handler)

  # check health for lost heartbeat（跳过固件版本不匹配的设备，后续会刷写）
  for s in Panda.list():
    try:
      with Panda(s) as p:
        health = p.health()
        if p.is_internal() and health["heartbeat_lost"]:
          Params().put_bool("PandaHeartbeatLost", True, block=True)
          cloudlog.event("heartbeat lost", deviceState=health)
    except Exception:
      cloudlog.exception("pandad.uncaught_exception")

  count = 0
  while not do_exit:
    try:
      cloudlog.event("pandad.flash_and_connect", count=count)
      if (count % 2) == 0:
        HARDWARE.reset_internal_panda()
      else:
        HARDWARE.recover_internal_panda()
      count += 1

      # Flash all Pandas in DFU mode
      for serial in PandaDFU.list():
        cloudlog.info(f"Panda in DFU mode found, flashing recovery {serial}")
        PandaDFU(serial).recover()
        time.sleep(1)

      panda_serials = Panda.list()
      if panda_serials:
        cloudlog.info(f"{len(panda_serials)} panda(s) found - {panda_serials}")

        serial = None
        for s in panda_serials:
          if flash_panda(s):
            serial = s
            break
        cloudlog.warning(f"Panda {s} is not usable, trying next")

        if serial is None:
          cloudlog.error("No usable panda found, sleeping 5s")
          time.sleep(5)
          continue

        # run real pandad
        os.environ['MANAGER_DAEMON'] = 'pandad'
        process = subprocess.Popen(["./pandad"], cwd=os.path.join(BASEDIR, "selfdrive/pandad"))
        process.wait()
    # TODO: wrap all panda exceptions in a base panda exception
    except (usb1.USBErrorNoDevice, usb1.USBErrorPipe):
      # a panda was disconnected while setting everything up. let's try again
      cloudlog.exception("Panda USB exception while setting up")
    except PandaProtocolMismatch:
      cloudlog.exception("pandad.protocol_mismatch")
    except Exception:
      cloudlog.exception("pandad.uncaught_exception")


if __name__ == "__main__":
  main()
