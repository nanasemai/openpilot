# MADS 模块化辅助驾驶系统深度分析

> 本文档基于 sunnypilot 分支源码分析，聚焦 MADS (Modular Assistive Driving System) 的核心设计、状态流转、事件处理机制及其子功能 UEM (Unified Engagement Mode)。

---

## 目录

1. [概述](#1-概述)
2. [架构总览](#2-架构总览)
3. [状态机详解](#3-状态机详解)
4. [事件处理机制](#4-事件处理机制)
5. [安全层实现](#5-安全层实现)
6. [Unified Engagement Mode (UEM)](#6-unified-engagement-mode-uem)
7. [MadsMainCruiseAllowed](#7-madsmaincruiseallowed)
8. [Steering Mode on Brake](#8-steering-mode-on-brake)
9. [UI 状态显示](#9-ui-状态显示)
10. [横向激活决策链路](#10-横向激活决策链路)
11. [平台限制与兼容性](#11-平台限制与兼容性)
12. [附录：参数清单](#12-附录参数清单)

---

## 1. 概述

### 1.1 什么是 MADS

MADS (Modular Assistive Driving System) 是 sunnypilot 分支引入的**模块化辅助驾驶系统**，其核心设计理念是：

> **将横向控制（转向）与纵向控制（油门/刹车）解耦，使两者可以独立启用或关闭。**

在 stock openpilot 中，横向控制（车道居中 ALC）只能跟随系统整体启用/关闭——要么全开，要么全关。MADS 打破了这一限制，允许用户：
- 仅启用横向控制（方向盘由 openpilot 控制），纵向由驾驶员手动操作 → **全时横向控制**
- 仅启用纵向控制（ACC 自适应巡航），横向由驾驶员手动操作
- 横向+纵向同时启用（完整辅助驾驶）

### 1.2 解决的问题

| 场景 | Stock openpilot | MADS |
|------|:---:|:---:|
| 只想让车自己转弯，自己控制油门刹车 | ❌ 不可能 | ✅ `lat_only` 模式 |
| 遇到复杂路况想暂时关闭横向，但保持 ACC | ❌ 必须全关 | ✅ `long_only` 模式 |
| 等红灯时自动暂停横向，绿灯自动恢复 | ❌ 需要手动 | ✅ `paused` 状态 |
| 踩刹车时空横向表现 | ❌ 只能全退 | ✅ 可选保持/暂停/断开 |

---

## 2. 架构总览

### 2.1 文件结构

```
sunnypilot/
├── mads/
│   ├── mads.py          # MADS 主类：事件处理、参数读取、状态协调
│   ├── state.py         # 状态机：5 种状态的管理与转换
│   └── helpers.py       # 辅助函数：参数读取、标志位设置
│
selfdrive/
├── selfdrived/
│   └── selfdrived.py    # 集成 MADS：创建实例、发布 selfdriveStateSP
│
├── ui/sunnypilot/
│   ├── ui_state.py      # UI 状态计算（engaged/lat_only/long_only）
│   └── layouts/settings/steering_sub_layouts/
│       └── mads_settings.py  # UI 设置页面
│
opendbc/safety/sunnypilot/
├── mads_declarations.h  # MADS 安全层数据结构声明
└── mads.h               # MADS 安全层实现（panda 固件）
```

### 2.2 核心数据流

```
用户操作 (LKAS按钮/MAIN巡航/SET-/+ 按键/刹车踏板)
    │
    ▼
MADS.update_events(CS)      ← 处理 CAN 事件，替换/移除/添加事件
    │
    ▼
MADS.state_machine.update() ← 执行状态转换 (disabled/enabled/paused/...)
    │
    ├──▶ selfdriveStateSP.mads 发布到消息总线
    │
    ▼
controlsd_ext.get_lat_active()  ← 读取 mads.active 决定横向是否激活
    │
    ▼
LatControl.update()          ← 实际计算并输出转向扭矩
    │
    ▼
panda 安全层                 ← 校验 controls_allowed_lateral
    │
    ▼
CAN bus → 车辆执行
```

---

## 3. 状态机详解

MADS 状态机实现在 [state.py](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/state.py)，管理 5 种状态。

### 3.1 状态定义

```python
# cereal/custom.capnp 中定义
enum ModularAssistiveDrivingSystemState {
  disabled @0;         # 已禁用
  enabled @1;          # 已启用（横向控制就绪）
  softDisabling @2;    # 软禁用中（检测到问题，倒计时退出）
  paused @3;           # 已暂停（遇到门开/安全带/刹车等，条件恢复）
  overriding @4;       # 驾驶员正在干预转向
}
```

### 3.2 两个重要分组

```python
ACTIVE_STATES  = (enabled, softDisabling, overriding)  # 横向正在输出
ENABLED_STATES = (paused, *ACTIVE_STATES)               # MADS 处于"开"的状态
```

- `enabled`：MADS 开启且横向有控制权
- `active`：横向实际在输出扭矩的子集（排除 paused）
- `paused`：MADS 仍算 enabled，但横向暂停输出

### 3.3 状态转换图

```
                    ┌─────────────────────────────────────┐
                    │              DISABLED                │
                    └──┬────────────────────────────▲──────┘
                       │ ENABLE                      │ USER_DISABLE
                       │ (且无 NO_ENTRY)             │ (非静默)
                    ┌──▼─────────────────────────────┴──────┐
                    │              ENABLED                   │
                    └──┬──────────┬──────────┬──────────▲───┘
          SOFT_DISABLE │          │          │          │
                       │          │          │ 条件恢复  │
                    ┌──▼──┐  ┌────▼───┐  ┌───┴────┐    │
                    │soft │  │over-   │  │ PAUSED │    │
                    │Dis- │  │riding  │  │        │────┘
                    │able │  │        │  │  ENABLE│
                    └──┬──┘  └────▲───┘  └────────┘
                       │          │
             超时 /    │  OVERRIDE│
             条件消失   │_LATERAL  │
                       │          │
                    ┌──▼──────────┴──────┐
                    │     DISABLED        │
                    └────────────────────┘
```

#### 状态转换详细规则（[state.py#L45-L134](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/state.py#L45)）：

| 当前状态 | 触发事件 | 下一状态 | 说明 |
|---------|---------|---------|------|
| **任何非 disabled** | `USER_DISABLE` + `silentLkasDisable` | **paused** | 静默禁用 → 暂停（可恢复） |
| **任何非 disabled** | `USER_DISABLE` (非静默) | **disabled** | 用户主动关闭 |
| **任何非 disabled** | `IMMEDIATE_DISABLE` | **disabled** | 紧急禁用 |
| **enabled** | `SOFT_DISABLE` | **softDisabling** | 启动软禁用倒计时 |
| **enabled** | `OVERRIDE_LATERAL` | **overriding** | 驾驶员接管转向 |
| **softDisabling** | 倒计时 > 0 | **softDisabling** | 继续倒计时 |
| **softDisabling** | 倒计时 ≤ 0 | **disabled** | 超时，完全退出 |
| **softDisabling** | SOFT_DISABLE 条件消失 | **enabled** | 恢复正常 |
| **paused** | `ENABLE` + 无 `NO_ENTRY` | **enabled / overriding** | 恢复横向 |
| **overriding** | `SOFT_DISABLE` | **softDisabling** | 干预中检测到问题 |
| **overriding** | OVERRIDE_LATERAL 条件消失 | **enabled** | 干预结束 |
| **disabled** | `ENABLE` + 无 `NO_ENTRY` | **enabled / overriding** | 正常启用 |
| **disabled** | `ENABLE` + 有 `NO_ENTRY` + 齿轮允许 | **paused** | 条件不满足→暂停 |

---

## 4. 事件处理机制

MADS 的事件处理在 [mads.py#L119-L208](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/mads.py#L119) 的 `update_events()` 方法中。

### 4.1 事件替换机制

当 MADS enabled 且 openpilot 整体未 enabled 时，MADS 会"吞掉"某些本该触发退出的事件，替换为静默版本，使得横向控制可以继续保持：

| 原始事件 | 替换事件 | 触发条件 |
|---------|---------|---------|
| `doorOpen` | `silentDoorOpen` | 停车时 |
| `seatbeltNotLatched` | `silentSeatbeltNotLatched` | 停车时 |
| `wrongGear` | `silentWrongGear` | 车速 < 2.5 m/s 或 R 档 |
| `reverseGear` | `silentReverseGear` | 任何时候 |
| `brakeHold` | `silentBrakeHold` | 任何时候 |
| `parkBrake` | `silentParkBrake` | 任何时候 |
| `wrongCarMode` | `wrongCarModeAlertOnly` | 有巡航按键事件时（仅告警不阻断） |

同时，以下事件被**直接移除**（不产生任何影响）：
- `preEnableStandstill`
- `belowEngageSpeed`
- `speedTooLow`
- `cruiseDisabled`
- `manualRestart`
- `espActive`
- `pcmDisable`
- `buttonCancel`
- `pedalPressed`
- `wrongCruiseMode`

### 4.2 事件的生命周期

```
CAN 消息到达
    ↓
openpilot 事件系统产生 EventName (如 doorOpen)
    ↓
MADS.update_events() 判断：
    ├── MADS 未启用 → 事件保持原样 → 正常触发退出
    │
    └── MADS 已启用 + openpilot.enabled=false
        ├── 替换为 silent 事件 → MADS 进入 paused 而非 disabled
        └── 移除事件 → 完全忽略
            ↓
MADS.state_machine.update() 根据处理后的事件集合做状态转换
```

### 4.3 LKAS 按钮处理

LKAS 按钮是 MADS 的核心交互方式（[mads.py#L174-L181](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/mads.py#L174)）：

```python
if be.type == ButtonType.lkas and be.pressed and (CS.cruiseState.available or self.allow_always):
    if self.enabled:
        if self.selfdrive.enabled:
            self.events_sp.add(EventNameSP.manualSteeringRequired)  # 全开→需要手动接管转向
        else:
            self.events_sp.add(EventNameSP.lkasDisable)             # MADS 开但系统关→关 MADS
    else:
        self.events_sp.add(EventNameSP.lkasEnable)                  # MADS 关→开 MADS
```

**行为总结**：

| 当前 MADS | 当前 openpilot | 按 LKAS 结果 |
|:------:|:-----------:|------------|
| ✗ | ✗ | MADS 开启 → **lat_only** |
| ✓ | ✗ | MADS 关闭 → **disengaged** |
| ✓ | ✓ | 发出告警：请手动接管转向 |
| ✗ | ✓ | MADS 开启 → **engaged** |

---

## 5. 安全层实现

MADS 安全层实现在 panda 固件层面（C 代码），通过 `alternative_experience` 标志位下发配置。

### 5.1 核心变量

```c
// mads.h（全局变量）
bool controls_allowed_lateral;        // 独立于 controls_allowed 的横向控制许可
bool heartbeat_engaged_mads;          // MADS 心跳（通过 USB 命令传入）
```

### 5.2 Alternative Experience 标志位

```c
// mads_declarations.h
#define ALT_EXP_ENABLE_MADS                   1024  // 启用 MADS
#define ALT_EXP_MADS_DISENGAGE_LATERAL_ON_BRAKE 2048  // 踩刹车断开横向
#define ALT_EXP_MADS_PAUSE_LATERAL_ON_BRAKE   4096  // 踩刹车暂停横向
```

### 5.3 控制状态更新逻辑

[mads.h#L83-L134](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/opendbc_repo/opendbc/safety/sunnypilot/mads.h#L83) 的 `m_update_control_state()` 函数：

```
m_update_control_state()
    │
    ├── 检查 ACC MAIN 下降沿 → mads_exit_controls()
    ├── 检查 steering_disengage 上升沿 → mads_exit_controls()
    ├── 检查 disengage_on_brake + 刹车上升沿 → mads_exit_controls()
    ├── 检查 pause_on_brake + 刹车上升沿 → mads_exit_controls()（但刹车释放后可恢复）
    │
    └── 所有条件满足 → controls_allowed_lateral = true
```

### 5.4 心跳不匹配检测

```c
void mads_heartbeat_engaged_check(void) {
    if (controls_allowed_lateral && !heartbeat_engaged_mads) {
        heartbeat_engaged_mads_mismatches++;
        if (heartbeat_engaged_mads_mismatches >= 3) {
            mads_exit_controls(HEARTBEAT_ENGAGED_MISMATCH);  // 断开横向
        }
    } else {
        heartbeat_engaged_mads_mismatches = 0;  // 正常时清零
    }
}
```

### 5.5 Python 侧 Mismatch 检测

在 [mads.py#L108-L117](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/mads.py#L108) 的 `data_sample()` 中：

```python
def data_sample(self):
    if not self.active or self.selfdrive.enabled:
        self.lateral_mismatch_counter = 0
    elif any(not ps.controlsAllowedLateral for ps in self.selfdrive.sm['pandaStates']):
        self.lateral_mismatch_counter += 1
    # 200 次不匹配（约 2 秒）→ 触发 controlsMismatchLateral 告警
```

---

## 6. Unified Engagement Mode (UEM)

### 6.1 概念

**UEM 决定是否允许用巡航按键（SET/-RES/+）一次性同时接合横向+纵向控制**。

- **UEM = OFF**：巡航按键只接合纵向（ACC），横向需要用 LKAS 按钮单独开启
- **UEM = ON**：巡航按键同时接合横向+纵向，一步到位

### 6.2 核心逻辑

阻断判断在 [mads.py#L80-L91](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/mads.py#L80)：

```python
def block_unified_engagement_mode(self) -> bool:
    if not self.unified_engagement_mode:
        return True      # UEM 没开 → 阻断
    if self.enabled:
        return True      # MADS 已开 → 阻断（防止重复接合）
    if self.selfdrive.enabled and self.selfdrive.enabled_prev:
        return True      # 已经全开 → 阻断
    return False          # 放行
```

消费逻辑在 [mads.py#L158-L164](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/mads.py#L158)：

```python
if selfdrive_enable_events:   # 收到 pcmEnable 或 buttonEnable
    if self.block_unified_engagement_mode():
        # 阻断 → 移除 enable 事件，MADS 不接合
        self.events.remove(EventName.pcmEnable)
        self.events.remove(EventName.buttonEnable)
    # 不阻断 → 保留事件，MADS 随之接合
```

### 6.3 触发时序

```
UEM = ON 时按下 SET/-：
    ↓
pcmEnable 事件产生
    ↓
MADS.update_events()
    → block_unified_engagement_mode() 返回 False（不阻断）
    → pcmEnable 保留
    ↓
MADS 状态机检测到 ENABLE 条件
    → 状态: disabled → enabled → active
    ↓
get_lat_active() 返回 True
    → 横向控制开始输出扭矩
    ↓
UI 显示: "engaged"（横向+纵向同时工作）
```

### 6.4 UEM 的持久性

根据设置描述（[steering.yaml](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/sunnylink/settings_ui_src/pages/steering.yaml#L39)）：

> **Once lateral control is engaged via UEM, it will remain engaged until it is manually disabled via the MADS button or car shut off.**

即：一次 UEM 接合后，横向保持激活状态，直到：
- 用户手动按 LKAS 按钮关闭
- 或者车辆熄火

这意味着途中退出纵向（如踩刹车取消 ACC），横向仍然保持工作（`lat_only`）。

### 6.5 UEM vs MadsMainCruiseAllowed 对比

| 特性 | UEM | MadsMainCruiseAllowed |
|------|:---:|:--------------------:|
| **作用** | 巡航按键同时接合横向+纵向 | 用 MAIN 巡航按钮来**开关** MADS |
| **触发源** | `pcmEnable` / `buttonEnable`（SET/-RES/+ 按键） | `cruiseState.available` 的上升沿（MAIN 按键） |
| **行为** | 横向随 ACC 一起接合 | MAIN 按下=开 MADS，MAIN 关闭=关 MADS |
| **独立关系** | 可独立开关 | 可独立开关 |

---

## 7. MadsMainCruiseAllowed

### 7.1 概念

> **Toggle with Main Cruise**：允许用车辆方向盘的 MAIN（主巡航）按钮来切换 MADS 的开关。

对于没有独立 LKAS 按钮的车型（如某些 Toyota/Hyundai），这个功能是 MADS 可用的前提。

### 7.2 实现逻辑

在 [mads.py#L166-L168](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/mads.py#L166)：

```python
if self.main_enabled_toggle:
    if CS.cruiseState.available and not self.selfdrive.CS_prev.cruiseState.available:
        self.events_sp.add(EventNameSP.lkasEnable)
```

即：当 `cruiseState.available` 从 false→true（MAIN 被按下），生成 `lkasEnable` 事件，MADS 状态机检测到后切换到 enabled。

### 7.3 allow_always 条件

某些车型即使 `cruiseState.available == false` 也能按 LKAS 按钮：

```python
# mads.py#L45-L49
if self.CP.brand == "hyundai":
    if self.CP.flags & (HyundaiFlags.HAS_LDA_BUTTON | HyundaiFlags.CANFD):
        self.allow_always = True
if self.CP.brand == "tesla":
    self.allow_always = True
```

这些车型的 LKAS 按钮独立于巡航状态，任何时刻按下都有效。

---

## 8. Steering Mode on Brake

### 8.1 三种模式

通过 [MadsSteeringMode](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/common/params_keys.h#L195) 参数控制（默认值 0）：

| 模式 | 值 | 行为 | 安全层标志 |
|------|:--:|------|:---------:|
| **Remain Active** | 0 | 踩刹车时横向继续保持激活 | 无 |
| **Pause** | 1 | 踩刹车时横向暂停，松开后恢复 | `MADS_PAUSE_LATERAL_ON_BRAKE` |
| **Disengage** | 2 | 踩刹车时横向彻底退出 | `MADS_DISENGAGE_LATERAL_ON_BRAKE` |

### 8.2 实现路径

```python
# mads.py#L188-L196 - Disengage 模式
if self.steering_mode_on_brake == MadsSteeringModeOnBrake.DISENGAGE:
    if self.pedal_pressed_non_gas_pressed(CS):
        self.events_sp.add(EventNameSP.lkasDisable)   # 关闭 MADS

# mads.py#L141-L143 - Pause 模式
if self.steering_mode_on_brake == MadsSteeringModeOnBrake.PAUSE:
    if self.pedal_pressed_non_gas_pressed(CS):
        self.transition_paused_state()                  # 进入暂停
```

同时在安全层通过 [helpers.py#L40-L50](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/helpers.py#L40) 设置 alternative_experience 标志位，panda 安全层也会做对应的刹车检测。

### 8.3 Pause 模式的恢复

刹车释放后，[should_silent_lkas_enable()](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/mads.py#L71) 在条件满足时发送 `silentLkasEnable` 事件：

```python
if self.should_silent_lkas_enable(CS):
    if self.state_machine.state == State.paused:
        self.events_sp.add(EventNameSP.silentLkasEnable)
```

状态机检测到 `silentLkasEnable` → 从 paused 恢复为 enabled。

---

## 9. UI 状态显示

UI 状态计算在 [ui_state.py#L105-L139](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/selfdrive/ui/sunnypilot/ui_state.py#L105)：

```python
@staticmethod
def update_status(ss, ss_sp, onroad_evt) -> str:
    state = ss.state
    mads = ss_sp.mads
    mads_state = mads.state

    # preEnabled → override
    if state == OpenpilotState.preEnabled:
        return "override"

    # overriding 状态处理
    if state == OpenpilotState.overriding:
        if not mads.available:
            return "override"
        if any(e.overrideLongitudinal for e in onroad_evt):
            return "override"

    # MADS 暂停/覆盖状态
    if mads_state in (MADSState.paused, MADSState.overriding):
        return "override"

    # 以下为四种核心状态：
    if not mads.available:
        return "engaged" if ss.enabled else "disengaged"   # 无 MADS → stock 行为

    if not mads.enabled and not ss.enabled:
        return "disengaged"     # 全部关闭

    if mads.enabled and ss.enabled:
        return "engaged"        # 横向+纵向都在工作

    if mads.enabled:
        return "lat_only"       # ⭐ 全时横向控制：只有横向在工作

    if ss.enabled:
        return "long_only"      # 只有 ACC 在工作

    return "disengaged"
```

### UI 状态汇总

| 显示状态 | MADS enabled | openpilot enabled | 含义 | 典型场景 |
|---------|:----------:|:---------------:|------|---------|
| **engaged** | ✓ | ✓ | 完整辅助驾驶 | UEM=ON 按 SET，或分别接合 |
| **lat_only** | ✓ | ✗ | 仅横向控制 | 单独按 LKAS 接合 |
| **long_only** | ✗ | ✓ | 仅 ACC | UEM=OFF 按 SET |
| **disengaged** | ✗ | ✗ | 全部关闭 | 未接合 |
| **override** | - | - | 用户干预/暂停 | 踩刹车(Pause模式)、开门、R档 |

---

## 10. 横向激活决策链路

整个系统中横向控制是否激活的最终决策链路：

```
controlsd_ext.get_lat_active()
    │
    ├── 打转向灯(BlinkerPause)？→ 暂停横向
    │
    ├── MADS available?
    │   ├── Yes → return mads.active  (MADS 状态机决定)
    │   └── No  → return ss.active     (回退 stock 行为)
    │
    ▼
LatControl.update()（实际计算扭矩）
    │
    ▼
carcontroller 发送 CAN 消息
    │
    ▼
panda 安全层校验 controls_allowed_lateral
    │
    ▼
车辆执行转向
```

---

## 11. 平台限制与兼容性

### 11.1 MADS No ACC Main Button

下列品牌的车辆没有 ACC MAIN 按钮，`MadsMainCruiseAllowed` 参数不可用（[helpers.py#L15](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/helpers.py#L15)）：

```python
MADS_NO_ACC_MAIN_BUTTON = ("rivian", "tesla")
```

在这些平台上，MADS 只能通过 LKAS 按钮（如果有）或 UEM 来接合。

### 11.2 部分支持平台

某些平台因缺乏一致的信号来可靠切换 MADS 状态，被标记为"部分支持"（[helpers.py#L24-L30](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/helpers.py#L24)）：

```python
def get_mads_limited_brands(CP, CP_SP) -> bool:
    if CP.brand == 'rivian':
        return True
    if CP.brand == 'tesla':
        return not CP_SP.flags & TeslaFlagsSP.HAS_VEHICLE_BUS
    return False
```

部分支持平台的行为（[mads_settings.py#L111-L128](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/selfdrive/ui/sunnypilot/layouts/settings/steering_sub_layouts/mads_settings.py#L111)）：

| 设置项 | 行为 |
|-------|------|
| MadsMainCruiseAllowed | 强制关闭，选项隐藏 |
| MadsUnifiedEngagementMode | 强制开启，不可更改 |
| MadsSteeringMode | 强制 Disengage (2)，不可更改 |

### 11.3 自动参数强制

当检测到部分支持平台时，[helpers.py#L66-L69](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/sunnypilot/mads/helpers.py#L66) 在 `set_car_specific_params()` 中强制设置参数：

```python
mads_partial_support = get_mads_limited_brands(CP, CP_SP)
if mads_partial_support:
    params.put("MadsSteeringMode", 2, block=True)                # Disengage
    params.put_bool("MadsUnifiedEngagementMode", True, block=True) # UEM 强制开
```

---

## 12. 附录：参数清单

所有 MADS 相关参数定义在 [common/params_keys.h](file:///home/ubuntu/openpilot_c3_src/openpilot_nanasemai/common/params_keys.h)：

| 参数名 | 类型 | 默认值 | 说明 |
|--------|:---:|:-----:|------|
| `Mads` | bool | ✗ | MADS 总开关 |
| `MadsMainCruiseAllowed` | bool | 1 | 允许用 MAIN 巡航切换 MADS |
| `MadsSteeringMode` | int | 0 | 刹车时横向行为：0=保持 1=暂停 2=断开 |
| `MadsUnifiedEngagementMode` | bool | 1 | 统一接合模式（UEM） |

---

> 本文档基于 sunnypilot 分支源码编写。MADS 为第三方分支功能，非 comma.ai 官方 openpilot 的一部分。
