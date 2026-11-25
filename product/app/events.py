#!/usr/bin/env python3
"""实况事件：系统每做一步就记一行，实况页面（live.html）只画这些真实发生的事，不编数字。

一行一个 JSON：{"t": 时间戳, "run": 这次任务的编号, "kind": 事件种类, ...附加数字}
  run.start / run.end        一次建站（或喂养、验证门）开始、结束
  stage.start / stage.end    某一步开始、结束：stage ∈ understand plan blueprint generate browser fix learn deliver feed distill gate
  fix.try / fix.revert / guard.stop   自我纠错的每一轮、撤回、刹车
  feed.specimen / feed.skip  喂进来一个网站设计 / 跳过（重复、太大、读不出）
  gate.case                  验证门的一条用例
写入位置：环境变量 AISITE_EVENTS，否则仓库里的 runs/events.jsonl（不进 git）。超过 5MB 换新文件，旧的留一份 .1。
记事件永远不能让正事失败：任何错误都吞掉。只记数字、类别和短标签，不记用户原话、密钥或网页正文。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MAX_BYTES = 5 * 1024 * 1024
_LOCK = threading.Lock()
_local = threading.local()
KINDS = {"run.start", "run.end", "stage.start", "stage.end", "fix.try", "fix.revert", "guard.stop",
         "feed.specimen", "feed.skip", "gate.case", "note"}
STAGES = ["understand", "plan", "blueprint", "generate", "browser", "fix", "learn", "deliver", "feed", "distill", "gate"]
_SAFE = re.compile(r"[^\w一-鿿 .:/#%+\-→（）()、，·]")


def path() -> str:
    return os.environ.get("AISITE_EVENTS") or os.path.join(ROOT, "runs", "events.jsonl")


def _clean(v, depth=0):
    """只留数字、布尔、短字符串和它们的小列表/字典；字符串截短并去掉奇怪字符。"""
    if isinstance(v, bool) or v is None or isinstance(v, int):
        return v
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, str):
        return _SAFE.sub("", v)[:80]
    if depth < 2 and isinstance(v, (list, tuple)):
        return [_clean(x, depth + 1) for x in list(v)[:12]]
    if depth < 2 and isinstance(v, dict):
        return {str(k)[:24]: _clean(x, depth + 1) for k, x in list(v.items())[:16]}
    return str(v)[:40]


def current_run() -> str | None:
    return getattr(_local, "run", None)


def emit(kind: str, run: str | None = None, **data) -> dict | None:
    if kind not in KINDS:
        return None
    try:
        row = {"t": round(time.time(), 3), "run": run or current_run() or "-", "kind": kind}
        row.update({k: _clean(v) for k, v in data.items() if k not in row})
        line = json.dumps(row, ensure_ascii=False)
        p = path()
        with _LOCK:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if os.path.exists(p) and os.path.getsize(p) > MAX_BYTES:
                os.replace(p, p + ".1")
            with open(p, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return row
    except Exception:
        return None


class run:
    """with events.run("build", 标签=...) as rid: —— 记开始和结束（含耗时、是否出错），里面的事件自动带上编号。
    已经在一个任务里时不再开新任务（嵌套调用共享外层编号）。"""

    def __init__(self, what: str, **data):
        self.what, self.data, self.outer = what, data, None
        self.result: dict = {}

    def __enter__(self):
        self.outer = current_run()
        if self.outer:
            return self.outer
        self.rid = uuid.uuid4().hex[:8]
        _local.run = self.rid
        self.t0 = time.time()
        emit("run.start", what=self.what, **self.data)
        return self.rid

    def __exit__(self, et, ev, tb):
        if self.outer:
            return False
        emit("run.end", what=self.what, ms=int((time.time() - self.t0) * 1000), ok=et is None,
             **({"error": et.__name__} if et else {}), **self.result)
        _local.run = None
        return False


class stage:
    """with events.stage("browser") as s: ... s.out(problems=3) —— 记一步的开始、结束和结果数字。"""

    def __init__(self, name: str, **data):
        self.name, self.data, self.outv = name, data, {}

    def out(self, **kw):
        self.outv.update(kw)

    def __enter__(self):
        self.t0 = time.time()
        emit("stage.start", stage=self.name, **self.data)
        return self

    def __exit__(self, et, ev, tb):
        emit("stage.end", stage=self.name, ms=int((time.time() - self.t0) * 1000), ok=et is None, **self.data, **self.outv)
        return False


def read(since: int = 0, limit: int = 2000, p: str | None = None) -> tuple[list[dict], int]:
    """从字节位置 since 往后读完整的行；返回（事件列表，新的位置）。文件被换新时从头读。"""
    p = p or path()
    try:
        size = os.path.getsize(p)
    except OSError:
        return [], 0
    if since > size:
        since = 0
    out = []
    with open(p, "rb") as f:
        f.seek(since)
        chunk = f.read(2 * 1024 * 1024)
    end = chunk.rfind(b"\n")
    if end < 0:
        return [], since
    for line in chunk[:end].splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[-limit:], since + end + 1


def tail(n: int = 600, p: str | None = None) -> tuple[list[dict], int]:
    """最近 n 条（给页面一打开就有东西看），和文件当前末尾位置。"""
    p = p or path()
    try:
        size = os.path.getsize(p)
    except OSError:
        return [], 0
    start = max(0, size - 1024 * 1024)
    rows, pos = read(start, 10 ** 6, p)
    if start > 0 and rows:
        rows = rows[1:]  # 第一行可能是半行
    return rows[-n:], pos
