# 弯道减速压线问题分析与优化

> 适用版本：本仓库 `sp-dev` 分支（sunnypilot 风格扭矩控制 + OP 基础控制器）
> 关联提交：`e53cf7257f`（摩擦补偿随车速衰减）

## 目录

1. [问题描述](#1-问题描述)
2. [控制链路回顾](#2-控制链路回顾)
3. [根因分析](#3-根因分析)
4. [优化方案](#4-优化方案)
5. [实现说明](#5-实现说明)
6. [验证与调参](#6-验证与调参)
7. [风险与权衡](#7-风险与权衡)
8. [后续可研究方向](#8-后续可研究方向)

---

## 1. 问题描述

现象：车辆在**弯道中/入弯前减速**（制动或松油门滑行）时，横向位置偏离车道中心，出现**压线**。

- 压**内侧**线：车头向弯心"钻"，转向过度（过转/oversteer 趋势）。
- 压**外侧**线：车头跟不上弯道，转向不足（understeer 趋势）。

该现象尤其在"较高车速 + 入弯制动"组合下出现，与本仓库已实现的
"摩擦补偿随车速衰减"（高速直线蛇形晃动抑制）之间存在耦合，需要放在同一框架下分析。

## 2. 控制链路回顾

横向控制链路（`selfdrive/controls/controlsd.py` → `selfdrive/controls/lib/latcontrol_torque.py`）：

```
model_v2  (模型: 时间索引的规划轨迹 position/velocity/acceleration/curvature)
   │  ① 模型自带的期望曲率 desired_curvature (modeld.py:48-55, 用当前 vEgo 换算)
   ▼
controlsd.clip_curvature  (ISO jerk/加速度限幅, drive_helpers.py:26)
   ▼
LatControlTorque.update:
   ├─ future_desired_lateral_accel = desired_curvature * vEgo²        ←(本文件 关键)
   ├─ 存入 lat_accel_request_buffer (1s 环形缓存)
   ├─ expected_lateral_accel = buffer[-delay_frames]                  ←(延迟补偿, 纯时间)
   ├─ error = setpoint(expected) - measurement(实际κ * vEgo²)
   ├─ 前馈 ff = future_desired_lateral_accel - latAccelOffset ...     ←(本文件 关键)
   ├─ ff += friction_gain * get_friction(error + jerk前馈)            ←(已做速度衰减)
   └─ PID → torque_from_lateral_accel → 输出扭矩
```

关键点：

- 模型输出的轨迹是**按时间索引**的（`ModelConstants.T_IDXS`），天然携带规划减速信息。
- 但基础扭矩控制器里的所有 `vEgo²` 都用**当前速度**，未使用模型规划的**未来速度**。
- 延迟补偿时，`delay_frames` 只由 `lat_delay`（秒）换算，**是按时间索引的**；刹车时依然准确，
  因为模型轨迹本身是时间索引的（见 §3 论证）。

## 3. 根因分析

### 3.1 前馈/期望横向加速度用了"过大的当前速度平方"（主要根因)

入弯制动时：

```
实际所需横向加速度:  a_y,need = κ(当前点) * v(到达点)²          (v(到达点) < vEgo)
控制器请求:          a_y,req  = κ(当前点) * vEgo²                (vEgo 偏大)
```

- 前馈 `ff` 使用 `desired_curvature * vEgo²` → **旁路/前馈扭矩过大**。
- 延迟缓冲中的历史请求同样以当时的（更高）速度平方记录 → `expected_lateral_accel`
  是一个**锚定在高速上的陈旧目标**。

结果：控制器认为自己"没转够"/目标达不到 → 一直保持过大扭矩 → 弯中减速时持续
**过转**，车头向弯心钻 → 压**内侧**线。这正是社区常见的"刹车入弯压内线"。

> 对比：sunnypilot 自带的 NNLC 扩展早已在 `nnlc.py:115` 对未来采样时间做减速补偿
> `adjusted_future_times = t + 0.5*aEgo*(t/vEgo)`，说明上游项目认同"减速 → 参考量需
> 对齐更低速度"这个物理事实，但**基础扭矩控制器没有做等价补偿**。

### 3.2 纯时间延迟补偿在减速时是准确的（不是根因)

`expected_lateral_accel = buffer[-delay_frames]` 是**纯时间**延迟补偿。因为模型轨迹
是时间索引的，车辆实际减速到位置 P 的时间点 = 模型预测的对应时间点（在 MPC 精确执行
规划速度的前提下），所以时间索引延迟补偿**并不会**因刹车而错位。因此"缩短/加长 delay"
这类改动没有物理依据，**不建议实施**（将在 §4 中排除）。

### 3.3 摩擦衰减与弯中减速纠偏的矛盾（耦合点）

摩擦衰减的本意是抑制高速直线蛇形晃动，但摩擦项同时承担弯道中的**纠偏增益**
（在误差上叠加 `friction/latAccelFactor` 的额外比例增益）。若衰减曲线过早/过深
生效，会削弱中速连续弯道的纠偏能力——实测 70 km/h 连续弯压线即与此直接相关。

按中国法定限速梳理后的速度区间与设计目标：

| 工况 | km/h | 摩擦增益目标 |
|------|------|-------------|
| 山路/盘山连续弯 | 30–50 | 必须 = 1.0（原始） |
| 城市快速路连续弯（实测 70 km/h） | 60–80 | 必须 = 1.0（原始） |
| 高速普通段连续弯 | 80–100 | 轻微衰减（0.9） |
| 高速巡航 | 100–120 | 衰减到底（0.8） |

据此最终定为：**20 m/s（72 km/h）以下保持 1.0**（与原始逐位一致），
30 m/s（108 km/h）处 0.9，34 m/s（122 km/h）处 0.8 并钳制——衰减只在
合法高速段实质生效，压线敏感的中低速连续弯完全保留原始纠偏能力。
（见 §6 调参）

### 3.4 纵向转向耦合（次要，留作研究方向)

`limit_accel_in_turns`（longitudinal_planner.py:39-50）只限制**加速**时的总加速度预算，
防止打滑；对**减速**没有对称限制。制动入弯会产生载荷前移与横摆响应变化，理论上存在
低附着路面的耦合风险。但对称化限减速会削弱制动能力、引入安全风险，**当前不建议实施**
（见 §8）。

### 3.5 前馈 vs 误差结构的细节

延时采样：`lookahead_idx` 用于 jerk 前馈（`JERK_GAIN * desired_lateral_jerk`）。
当前实现中这个 jerk 项也是由"锚定高速度"的缓冲值导出的，减速时同样偏大。
把它与 §3.1 一起用"预测速度"修正后，jerk 前馈自然回落到正确量级。

## 4. 优化方案

| # | 方案 | 位置 | 状态 |
|---|------|------|------|
| 1 | **前馈/期望横向加速度改用模型预测速度** | `latcontrol_torque.py` | ✅ 实施 |
| 2 | 衰减曲线右移（摩擦衰减与弯道纠偏平衡） | `FRICTION_INTERP_*` | 调参项（默认不引入） |
| 3 | 纯时间延迟补偿的加减速修正 | `latcontrol_torque.py` | ❌ 无物理依据，排除 |
| 4 | 对称化 `limit_accel_in_turns` 限减速 | `longitudinal_planner.py` | ❌ 安全风险，暂不实施 |

### 方案 1 详细设计：用模型预测速度替代当前 vEgo²

- 模型规划的 `velocity.x`（m/s，按 `ModelConstants.T_IDXS` 按时间索引）已经内嵌了
  车辆将如何减速到达未来各点。
- 控制器请求的横向加速度应锚定在"执行转向命令后、车辆实际到达该曲率点时"的速度上，
  即 `lat_delay` 后的规划速度 `v_pred`：
  ```
  v_pred = interp(lat_delay, T_IDXS, model_v2.velocity.x)
  future_desired_lateral_accel = desired_curvature * v_pred²
  ```
- 这一值同时进入：前馈 `ff`、延迟缓冲（→ `expected_lateral_accel` / `setpoint` / jerk 前馈）。
  由于三者来自同一个 `future_desired_lateral_accel`，修正后**结构一致性保持**，不会产生
  ff 与 setpoint 的量纲错位。
- 模型无效/异常时回退到 `vEgo`，行为与现状完全一致，**零回归风险**。

## 5. 实现说明

新增方法（`latcontrol_torque.py`）：

```python
def get_predicted_velocity(self, CS, lat_delay):
  # 弯道减速时, 用模型规划的未来速度替代当前 vEgo 作为横向加速度的锚点速度,
  # 避免以偏大的 vEgo² 前馈/期望导致过转压内线。模型无效时回退当前速度。
  if not self.extension.model_valid:
    return CS.vEgo
  model_v2 = self.extension.model_v2
  if model_v2 is None or len(model_v2.velocity.x) < 2:
    return CS.vEgo
  v_pred = float(np.interp(lat_delay, ModelConstants.T_IDXS, model_v2.velocity.x))
  if not math.isfinite(v_pred) or v_pred <= 0.0:
    return CS.vEgo
  return v_pred
```

`update()` 中唯一改动点：

```python
v_pred = self.get_predicted_velocity(CS, lat_delay)
future_desired_lateral_accel = desired_curvature * v_pred ** 2
```

- 依赖 `self.extension.model_v2`：`controlsd.py:103` 对扭矩控制器无条件调用
  `update_model_v2`，运行时必然可用；测试/无模型环境回退 `vEgo`。
- 新增 import：`from openpilot.selfdrive.modeld.constants import ModelConstants`。

### 对 NNLC 的影响

`future_desired_lateral_accel` 会作为 `desired_lateral_accel` 传入扩展
（`latcontrol_torque.py:107`）。NNLC 开启时用其作为 NN 输入特征之一。
修正后传给 NN 的期望横向加速度更接近"减速后的真实需求"，量级上更准确；
NNLC 关闭（默认）时走基础路径，不受影响。

## 6. 验证与调参

### 6.1 自动测试

```bash
pytest selfdrive/controls/tests/test_latcontrol.py
```

该测试不注入 `model_v2`，因此 `get_predicted_velocity` 全程回退 `vEgo`，
行为与改动前一致，测试应保持通过。

### 6.2 实车/仿真验证清单

| 项 | 方法 | 预期 |
|----|------|------|
| 入弯制动不压内线 | 高速入弯带刹，观察轨迹 | 车头不再钻弯心 |
| 弯中恒速循迹 | 恒速过弯 | 与改动前一致（v_pred≈vEgo） |
| 出弯加速掠过弯 | 弯中加油门 | v_pred>vEgo → 参考略增，仍贴合此物理 |
| 直线/蛇形 | 高速直线 | 不劣于 `e53cf7257f` 表现 |
| NNLC 开启 | SP 设置开启 NNLC 复测 | 弯中表现更稳 |

### 6.3 主要调参旋钮

- `FRICTION_INTERP_SPEEDS / FRICTION_INTERP_GAIN`：若弯中减速纠偏偏弱，
  将衰减起点右移；若直线蛇形复发，左移/加深。
- `lat_delay` 插值时长：`lat_delay` 本身就是"命令生效时间"，无需新参数。

## 7. 风险与权衡

| 风险 | 等级 | 说明与缓解 |
|------|------|-----------|
| 模型无效时行为不变 | — | `get_predicted_velocity` 全程回退 vEgo，零回归 |
| NNLC 输入特征变化 | 低 | 特征更贴近物理真实；NNLC 默认关闭 |
| 前馈扭矩在高速制动入弯时"变小" | 低 | 这是本方案的**目的**(消除过转)，非副作用 |
| 低速(≤10 m/s) | 低 | v_pred≈vEgo，改动基本不生效 |
| 模型速度异常(如堵车急停) | 低 | `isfinite/≤0` 守卫回退 vEgo |

## 8. 后续可研究方向

1. **对称化转弯减速限制**（§4 方案 4）：需先建立低附着/高横向载荷下减速安全的试验数据，
   谨慎设计，不盲做。
2. **自动调整摩擦衰减曲线**：根据 `liveTorqueParameters` 或无人驾驶性能统计动态
   修正 `FRICTION_INTERP_GAIN`。
3. **把 v_pred 前馈思想推广到 v0.0 兼容层 / NNLC**：保持各版本语义一致。
4. **期望横向加速度整条链路的"预测速度"化**：`controlsd.py` 的 `measured_curvature`
   计算与 `modeld.py:48-55` 的 desiredCurvature 换算也使用当前 vEgo，可评估是否统一。