# 日志

openpilot 将行车记录以一分钟为一段进行分段存储，称为 segment。一个 route 从点火信号上升沿开始，到下降沿结束。

请查阅我们的 [Python 库](https://github.com/commaai/openpilot/blob/master/tools/lib/logreader.py) 了解如何读取 openpilot 日志。也可以查看我们的 [工具集](https://github.com/commaai/openpilot/tree/master/tools) 来回放和查看数据。这些就是我们用于调试和开发 openpilot 的同一套工具。

每个 segment，openpilot 会记录以下日志类型：

## rlog.zst

rlog 包含所有在 openpilot 进程间传递的消息。请参阅 [cereal/services.py](https://github.com/commaai/openpilot/blob/master/cereal/services.py) 了解所有被记录的 service 列表。它们是序列化 [Cap'n Proto](https://capnproto.org/) 消息的 zstd 归档文件。

## {f,e,d}camera.hevc

每个摄像头流都以 H.265 编码并写入对应的文件。

* `fcamera.hevc` 是前视道路摄像头
* `ecamera.hevc` 是广角道路摄像头
* `dcamera.hevc` 是驾驶员摄像头

## qlog.zst & qcamera.ts

qlog 是 rlog 的降采样子集。请查阅 [cereal/services.py](https://github.com/commaai/cereal/blob/master/services.py) 了解降采样规则。

qcamera 是 H.264 编码、低分辨率的 fcamera.hevc 版本。[comma connect](https://connect.comma.ai/) 上显示的视频就来自 qcamera。

qlog 和 qcamera 被设计得足够小，即使在慢速网络下也能即时上传，同时又足够用于大部分分析和调试工作。
