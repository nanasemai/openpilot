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

LOG = logging.getLogger("livestream_ws")

HOST = os.environ.get("LIVESTREAM_WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("LIVESTREAM_WS_PORT", "8090"))

# WebRTC 信令后端（webrtcd）地址
WEBRTCD_HOST = os.environ.get("WEBRTCD_HOST", "localhost")
WEBRTCD_PORT = int(os.environ.get("WEBRTCD_PORT", "5001"))

# Web 静态文件目录
WEB_DIST = os.path.join(os.path.dirname(__file__), "web", "dist")

# HUD 广播频率（Hz）
HUD_RATE_HZ = 10.0

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

    async def ensure_running(self):
        if self._task is None or self._task.done():
            self._agg = HudAggregator()
            self._task = asyncio.create_task(self._loop(), name="hud_pump")

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


def make_app() -> web.Application:
    app = web.Application()
    app["hud"] = HudBroadcaster()

    app.router.add_get("/", index)
    app.router.add_get("/ws/data", ws_data)
    app.router.add_post("/offer", webrtc_offer)
    app.router.add_get("/health", health)

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
