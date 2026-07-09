#!/usr/bin/env python3
import ast
import json
import os
from openpilot.common.basedir import BASEDIR
from openpilot.system.ui.lib.multilang import SYSTEM_UI_DIR, UI_DIR, TRANSLATIONS_DIR, multilang
from openpilot.selfdrive.ui.translations.potools import extract_strings, generate_pot, merge_po, init_po, POEntry

LANGUAGES_FILE = os.path.join(str(TRANSLATIONS_DIR), "languages.json")
POT_FILE = os.path.join(str(TRANSLATIONS_DIR), "app.pot")


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

  # Extract translatable strings from events.py
  events_path = os.path.join(BASEDIR, "selfdrive", "selfdrived", "events.py")
  events_entries = extract_events_strings(events_path)

  # Extract translatable strings from events_base.py
  events_base_path = os.path.join(BASEDIR, "openpilot", "sunnypilot", "selfdrive", "selfdrived", "events_base.py")
  events_base_entries = extract_events_strings(events_base_path)

  # Merge entries, prefer Python entries for source refs
  entries_dict = {e.msgid: e for e in entries}
  for je in json_entries + events_entries + events_base_entries:
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


if __name__ == "__main__":
  update_translations()
