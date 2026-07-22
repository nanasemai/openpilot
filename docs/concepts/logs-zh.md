# 日志记录

openpilot 将行驶路线记录为一分钟长的数据块，称为片段（segment）。一条路线从点火信号上升沿开始，到下降沿结束。

查看我们的 [Python 库](https://github.com/commaai/openpilot/blob/master/tools/lib/logreader.py)以读取 openpilot 日志。另请查看我们的[工具](https://github.com/commaai/openpilot/tree/master/tools)来回放和查看您的数据。这些也是我们用于调试和开发 openpilot 的工具。

对于每个片段，openpilot 记录以下日志类型：

## rlog.zst

rlog 包含 openpilot 各进程之间传递的所有消息。请参阅 [cereal/services.py](https://github.com/commaai/openpilot/blob/master/cereal/services.py) 获取所有已记录服务的列表。它们是经过序列化的 [Cap'n Proto](https://capnproto.org/) 消息的 zstd 归档文件。

## {f,e,d}camera.hevc

每个摄像头流以 H.265 编码并写入相应的文件。

* `fcamera.hevc` 是面向道路的摄像头
* `ecamera.hevc` 是广角道路摄像头
* `dcamera.hevc` 是驾驶员摄像头

## qlog.zst 和 qcamera.ts

qlog 是 rlog 的抽样子集。请参阅 [cereal/services.py](https://github.com/commaai/cereal/blob/master/services.py) 了解抽取规则。

qcamera 是 H.264 编码、低分辨率的 fcamera.hevc 版本。[comma connect](https://connect.comma.ai/) 中显示的视频来自 qcamera。

qlog 和 qcamera 设计为即使在慢速网络下也能即时上传，同时又足够用于大多数分析和调试。
