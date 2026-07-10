# 如何贡献

我们的软件是开源的，因此您可以自行解决问题，无需依赖他人。如果您解决了某个问题并且乐于分享，也可以将其贡献到上游，让全世界受益。请阅读我们关于[外部化](https://blog.comma.ai/a-2020-theme-externalization/)的文章。

开发工作通过 [Discord](https://discord.comma.ai) 和 GitHub 进行协调。

### 开始之前

* 搭建您的[开发环境](/tools/)
* 加入我们的 [Discord](https://discord.comma.ai)
* 文档位于 https://docs.comma.ai 和 https://blog.comma.ai

## 我们欢迎什么样的贡献？

**openpilot 的优先级依次是：安全、稳定性、质量、功能。**

openpilot 是 comma 实现*解决自动驾驶问题，同时交付可落地的阶段性成果*这一使命的一部分，所有开发工作都朝着这个目标前进。

### 哪些贡献会被合并？

拉取请求被合并的可能性取决于其对项目的价值以及我们将其合并所需投入的精力。
如果一个 PR 提供了*一定*价值，但需要大量时间才能合并，它将被关闭。
简单、经过充分测试的 Bug 修复最容易合并，而新功能最难合并。

以下都是优秀 PR 的示例：
* 修正拼写错误：https://github.com/commaai/openpilot/pull/30678
* 移除未使用的代码：https://github.com/commaai/openpilot/pull/30573
* 简单的车型移植：https://github.com/commaai/openpilot/pull/30245
* 汽车品牌移植：https://github.com/commaai/openpilot/pull/23331

### 哪些贡献不会被合并？

* **风格修改**：代码是艺术，美丑由作者决定
* **超过 500 行的 PR**：请清理代码、拆分为更小的 PR，或两者兼顾
* **目标不明确的 PR**：每个 PR 必须有单一且明确的目标
* **UI 设计**：我们目前还没有完善的 UI 审查流程
* **新功能**：我们认为 openpilot 的功能已基本完备，剩下的工作是优化和修复 Bug。因此，大多数功能 PR 会立即被关闭，但开源的美好之处在于，分支可以提供上游 openpilot 所没有的功能。
* **负期望值**：这类 PR 虽然带来了一定改进，但其风险或验证成本超过了改进本身的价值。可以通过先提交一个会失败的测试来降低风险。

### 第一次贡献

[Projects / openpilot bounties](https://github.com/orgs/commaai/projects/26/views/1?pane=info) 是最好的入门途径，其中详细介绍了参与悬赏任务的注意事项。
许多悬赏任务不需要 comma four 硬件或实车。

## 拉取请求

拉取请求应提交到 master 分支。

一个好的拉取请求应满足以下所有条件：
* 明确陈述目的
* 每一行修改都直接服务于所述目的
* 提供验证方法，即您如何测试您的 PR？
* 提供充分的理由
  * 如果您优化了某项性能，请提供基准测试数据证明其更优
  * 如果您改进了某款车型的调校，请提供优化前后的对比图表
* 通过 CI 测试

## 通过非代码方式贡献

* 在 GitHub Issues 中报告 Bug。
* 在 Discord 的 `#driving-feedback` 频道中报告驾驶问题。
* 考虑选择上传驾驶员摄像头数据，以帮助改进驾驶员监控模型。
* 定期将您的设备连接到 Wi-Fi，以便我们拉取数据来训练更好的驾驶模型。
* 使用 `nightly` 分支并报告问题。该分支与 `master` 类似，但以发布版本的方式构建。
* 在 [comma10k 数据集](https://github.com/commaai/comma10k)中标注图像。

## 贡献训练数据

### 分支指南

要使您分支的数据有资格纳入训练集：
* **您的 cereal 消息结构必须[兼容](../cereal#custom-forks)**
* **所有原车消息结构的定义不得更改**：不得更改任何字段的设置方式，包括从 `selfdriveState.enabled` 到 `carState.steeringAngleDeg` 的所有内容。请创建您自己的结构体并按需设置。
* **不要包含上游平台不支持的车型**：请为上游之外您想支持的车型创建新的 opendbc 平台，即使只是配置等级的差异。
