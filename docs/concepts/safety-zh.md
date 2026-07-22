# 安全性

openpilot 是一个自适应巡航控制（ACC）和自动车道居中（ALC）系统。
与其他 ACC 和 ALC 系统一样，openpilot 是一个故障安全型被动系统，要求驾驶员保持警觉并始终注意路况。

为了帮助驾驶员保持警觉，openpilot 包含一个驾驶员监控功能，在检测到驾驶员分心时发出警报。

然而，即使驾驶员保持警觉，我们仍需进一步努力确保系统的安全。我们重申，**驾驶员的警觉性是安全使用 openpilot 的必要条件，但不是充分条件**，且 openpilot 不提供任何适用性保证。

openpilot 是出于善意开发的，旨在符合 FMVSS 要求，并遵循 Level 2 驾驶员辅助系统的行业安全标准。特别是，我们遵守 ISO26262 指南，包括 NHTSA 发布的[相关文件](https://www.nhtsa.gov/sites/nhtsa.dot.gov/files/documents/13498a_812_573_alcsystemreport.pdf)中的内容。此外，我们在 openpilot 的安全相关部分实施严格的编码指南（如 [MISRA C：2012](https://www.misra.org.uk/what-is-misra/)）。我们还在每次软件发布前进行软件在环、硬件在环和实车测试。

通过危害分析和风险评估以及 FMEA，我们在高层次上设计了 openpilot 以确保两个主要安全要求：

1. 驾驶员必须始终能够立即重新取得车辆的 manual 控制权，通过踩下制动踏板或按下取消按钮。
2. 车辆不得过快改变轨迹，以确保驾驶员能够安全地做出反应。这意味着在系统启用期间，执行器被限制在合理范围内操作[^1]。

有关安全实现的更多详细信息，请参阅 [panda 安全模型](https://github.com/commaai/panda#safety-model)。有关车辆特定安全实现，请参阅 [opendbc/safety/safety](https://github.com/commaai/opendbc/tree/master/opendbc/safety/safety)。

[^1]: 对于这些执行器限制，我们遵守 ISO11270 和 ISO15622。其中描述的横向限制相当于最大执行 0.9 秒以实现 1 米的横向偏移。

---

### openpilot 的分支

* 请勿禁用或削弱[驾驶员监控](https://github.com/commaai/openpilot/tree/master/selfdrive/monitoring)
* 请勿禁用或削弱[过度执行检查](https://github.com/commaai/openpilot/tree/master/selfdrive/selfdrived/helpers.py)
* 如果您分支修改了 `opendbc/safety/` 中的任何代码：
   * 您的分支不能使用 openpilot 商标
   * 您的分支必须保留完整的[安全测试套件](https://github.com/commaai/opendbc/tree/master/opendbc/safety/tests)，并且所有测试必须通过，包括分支更改所需的新测试覆盖

未遵守这些标准的用户将被禁止使用 comma.ai 服务器。

**comma.ai 强烈反对使用缺少安全代码或安全代码未完全满足上述要求的分支。**
