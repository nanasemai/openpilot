# 安全

openpilot 是一个自适应巡航控制（ACC）和自动车道居中（ALC）系统。与其他 ACC 和 ALC 系统一样，openpilot 是一个故障安全的被动系统，要求驾驶员保持警觉并时刻注意路况。

为帮助驾驶员保持警觉，openpilot 包含一个驾驶员监控功能，在检测到驾驶员分心时会发出警报。

然而，即使驾驶员保持警觉，我们仍需付出更多努力来确保系统的安全性。我们重申，**驾驶员的警觉性是安全使用 openpilot 的必要条件，但不是充分条件**，openpilot 不提供任何适用性担保。

openpilot 是本着善意开发的，旨在符合 FMVSS 要求，并遵循 Level 2 驾驶辅助系统的行业安全标准。特别是，我们遵守 ISO26262 准则，包括 NHTSA 发布的[相关文件](https://www.nhtsa.gov/sites/nhtsa.dot.gov/files/documents/13498a_812_573_alcsystemreport.pdf)中的内容。此外，我们在 openpilot 中与安全相关的部分实施严格的编码规范（如 [MISRA C : 2012](https://www.misra.org.uk/what-is-misra/)）。在每次软件发布之前，我们还会进行软件在环、硬件在环以及实车测试。

根据危险分析和风险评估以及 FMEA 的结果，从宏观层面来看，我们设计 openpilot 时确保了两个主要的安全要求。

1. 驾驶员必须始终能够立即重新获得车辆的手动控制权，通过踩下制动踏板或按下取消按钮即可实现。
2. 车辆不得过快地改变行驶轨迹，以确保驾驶员有足够时间安全地做出反应。这意味着系统在启用时，执行器将限制在合理的范围内运行[^1]。

有关安全实现的更多细节，请参考 [panda 安全模型](https://github.com/commaai/panda#safety-model)。有关车辆特定安全概念的实现，请参考 [opendbc/safety/safety](https://github.com/commaai/opendbc/tree/master/opendbc/safety/safety)。

[^1]: 对于这些执行器限制，我们遵循 ISO11270 和 ISO15622 标准。其中描述的横向限制相当于最大作用 0.9 秒以达到 1 米的横向偏移。

---

### openpilot 分支

* 请勿禁用或削弱[驾驶员监控功能](https://github.com/commaai/openpilot/tree/master/selfdrive/monitoring)
* 请勿禁用或削弱[过度执行检测](https://github.com/commaai/openpilot/tree/master/selfdrive/selfdrived/helpers.py)
* 如果您分支修改了 `opendbc/safety/` 中的任何代码：
   * 您的分支不得使用 openpilot 商标
   * 您的分支必须保留完整的[安全测试套件](https://github.com/commaai/opendbc/tree/master/opendbc/safety/tests)，并且所有测试必须通过，包括分支修改所要求的任何新增测试覆盖

未遵守这些标准将导致您和您的用户被禁止使用 comma.ai 服务器。

**comma.ai 强烈反对使用安全代码缺失或未完全满足上述要求的 openpilot 分支。**
