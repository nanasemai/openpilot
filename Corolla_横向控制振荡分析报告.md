# 丰田卡罗拉横向控制振荡问题深度分析报告

## 文档概述

| 项目 | 内容 |
|------|------|
| 车辆型号 | Toyota Corolla 2017-19 (TSS-P) |
| 控制模式 | 扭矩控制 (Torque-Based) |
| 问题现象 | 横向控制不顺滑，方向盘左右反复修正（振荡） |
| 代码版本 | openpilot_nanasemai_c3 (含 Sunnypilot 扩展) |
| 分析日期 | 2026-08-23 |
| 文档性质 | 纯分析，不涉及代码修改 |

---

## 目录

1. [车辆规格与核心参数](#1-车辆规格与核心参数)
2. [横向控制算法架构](#2-横向控制算法架构)
3. [扭矩控制PID参数详解](#3-扭矩控制pid参数详解)
4. [扭矩限幅机制深度分析](#4-扭矩限幅机制深度分析)
5. [Corolla特有参数风险点](#5-corolla特有参数风险点)
6. [振荡根因逐层拆解](#6-振荡根因逐层拆解)
7. [完整振荡链路还原](#7-完整振荡链路还原)
8. [控制回路频率响应分析](#8-控制回路频率响应分析)
9. [与其他丰田车型对比](#9-与其他丰田车型对比)
10. [Sunnypilot扩展影响评估](#10-sunnypilot扩展影响评估)
11. [诊断建议与验证方法](#11-诊断建议与验证方法)
12. [附录：关键代码索引](#12-附录关键代码索引)

---

## 1. 车辆规格与核心参数

### 1.1 基础车辆参数

来源：`opendbc_repo/opendbc/car/toyota/values.py:194-198`

```python
TOYOTA_COROLLA = PlatformConfig(
    [ToyotaCarDocs("Toyota Corolla 2017-19")],
    CarSpecs(
        mass=2860. * CV.LB_TO_KG,
        wheelbase=2.7,
        steerRatio=18.27,
        tireStiffnessFactor=0.444
    ),
    dbc_dict('toyota_new_mc_pt_generated', 'toyota_adas'),
)
```

| 参数 | 值 | 单位 | 在丰田车系中排名 |
|------|-----|------|-----------------|
| 整车质量 | 2860 | lbs (1297 kg) | 最轻级 |
| 轴距 | 2.7 | m | 中等偏短 |
| 转向比 | **18.27** | :1 | **最高** |
| 轮胎刚度系数 | 0.444 | - | 标准 |

**转向比18.27的影响分析：**

曲率计算公式：
```
curvature = sin(steeringAngleRad) / (wheelbase × steerRatio)
```

转向比越高，方向盘转相同的角度，轮胎偏转角越小，意味着：
- 要达到同样的横向加速度，方向盘转角更大
- 方向盘角度传感器的噪声对曲率计算的影响被**除以**了18.27
- 但反过来，要达到同样的车辆响应，需要更大的方向盘偏转，EPS电机负担更重

这里需要注意：steerRatio在曲率计算中作为分母，高steerRatio实际上**减小**了方向盘角噪声对曲率的影响。但高steerRatio意味着EPS需要输出更大的扭矩来驱动方向盘，这对扭矩控制系统的响应速度提出了更高要求。

### 1.2 扭矩调校参数

来源：`opendbc_repo/opendbc/car/torque_data/params.toml:64`

```toml
"TOYOTA_COROLLA" = [3.117154369115421, 1.8438132575043773, 0.12289685869250652]
```

参数含义：
| 索引 | 参数名 | 值 | 说明 |
|------|--------|-----|------|
| 0 | LAT_ACCEL_FACTOR | **3.1172** | 扭矩→横向加速度转换系数 |
| 1 | MAX_LAT_ACCEL_MEASURED | 1.8438 | 实测最大横向加速度 (m/s²) |
| 2 | FRICTION | 0.1229 | 方向盘摩擦系数 |

**LAT_ACCEL_FACTOR 的作用：**

在扭矩控制中，控制器的输出流程为：
```
期望扭矩 = PID输出(横向加速度) / LAT_ACCEL_FACTOR
```

LAT_ACCEL_FACTOR 越大，意味着产生同样横向加速度需要越多的扭矩。Corolla的3.1172是丰田车系中**最高**的值之一，这表明Corolla的EPS转向系统效率较低，或者EPS传感器标度使得单位扭矩对应的实际力矩较小。

### 1.3 EPS标度因子

来源：`opendbc_repo/opendbc/car/toyota/values.py:590-592`

```python
EPS_SCALE = defaultdict(lambda: 73,
    {
        CAR.TOYOTA_PRIUS: 66,
        CAR.TOYOTA_COROLLA: 88,
        CAR.LEXUS_IS: 77,
        ...
    })
```

Corolla的EPS_SCALE = **88**，而默认值是73。

在`carstate.py`中的应用：
```python
eps_torque_scale = EPS_SCALE[CP.carFingerprint] / 100.0
ret.steeringTorqueEps = cp.vl["STEER_TORQUE_SENSOR"]["STEER_TORQUE_EPS"] * eps_torque_scale
```

这意味着Corolla的EPS扭矩读取值会被乘以0.88。如果这个标度因子不准：
- 如果实际比例应该是0.73而不是0.88，那么`steeringTorqueEps`读数会系统性**偏大19.5%**
- 控制器会认为EPS电机已经输出比实际更多的扭矩
- 限幅逻辑会基于错误的读数做出错误判断

---

## 2. 横向控制算法架构

### 2.1 整体控制流程图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        控制回路 (100Hz)                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [模型预测] ──→ 期望曲率 ──→ clip_curvature() ──→ 期望横向加速度      │
│       │                                                       │    │
│       │                      delay_compensated_buffer        │    │
│       │                               │                      │    │
│       ▼                               ▼                      ▼    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    横向控制器 (latcontrol_torque.py)         │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │                                                             │   │
│  │  ① setpoint = 延迟补偿后的期望横向加速度                     │   │
│  │  ② measurement = 实测曲率 × vEgo²                           │   │
│  │  ③ error = setpoint - measurement                           │   │
│  │  ④ ff = 期望横向加速度 - 摩擦补偿 + jerk前馈                 │   │
│  │  ⑤ PID: output_lat_accel = Kp×error + Ki×∫error + ff       │   │
│  │  ⑥ torque = output_lat_accel / LAT_ACCEL_FACTOR             │   │
│  │  ⑦ torque = -torque (方向反转)                               │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                               │                                     │
│                               ▼                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              扭矩限幅 (carcontroller.py / lateral.py)         │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │                                                             │   │
│  │  ① 绝对限幅: clip(torque, -1500, 1500)                     │   │
│  │  ② 误差限幅: clip(torque, [eps_meas-350, eps_meas+350])    │   │
│  │  ③ 速率限幅: clip(torque, [last±15, last±25])              │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                               │                                     │
│                               ▼                                     │
│                    CAN 消息输出 → EPS电机执行                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键数据流

```
模型输出路径：
modeld → controlsd → desired_curvature → desired_lateral_accel
                                          ↓ (延迟补偿缓冲)
                                    latcontrol_torque.setpoint
                                          ↓
期望值 vs 实测值比较：
  setpoint (期望横向加速度，来自模型)
  measurement (实测横向加速度，来自方向盘角+车速)
  error = setpoint - measurement

实测横向加速度计算：
  measured_curvature = -VM.calc_curvature(
      math.radians(CS.steeringAngleDeg - params.angleOffsetDeg),
      CS.vEgo,
      params.roll
  )
  measurement = measured_curvature × CS.vEgo²
```

---

## 3. 扭矩控制PID参数详解

### 3.1 基础PID配置

来源：`selfdrive/controls/lib/latcontrol_torque.py`

```python
KP = 0.8          # 基础高速P增益
KI = 0.15         # 积分增益

INTERP_SPEEDS = [1, 1.5, 2.0, 3.0, 5, 7.5, 10, 15, 30]   # m/s
KP_INTERP = [250, 120, 65, 30, 11.5, 5.5, 3.5, 2.0, KP]
```

### 3.2 速度依赖的Kp曲线

| 速度 (m/s) | 速度 (km/h) | Kp | 实际控制力评估 |
|------------|-------------|------|--------------|
| 1.0 | 3.6 | 250 | 极低速，几乎不用 |
| 1.5 | 5.4 | 120 | 泊车/蠕行 |
| 2.0 | 7.2 | 65 | 起步阶段 |
| 3.0 | 10.8 | 30 | 缓慢行驶 |
| 5.0 | 18 | 11.5 | 城市低速 |
| 7.5 | 27 | 5.5 | 城市正常 |
| 10.0 | 36 | 3.5 | 城市快速/快速路慢速 |
| 15.0 | 54 | 2.0 | 快速路/高速低速段 |
| **30.0** | **108** | **0.8** | **高速公路** |

**Kp在高速时极低的问题：**

在108 km/h时，Kp仅为0.8。这意味着：
- 横向加速度误差1 m/s²，比例项仅输出 0.8 m/s²
- 相对于期望的3 m/s²横向加速度（MAX_LATERAL_ACCEL_NO_ROLL），比例项仅贡献 0.8/3 = **27%**的修正
- 其余73%需要积分项累积和前馈项来补偿
- 积分项的响应时间为 1/Kp×KI = 1/0.12 ≈ **8.3秒**（时间常数）

这是一个**极其缓慢**的积分响应。在高速弯道变化时，积分器需要很长时间才能追上误差，期间车辆会偏离车道中心。

### 3.3 积分器冻结条件

来源：`selfdrive/controls/lib/latcontrol_torque.py`

```python
freeze_integrator = steer_limited_by_safety or CS.steeringPressed or CS.vEgo < 5
```

积分器会在以下情况冻结：
1. 扭矩被安全限幅
2. 驾驶员干预（方向盘力超过100个单位）
3. 车速低于5 m/s (18 km/h)

**问题场景：** 在高速弯道上，如果扭矩被限幅（STEER_ERROR_MAX=350触发），积分器冻结，控制器无法累积修正量。等限幅解除后，积分器从0开始重新累积，导致响应滞后。

### 3.4 微分项缺失

```python
k_d = 0   # PIDController中默认k_d=0
```

**没有微分项意味着：**
- 无法根据误差变化趋势提前干预
- 所有"阻尼"效果需要靠系统自身的物理惯性和低通滤波器提供
- 在快速变化的道路曲率下，控制器只能被动响应，无法预测

### 3.5 前馈设计

```python
ff = gravity_adjusted_future_lateral_accel   # 期望横向加速度（含路面倾斜补偿）
ff -= self.torque_params.latAccelOffset      # 减去静态偏移
ff += get_friction(error + JERK_GAIN * desired_lateral_jerk, ...)  # 摩擦补偿
```

**Jerk前馈：**
```python
JERK_LOOKAHEAD_SECONDS = 0.19    # 前视时间
JERK_GAIN = 0.3                  # 前馈增益
LP_FILTER_CUTOFF_HZ = 1.2        # 低通滤波器截止频率
```

1.2 Hz低通滤波器的相位延迟：
```
相位延迟 = -arctan(2πf/Fc) 在 f=1.2Hz时 = -45°
对应时间延迟 ≈ 1/(2π×1.2) ≈ 0.133s
```

结合0.19s的前视时间，总前馈延迟约0.32s。在108 km/h（30 m/s）时，车辆在这段时间行驶了约9.6米。如果路面曲率变化较快，这个延迟会导致前馈不准确。

---

## 4. 扭矩限幅机制深度分析

### 4.1 三层限幅结构

来源：`opendbc_repo/opendbc/car/lateral.py:63-88` 和 `opendbc_repo/opendbc/car/toyota/carcontroller.py`

```python
def apply_dist_to_meas_limits(val, val_last, val_meas,
                              STEER_DELTA_UP, STEER_DELTA_DOWN,
                              STEER_ERROR_MAX, STEER_MAX):
    # 第一层：绝对限幅
    max_lim = min(max(val_meas + STEER_ERROR_MAX, STEER_ERROR_MAX), STEER_MAX)
    min_lim = max(min(val_meas - STEER_ERROR_MAX, -STEER_ERROR_MAX), -STEER_MAX)
    val = np.clip(val, min_lim, max_lim)

    # 第二层：基于方向的速度限幅
    if val_last > 0:
        val = np.clip(val,
                      max(val_last - STEER_DELTA_DOWN, -STEER_DELTA_UP),
                      val_last + STEER_DELTA_UP)
    else:
        val = np.clip(val,
                      val_last - STEER_DELTA_UP,
                      min(val_last + STEER_DELTA_DOWN, STEER_DELTA_UP))
    return val
```

### 4.2 Corolla限幅参数

| 参数 | 值 | 换算 |
|------|-----|------|
| STEER_MAX | 1500 | 最大扭矩单位 |
| STEER_ERROR_MAX | **350** | 相当于23.3%满量程 |
| STEER_DELTA_UP | **15** | 1500单位/秒 |
| STEER_DELTA_DOWN | **25** | 2500单位/秒 |
| 控制频率 | 100 Hz | 10ms一帧 |

### 4.3 STEER_ERROR_MAX=350 的振荡机制详解

这是**最关键的振荡源**。

假设场景：控制器期望输出扭矩=1000，EPS电机实际输出=800。

**第一帧：**
```
期望扭矩 = 1000
eps_meas  = 800
max_lim   = min(800 + 350, 1500) = 1150  ✓
min_lim   = max(800 - 350, -1500) = 450   ✓
限幅后扭矩 = clip(1000, 450, 1150) = 1000  通过
速率限幅后 = clip(1000, last±15) = 假设通过
→ 实际发送扭矩 = 1000
```

**第二帧：EPS响应滞后，实际只达到850**
```
期望扭矩 = 1000（PID未感知差距，继续输出1000）
eps_meas  = 850
max_lim   = min(850 + 350, 1500) = 1200   ✓
限幅后扭矩 = clip(1000, 500, 1200) = 1000  通过
→ 实际发送扭矩 = 1000
```

**第三帧：EPS过冲，实际达到1100**
```
期望扭矩 = 1000
eps_meas  = 1100
max_lim   = min(1100 + 350, 1500) = 1450   ✓
min_lim   = max(1100 - 350, -1500) = 750    ✓
限幅后扭矩 = clip(1000, 750, 1450) = 1000    通过
→ 实际发送扭矩 = 1000
```

**第四帧：测量噪声使eps_meas=1200**
```
期望扭矩 = 1000
eps_meas  = 1200
max_lim   = min(1200 + 350, 1500) = 1500    ✓
min_lim   = max(1200 - 350, -1500) = 850     ✓
限幅后扭矩 = clip(1000, 850, 1500) = 1000     通过
```

上面的情况限幅没有生效。真正的问题出在**EPS实际扭矩快速变化时**：

**第五帧：EPS快速下降，eps_meas=950（下降了250）**
```
期望扭矩 = 1000
eps_meas  = 950
val_last  = 1000
max_lim   = min(950 + 350, 1500) = 1300
min_lim   = max(950 - 350, -1500) = 600
限幅后扭矩 = clip(1000, 600, 1300) = 1000
速率限幅: clip(1000, max(1000-25, -15), 1000+15) = clip(1000, 975, 1015) = 1000 ✓
→ 发送扭矩 = 1000
```

**第六帧：EPS大幅下降，eps_meas=700（下降了250）**
```
期望扭矩 = 1000
eps_meas  = 700
val_last  = 1000
max_lim   = min(700 + 350, 1500) = 1050     ✓
min_lim   = max(700 - 350, -1500) = 350      ✓
限幅后扭矩 = clip(1000, 350, 1050) = 1000     通过
速率限幅: clip(1000, 975, 1015) = 1000 ✓
→ 发送扭矩 = 1000
```

**第七帧：期望扭矩由于积分累积上升到1050，但eps_meas=700**
```
期望扭矩 = 1050（积分累积了误差）
eps_meas  = 700
max_lim   = min(700 + 350, 1500) = 1050
限幅后扭矩 = clip(1050, 350, 1050) = 1050  ← 恰好卡在上限
速率限幅: clip(1050, 1000-25, 1000+15) = clip(1050, 975, 1015) = 1015
→ 实际发送扭矩 = 1015（被速率限幅截断）
```

**第八帧：EPS追赶到1000，期望扭矩因误差减小降到980**
```
期望扭矩 = 980
eps_meas  = 1000
max_lim   = min(1000+350, 1500) = 1350
min_lim   = max(1000-350, -1500) = 650
限幅后扭矩 = clip(980, 650, 1350) = 980
速率限幅: clip(980, 1015-25, 1015+15) = clip(980, 990, 1030) = 990
→ 实际发送扭矩 = 990
```

**关键问题：** EPS实际扭矩的波动直接传递到限幅边界，当期望扭矩接近限幅边界时，任何EPS测量波动都会导致实际发送扭矩的跳跃，形成振荡。

### 4.4 STEER_DELTA_UP=15 的限制

在100Hz下，STEER_DELTA_UP=15意味着：
- 最大扭矩上升速率 = 15 × 100 = 1500 单位/秒
- 从0加速到1500需要 = 1500/1500 = **1.0秒**
- 从1000跳到1500需要 = 500/15 = **33帧 = 0.33秒**

这个限制在快速弯道时可能导致扭矩跟不上需求，控制器不断要求增大扭矩但被速率限幅卡住。

---

## 5. Corolla特有参数风险点

### 5.1 LAT_ACCEL_FACTOR=3.117 的影响量化

扭矩计算：
```
torque = PID_output_lat_accel / LAT_ACCEL_FACTOR
```

对比同级别车型：
| 车型 | LAT_ACCEL_FACTOR | 等效扭矩倍数 |
|------|-----------------|-------------|
| Corolla | **3.117** | 1.00× (基准) |
| Camry | 2.057 | 1.51× |
| RAV4 | 2.086 | 1.49× |
| Prius | 2.530 | 1.23× |
| Sienna | 2.000 | 1.56× |

相同PID输出下，Camry需要的扭矩只有Corolla的64.4%。这意味着Corolla的EPS电机需要输出更大的扭矩才能达到同样的横向加速度，EPS的响应余量更小。

### 5.2 steerRatio=18.27 的影响

对比：
| 车型 | steerRatio | 相对值 |
|------|-----------|--------|
| Corolla | **18.27** | 最高 |
| Camry | 15.75 | -13.8% |
| RAV4 | 16.24 | -11.1% |
| Prius | 14.43 | -21.0% |

高转向比导致：
1. EPS电机需要旋转更大角度才能达到目标方向盘转角
2. 方向盘角度测量中的任何噪声都被放大（因为需要更大的转角来实现同样的效果）
3. angleOffsetDeg的校准精度要求更高

### 5.3 EPS_SCALE=88 的测量偏差

```python
# carstate.py
eps_torque_scale = 88 / 100.0  # = 0.88 for Corolla
ret.steeringTorqueEps = raw_eps_value * eps_torque_scale
```

如果实际正确的比例应该是73（默认值），而代码用了88，那么：
```
报告扭矩 / 实际扭矩 = 0.88 / 0.73 = 1.205
```

即扭矩读数**虚高20.5%**。这会导致：
- 控制器认为EPS已经输出足够的扭矩
- STEER_ERROR_MAX限幅基于虚高的读数，可能过早截断
- 实际EPS扭矩小于控制器认为的值，车辆实际响应弱于预期
- 积分器累积误差，最终输出被限幅，形成周期性的"追赶-过冲"

---

## 6. 振荡根因逐层拆解

### 6.1 根因一：限幅窗口与测量噪声的相互作用（严重度：高）

**机制：**
```
STEER_ERROR_MAX=350 定义了"信任窗口"
期望扭矩 ± 350 范围内被认为是EPS的正常偏差

但实际EPS扭矩的测量噪声如果超过±350，限幅就会频繁截断
```

**触发条件：**
- EPS电机在高负载下温度上升，内部摩擦增大，扭矩输出波动
- CAN总线上的扭矩传感器数据有±10~20单位的量化噪声
- 结合EPS_SCALE=88的标度偏差，实际波动范围可能更大

**表现形式：**
- 方向盘轻微左右摆动
- 频率约2-5 Hz（对应控制环路的延迟反馈）
- 在弯道或路面不平坦时加重

### 6.2 根因二：高速段PID增益过低（严重度：高）

**机制：**
```
30 m/s时 Kp=0.8, Ki=0.15
积分时间常数 T_i = Kp/Ki = 0.8/0.15 = 5.33s
闭环带宽 ≈ 1/T_i = 0.19 Hz
```

0.19 Hz的带宽意味着系统只能跟踪低于0.19 Hz的变化。道路曲率的变化频率通常在0.1-1.0 Hz范围，大部分情况下系统**无法跟上**。

**触发条件：**
- 高速公路上的连续弯道
- 路面有轻微的不规则弯曲
- 道路有横向坡度变化

**表现形式：**
- 车辆偏离车道中心线后缓慢修正
- 修正过程中出现"慢-停-反向-慢"的往复
- 感觉方向盘在慢慢打正又慢慢打反

### 6.3 根因三：EPS标度因子不准（严重度：中）

**机制：**
```
Corolla使用EPS_SCALE=88，默认值为73
如果88不准，steeringTorqueEps读数系统性偏差
→ 限幅逻辑判断错误
→ 控制器与EPS的实际状态不一致
```

**触发条件：**
- 所有工况都存在
- 在EPS高负载（大扭矩需求）时偏差更明显

**表现形式：**
- 弯道中方向盘感觉"发飘"
- 控制器给出的指令与实际执行有系统性偏差

### 6.4 根因四：Jerk前馈预测误差（严重度：中）

**机制：**
```
JERK_GAIN=0.3, 前视0.19s, LP滤波1.2Hz
在曲率变化率高的路段（如S弯、匝道），jerk预测偏差大
错误的前馈被加到输出中，形成额外的振荡源
```

**触发条件：**
- 连续S弯
- 匝道进出口
- 路面曲率不连续的路段

**表现形式：**
- 在弯道变化点方向盘突然反打
- 在直道-弯道过渡处有"顿挫感"

### 6.5 根因五：低通滤波器的相位滞后（严重度：低-中）

**机制：**
```
LP_FILTER_CUTOFF_HZ = 1.2
在1.2Hz时的相位滞后 = -45°，时间延迟≈0.133s
在30m/s时，延迟对应距离 = 4米
```

4米的预测误差在高速弯道中可能导致明显的横向偏差。

---

## 7. 完整振荡链路还原

### 场景：高速公路直线行驶，轻微路面不平

```
时间轴 (100Hz = 每帧10ms)
─────────────────────────────────────────────────────────────────────
t=0ms:  路面轻微颠簸
        → 方向盘角微小变化(+0.1°)
        → curvature测量变化 = sin(0.1°) / (2.7×18.27) = 0.0000113 rad/m
        → 实测横向加速度变化 = 0.0000113 × (25²) = 0.0071 m/s²

t=10ms: error = setpoint - 0.0071 = -0.0071
        PID输出 = 0.8 × (-0.0071) = -0.0057 (比例)
        ff = 0 (直线行驶, 无期望加速度)
        total output = -0.0057
        torque = -0.0057 / 3.117 = -0.0018 (几乎无变化)

t=100ms: 路面颠簸持续，方向盘角累积变化(+0.5°)
         实测横向加速度变化 = sin(0.5°)/(2.7×18.27) × (25²) = 0.035 m/s²
         error = 0 - 0.035 = -0.035
         PID输出 = 0.8×(-0.035) + 积分累积(-0.0015) = -0.0295
         torque = -0.0295 / 3.117 = -0.0095

t=500ms: 积分累积增大，输出开始显著
         error ≈ -0.035
         integral ≈ -0.15 (累积了150帧的积分)
         PID输出 = 0.8×(-0.035) + (-0.15) = -0.178
         torque = -0.178 / 3.117 = -0.057
         ← 仍然很小，因为3.117的除数放大了

t=2000ms: 积分继续累积，torque累积到可感知量级
          方向盘开始向左偏转
          EPS实际扭矩达到-50
          但EPS_SCALE=88导致报告值为-44
          STEER_ERROR_MAX限幅检查: max_lim = -44+350 = 306 ✓

t=3000ms: 方向盘偏转过量（积分过冲）
          error开始反向变为正
          PID输出开始减小
          但积分器仍在累积正向误差

t=5000ms: 积分过冲达到峰值
          方向盘开始回正
          实测curvature减小
          error变正

t=8000ms: 方向盘回正后继续过冲（反向积分累积）
          形成完整的振荡周期 ≈ 8-12秒
─────────────────────────────────────────────────────────────────────
```

### 振荡频率估算

```
振荡周期 ≈ 2 × (1/(2π) × √(T_i × T_d))
其中 T_i = Kp/Ki = 5.33s, T_d = steerActuatorDelay = 0.12s
振荡周期 ≈ 2 × (1/(2π) × √(5.33 × 0.12))
         ≈ 2 × (1/6.28 × 0.80)
         ≈ 0.255s

考虑延迟和积分时间常数，实际振荡周期会更长：
实际周期 ≈ 1/(0.19Hz) ≈ 5.3s (对应积分带宽)
加上jerk前馈和限幅的影响，可能出现叠加的次级振荡：
- 主振荡：~0.2 Hz (5秒周期)，来自PID积分
- 次振荡：~1-2 Hz，来自限幅与EPS交互
- 高频抖动：~10-20 Hz，来自CAN量化噪声
```

---

## 8. 控制回路频率响应分析

### 8.1 各环节传递函数

```
环节1: 延迟补偿 (延迟steerActuatorDelay=0.12s)
G1(s) = e^(-0.12s) ≈ 1/(1+0.12s) (一阶近似)

环节2: PID控制器
G2(s) = Kp + Ki/s = 0.8 + 0.15/s = (0.8s+0.15)/s
零极点: 零点 s=-0.1875, 极点 s=0

环节3: 扭矩转换
G3 = 1/LAT_ACCEL_FACTOR = 1/3.117 = 0.321

环节4: EPS执行器 (近似为二阶系统)
G4(s) = ωn²/(s²+2ζωn×s+ωn²)
假设 ωn=50 rad/s, ζ=0.7

环节5: 低通滤波器 (1.2Hz)
G5(s) = 2π×1.2 / (s + 2π×1.2) = 7.54/(s+7.54)

环节6: 限幅 (非线性，小信号近似为单位增益)
G6 ≈ 1 (小信号)
```

### 8.2 开环传递函数

```
G_open(s) = G1 × G2 × G3 × G4 × G5

低频增益 (s→0):
G_open(0) = 1 × (0.15/0) × 0.321 × 1 × 1 → ∞ (积分)

带宽 (0dB频率):
估算约 0.2-0.3 Hz (非常低)

相位裕度：
延迟0.12s在0.2Hz处产生相位滞后 = 2π×0.2×0.12 = 0.15 rad ≈ 8.6°
低通滤波器在0.2Hz处产生相位滞后 = arctan(0.2/1.2) = 9.5°
总相位滞后 ≈ 18°
相位裕度 ≈ 180° - 90°(积分) - 18° ≈ 72° (足够)
```

### 8.3 相位裕度与振荡的关系

虽然相位裕度72°看起来足够，但问题在于：

1. **极限环振荡**：限幅非线性会导致系统在大信号时进入极限环振荡，线性分析不适用
2. **EPS延迟的不确定性**：实际EPS延迟可能在0.1~0.2s之间变化，温度影响显著
3. **测量噪声放大**：方向盘角传感器噪声通过高steerRatio和高LAT_ACCEL_FACTOR被放大

### 8.4 奈奎斯特分析（定性）

```
频率范围 | 开环增益 | 相位 | 风险
0.01 Hz  | 高       | 接近0°  | 安全（积分主导）
0.1 Hz   | 高       | -30°    | 安全
0.2 Hz   | ~1 (0dB) | -72°    | 相位裕度72°，刚好
0.5 Hz   | <1       | -120°   | 安全（增益已衰减）
1.0 Hz   | <<1      | -160°   | 安全
```

系统在0.2Hz附近是**最脆弱的**。任何参数漂移（如EPS延迟增大、轮胎刚度变化）都可能将相位裕度降低到不安全范围。

---

## 9. 与其他丰田车型对比

### 9.1 核心参数对比表

| 参数 | Corolla | Camry | RAV4 | Prius | Sienna |
|------|---------|-------|------|-------|--------|
| LAT_ACCEL_FACTOR | **3.117** | 2.057 | 2.086 | 2.530 | 2.000 |
| steerRatio | **18.27** | 15.75 | 16.24 | 14.43 | 16.24 |
| mass (kg) | 1297 | 1592 | 1731 | 1380 | 2108 |
| tireStiffness | 0.444 | 0.444 | 0.444 | 0.444 | 0.444 |
| EPS_SCALE | **88** | 73 | 73 | 66 | 73 |
| friction | 0.123 | 0.169 | 0.203 | 0.181 | 0.163 |
| max_lat_accel | 1.844 | 1.671 | 1.915 | 1.928 | 1.773 |

### 9.2 Corolla的独特性分析

**最不利组合：**
- LAT_ACCEL_FACTOR最高 (3.117 vs 平均2.156) → 扭矩需求最大
- steerRatio最高 (18.27 vs 平均15.83) → 方向盘噪声影响最大
- EPS_SCALE唯一 (88 vs 73) → 可能存在测量偏差

**唯一有利因素：**
- friction最低 (0.123 vs 平均0.181) → 方向盘摩擦力小，理论上EPS更容易控制

### 9.3 等效控制难度指数

定义控制难度指数为：
```
难度 = LAT_ACCEL_FACTOR × steerRatio / max_lat_accel
```

| 车型 | 计算 | 难度指数 |
|------|------|---------|
| Corolla | 3.117×18.27/1.844 | **30.87** |
| Camry | 2.057×15.75/1.671 | 19.26 |
| RAV4 | 2.086×16.24/1.915 | 17.58 |
| Prius | 2.530×14.43/1.928 | 18.97 |
| Sienna | 2.000×16.24/1.773 | 18.32 |

**Corolla的控制难度是其他丰田车型的1.6~1.8倍**，这从数值上解释了为什么Corolla比其他丰田车更容易出现横向控制问题。

---

## 10. Sunnypilot扩展影响评估

### 10.1 NNLC扩展参数

来源：`sunnypilot/selfdrive/controls/lib/latcontrol_torque_ext_base.py`

```python
KP = 1.0          # 基础版是0.8
KI = 0.3          # 基础版是0.15
lat_jerk_friction_factor = 0.4
lat_accel_friction_factor = 0.7
friction_look_ahead_v = [1.4, 2.0]  # seconds
friction_look_ahead_bp = [9.0, 30.0]  # m/s
```

### 10.2 NNLC启用时的变化

| 参数 | 基础版 | NNLC版 | 变化 |
|------|--------|--------|------|
| Kp | 0.8 | 1.0 | +25% |
| Ki | 0.15 | **0.30** | **+100%** |
| 积分时间常数 | 5.33s | 3.33s | -37.5% |
| 摩擦补偿 | 标准 | 增强(前视1.4-2.0s) | 更积极 |

### 10.3 NNLC对振荡的影响

Ki从0.15增加到0.30意味着积分响应速度翻倍。好处是纠正误差更快，但代价是：

1. **过冲更严重**：更快的积分响应意味着到达目标后更大的过冲
2. **极限环振幅可能更大**：积分过冲+限幅截断→反向积分累积→更大的反向过冲
3. **摩擦补偿的前视时间太长**（1.4-2.0秒），在快速变化的道路上可能引入错误补偿

### 10.4 TorqueParamsOverride检查

来源：`sunnypilot/selfdrive/controls/lib/latcontrol_torque_ext_override.py`

如果用户启用了`TorqueParamsOverrideEnabled`，可能自定义了以下参数：
- `latAccelFactor`
- `latAccelOffset`
- `friction`
- `steeringAngleDeadzoneDeg`

任何不当的自定义值都可能引入额外的振荡源。建议检查：
```
# 查看当前生效的扭矩参数
# Path: /data/params/d/TorqueParamsOverride
# 检查 latAccelFactor, friction 等值是否合理
```

---

## 11. 诊断建议与验证方法

### 11.1 数据记录检查清单

建议在开动车辆后，记录以下数据并分析：

| 数据源 | 关键字段 | 关注点 |
|--------|---------|--------|
| `controlsState` | lateralAccelCalc, lateralAccelEgo | 期望vs实测横向加速度差值 |
| `controlsState` | SteeringAngleDesiredDeg, steeringAngleDeg | 期望vs实际方向盘角差值 |
| `carState` | steeringTorqueEps | EPS实际扭矩波动情况 |
| `carControl` | actuatorOutput.torque | 控制器输出扭矩 |
| `carOutput` | torque | 实际CAN发送的扭矩 |
| `liveParameters` | angleOffsetDeg, roll | 参数校准值是否稳定 |
| `liveCalibration` | pcCalib | 前向矩阵校准质量 |
| `modelV2` | laterals, aLon | 模型输出的期望值波动 |

### 11.2 分析指标

```python
# 振荡幅度
oscillation_amp = max(carOutput.torque) - min(carOutput.torque)
# 期望值vs实际值差
torque_error = carControl.actuatorOutput.torque - carOutput.torque
# EPS测量噪声
eps_noise = std(steeringTorqueEps)  # 标准差
# 限幅触发频率
limiter_count = count(|torque_error| > STEER_ERROR_MAX) / total_frames
# 方向盘角噪声
steer_noise = std(diff(steeringAngleDeg)) / dt
```

### 11.3 具体诊断步骤

**步骤一：确认控制模式**
```
检查 CarParams.lateralTuning.which()
- 如果是 'torque'：继续分析
- 如果是 'pid' 或 'angle'：分析路径不同
```

**步骤二：检查NNLC状态**
```
检查 params/d/NeuralNetworkLateralControl
- 如果为 True：NNLC扩展参数生效
- 如果为 False：使用标准PID
```

**步骤三：检查自定义参数**
```
检查 params/d/TorqueParamsOverrideEnabled
检查 params/d/TorqueParamsOverride (如果启用)
```

**步骤四：分析扭矩波形**
```
画两条曲线：
1. carControl.actuatorOutput.torque (期望扭矩)
2. carOutput.torque (实际发送扭矩)

观察：
- 两条线之间的差距是否经常接近350（限幅边界）
- 实际发送扭矩是否有"锯齿"形状
- 期望扭矩是否有高频波动
```

**步骤五：分析方向盘角波形**
```
画：
1. SteeringAngleDesiredDeg
2. steeringAngleDeg

观察：
- 实际方向盘角是否在期望值附近来回振荡
- 振荡频率是否稳定（周期性）还是不规则
```

**步骤六：检查angleOffsetDeg**
```
画：liveParameters.angleOffsetDeg 随时间变化

如果angleOffsetDeg不稳定（持续漂移），说明：
- 方向盘零位校准不准
- 传感器有系统偏差
- 这会导致曲率计算系统误差
```

### 11.4 预期发现

根据代码分析，最可能观察到的现象是：

1. **期望扭矩和实际发送扭矩之间存在持续的"锯齿差"**，差值在±200~350范围内波动
2. **方向盘角在期望值附近做小幅度的周期性振荡**，频率约0.1-0.3 Hz
3. **在弯道中，EPS实际扭矩波动幅度大于直道**
4. **angleOffsetDeg可能有数度级别的偏移**（如果校准不准）
5. **`lateralAccelCalc`（模型期望）和`lateralAccelEgo`（实测）之间存在持续的误差**

### 11.5 验证EPS_SCALE准确性的方法

```
方法：
1. 在直道停车状态下，记录 steeringTorqueEps 的零位偏移
2. 手动转动方向盘到不同角度，记录 steeringTorqueEps
3. 计算 torque 与方向盘角度之间的关系
4. 对比与其他丰田车（EPS_SCALE=73）的比例

如果 Corolla 的 EPS 实际比例更接近73而不是88：
   → 读数虚高约20.5%
   → 限幅逻辑基于虚高的读数
   → 实际EPS扭矩比控制器认为的小
   → 振荡可能性大幅增加
```

---

## 12. 附录：关键代码索引

### 12.1 车辆参数文件

| 文件路径 | 内容 | 关键行 |
|---------|------|--------|
| `opendbc_repo/opendbc/car/toyota/values.py` | Corolla平台配置 | 194-198 |
| `opendbc_repo/opendbc/car/toyota/values.py` | CarControllerParams | 18-50 |
| `opendbc_repo/opendbc/car/toyota/values.py` | EPS_SCALE字典 | 590-592 |
| `opendbc_repo/opendbc/car/torque_data/params.toml` | 扭矩调校参数 | 64 |
| `opendbc_repo/opendbc/car/toyota/fingerprints.py` | ECU指纹识别 | - |

### 12.2 控制算法文件

| 文件路径 | 内容 | 关键行 |
|---------|------|--------|
| `selfdrive/controls/lib/latcontrol_torque.py` | 扭矩横向控制器主算法 | 全部 |
| `selfdrive/controls/lib/latcontrol.py` | 基类，饱和度检查 | - |
| `selfdrive/controls/lib/drive_helpers.py` | 曲率裁剪，ISO限制 | 26-39 |
| `selfdrive/controls/controlsd.py` | 主控制循环 | 160 |
| `common/pid.py` | PID控制器实现 | 全部 |

### 12.3 限幅和接口文件

| 文件路径 | 内容 | 关键行 |
|---------|------|--------|
| `opendbc_repo/opendbc/car/toyota/carcontroller.py` | CAN消息生成，限幅执行 | 127 |
| `opendbc_repo/opendbc/car/lateral.py` | 通用扭矩限幅函数 | 63-88 |
| `opendbc_repo/opendbc/car/toyota/interface.py` | CarParams配置 | 29, 45-52 |
| `opendbc_repo/opendbc/car/toyota/carstate.py` | CAN解析，EPS扭矩读取 | 123 |

### 12.4 Sunnypilot扩展文件

| 文件路径 | 内容 |
|---------|------|
| `sunnypilot/selfdrive/controls/lib/latcontrol_torque_ext.py` | 扩展包装器 |
| `sunnypilot/selfdrive/controls/lib/latcontrol_torque_ext_base.py` | 扩展基础类 |
| `sunnypilot/selfdrive/controls/lib/nnlc/nnlc.py` | 神经网络横向控制 |
| `sunnypilot/selfdrive/controls/lib/latcontrol_torque_ext_override.py` | 用户调参覆盖 |

---

## 总结

### 振荡根因排序

| 排名 | 根因 | 严重度 | 影响范围 | 修复难度 |
|------|------|--------|---------|---------|
| 1 | STEER_ERROR_MAX=350 限幅窗口过大 | 高 | 全速域 | 需调整参数 |
| 2 | 高速段PID增益过低(Kp=0.8) | 高 | 高速 | 需调整参数 |
| 3 | LAT_ACCEL_FACTOR=3.117 偏高 | 中 | 全速域 | 需重新标定 |
| 4 | EPS_SCALE=88 可能存在偏差 | 中 | 全速域 | 需实测验证 |
| 5 | steerRatio=18.27 偏高 | 中 | 全速域 | 车辆固有 |
| 6 | Jerk前馈预测不准确 | 中 | 弯道 | 需改进算法 |
| 7 | 低通滤波器1.2Hz相位滞后 | 低-中 | 弯道 | 需调整参数 |

### Corolla的结构性困难

Corolla在丰田车系中的**控制难度指数(30.87)**比其他车型高60%~80%。这不是单纯的参数调校问题，而是车辆的EPS硬件特性和控制算法设计之间的结构性不匹配。LAT_ACCEL_FACTOR和steerRatio同时处于不利端，加上EPS_SCALE的特殊标度，使得Corolla成为丰田车系中最难做横向控制的车型之一。

### 建议优先级

1. **首要**：记录并分析扭矩波形数据，确认振荡的实际形态和频率
2. **关键**：验证EPS_SCALE=88是否准确
3. **重要**：检查angleOffsetDeg的稳定性
4. **参考**：检查是否启用了NNLC或TorqueParamsOverride

---

*文档结束*
