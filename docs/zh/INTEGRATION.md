# 与原车功能的集成

在所有支持的车型上：
* 原车车道保持辅助（LKA）和原车自动车道居中（ALC）将被 openpilot ALC 替代，后者仅在用户启用 openpilot 时生效。
* 原车车道偏离预警（LDW）将被 openpilot LDW 替代。

此外，在部分特定支持的车型上（参见[支持车型](CARS.md)中的 ACC 列）：
* 原车 ACC 将被 openpilot ACC 替代。
* openpilot FCW 在原有 FCW 基础上额外生效。

openpilot 应保留车辆的所有其他原车功能，包括但不限于：FCW、自动紧急制动（AEB）、自动远光灯、盲点预警和侧碰撞预警。
