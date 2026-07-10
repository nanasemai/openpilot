# 什么是车型适配（Car Port）？

车型适配（Car Port）是指为特定车型添加 openpilot 支持。openpilot 支持的每款车型都需要单独进行适配。车型适配的复杂度因多种因素而异，包括：

* 已有 openpilot 对类似车型的支持程度
* 车辆可用的架构和 API

# 车型适配的结构

所有车型特定代码都包含在 [opendbc](https://github.com/commaai/opendbc) 项目中。

## opendbc

每个汽车品牌通过 `opendbc/car/[品牌]` 下的标准接口结构获得支持：

* `interface.py`：车辆接口，定义 CarInterface 类
* `carstate.py`：从车辆读取 CAN 消息，构建 openpilot CarState 消息
* `carcontroller.py`：在车辆上执行 openpilot CarControl 动作的控制逻辑
* `[品牌]can.py`：组合 CAN 消息供 carcontroller 发送
* `values.py`：执行限制、通用车辆常量以及受支持车辆的文档
* `radar_interface.py`：解析车辆雷达点（如适用）的接口

## safety

* `opendbc/safety/modes/[品牌].h`：品牌特定的安全逻辑
* `opendbc/safety/tests/test_[品牌].py`：品牌特定的安全 CI 测试

## openpilot

由于历史原因，openpilot 仍包含少量车型特定逻辑。这些最终会迁移到 opendbc 或以其他方式移除。

* `selfdrive/car/car_specific.py`：品牌特定的事件逻辑

# 如何进行车型适配？

[Jason Young](https://github.com/jyoung8607) 在 COMMA_CON 上做了一个关于车型适配流程概述的演讲，可在 YouTube 上观看：

https://www.youtube.com/watch?v=XxPS5TpTUnI

## 品牌适配（Brand Port）

品牌适配是指将 openpilot 适配到一个全新的汽车品牌或该品牌下的新平台。

以下是一个示例：https://github.com/commaai/openpilot/pull/23331。

## 车型适配（Model Port）

车型适配是指将 openpilot 适配到已受支持品牌中的一款新车型。车型适配比品牌适配更简单，因为车辆的现有 API 已经是已知的。

以下是一个示例：https://github.com/commaai/openpilot/pull/30672/。
