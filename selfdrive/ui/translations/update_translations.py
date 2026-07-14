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
  """Collect bare string literals passed to Alert classes in events.py.

  Alert texts are plain string literals wrapped by the Alert base class at runtime
  (Alert.__init__ calls tr()), so they aren't caught by the tr()/trn() extractor and
  must be collected here explicitly.
  """
  entries = []
  seen = set()
  try:
    with open(py_path, encoding='utf-8') as f:
      tree = ast.parse(f.read())
    rel_path = os.path.relpath(py_path, BASEDIR)

    for node in ast.walk(tree):
      if not isinstance(node, ast.Call):
        continue
      name = None
      if isinstance(node.func, ast.Name):
        name = node.func.id
      elif isinstance(node.func, ast.Attribute):
        name = node.func.attr
      if name not in ALERT_CLASSES:
        continue
      for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value:
          if arg.value not in seen:
            seen.add(arg.value)
            entries.append(POEntry(
              msgid=arg.value,
              source_refs=[rel_path],
              flags=['python-format'],
            ))
  except (FileNotFoundError, SyntaxError):
    pass
  return entries


def update_translations():
  files = []
  # Scan the whole UI tree (system/ui and selfdrive/ui) so no interface strings are
  # missed, including the mici/ and body/ subdirectories. Skip tests and translations.
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

  # Extract offroad alert strings from alerts_offroad.json
  alerts_offroad_path = os.path.join(BASEDIR, "selfdrive", "selfdrived", "alerts_offroad.json")
  json_entries = extract_json_strings(alerts_offroad_path)

  # Extract onroad alert/event strings from events.py: both the bare string literals
  # passed to Alert classes and any explicit tr()/tr_noop() calls in that module.
  events_py = os.path.join(BASEDIR, "selfdrive", "selfdrived", "events.py")
  events_entries = extract_events_strings(events_py)
  events_entries += extract_strings(["selfdrive/selfdrived/events.py"], BASEDIR)

  # Merge entries, preferring Python entries for source refs
  entries_dict = {e.msgid: e for e in entries}
  for extra in json_entries + events_entries:
    if extra.msgid in entries_dict:
      if extra.source_refs[0] not in entries_dict[extra.msgid].source_refs:
        entries_dict[extra.msgid].source_refs.append(extra.source_refs[0])
    else:
      entries.append(extra)
      entries_dict[extra.msgid] = extra

  # Extract translatable strings and generate .pot template
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

  # Also update dragonpilot translations if available
  try:
    from dragonpilot.selfdrive.ui.update_translations import update_translations as update_dp_translations
    update_dp_translations()
  except ImportError:
    pass
