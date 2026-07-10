#!/usr/bin/env python3
import ast
import json
import os
from openpilot.common.basedir import BASEDIR
from openpilot.system.ui.lib.multilang import SYSTEM_UI_DIR, UI_DIR, TRANSLATIONS_DIR, multilang
from openpilot.selfdrive.ui.translations.potools import extract_strings, generate_pot, merge_po, init_po, POEntry

LANGUAGES_FILE = os.path.join(str(TRANSLATIONS_DIR), "languages.json")
POT_FILE = os.path.join(str(TRANSLATIONS_DIR), "app.pot")
MISSING_REPORT_FILE = os.path.join(str(TRANSLATIONS_DIR), "missing_translations.txt")


def extract_json_strings(json_path: str) -> list[POEntry]:
  entries = []
  try:
    with open(json_path, encoding='utf-8') as f:
      data = json.load(f)
    for key, value in data.items():
      if isinstance(value, dict) and 'text' in value:
        text = value['text']
        if isinstance(text, str) and text:
          entries.append(POEntry(
            msgid=text,
            source_refs=[os.path.relpath(json_path, BASEDIR)],
            flags=['python-format'],
          ))
  except (FileNotFoundError, json.JSONDecodeError):
    pass
  return entries


ALERT_CLASSES = {
  'Alert', 'NoEntryAlert', 'SoftDisableAlert', 'UserSoftDisableAlert',
  'ImmediateDisableAlert', 'EngagementAlert', 'NormalPermanentAlert', 'StartupAlert'
}


def extract_events_strings(py_path: str) -> list[POEntry]:
  entries = []
  seen = set()
  try:
    with open(py_path, encoding='utf-8') as f:
      content = f.read()

    tree = ast.parse(content)
    rel_path = os.path.relpath(py_path, BASEDIR)

    for node in ast.walk(tree):
      if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in ALERT_CLASSES:
          for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
              text = arg.value
              if text and text not in seen:
                seen.add(text)
                entries.append(POEntry(
                  msgid=text,
                  source_refs=[rel_path],
                  flags=['python-format'],
                ))
      elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in ALERT_CLASSES:
          for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
              text = arg.value
              if text and text not in seen:
                seen.add(text)
                entries.append(POEntry(
                  msgid=text,
                  source_refs=[rel_path],
                  flags=['python-format'],
                ))
  except (FileNotFoundError, SyntaxError):
    pass
  return entries


def update_translations():
  files = []
  # 扫描整个 UI 代码树（system/ui 与 selfdrive/ui），覆盖 sunnypilot、mici 等所有子目录，
  # 避免遗漏未被翻译提取的界面字符串。排除 tests 与 translations 目录。
  for base_dir in (SYSTEM_UI_DIR, str(UI_DIR)):
    for root, _, filenames in os.walk(base_dir):
      if os.sep + "tests" in root or os.sep + "translations" in root:
        continue
      for filename in filenames:
        if filename.endswith(".py"):
          rel_path = os.path.relpath(os.path.join(root, filename), BASEDIR)
          if rel_path.startswith("openpilot/"):
            rel_path = rel_path[len("openpilot/"):]
          files.append(rel_path)

  # Extract translatable strings from Python files
  entries = extract_strings(files, BASEDIR)

  # Extract translatable strings from alerts_offroad.json
  alerts_offroad_path = os.path.join(BASEDIR, "selfdrive", "selfdrived", "alerts_offroad.json")
  json_entries = extract_json_strings(alerts_offroad_path)

  # Extract translatable strings from all events.py / events_base.py files.
  # Alert texts are bare string literals wrapped by the Alert base class at runtime
  # (events_base.Alert.__init__ calls tr()), so they must be collected here explicitly.
  # NOTE: sunnypilot/selfdrive/selfdrived/events.py holds fork-specific alerts (e.g. lane
  # turn / speed limit alerts) and was previously missed, leaving those strings untranslated.
  event_sources = [
    os.path.join(BASEDIR, "selfdrive", "selfdrived", "events.py"),
    os.path.join(BASEDIR, "sunnypilot", "selfdrive", "selfdrived", "events.py"),
    os.path.join(BASEDIR, "sunnypilot", "selfdrive", "selfdrived", "events_base.py"),
  ]
  events_entries = []
  for path in event_sources:
    if os.path.exists(path):
      events_entries.extend(extract_events_strings(path))

  # Merge entries, prefer Python entries for source refs
  entries_dict = {e.msgid: e for e in entries}
  for je in json_entries + events_entries:
    if je.msgid in entries_dict:
      if je.source_refs[0] not in entries_dict[je.msgid].source_refs:
        entries_dict[je.msgid].source_refs.append(je.source_refs[0])
    else:
      entries.append(je)

  # Generate .pot template
  generate_pot(entries, POT_FILE)

  # Generate/update translation files for each language
  for name in multilang.languages.values():
    po_file = os.path.join(TRANSLATIONS_DIR, f"app_{name}.po")
    if os.path.exists(po_file):
      merge_po(po_file, POT_FILE)
    else:
      init_po(POT_FILE, po_file, name)


def _po_missing(po_file: str) -> list[POEntry]:
  """Return entries in a .po file that have no translation yet (empty msgstr)."""
  from openpilot.selfdrive.ui.translations.potools import parse_po
  _, entries = parse_po(po_file)
  missing = []
  for e in entries:
    if e.is_plural:
      if not any(e.msgstr_plural.values()):
        missing.append(e)
    elif not e.msgstr:
      missing.append(e)
  return missing


def generate_missing_report(report_path: str = MISSING_REPORT_FILE) -> int:
  """Write a human-readable report of untranslated strings per language.

  Compares each app_<lang>.po against its own entries and lists every msgid whose
  translation is still empty. Makes it easy to spot what is missing after running
  update_translations(). Returns the total number of missing entries across languages.
  """
  lines = []
  total = 0
  for name in sorted(multilang.languages.values()):
    po_file = os.path.join(TRANSLATIONS_DIR, f"app_{name}.po")
    if not os.path.exists(po_file):
      continue
    missing = _po_missing(po_file)
    total += len(missing)
    lines.append(f"===== {name}: {len(missing)} missing =====")
    for e in missing:
      ref = e.source_refs[0] if e.source_refs else "?"
      msgid = e.msgid.replace("\n", "\\n")
      lines.append(f"  [{ref}] {msgid!r}")
    lines.append("")

  header = f"# Missing translations report — {total} total across all languages\n\n"
  with open(report_path, "w", encoding="utf-8") as f:
    f.write(header + "\n".join(lines) + "\n")
  print(f"Missing translations report written to {report_path} ({total} total)")
  return total


if __name__ == "__main__":
  import argparse
  parser = argparse.ArgumentParser(description="Update .po translation files and/or report missing strings")
  parser.add_argument("--report", action="store_true",
                      help="only generate the missing-translations report, without updating .po files")
  args = parser.parse_args()

  if not args.report:
    update_translations()
  generate_missing_report()
