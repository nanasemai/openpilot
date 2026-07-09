import pyray as rl
import re
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.application import font_fallback

def _is_cjk(char):
  return '\u4e00' <= char <= '\u9fff'

def _split_cjk(text):
  parts = []
  current = []
  for char in text:
    if _is_cjk(char):
      if current:
        parts.append(''.join(current))
        current = []
      parts.append(char)
    else:
      current.append(char)
  if current:
    parts.append(''.join(current))
  return parts


def _break_long_word(font: rl.Font, word: str, font_size: int, max_width: int, spacing: float = 0) -> list[str]:
  if not word:
    return []

  parts = []
  remaining = word

  while remaining:
    if measure_text_cached(font, remaining, font_size, spacing).x <= max_width:
      parts.append(remaining)
      break

    # Binary search for the longest substring that fits
    left, right = 1, len(remaining)
    best_fit = 1

    while left <= right:
      mid = (left + right) // 2
      substring = remaining[:mid]
      width = measure_text_cached(font, substring, font_size, spacing).x

      if width <= max_width:
        best_fit = mid
        left = mid + 1
      else:
        right = mid - 1

    # Add the part that fits
    parts.append(remaining[:best_fit])
    remaining = remaining[best_fit:]

  return parts


_cache: dict[int, list[str]] = {}


def wrap_text(font: rl.Font, text: str, font_size: int, max_width: int, spacing: float = 0) -> list[str]:
  font = font_fallback(font)
  spacing = round(spacing, 4)
  key = hash((font.texture.id, text, font_size, max_width, spacing))
  if key in _cache:
    return _cache[key]

  if not text or max_width <= 0:
    return []

  paragraphs = text.split('\n')
  all_lines: list[str] = []

  for paragraph in paragraphs:
    if not paragraph.strip():
      all_lines.append("")
      continue

    has_cjk = any(_is_cjk(c) for c in paragraph)
    if has_cjk:
      tokens = _split_cjk(paragraph)
    else:
      tokens = paragraph.split()

    if not tokens:
      all_lines.append("")
      continue

    lines: list[str] = []
    current_line: list[str] = []

    for token in tokens:
      token_width = measure_text_cached(font, token, font_size, spacing).x

      if token_width > max_width:
        if current_line:
          lines.append("".join(current_line))
          current_line = []
        lines.extend(_break_long_word(font, token, font_size, max_width, spacing))
        continue

      join_char = "" if has_cjk else " "
      test_line = join_char.join(current_line + [token]) if current_line else token
      test_width = measure_text_cached(font, test_line, font_size, spacing).x

      if test_width <= max_width:
        current_line.append(token)
      else:
        if current_line:
          lines.append(join_char.join(current_line))
        current_line = [token]

    if current_line:
      lines.append(join_char.join(current_line))

    all_lines.extend(lines)

  _cache[key] = all_lines
  return all_lines
