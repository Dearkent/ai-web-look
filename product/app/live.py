#!/usr/bin/env python3
"""实况页面的数据：顶部的真实指标 + 事件流（Server-Sent Events）。

指标全部从仓库里现成的记录算，没有记录就显示“—”，不估、不编：
  完成度   dashboard/roadmap.json 的 earned / weight
  验证门   evals/last_run.json 里通过的用例数 / 总数
  经验卡片 cards/ 里的卡片数
  学过的网站 product/learn/corpus/specimens.jsonl 的行数
"""
from __future__ import annotations

import json
import os
import time

import events

ROOT = events.ROOT


def _json(rel):
    try:
        return json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def stats() -> dict:
    out = {}
    rm = _json("dashboard/roadmap.json")
    if isinstance(rm, list) and rm:
        w = sum(float(r.get("weight", 0)) for r in rm)
        out["completion"] = round(100 * sum(float(r.get("earned", 0)) for r in rm) / w, 1) if w else None
    lr = _json("evals/last_run.json")
    if isinstance(lr, dict) and lr.get("rows"):
        out["gate"] = {"ok": sum(1 for r in lr["rows"] if r.get("result") == "通过"), "n": len(lr["rows"]), "at": lr.get("at", "")}
    cdir = os.path.join(ROOT, "cards")
    if os.path.isdir(cdir):
        out["cards"] = sum(1 for f in os.listdir(cdir) if f.endswith(".md"))
    cp = os.path.join(ROOT, "product", "learn", "corpus", "specimens.jsonl")
    if os.path.isfile(cp):
        with open(cp, encoding="utf-8") as f:
            out["specimens"] = sum(1 for line in f if line.strip())
    pr = _json("product/learn/corpus/priors.json")
    if isinstance(pr, dict):
        out["priors"] = sum(1 for v in pr.get("industries", {}).values() if v.get("status") == "采纳")
    return out


def snapshot(n: int = 600) -> dict:
    rows, pos = events.tail(n)
    return {"events": rows, "pos": pos, "stats": stats(), "now": time.time()}


def stream(write, since: int, max_seconds: float = 1800, poll: float = 0.4, ping: float = 15.0):
    """把 since 之后的新事件一条条写成 SSE。write(bytes) 抛错（浏览器关了）就结束。"""
    t_end, last_ping, last_stats = time.time() + max_seconds, 0.0, 0.0
    write(b"retry: 2000\n\n")
    while time.time() < t_end:
        rows, since = events.read(since)
        for r in rows:
            write(("event: ev\ndata: " + json.dumps(r, ensure_ascii=False) + "\n\n").encode("utf-8"))
        now = time.time()
        if rows and now - last_stats > 5 or now - last_stats > 30:  # 指标变化慢：有事件时最多 5 秒一次
            write(("event: stats\ndata: " + json.dumps(stats(), ensure_ascii=False) + "\n\n").encode("utf-8"))
            last_stats = now
        if now - last_ping > ping:
            write(b": ping\n\n")
            last_ping = now
        time.sleep(poll)
