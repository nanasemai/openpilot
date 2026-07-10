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
12. [车型支持矩阵](#12-车型支持矩阵)
13. [附录：参数清单](#13-附录参数清单)
14. [实际案例分析：丰田卡罗拉 MADS 声音差异](#14-实际案例分析丰田卡罗拉-mads-声音差异)
15. [丰田 TSS2 纵向控制架构：视觉纯控 vs 雷达融合](#15-丰田-tss2-纵向控制架构视觉纯控-vs-雷达融合)
    - [15.5 CAN 总线拓扑](#155-can-总线拓扑)
    - [15.6 ACC_TYPE 信号](#156-acc_type--决定纵向能力的核心信号)
    - [15.7 PERMIT_BRAKING 刹车控制](#157-permit_braking--刹车许可精细控制)
    - [15.8 雷达数据流](#158-雷达数据流)
    - [15.9 DISABLE_RADAR 与 SmartDSU](#159-disable_radar-与-smartdsu)
    - [15.10 完整控制流对比](#1510-完整控制流对比)
16. [案例分析：丰田卡罗拉 TSS2 最佳配置](#16-案例分析丰田卡罗拉-tss2-最佳配置)
    - [16.5 硬件兼容性注意事项](#165-硬件兼容性注意事项)
    - [16.6 启动后检查](#166-启动后检查)

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

MADS 状态机实现在 [state.py](../../../sunnypilot/mads/state.py)，管理 5 种状态。

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

#### 状态转换详细规则（[state.py#L45-L134](../../../sunnypilot/mads/state.py#L45)）：

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

MADS 的事件处理在 [mads.py#L119-L208](../../../sunnypilot/mads/mads.py#L119) 的 `update_events()` 方法中。

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

LKAS 按钮是 MADS 的核心交互方式（[mads.py#L174-L181](../../../sunnypilot/mads/mads.py#L174)）：

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

[mads.h#L83-L134](../../../opendbc_repo/opendbc/safety/sunnypilot/mads.h#L83) 的 `m_update_control_state()` 函数：

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

在 [mads.py#L108-L117](../../../sunnypilot/mads/mads.py#L108) 的 `data_sample()` 中：

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

阻断判断在 [mads.py#L80-L91](../../../sunnypilot/mads/mads.py#L80)：

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

消费逻辑在 [mads.py#L158-L164](../../../sunnypilot/mads/mads.py#L158)：

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

根据设置描述（[steering.yaml](../../../sunnypilot/sunnylink/settings_ui_src/pages/steering.yaml#L39)）：

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

在 [mads.py#L166-L168](../../../sunnypilot/mads/mads.py#L166)：

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

通过 [MadsSteeringMode](../../../common/params_keys.h#L195) 参数控制（默认值 0）：

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

同时在安全层通过 [helpers.py#L40-L50](../../../sunnypilot/mads/helpers.py#L40) 设置 alternative_experience 标志位，panda 安全层也会做对应的刹车检测。

### 8.3 Pause 模式的恢复

刹车释放后，[should_silent_lkas_enable()](../../../sunnypilot/mads/mads.py#L71) 在条件满足时发送 `silentLkasEnable` 事件：

```python
if self.should_silent_lkas_enable(CS):
    if self.state_machine.state == State.paused:
        self.events_sp.add(EventNameSP.silentLkasEnable)
```

状态机检测到 `silentLkasEnable` → 从 paused 恢复为 enabled。

---

## 9. UI 状态显示

UI 状态计算在 [ui_state.py#L105-L139](../../../selfdrive/ui/sunnypilot/ui_state.py#L105)：

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

下列品牌的车辆没有 ACC MAIN 按钮，`MadsMainCruiseAllowed` 参数不可用（[helpers.py#L15](../../../sunnypilot/mads/helpers.py#L15)）：

```python
MADS_NO_ACC_MAIN_BUTTON = ("rivian", "tesla")
```

在这些平台上，MADS 只能通过 LKAS 按钮（如果有）或 UEM 来接合。

### 11.2 部分支持平台

某些平台因缺乏一致的信号来可靠切换 MADS 状态，被标记为"部分支持"（[helpers.py#L24-L30](../../../sunnypilot/mads/helpers.py#L24)）：

```python
def get_mads_limited_brands(CP, CP_SP) -> bool:
    if CP.brand == 'rivian':
        return True
    if CP.brand == 'tesla':
        return not CP_SP.flags & TeslaFlagsSP.HAS_VEHICLE_BUS
    return False
```

部分支持平台的行为（[mads_settings.py#L111-L128](../../../selfdrive/ui/sunnypilot/layouts/settings/steering_sub_layouts/mads_settings.py#L111)）：

| 设置项 | 行为 |
|-------|------|
| MadsMainCruiseAllowed | 强制关闭，选项隐藏 |
| MadsUnifiedEngagementMode | 强制开启，不可更改 |
| MadsSteeringMode | 强制 Disengage (2)，不可更改 |

### 11.3 自动参数强制

当检测到部分支持平台时，[helpers.py#L66-L69](../../../sunnypilot/mads/helpers.py#L66) 在 `set_car_specific_params()` 中强制设置参数：

```python
mads_partial_support = get_mads_limited_brands(CP, CP_SP)
if mads_partial_support:
    params.put("MadsSteeringMode", 2, block=True)                # Disengage
    params.put_bool("MadsUnifiedEngagementMode", True, block=True) # UEM 强制开
```

---

## 12. 车型支持矩阵

### 12.1 总览

MADS 的核心逻辑（状态机 + 事件处理）运行在 **controlsd** 层，与车型无关。所有 sunnypilot 兼容的车型都可获得 MADS 的基本功能。但 MADS 需要车型提供 **LKAS 按钮信号** 方能独立切换横向控制，各品牌的集成深度存在差异。

| 品牌 | 类型 | 集成深度 | LKAS 按钮源 | 限制说明 |
|:----:|:----:|:--------:|:-----------|:---------|
| **Hyundai** | ✅ 完整支持 | MadsCarState + MadsCarController | LKAS/LDA 按钮（CAN 总线） | `allow_always` 支持（CANFD/HAS_LDA 车型 LKAS 独立于巡航），MAIN 巡航可切换 |
| **Honda** | ✅ 完整支持 | MadsCarController | 方向盘 LKAS 按钮 | 仪表盘虚线车道显示适配 |
| **Chrysler** | ✅ 完整支持 | MadsCarState + MadsCarController | `Center_Stack_2` / `TRACTION_BUTTON` | RAM 与非 RAM 车型按钮路径不同，自定义 LKAS 心跳 |
| **Ford** | ✅ 完整支持 | MadsCarState | `Steering_Data_FD1.TjaButtnOnOffPress` | 安全层已适配 MADS |
| **Subaru** | ✅ 完整支持 | MadsCarState | `ES_LKAS_State.LKAS_Dash_State` | Pre-global 车型不支持（无 LKAS_Dash_State） |
| **Nissan** | ⚠️ 基础支持 | 无专用 MADS 模块 | 无 LKAS 按钮读取 | HUD 显示已适配 `CC_SP.mads.enabled`，MADS 核心功能通过 controlsd 层工作 |
| **GM** | ⚠️ 基础支持 | 无专用 MADS 模块 | 无 LKAS 按钮读取 | MADS 核心功能通过 controlsd 层 + 安全层工作 |
| **Toyota** | ⚠️ 基础支持 | 无专用 MADS 模块 | 无 LKAS 按钮读取 | MADS 核心功能通过 controlsd 层 + 安全层工作 |
| **Mazda** | ⚠️ 基础支持 | 无专用 MADS 模块 | 无 LKAS 按钮读取 | MADS 核心功能通过 controlsd 层 + 安全层工作 |
| **Volkswagen** | ⚠️ 基础支持 | 无专用 MADS 模块 | 无 LKAS 按钮读取 | MADS 核心功能通过 controlsd 层 + 安全层工作 |
| **Rivian** | 🔶 部分支持 | 仅 MadsCarController | 无 LKAS 按钮 | **有限支持**：无 ACC MAIN 按钮、UEM 强制开、SteeringMode 强制 Disengage |
| **Tesla** | 🔶 部分支持 | 无专用 MADS 模块 | `allow_always`（始终可接合） | **有限支持**：无 ACC MAIN 按钮、有车辆总线时可全支持、否则 UEM 强制开 |

### 12.2 品牌详细分析

#### Hyundai / Kia / Genesis — 完整支持

- **MadsCarState**：集成在 [carstate.py](../../../opendbc_repo/opendbc/car/hyundai/carstate.py#L14)，支持 CANFD 和 CAN 两种平台
- **MadsCarController**：在 [hyundai/mads.py](../../../opendbc_repo/opendbc/sunnypilot/car/hyundai/mads.py#L25) 实现，控制 LKAS/LFA 仪表盘图标状态：
  - `lat_active`：方向盘图标绿色（横向激活）
  - `disengaging`：方向盘图标闪烁（横向退出中）
  - `paused`：方向盘图标灰色（横向暂停）
- **LKAS 按钮**：通过 CAN 总线信号读取，部分车型有独立 LKAS 按钮，部分通过 LDA (Lane Departure Alert) 按钮
- **`allow_always`**：[mads.py#L45-L49](../../../sunnypilot/mads/mads.py#L45) 中 Hyundai 的 CANFD 和 `HAS_LDA_BUTTON` 车型，LKAS 按钮不依赖巡航状态
- **MAIN 巡航切换**：通过 `HyundaiFlagsSP.LONGITUDINAL_MAIN_CRUISE_TOGGLEABLE` 标志位支持
- **安全层**：`hyundai.h` / `hyundai_canfd.h` 均已适配 MADS
- **测试**：专用测试文件 [test_hyundai.py](../../../opendbc_repo/opendbc/safety/tests/test_hyundai.py)

#### Honda / Acura — 完整支持

- **MadsCarController**：在 [honda/mads.py](../../../opendbc_repo/opendbc/sunnypilot/car/honda/mads.py#L12) 实现，核心是仪表盘虚线车道（`dashed_lanes`）显示：
  - MADS enabled + 横向不激活 → 虚线车道（提示驾驶员接管转向）
  - MADS 未启用 → 回退 stock 行为
- **LKAS 按钮**：方向盘上的 LKAS 按钮（Honda 原生支持）
- **安全层**：`honda.h` 中引用了 `controls_allowed_lateral`
- **测试**：专用测试文件 [test_honda.py](../../../opendbc_repo/opendbc/safety/tests/test_honda.py)

#### Chrysler / Jeep / RAM / Dodge — 完整支持

- **MadsCarState**：在 [chrysler/mads.py](../../../opendbc_repo/opendbc/sunnypilot/car/chrysler/mads.py#L57) 实现，初始化时从 `LKAS_HEARTBIT` 读取 `LKAS_DISABLED` 状态
- **MadsCarController**：在 [chrysler/mads.py#L23](../../../opendbc_repo/opendbc/sunnypilot/car/chrysler/mads.py#L23) 实现，控制 `LKAS_HEARTBIT` 的 `LKAS_DISABLED` 信号
- **LKAS 按钮**：RAM 车型通过 `Center_Stack_2.LKAS_Button`，非 RAM 车型通过 `TRACTION_BUTTON.TOGGLE_LKAS`
- **安全层**：已适配 MADS

#### Ford — 完整支持

- **MadsCarState**：在 [ford/mads.py](../../../opendbc_repo/opendbc/sunnypilot/car/ford/mads.py#L16) 实现
- **LKAS 按钮**：从 `Steering_Data_FD1` 消息的 `TjaButtnOnOffPress` 信号读取
- **安全层**：`ford.h` 已适配 MADS
- **测试**：专用测试文件 [test_ford.py](../../../opendbc_repo/opendbc/safety/tests/test_ford.py)

#### Subaru — 完整支持

- **MadsCarState**：在 [subaru/mads.py](../../../opendbc_repo/opendbc/sunnypilot/car/subaru/mads.py#L18) 实现
- **LKAS 按钮**：从摄像头 CAN 消息 `ES_LKAS_State.LKAS_Dash_State` 读取，将 Dash_State 值映射为 `ButtonType.lkas` 事件
- **限制**：`SubaruFlags.PREGLOBAL`（Pre-global 平台）不支持 LKAS 按钮读取
- **安全层**：`subaru.h` 已适配 MADS
- **测试**：专用测试文件 [test_subaru.py](../../../opendbc_repo/opendbc/safety/tests/test_subaru.py)

#### Nissan — 基础支持

- **无专用 MADS 模块**（无 MadsCarState / MadsCarController）
- **HUD 适配**：[carcontroller.py#L73](../../../opendbc_repo/opendbc/car/nissan/carcontroller.py#L73) 中传递 `CC_SP.mads.enabled` 给 HUD 显示
- **MADS 工作方式**：MADS 核心逻辑（状态机、事件处理）通过 controlsd 层运行，但无 LKAS 按钮信号读取，因此**无法通过方向盘按钮独立切换横向**，只能通过 UEM（巡航按键统一接合）或设置中开关

#### GM / Toyota / Mazda / Volkswagen — 基础支持

- **无专用 MADS 模块**
- **MADS 工作方式**：与 Nissan 类似，通过 controlsd 层的 MADS 状态机获得基本功能，但缺乏 LKAS 按钮集成
- **UEM 是主要接合方式**：由于无 LKAS 按钮信号，主要依赖 UEM 通过巡航按键同时接合横向+纵向

#### Rivian — 部分支持

- **MadsCarController**：在 [rivian/mads.py](../../../opendbc_repo/opendbc/sunnypilot/car/rivian/mads.py#L18) 实现，控制 LKA 图标和横向激活状态（限速 90° 转向角）
- **无 MadsCarState**：Rivian 没有独立的 LKAS 按钮信号用于 MADS 切换
- **强制限制**：
  - 无 ACC MAIN 按钮 → `MadsMainCruiseAllowed` 不可用
  - UEM 强制开启 → 只能通过巡航按键接合
  - SteeringMode 强制 Disengage → 踩刹车横向必然退出
- **原因**：代码注释明确说明 *"lack of consistent states to engage controls"*

#### Tesla — 部分支持（有车辆总线时可全支持）

- **无专用 MADS 模块**（无 MadsCarState，只有 `allow_always = True`）
- **`allow_always`**：[mads.py#L49](../../../sunnypilot/mads/mads.py#L49) 中配置，LKAS 按钮始终可用
- **有车辆总线**（`TeslaFlagsSP.HAS_VEHICLE_BUS`）：可通过方向盘滚轮按钮接合 MADS → **完整支持**
- **无车辆总线**：强制 UEM，Disengage 模式 → **部分支持**
- **安全层**：`tesla.h` 中已引用 `controls_allowed_lateral`

### 12.3 MADS 工作方式分类

根据集成深度，MADS 在各车型上的工作方式可分为三个层次：

| 层级 | 能力 | 车型 | 用户可用的接合方式 |
|:----:|:----|:-----|:------------------|
| **A 级** | LKAS 按钮 + UEM + ACC MAIN | Hyundai, Honda, Chrysler, Ford, Subaru | LKAS 按钮 / 巡航按键 / MAIN 巡航 |
| **B 级** | UEM 接合，无 LKAS 按钮 | Nissan, GM, Toyota, Mazda, Volkswagen | 巡航按键（UEM） |
| **C 级** | 有限支持，强制 UEM + Disengage | Rivian, Tesla（无车辆总线） | 仅巡航按键（UEM 强制），踩刹车即退出 |

### 12.4 安全层覆盖

MADS 的安全层通过两个机制确保所有品牌的安全性：

1. **通用层**（`safety/lateral.h`）：包含 `mads.h`，所有品牌的横向安全检测都使用 `controls_allowed || controls_allowed_lateral` 判断。这是**所有品牌共享的基础安全屏障**。
2. **品牌层**（`safety/modes/*.h`）：部分品牌直接在安全模式中引用 `controls_allowed_lateral`，做品牌特定的安全检查。

已确认安全层显式引用 `controls_allowed_lateral` 的品牌：
- **Honda**：[honda.h#L299](../../../opendbc_repo/opendbc/safety/modes/honda.h#L299)
- **Tesla**：[tesla.h#L221](../../../opendbc_repo/opendbc/safety/modes/tesla.h#L221)

其他品牌的安全模式通过 `lateral.h` 的通用逻辑间接引用 `controls_allowed_lateral`。

---

## 13. 附录：参数清单

所有 MADS 相关参数定义在 [common/params_keys.h](../../../common/params_keys.h)：

| 参数名 | 类型 | 默认值 | 说明 |
|--------|:---:|:-----:|------|
| `Mads` | bool | ✗ | MADS 总开关 |
| `MadsMainCruiseAllowed` | bool | 1 | 允许用 MAIN 巡航切换 MADS |
| `MadsSteeringMode` | int | 0 | 刹车时横向行为：0=保持 1=暂停 2=断开 |
| `MadsUnifiedEngagementMode` | bool | 1 | 统一接合模式（UEM） |

## 14. 实际案例分析：丰田卡罗拉 MADS 声音差异

### 14.1 现象

在丰田卡罗拉（Corolla TSS2）上开启 MADS 后，观察到以下行为：

| 操作 | 表现 |
|:----|:----|
| **按下 LKAS 按钮**激活横向控制 | ✅ 有声音提醒 |
| **按下 SET/-** 激活纵向控制（ACC） | ❌ 无声音提醒 |

### 14.2 根因分析

这个差异并非用户可配置的设置项，而是 MADS 事件处理机制与丰田硬件声音机制共同作用的结果。

#### 第一层：MADS 事件层 — `pcmEnable` 被移除

核心在于 MADS 中 [block_unified_engagement_mode()](../../../sunnypilot/mads/mads.py#L80) 对事件的处理。当 **UEM = OFF** 时，按下 SET/- 产生 `pcmEnable` 事件后，MADS 在 [update_events()](../../../sunnypilot/mads/mads.py#L158) 中将其从事件列表移除：

```python
if selfdrive_enable_events:   # 收到 pcmEnable 或 buttonEnable
    if self.block_unified_engagement_mode():
        # UEM 未开启 → 移除 enable 事件
        self.events.remove(EventName.pcmEnable)
        self.events.remove(EventName.buttonEnable)
```

`self.events` 指向**主事件系统的同一个对象**（[mads.py#L42](../../../sunnypilot/mads/mads.py#L42)），因此这个移除直接影响主事件系统。

- **LKAS 按钮**：通过独立的 `events_sp` 事件流添加 `lkasEnable`，在 [events.py#L92](../../../sunnypilot/selfdrive/selfdrived/events.py#L92) 中定义为 `EngagementAlert(AudibleAlert.engage)` → **声音正常触发** ✅
- **SET/- 按钮**：`pcmEnable` 被移除 → 主事件系统看不到 ENABLE 事件 → `AudibleAlert.engage` 不会触发 → **无声** ❌

#### 第二层：丰田 HW 层 — TWO_BEEPS 由 pcm_cancel_cmd 触发

丰田产生 CAN 声音的唯一机制是通过 LKAS_HUD 消息中的 `TWO_BEEPS` 信号（[toyotacan.py#L112](../../../opendbc_repo/opendbc/car/toyota/toyotacan.py#L112)）：

```python
def create_ui_command(packer, steer, chime, ...):
    values = {
        "TWO_BEEPS": chime,  # chime = pcm_cancel_cmd
    }
```

`pcm_cancel_cmd` 来自 [controlsd.py#L191](../../../selfdrive/controls/controlsd.py#L191)：

```python
CC.cruiseControl.cancel = CS.cruiseState.enabled and (not CC.enabled or not self.CP.pcmCruise)
```

丰田卡罗拉 TSS2 的 `openpilotLongitudinalControl = true`、`pcmCruise = false`（未显式设置，默认值），因此 `pcm_cancel_cmd = CS.cruiseState.enabled`，即**只要车上巡航处于激活状态，pcm_cancel_cmd 就为 true**。

但关键点是：`TWO_BEEPS` 是一个**边沿触发**信号——它在状态变化时响一声，持续保持时不重复响。在 [carcontroller.py#L316](../../../opendbc_repo/opendbc/car/toyota/carcontroller.py#L316) 中：

```python
elif pcm_cancel_cmd:
    # forcing the pcm to disengage causes a bad fault sound so play a good sound instead
    send_ui = True  # 强制发送一次 UI 命令（带 chime）
```

`pcm_cancel_cmd` 刚变成 true 时触发一次立即发送，之后每 20 帧常规发送时虽然 `TWO_BEEPS=1`，但 ECU 不会重复响。

### 14.3 完整对比

| 场景 | 按键 | UEM 状态 | MADS 对 pcmEnable | 事件系统 | PCM/TWO_BEEPS | 效果 |
|:----|:----|:-------:|:----------------:|:--------:|:-------------:|:----:|
| **lat_only** | LKAS | — | 无关（通过 events_sp） | `AudibleAlert.engage` | 可能触发 | **有声音** ✅ |
| **long_only** | SET/- | OFF | 移除 | 无 enable 事件 | 独立工作 | **无声音** ❌ |
| **engaged** | SET/- | ON | 保留 | `AudibleAlert.engage` | 独立工作 | **有声音** ✅ |

### 14.4 如何修复（开启 UEM）

默认值确实为 ON（[params_keys.h#L196](../../../common/params_keys.h#L196)）：

```cpp
{"MadsUnifiedEngagementMode", {PERSISTENT | BACKUP, BOOL, "1"}},
```

但由于 `PERSISTENT` 特性，**默认值只在参数从未被写入时生效**。一旦在任何时候（包括旧版本、误操作等）将 UEM 设为 OFF，该值会**永久保持 OFF**，跨版本更新、跨重启都不会自动重置。

**检查当前状态：**

```bash
python -c "from common.params import Params; p=Params(); print('UEM:', p.get_bool('MadsUnifiedEngagementMode'))"
```

**若输出 `False`，通过设置页面开启：**

```
Settings → Steering → MADS → MadsUnifiedEngagementMode → ON
```

**或命令行开启：**

```bash
python -c "from common.params import Params; Params().put_bool('MadsUnifiedEngagementMode', True)"
```

开启 UEM 后：
- `block_unified_engagement_mode()` 返回 False → `pcmEnable` 不再被移除
- 主事件系统收到 enable 事件 → `AudibleAlert.engage` 触发 → **有声音** ✅
- 横向+纵向同时接合 → UI 显示 "engaged"

---

## 15. 丰田 TSS2 纵向控制架构：视觉纯控 vs 雷达融合

### 15.1 背景

在了解 MADS 在丰田车上的行为后，有必要理解丰田 TSS2 平台的纵向控制架构。这直接关系到 MADS 启用后纵向控制的真实工作方式。

丰田 TSS2 车型根据纵向控制方式分为两类：

| 分组 | 含义 | 代码条件 |
|:----|:-----|:--------|
| **RADAR_ACC_CAR** | 保留原厂雷达 ACC | `candidate in RADAR_ACC_CAR` |
| **TSS2_CAR - RADAR_ACC_CAR** | 摄像头直接发送 ACC_CONTROL | `candidate in (TSS2_CAR - RADAR_ACC_CAR)` |

代码定义在 [interface.py#L107-L108](../../../opendbc_repo/opendbc/car/toyota/interface.py#L107)：

```python
ret.openpilotLongitudinalControl = (candidate in (TSS2_CAR - RADAR_ACC_CAR) or
                                    bool(ret.flags & ToyotaFlags.DISABLE_RADAR.value))
```

### 15.2 丰田卡罗拉 TSS2 的架构

卡罗拉 TSS2 属于 **TSS2_CAR** 但不属于 **RADAR_ACC_CAR**，因此其纵向控制架构为：

**视觉纯控模式**（非融合模式）：

```
摄像机 ──→ openpilot ──→ ACC_CONTROL（直接控制油门/刹车）
                        [视觉模型计算加速度]

雷达 ──→ CAN 总线 ──→ 可读但不参与纵向控制
```

关键证据在 [carstate.py#L65](../../../opendbc_repo/opendbc/car/toyota/carstate.py#L65)：

```python
cp_acc = cp_cam if self.CP.carFingerprint in (TSS2_CAR - RADAR_ACC_CAR) else cp
```

ACC 信号来源是**摄像机 CAN 总线**，而非雷达总线。完整的解析路径：

| 车型分类 | ACC 信号来源 | 纵向控制 | 雷达作用 |
|:--------|:-----------:|:--------:|:--------|
| RADAR_ACC_CAR | 雷达 CAN 总线 | 通过 PCM 间接调 ACC | 主动参与 ACC |
| TSS2_CAR - RADAR_ACC_CAR（含 Corolla） | 摄像机 CAN 总线 | 视觉纯控，直接发 accel | 解析 → 规划层融合 |

### 15.3 工作流程

完整链路分为两层：

#### 规划层（plannerd）— 融合层

```
视觉模型 (modelV2) → desiredAcceleration
                              ↓
雷达 (radarState) → leadOne/leadTwo (dRel, vRel, aLeadK)
                              ↓
                    LongitudinalPlanner.update()
                      ├── 读 radarState.leadOne（雷达前车数据）
                      ├── 读 modelV2.action.desiredAcceleration（视觉加速度）
                      └── mpc.update(radarState) → MPC 计算最优轨迹
                              ↓
                    output = min(e2e_desiredAccel, mpc_plan_accel)
                              ↓
                    longitudinalPlan.aTarget（最终统一输出）
```

关键融合点在 [longitudinal_planner.py#L176-L199](../../../selfdrive/controls/lib/longitudinal_planner.py#L176)：

```python
# MPC 使用雷达数据（long_mpc.py#L316）
self.mpc.update(sm['radarState'], v_cruise, personality=personality)

# 视觉模型输出（line 195）
output_a_target_e2e = sm['modelV2'].action.desiredAcceleration
output_a_target_mpc = ...  # MPC 规划加速度（含雷达数据）

# 融合：取两者最小值（更保守，更安全）
if self.is_e2e(sm):
    output_a_target = min(output_a_target_e2e, output_a_target_mpc)
```

#### 执行层（carcontroller）— 单一路径

```
longitudinalPlan.aTarget
    ↓
CarController → PID → pcm_accel_cmd
    ↓
create_accel_command(ACCEL_CMD, ACC_TYPE=1, PERMIT_BRAKING, ...)
    ↓
camera CAN bus (bus 2)
    ↓
PCM → 执行油门/刹车
```

注意 [interface.py#L97-L99](../../../opendbc_repo/opendbc/car/toyota/interface.py#L97) 的注释：

```python
# Disabling radar is only supported on TSS2 radar-ACC cars
# 禁用雷达仅支持 TSS2 雷达-ACC 车型
```

——只有 **RADAR_ACC_CAR** 才有"禁用雷达"的选项。卡罗拉 TSS2 不在此列，雷达本就处于**被动旁观**状态，openpilot 的纵向目标加速度完全由视觉模型决定，雷达数据不参与融合。

### 15.4 对 MADS 行为的影响

这一架构解释了为什么之前分析的**声音差异**场景中，即使 UEM=OFF 导致 `pcmEnable` 被 MADS 移除，纵向控制仍然可以工作：

1. 按下 SET/- 后，车辆 PCM **独立检测到巡航按键信号**，自行启用 ACC
2. MADS 移除了 `pcmEnable` 事件 → openpilot 事件系统未收到 enable
3. 但 **PCM 已独立接管 ACC 控制** → 纵向控制仍然有效
4. MADS 仅控制了横向（不激活）→ UI 显示 "long_only"

对于 **RADAR_ACC_CAR** 车型（如部分 TSS2 丰田），pcmCruise 模式下纵向由 PCM 和原车雷达管理，MADS 移除 `pcmEnable` 后同样会出现类似行为。

### 15.5 CAN 总线拓扑

丰田 TSS2 车型有 **3 条 CAN 总线**：

| 总线 | ID | 设备 | 关键信号 |
|:----|:--:|:-----|:---------|
| **PT bus** | 0 | PCM、EPS、ABS、BCM | 车速、转向扭矩、刹车/油门、巡航状态 |
| **Radar bus** | 1 | 毫米波雷达 | 障碍物点云 (0x180-0x19F) |
| **Cam bus** | 2 | 前视摄像头 | ACC_CONTROL、LKAS_HUD、车道线 |

`ACC_CONTROL` 消息的来源在 [carstate.py#L65](../../../opendbc_repo/opendbc/car/toyota/carstate.py#L65) 决定：

```python
cp_acc = cp_cam if self.CP.carFingerprint in (TSS2_CAR - RADAR_ACC_CAR) else cp
```

- **Corolla TSS2（非 RADAR_ACC）**：`cp_acc = cp_cam` → ACC 信号从 **cam bus（总线 2）** 获取
- **RADAR_ACC_CAR（如 RAV4）**：`cp_acc = cp` → ACC 信号从 **PT bus（总线 0）** 获取

### 15.6 ACC_TYPE — 决定纵向能力的核心信号

在 [carstate.py#L160](../../../opendbc_repo/opendbc/car/toyota/carstate.py#L160) 中有一个极易被忽略但非常重要的参数：

```python
self.acc_type = cp_acc.vl["ACC_CONTROL"]["ACC_TYPE"]
```

| ACC_TYPE | 含义 |
|:--------:|:-----|
| **1** | 全速范围 ACC（支持 Stop & Go） |
| **2** | 低速锁定 — 需要车速 > ~30km/h 才能启用 |

当 openpilot 接管纵向控制后，通过 `create_accel_command()` 持续发送 `ACC_TYPE=1`，让 PCM 保持在"全速 ACC"模式。如果 `ACC_TYPE` 变成 2，PCM 会认为车辆不支持低速 ACC，触发 `LOW_SPEED_LOCKOUT`（[carstate.py#L167-L170](../../../opendbc_repo/opendbc/car/toyota/carstate.py#L167)）：

```python
if (self.CP.carFingerprint in TSS2_CAR and self.acc_type == 1):
    if self.CP.openpilotLongitudinalControl:
        ret.accFaulted = ret.accFaulted or cp.vl["PCM_CRUISE_2"]["LOW_SPEED_LOCKOUT"] == 2
```

**这是 openpilot 能实现 Stop & Go 的关键** — 持续注入 `ACC_TYPE=1`，让 PCM 认为 ACC 始终是"全速可用"状态，从而允许低速跟车和自动起步。

### 15.7 PERMIT_BRAKING — 刹车许可精细控制

在 [carcontroller.py#L278-L281](../../../opendbc_repo/opendbc/car/toyota/carcontroller.py#L278) 中有一个精细的刹车许可逻辑：

```python
if net_acceleration_request_min < 0.2 or stopping or not CC.longActive:
    self.permit_braking = True       # 允许刹车
elif net_acceleration_request_min > 0.3:
    self.permit_braking = False      # 禁止刹车（只在需要加速时）
```

`net_acceleration_request` 考虑了**坡度补偿**（[carcontroller.py#L239](../../../opendbc_repo/opendbc/car/toyota/carcontroller.py#L239)）：

```python
accel_due_to_pitch = math.sin(min(self.pitch.x, 0.0)) * ACCELERATION_DUE_TO_GRAVITY
net_acceleration_request = pcm_accel_cmd + accel_due_to_pitch
```

下坡时计算重力分量并叠加到加速度请求中，避免在需要减速时意外解除刹车许可。

### 15.8 雷达数据流 — 规划层融合详解

雷达数据在 Corolla TSS2 上**并非旁观者**，而是经过完整的解析链路后参与到规划层的融合决策中。

#### 数据链路

```
CAN bus 1 (Radar)
  → RadarInterface (radar_interface.py)
    → 解析 0x180-0x19F 共 16 个点云消息
    → 输出 RadarPoint[] (dRel, yRel, vRel, measured)
  → radard 进程
    → 聚合点云、跟踪前车
    → 输出 radarState (leadOne/leadTwo)
  → plannerd (LongitudinalPlanner)
    → mpc.update(radarState)  ← 雷达数据进入 MPC
```

#### MPC 内部如何使用雷达

在 [long_mpc.py#L316-L351](../../../selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py#L316) 中：

```python
def update(self, radarstate, v_cruise, ...):
    # 从雷达数据提取前车状态
    lead_xv_0 = self.process_lead(radarstate.leadOne)
    lead_xv_1 = self.process_lead(radarstate.leadTwo)

    # 计算前车等效静止障碍物距离
    lead_0_obstacle = lead_xv_0[:,0] + get_stopped_equivalence_factor(lead_xv_0[:,1])
    lead_1_obstacle = lead_xv_1[:,0] + get_stopped_equivalence_factor(lead_xv_1[:,1])

    # 计算巡航虚拟障碍物（无前车时使用）
    cruise_obstacle = np.cumsum(T_DIFFS * v_cruise_clipped) + get_safe_obstacle_distance(v_cruise_clipped, t_follow)

    # 融合决策：取最近障碍物
    x_obstacles = np.column_stack([lead_0_obstacle, lead_1_obstacle, cruise_obstacle])
    self.source = MPC_SOURCES[np.argmin(x_obstacles[0])]

    # 将最近障碍物距离作为 MPC 参数
    self.params[:,2] = np.min(x_obstacles, axis=1)
```

MPC 的决策来源（[long_mpc.py#L339](../../../selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py#L339)）：

| `self.source` | 含义 | 触发条件 |
|:-------------|:-----|:--------|
| `lead0` | 跟随最近前车 | 雷达 leadOne 障碍物最近 |
| `lead1` | 跟随次近前车 | 雷达 leadTwo 障碍物最近 |
| `cruise` | 巡航到设定速度 | 无前车或前车很远 |

#### 真正的融合发生在 plannerd

最终输出在 [longitudinal_planner.py#L195-L205](../../../selfdrive/controls/lib/longitudinal_planner.py#L195)：

```python
output_a_target_e2e = sm['modelV2'].action.desiredAcceleration  # 视觉模型
output_a_target_mpc = ...   # MPC 规划（含雷达数据）

if self.is_e2e(sm):
    output_a_target = min(output_a_target_e2e, output_a_target_mpc)
    # ^ 取更保守的值：视觉说"加速"，雷达说"刹车" → 选刹车
else:
    output_a_target = output_a_target_mpc
    # ^ 非 E2E 模式：仅 MPC（基于雷达）
```

融合策略：**`min()` 取最小值**，即视觉模型和 MPC（雷达）中更保守的那个胜出。这确保了：
- 视觉漏检前车 → 雷达检测到 → MPC 输出低加速度 → 安全
- 雷达误报障碍物 → 视觉正常 → E2E 输出高加速度 → MPC 限制 → 平缓

#### 与老款车型的差异

雷达消息 ID 不同（[radar_interface.py#L29-L34](../../../opendbc_repo/opendbc/car/toyota/radar_interface.py#L29)）：

```python
if CP.carFingerprint in TSS2_CAR:
    self.RADAR_A_MSGS = list(range(0x180, 0x190))  # TSS2: 0x180-0x18F
    self.RADAR_B_MSGS = list(range(0x190, 0x1a0))  # TSS2: 0x190-0x19F
else:
    self.RADAR_A_MSGS = list(range(0x210, 0x220))  # 老款: 0x210-0x21F
    self.RADAR_B_MSGS = list(range(0x220, 0x230))  # 老款: 0x220-0x22F
```

但解析逻辑完全相同，最终都是 `RadarPoint[]` → `radarState` → `plannerd`。

### 15.9 DISABLE_RADAR 与 SmartDSU

#### DISABLE_RADAR — 仅对 RADAR_ACC_CAR 生效

[interface.py#L97-L99](../../../opendbc_repo/opendbc/car/toyota/interface.py#L97) 的注释说得很清楚：

```python
# Disabling radar is only supported on TSS2 radar-ACC cars
if alpha_long and candidate in RADAR_ACC_CAR:
    ret.flags |= ToyotaFlags.DISABLE_RADAR.value
```

当 RADAR_ACC_CAR 车型开启实验性纵向控制（`alpha_long`）后：

1. 设置 `DISABLE_RADAR` 标志位
2. [init()#L206-L209](../../../opendbc_repo/opendbc/car/toyota/interface.py#L206) 通过 UDS 协议**物理禁用雷达的发送**：
   ```python
   if CP.flags & ToyotaFlags.DISABLE_RADAR.value:
       communication_control = bytes([uds.SERVICE_TYPE.COMMUNICATION_CONTROL,
                                      uds.CONTROL_TYPE.ENABLE_RX_DISABLE_TX,
                                      uds.MESSAGE_TYPE.NORMAL])
       disable_ecu(can_recv, can_send, bus=0, addr=0x750, sub_addr=0xf, com_cont_req=communication_control)
   ```
3. [carcontroller.py#L334](../../../opendbc_repo/opendbc/car/toyota/carcontroller.py#L334) 持续发送 tester present 消息保持雷达静默：
   ```python
   if self.frame % 20 == 0 and self.CP.flags & ToyotaFlags.DISABLE_RADAR.value:
       can_sends.append(make_tester_present_msg(0x750, 0, 0xF))
   ```

这是为了保证雷达不会与 openpilot 发送的 `ACC_CONTROL` 指令冲突。Corolla TSS2 不在此列 — 它本就**不依赖雷达做 ACC**，无需禁用。

#### SmartDSU — 第三方硬件桥接

[interface.py#L139-L144](../../../opendbc_repo/opendbc/car/toyota/interface.py#L139) 检测 smartDSU 硬件：

```python
if 0x2FF in fingerprint[0] or (0x2AA in fingerprint[0] and candidate in NO_DSU_CAR):
    ret.flags |= ToyotaFlagsSP.SMART_DSU.value

    if 0x2AA in fingerprint[0] and candidate in NO_DSU_CAR:
        ret.flags |= ToyotaFlagsSP.RADAR_CAN_FILTER.value
```

smartDSU 是一个**第三方硬件**，插在 DSU（或雷达）和摄像头之间，**拦截 PCM/DSU 的 ACC 消息**，让 openpilot 的 `ACC_CONTROL` 能通过。它允许原本使用 DSU/PCM 控制纵向的车型（如部分 RADAR_ACC_CAR）切换到 openpilot 纵向控制，且无需禁用雷达。

### 15.10 完整控制流对比

```
Corolla TSS2（视觉+雷达规划层融合）:
  视觉模型 → desiredAcceleration ─┐
                                   ├──→ min() ─→ aTarget → PID → ACC_CONTROL → PCM → 执行
  雷达 → radarState → MPC ─────────┘     ^ 取更保守值

RADAR_ACC_CAR + alpha_long（禁用雷达）:
  视觉模型 → desiredAcceleration ─┐
                                   ├──→ min() ─→ aTarget → PID → ACC_CONTROL → PCM → 执行
  雷达 → [物理禁用] ───→ MPC(无雷达) ┘

RADAR_ACC_CAR + SmartDSU（第三方桥接）:
  视觉模型 → desiredAcceleration ─┐
                                   ├──→ min() ─→ aTarget → PID → ACC_CONTROL → SmartDSU → PCM → 执行
  雷达 → radarState → MPC ─────────┘

RADAR_ACC_CAR + pcmCruise（纯原厂）:
  openpilot → 仅提供转向辅助，不发送 ACC_CONTROL
  雷达 → PCM → 原厂 ACC [完全由车辆独立控制]
```

---

## 16. 案例分析：丰田卡罗拉 TSS2 最佳配置

基于前文对 Corolla TSS2 架构的全面分析（CAN 拓扑、ACC_TYPE、视觉+雷达 MPC 融合、PERMIT_BRAKING、SmartDSU 等），以下是最佳配置建议。

### 16.1 NNLC — 建议启用

Corolla TSS2 有专门的 NNLC 模型文件（[TOYOTA_COROLLA_TSS2.json](../../../sunnypilot/neural_network_data/neural_network_lateral_control/TOYOTA_COROLLA_TSS2.json)），模型匹配逻辑（[helpers.py#L23-L68](../../../sunnypilot/selfdrive/controls/lib/nnlc/helpers.py#L23)）会按车型指纹 + EPS 固件版本做模糊匹配，Corolla TSS2 各变体都会命中该模型。

NNLC 的架构（[nnlc.py#L34-L164](../../../sunnypilot/selfdrive/controls/lib/nnlc/nnlc.py#L34)）：

```python
class NeuralNetworkLateralControl(LatControlTorqueExtBase):
    def update_neural_network_feedforward(self, CS, params, calibrated_pose):
        # 输入：vEgo, desired/actual lateral_accel, jerk, roll, pitch
        #      + 过去 3 帧历史数据（-0.3s, -0.2s, -0.1s）
        #      + 未来 4 个时间点（0.3s, 0.6s, 1.0s, 1.5s）的规划数据
        nnff_setpoint_input = [CS.vEgo, self._setpoint, self.lateral_jerk_setpoint, roll] \
                              + [self._setpoint] * self.past_future_len + past_rolls + future_rolls
        torque_from_setpoint = self.model.evaluate(nnff_setpoint_input)

        # 前馈也经 NN 计算
        nn_input = [CS.vEgo, self._desired_lateral_accel, friction_input, roll] \
                   + past_lateral_accels_desired + future_planned_lateral_accels \
                   + past_rolls + future_rolls
        self._ff = self.model.evaluate(nn_input)
```

与传统 PID 扭矩控制不同的是：

| 维度 | Stock LQR/Torque | NNLC |
|:----|:----------------|:-----|
| **转向模型** | 线性前馈表（基于车速查表） | 神经网络（考虑侧倾、侧向加速度、历史轨迹） |
| **弯道补偿** | 固定增益 | 根据曲率+侧倾动态调整 |
| **高速直线** | 可能微调抖动 | 更平滑（NN 学习到直行不应有扭矩输出） |
| **启用条件** | 始终可用 | 需要车型有 `.json` 训练模型 |

### 16.2 最佳配置清单

| 设置项 | 推荐值 | 理由 |
|:------|:------:|:-----|
| **Mads** | ON | 核心功能，横向/纵向解耦 |
| **MadsUnifiedEngagementMode (UEM)** | ON | 一次按键接合所有控制，解决之前讨论的声音缺失问题 |
| **MadsMainCruiseAllowed** | ON | 允许 MAIN 按钮切换 MADS 开关 |
| **MadsSteeringMode** | 1 (Pause) | 刹车时横向暂停，松脚恢复，最自然 |
| **NeuralNetworkLateralControl (NNLC)** | ON | 神经网络扭矩控制，转向手感更平滑 |
| **EnforceTorqueControl** | 可选 | 开启后强制使用扭矩控制而非角度控制（需要 NNLC 时推荐） |
| **ExperimentalLongitudinalControl** | N/A | Corolla TSS2 不是 RADAR_ACC_CAR，此选项无效 |

### 16.3 纵向控制架构总结

```
视觉模型 (modelV2.action.desiredAcceleration) ──┐
                                                  ├── min() → aTarget → PID → ACC_CONTROL
雷达 (radarState → MPC lead 检测) ────────────────┘

ACC_TYPE=1（全速范围）持续注入 → 支持 Stop & Go
PERMIT_BRAKING 根据 net_acceleration_request 动态切换
```

Corolla TSS2 是 openpilot 视觉纯控 + 雷达 MPC 辅助校验模式。雷达数据经 `0x180-0x19F` 点云解析 → `radarState` → `LongitudinalMPC` → 与视觉 `desiredAcceleration` 取最小值。无需启用 `alpha_long` 或 SmartDSU。

### 16.4 横向控制架构总结

```
NNLC = ON:
  vEgo, latAccel, roll, pitch, 历史数据, 未来规划
    → TOYOTA_COROLLA_TSS2 NN 模型 → 扭矩前馈 (self._ff)
    → PID 误差修正 → 最终输出扭矩

NNLC = OFF:
  扭矩前馈表 (torque_data) → PID 误差修正 → 最终输出扭矩
```

### 16.5 硬件兼容性注意事项

以下是与 Corolla TSS2 相关的硬件兼容性事项，理解这些有助于排查问题：

| 项目 | 说明 | Corolla TSS2 是否适用 |
|:----|:-----|:--------------------|
| **EPS 扭矩比例 (EPS_SCALE)** | 部分车型 EPS 的扭矩缩放因子非标准值。Corolla TSS2 为 **88**（默认 73）。[values.py#L591-L592](../../../opendbc_repo/opendbc/car/toyota/values.py#L591) | **适用** — `eps_torque_scale = 0.88` |
| **DSU (Driver Support Unit)** | 老款丰田有独立 DSU 模块处理 ACC 逻辑。TSS2 车型无 DSU（`NO_DSU`），摄像头直连 CAN | **无需关注** — TSS2 天生无 DSU |
| **不支持的 DSU 车型** | 部分车型（如 Mirai、RAV4 Prime）DSU 使用 AEB 消息控制纵向，openpilot 无法接管纵向 | **不适用** — Corolla TSS2 不在此列 |
| **SmartDSU 硬件桥接** | 第三方硬件，拦截 DSU/雷达 ACC 消息，允许 openpilot 发 ACC_CONTROL | **不适用** — Corolla TSS2 无 DSU |
| **CAN 过滤器** | 配合 Radar CAN Filter 的第三方设备，发送 0x2AA 消息拦截雷达 ACC 信号 | **不适用** — Corolla TSS2 无需拦截雷达 |
| **ZSS 角度传感器** | 第三方硬件，[zorrobyte/betterToyotaAngleSensorForOP](https://github.com/zorrobyte/betterToyotaAngleSensorForOP)，提供更精确的方向盘角度。检测条件：CAN 总线 0x23 消息存在且非 SECOC 车型 | **可选安装** — 可提升横向控制精度 |
| **Gas Interceptor** | 油门拦截器硬件（检测条件：总线 0x201 消息 + openpilotLongitudinalControl + 非 SECOC）。启用后 `minEnableSpeed = -1` 且无需 PCM 巡航 | **可选安装** — 用于绕过原车 PCM 限速 |
| **SECOC（安全车载通信）** | 新型丰田/雷克萨斯（2023+）使用的 CAN 消息加密机制。`SECOC_CAR` 车型需要额外密钥处理，发送 LKA/LTA 命令需计算 MAC 校验 | **不适用** — Corolla TSS2 2020-22 不使用 SECOC |
| **LTA vs LKAS 转向控制** | `ANGLE_CONTROL_CAR`（如 RAV4 Prime、Mirai）使用 LTA 角度控制消息，其他车型使用 EPS 扭矩控制 | **扭矩控制** — Corolla TSS2 使用标准 EPS 扭矩控制 |
| **Alt Brake** | `toyota_new_mc_pt_generated` DBC 车型使用替代刹车信号（[interface.py#L33-L34](../../../opendbc_repo/opendbc/car/toyota/interface.py#L33)） | **不适用** — Corolla TSS2 使用 `toyota_nodsu_pt_generated` |

关键结论：

- Corolla TSS2 硬件兼容性**非常简单**——它不需要 SmartDSU、CAN 过滤器或任何桥接硬件
- 所有 TSS2 车型都是 `NO_DSU`，摄像头通过 `toyota_nodsu_pt_generated` DBC 直连 CAN PT 总线
- **只需一根标准 OBD-II 到 Panda 线缆**，无需其他改装即可使用 MADS
- ZSS 和 Gas Interceptor 是**可选**的第三方改装，能提升体验但不必须

### 16.6 启动后检查

如果遇到之前讨论的 UEM 不生效问题，在终端运行：

```bash
python -c "from common.params import Params; p=Params(); print('UEM:', p.get_bool('MadsUnifiedEngagementMode')); print('NNLC:', p.get_bool('NeuralNetworkLateralControl')); print('Mads:', p.get_bool('Mads'))"
```

如果输出 `UEM: False`，说明参数是 PERSISTENT 的旧值覆盖了代码默认值，手动设为 True 即可。

> 本文档基于 sunnypilot 分支源码编写。MADS 为第三方分支功能，非 comma.ai 官方 openpilot 的一部分。
