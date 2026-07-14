# 加速度均衡器（Acceleration EQ）

用户可调的纵向加速度功能。驾驶员通过 dashy 网页 UI 编辑 EQ 风格的**速度→最大加速度**曲线，这些曲线按命名的**配置文件**分组；纵向规划器读取当前激活的配置文件，将其曲线作为加速度上限。配套的**记录器**记录驾驶员自身的加速度（当他们控制油门时），以便 UI 后续显示"你实际在哪里加速"。

dashy 网页 UI 位于**独立的仓库**中；本文档涵盖 dragonpilot/规划器端（数据契约、规划器读取器、记录器）并总结其集成的 dashy 端。

---

## 架构

```
┌─ dashy 网页 UI（独立仓库）──┐  GET/POST   ┌─ serverd ────────────────┐
│ EQ 编辑器 · 配置文件 ·      │ ──────────► │ params REST API +        │
│ personality→profile 关联    │  /api/...    │ /api/accel_eq/config     │
└─────────────────────────────┘             └─────────┬────────────────┘
                                                        │ Params
                            dp_lon_accel_profiles（JSON 参数）
                                                        │
          ┌─ longitudinal_planner.py ────────────────────▼───────────────────┐
          │ AccelEq (accel_eq.py): 读取+缓存 JSON (mtime 门控), 解析        │
          │   根据 personality/active 激活配置文件 → max_accel(v)            │
          │ AccelLogger (accel_logger.py): 记录干净的驾驶员加速度样本       │
          │   → /data/media/0/realdata/accel_log.csv                        │
          └──────────────────────────────────────────────────────────────────┘
```

两个存储方向相反：

| 存储 | 内容 | 写入者 | 读取者 |
|------|------|--------|--------|
| `dp_lon_accel_profiles`（JSON 参数） | 整个 EQ 文档 — 配置文件+曲线、手动 `active` 选择、personality 关联 | dashy | 规划器 |
| `/data/media/0/realdata/accel_log.csv` | 驾驶员自然加速度样本（`vEgo,aEgo`） | **规划器**（AccelLogger）| dashy 叠加层（未来） |

该参数在 `dragonpilot/settings/min-feat.lon.accel-eq.py` 中声明（构建时生成到 `common/params_keys.h`）。CSV 是遥测数据而非配置，因此存储在行车记录分区，而非参数存储中。

---

## 数据契约 — `dp_lon_accel_profiles`

权威格式由 dashy 的 `serializeDoc` 写入，规划器读取。示例：

```json
{
  "active": "Sport",
  "use_personality": false,
  "personality_map": { "0": "Sport", "1": "Stock", "2": "Eco" },
  "profiles": [
    { "name": "Stock", "max": {"bp": [0, 10, 25, 40], "v": [1.6, 1.2, 0.8, 0.6]} },
    { "name": "Eco", "source": "Stock", "max": {"bp": [0, 12, 30, 40], "v": [1.0, 0.8, 0.6, 0.5]} }
  ]
}
```

- **`profiles`** — 有序列表。每个都有非空的**唯一** `name` 和一个 `max` 曲线 `{bp:[m/s…], v:[m/s²…]}`。速度（`bp`）以 **m/s** 存储，与 UI 显示单位无关。`max` 缺失/无效 → 该配置文件使用 Stock。
- **`active`** — 手动选择的配置文件名称（当 `use_personality` 关闭时使用）。**没有单独的 `active` 参数** — 它存在于本文档中。
- **`use_personality`** + **`personality_map`** — personality 关联（见下文）。
- **`source`**（可选）— 仅 UI 谱系（从哪个配置文件复制而来，绘制为灰色参考线）。规划器忽略它及任何其他未知键。

> **"Stock"** 是 UI 保护的基线（不可重命名/删除，在编辑器中只读）。规划器将其视为**注入的 stock 表的实时镜像** — 它忽略任何名为 "Stock" 的已存储曲线，因此规划器的 stock 变更始终优先。

**无 `version` 字段和无转弯限制曲线**：schema 变更通过版本化发布版（或者，如果不兼容，则更改参数键）来处理；转弯加速度限制是规划器的 stock `_A_TOTAL_MAX_*`，不可调。

---

## 配置文件选择

在初始化、参数 mtime 变更以及 personality 变更时解析。规则：

```
读取/缓存 JSON 文档
  文档无效 / 空 / 缺失              → STOCK（无论 personality 如何）
  文档有效：
    use_personality == true          → personality_map[personality]
    use_personality == false         → active
    → 将名称解析为配置文件（精确匹配）并验证其曲线
       匹配且有效                      → 该配置文件的曲线
       未映射 / 未设置 / 无匹配 / Stock / 无效曲线 → STOCK
```

**Stock 是唯一的通用回退。** 没有"第一个配置文件"回退，并且当 `use_personality` 开启时，未映射的 personality 回退到 Stock（而非手动的 `active`）。

| `use_personality` | 情况 | 结果 |
|-------------------|------|------|
| true | personality 已映射 → 真实配置文件，有效曲线 | 该配置文件 |
| true | personality 未映射 | **Stock** |
| false | `active` → 真实配置文件，有效曲线 | 该配置文件 |
| false | `active` 未设置/空 | **Stock** |
| 任一 | 名称指向不存在的配置文件 / 是 "Stock" / 曲线无效 | **Stock** |
| 任一 | 文档缺失 / 空 / 无法解析 / 不是可用字典 | **Stock** |

### Personality 关联

驾驶员为每个 openpilot personality 关联一个配置文件，存储在 `personality_map` 中，键为 `LongitudinalPersonality` 枚举整数 — **`"0"` 激进，`"1"` 标准，`"2"` 从容**。开启 `use_personality` 时，现有的**人格按钮**选择配置文件（无需新的行车中控件）。

规划器从 `selfdriveState.personality.raw`（整数）读取实时 personality — 与 MPC 使用的来源相同 — 而非从参数读取。

> **刻意耦合：** `LongitudinalPersonality` 也驱动 openpilot 的跟车距离，因此 personality 关联使按钮成为一个单一的"激进程度"旋钮（加速感觉 + 跟车一起调节）。关闭关联可独立设置它们（手动 `active`）。

---

## 规划器：`AccelEq`（`dragonpilot/selfdrive/controls/lib/accel_eq.py`）

在 `LongitudinalPlanner` 中实例化，纯观察安全 — 任何失败回退到 stock，不会向规划层抛出异常。

- **Stock 是注入的**，非硬编码：规划器拥有规范的 `A_CRUISE_MAX_*` 表并将其传入（`AccelEq(A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)`）。这保持了单一事实来源，并使 `accel_eq` 保持为叶子模块（它从不导入规划器 — 那会形成循环依赖）。
- **读取是 mtime 门控的；解析后的文档被缓存。** `maybe_refresh(personality)` 每帧对参数执行 `stat()`；**仅 mtime 变更**触发重新读取（`_reload_doc` → `Params.get`）。**personality 变更**仅重新解析缓存的文档（`_resolve`）— 零 I/O。
- **`max_accel(v_ego)`** = 在激活曲线上进行 `np.interp` 插值，提供给规划器的加速度裁剪。默认 personality 是一个 `-1` 哨兵值，因此第一次真实的 `maybe_refresh` 始终能解析。

`limit_accel_in_turns` 保持 stock 不变（使用 `_A_TOTAL_MAX_*`）。

### 验证是安全边界 — `_validate_curve`

参数是外部可写的（手动编辑、脚本、旧版/有 bug 的 dashy），因此规划器从不信任它。`_validate_curve` 在每条曲线影响加速度上限之前重新排序和限制边界：

- 形状：包含等长 `bp`/`v` 列表的字典，`MIN_PTS(2) ≤ n ≤ MAX_PTS(12)`，所有数值为有限数；
- **排序**按速度排序键值对（必须 — `np.interp` 需要递增的 `bp`）；
- 速度钳制到 `[0, SPEED_CEIL(60)]`；如果任何相邻间隔 `< MIN_GAP(0.5)` 则拒绝；
- **值钳制到 `[0, MAX_ACCEL_CEIL]`**（`= ACCEL_MAX`，2.0 m/s²）— 实际的加速度上限。

任何失败 → 该曲线不可用 → stock。dashy 在客户端镜像这些精确规则（UX），因此编辑器无法创建规划器拒绝的曲线；规划器的副本是保证。

---

## 记录器：`AccelLogger`（`dragonpilot/selfdrive/controls/lib/accel_logger.py`）

记录驾驶员的**自然**加速度，使数据反映*他们的*偏好，而非 openpilot 的。仅保留"干净的自由人类加速"样本 — `_should_log` 要求**全部**满足：

| 条件 | 信号 |
|------|------|
| op 纵向未激活（人类控制油门） | `controlsState.longControlState == off` |
| 踩油门加速 | `gasPressed and aEgo > 0` |
| 未刹车 | `not brakePressed` |
| 无转向灯（未转弯/变道） | `not (leftBlinker or rightBlinker)` |
| 处于前进挡 | `gearShifter == drive` |
| 行驶中（非蠕行/停止） | `not standstill and vEgo > 1.0` |
| 无近距离前车 | 无前车，或 `dRel / max(vEgo, 0.1) > 2.0 s` |
| 直线行驶（非弯道） | 横向加速度 `< 1.0 m/s²` |

行为：将匹配的 `(vEgo, aEgo)` 缓冲在 RAM 中，**每分钟追加到 CSV**（`FLUSH_DT`，按帧计数）— 每分钟写入一次保护闪存；硬关机时最多丢失约 1 分钟的样本（对于聚合数据可忽略不计）。完全异常隔离；写入失败时丢弃缓冲行并空操作（例如开发中路径不可写）。干净的样本门控使增长缓慢，因此没有大小上限。CSV 列：`vEgo,aEgo`（m/s，m/s²）。

---

## 常量 — 单一事实来源

`accel_eq.py` 拥有契约常量（`SPEED_CEIL`、`MIN_GAP`、`MIN_PTS`、`MAX_PTS`、`MAX_ACCEL_CEIL`）。serverd 在 `GET /api/accel_eq/config` 提供它们，dashy 模型在加载时将其应用于内置回退默认值之上，因此编辑器的限制不会偏离规划器。（`MAX_PTS` 尤其必须匹配：超出规划器上限的曲线会被静默拒绝 → stock。）

---

## 持久化往返

dashy 将文档序列化为 **JSON 字符串**；规划器读取解析后的**字典**。serverd 桥接它们：

1. dashy `POST /api/settings/params/dp_lon_accel_profiles` 携带 JSON 字符串。
2. serverd `_save_param` 检测 JSON 类型参数并对字符串执行 `json.loads`，然后 `Params.put(key, dict)`（`(dict, JSON)` 转换器存储它）。格式错误的 JSON → **400**，而非 500。
3. 规划器 `Params.get(...)` → 解析后的字典 → `AccelEq._reload_doc` 缓存。

`dp_lon_accel_profiles` 在 serverd 的 `_param_allowed` 白名单中。

---

## Dashy 端（独立仓库）

网页 UI 实现：画布 **EQ 编辑器**（拖拽点、添加/删除、数值输入、重置、撤销/重做、实时的"你在这里"速度标记）、**配置文件管理**（创建/复制/重命名/删除、快速切换）、**personality→profile 选择器**，以及客户端**`_validate_curve` 的镜像**，以便编辑器强制执行规划器的限制。它与 serverd 的 params REST API 和 `/api/accel_eq/config` 通信。显示单位跟随 `IsMetric`；存储始终为 m/s。

---

## 文件（本仓库）

| 文件 | 角色 |
|------|------|
| `dragonpilot/selfdrive/controls/lib/accel_eq.py` | `AccelEq` — 配置文件读取器/解析器 |
| `dragonpilot/selfdrive/controls/lib/accel_logger.py` | `AccelLogger` — 加速度 CSV 记录器 |
| `dragonpilot/selfdrive/controls/lib/tests/test_accel_eq.py` | AccelEq 测试 |
| `dragonpilot/selfdrive/controls/lib/tests/test_accel_logger.py` | AccelLogger 测试 |
| `dragonpilot/settings/min-feat.lon.accel-eq.py` | 声明 `dp_lon_accel_profiles` |
| `selfdrive/controls/lib/longitudinal_planner.py` | 拥有 `A_CRUISE_MAX_*`，接入 `AccelEq` + `AccelLogger` |

运行测试：`uv run python -m pytest dragonpilot/selfdrive/controls/lib/tests/ -q`

---

## 备注 / 未来

- **Dashy 中的习惯叠加层** — 读取 `accel_log.csv`（服务端聚合到第 85 百分位带）并在 EQ 曲线背后绘制。无需新参数。
- **转弯限制通道**有意不可调（已从 UI 和规划器中移除；转弯限制保持 stock）。
- Dashy 后续需与此端保持同步：将 serverd 的 `ACCEL_EQ_CONFIG` 裁剪为 `accel_eq` 仍然暴露的常量，并在 dashy 模型中镜像 Stock 回退选择规则。
