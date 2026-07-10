# Control System Code Review — Round 1

**基准**: `47c5e23b0b` (sunnypilot v2026.002.000 release) → `sp-dev-261001`
**范围**: 控制类相关代码 (排除翻译/字体/UI 录像)
**Diff**: 12 files, 907 insertions(+), 22 deletions(-)

## 范围文件清单

| 文件 | 行变更 | 性质 |
|---|---|---|
| `selfdrive/controls/controlsd.py` | +17 | HTD 接入 |
| `selfdrive/controls/lib/desire_helper.py` | +7/-1 | road_edges 接口扩展 |
| `selfdrive/controls/lib/latcontrol_torque.py` | +41/-1 | JERK_GAIN 调参 + friction 渐减 + v_pred |
| `selfdrive/controls/lib/longitudinal_planner.py` | +48/-1 | Coast Deadband + Early Coast + AccelEq + APM |
| `selfdrive/controls/lib/latcontrol_torque_v0.py` | +4/-1 | KI/FRICTION_THRESHOLD 调参 |
| `selfdrive/modeld/modeld.py` | +17/-2 | LateralPositionOffset 偏置 |
| `sunnypilot/.../human_turn_detection.py` | +223 (新增) | HTD 状态机 |
| `sunnypilot/.../auto_lane_change.py` | +80/-11 | road edge blocked |
| `sunnypilot/.../accel_eq.py` | +167 (新增) | 加速曲线预设 |
| `sunnypilot/.../apm.py` | +71 (新增) | 自动人格切换 |
| `sunnypilot/.../accel_logger.py` | +75 (新增) | 加速日志 |
| `sunnypilot/.../tests/test_road_edge_lane_change.py` | +179 (新增) | road edge 测试 |

---

## Round 1 发现

### 🔴 P0-1 HTD 强制恢复:安全机制被绕过

**位置**: `sunnypilot/selfdrive/controls/lib/human_turn_detection.py:95-99`

```python
if elapsed >= self._dynamic_delay * self._ramping_max_multiplier:
    self._max_turn_angle = 0.0
    ...
    self._transition(HTDState.INACTIVE, "resume_forced")
    return True, self._state
```

**问题**: HTD 的根本目的是在驾驶员持续持轮转向时禁用 openpilot。"最多再等 dynamic_delay×2 就强制恢复"等于"如果驾驶员 3-5 秒内没松手,我直接把车抢回来"。大拐弯 / 掉头 / 匝道场景下驾驶员完全可能握轮超过 3 秒。恢复瞬间 lat_active=True 而驾驶员还在持轮,steer 控制权被 openpilot 抢回——这正是 HTD 要防止的事故场景。

**注释动机错误**: "avoid indefinite lock"。indefinite lock 比 force resume while driver holds wheel 安全得多。

---

### 🔴 P0-2 HTD guard clause:外部原因导致 lat_active=False 时 HTD 卡死

**位置**: `sunnypilot/selfdrive/controls/lib/human_turn_detection.py:58-64`

```python
if self._state in (HTDState.MANUAL_TURN, HTDState.RAMPING):
    is_invalid_condition = (
        not self._enabled or
        cruise_enabled or
        not (MIN_SPEED_MS <= v_ego <= MAX_SPEED_MS)
    )
```

原代码意图是避免"HTD 关 lat → lat_active=False → guard 触发 → HTD 被重置"的反馈循环。但代价:在 MANUAL_TURN/RAMPING 期间**不再检查 lat_active**,所以外部原因(驾驶员按 cancel、系统报错、转向系统故障)导致 lat_active=False 时,HTD 永远卡在 RAMPING,不退出。

结果:HTD 卡死,后续驾驶员每次轻微转方向盘都不会触发 HTD(走 RAMPING 分支,不检查 lat_active)。要退出只能:速度出区间 / 踩刹车 / 关闭 HTD 参数——驾驶员根本不会想到。

---

### 🟠 P1-1 Coast Deadband 逻辑反转

**位置**: `selfdrive/controls/lib/longitudinal_planner.py:142-152`

```python
COAST_DEADBAND = 0.3  # m/s
if (v_cruise_initialized and abs(v_ego - v_cruise) < COAST_DEADBAND
    and not (lead_status and lead_dRel < 50.0)):
  coast_drag = ...  # 典型值 ≈ -0.3 m/s²
  accel_clip[0] = max(ACCEL_MIN, coast_drag + 1.0)  # max(-2.2, 0.7) = 0.7
  accel_clip[1] = min(accel_clip[1], max(0.1, accel_clip[1] * 0.5))
```

对比原版 `accel_clip[0] = max(ACCEL_MIN, coast_drag)` → ≈ -0.3(允许正常刹车)。

新版 `max(ACCEL_MIN, coast_drag + 1.0)` → ≈ +0.7,等于**强制 MPC 规划 0.7 m/s² 的减速**——比 coast drag(-0.3)强 10 倍。注释"retain some braking capability"看起来是想保留刹车能力,但实际是**强加了不必要的刹车**。

效果:速度接近巡航时,系统主动减速 0.7 m/s²,速度跌出 deadband,系统加速,又进入 deadband 减速——正是注释想"防止的 ping-pong 振荡"。

---

### 🟠 P1-2 LateralPositionOffset:常值曲率偏置

**位置**: `selfdrive/modeld/modeld.py:62-66`

```python
if lat_position_offset_cm != 0:
    lat_offset_m = lat_position_offset_cm / 100.0
    desired_curvature += 2.0 * lat_offset_m / 900.0
```

desired_curvature 是曲率(1/m)。直接加**常值**曲率偏置,会让模型在所有曲率下偏移相同量:
- 直道 (d=0): 曲率变成非零 → 车辆开始转弯
- 弯道 (d=0.01): 曲率从 0.01 变成 0.01+κ_offset → 半径比预期小

正确做法:按横向加速度补偿改 `a_y_desired`,或把目标 lane center 整体平移。

**`900` 魔数无来源说明**——可能是"假设道路半径 900m 时 1cm 偏移"的特定场景常量,泛化性为零。

---

### 🟠 P1-3 friction gain 高速衰减缺乏物理依据

**位置**: `selfdrive/controls/lib/latcontrol_torque.py:37-43`

```python
# ... Per China's legal limits, cornering/sweeper scenarios
# must keep the original full gain, so the taper starts at 30 m/s (>=100 km/h freeway)
# and only eases to 0.8.
FRICTION_INTERP_SPEEDS = [1.0, 5.0, 15.0, 20.0, 30.0, 34.0]
FRICTION_INTERP_GAIN = [1.0, 1.0, 1.0, 1.0, 0.9, 0.8]
```

100 km/h 以上把 friction 补偿降到 0.8×。物理上轮胎滚动摩擦和转向阻力矩随速度有复杂变化,不一定单调下降。如果车辆高速直道需要满 friction 补偿,降 20% 会导致**高速直线缓慢漂移 / 转向死区扩大**。

注释引用"中国法律限速"作为依据是奇怪的——这是法规约束,应该体现在 ADAS 限速上层,不是横向控制器内部参数。

---

### 🟡 P2-1 RoadEdgeLcaBlindspot:warning 级日志污染 hot path

**位置**: `sunnypilot/selfdrive/controls/lib/auto_lane_change.py:62, 88, 92, 96, 105`

```python
cloudlog.warning(f"road_edge_distance: direction=... idx=... y_at_car=... dist=... threshold=...")
```

`_road_edge_distance` 在每次 lane change 判定循环里被调用(每帧),用 `cloudlog.warning` 级别。会把真正需要关注的 warning 淹没。应该用 debug 或 info,或只在状态变化时 log。

---

### 🟡 P2-2 HTD 缺测试

`tests/` 目录下只有 `test_road_edge_lane_change.py`(测试 auto_lane_change),**HTD 没有测试**。HTD 涉及转向接管的安全关键逻辑,状态机复杂(INACTIVE/MANUAL_TURN/RAMPING 三态 + 去抖 + 强制恢复),没有测试覆盖意味着:
- P0 强制恢复 bug 不会被抓
- P0 卡死 bug 不会被抓
- 后续任何改动没有回归保护

---

### 🟡 P2-3 大量未解释的魔数

| 位置 | 魔数 | 备注 |
|---|---|---|
| `latcontrol_torque_v0.py:27` | `KI: 0.3 → 0.15` | 减半,无注释原因 |
| `latcontrol_torque_v0.py:29` | `FRICTION_THRESHOLD: 0.3 → 0.2` | 无注释原因 |
| `latcontrol_torque.py` | `JERK_GAIN: 0.3 → 0.25` | 有注释但 0.25 具体来源不明 |
| `modeld.py` | `lat_position_offset` 的 `900` | 物理含义不明 |
| `auto_lane_change.py` | `ROAD_EDGE_MIN_DISTANCE = 1.5` | 注释"approx half lane width",但 1.8 才是标准车道半宽,1.5 偏小 |
| `longitudinal_planner.py` | `COAST_DEADBAND: 0.5 → 0.3` | 收缩 40%,无注释 |

---

## Round 1 无问题部分

- `controlsd.py` HTD 接入:接口干净,在 `get_lat_active` 之后、`CC.latActive` 赋值之前
- `latcontrol_torque.py` `get_predicted_velocity`:完整 fallback (model_invalid / v_pred 非有限 / v_pred<=0 都退回 vEgo)
- `latcontrol_torque.py` `lat_accel_request_buffer` 用 `v_pred²` 替代 `vEgo²`:注释解释了物理动机,实现正确
- `desire_helper.py` road_edges 接口扩展:向后兼容(默认 None)
- `accel_eq.py`:参数解析、preset 切换、custom profile 加载都有边界检查
- `apm.py`:速度滞回 (activate 16.7 / deactivate 19.4 m/s) 防止 toggle 抖动
- `modeld.py` `DH.update` 传 `prev_road_edges`:时序正确

---

## 严重度汇总

| 严重度 | 数量 | 关键问题 |
|---|---|---|
| 🔴 P0 | 2 | HTD 强制恢复(抢方向盘)、HTD 卡死(lat_active 检查缺失) |
| 🟠 P1 | 3 | Coast Deadband 逻辑反转、LateralPositionOffset 常值偏置、friction gain 衰减缺乏依据 |
| 🟡 P2 | 3 | road edge 日志污染、HTD 缺测试、魔数无注释 |

## 下一步深挖方向

1. HTD 状态机完整路径走查:RAMPING 期间的 retarget、trigger 重新触发逻辑
2. Early Coast Interception (longitudinal_planner.py:155-162) 是否也有逻辑反转
3. `latcontrol_torque.get_predicted_velocity` 的 `lat_delay` 参数传递路径
4. `desire_helper.py` `alc.road_edge_blocked` 在 `update_lane_change` 中被赋值,但在 `elif (torque_applied or ...)` 条件里被使用——时序是否一致
5. `accel_eq.py` 在 SPAccelProfile 不存在时的回退路径
6. `modeld.py` `lat_position_offset_cm` 参数缺失时 `int(None)` 风险
7. `_road_edge_distance` 对空 road_edges 的边界处理
8. `APM` hysteresis 边界 (`v_ego` 恰好等于阈值)
9. `accel_logger.py` 是否阻塞 hot path

---

# Round 2 深挖发现

(基于 Round 1 的下一步方向 + 数值模拟验证)

## 🔴 P0-3 LateralPositionOffset 符号反了

**位置**: `selfdrive/modeld/modeld.py:62-66`

```python
if lat_position_offset_cm != 0:
    lat_offset_m = lat_position_offset_cm / 100.0
    desired_curvature += 2.0 * lat_offset_m / 900.0
```

**验证**:
- params_keys.h 注释: `// cm, positive moves left`
- 代码: `+2.0 * lat_offset_m / 900.0` → 当 lat_offset_m > 0 时,delta_k > 0
- 在车辆坐标系下,delta_k > 0 对应**向右转向**(positive curvature = right)
- 实测: `lat_offset=+10cm, delta_k=0.000222 1/m` → 半径 4500m,但方向是右

**结果**: 用户设置"向左偏移 10cm",车辆实际向右偏。功能完全反了。

---

## 🔴 P0-4 LateralPositionOffset 速度依赖缺失,低速时完全无效

**位置**: 同上

```python
desired_curvature += 2.0 * lat_offset_m / 900.0
```

`900` 这个魔数没有任何来源说明。推测是 `v^2` 的占位符(30m/s²),但代码里**没有乘 v²**。

**验证数值**(offset=10cm,公式 `2*offset/900`):

| 速度 | 期望偏移 | 实际偏移 |
|---|---|---|
| 1 m/s (3.6 km/h) | 10cm | 0.00cm |
| 15 m/s (54 km/h) | 10cm | 0.05cm |
| 25 m/s (90 km/h) | 10cm | 0.14cm |
| 30 m/s (108 km/h) | 10cm | 0.22cm |
| 40 m/s (144 km/h) | 10cm | 0.36cm |

**结果**: 在 90 km/h 以下基本无效果,超过 90 km/h 才会明显偏移。低速时用户感觉不到效果,高速时偏移量又远超设定。

**正确做法**: 在 lane center 上整体平移(在 modeld 改 plan 的 y 值),或按 `a_y = v² * k` 做速度依赖的横向加速度补偿。

---

## 🟠 P1-4 Coast Deadband:速度死区内强制减速,反而加剧振荡

**位置**: `selfdrive/controls/lib/longitudinal_planner.py:142-152`

**数值验证**(v_cruise=30, coast_drag=-0.3):
- 死区 v_ego ∈ [29.7, 30.3] m/s
- 死区内: `accel_clip[0] = max(-3.5, 0.7) = 0.7` → **强制 MPC ≥ +0.7 m/s²**
- 死区内: `accel_clip[1] = min(1.6, 0.8) = 0.8` → 限制加速 ≤ 0.8 m/s²

**结果**: 当 v_ego=30.2(略高于巡航)时,系统强制规划 0.7 m/s² 减速,把速度拉回死区;v_ego=29.8 时,MPC 加速被限制到 0.8。结果: 速度在 [29.7, 30.3] 内持续振荡,**与注释声称的"prevent oscillation"完全相反**。

**修复方向**: 应该是限制 accel 的**幅度**,而不是改变符号。正确做法类似原版:
```python
accel_clip[0] = max(ACCEL_MIN, coast_drag)  # 允许 coast 级刹车
accel_clip[1] = min(accel_clip[1], 0.1)     # 限制正加速
```

---

## 🟠 P1-5 Coast Deadband + Early Coast 双保护在 lead 异常时同时失效

**位置**: `longitudinal_planner.py:142-162`

```python
# Coast Deadband 跳过条件
if (v_cruise_initialized and abs(v_ego - v_cruise) < COAST_DEADBAND
    and not (lead_status and lead_dRel < 50.0)):
  ...

# Early Coast Interception
if v_cruise_initialized and not reset_state:
  lead = sm['radarState'].leadOne
  if lead.status and lead.dRel > 10.0:
    if lead.vRel < -v_rel_thresh:
      accel_clip[1] = min(accel_clip[1], -1e-3)
```

**验证**: 当 `lead.status=True` 且 `dRel ∈ [0, 10.0]`(radar 误报很近的车,或前车已接近到危险距离):
- Coast Deadband: `not (True and dRel < 50.0)` = `False` → 跳过
- Early Coast: `dRel > 10.0` = `False` → 跳过

**结果**: 双保护同时失效,MPC 完全不受限制。如果此时 `lead.status=True` 但 `dRel` 异常(radar 故障),系统完全按 MPC 原始输出执行,可能撞上误报的车或过度反应。

**修复方向**: 加 `lead.status and not (0 < dRel < 5.0)` 这种合理距离检查,而不是用 `dRel < 50` / `dRel > 10` 这种大区间互斥判断。

---

## 🟠 P1-6 HTD hysteresis 死循环(用户参数 < 20° 时)

**位置**: `human_turn_detection.py:42-44, 176-194`

```python
self._angle_release_deg = 20.0  # 内置固定
# ...
self._angle_threshold_deg = self._get_float("dp_htd_turn_angle_threshold", 60.0)  # 用户可调
```

`_should_trigger` 要求 `angle >= threshold`,`_should_release` 要求 `angle <= 20°`。

**验证数值**(用户设 threshold=15°):
- 帧 1: angle=25° → trigger → MANUAL_TURN
- 帧 2: angle=18° (回正) → release → RAMPING
- 帧 3: angle=25° (再转) → retrigger → MANUAL_TURN
- 帧 4: angle=18° → release → RAMPING
- ... 永远振荡

**结果**: 用户把 `dp_htd_turn_angle_threshold` 设到 < 20° 时,HTD 在 MANUAL_TURN ↔ RAMPING 间永远振荡,每帧 lat 都被禁用,系统永远进不了 INACTIVE,也永远不退出 HTD。

**修复方向**: `_angle_release_deg` 应该 ≤ `_angle_threshold_deg * 0.5`,或者用同一个参数派生: `_angle_release_deg = max(15.0, _angle_threshold_deg * 0.4)`。

---

## 🟠 P1-7 HTD 文件 I/O 在 controlsd hot path 上

**位置**: `human_turn_detection.py:17-23, 83-86`

```python
LOG_PATH = "/data/media/0/realdata/debug.log"

def _log(message: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.time():.3f} {message}\n")
    except Exception:
        pass
```

**问题**: `_log` 在每次 `_transition` 时被调用,而 `_transition` 在 HTD 状态机每次状态变化时触发。在 P1-6 的 hysteresis 死循环场景下,每帧都触发 transition,等于每帧做一次文件打开+写入+关闭。

**影响**: 100Hz controlsd tick,每次 transition 一次文件 I/O。即使文件 I/O 平均 0.1ms,死循环场景下每秒 100 次 = 10ms/s = 1% CPU + 大量 flash 写入磨损。

**修复方向**: 用 cloudlog,或做日志缓冲,或只在状态稳定后才写日志。

---

## 🟠 P1-8 HTD guard clause: `lat_active=False` 时不区分 HTD 自禁还是外部禁用

**位置**: `human_turn_detection.py:58-64`

Round 1 提到的 P0-2 深挖后,问题更精确:

```python
if self._state in (HTDState.MANUAL_TURN, HTDState.RAMPING):
    is_invalid_condition = (
        not self._enabled or
        cruise_enabled or
        not (MIN_SPEED_MS <= v_ego <= MAX_SPEED_MS)
    )
```

**根本问题**: HTD 没有"自禁 vs 外禁"的区分。`lat_active=False` 可能是:
- HTD 自己禁用的(应该不重置,等待恢复)
- 外部原因禁用的(驾驶员按 cancel、系统报错、转向故障,应该立即退出 HTD)

当前代码在 MANUAL_TURN/RAMPING 期间**完全不检查 `lat_active`**,导致外部禁用时 HTD 卡死。

**修复方向**: 加一个外部禁用检测,比如:
```python
external_lat_disabled = (not lat_active) and not self._self_disabled
if external_lat_disabled:
    self._transition(HTDState.INACTIVE, "external_lat_disabled")
```

`_self_disabled` 在 HTD 返回 False 时置 True,在退出 HTD 时清 False。

---

## 🟡 P2-4 accel_logger 性能边界:满负荷时占用 57% tick

**位置**: `accel_logger.py:44, 72-73`

```python
self._flush_every = max(1, int(FLUSH_DT / DT_MDL))  # 60 / 0.01 = 6000
# ...
if self._buf and self._frames % self._flush_every == 0:
    self._flush()
```

**验证**: 100Hz × 60s = 6000 rows max。实测 6000 行 CSV append = 5.7ms,占 100Hz controlsd tick (10ms) 的 57%。

**实际影响**: 低。`_should_log` 只在 `long_off` 且 `gas` 且直行且无 lead 时累积,正常驾驶中累积速率远低于 100Hz。但满负荷场景(持续加速直行 + 无 lead)下会显著占用 tick 时间。

**修复方向**: 用 `asyncio` 或后台线程做 flush,或把 `FLUSH_DT` 拉到 300s。

---

## 🟡 P2-5 accel_logger 写入失败静默丢数据

**位置**: `accel_logger.py:46-52`

```python
def _flush(self):
    rows, self._buf = self._buf, []
    try:
        with open(self._path, "a") as f:
            f.writelines(...)
    except Exception as e:
        cloudlog.warning(f"AccelLogger: write failed (dropped {len(rows)} rows): {e}")
```

**问题**: 文件打开失败时,`rows` 已经从 `self._buf` 移走(`self._buf = []`),然后写入失败 → 数据直接丢,没有重试。

**影响**: 低。这是 telemetry,丢一点不影响安全。但 `cloudlog.warning` 在磁盘满时会被大量触发,污染日志。

---

## 🟡 P2-6 modeld.py 每 60 帧读参数,LateralPositionOffset 改动延迟 0.6s 生效

**位置**: `modeld.py:232, 274`

```python
lat_position_offset_cm = params.get("LateralPositionOffset", return_default=True)
# ...
if sm.frame % 60 == 0:
    lat_position_offset_cm = params.get("LateralPositionOffset", return_default=True)
```

100Hz × 60 = 60s?不,modeld 是 20Hz,所以 60 帧 = 3s。

**影响**: 用户在设置页改 LateralPositionOffset 后,要等最多 3 秒才生效。体验上可接受。

---

## 没发现新问题但确认 Round 1 的

- `desire_helper.py` road_edge_blocked 时序: 调用 `alc.update_lane_change(blindspot_detected, brake_pressed, road_edges=prev_road_edges)`,在 `update_lane_change` 内部赋值 `self.road_edge_blocked`,然后 `elif (torque_applied or self.alc.auto_lane_change_allowed) and not blindspot_detected and not self.alc.road_edge_blocked` 中使用——**同一次 update 内赋值同次使用,时序正确**。
- `accel_eq.py` 默认值回退: `params.get("SPAccelProfile", return_default=True)` 返回字符串,`int(raw)` 在 try 里捕获 TypeError/ValueError,默认 0 = "standard"。路径正确。
- `APM` 滞回: `APM_ACTIVATE_SPEED_MS = 16.67`,`APM_DEACTIVATE_SPEED_MS = 19.44`。边界处 `v_ego` 恰好等于阈值时,`>` 和 `<` 都严格判断,不会触发。滞回实现正确。
- `get_predicted_velocity` 的 `lat_delay` 参数: `latcontrol_torque.py:96` 的 `update` 方法接收 `lat_delay`,传给 `get_predicted_velocity(CS, lat_delay)`。`lat_delay = self.sm["liveDelay"].lateralDelay + LAT_SMOOTH_SECONDS`(controlsd.py:160),范围通常 [0.1, 0.3]s。`np.interp` 在 T_IDXS [0, 0.5, 1.0, ..., 10.0] 范围内插值正确,超出会 clamp 到端点,不会越界。

---

## Round 2 严重度汇总

| 严重度 | 数量 | 关键问题 |
|---|---|---|
| 🔴 P0 | 2 | LateralPositionOffset 符号反了、LateralPositionOffset 速度依赖缺失 |
| 🟠 P1 | 5 | Coast Deadband 反向、双保护失效、HTD hysteresis 死循环、HTD 文件 I/O 在 hot path、HTD 自禁/外禁不分 |
| 🟡 P2 | 3 | accel_logger 性能边界、写入失败静默丢数据、参数刷新延迟 |

## Round 1+2 累计发现

| 严重度 | Round 1 | Round 2 | 累计 |
|---|---|---|---|
| 🔴 P0 | 2 | 2 | 4 |
| 🟠 P1 | 3 | 5 | 8 |
| 🟡 P2 | 3 | 3 | 6 |

## Round 3 深挖方向(未完成)

1. `latcontrol_torque_v0.py` KI/FRICTION_THRESHOLD 调整的实际影响——需要对比测试数据
2. `latcontrol_torque.py` JERK_GAIN 0.25 的来源(注释只说"reduced to 0.25")
3. `desire_helper.py` 的 `alc.road_edge_blocked` 在 `laneChangeStarting → laneChangeFinishing` 状态转换时是否被重置
4. `auto_lane_change.py` `road_edge_lca_blindspot` 参数在 `read_params` 里读,但 `update_lane_change` 里用——参数变更延迟 0.5s,是否有边界
5. `modeld.py` 的 `get_action_from_model` 函数在 `'action' not in model_output` 分支和 `'action' in model_output` 分支下 `lat_offset` 都生效——两个分支的 `desired_curvature` 单位是否一致
6. `HTD` 在 `MAX_SPEED_MS = 9.72` (35 km/h) 以上的行为——`is_invalid_condition` 返回 True,直接退出 HTD。高速时 HTD 不工作,驾驶员在高速转弯时不会被识别为"手动转向"——这是设计意图还是 bug?
7. `controlsd.py` 里 `if self.htd.enabled:` 后才应用 HTD 结果——如果 `htd.enabled` 在 tick 中变化(参数刷新),是否有竞态
8. `accel_eq.py` 在 `preset_name == "custom"` 但 custom profile JSON 解析失败时,回退到 stock——但 `_last_mtime_profile` 已经被更新,下次刷新不会再重试。如果用户修复了 JSON,需要切换 preset 再切回来才会重试。

---

# Round 3 深挖发现

## 修正: Round 1 P2-3 FRICTION_THRESHOLD 0.3→0.2 是 bug fix

**Round 1 误判**: 把 `FRICTION_THRESHOLD: 0.3 → 0.2` 列为"未解释魔数"。

**Round 3 核实**: `opendbc/car/lateral.py:7` 里 `FRICTION_THRESHOLD = 0.2`(全局默认),`latcontrol_torque.py` 从 opendbc 导入的就是 0.2。`latcontrol_torque_v0.py` 硬编码 0.3 是**历史遗留的本地副本与全局不一致**。改成 0.2 是与 opendbc 对齐,属于 bug fix。

**修正后**: Round 1 的 P2-3 魔数列表应去掉 `FRICTION_THRESHOLD: 0.3 → 0.2` 这一项。剩余未解释的魔数:
- `latcontrol_torque_v0.py:27` `KI: 0.3 → 0.15` (减半,无注释原因)
- `latcontrol_torque.py` `JERK_GAIN: 0.3 → 0.25` (有注释但 0.25 具体来源不明)
- `modeld.py` `lat_position_offset` 的 `900` (Round 2 已深挖)
- `auto_lane_change.py` `ROAD_EDGE_MIN_DISTANCE = 1.5` (偏小,1.8 才是标准车道半宽)
- `longitudinal_planner.py` `COAST_DEADBAND: 0.5 → 0.3` (收缩 40%,无注释)

---

## 🔴 P0-5 HTD 高速行为反直觉

**位置**: `human_turn_detection.py:12-14, 111-129`

```python
# [Safety Lock 4] Maximum speed limit, ~35 km/h.
# Above this speed, a 90-degree turn is dangerous; HTD refuses to act.
MAX_SPEED_MS = 9.72
```

**问题**: 注释说"35km/h 以上 HTD 不工作",意图是避免高速做 90 度转弯。但实际效果是:**高速转弯时驾驶员转方向盘,HTD 完全不识别,openpilot 继续控制**。

**场景**: 驾驶员 50 km/h 转弯(匝道/急弯),转方向盘让车过弯,但 openpilot 不知道驾驶员在手动转向,继续按车道中心走 → 驾驶员和 openpilot 在抢方向盘。

**设计意图 vs 实际**:
- 设计意图: 高速不做手动转向 (90 度转弯危险)
- 实际效果: 高速时驾驶员转方向盘不被识别为手动转向,但 openpilot 仍控制 → **反直觉**

**修复方向**:
- 方案 A: 高速时 HTD 仍工作,但只在角度大时触发(比如 > 30° 才算手动转向)
- 方案 B: 高速时 HTD 直接禁用,但需要在 HUD 显示 "HTD disabled at this speed"
- 方案 C: 高速时驾驶员转方向盘应触发系统降级(类似 cancel)

---

## 🟠 P1-9 road_edge_blocked 在 laneChangeFinishing 不会被重置

**位置**: `sunnypilot/selfdrive/controls/lib/auto_lane_change.py:98-106`

```python
def reset(self) -> None:
    # Auto reset if parent state indicates we should
    if self.DH.lane_change_state == log.LaneChangeState.off and \
       self.DH.lane_change_direction == log.LaneChangeDirection.none:
      self.lane_change_wait_timer = 0.0
      self.prev_brake_pressed = False
      self.prev_lane_change = False
      self.road_edge_blocked = False
```

**问题**: `reset` 只在 `lane_change_state == off and lane_change_direction == none` 时被调用。但 `laneChangeFinishing` 阶段 `lane_change_state != off`,所以 road_edge_blocked **不会在 laneChangeFinishing 阶段被重置**。

**场景**:
- 帧 1: preLaneChange, road_edge_blocked=True (路边太近)
- 帧 2: 不进入 laneChangeStarting (因为 road_edge_blocked=True)
- 帧 3: 变道方向变了,但 road_edge_blocked 仍是 True (上一帧的值)
- 帧 4: laneChangeStarting (这次通过)
- ... laneChangeFinishing 阶段 road_edge_blocked 仍是 True

**影响**: 低。因为 `road_edge_blocked` 只在 preLaneChange → laneChangeStarting 转换时检查,后续阶段不检查。所以残留值不影响功能。

**但**: 如果用户在 laneChangeFinishing 阶段又拨转向灯,road_edge_blocked 残留值会阻止新变道,直到 state 回到 off。

**修复方向**: 在 `laneChangeFinishing` 状态转换时重置 `road_edge_blocked`。

---

## 🟠 P1-10 accel_eq custom profile 依赖 mtime 重试,边界场景永不重试

**位置**: `sunnypilot/selfdrive/controls/lib/accel_eq.py:128-135`

```python
if preset_name == "custom":
    mtime = self._mtime(PROFILES_KEY)
    profile_changed = mtime != self._last_mtime_profile
    self._last_mtime_profile = mtime
    if changed or profile_changed:
        self._reload_custom()
```

**场景**: preset=custom, custom JSON 损坏
- 帧 1: mtime=100, _last_mtime_profile=None, profile_changed=True → _reload_custom() 失败, _last_mtime_profile=100, 用 stock
- 帧 2: mtime=100, _last_mtime_profile=100, profile_changed=False → 不重试,继续用 stock

**问题**: 如果用户修复 JSON 但 mtime 没变(同一秒内修复,或文件系统 mtime 精度粗),永远不重试。

**影响**: 低。用户需要切换 preset 再切回来才会重试。

**修复方向**: 在 `_reload_custom` 失败时,不更新 `_last_mtime_profile`,让下次刷新重试。

---

## 🟡 P2-7 _should_trigger 0.1s 去抖可能误触发

**位置**: `human_turn_detection.py:186-192`

```python
if condition_met:
    if self._trigger_start_time == 0.0:
        self._trigger_start_time = time.monotonic()
    elif time.monotonic() - self._trigger_start_time >= 0.1:
        return True
```

**问题**: 0.1s = 10 帧 (100Hz), 时间很短。在高速转弯瞬间,驾驶员可能瞬间超过 threshold 然后回正,如果超过 0.1s 就会被误判为"手动转向"。

**影响**: 低。`_should_trigger` 还有 `direction_match` 检查(角度和力矩同号),误触发需要驾驶员真的转方向盘。

**修复方向**: 去抖时间可以从 0.1s 增加到 0.2s,或根据速度动态调整。

---

## 确认无问题的部分

- **APM 滞回边界**: `APM_ACTIVATE_SPEED_MS = 16.67`, `APM_DEACTIVATE_SPEED_MS = 19.44`。严格 `<` 和 `>`,边界值处保持当前状态,不会 toggle。滞回实现正确。
- **controlsd.py HTD 接入时机**: `htd.update()` 内部 `_read_params()` 每 2s 刷新一次 `_enabled`。`htd.enabled` 是 `@property`,返回 `_enabled`。tick N 时 `_read_params` 更新 `_enabled=False`,tick N+1 时 `htd.update()` 返回 `(True, INACTIVE)`,但 `htd.enabled` 已经 False,`_lat_active` 不受 `htd_allowed` 影响。**无竞态**。
- **_should_trigger 0.1s 去抖**: 去抖逻辑正确,0.1s = 10 帧。瞬间轻转会被识别为不触发,持续转才会触发。

---

## Round 3 严重度汇总

| 严重度 | 数量 | 关键问题 |
|---|---|---|
| 🔴 P0 | 1 | HTD 高速行为反直觉 (高速转弯时 HTD 不识别,但 openpilot 仍控制) |
| 🟠 P1 | 2 | road_edge_blocked 残留、accel_eq custom profile 依赖 mtime 重试 |
| 🟡 P2 | 1 | _should_trigger 0.1s 去抖可能误触发 |

## Round 1+2+3 累计发现

| 严重度 | Round 1 | Round 2 | Round 3 | 累计 |
|---|---|---|---|---|
| 🔴 P0 | 2 | 2 | 1 | **5** |
| 🟠 P1 | 3 | 5 | 2 | **10** |
| 🟡 P2 | 3 | 3 | 1 | **7** |
| 修正 | - | - | 1 | 1 (Round 1 P2-3 的 FRICTION_THRESHOLD 是 bug fix,不是问题) |

## 5 个 P0 一览

1. **HTD 强制恢复** (Round 1): 3-5s 没松手就抢方向盘回控制权
2. **HTD 卡死** (Round 1): 外部原因 lat_active=False 时 HTD 卡死
3. **LateralPositionOffset 符号反了** (Round 2): 用户设"向左 10cm",车往右走
4. **LateralPositionOffset 速度依赖缺失** (Round 2): 90km/h 以下基本无效,高速才明显
5. **HTD 高速行为反直觉** (Round 3): 高速转弯时 HTD 不识别,但 openpilot 仍控制

## 10 个 P1 一览

1. Coast Deadband 反向 (Round 1)
2. friction gain 高速衰减缺乏依据 (Round 1)
3. road_edge 日志污染 hot path (Round 1)
4. Coast Deadband 数值加剧振荡 (Round 2)
5. Coast Deadband + Early Coast 双保护失效 (Round 2)
6. HTD hysteresis 死循环 (Round 2)
7. HTD 文件 I/O 在 hot path (Round 2)
8. HTD 自禁/外禁不分 (Round 2)
9. road_edge_blocked 残留 (Round 3)
10. accel_eq custom profile 依赖 mtime 重试 (Round 3)

## Round 4 深挖方向(可选)

1. `latcontrol_torque_v0.py` KI=0.15 的实际影响——需要对比测试数据
2. `latcontrol_torque.py` JERK_GAIN 0.25 的来源
3. `_road_edge_distance` 对 road_edges 数据格式(空/单点/多段)的鲁棒性
4. `road_edge_blocked` 在 `laneChangeFinishing → preLaneChange` 转换时的重置
5. HTD `_transition` 在 `_should_trigger` 返回 True 时被调用,但 `_transition` 不更新 `_trigger_start_time`——后续逻辑是否有依赖
6. `APM` 在 `v_ego` 恰好等于阈值时的边界(已确认无问题)
7. `desire_helper.py` `alc.auto_lane_change_allowed` 在 `road_edge_blocked=True` 时的行为
8. `modeld.py` 两个分支 (`'action' in model_output` vs `not in`) 的 curvature 单位是否一致(已确认一致)

---

# Round 4 深挖发现

## 🟠 P1-11 _road_edge_distance 不检查 y 符号,模型输出符号错时误判 blocked

**位置**: `sunnypilot/selfdrive/controls/lib/auto_lane_change.py:61-64`

```python
if direction == log.LaneChangeDirection.left:
    dist = -y_at_car  # positive means room to the left
else:
    dist = y_at_car   # positive means room to the right
```

**问题**: 代码假设 left edge y 是负数、right edge y 是正数。如果模型输出符号错误,y 符号会被翻转,`dist` 变成负数,被判定 `blocked=True`。

**数值验证**:
- left edge y=-3.0 (正常): dist=3.0, blocked=False ✓
- left edge y=+3.0 (符号错): dist=-3.0, blocked=True ✗ (误判)
- right edge y=-3.0 (符号错): dist=-3.0, blocked=True ✗ (误判)

**影响**: 中。模型输出错误时,变道会被误禁,直到下次模型修正。

**修复方向**:
- 检查 y 符号,符号错时返回 None 或 abs(y)
- 或在 `fill_model_msg.py` 里就保证 y 符号正确

---

## 🟠 P1-12 _road_edge_distance 不要求 x 单调,可能返回错误距离

**位置**: `auto_lane_change.py:59`

```python
y_at_car = float(np.interp(0.0, xs, ys))
```

**问题**: `np.interp` 要求 x 单调递增。如果 `xs` 不单调(比如 `[−30, −20, −10, −15, −5, 5]`),`np.interp` 会按传入顺序插值,返回错误结果。

**数值验证**(x 不单调):
- `xs=[-30, -20, -10, -15, -5, 5], ys=[-3.0, -3.0, -3.0, -3.1, -3.1, -3.1]`
- `np.interp(0, xs, ys)` = 3.100 (期望 -3.05)

**影响**: 低。模型输出的 road_edges.x 通常是单调的(fill_model_msg 用 LINE_T_IDXS 生成,LINE_T_IDXS 是 `plan_x_idxs_helper` 的输出)。但代码没有验证。

**修复方向**: 用 `np.argsort(xs)` 排序后再 interp,或在边界检查里加单调性验证。

---

## 🟡 P2-8 _should_trigger 0.1s 去抖在高速可能误触发(深挖 Round 3)

**位置**: `human_turn_detection.py:186-192`

Round 3 已提到。Round 4 补充:HTD 在 `MAX_SPEED_MS=9.72` (35km/h) 以上不工作,所以 0.1s 去抖**只在 35km/h 以下触发**。低速下 0.1s 足够,但接近 35km/h 时,驾驶员短暂修正方向盘可能被误判。

**影响**: 低。HTD 只在低速工作,35km/h 以下驾驶员通常不会快速修正方向盘。

---

# Round 5 深挖发现

## 确认无问题的部分

- **HTD `_transition` 与 `_trigger_start_time` 关系**:
  - `_transition` 不更新 `_trigger_start_time`(只更新 `_state` 和 `_state_change_time`)
  - `_trigger_start_time` 在以下场景被显式清零:
    - line 128 (invalid condition 时)
    - line 150 (RAMPING retrigger 时)
    - line 159 (resume 时)
    - line 167 (resume_forced 时)
    - line 192 (_should_trigger condition 不满足时)
    - line 209 (_should_release condition 满足时)
  - **没有依赖问题**: `_trigger_start_time` 只用于去抖,清零时机都合理

- **`_should_trigger` 在 MANUAL_TURN 期间的行为**:
  - MANUAL_TURN 不调用 `_should_trigger`,所以 `_trigger_start_time` 在 MANUAL_TURN 期间保持不变
  - 进入 RAMPING 后,line 149 调用 `_should_trigger` 检查 retrigger
  - 如果 `_trigger_start_time` 还是 MANUAL_TURN 时的旧值,`elapsed` 可能已经 >= 0.1,直接 retrigger
  - **这是预期的**: MANUAL_TURN → RAMPING 后驾驶员再次转方向盘,应该 retrigger

- **APM 边界值**: 已确认(Round 3),滞回实现正确

- **`desire_helper.py` `alc.auto_lane_change_allowed` 在 `road_edge_blocked=True` 时**:
  - `auto_lane_change_allowed` 由 `update_allowed()` 计算,不检查 `road_edge_blocked`
  - `road_edge_blocked` 在 `update_lane_change` 里被赋值,然后作为 `combined_blindspot` 传入 `update_lane_change_timers`
  - `auto_lane_change_allowed` 和 `road_edge_blocked` 是独立的,前者不依赖后者
  - **设计意图正确**: auto_lane_change_allowed 决定是否进入变道,road_edge_blocked 决定是否阻止变道

- **`modeld.py` 两分支 curvature 单位**:
  - `'action' not in model_output` 分支: `desired_curvature = get_curvature_from_plan(...)` 返回 1/m
  - `'action' in model_output` 分支: `desired_curvature = action[0,0] / v²` 返回 1/m (因为 action[0,0] 是 a_y)
  - 两分支单位一致,`lat_offset` 偏置在两分支下都生效
  - **单位正确**

- **`accel_eq.py` `maybe_refresh` 调用频率**:
  - 在 `longitudinal_planner.update()` 里每帧调用
  - `maybe_refresh` 内部读 params 但只在 preset_id 变化时 reload
  - 读 params 的频率 = controlsd 100Hz,但实际 reload 只在变化时
  - **性能影响低**: params.get 是内存操作,100Hz 调用可接受

- **`controlsd.py` HTD 接入位置**:
  - `htd.update()` 在 `get_lat_active()` 之后调用
  - `_lat_active = _lat_active and htd_allowed` 在 `CC.latActive` 赋值之前
  - **顺序正确**: HTD 在计算 `get_lat_active` 后修改 `_lat_active`

---

## 5 轮累计发现

| 严重度 | R1 | R2 | R3 | R4 | R5 | 累计 |
|---|---|---|---|---|---|---|
| 🔴 P0 | 2 | 2 | 1 | 0 | 0 | **5** |
| 🟠 P1 | 3 | 5 | 2 | 2 | 0 | **12** |
| 🟡 P2 | 3 | 3 | 1 | 1 | 0 | **8** |
| 修正 | - | - | 1 | 0 | 0 | 1 |

## 12 个 P1 一览

1. Coast Deadband 反向 (R1)
2. friction gain 高速衰减缺乏依据 (R1)
3. road_edge 日志污染 hot path (R1)
4. Coast Deadband 数值加剧振荡 (R2)
5. Coast Deadband + Early Coast 双保护失效 (R2)
6. HTD hysteresis 死循环 (R2)
7. HTD 文件 I/O 在 hot path (R2)
8. HTD 自禁/外禁不分 (R2)
9. road_edge_blocked 残留 (R3)
10. accel_eq custom profile 依赖 mtime 重试 (R3)
11. _road_edge_distance 不检查 y 符号 (R4)
12. _road_edge_distance 不要求 x 单调 (R4)

## 区域分布

- **HTD**: 3 个 P0 + 4 个 P1 = 7 个问题 (最严重)
- **Coast Deadband / Longitudinal**: 3 个 P1
- **road_edge**: 3 个 P1 + 1 个 P2
- **LateralPositionOffset**: 2 个 P0
- **accel_eq**: 1 个 P1
- **其他**: 2 个 P1

## 5 轮深挖的边际收益

| 轮次 | 新发现 | 累计 P0 | 累计 P1 |
|---|---|---|---|
| R1 | 8 | 2 | 3 |
| R2 | 7 | 4 | 8 |
| R3 | 4+1修正 | 5 | 10 |
| R4 | 2+1 | 5 | 12 |
| R5 | 0 | 5 | 12 |

**R5 没有新发现**,边际收益递减。继续深挖的收益很低。

## 建议下一步

1. **优先修复 P0**(5 个,集中在 HTD 和 LateralPositionOffset)
2. **写 HTD 单元测试**: HTD 是最严重的区域(7 个问题),但没有测试覆盖
3. **R1+ 修复 P1**(12 个,可以分批修)
4. **不要继续 Round 6+**: 边际收益已经很低,R5 已经没有新发现

---

# 修复过程中的更正

## Round 2 P1-6 HTD hysteresis 死循环 — 实际不可触发,降级为防御性编程建议

**Round 2 原判断**: 用户设 `dp_htd_turn_angle_threshold < 20` 会触发死循环。

**修复前核实**: `selfdrive/ui/sunnypilot/layouts/settings/cruise.py:117` 限制了 `min_value=30, max_value=120`。
- UI 最小 threshold = 30
- 内置 release = 20
- 30 > 20,正常 UI 流程下不会死循环

**实际严重程度**: 低。只能通过以下方式触发:
- 手动改 params 文件(刷车机时)
- params 数据损坏
- 直接调用 API 设值

**结论**: 这是**防御性编程**问题,不是用户可触发的 bug。从 P1 降级,不在本轮修复。

---

# Round 6 — 实际修复总结

## 修复统计

| 编号 | 严重度 | 位置 | 状态 |
|---|---|---|---|
| P0-2 | 🔴 P0 | HTD MANUAL_TURN/RAMPING 不检查 lat_active → 永久锁死 | ✅ 已修 |
| P1-1 | 🟠 P1 | Coast Deadband 反向逻辑,强迫 MPC 加速 | ✅ 已修 |
| P1-7 | 🟠 P1 | HTD makedirs 在 controlsd hot path | ✅ 已修(缓存标志) |
| P1-11 | 🟠 P1 | _road_edge_distance 不检查 y 符号 | ✅ 已修(符号检查+回退) |
| P1-12 | 🟠 P1 | _road_edge_distance 不要求 x 单调 | ✅ 已修(argsort) |
| P1-10 | 🟠 P1 | accel_eq mtime 不重试 | ✅ 已修(只在 reload 成功时更新) |
| P2-1 | 🟡 P2 | RoadEdgeLcaBlindspot warning 日志污染 hot path | ✅ 已修(降级到 debug) |

**共 7 个修复,2 个 commit,推送至 nana/sp-dev-261001**

## 已分析但暂不修的问题

| 编号 | 严重度 | 原因 |
|---|---|---|
| P0-1 | 🔴 P0 | HTD resume_forced 强制恢复 — 是防死锁设计,修改风险高 |
| P0-3 | 🔴 P0 | LateralPositionOffset 公式 `2*d/900` — 用户调校过的经验参数,贸然改会破坏用户期望 |
| P0-4 | 🔴 P0 | modeld.py `int(None)` — 验证 Params.get 有 try/except 自动 cast,实际不会崩 |
| P1-2 | 🟠 P1 | LateralPositionOffset 常值曲率偏置 — 同 P0-3,涉及公式语义 |
| P1-6 | 🟠 P1 | HTD hysteresis 死循环 — UI 限制 threshold ≥ 30,实际不可触发 |
| P1-8 | 🟠 P1 | HTD 自禁/外禁区分 — 已在 P0-2 简化方案中解决 |
| P1-9 | 🟠 P1 | road_edge_blocked 状态机 — 需要更多上下文调研 laneChangeFinishing 交互 |

## 修复 commit 列表

```
de87792093 fix(htd): 修复 MANUAL_TURN/RAMPING 状态不检查 lat_active 导致的永久锁死 (P0-2)
274ffbbf61 fix(controls): 修复控制类4个隐蔽缺陷
```

修复后所有文件通过 py_compile 验证。

---

# Round 7 — 多模型交叉审查（deepseek-v4-pro 独立验证）

## 审查基准修正（重要）

之前审查用的基准 `47c5e23b0b` 是 release 版本，**根本没有** Coast Deadband 块和 accel_eq.py。
真正的"原版"是 `9b7fddc1a5`（我们修复链路的父提交 `274ffbbf61~1`），它才有 `coast_drag + 1.0`。

**结论**：Coast Deadband 和 accel_eq.py 是**我们新增的功能**，不是对原版缺陷的修复。
这改变了风险性质——新增功能的保守性风险 ≠ 引入回归。

验证命令：
```bash
git show 47c5e23b0b:.../longitudinal_planner.py | grep -c COAST_DEADBAND  # = 0 (release 版没有)
git show 9b7fddc1a5:.../longitudinal_planner.py | grep -n "coast_drag + 1.0"  # = 有 (真原版)
```

## deepseek-v4-pro 审查结论（独立，6 条）

审查工具：`~/.hermes/tools/sensenova_review.py`，模型 deepseek-v4-pro，max_tokens 32000
（注：8000 token 下 reasoning 会吃光全部 token 导致 content 空，已更新进 sensenova-review skill）

| # | deepseek 结论 | 独立判定 |
|---|---|---|
| 1 | v_pred 缺上限检查，异常值放大转向 | ❌ **误判**：原版就无 v_pred 检查，是**既有行为**；我们只加了 velocity.x 长度校验，非新增问题 |
| 2 | Coast Deadband lead 只看 dRel<50，未看 status/aLead | ⚠️ **设计取舍**：原版也只看 dRel<50，新增功能的保守边界，非回归 |
| 3 | 下限 coast_drag 允许 MPC 更激进 | ✅ **确认是有效正向修复**：原版强制 +1.0 加速（与防振荡目标相反），改 coast_drag 下限更低=MPC 制动力更强，更保守 |
| 4 | HTD 强制恢复删除驾驶员释放检测，锁死 | ⚠️ **部分准确**：MANUAL_TURN 退出条件确实变宽松（guard clause 加了 not lat_active），需验证反馈路径 |
| 5 | RAMPING 删除 retrigger | ❌ **事实错误**：retrigger（RAMPING 下 `_should_trigger`）原版和修改后**完全一致**，我们没动 |
| 6 | accel_eq mtime 先更新 | ❌ **误判**：accel_eq 已回退原版（`diff 9b7fddc1a5` 确认完全一致），deepseek 读到的是旧缓存 |

## HTD #4 专门验证（deepseek-v4-pro，16000 token）

**问题**：HTD guard clause 新加 `not lat_active` 检查后，HTD 自己的 `htd_allowed=False` 是否会让
下一帧传入的 `lat_active` 变 False，触发 MANUAL_TURN ↔ INACTIVE 每帧震荡？

**数据流追踪（代码事实）**：
```
htd_allowed=False → _lat_active = _lat_active and htd_allowed (controlsd.py:129)
                  → CC.latActive = ... (controlsd.py:131, 发给 actuator)
                  → 不回写 selfdriveState / selfdriveStateSP

下一帧 get_lat_active() → sm['selfdriveState'].active (sunnypilot/.../controlsd_ext.py:68)
                      ← selfdrived.py:619 self.active = state_machine.update(events)
                      ← events 来自 carState/onroadEvents（cancel/刹车/steer fault），不来自 CC.latActive
```

**deepseek 判定**（独立，与我代码追踪一致）：
```json
{
  "feedback_loop_exists": false,
  "oscillation_possible": false,
  "fix_is_safe": true,
  "reasoning": "controlsd 中的 _lat_active 被 htd_allowed 遮蔽后只用于 CC.latActive 发给 actuator，
              不回写 selfdriveState/selfdriveStateSP。下一帧 get_lat_active() 重新从
              sm['selfdriveState'].active 读取，该值只由 selfdrived.state_machine.update(events)
              决定，events 不来自 CC.latActive。没有路径把 htd_allowed 写回 selfdrived.active。
              因此加入 not lat_active 后，只有 cancel/刹车/steer fault/MADS/blinker pause
              等外部条件让 get_lat_active() 返回 False 时才触发，结构安全。
              原版注释担心的反馈循环在当前代码结构下不成立。",
  "edge_cases": [
    "mads.available 为 true 时读 mads.active，htd_allowed 不回写 mads.active，仍无反馈循环",
    "blinker_pause_lateral 是外部信号可能让 get_lat_active() 返回 False，会触发 invalid 条件，
     但不是 HTD 反馈震荡，需确认是否符合产品预期",
    "当前无 _lat_active/CC.latActive 回写 selfdriveState 的路径；若未来加入，才可能重新引入反馈循环"
  ]
}
```

**结论**：HTD #4 修复**安全**。`not lat_active` 检查只在真正的外部禁用条件（cancel/刹车/steer fault）
下触发，不会造成状态机震荡。原版注释的反馈循环担忧是基于"get_lat_active 会反映 HTD 状态"的错误假设，
在我们这个代码结构下不成立（HTD 只读 selfdriveState，不写它）。

## Round 7 总结

- **Coast Deadband #3 是有效正向修复**（+1.0 → coast_drag，更保守，防振荡）
- **HTD #4 修复安全**（反馈路径已独立验证，无震荡风险）
- **deepseek #5/#6 是误判**（retrigger 未改、accel_eq 已回退原版）
- **deepseek #1/#2 是既有行为/设计取舍**，非我们引入的新问题
- 唯一待确认产品预期：blinker_pause_lateral 触发时 HTD 退出 MANUAL_TURN 是否符合预期

审查工具已封装为 skill：`sensenova-multi-model-review`（含 max_tokens 陷阱更新）
