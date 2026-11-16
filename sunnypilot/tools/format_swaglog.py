#!/usr/bin/env python3
"""
将 swaglog JSON Lines 转换为易读的纯文本格式。

用法:
  python3 sunnypilot/tools/format_swaglog.py                    # 转换最近 100 个文件
  python3 sunnypilot/tools/format_swaglog.py --daemon ui        # 只查看某进程
  python3 sunnypilot/tools/format_swaglog.py --level WARNING    # 最低级别
  python3 sunnypilot/tools/format_swaglog.py --follow           # 实时跟踪（类似 tail -f）
  python3 sunnypilot/tools/format_swaglog.py --count 50         # 最近 50 个文件
  python3 sunnypilot/tools/format_swaglog.py --count -1         # 所有文件

输出格式:
  2026-07-16 12:34:56.789 | INFO  | manager | 导入 system.livestream_ws.livestream_ws
  2026-07-16 12:34:57.012 | WARN  | ui      | 绘制延迟 45ms
  2026-07-16 12:34:58.345 | ERROR | soundd  | stream inactive, restarting

输出路径:
  /data/media/0/system_logs/formatted/all.log
"""

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

SWAGLOG_DIR = "/data/log"
FORMATTED_DIR = "/data/media/0/system_logs/formatted"
DEFAULT_COUNT = 100

_TYPE_SUFFIX_RE = re.compile(r"\$(s|i|f|b|a)$")


def strip_suffixes(obj):
    """递归移除所有键名中的 $s/$i/$f/$b/$a 类型后缀。"""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            k_stripped = _TYPE_SUFFIX_RE.sub("", k)
            cleaned[k_stripped] = strip_suffixes(v)
        return cleaned
    elif isinstance(obj, list):
        return [strip_suffixes(item) for item in obj]
    return obj


def format_timestamp(created):
    """将 Unix 时间戳格式化为 YYYY-MM-DD HH:MM:SS.mmm"""
    if isinstance(created, (int, float)) and created > 1e8:
        dt = datetime.fromtimestamp(created)
        return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    return str(created)


_LEVEL_MAP = {50: "CRITICAL", 40: "ERROR", 30: "WARNING", 20: "INFO", 10: "DEBUG"}


def format_level(level_name, levelnum=None):
    if level_name is None or level_name == "?":
        if levelnum is not None and levelnum in _LEVEL_MAP:
            return _LEVEL_MAP[levelnum].ljust(5)
    return (level_name or "?").ljust(5)


def format_message(raw_msg):
    """展开消息，支持简单字符串和结构化字典。"""
    if isinstance(raw_msg, dict):
        parts = []
        for k, v in raw_msg.items():
            if k == "module":
                continue
            if isinstance(v, (dict, list)):
                parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
            else:
                parts.append(f"{k}={v}")
        if not parts:
            return ""
        return "  ".join(parts)
    return str(raw_msg)


def format_entry(entry):
    """将一条日志条目转为易读文本。"""
    ts = format_timestamp(entry.get("created", 0))
    level = format_level(entry.get("level"), entry.get("levelnum"))
    daemon = (entry.get("ctx") or {}).get("daemon", "?")
    module = entry.get("module", daemon)
    msg = format_message(entry.get("msg", ""))

    lines = [f"{ts} | {level} | {module} | {msg}"]

    exc = entry.get("exc_info", "")
    if exc:
        for line in exc.splitlines():
            lines.append(f"  {line}")

    return "\n".join(lines)


def parse_file(fp, daemon_filter=None, min_level=10):
    """解析一个 swaglog 文件，产出 (timestamp, 格式化文本) 元组。"""
    with open(fp, "r", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            entry = strip_suffixes(entry)

            if daemon_filter:
                d = (entry.get("ctx") or {}).get("daemon", "")
                if d != daemon_filter:
                    continue

            if entry.get("levelnum", 0) < min_level:
                continue

            yield (entry.get("created", 0), format_entry(entry))


def follow_logs(swaglog_dir, daemon_filter, min_level):
    """实时跟踪最新的日志文件。"""
    latest = None
    fh = None
    print(f"实时跟踪 swaglog (过滤: daemon={daemon_filter or '*'}, level>={min_level}) ...")

    while True:
        log_files = sorted(swaglog_dir.glob("swaglog.*"), key=lambda p: p.stat().st_mtime)
        if not log_files:
            time.sleep(2)
            continue

        new_latest = log_files[-1]
        if new_latest != latest:
            if fh is not None:
                fh.close()
            latest = new_latest
            fh = open(latest, "r", errors="replace")
            fh.seek(0, 2)
            print(f"\n=== {latest.name} ===", flush=True)

        line = fh.readline()
        if line:
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entry = strip_suffixes(entry)

                if daemon_filter:
                    d = (entry.get("ctx") or {}).get("daemon", "")
                    if d != daemon_filter:
                        continue

                if entry.get("levelnum", 0) < min_level:
                    continue

                print(format_entry(entry), flush=True)
        else:
            time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description="将 swaglog JSON Lines 转换为易读的纯文本格式")
    parser.add_argument("--daemon", "-d", help="按进程名过滤 (如 ui, manager, livestream_ws)")
    parser.add_argument("--level", "-l", default="DEBUG",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        help="最低日志级别 (默认: DEBUG)")
    parser.add_argument("--follow", "-f", action="store_true", help="实时跟踪最新日志")
    parser.add_argument("--count", "-n", type=int, default=DEFAULT_COUNT,
                        help=f"处理最近 N 个文件 (默认: {DEFAULT_COUNT}, -1=全部)")
    parser.add_argument("--output", "-o", default=FORMATTED_DIR,
                        help=f"输出目录 (默认: {FORMATTED_DIR})")
    args = parser.parse_args()

    level_map = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
    min_level = level_map.get(args.level, 10)

    swaglog_dir = Path(SWAGLOG_DIR)
    if not swaglog_dir.is_dir():
        print(f"错误: 未找到 swaglog 目录 {SWAGLOG_DIR}")
        print("(此工具设计在 AGNOS 设备上运行，非 PC)")
        return 1

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.follow:
        follow_logs(swaglog_dir, args.daemon, min_level)
        return 0

    log_files = sorted(swaglog_dir.glob("swaglog.*"), key=lambda p: p.stat().st_mtime)
    if not log_files:
        print(f"{SWAGLOG_DIR} 中未找到 swaglog 文件")
        return 0

    if args.count > 0 and args.count < len(log_files):
        log_files = log_files[-args.count:]

    print(f"正在处理 {len(log_files)} 个 swaglog 文件")
    if args.daemon:
        print(f"  过滤: daemon = {args.daemon}")
    if args.level != "DEBUG":
        print(f"  过滤: 最低级别 = {args.level}")

    all_entries = []
    for fp in log_files:
        entries = list(parse_file(fp, args.daemon, min_level))
        all_entries.extend(entries)
        print(f"  {fp.name}: {len(entries)} 行")

    all_entries.sort(key=lambda x: x[0])

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_name = f"format_swaglog_{timestamp}.log"
    all_path = out_dir / out_name
    with open(all_path, "w", encoding="utf-8") as out:
        for _, formatted in all_entries:
            out.write(formatted + "\n")
    print(f"\n输出: {all_path} ({len(all_entries)} 行)")
    return 0


if __name__ == "__main__":
    exit(main())
