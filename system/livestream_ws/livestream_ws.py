#!/usr/bin/env python3
"""
Livestream WebSocket Server —— 局域网低占用实时投屏 + 车辆 HUD 数据

订阅 qRoadEncodeData（qcamera 526x330 @ 256kbps H.264, encoderd 常驻输出，
零额外编码开销），通过 WebSocket 二进制帧原样推送 H.264 NALU 给
浏览器/手机 App，客户端用 WebCodecs / MediaCodec 硬解显示。

同时通过 HudAggregator 提供第二路 /ws/data 中继聚合车辆状态作为
HUD 叠加数据。服务端做字段筛选 + 变更检测 + 10Hz 推送，避免带宽浪费。

监听：0.0.0.0:8090
端点：
    GET  /                → 前端全屏 <canvas> 视频 + HUD 叠加层
    GET  /ws/video?cam=X  → WebSocket 视频流 (只支持 cam=road, 默认 road)
    GET  /ws/data         → WebSocket 车辆状态 JSON 流 (10Hz, 增量推送)
    GET  /health          → JSON 健康检查
    # 向后兼容旧路径
    GET  /ws              → 等价 /ws/video?cam=road

设计要点：
- 单一聚合循环 + 多客户端广播（多观众共享一路 HudAggregator）
- Producer / Sender 双协程解耦，慢客户端不拖累其他人
- conflate=True：cereal 只保留最新一帧，无观众时休眠
- IDLE_STOP：无客户端 5 秒后关闭订阅，恢复零 CPU
- 视频客户端 backpressure：写缓冲 > 1MB 时丢非关键帧
- HUD 变更检测 + 增量推送 → 无变化时不产生 JSON 流量
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any

from aiohttp import web, WSMsgType

from cereal import messaging
from system.livestream_ws.aggregator import HudAggregator

LOG = logging.getLogger("livestream_ws")

HOST = os.environ.get("LIVESTREAM_WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("LIVESTREAM_WS_PORT", "8090"))

# Web 静态文件目录
WEB_DIST = os.path.join(os.path.dirname(__file__), "web", "dist")

# 视频源：road (qcamera 低码率)
CAMERA_TOPICS: dict[str, str] = {
    "road":   os.environ.get("LIVESTREAM_ROAD_TOPIC",   "qRoadEncodeData"),
}

# 视频客户端积压丢帧阈值：写缓冲 > 1MB 时丢非关键帧
DROP_BUFFER_BYTES = 1 * 1024 * 1024

# 无客户端 5 秒后停止 cereal 订阅（省 CPU）
IDLE_STOP_SEC = 5.0

# HUD 广播频率（Hz）
HUD_RATE_HZ = 10.0

# 视频帧协议：1 字节 tag + NALU
FRAME_HEADER = b"\x01"    # SPS/PPS (avcC extradata)
FRAME_NALU_KEY = b"\x02"  # IDR 关键帧
FRAME_NALU = b"\x03"      # P/B 非关键帧


# ─────────────────────────────────────────────────────────
# 视频广播器：producer / sender 双协程解耦
# ─────────────────────────────────────────────────────────
class VideoBroadcaster:
    QUEUE_MAXSIZE = 4

    def __init__(self, name: str, topic: str):
        self.name = name
        self.topic = topic
        self.clients: set[web.WebSocketResponse] = set()
        self.header: bytes | None = None
        self.header_annexb: bytes | None = None
        self._queue: asyncio.Queue[tuple[bytes, bool]] = asyncio.Queue(maxsize=self.QUEUE_MAXSIZE)
        self._producer: asyncio.Task | None = None
        self._sender: asyncio.Task | None = None
        self._idle_since: float = 0.0
        self._ws_fail: dict[web.WebSocketResponse, int] = {}

    async def ensure_running(self):
        if self._producer is None or self._producer.done():
            self._producer = asyncio.create_task(
                self._producer_loop(), name=f"video_prod_{self.name}")
        if self._sender is None or self._sender.done():
            self._sender = asyncio.create_task(
                self._sender_loop(), name=f"video_send_{self.name}")

    async def register(self, ws: web.WebSocketResponse):
        self.clients.add(ws)
        await self.ensure_running()
        if self.header:
            try:
                await ws.send_bytes(FRAME_HEADER + self.header)
                LOG.info("[%s] sent header %dB to new client", self.name, len(self.header))
            except Exception:
                self.clients.discard(ws)

    def unregister(self, ws: web.WebSocketResponse):
        self.clients.discard(ws)
        self._ws_fail.pop(ws, None)

    @staticmethod
    def _is_h264_keyframe(payload: bytes) -> bool:
        """Check if payload contains an H.264 IDR/keyframe NALU (type 5)."""
        if not payload:
            return False
        n = len(payload)
        i = 0
        while i + 5 < n and i < 128:
            if payload[i] == 0 and payload[i+1] == 0:
                if payload[i+2] == 1:
                    return (payload[i+3] & 0x1F) == 5
                if payload[i+2] == 0 and payload[i+3] == 1:
                    return (payload[i+4] & 0x1F) == 5
            i += 1
        if n >= 8:
            avcc_len = int.from_bytes(payload[:4], 'big')
            if 0 < avcc_len < n - 4 and (payload[4] & 0x1F) == 5:
                return True
        if (payload[0] & 0x1F) == 5:
            return True
        return False

    @staticmethod
    def _header_to_avcc(header: bytes) -> bytes:
        """将原始 H.264 header 转为 avcC 格式（AVCDecoderConfigurationRecord）。"""
        if not header:
            return b""
        if header[0] == 0x01:
            return header
        sps: bytes | None = None
        pps: bytes | None = None
        i = 0
        n = len(header)
        while i + 3 < n:
            if header[i] == 0 and header[i+1] == 0:
                if header[i+2] == 1:
                    start = i
                    nalu_type = header[i+3] & 0x1F
                    i += 3
                elif i + 4 < n and header[i+2] == 0 and header[i+3] == 1:
                    start = i
                    nalu_type = header[i+4] & 0x1F
                    i += 4
                else:
                    i += 1
                    continue
                j = i
                while j < n:
                    if j + 3 < n:
                        if (header[j] == 0 and header[j+1] == 0 and header[j+2] == 1) or \
                           (j + 4 < n and header[j] == 0 and header[j+1] == 0 and header[j+2] == 0 and header[j+3] == 1):
                            break
                    j += 1
                nalu = header[i:j]
                if nalu_type == 7 and sps is None:
                    sps = nalu
                elif nalu_type == 8 and pps is None:
                    pps = nalu
                i = j
            else:
                i += 1
            if sps and pps:
                break
        if not sps:
            nalu_type = header[0] & 0x1F
            if nalu_type == 7:
                sps = header
            elif nalu_type == 8:
                pps = header
            else:
                LOG.warning("_header_to_avcc: no SPS in %dB (type=%d)", len(header), nalu_type)
                return header
        profile = sps[1] if len(sps) > 1 else 0x42
        constraints = sps[2] if len(sps) > 2 else 0x00
        level = sps[3] if len(sps) > 3 else 0x1E
        avcc = bytearray()
        avcc.append(0x01)
        avcc.append(profile)
        avcc.append(constraints)
        avcc.append(level)
        avcc.append(0xFF)
        avcc.append(0xE1)
        avcc.extend(len(sps).to_bytes(2, 'big'))
        avcc.extend(sps)
        pps_data = pps or b""
        avcc.append(0x01)
        avcc.extend(len(pps_data).to_bytes(2, 'big'))
        avcc.extend(pps_data)
        return bytes(avcc)

    async def _producer_loop(self):
        loop = asyncio.get_running_loop()
        sock: Any = None
        while True:
            try:
                if not self.clients:
                    if self._idle_since == 0.0:
                        self._idle_since = time.monotonic()
                    elif time.monotonic() - self._idle_since > IDLE_STOP_SEC:
                        if sock is not None:
                            LOG.info("[%s] idle → stop sub_sock", self.name)
                            sock = None
                        await asyncio.sleep(0.5)
                        continue
                    await asyncio.sleep(0.1)
                    continue
                self._idle_since = 0.0

                if sock is None:
                    sock = messaging.sub_sock(self.topic, conflate=True)
                    LOG.info("[%s] subscribed to %s", self.name, self.topic)

                msg = await loop.run_in_executor(None, messaging.recv_one_or_none, sock)
                if msg is None:
                    await asyncio.sleep(0.005)
                    continue

                evt = getattr(msg, msg.which())
                data = bytes(evt.data or b"")
                header = bytes(evt.header or b"")

                idx = getattr(evt, "idx", None)
                flags = getattr(idx, "flags", 0) if idx is not None else 0
                is_key = bool(flags & 0x8) or self._is_h264_keyframe(data)

                if header and header != self.header_annexb:
                    self.header_annexb = header
                    self.header = self._header_to_avcc(header)
                    if self.clients:
                        hdr_payload = FRAME_HEADER + self.header
                        for ws in list(self.clients):
                            try:
                                await ws.send_bytes(hdr_payload)
                            except Exception:
                                pass
                elif is_key and not header and self.header is None:
                    extracted = self._header_to_avcc(data)
                    if extracted and len(extracted) > 5:
                        self.header = extracted
                        if self.clients:
                            hdr_payload = FRAME_HEADER + self.header
                            for ws in list(self.clients):
                                try:
                                    await ws.send_bytes(hdr_payload)
                                except Exception:
                                    pass

                if self.header is None and len(data) >= 4:
                    extracted = self._header_to_avcc(data)
                    if extracted and len(extracted) > 5:
                        self.header = extracted
                        if self.clients:
                            hdr_payload = FRAME_HEADER + self.header
                            for ws in list(self.clients):
                                try:
                                    await ws.send_bytes(hdr_payload)
                                except Exception:
                                    pass

                if is_key and self.header_annexb:
                    data = self.header_annexb + data

                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                    except Exception:
                        pass
                try:
                    self._queue.put_nowait((data, is_key))
                except Exception:
                    pass
            except asyncio.CancelledError:
                break
            except Exception:
                LOG.exception("[%s] producer error", self.name)
                await asyncio.sleep(0.1)

    async def _sender_loop(self):
        while True:
            try:
                data, is_key = await self._queue.get()
                if not self.clients:
                    continue
                payload = (FRAME_NALU_KEY if is_key else FRAME_NALU) + data
                clients = list(self.clients)
                results = await asyncio.gather(*[
                    self._send_one(ws, payload, is_key) for ws in clients
                ], return_exceptions=True)
                for ws, r in zip(clients, results):
                    if isinstance(r, Exception) or r is False:
                        n = self._ws_fail.get(ws, 0) + 1
                        self._ws_fail[ws] = n
                        if n >= 4:
                            self.clients.discard(ws)
                            self._ws_fail.pop(ws, None)
                            try:
                                await ws.close(code=1011, message=b"send_timeout")
                            except Exception:
                                pass
                    else:
                        self._ws_fail.pop(ws, None)
            except asyncio.CancelledError:
                break
            except Exception:
                LOG.exception("[%s] sender error", self.name)
                await asyncio.sleep(0.05)

    async def _send_one(self, ws: web.WebSocketResponse, payload: bytes, is_key: bool):
        try:
            buf = ws._writer.transport.get_write_buffer_size()
            if buf > DROP_BUFFER_BYTES and not is_key:
                return True
        except Exception:
            pass
        await asyncio.wait_for(ws.send_bytes(payload), timeout=0.35)
        return True


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
async def ws_video(request: web.Request):
    cam = request.query.get("cam", "road")
    if cam not in CAMERA_TOPICS:
        raise web.HTTPNotFound(text=f"unknown camera '{cam}'")
    ws = web.WebSocketResponse(max_msg_size=0, heartbeat=15)
    await ws.prepare(request)
    bc: VideoBroadcaster = request.app["video"][cam]
    await bc.register(ws)
    LOG.info("video[%s] client + (total=%d)", cam, len(bc.clients))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        bc.unregister(ws)
        LOG.info("video[%s] client - (total=%d)", cam, len(bc.clients))
    return ws


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


async def ws_legacy(request: web.Request):
    request = request.clone(rel_url=request.rel_url.with_query({"cam": "road"}))
    return await ws_video(request)


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
        "cameras": {
            cam: {"topic": bc.topic, "clients": len(bc.clients),
                  "has_header": bc.header is not None}
            for cam, bc in app["video"].items()
        },
        "hud": {"clients": len(hud.clients),
                "rate_hz": HUD_RATE_HZ},
    })


def make_app() -> web.Application:
    app = web.Application()
    app["video"] = {cam: VideoBroadcaster(cam, topic)
                    for cam, topic in CAMERA_TOPICS.items()}
    app["hud"] = HudBroadcaster()

    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_legacy)
    app.router.add_get("/ws/video", ws_video)
    app.router.add_get("/ws/data", ws_data)
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
    LOG.info("cameras: %s", CAMERA_TOPICS)
    LOG.info("hud rate: %.1fHz, frontend: %s", HUD_RATE_HZ, WEB_DIST)
    web.run_app(make_app(), host=HOST, port=PORT, access_log=None)


if __name__ == "__main__":
    main()
