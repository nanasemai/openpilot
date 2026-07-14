# 与原车功能集成

在所有支持的车辆上：
* 原厂车道保持辅助（LKA）和原厂 ALC 被 openpilot ALC 替代，后者仅在用户启用 openpilot 时起作用。
* 原厂 LDW 被 openpilot LDW 替代。

此外，在特定支持的车辆上（请参阅[支持车型](CARS.md)中的 ACC 列）：
* 原厂 ACC 被 openpilot ACC 替代。
* openpilot FCW 在原厂 FCW 基础上额外工作。

openpilot 应保留车辆的所有其他原厂功能，包括但不限于：FCW、自动紧急制动（AEB）、自动远光灯、盲点警告和侧面碰撞警告。
