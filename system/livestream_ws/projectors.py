"""
Livestream HUD 数据投影器

每个 _proj_* 函数从 cereal 消息中提取前端需要的字段，
做单位换算和格式化，前端 0 计算。
"""

from __future__ import annotations
import time

# 单位转换常量
MS_TO_KPH = 3.6
MS_TO_MPH = 2.236936
M_TO_FT = 3.28084

_ALERT_STATUS_MAP = {
    "normal": "info",
    "userPrompt": "warning",
    "critical": "severe",
}


def format_speed(speed_ms: float, is_metric: bool = True) -> float:
    """m/s → km/h 或 mph"""
    return speed_ms * (MS_TO_KPH if is_metric else MS_TO_MPH)


def get_speed_unit(is_metric: bool = True) -> str:
    return "km/h" if is_metric else "mph"


def get_distance_unit(is_metric: bool = True) -> str:
    return "m" if is_metric else "ft"


def proj_carState(cs, is_metric: bool = True) -> dict:
    """carState 投影：速度 / 转向 / 刹车 / 转向灯 / 盲点 / 手扶方向盘 / 踩油门"""
    gear = str(cs.gearShifter).split(".")[-1] if cs.gearShifter else "?"
    v_ego = cs.vEgo or 0.0
    return {
        "vKph": format_speed(v_ego, is_metric),
        "vEgo": v_ego,  # 原始值 m/s，给 TTC 用
        "aEgo": cs.aEgo if hasattr(cs, "aEgo") else None,
        "gear": gear.upper()[:1] if gear != "?" else "?",
        "steer": cs.steeringAngleDeg,
        "steeringPressed": bool(cs.steeringPressed) if hasattr(cs, "steeringPressed") else False,
        "brake": bool(cs.brakePressed),
        "gas": cs.gas,
        "gasPressed": bool(cs.gasPressed) if hasattr(cs, "gasPressed") else False,
        "blinkerL": bool(cs.leftBlinker),
        "blinkerR": bool(cs.rightBlinker),
        "blindspotL": bool(cs.leftBlindspot) if hasattr(cs, "leftBlindspot") else False,
        "blindspotR": bool(cs.rightBlindspot) if hasattr(cs, "rightBlindspot") else False,
        "cruise": bool(cs.cruiseState.enabled),
        "cruiseSet": format_speed(cs.cruiseState.speed or 0.0, is_metric),
        "speedUnit": get_speed_unit(is_metric),
        "distUnit": get_distance_unit(is_metric),
    }


def proj_selfdriveState(ss) -> dict:
    """selfdriveState 投影：OP 状态 / 提醒文本 / 实验模式"""
    return {
        "enabled": bool(ss.enabled),
        "active": bool(ss.active),
        "alert1": ss.alertText1 or "",
        "alert2": ss.alertText2 or "",
        "alertStatus": _ALERT_STATUS_MAP.get(str(ss.alertStatus).split(".")[-1], ""),
        "experimentalMode": bool(ss.experimentalMode) if hasattr(ss, "experimentalMode") else False,
    }


def proj_radarState(rs, v_ego: float = 0.0) -> dict:
    """radarState 投影：前车距离 / 速度 / TTC"""
    lead = rs.leadOne
    has_lead = bool(lead.status)

    ttc_value = None
    ttc_urgent = False
    if has_lead and v_ego > 0.5:
        d_rel = lead.dRel or 0.0
        ttc = abs(d_rel / v_ego) if v_ego > 0 else 999
        if ttc < 99:
            ttc_value = round(ttc, 1)
            ttc_urgent = ttc < 5.0

    return {
        "hasLead": has_lead,
        "dRel": lead.dRel if has_lead else None,
        "vRel": lead.vRel if has_lead else None,
        "vLead": lead.vLead if has_lead else None,
        "aLead": lead.aLeadK if has_lead else None,
        "yRel": lead.yRel if has_lead else None,
        "ttcValue": ttc_value,
        "ttcUrgent": ttc_urgent,
    }


def proj_longitudinalPlan(lp) -> dict:
    """longitudinalPlan 投影：期望加速度 / 速度"""
    a_target = lp.aTarget if hasattr(lp, "aTarget") else 0.0
    v_target = lp.vTarget if hasattr(lp, "vTarget") else 0.0
    return {"aTarget": a_target, "vTarget": v_target}


def proj_deviceState(ds) -> dict:
    """deviceState 投影：温度 / 内存 / 存储 / 网络 / 运行时长"""
    temps = list(ds.cpuTempC) if ds.cpuTempC else [0.0]
    uptime = 0.0
    if hasattr(ds, "startedMonoTime") and (ds.startedMonoTime > 0):
        uptime = time.monotonic() - (ds.startedMonoTime / 1e9)
    return {
        "cpuTempC": max(temps),
        "memPct": ds.memoryUsagePercent,
        "freeGB": (ds.freeSpacePercent or 0.0),
        "freePct": ds.freeSpacePercent,
        "gpuPct": ds.gpuUsagePercent if hasattr(ds, "gpuUsagePercent") else 0,
        "fanPct": ds.fanSpeedPercentDesired if hasattr(ds, "fanSpeedPercentDesired") else 0,
        "networkType": str(ds.networkType).split(".")[-1] if ds.networkType else None,
        "thermalStatus": str(ds.thermalStatus).split(".")[-1] if ds.thermalStatus else "?",
        "uptime": max(0, uptime),
    }


def proj_controlsState(cs) -> dict:
    """controlsState 投影：曲率 / 车速"""
    return {
        "curvature": cs.curvature if hasattr(cs, "curvature") else 0.0,
        "desiredCurvature": getattr(cs, "desiredCurvature", 0.0),
        "vCruise": getattr(cs, "vCruise", 0.0),
    }


def proj_carParams(cp) -> dict:
    """carParams 投影：纵向控制权"""
    return {
        "openpilotLongitudinal": bool(cp.openpilotLongitudinalControl) if hasattr(cp, "openpilotLongitudinalControl") else False,
    }


def proj_liveCalibration(lc) -> dict:
    """liveCalibration 投影：校准状态 / 俯仰偏航角 / 进度"""
    rpy = list(lc.rpyCalib) if lc.rpyCalib else [0, 0, 0]
    cal_perc = int(getattr(lc, "calPerc", 0) or 0)
    cal_status = str(lc.calStatus).split(".")[-1] if lc.calStatus else None
    return {
        "rpy": rpy,
        "calStatus": cal_status,
        "calPerc": cal_perc,
    }


def proj_modelV2(mv) -> dict:
    """modelV2 投影：路径点 / 车道线（下采样）"""
    def _down(seq, step=3, cap=11):
        out = []
        for i in range(0, min(len(seq), step * cap), step):
            out.append(round(seq[i], 3))
            if len(out) >= cap:
                break
        return out

    pos = mv.position
    xs = _down(pos.x) if pos.x else []
    ys = _down(pos.y) if pos.y else []
    lanes = []
    for ll in (mv.laneLines or []):
        lanes.append({"y": _down(ll.y) if ll.y else []})
    return {"pathX": xs, "pathY": ys, "lanes": lanes[:4]}


def proj_onroadEvents(ss) -> dict:
    """selfdriveState.onroadEvents 投影：事件列表（按严重程度降序）"""
    events = getattr(ss, "onroadEvents", None) or []
    out = []
    for ev in events:
        try:
            name = str(ev.name).split(".")[-1] if ev.name else "?"
        except Exception:
            name = "?"
        severity = 0
        if getattr(ev, "warning", False):
            severity = 1
        if getattr(ev, "softDisable", False):
            severity = 2
        if getattr(ev, "userDisable", False):
            severity = 2
        if getattr(ev, "immediateDisable", False):
            severity = 3
        if getattr(ev, "noEntry", False) and severity < 1:
            severity = 1
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


def proj_managerState(ms) -> dict:
    """managerState 投影：进程健康状态"""
    procs = getattr(ms, "processes", None) or []
    unhealthy = []
    healthy_count = 0
    for p in procs:
        running = bool(getattr(p, "running", False))
        should = bool(getattr(p, "shouldBeRunning", False))
        exit_code = int(getattr(p, "exitCode", 0) or 0)
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


# HUD 数据源注册表：每条输出字段名 → (cereal topic, 投影函数)
# 投影函数签名: fn(cereal_msg, **kwargs) -> dict
HUD_SOURCES: list[tuple[str, str, callable, dict]] = [
    ("car",    "carState",         proj_carState,         {}),
    ("self",   "selfdriveState",   proj_selfdriveState,   {}),
    ("lead",   "radarState",       proj_radarState,       {}),
    ("plan",   "longitudinalPlan", proj_longitudinalPlan, {}),
    ("dev",    "deviceState",      proj_deviceState,      {}),
    ("ctrl",   "controlsState",    proj_controlsState,    {}),
    ("cal",    "liveCalibration",  proj_liveCalibration,  {}),
    ("model",  "modelV2",          proj_modelV2,          {}),
    ("events", "selfdriveState",   proj_onroadEvents,     {}),
    ("procs",  "managerState",     proj_managerState,     {}),
    ("carParams", "carParams",     proj_carParams,        {}),
]
