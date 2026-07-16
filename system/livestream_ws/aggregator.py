"""
Livestream HUD Data Aggregator

在 HudBroadcaster 内部运行的数据聚合引擎：
1. 订阅所有 cereal topic
2. 通过 projectors 提取前端所需字段
3. 服务端单位转换（km/h ↔ mph 等）
4. 逐 topic 变更检测 → 支持增量推送
5. 周期性全量同步

设计目标：单进程内聚合，零额外 IPC 开销。
如需未来拆为独立进程，HudAggregator 可直接包裹。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from cereal import messaging
from openpilot.common.params import Params

from openpilot.system.livestream_ws.projectors import HUD_SOURCES

LOG = logging.getLogger("livestream_agg")

# 每 N 帧强制全量同步（让前端修正可能的合并偏差）
FULL_SYNC_INTERVAL = 6  # frames (≈3s @ 2Hz)

METRIC_REFRESH_INTERVAL = 20  # frames (≈10s)
PARAMS_REFRESH_INTERVAL = 10  # frames (≈5s)，驾驶风格等配置

# Params → 前端标签映射
PERSONALITY_MAP = {
    0: "激进", 1: "标准", 2: "放松",
}
ACCEL_PROFILE_MAP = {
    0: "标准", 1: "节能", 2: "运动",
    3: "舒适", 4: "自定义",
}


class HudAggregator:
    """数据聚合引擎：订阅 → 投影 → 变更检测 → 增量推送"""

    def __init__(self):
        self._sm: messaging.SubMaster | None = None
        # 全量快照（最新值，首次初始化时填入 None 默认值）
        self._full: dict[str, Any] = {}
        # 上一帧的逐 topic 数据（用于变更检测）
        self._prev: dict[str, Any] = {}
        # 已注册 topic 列表（HUD_SOURCES 去重）
        self._topics: list[str] = []
        # 当前单位偏好
        self._is_metric: bool = True
        self._frame: int = 0
        self._params: Params | None = None
        # 配置参数缓存（驾驶风格等），首次 poll 全量同步时一并推送
        self._cfg: dict = {}
        # 前车距离平滑（指数移动平均），α=0.3 兼顾响应速度和平滑度
        self._lead_smooth: dict[str, float] = {}
        self._lead_smooth_alpha: float = 0.3
        # 初始化缓存默认值，让 register() 的首次 full_snapshot 就有数据
        self._init_cache_defaults()

    def _ensure_params(self) -> Params:
        if self._params is None:
            self._params = Params()
        return self._params

    def _refresh_metric(self):
        try:
            self._is_metric = self._ensure_params().get_bool("IsMetric")
        except Exception:
            self._is_metric = True

    def _read_cfg_params(self) -> dict:
        """读取用户配置参数（驾驶风格、加速度预设等），返回 _cfg 子字典"""
        cfg = {}
        try:
            p = self._ensure_params()
            personality = p.get("LongitudinalPersonality", block=False)
            if personality is None:
                personality = 1  # default: standard
            cfg["personality"] = PERSONALITY_MAP.get(personality, "标准")
            accel = p.get("SPAccelProfile", block=False)
            if accel is None:
                accel = 0  # default: standard
            cfg["accelProfile"] = ACCEL_PROFILE_MAP.get(accel, "标准")
        except Exception:
            cfg["personality"] = "标准"
            cfg["accelProfile"] = "标准"
        return cfg

    def _read_car_params_from_params(self) -> dict:
        """从 Params 持久化存储读取 CarParams（避免等待 0.02Hz 的低频 cereal 消息）"""
        try:
            from cereal import car
            cp_bytes = self._ensure_params().get("CarParams")
            if cp_bytes:
                with car.CarParams.from_bytes(cp_bytes) as cp:
                    from openpilot.system.livestream_ws.projectors import proj_carParams
                    return proj_carParams(cp)
        except Exception:
            pass
        return {"openpilotLongitudinal": False}

    def _init_cache_defaults(self):
        """初始化缓存默认值，让前端立即有数据可渲染（显示 Off/-- 而非"未连接"）"""
        for key, _, _, _ in HUD_SOURCES:
            if key not in self._full:
                self._full[key] = None
        # carParams 从 Params 持久化存储读取，不依赖 cereal 消息
        self._full['carParams'] = self._read_car_params_from_params()

    @property
    def topics(self) -> list[str]:
        if not self._topics:
            seen: set[str] = set()
            self._topics = [t for _, t, _, _ in HUD_SOURCES
                           if not (t in seen or seen.add(t))]
        return self._topics

    # ── 公开接口 ──────────────────────────────────────

    def poll(self) -> dict[str, Any]:
        """拉取一次最新数据。

        返回值格式:
            { '_ts': float,           # 时间戳
              '_sync': bool,          # True=全量, False=增量
              'car': {...},           # 变化/新增的字段
              'self': {...},
              ...                     # 未变化的字段不会出现在增量帧中
            }
        """
        self._frame += 1

        if self._sm is None:
            self._sm = messaging.SubMaster(self.topics)
            self._refresh_metric()
            # 非阻塞拉取，开始接收 cereal 消息
            self._sm.update(0)
            # 重置帧计数，让本次 poll 触发全量同步（is_full_sync = True）
            self._frame = 0

        # 非阻塞拉取，由 _loop 的 sleep 控制推送节奏
        self._sm.update(0)

        # 周期刷新单位偏好
        if self._frame % METRIC_REFRESH_INTERVAL == 0:
            self._refresh_metric()

        # 周期读取配置参数（驾驶风格等），始终缓存到 self._cfg 供全量同步使用
        if self._frame % PARAMS_REFRESH_INTERVAL == 1:
            self._cfg = self._read_cfg_params()

        # 首次 poll 或每 N 帧强制全量同步
        is_full_sync = (self._frame % FULL_SYNC_INTERVAL == 1) or (not self._full)

        snapshot: dict[str, Any] = {}
        v_ego = self._sm['carState'].vEgo if 'carState' in self.topics and self._sm.valid.get('carState', False) else 0.0

        for key, topic, proj, kwargs in HUD_SOURCES:
            if not self._sm.updated.get(topic, False) and not is_full_sync:
                continue
            if not self._sm.valid.get(topic, False):
                continue

            try:
                raw = self._sm[topic]
                # lead 投影需要 v_ego
                if key == 'lead':
                    new_data = proj(raw, v_ego=float(v_ego))
                    # 对 dRel 做指数移动平均平滑，避免雷达噪声导致前端跳动
                    if new_data.get('dRel') is not None:
                        prev = self._lead_smooth.get('dRel', new_data['dRel'])
                        smoothed = self._lead_smooth_alpha * new_data['dRel'] + (1 - self._lead_smooth_alpha) * prev
                        self._lead_smooth['dRel'] = smoothed
                        new_data['dRel'] = round(smoothed, 2)
                else:
                    new_data = proj(raw, is_metric=self._is_metric)

                # 变更检测：跟上一帧对比
                old = self._prev.get(key)
                if new_data == old and not is_full_sync:
                    continue

                self._prev[key] = new_data
                snapshot[key] = new_data
            except Exception as e:
                LOG.debug("projection error for %s: %s", key, e)

        if not snapshot and not is_full_sync:
            return {'_ts': time.time(), '_sync': False}

        # 更新全量快照
        self._full.update(snapshot)

        if is_full_sync:
            result = dict(self._full)
            # 全量同步 → 清除已失效 topic 的脏数据（车熄火后旧速度/转向等不再推送）
            for key, topic, _, _ in HUD_SOURCES:
                if not self._sm.valid.get(topic, False) and key in result:
                    result[key] = None
                    self._full[key] = None   # 同步清除缓存，避免下轮增量带出旧值
            # 全量同步携带配置参数，确保前端 _cfg 始终生效
            if self._cfg:
                result['_cfg'] = self._cfg
        else:
            result = dict(snapshot)
        result['_ts'] = time.time()
        result['_sync'] = is_full_sync
        return result

    @property
    def full_snapshot(self) -> dict[str, Any]:
        """获取当前全量快照（不触发 cereal 更新）"""
        # SubMaster 从未收到有效数据 → 返回最小响应，避免前端被 None 值覆盖
        if self._sm is None or not any(self._sm.valid.values()):
            result: dict[str, Any] = {'_ts': time.time(), '_sync': True}
            if self._cfg:
                result['_cfg'] = self._cfg
            return result

        result = dict(self._full)
        # 新客户端连接时也清除脏数据，避免刚上车时看到熄火前的旧值
        if self._sm is not None:
            for key, topic, _, _ in HUD_SOURCES:
                if not self._sm.valid.get(topic, False) and key in result:
                    result[key] = None
        if self._cfg:
            result['_cfg'] = self._cfg
        result['_ts'] = time.time()
        result['_sync'] = True
        return result