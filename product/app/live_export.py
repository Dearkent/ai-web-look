#!/usr/bin/env python3
"""把实况页面导出成一个独立的回放网页：嵌入事件记录里最近几次真实任务，不需要服务器也能看。

挑哪几次：每种任务（喂设计、试跑先验、建站、验证门）各取最近一次，按发生顺序拼起来。
只用 runs/events.jsonl 里真实记下的事件，不补、不改数字（回放时只把时间间隔压缩）。
用法：python3 -I live_export.py 输出.html [--kinds feed,trial,site,gate] [--max-feed 30]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import events  # noqa: E402
import live  # noqa: E402


def pick(rows, kinds, max_feed):
    ends = [r for r in rows if r["kind"] == "run.end" and r.get("what") in kinds]
    chosen = {}
    for e in ends:  # 每种取最近一次（后面的覆盖前面的）
        chosen[e["what"]] = e["run"]
    runs = set(chosen.values())
    if "site" in chosen:  # 建站之前那次“读懂需求”也带上
        site_start = next(r["t"] for r in rows if r["run"] == chosen["site"] and r["kind"] == "run.start")
        und = [r["run"] for r in rows if r["kind"] == "run.end" and r.get("what") == "understand" and r["t"] <= site_start]
        if und:
            runs.add(und[-1])
    out = [r for r in rows if r["run"] in runs]
    if "feed" in chosen:  # 喂设计一批可能上百条：只保留前 max_feed 个网站，结尾照实写总数
        fid, n, keep = chosen["feed"], 0, []
        for r in out:
            if r["run"] == fid and r["kind"] in ("feed.specimen", "feed.skip"):
                n += 1
                if n > max_feed:
                    continue
            if r["run"] == fid and r["kind"] in ("stage.start", "stage.end") and n > max_feed:
                continue
            keep.append(r)
        out = keep
    out.sort(key=lambda r: r["t"])
    return out, chosen


def history(rows):
    return [{"ms": r.get("ms", 0), "problems": r.get("problems"), "rounds": r.get("rounds"), "what": r.get("what")}
            for r in rows if r["kind"] == "run.end" and r.get("what") not in ("build", "understand")][-24:]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--kinds", default="feed,trial,site,gate")
    ap.add_argument("--max-feed", type=int, default=30)
    ap.add_argument("--speed", type=float, default=4)
    a = ap.parse_args(argv)
    rows, _ = events.tail(200000)
    sel, chosen = pick(rows, set(a.kinds.split(",")), a.max_feed)
    if not sel:
        print("事件记录里还没有可回放的任务")
        return 1
    data = {"events": sel, "stats": live.stats(), "history": history(rows), "speed": a.speed,
            "recorded": time.strftime("%Y-%m-%d %H:%M", time.localtime(sel[0]["t"])) + " 起的真实记录"}
    page = open(os.path.join(HERE, "live.html"), encoding="utf-8").read()
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = page.replace("<script>\n(() => {", f"<script>window.__LIVE_DATA__ = {blob};</script>\n<script>\n(() => {{", 1)
    page = page.replace("<title>建站大脑 · 实况</title>", "<title>建站大脑 · 实况（回放）</title>", 1)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"导出 {len(sel)} 条事件：" + "、".join(f"{k}" for k in chosen) + f" → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
