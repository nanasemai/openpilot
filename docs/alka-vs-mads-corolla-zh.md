# ALKA vs MADS：丰田卡罗拉 TSS2 实际测试表现对比分析

## 概述

本文档对比 **DragonPilot (ALKA)** 与 **Sunnypilot (MADS)** 在丰田卡罗拉 TSS2 上的实际测试表现差异。两个功能都实现了"全时横向控制"——让横向控制独立于纵向控制运行，但实现方式和工作行为有显著差异。

---

## 1. 架构差异

| 维度 | ALKA（DragonPilot / dp-dev） | MADS（Sunnypilot / sp-dev） |
|:----|:--------------------------|:--------------------------|
| **代码量** | ~50 行（嵌入 controlsd） | ~800+ 行（独立 mads/ 模块） |
| **状态机** | 无独立状态机（复用 stock disabled/enabled） | 5 种状态（disabled/enabled/paused/softDisabling/overriding） |
| **LKAS 信号源** | `cruiseState.available`（MAIN 按钮） | 实际 CAN 总线 LKAS 按钮信号 |
| **安全层** | `lat_control_allowed()` 通用层（`lateral.h`） | 专用 `controls_allowed_lateral` + 品牌定制 |
| **复杂程度** | 轻量、简洁 | 完整模块化、可配置性高 |

---

## 2. 按键交互对比

### 2.1 横向接合方式

| 场景 | ALKA | MADS |
|:----|:-----|:-----|
| **LKAS 按钮** | ❌ 不使用（丰田无独立 LKAS 信号） | ✅ 核心交互方式，切换 enabled/disabled |
| **MAIN 按钮** | ✅ 切换 `alka_active` | ✅ `MadsMainCruiseAllowed=ON` 时可配置为切换 MADS |
| **SET/- 巡航键** | 仅接合纵向（stock 行为） | 接合纵向；`UEM=ON` 时同时接合横向+纵向 |
| **按钮响应** | 无独立的声音反馈 | 触发 `AudibleAlert.engage` 声音 |

### 2.2 丰田 Corolla 特有行为

| 行为 | ALKA | MADS |
|:----|:-----|:-----|
| **lkas_on 来源** | `PCM_CRUISE_2` 位 15（ACC 主开关状态） | 实际 LKAS/LDA 按钮 CAN 消息 |
| **按下 LKAS 按钮效果** | 不影响 ALKA（仅更改仪表盘显示） | 切换 MADS enabled/disabled |
| **按下 MAIN 按钮效果** | 切换 `alka_active`（开关整个 ALKA 功能） | 根据配置切换 MADS 或仅切换巡航 |

---

## 3. 刹车行为对比

这是两者**最显著的实际体验差异**。

### 3.1 ALKA：无特殊刹车处理

```python
self.alka_active = lkas_on and gear_ok and calibrated \
                   and not CS.seatbeltUnlatched and not CS.doorOpen
```

- **刹车按下时**：`alka_active` 不受影响（不检查 `brakePressed`）
- `CC.latActive = (enabled or alka_active) and ...`
- **效果**：`enabled=False`（系统退出），但 `alka_active=True` → `CC.latActive=True`
- **实际表现**：踩刹车时横向**始终保持激活**，等同于 MADS 的 SteerMode=0（Remain Active）

### 3.2 MADS：三种刹车模式可配置

通过 `MadsSteeringMode` 参数控制：

| 模式 | 值 | Corolla 上的表现 |
|:----|:--:|:----------------|
| **Remain Active** | 0 | 踩刹车时横向继续保持激活（同 ALKA 行为） |
| **Pause**（推荐） | 1 | 踩刹车时横向暂停，松开后自动恢复 |
| **Disengage** | 2 | 踩刹车时横向彻底退出，需重新接合 |

### 3.3 实际测试差异

| 场景 | ALKA | MADS（Pause 模式） |
|:----|:-----|:-----------------|
| **高速巡航踩刹车减速** | 方向盘仍由 OP 控制 | 方向盘暂停控制 → 手动转向 |
| **松开刹车后** | 横向仍然保持激活 | 横向自动恢复（状态从 paused → enabled） |
| **弯道中踩刹车** | 仍辅助转向（可能出乎意料） | 暂停控制 → 驾驶员完全接管 |
| **走走停停** | 始终横向辅助 | 刹车时暂停，松刹车自动恢复 |

---

## 4. 声音反馈对比

### 4.1 ALKA：无声音差异

- ALKA 不涉及事件系统修改，不会移除 `pcmEnable`
- 按下 SET/- 接合纵向 → 正常触发 `AudibleAlert.engage`（**有声音** ✅）
- 横向激活 via MAIN → 不产生新的 engage 声音（**无声** ❌）
- 无 UEM 概念，不存在 `pcmEnable` 被移除的问题

### 4.2 MADS：三场景声音对比（UEM=OFF 时）

| 场景 | 接合方式 | 发出声音？ | 原因 |
|:----|:--------|:---------:|:----|
| **lat_only** | LKAS 按钮 | ✅ 有 | `events_sp` 添加 `lkasEnable` → `AudibleAlert.engage` |
| **long_only** | SET/- | ❌ 无 | `pcmEnable` 被 `block_unified_engagement_mode()` 移除 |
| **engaged** | SET/-（UEM=ON） | ✅ 有 | `pcmEnable` 保留，正常触发音效 |

### 4.3 丰田丰田声音机制

两者都受丰田硬件的声音机制限制：
- `TWO_BEEPS` 信号是**边沿触发**（只在状态变化时响一次）
- 通过 `pcm_cancel_cmd = True` 触发补偿音效
- 活跃状态下不再重复响

> **结论**：在声音体验上，ALKA 更简洁（纵向有声音、横向无声），MADS 更灵活（通过 UEM 控制是否要声音）。

---

## 5. 安全层对比

### 5.1 ALKA：通用 `lat_control_allowed()`

```c
// lateral.h
static bool lat_control_allowed(void) {
  return controls_allowed || (alka_allowed && (alternative_experience & ALT_EXP_ALKA) != 0
                              && lkas_on && vehicle_moving);
}
```

- 单一检查点：`controls_allowed` 或 ALKA 条件满足
- 依赖 `lkas_on` 信号（丰田从 `PCM_CRUISE_2` 位 15 读取）
- 依赖 `vehicle_moving`（禁止横向在静止时激活）
- 不需要 panda 心跳校验

### 5.2 MADS：双重安全层

```c
// mads.h
controls_allowed_lateral = controls_allowed || (alt_exp & ALT_EXP_ENABLE_MADS) && mads_enabled;
```

- 独立于 `controls_allowed` 的 `controls_allowed_lateral`
- panda 心跳检测（3 次不匹配触发断开）
- 品牌安全模式扩展（Honda/Tesla 有显式引用）
- 通过 `alternative_experience` 传递 MADS 配置标志位

### 5.3 Corolla 上的安全影响

| 场景 | ALKA | MADS |
|:----|:-----|:-----|
| **panda 固件** | 使用 stock toyota 安全模式 + `alka_allowed=true` | 使用 stock toyota 安全模式 + MADS 标志位 |
| **心跳校验** | 无 | 有（`alternative_experience` 心跳匹配） |
| **故障检测** | 依赖 stock `steerFault` 检测 | 独立 + stock 双重检测 |
| **安全冗余** | 较低（单层校验） | 较高（双层校验 + 心跳） |

---

## 6. UI 状态显示对比

### 6.1 ALKA：3 种状态

```python
class UIStatus(Enum):
    DISENGAGED = "disengaged"
    ENGAGED = "engaged"
    OVERRIDE = "override"
    ALKA = "alka"
```

| UI 状态 | 含义 | 触发条件 |
|:--------|:-----|:---------|
| **engaged** | 纵向+横向都在工作 | `selfdriveState.enabled=True` |
| **alka** | 只有横向在工作 | `alka_active=True` 且 `enabled=False` |
| **disengaged** | 横向+纵向都未激活 | `enabled=False` 且 `alka_active=False` |

### 6.2 MADS：4 种状态

| UI 状态 | 含义 | 触发条件 |
|:--------|:-----|:---------|
| **engaged** | 横向+纵向都在工作 | `mads.enabled=True` 且 `ss.enabled=True` |
| **lat_only** | 只有横向在工作 | `mads.enabled=True` 且 `ss.enabled=False` |
| **long_only** | 只有纵向在工作 | `mads.enabled=False` 且 `ss.enabled=True` |
| **disengaged** | 横向+纵向都未激活 | `mads.enabled=False` 且 `ss.enabled=False` |

### 6.3 实际 HUD 显示差异

| 场景 | ALKA HUD | MADS HUD |
|:----|:---------|:---------|
| **横向激活（未接合 ACC）** | 显示 `alka` 状态图标 | 显示 `lat_only` 状态图标 |
| **横向+纵向同时工作** | 显示 `engaged` | 显示 `engaged` |
| **纵向工作（横向关闭）** | 显示 `engaged`（无区别） | 显示 `long_only`（明确区分） |
| **方向盘图标** | 显示方向盘图标（根据 DP 配置） | 显示方向盘图标（根据 SP 配置） |

---

## 7. 实际驾驶场景测试对比

### 7.1 场景一：正常起步

```
驾驶员操作：按 MAIN → 按 SET/- → 行驶
```

| 步骤 | ALKA | MADS（UEM=ON） | MADS（UEM=OFF） |
|:----|:-----|:--------------|:---------------|
| ① 按 MAIN | 打开巡航准备（`acc_main_on=true`） | 打开巡航准备 | 打开巡航准备 |
| ② 按 SET/- | 接合纵向，`enabled=true`，**有声音** ✅ | 接合横向+纵向，**有声音** ✅ | 仅接合纵向，**无声** ❌ |
| ③ 行驶中 | 横向由 enabled 控制 | 横向+纵向同时工作 | 横向未激活，需按 LKAS |
| **需要声音次数** | 1 次 | 1 次 | 0 次（额外手动按 LKAS 有声音） |

### 7.2 场景二：纯横向控制（不开 ACC）

```
驾驶员操作：按 MAIN → 不按 SET/- → 按 LKAS
```

| 步骤 | ALKA | MADS |
|:----|:-----|:-----|
| 按 MAIN | `lkas_on=true` → `alka_active=true` | 仅准备巡航，横向未激活 |
| 按 LKAS | 无变化（丰田无 LKAS 信号） | 接合横向，**有声音** ✅ |
| 行驶中 | **横向激活** ✅（ALKA 自动工作） | **横向激活** ✅ |
| **注意** | ALKA 在 MAIN 按下后**自动激活**，无需额外按键 | MADS 需要额外按 LKAS 按钮 |

### 7.3 场景三：弯道中踩刹车

```
驾驶员操作：行驶中 → 踩刹车减速 → 松开刹车
```

| 阶段 | ALKA | MADS（Pause） | MADS（Remain） |
|:----|:-----|:-------------|:--------------|
| 踩刹车 | 横向**保持**激活 | 横向**暂停** | 横向**保持**激活 |
| 松开刹车 | 横向仍激活 | 横向**自动恢复** | 横向仍激活 |
| 驾驶员感受 | OP 始终控制方向盘 | 刹车时完全手动，恢复后自动 | OP 始终控制方向盘 |
| **安全风险** | 踩刹车时转向干预可能让驾驶员意外 | 更低 | 同 ALKA |

### 7.4 场景四：转向灯操作

```
驾驶员操作：打左/右转向灯 → 变道 → 关闭转向灯
```

| 阶段 | ALKA | MADS |
|:----|:-----|:-----|
| 打转向灯 | 无特殊处理（不检查 blinker） | `blinker_pause_lateral` → 暂停横向 |
| 变道中 | 可能抵抗驾驶员转向（需用力克服） | 横向暂停 → 轻松手动变道 |
| 关闭转向灯 | 保持横向激活 | 自动恢复（blinker 结束→恢复 latActive） |
| **结论** | 可能需要驾驶员用力 override | 更自然的变道体验 |

### 7.5 场景五：门开/安全带事件

| 事件 | ALKA | MADS |
|:----|:-----|:-----|
| **门开** | `alka_active=False`（条件检查 `doorOpen`）→ `latActive=False` | `doorOpen` 事件→ `paused` 状态 → `latActive=False` |
| **安全带解开** | `alka_active=False`（条件检查 `seatbeltUnlatched`） | 事件处理→ 替换为 `silentDoorOpen` → 退出或暂停 |
| **恢复** | 需要重新按 MAIN 激活 | 自动从 paused 恢复（条件满足时） |

---

## 8. 综合推荐

### 8.1 选择 ALKA 的场景

- 想要**最简单、最直接**的全时横向控制
- 习惯 MAIN 按钮切换，不介意刹车时横向保持激活
- 不需要刹车暂停/保持的可配置性
- 不需要 UEM 统一接合功能
- 偏好轻量级代码，减少引入 bug 的风险

### 8.2 选择 MADS 的场景

- 想要**完整的全时横向控制功能集**
- 需要**刹车三种模式**（特别是 Pause 模式，更接近人类驾驶习惯）
- 需要 **UEM（统一接合模式）**，让巡航按键一次性接合所有控制
- 需要 **LKAS 按钮作为主要交互方式**
- 需要更**明确的状态区分**（4 种 UI 状态）
- 不介意稍高的复杂度

### 8.3 Corolla TSS2 推荐配置

| 功能 | ALKA 推荐 | MADS 推荐 |
|:----|:---------|:---------|
| **横向模式** | ALKA = ON | MADS = ON |
| **UEM** | 不存在 | ON（解决接合声音问题）|
| **刹车模式** | 固定 Remain | Pause（模式 1） |
| **MadsMainCruiseAllowed** | 不存在 | ON（Corolla 无 LKAS 按钮替代方案） |
| **NNLC** | 需确认模型文件存在 | ON（Corolla 有专用模型） |
| **学习成本** | 低 | 中 |

---

## 9. 总结

| 场景体验评分 | ALKA | MADS |
|:-----------|:----:|:----:|
| 上手简单度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 刹车时自然感 | ⭐⭐（固定保持） | ⭐⭐⭐⭐（可配 Pause） |
| 变道体验 | ⭐⭐（抵抗转向） | ⭐⭐⭐⭐（blinker 暂停） |
| 状态清晰度 | ⭐⭐⭐（3 种状态） | ⭐⭐⭐⭐⭐（4 种状态） |
| 声音反馈一致性 | ⭐⭐⭐⭐（无 UEM 问题） | ⭐⭐⭐（UEM 影响声音） |
| 安全性（冗余设计） | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Corolla 适配度 | ⭐⭐⭐⭐（简化方案） | ⭐⭐⭐⭐⭐（完整方案） |

**一句话总结**：ALKA 简单直接，适合"开箱即用"的用户；MADS 功能完备，适合愿意花时间配置以获得最佳体验的用户。
