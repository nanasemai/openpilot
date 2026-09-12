# C3X 设备问题综合分析

## 1. 问题描述

在 Toyota Corolla TSS2 (2020-22) 上使用 C3X 设备运行 openpilot (sp-dev 分支, commit `e10a0bb9`) 时，出现以下问题：

1. **大拐弯时左侧压线** — 横向控制在大弯中持续禁用
2. **行程间通讯异常** — CAN 总线超时和进程间通讯错误

**设备信息:**
- IP: 192.168.77.132
- 版本: `2026.002.000`
- 车型: Toyota Corolla TSS2
- Panda 序列号: `120022000a51303436323838`

---

## 2. 问题一：HTD 大拐弯压线

### 2.1 HTD 状态机逻辑

HTD 状态机定义于 `sunnypilot/selfdrive/controls/lib/human_turn_detection.py`：

```
INACTIVE → MANUAL_TURN → RAMPING → INACTIVE
  ↑                          ↓
  └──── retrigger ───────────┘
```

| 状态 | 行为 | htd_allowed |
|------|------|-------------|
| INACTIVE | 等待触发条件 | True (允许横向) |
| MANUAL_TURN | 检测到手动转向 | False (禁用横向) |
| RAMPING | 驾驶员松开方向盘后的过渡期 | False (禁用横向) |

### 2.2 核心缺陷：RAMPING → INACTIVE 角度安全锁

**文件:** `sunnypilot/selfdrive/controls/lib/human_turn_detection.py:147-158`

```python
# 原代码（有 Bug）
elif self._state == HTDState.RAMPING:
    elapsed = time.monotonic() - self._state_change_time
    if elapsed >= self._dynamic_delay:
        if self._last_angle > self._resume_angle_lock_deg:  # 40.0
            return False, self._state  # ← 永久卡在 RAMPING！
        self._transition(HTDState.INACTIVE, "resume")
        return True, self._state
```

**`_resume_angle_lock_deg = 40.0`** 导致在大弯中方向盘角度持续高于 40° 时，HTD 永久停留在 RAMPING 状态，横向控制持续禁用。

### 2.3 次要缺陷：Guard Clause 反馈循环

**文件:** `sunnypilot/selfdrive/controls/lib/human_turn_detection.py:104-123`

```python
# 原代码（有 Bug）
is_invalid_condition = (
    not self._enabled or
    cruise_enabled or
    not lat_active or  # ← 反馈循环根源
    not (MIN_SPEED_MS <= v_ego <= MAX_SPEED_MS)
)
```

当 HTD 在 RAMPING 状态禁用横向后，`_lat_active` 被置为 False，下一 tick `get_lat_active()` 返回 False，guard clause 触发 `disabled_or_invalid_condition`。HTD 返回 True 但 `_lat_active` 已为 False，横向无法恢复。

### 2.4 debug.log 统计证据

| 事件类型 | 次数 | 说明 |
|----------|------|------|
| HTD MANUAL_TURN trigger | 486 | 手动转向触发 |
| HTD RAMPING | 482 | 进入过渡期 |
| HTD INACTIVE resume | ~200 | 正常恢复 |
| **HTD INACTIVE disabled_or_invalid_condition** | **47** | 异常断开 |
| HTD retrigger | 多 | RAMPING 中重新触发 |

### 2.5 时序分析

```
大弯场景时间线:
─────────────────────────────────────────────────────────
T0: 进入弯道 → 方向盘角度升高
T1: 角度 > 60° → HTD 触发 MANUAL_TURN → 横向禁用
T2: 驾驶员松开 → 进入 RAMPING (delay=1.0s)
T3: 1.0s 后检查 → 角度仍 > 40° → 卡在 RAMPING
T4: 车辆漂移 → get_lat_active() 返回 False
T5: guard clause 触发 disabled_or_invalid_condition
T6: HTD 返回 True 但 get_lat_active() 仍为 False
    → 横向持续禁用 → 压线！
─────────────────────────────────────────────────────────
```

### 2.6 修复方案

**修复 1: RAMPING 角度锁改为软恢复 + 强制恢复**

```python
# 修复后代码
elif self._state == HTDState.RAMPING:
    elapsed = time.monotonic() - self._state_change_time
    if elapsed >= self._dynamic_delay:
        # 驾驶员已松手 → 立即恢复
        if not self._last_pressed or self._last_angle <= self._resume_angle_lock_deg:
            self._transition(HTDState.INACTIVE, "resume")
            return True, self._state
        # 驾驶员仍握方向盘 → 再等一个周期后强制恢复
        if elapsed >= self._dynamic_delay * self._ramping_max_multiplier:
            self._transition(HTDState.INACTIVE, "resume_forced")
            return True, self._state
    return False, self._state
```

**修复 2: Guard Clause 跳过活跃状态的 lat_active 检查**

```python
# 修复后代码
if self._state in (HTDState.MANUAL_TURN, HTDState.RAMPING):
    is_invalid_condition = (
        not self._enabled or
        cruise_enabled or
        not (MIN_SPEED_MS <= v_ego <= MAX_SPEED_MS)
    )
else:
    is_invalid_condition = (
        not self._enabled or
        cruise_enabled or
        not lat_active or
        not (MIN_SPEED_MS <= v_ego <= MAX_SPEED_MS)
    )
```

---

## 3. 问题二：行程间通讯异常

### 3.1 CANParser 超时

**文件:** `opendbc_repo/opendbc/can/parser.py:200-214`

CAN 总线消息在启动或行程转换时超时：

```
WARNING CANParser: 0xaa WHEEL_SPEEDS not valid (timeout or missing)
WARNING CANParser: 0x320 VSC1S07 not valid (timeout or missing)
WARNING CANParser: 0x25 STEER_ANGLE_SENSOR not valid (timeout or missing)
...（共 406 次）
```

**根因:** CANParser 的 `timeout_threshold` 基于消息频率计算（`1_000_000_000 / frequency * 10`），默认 `bus_timeout_threshold = 500ms`。启动时 CAN 总线初始化需要时间，消息未及时到达触发超时。

**影响:** 启动阶段 `canValid=False`，系统无法激活，产生 `canError` 事件。

### 3.2 进程间通讯异常 (commIssue)

**文件:** `selfdrive/selfdrived/selfdrived.py:405-420`

```python
if not self.sm.all_checks() and no_system_errors:
    if not self.sm.all_alive():
        self.events.add(EventName.commIssue)
```

启动时部分服务未就绪：

```
not_alive: ['driverMonitoringState', 'alertDebug', 'lateralManeuverPlan', 
            'modelDataV2SP', 'driverCameraState', 'gpsLocation']
```

**根因:** `all_alive()` 要求所有服务在 10 倍预期频率内收到消息。启动时服务尚未完全初始化。

### 3.3 Panda 固件签名不匹配

```
WARNING Panda 120022000a51303436323838 connected, version: DEV-e10a0bb9-DEBUG, 
        signature 5bd5a6dbee1eb14f, expected 6e155acad7f71b17
WARNING Panda firmware out of date, update required
```

**根因:** 代码已更新到 commit `a7f9842a`，但 Panda 固件仍为 `e10a0bb9`。固件签名不匹配可能导致通讯异常。

**修复:** 需要重新烧录 Panda 固件。

### 3.4 通讯异常错误统计

| 错误类型 | 次数 | 说明 |
|----------|------|------|
| CANParser not valid | 406 | CAN 消息超时/丢失 |
| time jumped | 2271 | 时间跳变（GPS/WiFi 同步） |
| FPS dropped below 20 | 64 | 渲染帧率不足 |
| Failed to fetch | 127 | 模型下载失败（SSL 证书过期） |
| transport error | 66 | 网络传输错误 |
| Panda signature mismatch | 1 | 固件签名不匹配 |
| DoReboot | 7 | 系统重启 |

### 3.5 修复建议

| 问题 | 修复方案 | 优先级 |
|------|----------|--------|
| Panda 固件不匹配 | 重新烧录 Panda 固件至匹配签名 | **高** |
| CANParser 启动超时 | 增加启动宽限期或提高 timeout_threshold | 中 |
| commIssue 启动误报 | selfdrived 增加启动宽限期 | 中 |
| SSL 证书过期 | 更新系统 CA 证书 | 低 |
| time jumped | 检查 WiFi 时间同步配置 | 低 |

---

## 4. 相关参数建议

| 参数 | 当前值 | 建议值 | 说明 |
|------|--------|--------|------|
| dp_htd_turn_angle_threshold | 60° | 75-80° | 减少弯道误触发 |
| TorqueParamsOverrideEnabled | 0 | 1 | 启用横向力矩调参 |
| BlinkerLateralReengageDelay | 0 | 1 | 转向灯后延迟恢复 |

---

## 5. 修复文件清单

| 文件 | 修改内容 |
|------|----------|
| `sunnypilot/selfdrive/controls/lib/human_turn_detection.py` | RAMPING 角度锁改为软恢复+强制恢复；Guard Clause 跳过活跃状态 lat_active 检查 |
