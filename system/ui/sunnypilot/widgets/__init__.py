"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""


from openpilot.system.ui.lib.multilang import tr

def get_highlighted_description(params, param_name: str, descriptions: list[str]) -> str:
  index = int(params.get(param_name, return_default=True))
  lines = []
  for i, desc in enumerate(descriptions):
    if i == index:
      lines.append(f"<b>{tr(desc)}</b>")
    else:
      lines.append(f"{tr(desc)}")

  return "<br>".join(lines)
