import os
import pyray as rl
from openpilot.system.ui.lib.application import gui_app, FontWeight, FONT_SCALE
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wrap_text import wrap_text
from openpilot.system.ui.widgets import Widget


class DeviceInfoWidget(Widget):
  def __init__(self):
    super().__init__()

  def _get_info_lines(self) -> list[tuple[str, str]]:
    """返回 (标题, 值) 列表"""
    lines = []

    # ── 设备信息 ──
    lines.append(("设备型号", ""))
    try:
      from openpilot.system.hardware.tici.hardware import get_device_type
      dt = get_device_type()
      model_map = {"tici": "C3", "tizi": "C3X", "mici": "C4"}
      model = model_map.get(dt, dt)
      lines.append(("· 设备", model))
      lines.append(("· 硬件", f"comma {dt}"))
    except Exception:
      lines.append(("· 设备", "PC"))

    # LITE 变体
    if os.getenv("LITE") is not None:
      lite_suffix = "XLite" if "TICI_TRES" in os.environ else "Lite"
      lines.append(("· 变体", lite_suffix))

    # ── 内部 Panda ──
    lines.append(("", ""))
    lines.append(("内部 Panda", ""))
    if "TICI_DOS" in os.environ:
      lines.append(("· MCU", "STM32F4 (DOS)"))
      lines.append(("· 通信", "SPI"))
      lines.append(("· 固件", "panda.bin.signed"))
    elif "TICI_TRES" in os.environ:
      lines.append(("· MCU", "STM32H7 (TRES)"))
      lines.append(("· 通信", "SPI"))
      lines.append(("· 固件", "panda_h7.bin.signed"))
    else:
      lines.append(("· 状态", "无内部 Panda"))

    # ── 外部 USB Panda ──
    lines.append(("", ""))
    lines.append(("外部 USB", ""))
    if "TICI_DOS" in os.environ:
      lines.append(("· 支持外接", "✅ 支持 (USB)"))
    elif "TICI_TRES" in os.environ or not os.environ.get("TICI_DOS"):
      # PC or C3X/C4 — both use the same pandad, no aux USB
      try:
        from openpilot.system.hardware import PC
        if PC:
          lines.append(("· 支持外接", "✅ 支持 (USB)"))
        else:
          lines.append(("· 支持外接", "❌ 不支持"))
      except Exception:
        lines.append(("· 支持外接", "✅ 支持 (USB)"))

    # ── 版本信息 ──
    lines.append(("", ""))
    lines.append(("版本信息", ""))
    lines.append(("· Branch", os.environ.get("GIT_BRANCH", "?")))
    lines.append(("· Commit", os.environ.get("GIT_COMMIT", "?")[:8]))
    lines.append(("· Dirty", "是" if os.environ.get("CLEAN") is None else "否"))

    return lines

  def _render(self, rect: rl.Rectangle):
    # 背景
    rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y, rect.width, rect.height), 0.03, 20, rl.Color(51, 51, 51, 255))

    x = rect.x + 48
    y = rect.y + 32
    w = rect.width - 96

    bold_font = gui_app.font(FontWeight.BOLD)
    normal_font = gui_app.font(FontWeight.NORMAL)
    small_font = gui_app.font(FontWeight.MEDIUM)

    # 标题
    rl.draw_text_ex(bold_font, tr("设备信息"), rl.Vector2(x, y), 72, 0, rl.WHITE)
    y += 100

    # 提示：点击顶部版本号关闭
    hint_font = gui_app.font(FontWeight.NORMAL)
    rl.draw_text_ex(hint_font, tr("点击顶部版本号关闭"), rl.Vector2(x, y), 28, 0, rl.Color(180, 180, 180, 255))
    y += 50

    lines = self._get_info_lines()

    for label, value in lines:
      if label == "" and value == "":
        y += 12
        continue

      if value == "":
        # 分类标题
        rl.draw_text_ex(bold_font, tr(label), rl.Vector2(x, y), 52, 0, rl.Color(120, 200, 255, 255))
        y += 60
      else:
        # 普通条目
        rl.draw_text_ex(normal_font, tr(label), rl.Vector2(x, y), 40, 0, rl.Color(200, 200, 200, 255))
        value_width = rl.measure_text_ex(small_font, value, 40).x
        rl.draw_text_ex(small_font, value, rl.Vector2(x + w - value_width, y), 40, 0, rl.WHITE)
        y += 48

      # 如果超出可视区域，停止
      if y > rect.y + rect.height - 40:
        break