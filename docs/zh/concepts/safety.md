# 安全

openpilot 是一个自适应巡航控制（ACC）和自动车道居中（ALC）系统。与其他 ACC 和 ALC 系统一样，openpilot 是一个故障安全的被动系统，要求驾驶员始终保持警觉并时刻注意路况。

为了帮助驾驶员保持警觉，openpilot 包含驾驶员监控功能，会在检测到驾驶员分心时发出提醒。

然而，即使有警觉的驾驶员，我们仍需做出进一步努力来确保系统的安全性。我们再次强调，**驾驶员的警觉性是 openpilot 安全使用的必要条件，但并不充分**，openpilot 不提供任何适用性保证。

openpilot 本着诚信原则开发，力求符合 FMVSS 要求，并遵循 Level 2 驾驶员辅助系统的行业安全标准。具体而言，我们遵循 ISO26262 指南，包括 NHTSA 发布的 [相关文件](https://www.nhtsa.gov/sites/nhtsa.dot.gov/files/documents/13498a_812_573_alcsystemreport.pdf) 中的内容。此外，我们对 openpilot 中涉及安全的部分实施严格的编码规范（如 [MISRA C : 2012](https://www.misra.org.uk/what-is-misra/)）。在每次软件发布之前，我们还会进行软件在环、硬件在环以及实车测试。

通过危害分析与风险评估（HARA）和失效模式与影响分析（FMEA），我们从高层设计上确保 openpilot 满足两个主要的安全要求。

1. 驾驶员必须始终能够立即重新接管车辆的手动控制，方式包括踩下制动踏板或按下取消按钮。
2. 车辆不得过快改变其行驶轨迹，以确保驾驶员有足够的时间安全应对。这意味着系统在激活状态下，执行器的操作被限制在合理的范围内[^1]。

有关安全实现的更多细节，请参阅 [panda 安全模型](https://github.com/commaai/panda#safety-model)。有关安全概念在具体车型上的实现，请参阅 [opendbc/safety/safety](https://github.com/commaai/opendbc/tree/master/opendbc/safety/safety)。

[^1]: 对于这些执行器限制，我们遵循 ISO11270 和 ISO15622 标准。其中描述的横向限制转换为最大执行时间 0.9 秒以实现 1 米的横向偏移。

---

### openpilot 的分支

* 不得禁用或削弱 [驾驶员监控](https://github.com/commaai/openpilot/tree/master/selfdrive/monitoring)
* 不得禁用或削弱 [过度执行检查](https://github.com/commaai/openpilot/tree/master/selfdrive/selfdrived/helpers.py)
* 如果您的分支修改了 `opendbc/safety/` 中的任何代码：
   * 您的分支不得使用 openpilot 商标
   * 您的分支必须保留完整的 [安全测试套件](https://github.com/commaai/opendbc/tree/master/opendbc/safety/tests)，并且所有测试必须通过，包括分支修改所要求的任何新增覆盖率

未能遵守上述标准将导致您和您的用户被禁止访问 comma.ai 服务器。

**comma.ai 强烈反对使用缺少安全代码或安全代码未完全满足上述要求的 openpilot 分支。**
