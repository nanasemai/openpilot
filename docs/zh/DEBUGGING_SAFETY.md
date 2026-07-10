# 使用 Replay Drive + LLDB 调试 Panda 安全代码

## 1. 在 VS Code 中启动调试器

* 选择 **Replay drive + Safety LLDB** 配置。
* 根据提示输入路线或片段标识。
[<img src="https://github.com/user-attachments/assets/b0cc320a-083e-46a7-a9f8-ca775bbe5604">](https://github.com/user-attachments/assets/b0cc320a-083e-46a7-a9f8-ca775bbe5604)

## 2. 附加 LLDB

* 根据提示，选择正在运行的 **`replay_drive` 进程**。
* ⚠️ 请快速完成附加，否则 `replay_drive` 将开始消费消息。

> [!TIP]
> 在 `replay_drive.py` 开头添加一个 Python 断点，以暂停执行，为您留出附加 LLDB 的时间。

## 3. 在 VS Code 中设置断点
断点可以直接设置在 `modes/xxx.h`（或任何 C 文件）中。
无需额外的 LLDB 命令——只需在编辑器中放置断点即可。

## 4. 恢复执行
附加成功后，您可以在重放 CAN 日志时，同时在 Python（重放端）和 C 安全代码中单步调试。

> [!NOTE]
> * 使用短路线可以加快迭代速度。
> * 尽早暂停 `replay_drive`，避免浪费日志消息。

## 视频演示

查看添加此功能的 PR 中的工作流演示：https://github.com/commaai/openpilot/pull/36055#issue-3352911578
