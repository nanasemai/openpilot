# 如何贡献

我们的软件是开源的，因此您可以自行解决问题而无需他人帮助。如果您解决了某个问题并且乐于分享，可以将其上游提供给全世界使用。查看我们的[关于外部化的文章](https://blog.comma.ai/a-2020-theme-externalization/)。

开发协调通过 [Discord](https://discord.comma.ai) 和 GitHub 进行。

### 入门指南

* 设置您的[开发环境](/tools/)
* 加入我们的 [Discord](https://discord.comma.ai)
* 文档位于 https://docs.comma.ai 和 https://blog.comma.ai

## 我们寻找什么样的贡献？

**openpilot 的优先级依次是[安全](SAFETY.md)、稳定性、质量和功能。**
openpilot 是 comma 实现*解决自动驾驶问题同时交付可发布的中介产物*使命的一部分，所有开发都朝着这个目标进行。

### 什么会被合并？

拉取请求被合并的概率取决于它对项目的价值以及我们需要花费多少精力来合并它。
如果一个 PR 提供了*一些*价值但需要很长时间才能合并，它将被关闭。
简单、经过充分测试的 bug 修复最容易合并，而新功能最难合并。

以下都是优秀 PR 的示例：
* 拼写修正：https://github.com/commaai/openpilot/pull/30678
* 删除未使用的代码：https://github.com/commaai/openpilot/pull/30573
* 简单的车型适配：https://github.com/commaai/openpilot/pull/30245
* 车辆品牌适配：https://github.com/commaai/openpilot/pull/23331

### 什么不会被合并？

* **代码风格更改**：代码是艺术，由作者负责使其优美
* **超过 500 行的 PR**：请精简，拆分成较小的 PR，或两者都做
* **没有明确目标的 PR**：每个 PR 必须有一个明确的目标
* **UI 设计**：我们对此还没有良好的审查流程
* **新功能**：我们认为 openpilot 在功能上已基本完备，剩余的是优化和修复 bug 的工作。因此，大多数功能 PR 会被立即关闭，但开源的美妙之处在于分支可以而且确实提供了上游 openpilot 没有的功能。
* **负期望值**：这类 PR 做出了改进，但其风险或验证成本超过了改进本身的价值。可以通过先合并一个失败的测试来降低风险。

### 首次贡献

[项目 / openpilot 悬赏](https://github.com/orgs/commaai/projects/26/views/1?pane=info)是最好的入门途径，并深入介绍了悬赏任务的要求。
有很多悬赏任务不需要 comma four 或车辆。

## 拉取请求

拉取请求应针对 master 分支。

一个好的拉取请求具备以下所有条件：
* 明确陈述的目的
* 每一行修改都直接服务于所述目的
* 验证，即您如何测试您的 PR？
* 合理性说明
  * 如果您优化了某项功能，请提供基准测试来证明其更好
  * 如果您改进了车辆的调校，请提供前后对比图
* 通过 CI 测试

## 无需代码的贡献

* 在 GitHub issues 中报告 bug。
* 在 `#driving-feedback` Discord 频道中报告驾驶问题。
* 考虑选择加入驾驶员摄像头上传以改进驾驶员监控模型。
* 定期将设备连接到 Wi-Fi，以便我们可以拉取数据来训练更好的驾驶模型。
* 运行 `nightly` 分支并报告问题。该分支类似于 `master`，但以发布版本的方式构建。
* 在 [comma10k 数据集](https://github.com/commaai/comma10k)中标注图像。

## 贡献训练数据

### 分支指南

为了使您分支的数据有资格用于训练集：
* **您的 cereal 消息结构必须[兼容](../cereal#custom-forks)**
* **所有原始消息结构的定义不得更改**：不要更改任何字段的设置方式，包括从 `selfdriveState.enabled` 到 `carState.steeringAngleDeg` 的所有内容。相反，创建您自己的结构并按您的需要设置它们。
* **不要包含上游平台不支持的车款**：相反，为您希望在上游之外支持的车款创建新的 opendbc 平台，即使只是一个配置级别的差异。
