# openpilot 翻译指南

## 翻译系统架构

openpilot 使用基于 `.po`/`.mo` 文件的 GNU gettext 风格翻译系统。

```
翻译流程：
  源码中的字符串
    │  tr("text") / tr_noop("text")  标记
    ▼
  .pot 模板文件（翻译提取）
    │  xgettext / 手动同步
    ▼
  .po 翻译文件（人工编辑翻译）
    │  msgfmt 编译
    ▼
  .mo 二进制文件（运行时加载）
    │  multilang.py 解析
    ▼
  UI 渲染显示中文
```

## 文件结构

```
selfdrive/ui/translations/
├── app.pot                    # 主翻译模板（自动生成）
├── app_zh-CHS.po              # 简体中文主翻译
├── app_zh-CHS.mo              # 简体中文编译输出
├── app_zh-CHT.po              # 繁体中文主翻译
├── app_zh-CHT.mo              # 繁体中文编译输出
├── dragonpilot.pot            # dragonpilot 翻译模板
├── dragonpilot_zh-CHS.po      # dragonpilot 简体中文翻译
├── dragonpilot_zh-CHS.mo      # dragonpilot 简体编译输出
├── dragonpilot_zh-CHT.po      # dragonpilot 繁体中文翻译
├── dragonpilot_zh-CHT.mo      # dragonpilot 繁体编译输出
├── languages.json             # 语言列表配置
├── update_translations.py     # 翻译模板更新脚本
└── auto_translate.sh          # 自动翻译脚本
```

## 核心翻译函数

定义在 `system/ui/lib/multilang.py`：

| 函数 | 用途 | 示例 |
|------|------|------|
| `tr(text)` | 运行时翻译，在字典中查找并返回翻译 | `tr("Device")` → `"设备"` |
| `tr_noop(text)` | 标记字符串供提取工具扫描，运行时原样返回 | `tr_noop("Device")` → `"Device"` |
| `trn(singular, plural, n)` | 复数形式翻译 | `trn("{} minute ago", "{} minutes ago", n)` |

## 代码中如何使用翻译

### 方式一：直接使用 `tr()`

适用于按钮标签、对话框文本等动态显示的字符串：

```python
from openpilot.system.ui.lib.multilang import tr

button = Button(tr("Reboot"))
dialog = ConfirmDialog(tr("Are you sure you want to reboot?"))
```

### 方式二：`tr_noop()` + `tr()` 组合

适用于在文件顶部定义的常量，运行时再翻译：

```python
DESCRIPTIONS = {
  "key": tr_noop("Pair your device with comma connect"),
}

# 渲染时：
text = tr(DESCRIPTIONS["key"])
```

### 方式三：`lambda: tr(...)` 延迟求值

适用于语言切换时需要实时更新显示的文本：

```python
args = {
  "title": lambda: tr("Enable openpilot"),
  "description": lambda: tr("Allow openpilot to engage and control the vehicle."),
}
```

### 方式四：动态字符串（f-string）

注意：**不能**对整个 f-string 调用 `tr()`，因为动态内容会导致字典查找失败。应将静态部分拆出来单独翻译：

```python
# ❌ 错误：f-string 含动态值，无法命中翻译
tr(f"Calibrating: {perc:.0f}%")

# ✅ 正确：只翻译静态部分
f"{tr('Calibrating')}: {perc:.0f}%"
```

### 方式五：Alert 提醒（自动翻译）

`events.py` 中的 `Alert.__init__` 会自动对 `alert_text_1` 和 `alert_text_2` 调用 `tr()`，无需手动包裹：

```python
Alert(
  "Steer Assist Unavailable Below 10 mph",  # 自动翻译
  "Drive above 10 mph to engage",           # 自动翻译
  ...
)
```

## 离车提醒（offroad alerts）

`selfdrive/selfdrived/alerts_offroad.json` 中的文本存储在 Params 中，UI 代码需要主动调用 `tr()`：

```python
# BIG UI: selfdrive/ui/widgets/offroad_alerts.py (第 222 行)
text = tr(alert_json.get("text", "")).replace("%1", alert_json.get("extra", ""))

# MICI UI: selfdrive/ui/mici/layouts/offroad_alerts.py (第 290 行)
text = tr(alert_json.get("text", "")).replace("%1", alert_json.get("extra", ""))
```

## 如何添加新翻译

### 步骤 1：在 `.po` 文件中添加条目

打开对应的 `.po` 文件，添加：

```po
#: 源文件路径:行号
#, python-format
msgid "English text"
msgstr "中文翻译"
```

### 特殊格式说明

**包含 `%1` 占位符的字符串：**

```po
msgid "Device temperature too high. Current temperature: %1"
msgstr "设备温度过高。当前温度：%1"
```

**包含 `\n` 换行符的多行字符串：**

```po
msgid ""
"Unable to download updates\n"
"%1"
msgstr ""
"无法下载更新\n"
"%1"
```

**复数形式（nplurals=1 中文无需区分单复数）：**

```po
msgid "{} minute ago"
msgid_plural "{} minutes ago"
msgstr[0] "{} 分钟前"
```

### 步骤 2：编译 `.mo` 文件

```bash
cd selfdrive/ui/translations

# 简体中文
msgfmt app_zh-CHS.po -o app_zh-CHS.mo

# 繁体中文
msgfmt app_zh-CHT.po -o app_zh-CHT.mo

# dragonpilot
msgfmt dragonpilot_zh-CHS.po -o dragonpilot_zh-CHS.mo
msgfmt dragonpilot_zh-CHT.po -o dragonpilot_zh-CHT.mo
```

> 注意：如果 .po 文件中声明了 `nplurals=1`，则 `msgstr[0]` 和 `msgstr[1]` 会与声明冲突。
> 使用 `msgfmt`（不带 `-c` 参数）可以跳过严格检查正常编译。

### 步骤 3：重启 UI 或设备

编译后的 `.mo` 文件会在下一次 UI 启动时自动加载。

## 预翻译的字符串（无需额外处理）

以下场景中的字符串会被**自动翻译**，无需在代码中调用 `tr()`：

1. **Alert 构造函数中的文本** — `events.py` 中 `Alert.__init__` 自动对 `alert_text_1`/`alert_text_2` 调用 `tr()`
2. **`tr_noop()` 标记的常量** — 配合运行时 `tr()` 使用
3. **ListView 中 `lambda: tr(...)` 的 title/description** — ListItem 的 `_resolve_value()` 自动求值

## 需要手动添加 `tr()` 调用的位置

如果新增了包含用户可见文本的 JSON 数据源（如新的 `alerts_*.json`），需要在从 JSON 读取文本后手动调用 `tr()`。

## 翻译检查清单

- [ ] 源码中用户可见字符串用 `tr()`/`tr_noop()` 包裹
- [ ] `.po` 文件中有对应的 `msgid`/`msgstr`
- [ ] `msgid` 与源码中的字符串**完全一致**（大小写、空格、标点）
- [ ] 动态内容（数值、变量名）拆分到 f-string 外部
- [ ] `.mo` 文件已重新编译
- [ ] 繁简中文同步更新

## 常见问题

### Q: 翻译后 UI 仍然显示英文？

- 检查 `.mo` 文件是否已重新编译
- 检查 `msgid` 是否与源码字符串**精确匹配**（包括大小写）
- 检查 UI 代码中是否调用了 `tr()`

### Q: `msgfmt` 编译报错 "number of plural forms"？

- `.po` 文件第 2 行的 `nplurals` 声明为 `1`，但使用了 `msgstr[0]`/`msgstr[1]` 复数格式
- 解决方案：使用不带 `-c` 参数的 `msgfmt` 编译

### Q: 动态文本（如 "Calibrating: 45%"）无法翻译？

- 不要在 f-string 外套 `tr()`，应将 `tr()` 放在变量内部，只翻译静态文本部分

### Q: 新增的 JSON 文件文本显示英文？

- JSON 中的文本不会自动翻译，需要在读取后调用 `tr()`
