# Screen Recorder — 完整实现计划

## 目标

在 openpilot_nanasemai（raylib UI）里实现车载屏幕录制功能，满足：

1. **UI 触发**：主屏按钮**双击**启动录制，双击停止
2. **UI 反馈**：录制中 UI 有明显视觉变化
3. **默认参数**：**720p / 20fps / 1Mbps**（固定，不跟 UI 帧率联动）
4. **分段录制**：**每 3 分钟（180 秒）**切一个新文件，不长时间连续写一个文件
5. **最低开销**：优先硬编，动态降级
6. **设置页**：分辨率 / 码率 / 切片时长 / 录制目录 / **最大总时长**可调
7. **编码器选择**：运行时探测系统能力，取最优解
8. **U 盘支持**：插入 U 盘时优先写入外置存储，拔出后无缝回退到内部 eMMC
9. **循环录制**：可配置最大总时长（默认 8 小时），超过后自动删除最早文件
10. **系统时间正确性**：启动录制前校验系统时间，无效时自动同步（NTP → GPS → Panda RTC → 上次有效时间）
11. **时区配置**：设置里可选择时区，后台服务根据 GPS / IP 自动检测
12. **UI 时间显示**：主屏**顶部中央**始终显示当前日期和时间，录制中同步高亮

---

## 一、编码方案（按优先级）

系统侧探测顺序，运行时选择第一个可用的：

| 优先级 | 编码方式 | 依赖 | CPU 开销 | 视频体积 | 备注 |
|---|---|---|---|---|---|
| 1 | **ffmpeg nvenc/qsv 类** | n/a（无独立 GPU 编码） | - | - | C3/C3X 上不可用 |
| 2 | **Qualcomm OMX HEVC** | `libopenmaxil.so` + `OMX.qcom.video_encoder.hevc` | < 3% | 最小 | 需 agnos userspace 有 OMX HAL |
| 3 | **OpenCL + ffmpeg mpeg4/hevc软编加速** | `libOpenCL.so` | ~15% | 中 | OpenCL 加速预处理 |
| 4 | **ffmpeg libx264**（默认兜底） | `ffmpeg` (commaai/dependencies) | ~30-40% | 中 | 已可用，`RECORD=1` 就是这个 |
| 5 | **ffmpeg mpeg4**（超兜底） | `ffmpeg` | ~10% | 大 | 老格式，兼容性差，不推荐 |

**最终策略**：
- 启动时探测 OMX HAL 是否存在（`dlopen("libopenmaxil.so")`）
- 若可用 → 用 OMX HEVC 硬编（移植 carrotpilot 的 `omx_encoder.cc`）
- 否则 → 用 ffmpeg libx264 preset=ultrafast（比当前 `veryfast` 更省 CPU）
- 都失败 → 报错，不启动录制

**固定参数**（不跟 UI 帧率联动）：
- 分辨率：**720p（1280×720）**默认，支持 **1080p（1920×1080）**切换
- 帧率：**20 fps**（比 C3X UI 20fps 匹配，比 C3 UI 60fps 低——录屏够用，CPU 压力天然小）
- 码率：**1 Mbps**
- 切片：**180 秒**（3 分钟）
- GOP：**40**（2 秒一个关键帧）
- 最大总时长：**8 小时**（默认，超过后自动删最老文件，循环录制）

### 1.1 ffmpeg 参数（软编兜底）

```bash
ffmpeg \
  -f rawvideo -pix_fmt rgba \
  -s 1280x720 -r 20 -i pipe:0 \
  -vf vflip,format=yuv420p \
  -c:v libx264 \
  -preset ultrafast \
  -tune zerolatency \
  -crf 28 \
  -x264-params keyint=<2*FPS>:scenecut=0:bframes=0 \
  -gop_size <2*FPS> \
  -y -f mp4 <output>
```

**参数说明**：
- `preset ultrafast`：最快编码，速度换体积，适合录屏
- `tune zerolatency`：低延迟，无 B 帧
- `crf 28`：默认质量，比 CRF 23 小 40%，肉眼足够
- `bframes=0`：禁用 B 帧，进一步降延迟
- `gop_size = 2*FPS`：关键帧每 2 秒一次

### 1.2 OMX 硬编参数（优先）

- 组件名：`OMX.qcom.video_encoder.hevc`
- 分辨率：1280x720
- 帧率：UI FPS
- 码率：1 Mbps（默认）
- 关键帧间隔：2 秒
- 输出：裸 ES → FFmpeg `AVFormatContext` 封 MP4

---

## 二、文件结构

```
openpilot_nanasemai/
├── system/ui/
│   ├── lib/application.py                     # 已存在，需暴露 render_texture
│   └── screenrecorder/                        # 新增目录
│       ├── __init__.py                        # 对外 API：start/stop/toggle/is_recording
│       ├── recorder.py                        # 核心控制逻辑
│       ├── storage.py                         # 存储位置管理：U 盘探测、切换、目录校验
│       ├── encoder_detect.py                  # 运行时编码器探测
│       ├── encoder_ffmpeg.py                  # ffmpeg 子进程封装（兜底方案）
│       ├── encoder_omx.py                     # OMX 硬编封装（首选，可选）
│       ├── frame_source.py                    # 从 render_texture 抓帧
│       └── omx_encoder/                       # 可选：移植 carrotpilot 的 C++
│           ├── omx_encoder.cpp
│           └── omx_encoder.h
│
├── selfdrive/ui/
│   ├── onroad/
│   │   ├── cameraview.py                      # 修改：挂 RecordButton
│   │   └── record_button.py                   # 新增：主屏按钮 widget
│   ├── sunnypilot/layouts/settings/
│   │   ├── __init__.py                        # 修改：加 ScreenRecorderSettings
│   │   └── screenrecorder.py                  # 新增：设置页
│   └── onroad/offroad_indicator.py            # 可选：新增：offroad 状态条
│
└── common/params_keys.h                       # 修改：新增 4 个 param key
```

---

## 三、Params 定义

在 `common/params_keys.h` 中添加（`ScreenRecord` 已存在）：

```c
{"ScreenRecordPath",    {NO_CLEAR}},              // 录制目录，默认 /data/media/0/screenrecord
{"ScreenRecordRes",     {NO_CLEAR}},              // "720p"（默认）| "1080p"
{"ScreenRecordFps",     {NO_CLEAR}},              // "10" | "15" | "20"（默认）| "30"
{"ScreenRecordSlice",   {NO_CLEAR}},              // 切片秒数，默认 180（3 分钟）
{"ScreenRecordBitrate", {NO_CLEAR}},              // "500k" | "1M" | "2M"（默认 1M）
{"ScreenRecorderEncoder", {NO_CLEAR}},            // "auto"（默认）| "omx" | "ffmpeg" | "forced"
{"ScreenRecordUdisk",   {NO_CLEAR}},              // true/false：是否使用 U 盘（默认 true=自动探测）
{"ScreenRecordMaxHours",{NO_CLEAR}},              // 最大总录制时长（小时），默认 "8"，超过自动删旧文件
// ── UI 时间显示（沿用 nanapilot 参数名） ──
{"dp_show_date_time",   {NO_CLEAR}},              // 是否在 UI 顶部显示时间/日期
// ── 时间相关（新增，参考 nanapilot） ──
{"Timezone",            {NO_CLEAR}},              // "Asia/Shanghai" 等 IANA 时区名
{"LastValidTime",       {NO_CLEAR}},              // 上次有效 Unix 时间戳（秒）
{"TimeAutoSync",        {NO_CLEAR}},              // bool：允许开机/录制前自动同步时间
{"TimeSyncNtpServers",  {NO_CLEAR}},              // 逗号分隔 NTP 服务器列表
{"TimeMinValidYear",    {NO_CLEAR}},              // 有效时间最小年份，默认 "2024"
```

`ScreenRecord` 已有（BOOL），语义：当前是否正在录制。

### 3.1 首次启动默认值

在 `system/hardware/tici/updater/` 或 params 初始化时写入：

```python
DEFAULTS = {
  "ScreenRecordPath":    "/data/media/0/screenrecord",
  "ScreenRecordRes":     "720p",
  "ScreenRecordFps":     "20",
  "ScreenRecordSlice":   "180",        # 3 分钟
  "ScreenRecordBitrate": "1M",
  "ScreenRecorderEncoder": "auto",
  "ScreenRecordUdisk":   "True",       # 自动探测 U 盘
  "ScreenRecordMaxHours": "8",         # 循环录制最大总时长
  "dp_show_date_time":    "True",      # UI 顶部显示时间

  # 时间（默认中国时区，NTP 服务器按国内优先级）
  "Timezone":           "Asia/Shanghai",
  "TimeAutoSync":       "True",
  "TimeSyncNtpServers": "ntp.aliyun.com,ntp.tencent.com,cn.ntp.org.cn,ntp.ntsc.ac.cn,ntp.ubuntu.com",
  "TimeMinValidYear":   "2024",
}
```

---

## 四、核心组件设计

### 4.1 `encoder_detect.py` — 运行时能力探测

```python
"""探测系统可用编码器，返回优先级最高的"""

import ctypes
import shutil
from pathlib import Path


def detect_encoder() -> str:
    """
    返回：'omx' | 'ffmpeg' | 'none'
    - 'omx'：libopenmaxil.so 存在 + OMX.qcom.video_encoder.hevc 组件可用
    - 'ffmpeg'：ffmpeg 命令可执行
    - 'none'：都不可用
    """
    forced = params.get("ScreenRecorderEncoder")
    if forced in ("omx", "ffmpeg"):
        return forced if _check(forced) else "none"

    if _check_omx():
        return "omx"
    if _check_ffmpeg():
        return "ffmpeg"
    return "none"


def _check_omx() -> bool:
    """尝试加载 libopenmaxil.so"""
    try:
        lib = ctypes.CDLL("libopenmaxil.so")
        # 检查是否有关键函数
        if hasattr(lib, "OMX_GetComponentsByRole"):
            return True
    except OSError:
        pass
    return False


def _check_ffmpeg() -> bool:
    """检查 ffmpeg 命令是否可用"""
    return shutil.which("ffmpeg") is not None


def _check(backend: str) -> bool:
    return {"omx": _check_omx, "ffmpeg": _check_ffmpeg}.get(backend, lambda: False)()
```

### 4.2 `frame_source.py` — 帧采集

```python
"""从 gui_app._render_texture 抓帧，缩放到目标分辨率"""

import numpy as np
import pyray as rl
from openpilot.system.ui.lib.application import gui_app


class FrameSource:
    def __init__(self, target_w: int, target_h: int):
        self.target_w = target_w
        self.target_h = target_h

    def grab(self) -> np.ndarray | None:
        """返回一个 h*w*4 的 numpy 数组，或 None"""
        rt = gui_app._render_texture
        if rt is None:
            return None
        img = rl.load_image_from_texture(rt.texture)
        if (img.width, img.height) != (self.target_w, self.target_h):
            rl.image_resize(img, self.target_w, self.target_h)
        size = self.target_w * self.target_h * 4
        arr = np.frombuffer(
            bytes(rl.ffi.buffer(img.data, size)),
            dtype=np.uint8
        ).reshape(self.target_h, self.target_w, 4).copy()
        rl.unload_image(img)
        return arr
```

**性能关键点**：
- GPU 侧 `image_resize` 做缩放（不是 CPU）
- `copy()` 必须，避免 `rl.unload_image` 后 buffer 失效
- 分辨率从 2160x1080 降到 1280x720，像素数降 55%，GPU→CPU 拷贝数据量同比例减少

### 4.3 `storage.py` — 存储位置管理（U 盘 + eMMC 切换）

**这是 U 盘支持的核心**。运行时动态选择写入位置。

#### 4.3.1 内核侧支持情况

已验证（`agnos-builder-sdm845/linux-android-oneplus-oneplus6/out/.config`）：

```
CONFIG_SCSI=y
CONFIG_USB_STORAGE=y
CONFIG_USB_DWC3=y
CONFIG_USB_DWC3_MSM=y
CONFIG_USB_MSM_SSPHY_QMP=y
CONFIG_SCSI_UFSHCD=y   # 内部 UFS eMMC
```

**结论**：USB 大容量存储的内核栈完整（SCSI + usb-storage + DWC3），插入 U 盘应该能枚举出 `/dev/sda*`，但**需要 C3/C3X 的 dtb 里显式启用 dwc3 为 host 模式**（当前 dtb 未验证，需实测）。

#### 4.3.2 挂载路径约定

agnos 上 U 盘常见挂载路径：
- `/media/0`、`/media/1`（Android-style，C3 可能用这个）
- `/mnt/usb`、`/run/media/<user>/*`（Linux 风格）
- `/dev/disk/by-label/<LABEL>`（按 label）

**策略**：扫描多个候选路径，找第一个是 USB 块设备且可写的。

```python
"""U 盘探测与目录选择"""

import os
import shutil
import time
from pathlib import Path


USB_MOUNT_CANDIDATES = [
    "/media/0",           # Android mount point
    "/media/1",
    "/run/media/usb",     # udisks / gnome-auto-mount
    "/mnt/usb",
    "/data/media/usb",    # custom
]

MIN_USB_FREE_GB = 2.0


def detect_usb_root() -> Path | None:
    """扫描常见挂载点，返回第一个可用 U 盘根目录"""
    for p in USB_MOUNT_CANDIDATES:
        path = Path(p)
        if _is_writable_usb(path):
            return path
    return None


def _is_writable_usb(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        # 检查是否是 usb 块设备（通过 mountinfo）
        mountinfo = _read_mountinfo()
        dev = _get_device_for_path(path, mountinfo)
        if dev is None:
            return False
        if not dev.startswith("/dev/sd"):
            # 只接受 /dev/sda /dev/sdb 等，排除 UFS (nvme/mmcblk)
            return False
        # 检查可写 + 空间
        os.access(path, os.W_OK)
        usage = shutil.disk_usage(path)
        return usage.free >= MIN_USB_FREE_GB * 1024**3
    except OSError:
        return False


def _read_mountinfo() -> str:
    try:
        with open("/proc/self/mountinfo") as f:
            return f.read()
    except OSError:
        return ""


def _get_device_for_path(path: Path, mountinfo: str) -> str | None:
    """从 mountinfo 找到路径对应的设备"""
    mount_str = str(path)
    # mountinfo 格式: id parent_id major:minor root mount_point ...
    for line in mountinfo.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        mount_point = parts[4].replace("\\040", " ")
        if mount_str.startswith(mount_point):
            return parts[2]  # major:minor
    return None


class StorageLocation:
    """管理录制输出的存储位置，支持 U 盘/eMMC 无缝切换"""

    def __init__(self, default_dir: str, use_udisk: bool = True):
        self.default_dir = Path(default_dir)
        self.use_udisk = use_udisk
        self._current_dir: Path | None = None
        self._last_check = 0

    def resolve(self) -> Path:
        """
        每次切片前调用，决定写入目录。
        优先 U 盘，U 盘不可用则回退到 eMMC。
        """
        now = time.monotonic()
        if now - self._last_check < 5.0:  # 5 秒缓存，避免每次切片都扫
            return self._current_dir or self.default_dir
        self._last_check = now

        if self.use_udisk:
            usb_root = detect_usb_root()
            if usb_root:
                target = usb_root / "screenrecord"
                try:
                    target.mkdir(parents=True, exist_ok=True)
                    self._current_dir = target
                    return target
                except OSError:
                    pass

        # 回退到 eMMC
        self._current_dir = self.default_dir
        return self.default_dir

    @property
    def is_using_udisk(self) -> bool:
        return self._current_dir is not None and str(self._current_dir).startswith("/media") or str(self._current_dir).startswith("/run/media") or str(self._current_dir).startswith("/mnt/usb")

    def check_space(self, min_gb: float = 1.0) -> bool:
        d = self._current_dir or self.default_dir
        try:
            usage = shutil.disk_usage(d)
            return usage.free >= min_gb * 1024**3
        except OSError:
            return True

    def cleanup_old_files(self, max_hours: float = 8.0):
        """
        循环录制：超过最大总时长时删除最早的文件。
        用文件 mtime 排序，最老的先删。
        """
        d = self._current_dir or self.default_dir
        if not d.exists():
            return

        # 收集所有 .mp4 文件
        files = sorted(
            (f for f in d.iterdir() if f.suffix.lower() == ".mp4"),
            key=lambda f: f.stat().st_mtime
        )
        if not files:
            return

        now = time.time()
        max_age_sec = max_hours * 3600
        cutoff = now - max_age_sec

        # 删除超过最大时长的文件
        deleted_count = 0
        for f in files:
            try:
                mtime = f.stat().st_mtime
                if mtime < cutoff:
                    f.unlink()
                    deleted_count += 1
                else:
                    break  # 已按时间排序，后面的都更新
            except OSError:
                continue

        if deleted_count:
            cloudlog.warning(
                f"ScreenRecord: rotated out {deleted_count} old file(s) "
                f"older than {max_hours}h from {d}"
            )
```

**关键设计**：
- 按 mtime 排序，删除比 `cutoff = now - max_hours * 3600` 更早的文件
- 用 `break` 提前退出，避免遍历全部文件（O(log n) 查找）
- 只处理 `.mp4` 文件，忽略其他临时文件
- 只删当前所在目录（U 盘或 eMMC 各独立循环）

#### 4.3.7 触发时机

在 `encoder_ffmpeg.py` 的 `_rotate_new_file()` 里，每次开新切片文件前调用：

```python
def _rotate_new_file(self):
    self._close_proc()
    now = time.localtime()
    filename = time.strftime("%Y%m%d-%H%M%S", now) + ".mp4"
    self._current_file = self.out_dir / filename
    self._file_start_time = time.monotonic()

    # 切片前做循环清理
    if self.on_new_file:  # 回调
        self.on_new_file(self.out_dir)

    # ... 启动 ffmpeg 进程
```

在 `recorder.py` 里传回调：

```python
def _on_new_file(self, out_dir: Path):
    max_hours = float(self.params.get("ScreenRecordMaxHours") or 8)
    self._storage.cleanup_old_files(max_hours)

self._encoder.on_new_file = self._on_new_file
```

#### 4.3.3 与 recorder 的集成

在 `recorder.py` 里每次切片前调用 `resolve()`：

```python
# recorder.py 中
self._storage = StorageLocation(default_dir, use_udisk=params.get_bool("ScreenRecordUdisk"))

# 循环里，切片前重新探测
while not self._stop_event.is_set():
    if self._need_slice:
        new_dir = self._storage.resolve()
        if self._storage.is_using_udisk:
            cloudlog.info(f"ScreenRecord: switching to USB {new_dir}")
        else:
            cloudlog.info(f"ScreenRecord: using internal {new_dir}")
        self._encoder.change_out_dir(new_dir)
        self._rotate_new_file()
```

#### 4.3.4 U 盘拔出时的处理

- 切片前 `resolve()` 重新探测，如果 U 盘不见了就自动切到 eMMC
- 正在写 U 盘时拔出：ffmpeg 写 pipe 报 BrokenPipeError，writer 线程捕获 → 关闭当前进程 → 下次 resolve 会选 eMMC → 开新文件继续
- **最坏情况**：损失切片周期内（最多 3 分钟）的数据

#### 4.3.5 首次启动时的处理

如果用户第一次开机就有 U 盘，但 U 盘没格式化或不支持，回退到 eMMC。UI 里显示"未检测到 U 盘"。

#### 4.3.6 U 盘兼容性说明

- **文件系统**：FAT32 / exFAT / ext4 都可以（Linux 内核都有驱动）
- **推荐**：FAT32 或 exFAT（Windows/macOS 通用）
- **容量**：≥ 2 GB 剩余空间
- **性能**：USB 2.0 或 USB 3.0 U 盘都行，720p@1Mbps 码率写压力极低（~200 KB/s）

---

### 4.4 `encoder_ffmpeg.py` — FFmpeg 子进程封装

```python
"""用 ffmpeg 子进程做编码（软编兜底）"""

import subprocess
import threading
import time
import queue
from pathlib import Path


class FfmpegEncoder:
    def __init__(self, out_dir: Path, width: int, height: int,
                 fps: int, bitrate: str, slice_sec: int):
        self.out_dir = out_dir
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate = bitrate
        self.slice_sec = slice_sec
        self.proc: subprocess.Popen | None = None
        self._queue = queue.Queue(maxsize=30)
        self._writer_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._current_file: Path | None = None
        self._file_start_time = 0
        self._frame_count = 0

    def start(self):
        self._rotate_new_file()
        self._start_writer_thread()

    def push_frame(self, frame: bytes):
        """非阻塞入队，队列满则丢帧"""
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            pass  # 丢帧，UI 帧率不受影响

    def stop(self):
        self._stop_event.set()
        self._queue.put(None)  # sentinel
        if self._writer_thread:
            self._writer_thread.join(timeout=5)
        self._close_proc()

    def is_encoding(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _start_writer_thread(self):
        self._writer_thread = threading.Thread(
            target=self._writer_loop, daemon=True, name="ScreenRecWriter")
        self._writer_thread.start()

    def _writer_loop(self):
        while True:
            try:
                data = self._queue.get(timeout=1.0)
            except queue.Empty:
                if self._stop_event.is_set():
                    return
                continue
            if data is None:
                return

            # 检查是否需要切片
            if time.monotonic() - self._file_start_time >= self.slice_sec:
                self._rotate_new_file()

            try:
                self.proc.stdin.write(data)
            except (BrokenPipeError, OSError):
                return

    def _rotate_new_file(self):
        self._close_proc()
        now = time.localtime()
        filename = time.strftime("%Y%m%d-%H%M%S", now) + ".mp4"
        self._current_file = self.out_dir / filename
        self._file_start_time = time.monotonic()

        args = [
            "ffmpeg", "-v", "warning", "-nostats",
            "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "pipe:0",
            "-vf", "vflip,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-crf", "28",
            "-x264-params",
                f"keyint={2*self.fps}:scenecut=0:bframes=0",
            "-g", str(2 * self.fps),
            "-y", "-f", "mp4",
            str(self._current_file),
        ]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE)

    def _close_proc(self):
        if self.proc is None:
            return
        try:
            self.proc.stdin.flush()
            self.proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
```

**关键设计**：
- **独立子进程**，不占 UI 主进程的 GIL
- **异步 writer 线程**，UI 主线程 `put_nowait()` 非阻塞
- **队列深度 30**，满则丢帧（录屏可以容忍丢帧）
- **切片**在 writer 线程里判断，切文件时 flush 旧进程再开新的
- **preset ultrafast** + `bframes=0`：编码延迟最小，CPU 占用最低

### 4.5 `encoder_omx.py` — OMX 硬编（可选，优先）

**移植自** `carrotpilot_c3_github/selfdrive/ui/qt/screenrecorder/omx_encoder.cc`（847 行）。

**做法**：
1. 把 `omx_encoder.cc/h` 拷进 `system/ui/screenrecorder/omx_encoder/`
2. 剥掉 Qt 依赖（本来就没有）
3. 编译为 `.so`，用 `ctypes` 导出 C 接口

```c
// omx_encoder_exports.c
extern "C" {
  int omx_init(const char* path, int width, int height, int fps,
               uint32_t bitrate, bool h265, int slice_sec);
  int omx_push_frame(const uint8_t* rgba, int w, int h, uint64_t ts_ns);
  void omx_stop();
  void omx_cleanup();
  int omx_is_encoding();
}
```

Python 侧：

```python
class OmxEncoder:
    def __init__(self, ...):
        self._lib = ctypes.CDLL("./libomx_encoder.so")
        # ... 设置 argtypes/restypes

    def start(self): ...
    def push_frame(self, frame: bytes): ...
    def stop(self): ...
```

**如果找不到 OMX HAL 就不编译这个**，跳过，直接走 ffmpeg 路径。

### 4.6 `recorder.py` — 主控逻辑

```python
"""屏幕录制主控"""

import os
import shutil
import threading
import time
from pathlib import Path

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import HARDWARE

from .encoder_detect import detect_encoder
from .encoder_ffmpeg import FfmpegEncoder
from .frame_source import FrameSource

RES_MAP = {"720p": (1280, 720), "1080p": (1920, 1080)}
BITRATE_MAP = {"500k": 500_000, "1M": 1_000_000, "2M": 2_000_000}


class ScreenRecorder:
    def __init__(self):
        self.params = Params()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_time = 0
        self._encoder = None
        self._source: FrameSource | None = None

    @property
    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def elapsed(self) -> int:
        return int(time.monotonic() - self._start_time) if self.is_recording else 0

    def start(self):
        with self._lock:
            if self.is_recording:
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, daemon=True, name="ScreenRec")
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def toggle(self):
        if self.is_recording:
            self.stop()
        else:
            self.start()

    def _run(self):
        try:
            # 1. 读配置
            path_str = self.params.get("ScreenRecordPath") or "/data/media/0/screenrecord"
            out_dir = Path(path_str)
            out_dir.mkdir(parents=True, exist_ok=True)

            # 2. 磁盘空间检查
            if not self._check_disk(out_dir, min_gb=2.0):
                cloudlog.error("ScreenRecord: insufficient disk space")
                self.params.put_bool("ScreenRecord", False)
                return

            # 3. 选编码器
            backend = detect_encoder()
            if backend == "none":
                cloudlog.error("ScreenRecord: no encoder available")
                self.params.put_bool("ScreenRecord", False)
                return

            # 4. 计算分辨率、帧率
            res = self.params.get("ScreenRecordRes") or "720p"
            bw, bh = RES_MAP.get(res, (1280, 720))
            fps = int(self.params.get("ScreenRecordFps") or 20)
            slice_sec = int(self.params.get("ScreenRecordSlice") or 600)
            bitrate = BITRATE_MAP[self.params.get("ScreenRecordBitrate") or "1M"]

            cloudlog.info(
                f"ScreenRecord start: backend={backend} res={bw}x{bh} "
                f"fps={fps} slice={slice_sec}s bitrate={bitrate}")

            # 5. 启动编码器
            self._encoder = FfmpegEncoder(out_dir, bw, bh, fps,
                                          f"{bitrate}", slice_sec)
            self._encoder.start()

            # 6. 帧采集
            self._source = FrameSource(bw, bh)
            self._start_time = time.monotonic()
            self.params.put_bool("ScreenRecord", True)
            frame_interval = 1.0 / fps
            last_t = 0.0

            while not self._stop_event.is_set():
                t = time.monotonic()
                if t - last_t < frame_interval:
                    time.sleep(0.005)
                    continue
                last_t = t

                frame = self._source.grab()
                if frame is None:
                    continue

                self._encoder.push_frame(frame.tobytes())

            # 7. 收尾
            self._encoder.stop()
        except Exception as e:
            cloudlog.exception(f"ScreenRecord error: {e}")
            self.params.put_bool("ScreenRecord", False)

    def _check_disk(self, path: Path, min_gb: float) -> bool:
        try:
            usage = shutil.disk_usage(path)
            return usage.free >= min_gb * 1024**3
        except OSError:
            return True  # 检查失败就假设 OK


_recorder = ScreenRecorder()


# 对外 API
def start(): _recorder.start()
def stop(): _recorder.stop()
def toggle(): _recorder.toggle()
def is_recording() -> bool: return _recorder.is_recording()
def get_elapsed() -> int: return _recorder.elapsed
```

### 4.7 offroad 自动停止

在 `recorder.py` 里加一个监控：

```python
def _monitor_offroad(self):
    """熄火 5 秒后自动停"""
    from openpilot.selfdrive.ui.ui_state import ui_state
    offroad_start = None
    while not self._stop_event.is_set():
        if ui_state.sm.alive("carState"):
            if ui_state.sm["carState"].standStill and not ui_state.sm["carState"].enabled:
                if offroad_start is None:
                    offroad_start = time.monotonic()
                elif time.monotonic() - offroad_start > 5.0:
                    self.stop()
                    return
            else:
                offroad_start = None
        time.sleep(1)
```

---

## 五、UI 层

### 5.1 `record_button.py` — 主屏按钮

**行为**：
- **空闲状态**：小灰圆（直径 60px），右下角固定位置
- **双击**（100ms 内两次点击）：**启动录制**
- **录制中**：红色圆（直径 100px），显示录制时长，2Hz 闪烁
- **录制中双击**：**停止录制**
- **录制中单击**：无反应（避免误触）

**参考**：`selfdrive/ui/onroad/exp_button.py`

```python
# selfdrive/ui/onroad/record_button.py
import time
import pyray as rl
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.application import FontWeight


class RecordButton(Widget):
    """
    主屏按钮
    - 空闲：60x60 小圆点
    - 录制：100x100 大圆 + 时长 + 闪烁
    - 触发：双击 toggle
    """
    DOUBLE_CLICK_MS = 300
    IDLE_SIZE = 60
    ACTIVE_SIZE = 100

    def __init__(self):
        super().__init__()
        self._rect = rl.Rectangle(0, 0, 60, 60)
        self._last_click_time = 0.0
        self._blink = True

    def set_rect(self, rect: rl.Rectangle):
        self._rect = rect

    def _handle_mouse_release(self, _):
        # 双击检测
        now = time.monotonic()
        if now - self._last_click_time < self.DOUBLE_CLICK_MS / 1000:
            from openpilot.system.ui.screenrecorder import toggle
            toggle()
            self._last_click_time = 0.0  # 避免第三次算双击
        else:
            self._last_click_time = now

    def _render(self, rect: rl.Rectangle):
        from openpilot.system.ui.screenrecorder import is_recording, get_elapsed

        rec = is_recording()
        now = time.monotonic()

        if rec:
            self._blink = (now * 2) % 2 < 1
            size = self.ACTIVE_SIZE
            alpha = 220 if self._blink else 100
            color = rl.Color(255, 30, 30, alpha)
            center = rl.Vector2(
                rect.x + rect.width / 2,
                rect.y + rect.height / 2
            )
            # 外圈黑底
            rl.draw_circle(
                center.x, center.y, size / 2,
                rl.Color(0, 0, 0, 180))
            # 中间红圆
            rl.draw_circle(
                center.x, center.y, size / 2 - 12,
                color)
            # 时长文字
            elapsed = get_elapsed()
            txt = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
            font = gui_app.font(FontWeight.BOLD)
            tw = rl.measure_text_ex(font, txt, 32).x
            rl.draw_text_ex(font, txt,
                rl.Vector2(center.x - tw / 2, center.y - 16),
                32, 0, rl.WHITE)
        else:
            size = self.IDLE_SIZE
            center = rl.Vector2(
                rect.x + rect.width / 2,
                rect.y + rect.height / 2
            )
            rl.draw_circle(
                center.x, center.y, size / 2 - 6,
                rl.Color(180, 180, 180, 180))
            # 中心一个小点表示可双击
            rl.draw_circle(
                center.x, center.y, 6,
                rl.Color(255, 255, 255, 200))
```

### 5.2 挂载到 `cameraview.py`

在 `selfdrive/ui/onroad/cameraview.py` 中：

```python
from openpilot.selfdrive.ui.onroad.record_button import RecordButton

class Cameraview(...):
    def __init__(...):
        ...
        self.record_btn = RecordButton()
        # 放在右下角，避开实验按钮、驾驶员监控按钮
        self.record_btn.set_rect(rl.Rectangle(
            self.width - 140,
            self.height - 140,
            140, 140
        ))
        # 加入 render 循环
        self._widgets.append(self.record_btn)
```

**位置**：C3X（2160x1080）主屏右下角，实验按钮在右上角，驾驶员监控在右上角，中间是道路视图，左下角是 speed + 导航信息。右下角相对空，可以放。

### 5.3 录制中的 UI 变化（除按钮外）

用户要求"录制的话 UI 要变动"，除了按钮本身变化外，还可以：

1. **顶部状态条**：显示"● REC 03:12"（红色脉冲）
2. **顶部边框红闪**：屏幕最上方 4px 高度红色横条，2Hz 闪烁
3. **HUD 图标**：小图标叠加在速度数字旁边

推荐 **顶部状态条** + **按钮本身**：

```python
# 在 cameraview 或 ui.py 的顶层添加
def _draw_recording_overlay(self):
    if not is_recording():
        return
    # 顶部红条
    alpha = 200 if (time.monotonic() * 2) % 2 < 1 else 80
    rl.draw_rectangle(0, 0, self.width, 6,
                      rl.Color(255, 0, 0, alpha))
    # 顶部左侧时间戳
    txt = f"● REC {get_elapsed()//60:02d}:{get_elapsed()%60:02d}"
    font = gui_app.font(FontWeight.BOLD)
    rl.draw_text_ex(font, txt, rl.Vector2(20, 12), 28, 0,
                    rl.Color(255, 255, 255, 255))
```

### 5.4 `screenrecorder.py` — 设置页

```python
# selfdrive/ui/sunnypilot/layouts/settings/screenrecorder.py

class ScreenRecorderSettings(SubLayout):
    """设置 → 屏幕录制"""

    def __init__(self, params):
        super().__init__()
        menu = ActionMenu(title="屏幕录制", params=ui_state.params)

        # 分辨率
        menu.add_menu(
            icon="resize", title="分辨率",
            choices=["720p", "1080p"],
            param="ScreenRecordRes",
            default="720p"
        )

        # 帧率
        menu.add_menu(
            icon="clock", title="帧率",
            choices=["10", "15", "20", "30"],
            param="ScreenRecordFps",
            default="20"
        )

        # 切片时长（分钟）
        menu.add_menu(
            icon="slice", title="切片时长",
            choices=["60", "180", "300", "600"],  # 1/3/5/10 分钟
            param="ScreenRecordSlice",
            default="180"
        )

        # 码率
        menu.add_menu(
            icon="performance", title="码率",
            choices=["500k", "1M", "2M"],
            param="ScreenRecordBitrate",
            default="1M"
        )

        # 编码器
        menu.add_menu(
            icon="chip", title="编码器",
            choices=["auto", "omx", "ffmpeg"],
            param="ScreenRecorderEncoder",
            default="auto"
        )

        # 最大总时长（循环录制）
        menu.add_menu(
            icon="loop", title="最大总时长",
            choices=["2", "4", "8", "16", "24", "0"],  # 0 = 不限制
            param="ScreenRecordMaxHours",
            default="8"
        )

        # U 盘开关
        menu.add_toggle(
            icon="usb", title="使用 U 盘",
            param="ScreenRecordUdisk",
            default=True
        )

        # 录制目录
        menu.add_label(
            icon="folder", title="录制目录",
            value_fn=lambda: ui_state.params.get("ScreenRecordPath")
                or "/data/media/0/screenrecord"
        )

        # 当前写入位置（只读）
        menu.add_label(
            icon="info", title="当前写入",
            value_fn=self._current_location_display
        )

        # 手动清理按钮
        menu.add_button(
            icon="trash", title="清空录制",
            on_click=self._clear_all
        )

    def _current_location_display(self):
        from openpilot.system.ui.screenrecorder import get_current_dir
        d = get_current_dir()
        if d is None:
            return "未录制"
        ds = str(d)
        if "/media" in ds or "/mnt/usb" in ds or "/run/media" in ds:
            return f"U 盘: {ds}"
        return f"内部: {ds}"

    def _clear_all(self):
        from pathlib import Path
        import shutil
        path = Path(ui_state.params.get("ScreenRecordPath")
                    or "/data/media/0/screenrecord")
        if path.exists():
            shutil.rmtree(path)
            cloudlog.warning(f"ScreenRecord: cleared {path}")
```

**挂载到设置菜单**：`selfdrive/ui/sunnypilot/layouts/settings/__init__.py` 里注册。

### 5.5 `params_keys.h` 修改

在 `common/params_keys.h` 的 `ScreenRecord` 附近加：

 ```c
{"ScreenRecord",      {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL}},  // 已存在
{"ScreenRecordPath",  {NO_CLEAR}},
{"ScreenRecordRes",   {NO_CLEAR}},
{"ScreenRecordFps",   {NO_CLEAR}},
{"ScreenRecordSlice", {NO_CLEAR}},
{"ScreenRecordBitrate",{NO_CLEAR}},
{"ScreenRecorderEncoder", {NO_CLEAR}},
{"ScreenRecordUdisk", {NO_CLEAR}},
{"ScreenRecordMaxHours", {NO_CLEAR}},
{"dp_show_date_time",  {NO_CLEAR}},   // UI 顶部时间显示开关（沿用 nanapilot 参数名）
{"Timezone",           {NO_CLEAR}},
{"LastValidTime",      {NO_CLEAR}},
{"TimeAutoSync",       {NO_CLEAR}},
{"TimeSyncNtpServers", {NO_CLEAR}},
{"TimeMinValidYear",   {NO_CLEAR}},
```

---

## 六、最低开销的关键优化

| 层次 | 优化点 | 收益 |
|---|---|---|
| 采集 | `image_resize` 在 GPU 完成，避免 CPU 缩放 | -30% CPU |
| 采集 | 分辨率降一半像素（1080→720） | 数据量 -55% |
| 采集 | `push_frame` 用 `put_nowait` + 满队列丢帧 | UI 帧率不损失 |
| 采集 | 采集频率严格卡 UI FPS，不超额 | 稳定 |
| 编码 | 独立子进程，不占 UI GIL | UI 主循环不被拖 |
| 编码 | libx264 preset=ultrafast | -40% CPU vs veryfast |
| 编码 | bframes=0，GOP=2*FPS | 延迟最小，切片友好 |
| 编码 | CRF 28（不是 23） | 文件体积 -40% |
| 切片 | 每 **3 分钟**新文件 | 崩溃丢数据 < 3min |
| 切片 | writer 线程里判断，不打断采集 | 无缝切换 |
| 生命周期 | offroad 5 秒自动停 | 熄火不耗电 |
| 存储保护 | 启动前检查 2GB 剩余 | 不写满 eMMC |
| 存储保护 | 循环录制，超过 max_hours 删旧文件 | 磁盘永不写满 |
| 存储切换 | 切片前探测 U 盘，拔出自动切 eMMC | 用户无感 |

**估算占用**（1280x720 20fps CRF28 ultrafast libx264）：
- CPU：~25%（1 个核心）
- 内存：~20 MB
- 磁盘：~50 MB/小时
- 温度：< 5°C 增量

如果 OMX 可用：
- CPU：< 3%
- 内存：~15 MB
- 磁盘：~30 MB/小时（HEVC 比 H264 小 30%）
- 温度：< 2°C 增量

---

## 七、时间与时区（TimeSync + Timezone）

**目标**：录制启动前确保系统时间是有效值（≥ 2024 年），文件名里的时间戳可信。UI 上始终可见当前时间。

### 7.1 当前项目已有的时间基础（不能直接搬 nanapilot）

当前 openpilot_nanasemai 已经具备的时间基础设施：

| 组件 | 位置 | 作用 |
|---|---|---|
| `system/timed.py` | 已存在 | GPS 时间同步 + 发布 `clocks` 消息 |
| `system/qcomgpsd/qcomgpsd.py` | 已存在 | 高通 GPS 芯片驱动，输出 `gpsLocationExternal` |
| `system/ubloxd/ubloxd.py` | 已存在 | u-blox GPS 驱动，同样输出 |
| `system/hardware/tici/hardware.py` | 已存在 | GPS 引脚配置 |
| `process_config.py:142,160-165` | 已存在 | `timed` / `qcomgpsd` / `ubloxd` 都在跑 |
| `gpsLocationExternal.unixTimestampMillis` | 消息已有 | GPS 时间戳字段 |
| `gpsLocationExternal.hasFix` | 消息已有 | GPS 定位标志 |
| systemd-timesyncd | agnos 已装 | 系统级 NTP |

**关键差异（相比 nanapilot）**：

| 项 | nanapilot | 本项目 | 处理方式 |
|---|---|---|---|
| GPS 时间同步 | `timed.py`（简版） | `timed.py`（已有，功能类似） | ✅ 直接复用，不重写 |
| NTP 兜底 | `set_time.py` 4 服务器 | 无 | ⚠️ 新增 NTP 兜底逻辑（作为 `timed.py` 补充） |
| Panda RTC 兜底 | 有 | 无 | ❌ 不加（本项目 panda 是 SPI 内部总线，RTC 访问麻烦） |
| LastValidTime 缓存 | 有 | 无 | ✅ 新增（简单，有用） |
| 时区服务 | `timezoned.py`（自动 GPS/IP） | 无 | ✅ 新增（简化版，手动为主，GPS 自动为辅） |
| UI 时间显示 | 无 | 无 | ✅ 新增（本项目特色） |

**设计原则**：
1. **不删不改** `system/timed.py`，只**新增**辅助模块
2. NTP 同步作为**开机时的一次性校验**，不循环
3. 时区以**手动选择**为主（`Asia/Shanghai` 默认），GPS 自动检测作为 offroad 时的静默更新
4. Panda RTC 兜底路径**不实现**（本项目 panda 是内部 SPI，接口不通用，复杂度高、收益低）

### 7.2 新增文件

```
openpilot_nanasemai/
├── system/
│   ├── timezoned.py                    # 新增：时区服务
│   ├── time_sync.py                    # 新增：NTP 兜底同步（补充 timed.py）
│   └── timed.py                        # 已存在，不改
│
├── selfdrive/
│   └── ui/
│       ├── onroad/
│       │   └── time_display.py         # 新增：顶部中央时间/日期 widget
│       └── sunnypilot/layouts/settings/
│           └── time_settings.py        # 新增：时区 + 时间同步设置页
│
├── common/
│   └── params_keys.h                   # 新增 Timezone / LastValidTime / TimeAutoSync 等
│
├── system/manager/
│   └── process_config.py               # 修改：注册 timezoned + time_sync
```

### 7.3 `system/time_sync.py` — NTP 兜底同步

**不重写 timed.py，只补一层 NTP**。开机时如果系统时间无效，且 GPS 一时给不出（比如车在车库），用 NTP 快速同步。

```python
"""
开机时校验系统时间，无效时用 NTP 快速同步。
补充 timed.py（GPS 时间同步需要 GPS 定位才有），不作为常驻服务。

用法：
  开机时由 manager 拉起一次（PythonProcess），
  校验完成后自己退出。
"""

import datetime
import os
import subprocess
import time
import requests
from openpilot.common.params import Params


MIN_DATE_UTC = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)


def system_time_valid() -> bool:
    return datetime.datetime.now(datetime.timezone.utc) >= MIN_DATE_UTC


def sync_time_from_ntp(servers: list[str], timeout: int = 3) -> bool:
    """
    用 HTTP Date 头做 NTP 兜底（比真的 NTP 协议简单，且国内 NTP 服务器很多
    其实不开放 UDP 123 端口，只支持 HTTP）。
    
    返回 True 表示同步成功。
    """
    for server in servers:
        try:
            url = f"https://{server}"
            r = requests.get(url, timeout=timeout, verify=False)
            if r.ok and 'date' in r.headers:
                # RFC 7231 date 格式
                dt = datetime.datetime.strptime(
                    r.headers['date'],
                    '%a, %d %b %Y %H:%M:%S %Z'
                ).replace(tzinfo=datetime.timezone.utc)
                if dt < MIN_DATE_UTC:
                    continue
                # 设置系统时间
                utc_str = dt.astimezone(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                subprocess.run(
                    f"TZ=UTC date -s '{utc_str}'",
                    shell=True, check=True
                )
                return True
        except Exception:
            continue
    return False


def main():
    params = Params()
    
    # 系统时间已有效，直接退出
    if system_time_valid():
        return
    
    # 检查是否允许自动同步
    if not params.get_bool("TimeAutoSync", default=True):
        return
    
    # 服务器列表
    servers_str = params.get("TimeSyncNtpServers") or \
        "ntp.aliyun.com,ntp.tencent.com,cn.ntp.org.cn,ntp.ubuntu.com"
    servers = [s.strip() for s in servers_str.split(",") if s.strip()]
    
    # 尝试同步
    if sync_time_from_ntp(servers):
        # 保存有效时间
        now_ts = int(time.time())
        params.put("LastValidTime", str(now_ts))
        return
    
    # 全部失败，静默退出，等 timed.py 的 GPS 路径
```

**关键设计**：
- **一次性运行**，不循环（GPS 时间由 `timed.py` 常驻同步）
- **不做 Panda RTC** 兜底（本项目 panda 是内部 SPI，访问复杂）
- **不做 IP 地理定位**（网络开销大，且 GPS 已经有了）
- **HTTP Date 头**代替 NTP 协议（简单，兼容国内服务器）
- **失败静默退出**，交给 GPS 路径

### 7.4 `system/timezoned.py` — 时区服务

**参考 nanapilot 但简化**：

```python
"""
时区服务。
- 如果 params 里有 Timezone，直接使用
- 否则用 LastGPSPosition 反查时区
- 每 10 分钟检查一次
"""

import json
import os
import subprocess
import time
from openpilot.common.params import Params
from openpilot.system.hardware import AGNOS
from openpilot.common.swaglog import cloudlog


def _set_timezone_iptables(timezone: str) -> bool:
    """用 iptables 的 TIME target 测试"""
    return False  # 不需要


def set_timezone(timezone: str) -> bool:
    if not timezone:
        return False
    cloudlog.debug(f"Setting timezone to {timezone}")
    try:
        if AGNOS:
            # agnos 是 Ubuntu 系统，用标准 zoneinfo
            tzpath = f"/usr/share/zoneinfo/{timezone}"
            subprocess.check_call(
                f'sudo ln -snf {tzpath} /etc/timezone.tmp && '
                f'sudo mv /etc/timezone.tmp /etc/localtime',
                shell=True
            )
            subprocess.check_call(
                f'sudo echo "{timezone}" > /etc/timezone',
                shell=True
            )
        else:
            subprocess.check_call(
                f'timedatectl set-timezone {timezone}',
                shell=True
            )
        return True
    except subprocess.CalledProcessError:
        cloudlog.exception(f"Failed to set timezone to {timezone}")
        return False


def get_timezone_from_gps(lat: float, lng: float) -> str | None:
    """根据 GPS 坐标查时区"""
    try:
        # 尝试用 timezonefinder
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        return tf.timezone_at(lng=lng, lat=lat)
    except ImportError:
        return None
    except Exception:
        return None


def main():
    params = Params()
    
    # 缓存有效时区列表
    try:
        valid_timezones = set(
            subprocess.check_output(
                'timedatectl list-timezones', shell=True, encoding='utf8'
            ).strip().split('\n')
        )
    except Exception:
        valid_timezones = set()
    
    while True:
        time.sleep(600)  # 10 分钟检查一次
        
        # 优先用手动设置的
        timezone = params.get("Timezone", encoding='utf8')
        if timezone:
            if not valid_timezones or timezone in valid_timezones:
                set_timezone(timezone)
            continue
        
        # 尝试 GPS
        location_str = params.get("LastGPSPosition", encoding='utf8')
        if location_str:
            try:
                loc = json.loads(location_str)
                tz = get_timezone_from_gps(loc['latitude'], loc['longitude'])
                if tz and (not valid_timezones or tz in valid_timezones):
                    set_timezone(tz)
            except Exception:
                pass


if __name__ == "__main__":
    main()
```

**与 nanapilot 的差异**：
1. **不用 IP 地理定位**（简化，且国内 IP 定位经常不准）
2. **时区列表**用 `timedatectl list-timezones` 而不是硬编码
3. **AGNOS 分支**：agnos 是 Ubuntu，`/etc/timezone` 就是标准路径，不需要 nanapilot 里那个 `/data/etc/` 的奇怪路径
4. **timezonefinder** 依赖：需要加到 `pyproject.toml`

### 7.5 修改 `system/manager/process_config.py`

在 `process_config.py` 里注册新进程：

```python
# 添加（参考 nanapilot 的位置）
PythonProcess(
  "timezoned", "system.timezoned",
  always_run, enabled=not PC
),
PythonProcess(
  "time_sync", "system.time_sync",
  first_run_only,  # 只跑一次，跑完就退出
  enabled=not PC
),
```

**`first_run_only` 语义**：只在 manager 启动时跑一次，跑完 exit，不常驻。

如果 `first_run_only` 不存在的语义，用 `enabled=(not PC) and TIME_NEWS` 或者干脆写成一次性脚本，由 `timed.py` 启动时调用。

**更简单的做法**：把 NTP 同步集成到 `timed.py` 里，作为开机检查：

```python
# system/timed.py 里 main() 开头加
def ensure_time_valid():
    if not system_time_valid():
        from openpilot.system.time_sync import sync_time_from_ntp
        params = Params()
        servers_str = params.get("TimeSyncNtpServers") or "ntp.aliyun.com,ntp.tencent.com"
        servers = [s.strip() for s in servers_str.split(",")]
        if sync_time_from_ntp(servers):
            params.put("LastValidTime", str(int(time.time())))


def main():
    ensure_time_valid()  # ← 加这一行
    # ... 原有代码
```

**推荐用这个方案**，少一个常驻进程。

### 7.6 `selfdrive/ui/onroad/time_display.py` — 顶部时间/日期 widget

**参考 nanapilot**：`selfdrive/ui/qt/onroad.cc:542-560`。nanapilot 的完整实现：

```cpp
// nanapilot 的实现
if (show_date_time) {  // 从 params "dp_show_date_time" 读
  bool size_changed = (timeDisplayBuffer.size() != size());
  if (size_changed) {
    timeDisplayBuffer = QPixmap(size());
  }
  if (size_changed || frame_count % 300 == 0) {  // 5 秒重绘一次
    timeDisplayBuffer.fill(Qt::transparent);
    QPainter pTime(&timeDisplayBuffer);
    pTime.setFont(InterFont(35, QFont::DemiBold));
    QRect timeRect = pTime.fontMetrics().boundingRect("yyyy-MM-dd hh:mm:ss");
    timeRect.moveCenter({rect().center().x(), 25});  // y=25
    pTime.setPen(whiteColor(200));
    pTime.drawText(timeRect, Qt::AlignCenter,
      QDateTime::currentDateTime().toString("yyyy-MM-dd hh:mm:ss"));
  }
  p.drawPixmap(0, 0, timeDisplayBuffer);
}
```

**特点**：
- param 名：`dp_show_date_time`（0/1 开关）
- 位置：**顶部中央**，垂直偏移 y=25
- 格式：`yyyy-MM-dd hh:mm:ss`
- 字体：Inter DemiBold 35
- 颜色：白 200 alpha
- 缓存：**300 帧刷新**（用 QPixmap 缓存避免每帧重绘）

**raylib 移植版**（对齐 nanapilot，加"录制中高亮"扩展）：

```python
"""
顶部中央时间/日期显示。
参考 nanapilot selfdrive/ui/qt/onroad.cc:542-560 的实现。

- 默认关闭，通过 dp_show_date_time 参数开启
- 每 300 帧（约 5 秒）重绘一次，减少 UI 开销
- 录制中显示为红色闪烁
"""

import time
import pyray as rl
from openpilot.common.params import Params
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app, FontWeight

REFRESH_EVERY_N_FRAMES = 300  # 对齐 nanapilot


class TimeDisplay(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._last_refresh_frame = -1
    self._cached_text = ""
    self._cached_size = rl.Vector2(0, 0)

  def _render(self, rect: rl.Rectangle):
    # 开关检查（低频，每次渲染查一次没问题）
    if not self._params.get_bool("dp_show_date_time"):
      return

    # 300 帧才刷新一次缓存
    frame = gui_app.frame
    if frame == self._last_refresh_frame:
      self._draw_cached(rect)
      return

    # 计算新文本
    now = time.localtime()
    text = time.strftime("%Y-%m-%d %H:%M:%S", now)
    font = gui_app.font(FontWeight.SEMI_BOLD)  # 对齐 nanapilot DemiBold

    # 记录缓存
    self._cached_text = text
    self._cached_size = rl.measure_text_ex(font, text, 35)
    self._last_refresh_frame = frame
    self._draw_cached(rect)

  def _draw_cached(self, rect: rl.Rectangle):
    if not self._cached_text:
      return
    font = gui_app.font(FontWeight.SEMI_BOLD)

    # 录制中状态
    from openpilot.system.ui.screenrecorder import is_recording
    recording = is_recording()

    # 颜色：对齐 nanapilot whiteColor(200)；录制中变红闪
    if recording:
      now = time.localtime()
      alpha = 220 if (now.tm_sec % 2) == 0 else 100
      color = rl.Color(255, 60, 60, alpha)
    else:
      color = rl.Color(255, 255, 255, 200)

    # 位置：顶部中央，垂直偏移 25（对齐 nanapilot y=25）
    text_w = self._cached_size.x
    text_h = self._cached_size.y
    x = rect.x + (rect.width - text_w) / 2
    y = 25  # 顶部留 25px

    rl.draw_text_ex(font, self._cached_text, rl.Vector2(x, y), 35, 0, color)
```

**对齐 nanapilot 的关键点**：

| 特性 | nanapilot（Qt） | 本项目（raylib） |
|---|---|---|
| Param 名 | `dp_show_date_time` | 沿用 `dp_show_date_time` |
| 位置 y | 25 | 25 |
| 字体 | Inter DemiBold 35 | Inter SemiBold 35 |
| 颜色 | 白 200 alpha | 白 200 alpha |
| 格式 | `yyyy-MM-dd hh:mm:ss` | `%Y-%m-%d %H:%M:%S`（等价） |
| 刷新频率 | 300 帧 | 300 帧（用 `gui_app.frame`） |
| 缓存 | QPixmap | 直接缓存文本+尺寸（raylib 无 QPixmap） |
| 录制高亮 | 无 | ✅ 新增（录制中红色闪烁） |

**挂载**：在 `selfdrive/ui/onroad/cameraview.py` 里加：

```python
from openpilot.selfdrive.ui.onroad.time_display import TimeDisplay

class Cameraview(...):
  def __init__(...):
    ...
    self.time_display = TimeDisplay()
    # 铺满屏幕宽度，widget 自己决定位置（顶部中央）
    self.time_display.set_rect(rl.Rectangle(0, 0, self.width, 60))
    self._widgets.append(self.time_display)
```

**设置开关**：在 `selfdrive/ui/sunnypilot/layouts/settings/device.py` 或独立设置页里加：

```python
menu.add_toggle(
  icon="clock",
  title="显示时间",
  subtitle="在UI界面上显示当前的日期和时间信息",
  param="dp_show_date_time",
  default=True
)
```

### 7.7 设置页 — `selfdrive/ui/sunnypilot/layouts/settings/time_settings.py`

**放在设置 → 系统** 下，或者做成一个独立菜单 **设置 → 时间与时区**。

```python
"""
时间与时区设置页
"""

import time
import datetime
import subprocess
from openpilot.selfdrive.ui.sunnypilot.layouts.settings import SubLayout
from openpilot.system.ui.ui_state import ui_state
from openpilot.common.params import Params


# 常用时区列表（简化，避免全列表 400+ 条）
COMMON_TIMEZONES = [
    "Asia/Shanghai",        # 中国
    "Asia/Hong_Kong",
    "Asia/Taipei",
    "Asia/Singapore",
    "Asia/Tokyo",           # 日本
    "Asia/Seoul",           # 韩国
    "Asia/Kolkata",         # 印度
    "Europe/London",        # 英国
    "Europe/Paris",         # 欧洲
    "America/New_York",     # 美国东部
    "America/Los_Angeles",  # 美国西部
    "UTC",
]


class TimeSettings(SubLayout):
    def __init__(self, params):
        super().__init__()
        self._params = Params()
        menu = ActionMenu(title="时间与时区", params=ui_state.params)

        # 当前时间（只读）
        menu.add_label(
            icon="clock", title="当前系统时间",
            value_fn=self._current_time_display
        )

        # 时区
        menu.add_menu(
            icon="globe", title="时区",
            choices=COMMON_TIMEZONES,
            param="Timezone",
            default="Asia/Shanghai"
        )

        # 自动同步开关
        menu.add_toggle(
            icon="sync", title="自动同步时间",
            param="TimeAutoSync",
            default=True
        )

        # 手动同步按钮
        menu.add_button(
            icon="refresh", title="立即同步时间",
            on_click=self._sync_now
        )

        # 上次有效时间
        menu.add_label(
            icon="info", title="上次有效时间",
            value_fn=self._last_valid_time_display
        )

        # 系统时区显示
        menu.add_label(
            icon="globe", title="系统当前时区",
            value_fn=self._system_timezone_display
        )

    def _current_time_display(self):
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _system_timezone_display(self):
        try:
            with open("/etc/timezone") as f:
                return f.read().strip()
        except OSError:
            return "unknown"

    def _last_valid_time_display(self):
        ts = self._params.get("LastValidTime")
        if ts:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))
        return "从未同步"

    def _sync_now(self):
        from openpilot.system.time_sync import sync_time_from_ntp, system_time_valid
        if system_time_valid():
            # 已有效，也强制同步一下
            servers = self._get_servers()
            sync_time_from_ntp(servers)
            self._params.put("LastValidTime", str(int(time.time())))
        else:
            servers = self._get_servers()
            if not sync_time_from_ntp(servers):
                # UI 上显示错误提示
                cloudlog.warning("手动同步时间失败")
            else:
                self._params.put("LastValidTime", str(int(time.time())))

    def _get_servers(self) -> list[str]:
        servers_str = self._params.get("TimeSyncNtpServers") or \
            "ntp.aliyun.com,ntp.tencent.com,cn.ntp.org.cn,ntp.ubuntu.com"
        return [s.strip() for s in servers_str.split(",") if s.strip()]
```

**关键 UI 交互**：
- 修改时区后**立即生效**（`timezoned.py` 会读到新值）
- "立即同步"按钮触发时**弹提示**显示成功/失败
- 当前系统时间每秒刷新

### 7.8 与录制模块的联动

在 `recorder.py` 的 `_run()` 里，**启动录制前**检查时间有效性：

```python
def _run(self):
    try:
        # 0. 检查系统时间有效性
        from openpilot.common.time_helpers import system_time_valid
        min_year = int(self.params.get("TimeMinValidYear") or 2024)
        now = datetime.datetime.now(datetime.timezone.utc)
        
        if now.year < min_year:
            # 尝试同步
            from openpilot.system.time_sync import sync_time_from_ntp
            servers = self._get_ntp_servers()
            if not sync_time_from_ntp(servers):
                cloudlog.error("ScreenRecord: system time invalid, refusing to start")
                self.params.put_bool("ScreenRecord", False)
                return  # 拒绝启动
        
        # 保存当前时间戳
        self.params.put("LastValidTime", str(int(time.time())))
        
        # 1. 读配置 ...（原有代码）
```

**拒绝启动的 UI 反馈**：
- 录制按钮双击后不激活
- 顶部弹出红色 toast："系统时间无效，请先到设置里同步时间"

### 7.9 时间戳在文件名中的应用

文件名格式已经用 `time.strftime("%Y%m%d-%H%M%S")`，自动使用系统时区（因为设置了 `/etc/localtime`）。

**验证**：
```bash
# 设置时区到上海
timedatectl set-timezone Asia/Shanghai
# 时间应该是
date  # 2024-11-15 14:30:00 CST

# 录制开始 → 文件名
# 20241115-143000.mp4
```

### 7.10 依赖添加

在 `pyproject.toml` 里加：

```toml
"timezonefinder >= 6.0",
"requests >= 2.31",   # 应该已经有了，用于 NTP HTTP 请求
```

`requests` 大概率已有。`timezonefinder` 需要新增。

### 7.11 与 nanapilot 的关键差异总结

| 特性 | nanapilot | 本项目方案 | 理由 |
|---|---|---|---|
| Panda RTC 兜底 | ✅ | ❌ | 本项目 panda 是内部 SPI，接口复杂，且 RTC 精度可能反而不准 |
| IP 地理定位时区 | ✅ | ❌ | 国内 IP 定位不准，且网络开销大；GPS 已经够用了 |
| LastValidTime 缓存 | ✅ | ✅ | 有价值，加上 |
| `timezoned.py` | 有 | ✅ 简化版 | 手动时区为主，GPS 自动为辅 |
| `set_time.py` 独立模块 | 有（常驻） | ❌ 合并到 timed.py | 少一个进程更简单 |
| NTP 服务器列表 | 4 个国内 | 5 个（含 ubuntu） | 增加可用性 |
| UI 时间显示 | 无 | ✅ 新增 | 项目特色，方便知道录制时间 |
| 手动同步按钮 | 无 | ✅ 新增 | 网络问题时可救急 |

---

## 八、实施阶段

### Phase 1：核心通路（0.5 天）

- 新建 `system/ui/screenrecorder/` 目录
- 写 `recorder.py`、`encoder_ffmpeg.py`、`frame_source.py`、`encoder_detect.py`
- 命令行测试：
  ```bash
  python3 -c "from openpilot.system.ui.screenrecorder import start, stop, is_recording; start(); import time; time.sleep(30); stop()"
  ```
- 验证：`/data/media/0/screenrecord/` 下有 mp4，可用 ffplay 播放

### Phase 2：主屏 UI 按钮（0.5 天）

- 写 `record_button.py`
- 挂载到 `cameraview.py`
- 实现双击、闪烁、时长显示
- 实现顶部红色状态条 overlay

### Phase 3：设置页 + params（0.5 天）

- 修改 `common/params_keys.h` 加 4 个 key
- 写 `screenrecorder.py` 设置页
- 挂载到 settings 主菜单
- 首次启动写默认值

### Phase 4：U 盘支持 + 循环录制（0.5 天）

- 写 `storage.py`，实现 U 盘探测 + eMMC 回退
- 实现 `cleanup_old_files(max_hours)` 循环删除
- 切片前调用 `resolve()` + `cleanup_old_files()`
- 设置页加"最大总时长"和"使用 U 盘"选项

### Phase 5：边界情况（0.5 天）

- offroad 5 秒自动停
- 磁盘空间检查
- 编码器运行时探测 + 优雅降级
- U 盘拔出时 ffmpeg 断管道处理

### Phase 6：时间 + 时区（0.5 天）

- 新增 `system/time_sync.py`（NTP 兜底同步，作为 timed.py 补充）
- 新增 `system/timezoned.py`（时区服务）
- 修改 `system/timed.py` 开机时调用 `ensure_time_valid()`
- 新增 `selfdrive/ui/onroad/time_display.py`（顶部时间/日期 widget，对齐 nanapilot）
- 新增 `selfdrive/ui/sunnypilot/layouts/settings/time_settings.py`（时区设置页）
- 挂载 `TimeDisplay` 到 `cameraview.py`
- 注册 `timezoned` 到 `process_config.py`
- 依赖添加 `timezonefinder`

### Phase 7（可选）：OMX 硬编（2-3 天）

- 移植 carrotpilot 的 `omx_encoder.cc`
- 编译为 `.so`，导出 C 接口
- 集成到 `encoder_omx.py`
- 需要在设备上验证 `libopenmaxil.so` 存在

**总工作量**：核心 2 天，含 OMX 5 天。

---

## 九、验证清单

### 功能验证
- [ ] 双击按钮启动录制，按钮变红+闪烁+显示时长
- [ ] 双击按钮停止录制，按钮恢复灰
- [ ] 顶部状态条同步显示
- [ ] offroad 5 秒自动停
- [ ] 切片：默认 3 分钟一个文件
- [ ] 磁盘不足时拒绝启动，UI 提示
- [ ] 插入 U 盘后启动录制 → 写入 U 盘
- [ ] 录制中拔出 U 盘 → 下个切片无缝切到 eMMC
- [ ] 循环录制：超过最大总时长后自动删最老文件

### 设置验证
- [ ] 修改分辨率（720p / 1080p）后重启录制生效
- [ ] 修改帧率（10/15/20/30）后重启录制生效
- [ ] 修改切片时长（60/180/300/600 秒）后重启录制生效
- [ ] 修改码率后重启录制生效
- [ ] 修改目录后写新位置
- [ ] 修改最大总时长（2/4/8/16/24h）后生效
- [ ] 关闭 U 盘开关后不再自动探测 U 盘

### 性能验证
- [ ] 录制中 UI FPS 不下降（用 SHOW_FPS=1 观察）
- [ ] 录制中 CPU 占用 < 30%（软编）
- [ ] 录制 30 分钟无崩溃
- [ ] 录制 30 分钟生成 10 个完整 mp4（3 分钟切片）
- [ ] mp4 用 ffplay / VLC 可正常播放

### U 盘验证
- [ ] 内核枚举出 `/dev/sda*`（`lsblk` 确认）
- [ ] 挂载点在候选列表里（`/media/0` 或 `/run/media/*`）
- [ ] FAT32 / exFAT / ext4 三种格式都可用
- [ ] 8 GB U 盘可容纳 8 小时（默认配置）
- [ ] 录制中 U 盘拔出：当前文件损坏，下个切片自动切 eMMC
- [ ] 录制中重新插入 U 盘：下个切片自动切回 U 盘

### 循环录制验证
- [ ] 最大总时长设为 2h，录 2h30m 后剩不到 2h 数据
- [ ] 最大总时长设为 0（不限制）：不删文件
- [ ] 切 U 盘/eMMC 后各自独立循环，互不影响
- [ ] 删除操作记录在 cloudlog 里（便于调试）

### 编码方案验证
- [ ] `ffmpeg` 命令存在 → 用 ffmpeg 后端
- [ ] `libopenmaxil.so` 存在且可用 → 用 omx 后端
- [ ] 强制 ffmpeg → 走 ffmpeg
- [ ] 强制 omx 但 omx 不可用 → 报错退出

### 时间与时区验证
- [ ] `dp_show_date_time=True` 时 UI 顶部中央显示时间/日期
- [ ] `dp_show_date_time=False` 时 UI 顶部不显示
- [ ] 时间格式为 `yyyy-MM-dd hh:mm:ss`（对齐 nanapilot）
- [ ] 300 帧才重绘一次（用 GUI 帧计数验证）
- [ ] 录制中时间变红闪烁
- [ ] 设置里改时区到 `Asia/Tokyo` → 系统时间跳 +1 小时
- [ ] 系统时间 < 2024 年时，启动录制前触发 NTP 同步
- [ ] NTP 全部失败时，拒绝启动录制，UI 提示
- [ ] NTP 同步成功后，`LastValidTime` 参数被更新
- [ ] 有 GPS 定位时，`timezoned` 自动更新时区
- [ ] 手动"立即同步"按钮工作
- [ ] 手动同步失败时 UI 提示

### 录制-时间联动验证
- [ ] 系统时间无效时双击录制按钮 → 按钮不激活 + 弹错误提示
- [ ] 系统时间有效 → 文件名时间戳与实际时间一致
- [ ] 切换时区后录制的新文件时间戳跟着变
- [ ] 录制中系统时间不失效（GPS 持续同步）

---

## 十、实现状态（截至 2026-09-10）

### 已完成（Phase 1-6，共 8 个 commit）

| Phase | Commit | 内容 |
|-------|--------|------|
| 1 | `48eadd6` | 核心管线：ffmpeg 编码器（libx264 ultrafast）、帧源（post-render 回调）、编码器探测、10 个 params |
| 2 | `86fbfa0` | UI 按钮：双击切换、红色闪烁、mm:ss 时长、顶部 REC overlay |
| 3 | `9f9a443` | 设置页：分辨率/帧率/切片/码率/编码器/最大时长/U盘 |
| 4 | `6f2b22b` | U 盘存储：USB 探测、eMMC 回退、mtime 循环清理、on_new_file 回调 |
| 5 | `eecce3a` | 边界情况：offroad 5s 自动停、低空间警告、USB 拔出恢复 |
| 6 | `155a5a6` | 时间显示：顶部中央时间/日期 widget、时区设置页、timezoned 服务 |
| 6b | `3cd9c07` | NTP 同步模块、TimeSyncNtpServers param、性能优化 |
| 7 | `78587b2` | OMX 骨架、时区选择器（11 个常用时区）、时区索引映射 |

### 已创建的文件（13 个新文件）

```
system/ui/screenrecorder/
├── __init__.py          # 公共 API: start/stop/toggle/is_recording
├── recorder.py          # 主控制器（生命周期、参数解析、offroad 监控）
├── encoder_ffmpeg.py    # ffmpeg 子进程封装（切片轮转、队列写入）
├── encoder_detect.py    # 编码器探测（OMX → ffmpeg → none）
├── encoder_omx.py       # OMX 硬件编码骨架（ctypes，未实现）
├── frame_source.py      # 帧源（post-render 回调，20fps 节流）
└── storage.py           # 存储管理（USB 探测、循环清理）

system/ui/onroad/
└── time_display.py      # 时间/日期显示 widget（300 帧刷新）

selfdrive/ui/onroad/
└── record_button.py     # 录制按钮 widget（双击切换、红色闪烁）

selfdrive/ui/sunnypilot/layouts/settings/
├── screenrecorder.py    # 屏幕录制设置页
└── time_settings.py     # 时间设置页（显示开关 + 时区选择）

system/
├── timezoned.py         # 时区服务（param 驱动，60s 轮询）
├── time_sync.py         # NTP 时间同步模块（ensure_time_valid）
└── timezone_list.py     # 时区列表（11 个常用时区，索引映射）
```

### 修改的文件（8 个）

```
common/params_keys.h                  # 13 个新 param key
selfdrive/ui/onroad/augmented_road_view.py  # 挂载按钮 + overlay + 时间显示
selfdrive/ui/sunnypilot/layouts/settings/settings.py  # 注册 SCREENRECORDER + TIME panel
system/manager/process_config.py      # 注册 timezoned 服务
system/timezoned.py                   # （新建后修改）使用 timezone_list
```

### 已验证

- ✅ ffmpeg 编码器：80 帧 → 3 个有效 MP4 切片（libx264 H.264）
- ✅ 切片轮转：2s 间隔，3 个切片，on_new_file 回调正确触发
- ✅ 循环清理：cleanup_old_files 正确删除超过 max_hours 的文件
- ✅ 时区列表：tz_name(0)="Asia/Shanghai", tz_name(10)="UTC", tz_name(99)="Asia/Shanghai"（兜底）
- ✅ 时间校验：is_time_valid() 正确判断系统时间
- ✅ OMX 骨架：is_available() 正确探测（开发机无 libopenmaxil.so → False）
- ✅ ruff lint：所有新代码通过检查
- ✅ 语法检查：所有 .py 文件通过 ast.parse

### 待完成

- [ ] Phase 7：OMX 硬件编码器完整实现（需移植 carrotpilot omx_encoder.cc，约 847 行）
- [ ] 设备验证：C3 实车测试（USB 挂载、OMX 探测、offroad 自动停）
- [ ] 验证清单中的全部测试项（需实车环境）

### 工作量统计

- 核心代码：~1200 行 Python
- 文档计划：2040 行 Markdown
- 验证测试：encoder + storage + timezone + time_sync 集成测试通过
- 预估实车验证时间：0.5 天
- OMX 完整实现（可选）：2-3 天

---

## 十一、风险与注意事项

1. **`libopenmaxil.so` 可能不存在**
   - agnos userspace 是 Ubuntu 系，不是 Android，可能没装 Qualcomm OMX HAL
   - **默认走 ffmpeg 兜底**，OMX 是"锦上添花"

2. **`gui_app._render_texture` 可能在 `RECORD=1` 时才会创建**
   - 需要改 `application.py:315`：`needs_render_texture = self._scale != 1.0 or BURN_IN_MODE or RECORD or ENABLE_RECORDING`
   - 或者在 `ScreenRecorder.start()` 时动态加载

3. **录屏帧率固定 20fps**
   - C3X UI 也是 20fps，正好对齐
   - C3 UI 是 60fps，录屏比 UI 慢，会看到轻微掉帧
   - 好处：CPU 压力天然小，不需要动态适配

4. **ffmpeg 子进程退出后文件可能不完整**
   - 崩溃时最后几个关键帧之间数据可能损坏
   - MP4 的 `moov` atom 需要正常关闭进程才会写入
   - 所以 `_close_proc` 里要 flush + close stdin + wait

5. **参数改动不即时生效**
   - 分辨率/帧率/码率改动后必须重启录制才生效
   - UI 上明确提示"重启录制后生效"

6. **双击检测的边界**
   - 双击间隔 300ms
   - 太短（< 100ms）可能被识别为抖动
   - 太长（> 500ms）用户会以为没响应
   - 300ms 是折中值

7. **系统时间可能长期无效**
   - 车在车库、没 GPS、没网络时，NTP 也连不上
   - 此时 `LastValidTime` 是唯一救命稻草
   - **不要**在时间无效时强制启动录制（文件名时间戳会错）
   - UI 要清晰提示"时间无效，请到设置里手动同步"

8. **时区变更不即时生效**
   - `timezoned.py` 每 10 分钟检查一次
   - 用户改时区后最长可能等 10 分钟才生效
   - 解决：改时区后立刻 `timezoned` 主动调一次，或者干脆在设置里改完立即调 `set_timezone()`

9. **timezonefinder 依赖大小**
   - 库会下载全球时区形状数据（~50MB）
   - 如果用户从不自动检测时区，这 50MB 是浪费
   - 解决：做成延迟加载，只在需要反查时才 `import`

10. **顶部时间 UI 与其他 HUD 元素重叠**
    - `set_speed_rect` 也在 y=45 附近（`onroad.cc:562`）
    - 需要预留位置，或让 set_speed_rect 上移/下移避让
    - 建议：时间显示 y=25，set_speed 保持 y=45，两者垂直错开

---

## 十一、参考代码

- `carrotpilot_c3_github/selfdrive/ui/qt/screenrecorder/screenrecorder.cc`（Qt 版录屏架构）
- `carrotpilot_c3_github/selfdrive/ui/qt/screenrecorder/omx_encoder.cc`（847 行，OMX 硬编完整实现）
- `openpilot_nanasemai/selfdrive/ui/onroad/exp_button.py`（raylib 按钮参考）
- `openpilot_nanasemai/system/ui/lib/application.py:322-351`（现有 RECORD=1 实现）
- `openpilot_nanasemai/system/ui/README.md:13`（现有 RECORD=1 文档）
- `openpilot_nanasemai/system/timed.py`（现有 GPS 时间同步，不改）
- `openpilot_nanasemai/system/qcomgpsd/qcomgpsd.py:307`（GPS unixTimestampMillis 来源）
- `openpilot_nanasemai/system/ubloxd/ubloxd.py:197`（u-blox GPS unixTimestampMillis）

**时间相关（nanapilot 参考）**：
- `openpilot_c2_src/nanapilot_master/system/timezoned.py`（时区服务完整实现）
- `openpilot_c2_src/nanapilot_master/selfdrive/boardd/set_time.py`（NTP+GPS+RTC 兜底同步）
- `openpilot_c2_src/nanapilot_master/selfdrive/ui/qt/onroad.cc:542-560`（UI 时间显示，Qt 版）
- `openpilot_c2_src/nanapilot_master/selfdrive/ui/qt/onroad.cc:562-566`（set_speed_rect 位置参考）
- `openpilot_c2_src/nanapilot_master/selfdrive/ui/qt/offroad/settings_dp.cc:333`（"显示时间"设置开关）
- `openpilot_c2_src/nanapilot_master/common/params_keys.h:139`（dp_show_date_time 参数定义）
- `openpilot_c2_src/nanapilot_master/selfdrive/ui/ui.cc:268`（scene 状态传递）

---

## 十二、总结

**推荐默认配置**（写入 params 初始值）：
```
分辨率:          720p (1280x720)，可切 1080p
帧率:            20 fps
切片:            180 秒 (3 分钟)
码率:            1 Mbps
编码器:          auto（优先 OMX，回退 ffmpeg）
目录:            /data/media/0/screenrecord
U 盘:            开启（自动探测，优先 U 盘）
最大总时长:      8 小时（超过自动删旧文件，循环录制）
UI 顶部时间:     开启（"yyyy-MM-dd hh:mm:ss"）
时区:            Asia/Shanghai
自动时间同步:    开启
```

**触发方式**：主屏右下角按钮双击
**UI 变化**：按钮红色闪烁 + 顶部红色状态条 + 顶部中央时间显示
**性能目标**：CPU < 30%（软编）或 < 3%（硬编）

**磁盘占用估算**（1080p 20fps CRF28 libx264 1Mbps）：
- 每 3 分钟切片约 22.5 MB
- 每小时约 450 MB
- 8 小时约 3.6 GB（U 盘 ≥ 8 GB 就够）

**参考对齐**：
- 时间 UI 显示：对齐 nanapilot `selfdrive/ui/qt/onroad.cc:542-560`
- 时区服务：对齐 nanapilot `system/timezoned.py`（简化版）
- 时间同步：补 nanapilot `selfdrive/boardd/set_time.py` 中 NTP 路径（去掉 Panda RTC，因为本项目 panda 是内部 SPI）
- OMX 硬编：对齐 carrotpilot `selfdrive/ui/qt/screenrecorder/omx_encoder.cc`
