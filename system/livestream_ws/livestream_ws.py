#!/usr/bin/env python3
"""
Livestream WebSocket Server —— 局域网低占用实时投屏 + 车辆 HUD 数据

订阅 qRoadEncodeData（qcamera 526x330 @ 256kbps H.264, encoderd 常驻输出，
零额外编码开销），通过 WebSocket 二进制帧原样推送 H.264 NALU 给
浏览器/手机 App，客户端用 WebCodecs / MediaCodec 硬解显示。

同时提供第二路 /ws/data 中继车辆状态（car/self/radar/model/…）作为
HUD 叠加数据。服务端做字段筛选 + 10Hz 降频，避免浏览器带宽/CPU 压力。

监听：0.0.0.0:8090
端点：
    GET  /                → 前端全屏 <canvas> 视频 + HUD 叠加层
    GET  /ws/video?cam=X  → WebSocket 视频流 (只支持 cam=road, 默认 road)
    GET  /ws/data         → WebSocket 车辆状态 JSON 流 (10Hz)
    GET  /health          → JSON 健康检查
    # 向后兼容旧路径
    GET  /ws              → 等价 /ws/video?cam=road

设计要点：
- 单一订阅循环 + 多客户端广播（多观众共享一路 cereal sub_sock）
- Producer / Sender 双协程解耦，慢客户端不拖累其他人
- conflate=True：cereal 只保留最新一帧，无观众时休眠
- IDLE_STOP：无客户端 5 秒后关闭订阅，恢复零 CPU
- 视频客户端 backpressure：写缓冲 > 1MB 时丢非关键帧
- HUD 服务端抽字段 + 10Hz 降频 → 约 4 KB/s 带宽，<0.5% CPU
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any, Callable

from aiohttp import web, WSMsgType

from cereal import messaging

LOG = logging.getLogger("livestream_ws")

HOST = os.environ.get("LIVESTREAM_WS_HOST", "0.0.0.0")
PORT = int(os.environ.get("LIVESTREAM_WS_PORT", "8090"))

# 视频源：road (qcamera 低码率)
CAMERA_TOPICS: dict[str, str] = {
    "road":   os.environ.get("LIVESTREAM_ROAD_TOPIC",   "qRoadEncodeData"),
}

# 视频客户端积压丢帧阈值：写缓冲 > 1MB 时丢非关键帧
DROP_BUFFER_BYTES = 1 * 1024 * 1024

# 无客户端 5 秒后停止 cereal 订阅（省 CPU）
IDLE_STOP_SEC = 5.0

# HUD 广播频率（Hz），人眼看仪表 10Hz 够用
HUD_RATE_HZ = 10.0

# 视频帧协议：1 字节 tag + NALU
FRAME_HEADER = b"\x01"    # SPS/PPS (avcC extradata)
FRAME_NALU_KEY = b"\x02"  # IDR 关键帧
FRAME_NALU = b"\x03"      # P/B 非关键帧


# ─────────────────────────────────────────────────────────
# 前端页面（video + HUD 叠加）
# ─────────────────────────────────────────────────────────
INDEX_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><meta name="theme-color" content="#eef1f6"><title>C3 仪表盘</title>
<style>
  :root{
    --bg:#eef1f6; --card:#ffffff; --card2:#f4f6fa; --line:#dde2ea;
    --txt:#1a2030; --dim:#6b7385; --accent:#2563eb; --green:#16a34a;
    --amber:#d97706; --red:#dc2626; --track:#e3e7ee;
    color-scheme:light;
  }
  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
  html,body{margin:0;min-height:100%;background:var(--bg);color:var(--txt);
            font-family:-apple-system,system-ui,"PingFang SC","Microsoft YaHei",sans-serif;
            overscroll-behavior:none}
  body{padding:env(safe-area-inset-top) 0 env(safe-area-inset-bottom)}

  /* ═══ 仪表盘视图 ═══ */
  #dash{padding:14px 14px 90px;max-width:640px;margin:0 auto}

  /* 顶栏 */
  #topbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
  #brand{font-size:24px;font-weight:800;letter-spacing:.5px}
  #brand small{font-size:14px;color:var(--dim);font-weight:500;margin-left:6px}
  #opState{padding:9px 18px;border-radius:999px;font-size:17px;font-weight:800;
           background:var(--card2);color:var(--dim);border:1px solid var(--line)}
  #opState.engaged{background:rgba(22,163,74,.14);color:var(--green);border-color:rgba(22,163,74,.4)}
  #opState.override{background:rgba(37,99,235,.14);color:var(--accent);border-color:rgba(37,99,235,.4)}
  #opState.warn{background:rgba(217,119,6,.14);color:var(--amber);border-color:rgba(217,119,6,.4)}

  /* ★ 提醒功能（最重要，常驻显示） */
  #alert{margin-bottom:14px;padding:18px 20px;border-radius:18px;position:relative;overflow:hidden;
         background:var(--card2);border:1px solid var(--line);transition:background .2s,border-color .2s;
         box-shadow:0 2px 12px rgba(30,40,70,.06)}
  #alert .ah{font-size:14px;font-weight:800;letter-spacing:1px;color:var(--dim);text-transform:uppercase;margin-bottom:8px}
  #alert .a1{font-size:30px;font-weight:800;line-height:1.2}
  #alert .a2{font-size:19px;font-weight:600;color:var(--dim);margin-top:6px;line-height:1.3}
  #alert.idle .a1{color:var(--dim);font-weight:700}
  #alert.info{background:rgba(37,99,235,.1);border-color:rgba(37,99,235,.4)}
  #alert.info .a1{color:#1d4ed8}
  #alert.warning{background:rgba(217,119,6,.12);border-color:rgba(217,119,6,.45)}
  #alert.warning .a1{color:#b45309}
  #alert.severe{background:rgba(220,38,38,.12);border-color:rgba(220,38,38,.55);animation:pulseA 1s infinite}
  #alert.severe .a1{color:#b91c1c}
  #alert.severe .ah{color:#b91c1c}
  @keyframes pulseA{0%,100%{box-shadow:0 0 0 0 rgba(220,38,38,.4)}50%{box-shadow:0 0 0 6px rgba(220,38,38,0)}}

  /* 校准状态卡 */
  #calCard{margin-bottom:14px;padding:16px 18px;border-radius:18px;background:var(--card);border:1px solid var(--line);
           box-shadow:0 2px 12px rgba(30,40,70,.06)}
  #calCard .calTop{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
  #calCard .calTop .k{font-size:17px;color:var(--dim);font-weight:700}
  #calCard .calTop .v{font-size:20px;font-weight:800}
  #calCard.done .calTop .v{color:var(--green)}
  #calCard.progress .calTop .v{color:var(--amber)}
  #calCard.invalid .calTop .v{color:var(--red)}
  #calCard .calBar{height:10px;background:var(--track);border-radius:5px;overflow:hidden}
  #calCard .calBar>i{display:block;height:100%;width:0;border-radius:5px;background:var(--amber);transition:width .3s}
  #calCard.done .calBar>i{background:var(--green)}
  #calCard .calPct{text-align:right;font-size:15px;color:var(--dim);margin-top:8px;font-variant-numeric:tabular-nums;font-weight:600}
  #calCard .calAim{margin-top:10px;padding-top:10px;border-top:1px solid var(--line);font-size:16px;font-weight:600;color:var(--txt)}

  /* 主速度卡 */
  #speedCard{background:linear-gradient(160deg,var(--card),var(--card2));border:1px solid var(--line);
             border-radius:24px;padding:26px 20px;text-align:center;margin-bottom:14px;position:relative;
             box-shadow:0 2px 12px rgba(30,40,70,.06)}
  #speedCard .spd{font-size:108px;font-weight:800;line-height:.92;letter-spacing:-3px}
  #speedCard .unit{font-size:24px;color:var(--dim);font-weight:700;margin-top:4px}
  #speedCard .sigs{position:absolute;top:20px;left:0;right:0;display:flex;justify-content:center;gap:44px;font-size:40px}
  #speedCard .sig{color:var(--track);transition:color .15s}
  #speedCard .sig.on{color:var(--green);text-shadow:0 0 12px rgba(22,163,74,.5)}
  #speedCard .gear{position:absolute;top:18px;right:22px;font-size:36px;font-weight:800;color:var(--dim)}
  #speedCard .cruise{margin-top:16px;display:inline-flex;align-items:center;gap:10px;
                     padding:10px 22px;border-radius:999px;background:var(--card2);border:1px solid var(--line);font-size:19px;font-weight:700}
  #speedCard .cruise .dot{width:12px;height:12px;border-radius:50%;background:var(--track)}
  #speedCard .cruise.on .dot{background:var(--green);box-shadow:0 0 8px var(--green)}
  #speedCard .cruise .setv{font-weight:800;color:var(--amber)}

  /* 参数网格 */
  #grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
  .cell{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px 12px;text-align:center;
        box-shadow:0 2px 12px rgba(30,40,70,.06)}
  .cell .k{font-size:15px;color:var(--dim);font-weight:700;margin-bottom:8px}
  .cell .v{font-size:32px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums}
  .cell .v small{font-size:16px;color:var(--dim);font-weight:600;margin-left:2px}
  .cell.brakeOn .v{color:var(--red)}
  .cell .bar{margin-top:10px;height:8px;background:var(--track);border-radius:4px;overflow:hidden}
  .cell .bar>i{display:block;height:100%;background:var(--green);border-radius:4px;width:0;transition:width .2s}

  /* 设备状态卡 */
  #sys{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px 18px;margin-bottom:12px;
       box-shadow:0 2px 12px rgba(30,40,70,.06)}
  #sys .row{display:flex;justify-content:space-between;align-items:center;padding:9px 0;
            border-bottom:1px solid var(--line);font-size:18px}
  #sys .row:last-child{border:none}
  #sys .row .k{color:var(--dim);font-weight:600}
  #sys .row .v{font-weight:800;font-variant-numeric:tabular-nums}

  /* 底部操作按钮 */
  #actions{position:fixed;left:0;right:0;bottom:0;padding:12px 14px calc(12px + env(safe-area-inset-bottom));
           display:flex;gap:10px;max-width:640px;margin:0 auto;
           background:linear-gradient(to top,var(--bg) 55%,transparent);z-index:20}
  #actions button{flex:1;padding:18px;border-radius:16px;border:1px solid var(--line);
                  background:var(--card);color:var(--txt);font-size:20px;font-weight:800;cursor:pointer}
  #camBtn{background:var(--accent);border-color:var(--accent);color:#fff}
  #diagBtn.badge{background:var(--red);border-color:var(--red);color:#fff}

  /* ═══ 摄像头全屏视图 ═══ */
  #camView{position:fixed;inset:0;background:#000;z-index:50;display:none}
  #camView.show{display:block}
  canvas#v{width:100%;height:100%;object-fit:contain;display:block;background:#000}
  video#vMse{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;display:none}
  #camClose{position:fixed;top:calc(14px + env(safe-area-inset-top));right:14px;z-index:60;
            width:46px;height:46px;border-radius:50%;border:none;background:rgba(0,0,0,.55);
            color:#fff;font-size:24px;cursor:pointer;backdrop-filter:blur(4px)}
  #camStatus{position:fixed;left:14px;bottom:calc(14px + env(safe-area-inset-bottom));z-index:60;
             padding:6px 12px;border-radius:8px;background:rgba(0,0,0,.55);font-size:13px;
             font-family:monospace;backdrop-filter:blur(4px)}
  #camStatus.err{background:rgba(239,68,68,.7)}
  /* 摄像头上的最小 HUD */
  #camHud{position:fixed;left:14px;bottom:calc(50px + env(safe-area-inset-bottom));z-index:55;
          font-weight:800;text-shadow:0 2px 6px #000;pointer-events:none}
  #camHud .cs{font-size:56px;line-height:1}
  #camHud .cu{font-size:18px;color:#ccc}

  /* ═══ 诊断弹层 ═══ */
  #panel{position:fixed;inset:0;background:rgba(20,28,45,.35);z-index:70;display:none;
         backdrop-filter:blur(3px)}
  #panel.show{display:block}
  #panelSheet{position:absolute;left:0;right:0;bottom:0;max-height:80vh;overflow:auto;
              background:var(--card);border-radius:20px 20px 0 0;padding:18px 16px calc(18px + env(safe-area-inset-bottom));
              box-shadow:0 -4px 24px rgba(30,40,70,.15)}
  #panelSheet .grab{width:44px;height:5px;border-radius:3px;background:var(--track);margin:0 auto 14px}
  #panelSheet h4{margin:16px 0 8px;color:var(--amber);font-size:19px;font-weight:800}
  #panelSheet h4:first-of-type{margin-top:0}
  #panelSheet .row{display:flex;justify-content:space-between;padding:9px 0;
                   border-bottom:1px solid var(--line);font-size:17px;line-height:1.4}
  #panelSheet .row:last-child{border:none}
  #panelSheet .sev0{color:var(--txt)} #panelSheet .sev1{color:var(--amber)}
  #panelSheet .sev2{color:#ea580c} #panelSheet .sev3{color:var(--red);font-weight:700}
  #panelSheet .procBad{color:var(--red)} #panelSheet .procRestart{color:var(--amber)}
  #panelSheet .hint{color:var(--dim);font-size:16px;padding:6px 0}
  #panelSheet .ok{color:var(--green)}
</style></head><body>

<!-- ═══ 仪表盘（默认视图，不占视频资源） ═══ -->
<div id="dash">
  <div id="topbar">
    <div id="brand">C3 <small>仪表盘</small></div>
    <div id="opState">未连接</div>
  </div>

  <!-- ★ 提醒功能：最重要，常驻显示 ★ -->
  <div id="alert" class="idle">
    <div class="ah">系统提醒</div>
    <div class="a1" id="alert1">等待连接…</div>
    <div class="a2" id="alert2"></div>
  </div>

  <div id="speedCard">
    <div class="sigs"><span id="blLeft" class="sig">◀</span><span id="blRight" class="sig">▶</span></div>
    <div class="gear" id="gearG">--</div>
    <div class="spd" id="spdN">--</div>
    <div class="unit">km/h</div>
    <div class="cruise" id="cruiseBox"><span class="dot"></span>CRUISE <span class="setv" id="cruiseSet">--</span></div>
  </div>

  <div id="grid">
    <div class="cell"><div class="k">转向角</div><div class="v" id="steerVal">--<small>°</small></div></div>
    <div class="cell" id="gasCell"><div class="k">油门</div><div class="v" id="gasVal">--<small>%</small></div>
         <div class="bar"><i id="gasFill"></i></div></div>
    <div class="cell" id="brakeCell"><div class="k">刹车</div><div class="v" id="brakeVal">OFF</div></div>
    <div class="cell"><div class="k">前车距离</div><div class="v" id="leadD">--<small>m</small></div></div>
    <div class="cell"><div class="k">相对速度</div><div class="v" id="leadV">--</div></div>
    <div class="cell"><div class="k">加速度</div><div class="v" id="accEl">--</div></div>
  </div>

  <div id="sys">
    <div class="row"><span class="k">CPU 温度</span><span class="v" id="sCpu">--</span></div>
    <div class="row"><span class="k">内存 / 存储</span><span class="v" id="sMem">--</span></div>
    <div class="row"><span class="k">网络</span><span class="v" id="sNet">--</span></div>
    <div class="row"><span class="k">规划 a* / v*</span><span class="v" id="sPlan">--</span></div>
  </div>

  <!-- 摄像头校准状态卡（与系统设置同源：liveCalibration） -->
  <div id="calCard">
    <div class="calTop"><span class="k">摄像头校准</span><span class="v" id="calStatus">--</span></div>
    <div class="calBar"><i id="calFill"></i></div>
    <div class="calPct" id="calPct">--</div>
    <div class="calAim" id="calAim">设备指向：--</div>
  </div>
</div>

<div id="actions">
  <button id="camBtn">📷 摄像头</button>
  <button id="diagBtn">⚙ 诊断</button>
</div>

<!-- ═══ 摄像头全屏（点击后才激活视频流） ═══ -->
<div id="camView">
  <canvas id="v"></canvas>
  <video id="vMse" muted playsinline></video>
  <div id="camHud"><span class="cs" id="camSpd">--</span><span class="cu"> km/h</span></div>
</div>
<button id="camClose" style="display:none">✕</button>
<div id="camStatus" style="display:none">connecting...</div>

<!-- ═══ 诊断底部弹层 ═══ -->
<div id="panel">
  <div id="panelSheet">
    <div class="grab"></div>
    <h4 id="evtTitle">事件 (0)</h4>
    <div id="evtList" class="hint">— 无事件 —</div>
    <h4 id="procTitle">进程</h4>
    <div id="procList" class="hint">等待 managerState...</div>
  </div>
</div>
<script>
(() => {
  const $ = id => document.getElementById(id);
  const canvas = $('v'), ctx = canvas.getContext('2d');
  const status = $('camStatus');

  let decoder = null, configured = false;
  let frames = 0;
  let camActive = false;   // 摄像头视图是否打开（决定是否连接视频流）

  // 视频路径：WebCodecs 优先 → MSE 降级
  const hasWC = 'VideoDecoder' in window;
  const hasMSE = 'MediaSource' in window;
  let useMSE = !hasWC && hasMSE;
  const videoSupported = hasWC || hasMSE;
  if (useMSE) { canvas.style.display = 'none'; $('vMse').style.display = 'block'; }

  // ─── 最小 fMP4 复用器（MSE 降级路） ─────
  const TS = 90000;
  let mseSeq = 1, mseSrc = null, mseBuf = null, mseReady = false;
  function u32(v) { const b = new Uint8Array(4); new DataView(b.buffer).setUint32(0, v); return b; }
  function u16(v) { const b = new Uint8Array(2); new DataView(b.buffer).setUint16(0, v); return b; }
  function box(t, ...parts) {
    let l = 8; for (const p of parts) l += p.length;
    const b = new Uint8Array(l), v = new DataView(b.buffer);
    v.setUint32(0, l); for (let i = 0; i < 4; i++) b[4+i] = t.charCodeAt(i);
    let o = 8; for (const p of parts) { b.set(p, o); o += p.length; } return b;
  }
  function fbox(t, ver, flg, ...parts) {
    return box(t, new Uint8Array([ver, flg>>16&255, flg>>8&255, flg&255]), ...parts);
  }
  function str4(s) { return new Uint8Array(s.split('').map(c => c.charCodeAt(0))); }
  function concat(...aa) {
    let t = 0; for (const a of aa) t += a.length;
    const r = new Uint8Array(t); let o = 0;
    for (const a of aa) { r.set(a, o); o += a.length; } return r;
  }

  function mseInit(avcc, codec) {
    const ftyp = box('ftyp', str4('isom'), u32(1), str4('isom'), str4('avc1'));
    const mvhd = fbox('mvhd', 0, 0, u32(0), u32(0), u32(TS), u32(0),
      u32(0x00010000), u16(0x0100), new Uint8Array(10), new Uint8Array(36),
      new Uint8Array(24), u32(2));
    const tkhd = fbox('tkhd', 0, 0x07, u32(0), u32(0), u32(1), u32(0), u32(0),
      u32(0), u32(0), u16(0), u16(0), u16(0x0100), new Uint8Array(10),
      new Uint8Array(36), u32(640<<16), u32(480<<16));
    const mdhd = fbox('mdhd', 0, 0, u32(0), u32(0), u32(TS), u32(0), u16(0x55c4));
    const hdlr = fbox('hdlr', 0, 0, u32(0), str4('vide'), u32(0), u32(0), u32(0));
    const vmhd = fbox('vmhd', 0, 1, u16(0), u16(0));
    const dref = fbox('dref', 0, 0, u32(1), fbox('url ', 0, 1));
    const avcCBox = box('avcC', avcc);
    const avc1Body = concat(new Uint8Array(6), u16(1), u16(0), u16(0), u32(0), u32(0),
      u16(640), u16(480), u32(0x00480000), u32(0x00480000), u32(0), u16(1),
      new Uint8Array(32), u16(0x0018), u16(0xffff));
    const stsd = fbox('stsd', 0, 0, u32(1), box('avc1', avc1Body, avcCBox));
    const e0 = u32(0);
    const stbl = box('stbl', stsd, fbox('stts',0,0,e0), fbox('stsc',0,0,e0),
      fbox('stsz',0,0,u32(0),e0), fbox('stco',0,0,e0));
    const moov = box('moov', mvhd,
      box('trak', tkhd, box('mdia', mdhd, hdlr, box('minf', vmhd, box('dinf', dref), stbl))));

    mseSrc = new MediaSource();
    $('vMse').src = URL.createObjectURL(mseSrc);
    mseSrc.addEventListener('sourceopen', () => {
      try {
        mseBuf = mseSrc.addSourceBuffer('video/mp4; codecs="' + codec + '"');
        mseBuf.appendBuffer(concat(ftyp, moov));
        mseReady = true; configured = true;
      } catch (e) { status.textContent = 'MSE: ' + e.message + ' codec=' + codec; }
    });
  }

  function mseAppend(nalu, ptsUs, isKey) {
    if (!mseReady || !mseBuf) return;
    const dur = TS / 30;
    const dTime = (ptsUs / 1e6 * TS) | 0;
    const mfhd = fbox('mfhd', 0, 0, u32(mseSeq++));
    const tfhd = fbox('tfhd', 0, 0x020000, u32(1));
    const tfdt8 = new Uint8Array(8); const tdv = new DataView(tfdt8.buffer);
    tdv.setUint32(0, dTime / 0x100000000); tdv.setUint32(4, dTime);
    const tfdt = fbox('tfdt', 1, 0, tfdt8);
    const trun = fbox('trun', 0, 0x000301, u32(1), u32(0), u32(dur),
      u32(nalu.length), u32(isKey ? 0x02000000 : 0x01010000), u32(0));
    const moof = box('moof', mfhd, box('traf', tfhd, tfdt, trun));
    const mdat = box('mdat', nalu);
    try { mseBuf.appendBuffer(concat(moof, mdat)); } catch (e) {}
  }

  // ─── 视频通道（按需连接） ─────────────────
  let videoWs = null, hdrTimer = null;
  function onFrame() {
    frames++;
    if (frames === 1) {
      status.textContent = 'road';
      status.classList.remove('err');
    }
  }
  function initDecoder(desc) {
    // 从 avcC extradata 解析实际 codec 字符串；若 desc 无效则用默认值
    let codec;
    if (desc && desc.length >= 4) {
      const profile = desc[1].toString(16).padStart(2, '0');
      const constraints = desc[2].toString(16).padStart(2, '0');
      const level = desc[3].toString(16).padStart(2, '0');
      codec = 'avc1.' + profile + constraints + level;
    } else {
      codec = 'avc1.640032'; // 默认 High Profile Level 5.0
    }
    if (configured && decoder && decoder.state === 'configured') return;
    status.textContent = 'codec: ' + codec;

    if (useMSE) { mseInit(desc, codec); return; }
    if (decoder) try { decoder.close(); } catch (e) {}
    decoder = new VideoDecoder({
      output: frame => {
        if (canvas.width !== frame.displayWidth) {
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
        }
        ctx.drawImage(frame, 0, 0); frame.close(); onFrame();
      },
      error: e => { status.textContent = '解码错误: ' + e.message + ' codec=' + codec; configured = false; }
    });
    // 注意：不传 description（avcC），因为服务端发的 NALU 是 Annex-B 格式
    decoder.configure({ codec: codec, optimizeForLatency: true });
    configured = true;
  }
  function connectVideo() {
    if (videoWs) { try { videoWs.close(); } catch (e) {} }
    configured = false; frames = 0; mseReady = false;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    videoWs = new WebSocket(proto + '//' + location.host + '/ws/video?cam=road');
    videoWs.binaryType = 'arraybuffer';
    hdrTimer = setTimeout(() => {
      if (!configured) { status.textContent = 'no header, using default codec'; initDecoder(null); }
    }, 2000);
    videoWs.onopen = () => { status.textContent = 'waiting...'; };
    videoWs.onclose = () => {
      clearTimeout(hdrTimer);
      if (!camActive) return;   // 已关闭摄像头视图，不重连
      status.classList.add('err');
      status.textContent = 'disconnected, retry...';
      setTimeout(() => { if (camActive) connectVideo(); }, 1000);
    };
    videoWs.onmessage = e => {
      const buf = new Uint8Array(e.data);
      const tag = buf[0], payload = buf.subarray(1);
      if (tag === 1) { clearTimeout(hdrTimer); initDecoder(payload); }
      else if (configured) {
        if (useMSE) { mseAppend(payload, performance.now() * 1000, tag === 2); onFrame(); }
        else {
          try { decoder.decode(new EncodedVideoChunk({
            type: tag === 2 ? 'key' : 'delta',
            timestamp: performance.now() * 1000,
            data: payload,
          })); } catch (e) {}
        }
      }
    };
  }
  function stopVideo() {
    if (hdrTimer) clearTimeout(hdrTimer);
    if (videoWs) { try { videoWs.close(); } catch (e) {} videoWs = null; }
    if (decoder) { try { decoder.close(); } catch (e) {} decoder = null; }
    configured = false; frames = 0;
    if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
  function openCam() {
    if (!videoSupported) { alert('浏览器不支持视频解码，需 Chrome 94+ / Safari 16.4+'); return; }
    camActive = true;
    $('camView').classList.add('show');
    $('camClose').style.display = 'block';
    $('camStatus').style.display = 'block';
    status.textContent = 'connecting...';
    status.classList.remove('err');
    connectVideo();
  }
  function closeCam() {
    camActive = false;
    stopVideo();
    $('camView').classList.remove('show');
    $('camClose').style.display = 'none';
    $('camStatus').style.display = 'none';
  }

  // ─── 数据通道 (HUD) ─────────────────────
  let dataWs = null;
  const alertBox = $('alert');
  function fmtNum(x, digits=0) {
    if (x === null || x === undefined || isNaN(x)) return '--';
    return Number(x).toFixed(digits);
  }
  function connectData() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    dataWs = new WebSocket(proto + '//' + location.host + '/ws/data');
    dataWs.onclose = () => setTimeout(connectData, 1500);
    dataWs.onmessage = e => {
      let m; try { m = JSON.parse(e.data); } catch (err) { return; }
      // carState
      if (m.car) {
        $('spdN').textContent = fmtNum(m.car.vKph, 0);
        $('camSpd').textContent = fmtNum(m.car.vKph, 0);
        $('gearG').textContent = m.car.gear || '--';
        $('blLeft').classList.toggle('on', !!m.car.blinkerL);
        $('blRight').classList.toggle('on', !!m.car.blinkerR);
        // 转向角
        $('steerVal').innerHTML = fmtNum(m.car.steer, 1) + '<small>°</small>';
        // 油门
        const gas = m.car.gas;
        if (gas !== null && gas !== undefined && !isNaN(gas)) {
          $('gasVal').innerHTML = fmtNum(gas * 100, 0) + '<small>%</small>';
          $('gasFill').style.width = Math.min(gas * 100, 100) + '%';
        }
        // 刹车
        $('brakeVal').textContent = m.car.brake ? 'ON' : 'OFF';
        $('brakeCell').classList.toggle('brakeOn', !!m.car.brake);
        // 加速度
        $('accEl').innerHTML = (m.car.aEgo != null ? (m.car.aEgo >= 0 ? '+' : '') + fmtNum(m.car.aEgo, 1) : '--') + '<small>m/s²</small>';
        // 巡航
        const cb = $('cruiseBox');
        if (m.car.cruise) {
          cb.classList.add('on');
          $('cruiseSet').textContent = fmtNum(m.car.cruiseSet, 0) + ' km/h';
        } else {
          cb.classList.remove('on');
          $('cruiseSet').textContent = '--';
        }
      }
      // radarState (前车)
      if (m.lead) {
        if (m.lead.hasLead) {
          $('leadD').innerHTML = fmtNum(m.lead.dRel, 0) + '<small>m</small>';
          const dv = m.lead.vRel;
          $('leadV').innerHTML = (dv >= 0 ? '+' : '') + fmtNum(dv * 3.6, 0) + '<small>km/h</small>';
        } else {
          $('leadD').innerHTML = '--<small>m</small>';
          $('leadV').textContent = '--';
        }
      }
      // selfdriveState (★ 提醒功能 + OP 状态) —— 常驻显示，不隐藏
      if (m.self) {
        const t1 = m.self.alert1 || '', t2 = m.self.alert2 || '';
        const stat = m.self.alertStatus || '';
        if (t1 || t2) {
          alertBox.className = stat;
          $('alert1').textContent = t1 || t2;
          $('alert2').textContent = t1 ? t2 : '';
        } else if (m.events && m.events.count > 0) {
          // 未上路 / 无 alertText 时，回退显示最严重的活跃事件
          const ev = m.events.list[0];  // 已按严重程度降序排列
          const sev = ev.severity || 0;
          alertBox.className = sev >= 2 ? 'severe' : sev === 1 ? 'warning' : 'info';
          $('alert1').textContent = ev.name;
          const tag = ev.immediateDisable ? '立即禁用' : ev.softDisable ? '软禁用'
                    : ev.warning ? '告警' : ev.noEntry ? '阻止启用'
                    : ev.permanent ? '常驻提示' : '';
          $('alert2').textContent = (m.events.count > 1 ? '等 ' + m.events.count + ' 条事件' : '')
                                    + (tag ? (m.events.count > 1 ? ' · ' : '') + tag : '');
        } else {
          // 无告警、无事件时显示当前驾驶状态
          alertBox.className = m.self.enabled ? 'info' : 'idle';
          $('alert1').textContent = m.self.active ? 'openpilot 已接管'
                                   : m.self.enabled ? 'openpilot 待命中'
                                   : '系统正常 · 无提醒';
          $('alert2').textContent = '';
        }
        // OP 驾驶状态徽章
        const os = $('opState');
        if (m.self.active) { os.textContent = '已接管'; os.className = 'engaged'; }
        else if (m.self.enabled) { os.textContent = '待命'; os.className = 'override'; }
        else { os.textContent = '未激活'; os.className = ''; }
      }
      // liveCalibration → 校准状态卡
      if (m.cal) {
        const st = m.cal.calStatus || 'unknown';
        const perc = m.cal.calPerc != null ? m.cal.calPerc : 0;
        const map = {calibrated: ['已校准', 'done'], uncalibrated: ['校准中', 'progress'],
                     recalibrating: ['重新校准', 'progress'], invalid: ['校准无效', 'invalid']};
        const [label, cls] = map[st] || [st, 'progress'];
        $('calStatus').textContent = label + (cls === 'done' ? '' : '  ' + perc + '%');
        $('calFill').style.width = Math.min(Math.max(perc, cls === 'done' ? 100 : perc), 100) + '%';
        $('calPct').textContent = cls === 'done' ? '✓ 校准完成' : '校准进度 ' + perc + '%';
        $('calCard').className = cls;
        // 设备指向角度（与系统设置一致：pitch>0=下,yaw>0=左，弧度转角度）
        const rpy = m.cal.rpy;
        if (st !== 'uncalibrated' && rpy && rpy.length >= 3) {
          const pitch = rpy[1] * 180 / Math.PI, yaw = rpy[2] * 180 / Math.PI;
          $('calAim').textContent = '设备指向：' + Math.abs(pitch).toFixed(1) + '° ' + (pitch > 0 ? '下' : '上')
                                    + ' · ' + Math.abs(yaw).toFixed(1) + '° ' + (yaw > 0 ? '左' : '右');
        } else {
          $('calAim').textContent = '设备指向：--';
        }
      }
      // deviceState + longitudinalPlan → 设备状态卡
      if (m.dev) {
        $('sCpu').textContent = fmtNum(m.dev.cpuTempC, 0) + ' °C';
        $('sMem').textContent = fmtNum(m.dev.memPct, 0) + '%  /  ' + fmtNum(m.dev.freeGB, 1) + ' G';
        $('sNet').textContent = m.dev.networkType || '--';
      }
      if (m.plan) $('sPlan').textContent = fmtNum(m.plan.aTarget, 2) + '  /  ' + fmtNum((m.plan.vTarget||0)*3.6, 0) + ' km/h';

      // ── onroadEvents 面板 ──
      if (m.events) {
        const n = m.events.count || 0;
        $('evtTitle').textContent = '事件 (' + n + ')';
        if (!n) {
          $('evtList').innerHTML = '<div class="hint">— 无事件 —</div>';
        } else {
          $('evtList').innerHTML = m.events.list.map(e => {
            const flags = [];
            if (e.immediateDisable) flags.push('❌立即禁用');
            else if (e.softDisable) flags.push('⚠软禁用');
            else if (e.warning) flags.push('⚠告警');
            else if (e.noEntry) flags.push('⛔阻止启用');
            else if (e.permanent) flags.push('ℹ常驻');
            return '<div class="row sev' + (e.severity||0) + '"><span>' + e.name +
                   '</span><span>' + flags.join(' ') + '</span></div>';
          }).join('');
        }
        // 有严重事件时红色徽章
        const bad = m.events.list.some(e => (e.severity||0) >= 2);
        $('diagBtn').classList.toggle('badge', bad || (m.procs && m.procs.unhealthy.length));
      }
      // ── managerState 面板 ──
      if (m.procs) {
        const bad = m.procs.unhealthy || [];
        $('procTitle').textContent = '进程 (' + (m.procs.healthy||0) + '/' + (m.procs.total||0) + ')';
        if (!bad.length) {
          $('procList').innerHTML = '<div class="hint ok">✅ 全部健康</div>';
        } else {
          $('procList').innerHTML = bad.map(p => {
            const st = p.running ? (p.shouldBeRunning ? 'ok' : '⚠不应运行')
                          : (p.shouldBeRunning ? '❌未运行' : 'ok');
            const cls = p.exitCode !== 0 ? 'procBad' : 'procRestart';
            const ec = p.exitCode !== 0 ? ' exit=' + p.exitCode : '';
            return '<div class="row ' + cls + '"><span>' + p.name +
                   '</span><span>' + st + ec + '</span></div>';
          }).join('');
        }
      }
    };
  }

  // ─── 交互绑定 ───────────────────────────
  const panel = $('panel');
  $('diagBtn').onclick = () => panel.classList.add('show');
  panel.onclick = e => { if (e.target === panel) panel.classList.remove('show'); };
  $('camBtn').onclick = openCam;
  $('camClose').onclick = closeCam;

  connectData();
})();
</script></body></html>
"""


# ─────────────────────────────────────────────────────────
# 视频广播器：producer / sender 双协程解耦
# ─────────────────────────────────────────────────────────
class VideoBroadcaster:
    QUEUE_MAXSIZE = 4  # 视频用小队列，超过就丢旧帧

    def __init__(self, name: str, topic: str):
        self.name = name
        self.topic = topic
        self.clients: set[web.WebSocketResponse] = set()
        self.header: bytes | None = None       # avcC 格式
        self.header_annexb: bytes | None = None  # 原始 Annex‑B 格式（拼接用）
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
        """Check if payload contains an H.264 IDR/keyframe NALU (type 5).

        同时支持三种格式：
        - Annex-B (起始码 00 00 01 / 00 00 00 01)
        - AVCC (4 字节长度前缀)
        - 裸 NALU (没有起始码，直接以 NALU type 开始)
        """
        if not payload:
            return False
        # 1) Annex-B: 扫描 00 00 01 / 00 00 00 01
        n = len(payload)
        i = 0
        while i + 5 < n and i < 128:
            if payload[i] == 0 and payload[i+1] == 0:
                if payload[i+2] == 1:
                    return (payload[i+3] & 0x1F) == 5
                if payload[i+2] == 0 and payload[i+3] == 1:
                    return (payload[i+4] & 0x1F) == 5
            i += 1
        # 2) AVCC 格式: 前 4 字节是 NALU 长度
        if n >= 8:
            avcc_len = int.from_bytes(payload[:4], 'big')
            if 0 < avcc_len < n - 4 and (payload[4] & 0x1F) == 5:
                return True
        # 3) 裸 NALU: 第一个字节就是 NALU type
        if (payload[0] & 0x1F) == 5:
            return True
        return False

    @staticmethod
    def _header_to_avcc(header: bytes) -> bytes:
        """将原始 H.264 header 转为 avcC 格式（AVCDecoderConfigurationRecord）。

        支持输入格式：
        - Annex-B (含 00 00 01 / 00 00 00 01 起始码)
        - 裸 NALU (无起始码，首字节即 NALU type)
        - 已经是 avcC 格式（首字节 0x01）
        """
        if not header:
            return b""
        if header[0] == 0x01:
            return header  # 已经是 avcC 格式
        # 从 Annex-B 中提取 SPS/PPS
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
                # 找下一个 NALU 或尾部
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
        # 如果 Annex-B 扫描没找到，尝试当作裸 NALU（首字节即 type）
        if not sps:
            nalu_type = header[0] & 0x1F
            if nalu_type == 7:
                sps = header
                LOG.info("_header_to_avcc: treated header as bare SPS NALU (%dB)", len(sps))
            elif nalu_type == 8:
                pps = header
                LOG.info("_header_to_avcc: treated header as bare PPS NALU (%dB)", len(pps))
            else:
                LOG.warning("_header_to_avcc: no SPS found in %dB header (type=%d)", len(header), nalu_type)
                return header
        # 从 SPS 提取 profile/constraints/level
        profile = sps[1] if len(sps) > 1 else 0x42
        constraints = sps[2] if len(sps) > 2 else 0x00
        level = sps[3] if len(sps) > 3 else 0x1E
        avcc = bytearray()
        avcc.append(0x01)  # version
        avcc.append(profile)
        avcc.append(constraints)
        avcc.append(level)
        avcc.append(0xFF)  # 6 bits reserved(0x3f) + 2 bits lengthSizeMinusOne(3)
        avcc.append(0xE1)  # 3 bits reserved(0x7) + 5 bits numSPS(1)
        avcc.extend(len(sps).to_bytes(2, 'big'))
        avcc.extend(sps)
        pps_data = pps or b""
        avcc.append(0x01)  # numPPS
        avcc.extend(len(pps_data).to_bytes(2, 'big'))
        avcc.extend(pps_data)
        LOG.info("_header_to_avcc: %dB raw → %dB avcC (profile=0x%02x level=0x%02x)",
                 len(header), len(avcc), profile, level)
        return bytes(avcc)

    async def _producer_loop(self):
        loop = asyncio.get_running_loop()
        sock: Any = None
        while True:
            try:
                # 无客户端时休眠
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

                # flags & 0x8 == 关键帧（比扫 NALU 快得多）
                idx = getattr(evt, "idx", None)
                flags = getattr(idx, "flags", 0) if idx is not None else 0
                is_key = bool(flags & 0x8) or self._is_h264_keyframe(data)

                # DEBUG: 前 5 帧打印帧信息
                if not hasattr(self, '_debug_frame_count'):
                    self._debug_frame_count = 0
                self._debug_frame_count += 1
                if self._debug_frame_count <= 5:
                    LOG.info("[%s] frame#%d: hdr=%dB data=%dB flags=0x%x key=%s",
                             self.name, self._debug_frame_count,
                             len(header), len(data), flags, is_key)

                if header and header != self.header_annexb:
                    self.header_annexb = header
                    self.header = self._header_to_avcc(header)
                    LOG.info("[%s] new header %dB (avcC start: %s)", self.name, len(self.header),
                             " ".join("%02x" % b for b in self.header[:8]))
                    # 广播新 header 给所有已连接的客户端
                    if self.clients:
                        hdr_payload = FRAME_HEADER + self.header
                        for ws in list(self.clients):
                            try:
                                await ws.send_bytes(hdr_payload)
                            except Exception:
                                pass
                elif is_key and not header and self.header is None:
                    # 编码器没发单独 header（hdr=0B），尝试从关键帧数据中提取 SPS/PPS
                    extracted = self._header_to_avcc(data)
                    if extracted and len(extracted) > 5:
                        self.header = extracted
                        LOG.info("[%s] extracted avcC from keyframe data (%dB)", self.name, len(self.header))
                        if self.clients:
                            hdr_payload = FRAME_HEADER + self.header
                            for ws in list(self.clients):
                                try:
                                    await ws.send_bytes(hdr_payload)
                                except Exception:
                                    pass

                # FALLBACK: 如果一直没有 header，尝试从任意帧数据中找 SPS/PPS
                if self.header is None and len(data) >= 4:
                    extracted = self._header_to_avcc(data)
                    if extracted and len(extracted) > 5:
                        self.header = extracted
                        LOG.info("[%s] fallback: extracted avcC from non-keyframe (%dB)", self.name, len(self.header))
                        if self.clients:
                            hdr_payload = FRAME_HEADER + self.header
                            for ws in list(self.clients):
                                try:
                                    await ws.send_bytes(hdr_payload)
                                except Exception:
                                    pass

                # 关键帧拼接 raw header（SPS/PPS），让前端无 description 也能自解析
                if is_key and self.header_annexb:
                    data = self.header_annexb + data

                # 队列满就丢最老的
                if self._queue.full():
                    try: self._queue.get_nowait()
                    except Exception: pass
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
                            try: await ws.close(code=1011, message=b"send_timeout")
                            except Exception: pass
                    else:
                        self._ws_fail.pop(ws, None)
            except asyncio.CancelledError:
                break
            except Exception:
                LOG.exception("[%s] sender error", self.name)
                await asyncio.sleep(0.05)

    async def _send_one(self, ws: web.WebSocketResponse, payload: bytes, is_key: bool):
        # backpressure：缓冲太多且非关键帧就丢弃这一次
        try:
            buf = ws._writer.transport.get_write_buffer_size()
            if buf > DROP_BUFFER_BYTES and not is_key:
                return True
        except Exception:
            pass
        await asyncio.wait_for(ws.send_bytes(payload), timeout=0.35)
        return True


# ─────────────────────────────────────────────────────────
# HUD 数据广播器：多 topic 抽字段 + 10Hz 降频
# ─────────────────────────────────────────────────────────

# 服务端抽字段器：每个 topic 一个函数，输出精简字典
def _proj_carState(cs) -> dict:
    gear = str(cs.gearShifter).split(".")[-1] if cs.gearShifter else "?"
    return {
        "vKph": (cs.vEgo or 0.0) * 3.6,
        "aEgo": cs.aEgo if hasattr(cs, "aEgo") else None,
        "gear": gear.upper()[:1] if gear != "?" else "?",
        "steer": cs.steeringAngleDeg,
        "brake": bool(cs.brakePressed),
        "gas": cs.gas,
        "blinkerL": bool(cs.leftBlinker),
        "blinkerR": bool(cs.rightBlinker),
        "cruise": bool(cs.cruiseState.enabled),
        "cruiseSet": (cs.cruiseState.speed or 0.0) * 3.6,
    }

_ALERT_STATUS_MAP = {
    "normal": "info",     # AlertStatus.normal
    "userPrompt": "warning",
    "critical": "severe",
}
def _proj_selfdriveState(ss) -> dict:
    return {
        "enabled": bool(ss.enabled),
        "active": bool(ss.active),
        "alert1": ss.alertText1 or "",
        "alert2": ss.alertText2 or "",
        "alertStatus": _ALERT_STATUS_MAP.get(str(ss.alertStatus).split(".")[-1], ""),
    }

def _proj_radarState(rs) -> dict:
    lead = rs.leadOne
    return {
        "hasLead": bool(lead.status),
        "dRel": lead.dRel if lead.status else None,
        "vRel": lead.vRel if lead.status else None,
        "vLead": lead.vLead if lead.status else None,
        "aLead": lead.aLeadK if lead.status else None,
    }

def _proj_longitudinalPlan(lp) -> dict:
    # 取第一个采样点作为期望
    aTarget = lp.aTarget if hasattr(lp, "aTarget") else 0.0
    vTarget = lp.vTarget if hasattr(lp, "vTarget") else 0.0
    return {"aTarget": aTarget, "vTarget": vTarget}

def _proj_deviceState(ds) -> dict:
    temps = list(ds.cpuTempC) if ds.cpuTempC else [0.0]
    return {
        "cpuTempC": max(temps),
        "memPct": ds.memoryUsagePercent,
        "freeGB": (ds.freeSpacePercent or 0.0),  # 有些版本直接是百分比
        "networkType": str(ds.networkType).split(".")[-1] if ds.networkType else None,
    }

def _proj_controlsState(cs) -> dict:
    return {
        "curvature": cs.curvature,
        "desiredCurvature": cs.desiredCurvature,
        "vEgoCluster": getattr(cs, "vCruise", 0.0),
    }

def _proj_liveCalibration(lc) -> dict:
    rpy = list(lc.rpyCalib) if lc.rpyCalib else [0, 0, 0]
    return {
        "rpy": rpy,
        "calStatus": str(lc.calStatus).split(".")[-1] if lc.calStatus else None,
        "calPerc": int(getattr(lc, "calPerc", 0) or 0),
    }

def _proj_modelV2(mv) -> dict:
    # 只下采样 x/y，从 33 点采到 11 点，够画路径
    def _down(seq, step=3, cap=11):
        out = []
        for i in range(0, min(len(seq), step * cap), step):
            out.append(round(seq[i], 3))
            if len(out) >= cap: break
        return out
    pos = mv.position
    xs = _down(pos.x) if pos.x else []
    ys = _down(pos.y) if pos.y else []
    lanes = []
    for ll in (mv.laneLines or []):
        lanes.append({"y": _down(ll.y) if ll.y else []})
    return {"pathX": xs, "pathY": ys, "lanes": lanes[:4]}


def _proj_onroadEvents(ss) -> dict:
    """selfdriveState.onroadEvents 是当前所有活跃事件（错误/告警/软禁用/立即禁用）。
    对无屏调试至关重要 —— 屏幕上滚动的一条告警只是这里的一个。"""
    events = getattr(ss, "onroadEvents", None) or []
    out: list[dict] = []
    for ev in events:
        try:
            name = str(ev.name).split(".")[-1] if ev.name else "?"
        except Exception:
            name = "?"
        # 严重程度：越大越严重
        severity = 0
        if getattr(ev, "warning", False): severity = 1
        if getattr(ev, "softDisable", False): severity = 2
        if getattr(ev, "userDisable", False): severity = 2
        if getattr(ev, "immediateDisable", False): severity = 3
        if getattr(ev, "noEntry", False) and severity < 1: severity = 1
        out.append({
            "name": name,
            "severity": severity,
            "warning": bool(getattr(ev, "warning", False)),
            "softDisable": bool(getattr(ev, "softDisable", False)),
            "immediateDisable": bool(getattr(ev, "immediateDisable", False)),
            "noEntry": bool(getattr(ev, "noEntry", False)),
            "permanent": bool(getattr(ev, "permanent", False)),
        })
    out.sort(key=lambda e: (-e["severity"], e["name"]))
    return {"count": len(out), "list": out[:12]}


def _proj_managerState(ms) -> dict:
    """managerState.processes：每个进程 running / shouldBeRunning / exitCode。
    无屏调试关键 —— 直接告诉你哪个进程死了。"""
    procs = getattr(ms, "processes", None) or []
    unhealthy: list[dict] = []
    healthy_count = 0
    for p in procs:
        running = bool(getattr(p, "running", False))
        should = bool(getattr(p, "shouldBeRunning", False))
        exit_code = int(getattr(p, "exitCode", 0) or 0)
        # 异常：应该运行但没运行、或已经退出且非零
        if should != running or exit_code != 0:
            unhealthy.append({
                "name": str(getattr(p, "name", "?")),
                "pid": int(getattr(p, "pid", 0) or 0),
                "running": running,
                "shouldBeRunning": should,
                "exitCode": exit_code,
            })
        else:
            healthy_count += 1
    unhealthy.sort(key=lambda x: (x["exitCode"] == 0, x["name"]))
    return {"total": len(procs), "healthy": healthy_count,
            "unhealthy": unhealthy[:20]}


# 每条 HUD 输出里的字段名 → (topic, projector)
HUD_SOURCES: list[tuple[str, str, Callable]] = [
    ("car",    "carState",           _proj_carState),
    ("self",   "selfdriveState",     _proj_selfdriveState),
    ("lead",   "radarState",         _proj_radarState),
    ("plan",   "longitudinalPlan",   _proj_longitudinalPlan),
    ("dev",    "deviceState",        _proj_deviceState),
    ("ctrl",   "controlsState",      _proj_controlsState),
    ("cal",    "liveCalibration",    _proj_liveCalibration),
    ("model",  "modelV2",            _proj_modelV2),
    ("events", "selfdriveState",     _proj_onroadEvents),  # 复用同一 topic，抽 onroadEvents
    ("procs",  "managerState",       _proj_managerState),
]


class HudBroadcaster:
    def __init__(self):
        self.clients: set[web.WebSocketResponse] = set()
        self._task: asyncio.Task | None = None
        self._idle_since: float = 0.0
        self._sm: Any = None
        self._latest: dict[str, dict] = {}

    async def ensure_running(self):
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="hud_pump")

    async def register(self, ws: web.WebSocketResponse):
        self.clients.add(ws)
        await self.ensure_running()
        # 立即发一次最新快照
        if self._latest:
            try:
                await ws.send_str(json.dumps(self._latest, ensure_ascii=False,
                                             separators=(",", ":")))
            except Exception:
                self.clients.discard(ws)

    def unregister(self, ws: web.WebSocketResponse):
        self.clients.discard(ws)

    async def _loop(self):
        loop = asyncio.get_running_loop()
        interval = 1.0 / HUD_RATE_HZ
        # 去重：多个 projector 可能引用同一 topic (e.g. selfdriveState → self + events)
        seen: set[str] = set()
        topics = [t for _, t, _ in HUD_SOURCES if not (t in seen or seen.add(t))]
        while True:
            try:
                if not self.clients:
                    if self._idle_since == 0.0:
                        self._idle_since = time.monotonic()
                    elif time.monotonic() - self._idle_since > IDLE_STOP_SEC:
                        if self._sm is not None:
                            LOG.info("[hud] idle → drop SubMaster")
                            self._sm = None
                            self._latest = {}
                        await asyncio.sleep(0.5)
                        continue
                    await asyncio.sleep(0.1)
                    continue
                self._idle_since = 0.0

                if self._sm is None:
                    self._sm = messaging.SubMaster(topics)
                    LOG.info("[hud] SubMaster started with %s", topics)

                await loop.run_in_executor(None, self._sm.update, 100)

                snapshot: dict[str, Any] = {}
                for key, topic, proj in HUD_SOURCES:
                    if self._sm.updated[topic] and self._sm.valid[topic]:
                        try:
                            snapshot[key] = proj(self._sm[topic])
                        except Exception:
                            pass
                    elif key in self._latest:
                        snapshot[key] = self._latest[key]

                snapshot["ts"] = round(time.time(), 3)
                self._latest = snapshot
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
    # 老前端还在用 /ws → 等价 /ws/video?cam=road
    request = request.clone(rel_url=request.rel_url.with_query({"cam": "road"}))
    return await ws_video(request)


async def index(request):
    return web.Response(text=INDEX_HTML, content_type="text/html")


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
                "topics": sorted(set(t for _, t, _ in HUD_SOURCES)),
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
    return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    LOG.info("livestream_ws listening on %s:%d", HOST, PORT)
    LOG.info("cameras: %s", CAMERA_TOPICS)
    LOG.info("hud topics: %s @ %.1fHz", [t for _, t, _ in HUD_SOURCES], HUD_RATE_HZ)
    web.run_app(make_app(), host=HOST, port=PORT, access_log=None)


if __name__ == "__main__":
    main()
