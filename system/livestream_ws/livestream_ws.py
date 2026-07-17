#!/usr/bin/env python3
"""
Livestream Web Server —— 局域网低占用实时投屏 + 车辆 HUD 数据

通过 HudAggregator 提供 /ws/data 中继聚合车辆状态作为 HUD 叠加数据。
服务端做字段筛选 + 变更检测 + 10Hz 推送，避免带宽浪费。
通过 WebRTC 信令代理 /offer 转发浏览器 SDP 给本机 webrtcd 实现视频推流。

监听：0.0.0.0:8090
端点：
    GET  /           → 前端全屏 <canvas> 视频 + HUD 叠加层
    GET  /ws/data    → WebSocket 车辆状态 JSON 流 (10Hz, 增量推送)
    POST /offer      → WebRTC SDP 信令代理
    GET  /health     → JSON 健康检查

设计要点：
- 单一聚合循环 + 多客户端广播（多观众共享一路 HudAggregator）
- Producer / Sender 双协程解耦，慢客户端不拖累其他人
- conflate=True：cereal 只保留最新一帧，无观众时休眠
- IDLE_STOP：无客户端 5 秒后关闭订阅，恢复零 CPU
- HUD 变更检测 + 增量推送 → 无变化时不产生 JSON 流量
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import aiohttp
from aiohttp import web, WSMsgType

from openpilot.system.livestream_ws.aggregator import HudAggregator
from openpilot.common.params import Params
from cereal import messaging

LOG = logging.getLogger("livestream_ws")

HOST = os.environ.get("LIVESTREAM_WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("LIVESTREAM_WS_PORT", "8090"))

# WebRTC 信令后端（webrtcd）地址
WEBRTCD_HOST = os.environ.get("WEBRTCD_HOST", "localhost")
WEBRTCD_PORT = int(os.environ.get("WEBRTCD_PORT", "5001"))

# Web 静态文件目录
WEB_DIST = os.path.join(os.path.dirname(__file__), "web", "dist")

# HUD 广播频率（Hz）- 0.5s 更新一次，避免前端刷新过快
HUD_RATE_HZ = 2.0

# 无客户端 5 秒后停止聚合（省 CPU）
IDLE_STOP_SEC = 5.0


# ─────────────────────────────────────────────────────────
# HUD 数据广播器：聚合 → 增量推送 → WebSocket 客户端
# ─────────────────────────────────────────────────────────
class HudBroadcaster:
    def __init__(self):
        self.clients: set[web.WebSocketResponse] = set()
        self._task: asyncio.Task | None = None
        self._agg: HudAggregator | None = None
        self._idle_since: float = 0.0
        # 持久 SubMaster：用于 get_safety_context，避免每次 API 请求新建导致读不到数据
        self._safety_sm: messaging.SubMaster | None = None

    async def ensure_running(self):
        if self._task is None or self._task.done():
            self._agg = HudAggregator()
            self._task = asyncio.create_task(self._loop(), name="hud_pump")
        # 确保安全上下文的 SubMaster 已初始化
        if self._safety_sm is None:
            self._safety_sm = messaging.SubMaster(["deviceState", "selfdriveState", "selfdriveStateSP"])

    async def register(self, ws: web.WebSocketResponse):
        self.clients.add(ws)
        await self.ensure_running()
        # 新客户端立即发一次全量快照
        if self._agg:
            try:
                full = self._agg.full_snapshot
                if full:
                    await ws.send_str(json.dumps(full, ensure_ascii=False,
                                                  separators=(",", ":")))
            except Exception:
                self.clients.discard(ws)

    def unregister(self, ws: web.WebSocketResponse):
        self.clients.discard(ws)

    def get_safety_context(self, params: Params) -> dict:
        """获取安全上下文

        规则：
          - 开启 OffroadMode → 始终停车，所有参数可改
          - 关闭 OffroadMode → 从持久 SubMaster 读取真实 deviceState.started
          - engaged = started AND (selfdriveState.enabled OR selfdriveStateSP.mads.enabled)
        """
        started = False
        engaged = False
        always_offroad = False
        try:
            always_offroad = params.get_bool("OffroadMode")
            if always_offroad:
                # 强制停车模式
                started = False
                engaged = False
            else:
                # 从持久 SubMaster 读取真实车辆状态
                if self._safety_sm is not None:
                    self._safety_sm.update(0)
                    if self._safety_sm.updated["deviceState"]:
                        started = self._safety_sm["deviceState"].started
                    sd_enabled = bool(self._safety_sm["selfdriveState"].enabled) if self._safety_sm.updated["selfdriveState"] else False
                    mads_enabled = bool(self._safety_sm["selfdriveStateSP"].mads.enabled) if self._safety_sm.updated.get("selfdriveStateSP", False) else False
                    engaged = started and (sd_enabled or mads_enabled)
        except Exception:
            pass
        return {"started": started, "engaged": engaged, "always_offroad": always_offroad,
                "level": 2 if engaged else (1 if started else 0)}

    async def _loop(self):
        loop = asyncio.get_running_loop()
        interval = 1.0 / HUD_RATE_HZ
        agg = self._agg
        if agg is None:
            return

        while True:
            try:
                if not self.clients:
                    if self._idle_since == 0.0:
                        self._idle_since = time.monotonic()
                    elif time.monotonic() - self._idle_since > IDLE_STOP_SEC:
                        LOG.info("[hud] idle → stop aggregator")
                        # idle stop: 下一个客户端会重新 ensure_running
                        break
                    await asyncio.sleep(0.1)
                    continue
                self._idle_since = 0.0

                # 在 executor 中运行 agg.poll()（内含 cereal recv）
                snapshot = await loop.run_in_executor(None, agg.poll)

                # 无变化时跳过
                if not snapshot.get('_sync') and len(snapshot) <= 2:  # 只有 _ts 和 _sync
                    await asyncio.sleep(interval)
                    continue

                payload = json.dumps(snapshot, ensure_ascii=False,
                                     separators=(",", ":"))

                dead: list[web.WebSocketResponse] = []
                for ws in self.clients:
                    try:
                        await asyncio.wait_for(ws.send_str(payload), timeout=0.3)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    self.clients.discard(ws)

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception:
                LOG.exception("[hud] loop error")
                await asyncio.sleep(0.2)


# ─────────────────────────────────────────────────────────
# HTTP / WebSocket 路由
# ─────────────────────────────────────────────────────────

async def ws_data(request: web.Request):
    ws = web.WebSocketResponse(max_msg_size=0, heartbeat=15)
    await ws.prepare(request)
    hud: HudBroadcaster = request.app["hud"]
    await hud.register(ws)
    LOG.info("hud client + (total=%d)", len(hud.clients))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        hud.unregister(ws)
        LOG.info("hud client - (total=%d)", len(hud.clients))
    return ws


async def index(request):
    index_path = os.path.join(WEB_DIST, "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    # 降级：没有前端文件时返回简单状态页
    return web.Response(
        text="<html><body><h1>livestream_ws running</h1>"
             "<p>Install frontend at system/livestream_ws/web/dist/index.html</p></body></html>",
        content_type="text/html")


async def health(request):
    app = request.app
    hud: HudBroadcaster = app["hud"]
    return web.json_response({
        "ok": True,
        "hud": {"clients": len(hud.clients),
                "rate_hz": HUD_RATE_HZ},
    })


# ─────────────────────────────────────────────────────────
# WebRTC 信令代理：转发浏览器 SDP offer 给本机 webrtcd
# 浏览器（含 iOS Safari）原生支持 WebRTC，无需 WebCodecs/MSE
# ─────────────────────────────────────────────────────────
async def webrtc_offer(request: web.Request):
    try:
        params = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="invalid JSON")

    sdp = params.get("sdp")
    if not sdp:
        raise web.HTTPBadRequest(text="missing sdp")
    camera = params.get("camera", "road")

    # 转发给 webrtcd 的 /stream（body 契约见 webrtcd.StreamRequestBody）
    body = json.dumps({
        "sdp": sdp,
        "initCamera": camera,
        "bridge_services_in": [],
        "bridge_services_out": [],
    })
    url = f"http://{WEBRTCD_HOST}:{WEBRTCD_PORT}/stream"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.post(url, data=body,
                                    headers={"Content-Type": "application/json"}) as resp:
                text = await resp.text()
                return web.Response(status=resp.status, text=text,
                                    content_type="application/json")
    except aiohttp.ClientError as e:
        LOG.warning("webrtcd unreachable: %s", e)
        raise web.HTTPBadGateway(
            text=json.dumps({"error": "webrtcd_unreachable", "message": str(e)}),
            content_type="application/json")


# ─────────────────────────────────────────────────────────
# 设置管理 API
# ─────────────────────────────────────────────────────────

# 参数定义：分组、参数名、安全级别
# 分组结构参考 selfdrive/ui/layouts/ (stock + sunnypilot)
# type: "bool"=开关, "int"=数值(+/-), "select"=多选一
# safety: "offroad"=停车才能改, "not_engaged"=非engaged可改, "always"=随时可改
SETTINGS_DEFS = [
  # Toggles - 主开关页面 (selfdrive/ui/layouts/settings/toggles.py)
  {"group": "Toggles", "params": [
    {"key": "OffroadMode", "label": "启用非上路模式", "type": "bool", "safety": "always"},
    {"key": "OpenpilotEnabledToggle", "label": "启用 sunnypilot", "type": "bool", "safety": "offroad", "needs_restart": True},
    {"key": "ExperimentalMode", "label": "实验模式", "type": "bool", "safety": "not_engaged"},
    {"key": "LongitudinalPersonality", "label": "驾驶风格", "type": "select", "safety": "always", "options": [{"v": 0, "l": "激进"}, {"v": 1, "l": "标准"}, {"v": 2, "l": "放松"}]},
    {"key": "DisengageOnAccelerator", "label": "踩下加速踏板时脱离", "type": "bool", "safety": "always"},
    {"key": "IsLdwEnabled", "label": "启用车道偏离警示", "type": "bool", "safety": "always"},
    {"key": "DisableDriverMonitoringCamera", "label": "禁用驾驶监控摄像头", "type": "bool", "safety": "offroad", "needs_restart": True},
    {"key": "IsMetric", "label": "使用公制", "type": "bool", "safety": "always"},
  ]},
  # Cruise - 巡航页面 (selfdrive/ui/sunnypilot/layouts/settings/cruise.py)
  {"group": "Cruise", "params": [
    {"key": "DynamicExperimentalControl", "label": "动态实验控制 (DEC)", "type": "bool", "safety": "not_engaged"},
    {"key": "IntelligentCruiseButtonManagement", "label": "智能巡航按钮管理 (ICBM)", "type": "bool", "safety": "offroad"},
    {"key": "SmartCruiseControlVision", "label": "智能巡航控制 - 视觉 (SCC-V)", "type": "bool", "safety": "not_engaged"},
    {"key": "SmartCruiseControlMap", "label": "智能巡航控制 - 地图 (SCC-M)", "type": "bool", "safety": "not_engaged"},
    {"key": "CustomAccIncrementsEnabled", "label": "自定义 ACC 速度增量", "type": "bool", "safety": "offroad"},
    {"key": "CustomAccShortPressIncrement", "label": "短按增量 (km/h)", "type": "int", "safety": "always"},
    {"key": "CustomAccLongPressIncrement", "label": "长按增量 (km/h)", "type": "int", "safety": "always"},
    {"key": "SPAccelProfile", "label": "加速度预设", "type": "select", "safety": "offroad", "options": [{"v": 0, "l": "标准"}, {"v": 1, "l": "节能"}, {"v": 2, "l": "运动"}, {"v": 3, "l": "舒适"}]},
    {"key": "SPAccelProfileModeEnabled", "label": "自动激进模式 (APM)", "type": "bool", "safety": "offroad"},
    {"key": "dp_htd_enabled", "label": "人工转弯检测 (HTD)", "type": "bool", "safety": "always"},
    {"key": "dp_htd_turn_angle_threshold", "label": "HTD 转向角阈值", "type": "int", "safety": "always"},
    {"key": "SpeedLimitMode", "label": "限速模式", "type": "select", "safety": "not_engaged", "options": [{"v": 0, "l": "关闭"}, {"v": 1, "l": "提示"}, {"v": 2, "l": "警告"}, {"v": 3, "l": "辅助"}]},
    {"key": "SpeedLimitPolicy", "label": "限速数据源", "type": "select", "safety": "not_engaged", "options": [{"v": 0, "l": "仅车辆"}, {"v": 1, "l": "仅地图"}, {"v": 2, "l": "车辆优先"}, {"v": 3, "l": "地图优先"}, {"v": 4, "l": "综合"}]},
    {"key": "SpeedLimitOffsetType", "label": "限速偏移类型", "type": "select", "safety": "not_engaged", "options": [{"v": 0, "l": "无"}, {"v": 1, "l": "固定值"}, {"v": 2, "l": "百分比"}]},
    {"key": "SpeedLimitValueOffset", "label": "限速偏移值", "type": "int", "safety": "not_engaged"},
  ]},
  # Steering - 转向页面 (selfdrive/ui/sunnypilot/layouts/settings/steering.py)
  {"group": "Steering", "params": [
    {"key": "Mads", "label": "模块化辅助驾驶系统 (MADS)", "type": "bool", "safety": "offroad"},
    {"key": "MadsMainCruiseAllowed", "label": "MADS 允许主巡航切换", "type": "bool", "safety": "offroad"},
    {"key": "MadsUnifiedEngagementMode", "label": "MADS 统一接合模式 (UEM)", "type": "bool", "safety": "offroad"},
    {"key": "MadsSteeringMode", "label": "制动踏板转向模式", "type": "select", "safety": "offroad", "options": [{"v": 0, "l": "保持活跃"}, {"v": 1, "l": "暂停"}, {"v": 2, "l": "脱离"}]},
    {"key": "BlinkerPauseLateralControl", "label": "拨杆时暂停横向控制", "type": "bool", "safety": "always"},
    {"key": "BlinkerMinLateralControlSpeed", "label": "暂停横向最低速度", "type": "int", "safety": "always"},
    {"key": "BlinkerLateralReengageDelay", "label": "拨杆后重接延迟 (秒)", "type": "int", "safety": "always"},
    {"key": "EnforceTorqueControl", "label": "强制扭矩横向控制", "type": "bool", "safety": "offroad"},
    {"key": "NeuralNetworkLateralControl", "label": "神经网络横向控制 (NNLC)", "type": "bool", "safety": "offroad"},
    {"key": "LateralPositionOffset", "label": "车道位置偏移 (cm)", "type": "int", "safety": "always"},
    {"key": "RoadEdgeLcaBlindspot", "label": "变道检测到道路边缘", "type": "bool", "safety": "always"},
    {"key": "AutoLaneChangeTimer", "label": "自动变道延迟 (秒)", "type": "int", "safety": "always"},
    {"key": "AutoLaneChangeBsmDelay", "label": "盲区时延迟自动变道", "type": "bool", "safety": "always"},
  ]},
  # Visuals - 视觉页面 (selfdrive/ui/sunnypilot/layouts/settings/visuals.py)
  {"group": "Visuals", "params": [
    {"key": "BlindSpot", "label": "显示盲区警告", "type": "bool", "safety": "always"},
    {"key": "TorqueBar", "label": "转向弧度", "type": "bool", "safety": "always"},
    {"key": "RainbowMode", "label": "彩红路径模式", "type": "bool", "safety": "always"},
    {"key": "StandstillTimer", "label": "停车计时器", "type": "bool", "safety": "always"},
    {"key": "RoadNameToggle", "label": "显示道路名称", "type": "bool", "safety": "always"},
    {"key": "GreenLightAlert", "label": "绿灯提醒 (Beta)", "type": "bool", "safety": "always"},
    {"key": "LeadDepartAlert", "label": "前车驶离提醒 (Beta)", "type": "bool", "safety": "always"},
    {"key": "TrueVEgoUI", "label": "车速表：始终显示真实速度", "type": "bool", "safety": "always"},
    {"key": "HideVEgoUI", "label": "车速表：隐藏", "type": "bool", "safety": "always"},
    {"key": "ShowTurnSignals", "label": "显示转向灯", "type": "bool", "safety": "always"},
    {"key": "RocketFuel", "label": "实时加速度条", "type": "bool", "safety": "always"},
    {"key": "ChevronInfo", "label": "前车下方显示信息", "type": "select", "safety": "always", "options": [{"v": 0, "l": "关闭"}, {"v": 1, "l": "距离"}, {"v": 2, "l": "速度"}, {"v": 3, "l": "时间"}, {"v": 4, "l": "全部"}]},
    {"key": "DevUIInfo", "label": "开发者信息显示", "type": "select", "safety": "always", "options": [{"v": 0, "l": "关闭"}, {"v": 1, "l": "底部"}, {"v": 2, "l": "右侧"}, {"v": 3, "l": "右侧和底部"}]},
  ]},
  # Models - 模型页面 (selfdrive/ui/sunnypilot/layouts/settings/models.py)
  {"group": "Models", "params": [
    {"key": "LaneTurnDesire", "label": "使用车道转弯意图", "type": "bool", "safety": "always"},
    {"key": "LaneTurnValue", "label": "车道转弯速度调整", "type": "int", "safety": "always"},
    {"key": "LagdToggle", "label": "实时学习转向延迟", "type": "bool", "safety": "always"},
  ]},
  # Device - 设备页面 (selfdrive/ui/sunnypilot/layouts/settings/device.py)
  {"group": "Device", "params": [
    {"key": "OffroadMode", "label": "始终非上路", "type": "bool", "safety": "always"},
    {"key": "MaxTimeOffroad", "label": "最大熄火时间 (分钟)", "type": "int", "safety": "always"},
    {"key": "DeviceBootMode", "label": "启动行为", "type": "select", "safety": "offroad", "options": [{"v": 0, "l": "默认"}, {"v": 1, "l": "非上路"}]},
    {"key": "AudibleAlertMode", "label": "声音提示模式", "type": "select", "safety": "always", "options": [{"v": 0, "l": "全部"}, {"v": 1, "l": "仅警告"}, {"v": 2, "l": "静音"}]},
  ]},
  # Display - 显示页面 (selfdrive/ui/sunnypilot/layouts/settings/display.py)
  {"group": "Display", "params": [
    {"key": "OnroadScreenOffBrightness", "label": "行车中屏幕亮度", "type": "int", "safety": "always"},
    {"key": "OnroadScreenOffTimer", "label": "行车中亮度延迟 (秒)", "type": "int", "safety": "always"},
    {"key": "InteractivityTimeout", "label": "交互超时 (秒)", "type": "int", "safety": "always"},
  ]},
  # Software - 软件页面 (selfdrive/ui/layouts/settings/software.py)
  {"group": "Software", "params": [
    {"key": "DisableUpdates", "label": "禁用更新", "type": "bool", "safety": "offroad"},
    {"key": "dp_dev_disable_connect", "label": "禁用 Comma Connect", "type": "bool", "safety": "always"},
  ]},
  # Sunnylink (selfdrive/ui/sunnypilot/layouts/settings/sunnylink.py)
  {"group": "Sunnylink", "params": [
    {"key": "SunnylinkEnabled", "label": "启用 Sunnylink", "type": "bool", "safety": "offroad"},
    {"key": "EnableSunnylinkUploader", "label": "启用 Sunnylink 上传", "type": "bool", "safety": "offroad"},
  ]},
  # Developer - 开发者页面 (selfdrive/ui/sunnypilot/layouts/settings/developer.py)
  {"group": "Developer", "params": [
    {"key": "AdbEnabled", "label": "启用 ADB", "type": "bool", "safety": "offroad"},
    {"key": "SshEnabled", "label": "启用 SSH", "type": "bool", "safety": "always"},
    {"key": "EnableLivestream", "label": "启用投屏", "type": "bool", "safety": "always"},
    {"key": "EnableCopyparty", "label": "copyparty 服务", "type": "bool", "safety": "offroad"},
    {"key": "QuickBootToggle", "label": "快速启动模式", "type": "bool", "safety": "offroad"},
    {"key": "ShowAdvancedControls", "label": "显示高级控制", "type": "bool", "safety": "always"},
    {"key": "EnableGithubRunner", "label": "GitHub Runner 服务", "type": "bool", "safety": "always"},
  ]},
]

# 安全级别数值（与 level 比较）：
#   always(0):       任何状态可改
#   offroad(1):      started 时锁定   → locked = level >= 1
#   not_engaged(2):  engaged 时锁定  → locked = level >= 2
SAFETY_LEVELS = {"offroad": 1, "not_engaged": 2, "always": 0}

# 可写参数集合（白名单）
WRITABLE_KEYS = {p["key"] for g in SETTINGS_DEFS for p in g["params"]}


def get_safety_context(params: Params) -> dict:
    """获取车辆安全上下文：started / engaged

    语义对齐 RAYLIB UI（selfdrive/ui/ui_state.py）：
      - started = IsOnroad OR ForceOnroad
        （manager 在 write_onroad_params() 中同步写入 IsOnroad，
          基于 deviceState.started AND ignition，比单独查 cereal 可靠）
      - engaged = started AND (selfdriveState.enabled OR selfdriveStateSP.mads.enabled)
    安全级别锁定条件：
      offroad(2):    started 时锁定   → locked = started
      not_engaged(1): engaged 时锁定  → locked = engaged
      always(0):     任何状态可改
    """
    started = False
    engaged = False
    always_offroad = False
    try:
        always_offroad = params.get_bool("OffroadMode")
        # started 优先从 Params 读取（manager 同步写入，无 cereal 时序问题）
        started = params.get_bool("IsOnroad") or params.get_bool("ForceOnroad")
        # engaged 仍需 cereal 数据，尝试非阻塞读取一次
        sm = messaging.SubMaster(["selfdriveState", "selfdriveStateSP"])
        sm.update(0)
        sd_enabled = bool(sm["selfdriveState"].enabled) if sm.updated["selfdriveState"] else False
        mads_enabled = bool(sm["selfdriveStateSP"].mads.enabled) if sm.updated.get("selfdriveStateSP", False) else False
        engaged = started and (sd_enabled or mads_enabled)
    except Exception:
        pass
    # 始终非上路模式下，视为停车状态，允许修改停车时才能改的参数
    if always_offroad:
        started = False
        engaged = False
    return {"started": started, "engaged": engaged, "always_offroad": always_offroad,
            "level": 2 if engaged else (1 if started else 0)}


async def get_settings_api(request):
    """GET /api/settings → 返回所有参数配置 + 当前值 + 安全状态"""
    params: Params = request.app["params"]
    hud: HudBroadcaster = request.app["hud"]
    ctx = hud.get_safety_context(params)
    result = []
    for group in SETTINGS_DEFS:
        items = []
        for p in group["params"]:
            key = p["key"]
            try:
                if p["type"] == "bool":
                    val = params.get_bool(key)
                else:
                    raw = params.get(key)
                    if raw is not None:
                        try:
                            val = int(float(raw))
                        except (ValueError, TypeError):
                            val = 0
                    else:
                        val = 0
            except Exception:
                val = None
            min_safety = SAFETY_LEVELS.get(p["safety"], 0)
            locked = min_safety > 0 and ctx["level"] >= min_safety
            items.append({**p, "value": val, "locked": locked})
        result.append({"group": group["group"], "items": items})
    return web.json_response({"settings": result, "context": ctx})


async def save_setting_api(request):
    """POST /api/settings/{param}  body: {"value": ...} → 修改参数（带安全校验）"""
    param_name = request.match_info.get("param")
    if param_name not in WRITABLE_KEYS:
        raise web.HTTPBadRequest(text=json.dumps({"error": "unknown_param"}), content_type="application/json")

    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text=json.dumps({"error": "invalid_json"}), content_type="application/json")

    params: Params = request.app["params"]
    hud: HudBroadcaster = request.app["hud"]
    ctx = hud.get_safety_context(params)

    # 查找参数定义
    pdef = None
    for g in SETTINGS_DEFS:
        for p in g["params"]:
            if p["key"] == param_name:
                pdef = p
                break
        if pdef:
            break

    if not pdef:
        raise web.HTTPBadRequest(text=json.dumps({"error": "unknown_param"}), content_type="application/json")

    # 安全校验
    min_safety = SAFETY_LEVELS.get(pdef["safety"], 0)
    LOG.info("save_setting: key=%s value=%s safety=%s min_safety=%s level=%s",
             param_name, body.get("value"), pdef["safety"], min_safety, ctx["level"])
    if min_safety > 0 and ctx["level"] >= min_safety:
        # reason 按 RAYLIB UI 语义生成：
        #   offroad(1)     锁定条件 = started  → "车辆启动后无法修改"
        #   not_engaged(2) 锁定条件 = engaged  → "sunnypilot 启用中无法修改"
        if min_safety == 2:
            reason = "sunnypilot 启用中无法修改，请脱离后再试"
        else:
            reason = "车辆启动后无法修改，请熄火后再试"
        raise web.HTTPForbidden(text=json.dumps({"error": "locked", "reason": reason}), content_type="application/json")

    value = body.get("value")
    try:
        if pdef["type"] == "bool":
            params.put_bool(param_name, bool(value))
        else:
            params.put(param_name, str(int(value)))
        if pdef.get("needs_restart"):
            params.put_bool("OnroadCycleRequested", True)
    except Exception as e:
        raise web.HTTPBadRequest(text=json.dumps({"error": "write_failed", "message": str(e)}), content_type="application/json")

    return web.json_response({"ok": True, "param": param_name, "value": value})


async def get_context_api(request):
    """GET /api/context → 车辆安全上下文"""
    params: Params = request.app["params"]
    hud: HudBroadcaster = request.app["hud"]
    ctx = hud.get_safety_context(params)
    return web.json_response(ctx)


def make_app() -> web.Application:
    app = web.Application()
    app["hud"] = HudBroadcaster()
    app["params"] = Params()

    app.router.add_get("/", index)
    app.router.add_get("/ws/data", ws_data)
    app.router.add_post("/offer", webrtc_offer)
    app.router.add_get("/health", health)
    app.router.add_get("/api/settings", get_settings_api)
    app.router.add_post("/api/settings/{param}", save_setting_api)
    app.router.add_get("/api/context", get_context_api)

    # 静态文件（CSS/JS/图片等）
    if os.path.isdir(WEB_DIST):
        app.router.add_static("/static", path=WEB_DIST, name="static")
        LOG.info("serving static files from %s", WEB_DIST)

    return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    LOG.info("livestream_ws listening on %s:%d", HOST, PORT)
    LOG.info("hud rate: %.1fHz, frontend: %s", HUD_RATE_HZ, WEB_DIST)
    web.run_app(make_app(), host=HOST, port=PORT, access_log=None)


if __name__ == "__main__":
    main()
