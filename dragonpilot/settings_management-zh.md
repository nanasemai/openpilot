# Dragonpilot 设置管理

## 问题

将功能分支合并到 `full` 分支时，`settings.py` 和 `params_keys.h` 中的冲突虽然是简单的（追加条目），但反复出现且需要手动解决。

**根本原因：** 这两个文件都是仅追加结构。多个分支向同一数组添加条目会导致每次功能合并时产生 git 合并冲突。

## 解决方案

每个功能分支拥有自己的 YAML 文件。生成器脚本扫描所有 YAML 文件并生成 `settings.py` 和 `params_keys.h`。

```
dragonpilot/settings/            # YAML 文件目录（每个功能分支一个）
  min-feat-lat-alka.yaml        # 来自 min-feat/lat/alka
  min-feat-ui-torque-bar.yaml   # 来自 min-feat/ui/torque-bar
  brands-toyota.yaml            # 来自 brands/toyota

generate_settings.py            # 生成器脚本
```

**注意：** 每个 YAML 文件以分支命名，可以包含**任意**区块（Lateral、Longitudinal、UI、Device 等）的设置。一个功能分支可能需要在多个区块中设置 — 全部定义在该分支的单个 YAML 文件中。

构建时，生成器扫描 `dragonpilot/settings/*.yaml` 并输出：
```
dragonpilot/settings.py        # 生成的文件
common/params_keys.h           # 生成的文件
```

## 为什么没有冲突

- 每个分支有自己的 YAML 文件
- Git 自动合并独立的文件没有问题
- 生成器读取**所有** YAML 并合并它们
- 没有两个分支编辑同一文件 = 没有冲突

## 架构

### core-feat/panel 分支

`core-feat/panel` 提供：
- `dragonpilot/settings/` 目录（占位，YAML 来自功能分支）
- `generate_settings.py` 脚本
- 带空区块结构的 `dragonpilot/settings.py`
- SConstruct 集成

### 功能分支

每个功能分支添加：
- `dragonpilot/settings/<feature>.yaml` — 该功能的设置
- 任何功能特定的代码

### Full 分支

将功能合并到 `full` 时：
1. YAML 文件自动合并（git 处理）
2. 构建运行生成器 → 生成 `settings.py` + `params_keys.h`
3. 设置无需手动解决冲突

## YAML 模式

单个 YAML 文件（以分支命名）可以在**任意数量**的区块中定义设置。

### 完整示例

```yaml
# min-feat-lat-alka.yaml — 每个分支一个 YAML，可以在多个区块中有条目

settings:
  # 横向设置
  - title: "Lateral"
    items:
      - key: dp_lat_alka
        type: toggle_item
        title: "Always-on Lane Keeping Assist (ALKA)"
        description: "Enable lateral control even when ACC/cruise is disengaged."
        brands: ["toyota", "hyundai", "honda"]

  # UI 设置（同一 YAML，不同区块）
  - title: "UI"
    condition: "not MICI"
    items:
      - key: dp_ui_rainbow
        type: toggle_item
        title: "Rainbow Driving Path"
        description: "Like Tesla's rainbow road."

  # 纵向设置
  - title: "Longitudinal"
    condition: "openpilotLongitudinalControl"
    items:
      - key: dp_lon_acm
        type: toggle_item
        title: "Adaptive Coasting Mode"
        description: "Reduce braking for smoother coasting."

params_keys:
  - key: dp_lat_alka
    flags: PERSISTENT
    type: BOOL
    default: "0"

  - key: dp_ui_rainbow
    flags: PERSISTENT
    type: BOOL
    default: "0"

  - key: dp_lon_acm
    flags: PERSISTENT
    type: BOOL
    default: "0"
```

### settings 区块

```yaml
settings:
  - title: "Section Name"
    condition: "brand == 'honda'"  # 可选，区块级条件
    items:
      - key: dp_something
        type: toggle_item
        title: "My Setting"
        description: "Description text"
        brands: ["toyota", "honda"]  # 可选，限制特定品牌
        condition: "LITE"  # 可选，条目级条件
        default: 0  # 用于 spin 条目
        min_val: 0  # 用于 spin 条目
        max_val: 100  # 用于 spin 条目
        step: 5  # 用于 spin 条目
        suffix: "mph"  # 用于 spin 条目
        special_value_text: "Off"  # 用于 spin 条目，min_val 的文本
        options: ["Option1", "Option2"]  # 用于 text_spin_button_item
        on_change:
          - target: dp_other_param
            action: set_enabled
            condition: "value > 0"
        initially_enabled_by:
          param: dp_other_param
          condition: "value > 0"
          default: 20
```

### params_keys 区块

```yaml
params_keys:
  - key: dp_something
    flags: PERSISTENT  # PERSISTENT, CLEAR_ON_MANAGER_START, CLEAR_ON_OFFROAD_TRANSITION 等
    type: BOOL  # BOOL, INT, FLOAT, STRING, JSON, BYTES, TIME
    default: "0"  # 默认值的字符串表示
```

注意：`params_keys` 条目不要求有对应的 `settings` 条目（用于没有 UI 的内部参数）。

## 条目类型

| 类型 | 描述 | 额外字段 |
|------|------|---------|
| `toggle_item` | 开/关切换 | `brands`, `condition` |
| `spin_button_item` | 整数微调器 | `default`, `min_val`, `max_val`, `step`, `suffix`, `special_value_text` |
| `double_spin_button_item` | 浮点数微调器 | 同 spin_button_item |
| `text_spin_button_item` | 下拉/文本选择器 | `default`, `options` |

## 条件

条件使用类 Python 语法：

| 条件 | 含义 |
|------|------|
| `brand == 'honda'` | 仅对本田品牌显示 |
| `brand == 'toyota'` | 仅对丰田品牌显示 |
| `LITE` | 仅 LITE 硬件上显示 |
| `not LITE` | 在 LITE 硬件上隐藏 |
| `not MICI` | 使用 MICI UI 时隐藏 |
| `openpilotLongitudinalControl` | 当 openpilot 控制纵向时 |

## on_change

用于根据当前值启用/禁用另一个设置：

```yaml
on_change:
  - target: dp_lat_lca_auto_sec
    action: set_enabled
    condition: "value > 0"
```

动作：`set_enabled`, `set_visible`, `set_value`

## initially_enabled_by

控制条目是否根据另一个参数的值初始为启用状态：

```yaml
initially_enabled_by:
  param: dp_lat_lca_speed
  condition: "value > 0"
  default: 20
```

## 生成器

扫描 `dragonpilot/settings/*.yaml`，合并所有条目，输出 `settings.py` 和 `params_keys.h`。

```bash
python generate_settings.py
```

## SConstruct 集成

生成器应在构建时自动运行：

```python
# 在 SConstruct 中
Command(
    target=['dragonpilot/settings.py', 'common/params_keys.h'],
    source=['generate_settings.py'] + Glob('dragonpilot/settings/*.yaml'),
    action='python generate_settings.py'
)
```

## 工作流

### 开发（功能分支）

1. 在 `dragonpilot/settings/<feature>.yaml` 中添加/编辑设置
2. 构建/测试 — SConstruct 自动运行生成器
3. 提交 YAML 文件 + 任何功能代码更改

### 创建 Full 分支

```bash
# 从 core-feat/panel 开始
git checkout core-feat/panel
git merge min-feat/lat/alka
git merge min-feat/ui/torque-bar
git merge brands/toyota
# ... 合并所有功能分支

# 正常解决代码冲突（YAML 文件自动合并）

# 构建 — 生成器通过 SConstruct 自动运行
scons
```

### 生成的文件

`settings.py` 和 `params_keys.h` 是**构建产物**：
- 不要手动编辑 — 更改会被覆盖
- 可选择不提交到 git — 构建时重新生成
- 或者提交它们，如果你希望无需重新构建即可获得可复现的构建

## 区块排序

生成器定义固定的区块顺序。每个 YAML 贡献到其区块：

```python
SECTION_ORDER = [
    "Toyota / Lexus",
    "VAG",
    "Mazda",
    "Lateral",
    "Longitudinal",
    "UI",
    "Device",
]
```

生成器扫描所有 YAML，按区块标题收集条目，按固定顺序输出。
