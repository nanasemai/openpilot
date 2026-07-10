"""Shared timezone definitions for settings UI and timezoned service."""


TZ_LIST = [
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Asia/Seoul",
  "Asia/Hong_Kong",
  "Asia/Taipei",
  "Asia/Singapore",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "UTC",
]

DEFAULT_TZ_INDEX = 0


def tz_name(index: int) -> str:
  if 0 <= index < len(TZ_LIST):
    return TZ_LIST[index]
  return TZ_LIST[DEFAULT_TZ_INDEX]


def tz_index(timezone: str) -> int:
  try:
    return TZ_LIST.index(timezone)
  except ValueError:
    return DEFAULT_TZ_INDEX


def get_timezone_from_params(params) -> str:
  v = params.get("Timezone")
  if v is None:
    return tz_name(DEFAULT_TZ_INDEX)
  try:
    idx = int(v)
    return tz_name(idx)
  except (ValueError, TypeError):
    if v in TZ_LIST:
      return v
    return tz_name(DEFAULT_TZ_INDEX)
