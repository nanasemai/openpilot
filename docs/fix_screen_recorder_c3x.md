# 屏幕录制修复记录（C3X / tizi）

> 对应设计文档：`docs/plan_screen_recorder.md`
> 目标设备：C3X（tizi，commit `7d6da0f`，version `2026.002.000`）
> 分支：`sp-dev-261001`

---

## 一、问题现象

设置页开启"录制到 U 盘"后，实际表现：

| 现象 | 具体表现 |
|---|---|
| 录出来是空文件 | mp4 只有 **261 字节**，任何播放器都无法打开 |
| 录制时车机卡顿 | CPU 长时间打满，HUD 掉帧，触摸延迟 |
| 开机自动挂载崩溃 | 日志出现 `PermissionError`，U 盘不挂载 |
| 手动挂载也失败 | 提示 "already in use by /dev/sda12"，实际是误判 |
| 时间不同步 | 开机后时间停在出厂值，NTP 同步从未成功过 |

按下按钮有 UI 变化（按钮变红、顶部闪红条），所以**录制流程表面上是启动了的**——问题全部藏在数据链路里。

---

## 二、根因分析（6 个独立缺陷）

### 缺陷 1：`frame_source.py` 误用 raylib 6.0 的原地 API —— 空文件根因

这是最关键的一个。raylib 5.5 起，`ImageResize` / `ImageCrop` 的签名从"返回新 Image"改成了**原地修改、返回 void**：

```c
void ImageResize(Image *img, int newWidth, int newHeight);
```

设备上的 raylib 是 **6.0.0.0**，pyray 类型声明明确是 `void(*)(struct Image*,int,int)`。

但原代码仍按旧 API 写：

```python
# 错误：把 void 的返回值赋给 img
if img.width != target_w or img.height != target_h:
    resized = rl.image_resize(img, target_w, target_h)
    rl.unload_image(img)
    img = resized          # resized 实际是 None
```

于是每一帧都执行 `img = None`，随后 `rl.ffi.buffer(img.data, size)` 抛
`AttributeError: 'NoneType' object has no attribute 'data'`。

这条异常被 `application.py` 的 post-render 回调捕获并吞掉，只留下一行
`post-render callback error`，录制管线看起来正常运行，实际**一帧都没进编码器**。

ffmpeg 收到 0 帧 stdin 后仍然会写完整的 MP4 容器头，所以产出的是 261 字节的
"合法但空"文件。

默认参数是 1280x720，而渲染纹理是 2160x1080，**resize 分支必命中**，因此
默认设置下 100% 复现。

### 缺陷 2：`mountinfo` major:minor 匹配失效 —— U 盘检测误判

`storage.py` 原实现解析 `/proc/self/mountinfo` 拿 `major:minor`，再用它去
`/sys/block/*/` 里找设备号。

问题：`/proc/self/mountinfo` 里的 major:minor 是**挂载时该设备的块设备号**，
而 `/sys/block/<disk>/` 下面并没有按 major:minor 索引的文件，这个匹配逻辑
在部分内核版本上返回空。更严重的是它会把 eMMC 根分区匹配出来。

设备实测：`/data/media/usb` 被解析成 `/dev/sda12`（eMMC 上的数据分区），
而真正的 U 盘是 `/dev/sdg1`。

### 缺陷 3：往只读的 `/etc` 写 udev 规则 —— 开机自动挂载崩溃

原 `usb_storage.py` 的自动挂载方案是写入
`/etc/udev/rules.d/99-usb-storage.rules`，让 udev 在设备插入时自动挂载。

但 AGNOS 上 `/` 挂载为 **ro**（实测 `mount | grep ' / '` → `/dev/sda6 on /
type ext4 (ro,...)`），写文件直接 `PermissionError`，异常冒泡导致整个设置页
崩溃。

系统级 udev 目录不可写，这个方案在该设备上**结构性不可行**，不是配置问题。

### 缺陷 4：`mount` 不带 sudo 且不检查返回码 —— 手动挂载失败

两处问题叠加：

- `mount_usb()` 直接调 `mount`，未加 `sudo`。虽然 `comma` 用户可 sudo 免密，
  但 `mount` 本身需要 CAP_SYS_ADMIN，非 root 直接返回权限拒绝。
- `is_mounted()` 用 `mountpoint -q` 判断，但**忽略了退出码**，无条件 `return
  True`。

第二点是"already in use by /dev/sda12"的直接来源：`is_mounted()` 恒返回
True → 认为挂载点已占用 → 报"已被 /dev/sda12 占用"。实际上那个设备号还是
缺陷 2 解析出来的错误值。

此外 `get_mount_device` 原实现取 `/proc/mounts` 中**第一条前缀匹配**，
`/data/media/usb` 会先匹配到 `/data`（`/dev/sda12`）而不是
`/data/media/usb`（`/dev/sdg1`）。

### 缺陷 5：NTP 走 HTTPS 响应头 —— 时间同步永远失败

原 `time_sync.py` 用 `urllib.request.urlopen` 抓 HTTP 响应头里的 `Date`
字段，解析后 `date -s` 设置系统时间。

设备是车机离线环境，对外 HTTPS 被防火墙/代理拦截，`urlopen` 要么超时要么
返回错误页面，**从未拿到过 Date 头**。日志显示每次同步都走到超时分支。

### 缺陷 6：`date -s` 时区处理双向错误

发现两个方向相反的时区 bug，都在设备实测中确认：

- **timed.py**：传的是**本地 naive 时间串**，却加了 `env["TZ"] = "UTC"` →
  本地时间被当成 UTC 解释，**快 8 小时**。
- **time_sync.py**：传的是 **UTC 时间串**，却**没设 `TZ=UTC`**，容器默认
  TZ 是本地时区 → UTC 被按本地解释，**慢 8 小时**。

两处正好抵消，容易误以为"时区是对的"。设备无 `hwclock`、无 `clock` 命令、
`/dev/rtc0` ioctl 报 `Inappropriate ioctl for device`（虚拟 RTC），所以时间
只能靠 NTP + `date -s`，这两个 bug 让整条链路失效。

### 附带陷阱：NTP era 位

调试中一度误按 RFC 868 的 era 位处理 NTP 64 位秒字段，把 bit30 当成 era
标志位重新映射，得到 2060 年。NTPv4 的 seconds 字段是**普通 32 位秒**
（2026 年约 `3998302463`），bit30 只是普通位，不能做 era 重映射。

---

## 三、修复方案

### 3.1 `frame_source.py` —— 适配原地 API + 逐层防护

```python
if img.width <= 0 or img.height <= 0 or not img.data:
    rl.unload_image(img)
    return
if img.width != target_w or img.height != target_h:
    rl.image_resize(img, target_w, target_h)      # 原地，不赋值
    if img.width != target_w or img.height != target_h or not img.data:
        rl.unload_image(img)
        return
```

三道防护：加载后校验、resize 后二次校验、buffer 读取包 try/except。
任一步失败都干净卸载并 return，不会把异常抛到 post-render 回调里。

### 3.2 新增 `system/usb_mount.py` —— 共享挂载助手

把散落各处的挂载逻辑收敛到一个模块，供 `storage.py`、设置页、开机引导共用：

- `mount_usb` / `unmount_usb` / `format_drive`：全部 `sudo` 执行，
  **检查 returncode**，返回结构化 `MountResult`
- `get_mount_device(path)`：解析 `/proc/mounts`，用**最长前缀匹配**，
  正确得到 `/dev/sdg1` 而非 `/dev/sda12`
- `is_mounted(path)`：用 `/proc/mounts` **精确匹配**挂载点，不再忽略退出码
- `is_removable_device(dev)`：读 `/sys/block/<disk>/removable`，并剥离尾数字
  （`sdg1` → `sdg`）。这个检查取代了原来的 `/dev/sd*` 前缀判断——后者会把
  eMMC 的 `/dev/sda12` 误判为可移动设备
- `auto_mount_on_boot()`：2 秒间隔、20 秒上限的重试循环（开机时 USB 枚举
  慢于启动脚本）；CLI `--auto-mount` 永不抛异常、退出码恒 0

### 3.3 `launch_chffrplus.sh` —— 用户态自动挂载钩子

```sh
function usb_init {
  if [ "$(cat /data/params/d/USBAutoMount 2>/dev/null)" = "1" ]; then
    timeout 40 python3 "$DIR/system/usb_mount.py" --auto-mount 2>/dev/null || true
  fi
}
```

在 `if [ -f /AGNOS ]` 块内调用。`timeout` + `|| true` 保证任何情况下都不
阻塞启动。

### 3.4 `time_sync.py` —— 真实 NTP UDP 客户端

- `get_ntp_time_udp(server)`：直接发 NTPv4 48 字节包，解析 **plain 32 位秒**
  （不做任何 era 处理）；2036 溢出回退 `+2**32`；结果经
  `MIN_DATE_UTC < dt < MAX_DATE_UTC` 区间校验
- `set_system_time(dt, source)`：`env={**os.environ, "TZ": "UTC"}`（修慢 8 小时
  的 bug），失败时 sudo 回退
- `sync_if_drifted(params, max_drift_s=DEFAULT_MAX_DRIFT_S)`：漂移超 30 秒才
  校时，避免频繁改时间

NTP 服务器列表：`ntp.aliyun.com`、`ntp.tencent.com`、`pool.ntp.org`、
`cn.ntp.org.cn`、`ntp.ntsc.ac.cn`（多源容错）。

### 3.5 `timed.py` —— 开机 + 周期校时

- `set_time()` **去掉 `TZ=UTC`**（naive 本地串应无 TZ，修快 8 小时的 bug）
- `sync_time_at_boot()`：daemon 线程，开机即同步一次
- `retry_time_sync()`：60 秒周期；时间无效 → `ensure_time_valid()`，
  时间有效 → `sync_if_drifted()`

### 3.6 按钮 UI

| 项 | 修改前 | 修改后 |
|---|---|---|
| 空闲尺寸 | — | `IDLE_SIZE = 128` |
| 录制中尺寸 | — | `ACTIVE_SIZE = 172` |
| 录制指示 | 显示 `mm:ss` 秒数 | **红色实心闪烁圆**，不显示时间 |
| 按钮位置 | 与限速牌重叠 | 锚定 `set_speed_box()` 下方居中 |
| 顶部遮罩 | 显示 `● REC mm:ss` | 仅 `● REC` |
| 双击阈值 | — | `DOUBLE_CLICK_S = 0.35` |

新增 `RECORD_BTN_SIZE = 180`、`RECORD_BTN_GAP = 30`。

### 3.7 `hud_renderer.py` —— 共享几何

抽出 `set_speed_box(rect)`，两种单位（metric/imperial）中心 x 都归一到
`rect.x + 146`，底边 `rect.y + 249`，这样按钮在单位切换时不跳动。
`sunnypilot/onroad/hud_renderer.py` 也改用同一函数。

---

## 四、设备实测证据

设备与工作区代码完全一致（commit `7d6da0f`，11 个关键文件 `diff -q` 全 same），
故本地修复可直接在设备上验证。

### 4.1 旧代码复现原始报错

把设备上的**原始** `frame_source.py` 跑端到端流程，精确复现用户日志：

```
File ".../frame_source.py", line 46, in _grab_and_push
    data = bytes(rl.ffi.buffer(img.data, size))
AttributeError: 'NoneType' object has no attribute 'data'

During handling of the above exception, another exception occurred:
TypeError: initializer for ctype 'struct Image' must be a list or tuple or
dict or struct-cdata, not NoneType
```

### 4.2 修复后端到端录制（合成帧）

把本地修复版临时部署到设备，用真实 raylib 渲染纹理（2160x1080）+
真实 `_grab_and_push` 回调 + 真实 `FfmpegEncoder` 跑 60 帧：

```
callback runs=60, frames pushed=60, encoder frame_count=60, 5.60s
pushed-frame hashes: 60 total, 60 unique

screenrecord_20260913-162657_0000.mp4: 37569 bytes

codec_name=h264
width=1280
height=720
r_frame_rate=15/1
nb_frames=60
duration=4.000000
size=37569

full decode integrity (decode every frame to PNG): rc=0 | no errors
decoded: 60 frames, 60 unique PNG hashes
```

对照修复前：**0 帧 / 261 字节 / 无法播放**。
修复后：**60/60 帧 / 37.5KB / h264 解码零错误 / 帧内容真实变化**。

### 4.3 NTP 时间同步

两轮实测（原实现 0 次成功）：

| 服务器 | 第一轮 | 第二轮 |
|---|---|---|
| `ntp.aliyun.com` | OK 0.010s | OK 0.030s (60ms) |
| `ntp.tencent.com` | OK | OK 0.028s (45ms) |
| `pool.ntp.org` | OK | OK 0.229s (346ms) |
| `cn.ntp.org.cn` | OK | OK 0.061s (99ms) |
| `ntp.ntsc.ac.cn` | OK | **FAIL** (3014ms 超时) |

`get_ntp_time()` 全链路 drift **0.030 秒**。多源容错设计生效：单一服务器
超时不阻塞，4/5 可用即成功。

### 4.4 USB 挂载全路径

| 测试项 | 结果 |
|---|---|
| 手动挂载 `/dev/sdg1` | 成功 |
| 重复挂载（幂等） | 正确拒绝，不误报 "already in use" |
| 卸载 | 成功，`is_mounted` 正确返回 False |
| 格式化为 FAT32 | 成功（sudo + returncode 检查） |
| 开机自动挂载（冷启动） | 重试循环内成功 |
| `is_removable_device(/dev/sda12)` | `False`（eMMC 正确排除） |
| `is_removable_device(/dev/sdg1)` | `True` |

### 4.5 按钮几何

设备实测（真实 pyray）：按钮区域 `(86, 309) - (266, 489)`，限速牌从
x=314 起 → **无重叠**。

### 4.6 静态检查

- 全部 11 个改动文件 `py_compile` 通过，`launch_chffrplus.sh` `bash -n` 通过
- `ruff 0.9.10` 仅剩 3 条 **预先存在**的 TID251
  （`augmented_road_view.py` 的 `draw_text` / `draw_texture`，`git stash`
  前后一致，非本次改动引入）
- 设备上导入 7 个改动模块全部成功

---

## 五、部署后设备验证

5 个提交部署到设备（HEAD `94a09d4`，UI 进程 00:53 启动、代码 00:49 部署，
确认进程跑的是新代码）后的逐项回归验证。

### 5.1 运行时代码确认（反汇编）

不是只检查源码，而是反汇编设备实际加载的字节码确认修复真的生效：

```
408 LOAD_FAST   8 (rl)
410 LOAD_ATTR  29 (NULL|self + image_resize)
430 LOAD_FAST  10 (img)
432 LOAD_FAST   0 (target_w)
434 LOAD_FAST   1 (target_h)
436 CALL        3
444 POP_TOP          <-- 返回值被丢弃，原地修改语义正确
```

若是原 bug，此处会是 `CALL 3` → `STORE_FAST img`。

### 5.2 时区修正实测（双向）

`set_system_time()` 实机应用 NTP 时间后读回：

```
NTP time         : 2026-09-13 16:56:18.764415+00:00
local UTC before : 2026-09-13 16:56:18.726050+00:00
set_system_time() : True
local UTC after  : 2026-09-13 16:56:19.077188+00:00
post-apply drift : +0.313s    (必须 ~0，而非 +/-8h)
```

若两个时区 bug 仍在，这里会是 `+8h` 或 `-8h`。

同时确认：`time_sync.py` 传 `env={**os.environ, "TZ": "UTC"}`，
`timed.py` 的 `date -s` 不带 TZ。

### 5.3 USB 挂载全路径实测

```
1. unmount_usb()           -> ok=True  'Unmounted /data/media/usb'
   is_mounted()            -> False
2. mount_usb("/dev/sdg1")  -> ok=True  'Mounted /dev/sdg1 at /data/media/usb'
   df                      -> /dev/sdg1 100G 96K 100G 1%
3. 写入 /data/media/usb/.opencode_write_test -> 22 bytes   (确认真可写)
4. 重复 mount_usb()        -> ok=True  'Already mounted at /data/media/usb'
                             (不再误报 "already in use by /dev/sda12")
5. python3 system/usb_mount.py --auto-mount -> exit 0 (0.164s, 幂等)
```

可移动设备判定（eMMC 假阳性修复）：

| 设备 | `is_removable_device` |
|---|---|
| `/dev/sda12` | `False` |
| `/dev/sda6` | `False` |
| `/dev/mmcblk0p1` | `False` |
| `/dev/sdg` | `True` |
| `/dev/sdg1` | `True` |

挂载点解析（最长前缀修复）：`/data/media/usb` → `/dev/sdg1`，
`/data` → `/dev/sda12`，不存在的路径 → `None`。

### 5.4 按钮几何（两种单位系统）

| 单位 | 定速牌中心 x | 按钮区域 | 垂直间隙 | 按钮中心 x |
|---|---|---|---|---|
| metric | 146.0 | 56.0..236.0 × 279.0..459.0 | 30.0px | 146.0 |
| imperial | 146.0 | 56.0..236.0 × 279.0..459.0 | 30.0px | 146.0 |

两种单位中心 x 完全一致（`set_speed_box()` 归一化的目的达成），
单位切换时按钮不跳动；按钮与定速牌垂直不重叠。

确认 `record_button.py` 与 `augmented_road_view.py` 中**不存在任何**
`get_elapsed_seconds` / `strftime` / `mm:ss` / `%02d:%02d` 时间格式化代码。
双击启动/停止保留（`DOUBLE_CLICK_S = 0.35`）。

### 5.5 全栈录制（真实 ScreenRecorder）

用设备上已有的参数配置（`ScreenRecordUdisk=1`、`Res=0`、`Fps=2`、
`Encoder=0` 自动、`Bitrate=1`）跑真实 `ScreenRecorder`：

```
recorder.start() = True  (0.01s)
  resolved: 1280x720 @ 20fps, bitrate=1000000
  encoder backend proc pid = 80547          <-- ffmpeg 实际拉起
  storage resolve -> /data/media/usb/screenrecord
  using_udisk     -> True                   <-- 走 USB 而非 eMMC
post-render callbacks registered: 1
fired callback 80x in 5.53s
```

post-render 回调按 `application.py` 在 `rl.end_drawing()` 后的方式触发，
即真实运行路径。

**注**：测试后半段 `rec._encoder` 变为 `None`，这不是 bug——车机处于
offroad，`_monitor_offroad` 线程按原设计自动停止了录制（"下车自动停录"）。
这也反向证明监控线程正常工作。

### 5.6 提交结构

| commit | 内容 |
|---|---|
| `9614f32c52` | `fix(recorder)` frame_source 原地 API |
| `efdb7871ce` | `fix(usb)` 挂载助手 + 开机钩子 |
| `27c1f79eaf` | `fix(time)` NTP UDP + 时区 |
| `6f722b0f5a` | `fix(ui)` 按钮尺寸/位置/指示 |
| `94a09d4141` | `docs` 本文档 |

推送前检查：工作区无残留、`prebuilt` 已被 gitignore 不会误入、
变更内容扫描无密钥/证书、pre-push 依赖的 `git-lfs 3.4.1` 可用。

---

## 六、遗留说明

### 6.1 性能

崩溃修好后异常风暴和日志风暴消失，节流逻辑恢复，负载已大幅下降。

但 2160x1080 RGBA 每帧 readback 仍是 **~186 MB/s 的 GPU→CPU 拷贝**，
叠加 libx264 软编，仍是主要负载来源。

设备上**没有 OMX 库**（`libopenmaxil.so` 不存在），因此 `detect_encoder()`
必然返回 `ffmpeg` 而非 `omx`，短期无法硬件编码。要真正降低负载，需要：

- 让 agnos userspace 提供 OMX HAL，走 `OMX.qcom.video_encoder.hevc`（原计划
  文档中的优先级 2 方案）
- 或直接把录制分辨率降到 720p 后做 GPU 侧缩放，减少 readback 数据量

### 6.2 ffmpeg 可发现性

`/usr/local/venv/bin/ffmpeg` 是一个 313 字节的 Python 包装脚本，不在
系统默认 PATH 上。当前 manager 进程的 PATH 已包含 `/usr/local/venv/bin`
（由 `/etc/profile` 注入 `/usr/comma/shims:/usr/local/venv/bin:...`），
所以运行时能正常找到（全栈测试中 ffmpeg 子进程成功拉起）；但
`shutil.which("ffmpeg")` 在独立 shell 里返回 `None`，`detect_encoder()`
在隔离环境下会返回 `"none"`。

本次未改动该行为（录制在真实运行环境下工作正常），但需注意：若 PATH 被
裁剪，录制会报 `no encoder backend available` 而非静默产出空文件。

### 6.3 参数写入类型

录制相关参数在 `common/params_keys.h` 里是**强类型**的，例如
`{"ScreenRecordUdisk", {PERSISTENT | BACKUP, BOOL, "1"}}`。

用 Python 写这类参数必须匹配声明类型：`Params().put("ScreenRecordUdisk", "1")`
会抛 `TypeError: Type mismatch ... expected_type=<ParamKeyType.BOOL: 1>`。
必须传 `bool`（或对应 INT/FLOAT 类型）而非字符串。

设置页走的是 UI 控件的写入路径（已按类型处理），手工脚本改参数时容易踩坑。
`recorder._get_bool()` / `_get_int()` 内部已包 try/except 做容错，读侧安全。

---

## 七、改动文件清单

| 文件 | 改动 |
|---|---|
| `system/ui/screenrecorder/frame_source.py` | 修复原地 API 误用 + 三层防护 |
| `system/usb_mount.py` | **新建**：共享挂载助手 + CLI 引导入口 |
| `system/ui/screenrecorder/storage.py` | 改用 `get_mount_device` / `is_removable_device` |
| `system/time_sync.py` | NTP UDP 客户端 + `TZ=UTC` + drift 修正 |
| `system/timed.py` | 去掉错误的 TZ、开机/周期校时 |
| `launch_chffrplus.sh` | 新增 `usb_init` 引导钩子 |
| `selfdrive/ui/sunnypilot/layouts/settings/usb_storage.py` | 改用助手，删除 udev 写入 |
| `selfdrive/ui/sunnypilot/layouts/settings/screenrecorder.py` | 改用助手 |
| `selfdrive/ui/onroad/record_button.py` | 尺寸加大、红色闪烁、去时间显示 |
| `selfdrive/ui/onroad/augmented_road_view.py` | 按钮锚定限速牌下方居中 |
| `selfdrive/ui/onroad/hud_renderer.py` | 抽出 `set_speed_box()` |
| `selfdrive/ui/sunnypilot/onroad/hud_renderer.py` | 复用 `set_speed_box()` |
