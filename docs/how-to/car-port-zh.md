# 什么是车型适配？

车型适配是指在特定车辆上启用 openpilot 支持。openpilot 支持的每款车型都需要单独适配。车型适配的复杂度因多种因素而异，包括：

* 是否有类似车型的现有 openpilot 支持
* 车辆的架构和可用 API

# 车型适配的结构

所有车辆特定代码都包含在 [opendbc](https://github.com/commaai/opendbc) 项目中。

## opendbc

每个车辆品牌通过 `opendbc/car/[brand]` 中的标准接口结构支持：

* `interface.py`：车辆接口，定义 CarInterface 类
* `carstate.py`：读取来自车辆的 CAN 消息，构建 openpilot CarState 消息
* `carcontroller.py`：在车辆上执行 openpilot CarControl 动作的控制逻辑
* `[brand]can.py`：组合 CAN 消息供 carcontroller 发送
* `values.py`：执行器限制、通用车辆常量和支持车型文档
* `radar_interface.py`：解析来自车辆的雷达点（如果适用）的接口

## 安全

* `opendbc/safety/modes/[brand].h`：品牌特定的安全逻辑
* `opendbc/safety/tests/test_[brand].py`：品牌特定的安全 CI 测试

## openpilot

由于历史原因，openpilot 仍然包含少量车辆特定逻辑。这些最终将迁移到 opendbc 或以其他方式移除。

* `selfdrive/car/car_specific.py`：品牌特定的事件逻辑

# 如何进行车型适配？

[Jason Young](https://github.com/jyoung8607) 在 COMMA_CON 上做了关于车型适配流程的演讲。该演讲可在 YouTube 上观看：

https://www.youtube.com/watch?v=XxPS5TpTUnI

## 品牌适配

品牌适配是将 openpilot 适配到一个全新品牌或同一品牌内的新平台。

示例：https://github.com/commaai/openpilot/pull/23331

## 车型适配

车型适配是将 openpilot 适配到已有支持品牌内的新车型。车型适配比品牌适配更容易，因为车辆的现有 API 已知。

示例：https://github.com/commaai/openpilot/pull/30672/
