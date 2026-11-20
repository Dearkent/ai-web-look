#!/usr/bin/env python3
"""修复回路：构建 → 报错 → 修复者给改动 → 工作区整批预检并提交 → 再构建 → 守卫判断 → 必要时回滚。

* 修复者可以是真实模型，也可以是测试用的模拟修复者；接口相同：fixer(files, errors, hint, strategy, round) → [Change]。
* 守卫的提醒和报错原文都写回给修复者（经验 P006）。
* 每次运行写一行修复记录（fix_runs.jsonl），以后用来校准守卫的阈值。
* 兜底：即使守卫失灵一直说“继续”，循环本身也有轮数上限，到点就停下、退回最好的版本（双保险）。
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from fix_guard import Attempt, Decision, FixGuard  # noqa: E402
from workspace import Rejected, Workspace, patch_signature  # noqa: E402


def run(ws: Workspace, build, fixer, guard: FixGuard, log_path: str | None = None, label: str = "") -> dict:
    t0 = time.monotonic()
    errors = build(ws.files())
    start_head, start_errors = ws.head(), list(errors)
    best = (len(errors), start_head)
    rounds, hint, strategy = [], "", "fast-fix"
    pre = guard.preflight(errors)
    decision = pre
    if pre.verdict == "continue" and errors:
        guard.baseline(errors, snapshot=start_head, code_state=ws.tree())
        cap = guard.p.max_attempts + 1  # 兜底上限：比守卫多留一轮
        for rnd in range(1, cap + 1):
            r0 = time.monotonic()
            changes = fixer(ws.files(), errors, hint, strategy, rnd)
            sig = patch_signature(changes) if changes else f"empty-{rnd}"
            applied, note = True, ""
            try:
                snap = ws.apply(changes, f"第 {rnd} 轮修复（{strategy}）")
                new_errors = build(ws.files())
            except Rejected as e:
                applied, snap = False, ws.head()
                note = "补丁被整批拒绝：" + "；".join(e.reasons)
                new_errors = list(errors) + [note]
            except RuntimeError as e:
                applied, snap = False, ws.head()
                note = str(e)
                new_errors = list(errors) + [note]
            if applied and len(new_errors) < best[0]:
                best = (len(new_errors), snap)
            # 补丁没落地时代码没变，不能算“改回旧版本”，所以不报 code_state
            decision = guard.record(Attempt(errors=new_errors, code_state=ws.tree() if applied else "", patch_signature=sig,
                                            snapshot=snap if applied else "", seconds=time.monotonic() - r0,
                                            strategy=strategy))
            rounds.append({"round": rnd, "strategy": strategy, "applied": applied, "errors": len(new_errors),
                           "verdict": decision.verdict, "code": decision.code, "note": note[:200]})
            errors = new_errors
            if decision.rollback_to and decision.rollback_to != ws.head():
                ws.rollback(decision.rollback_to, f"{decision.code} {decision.reason}")
                errors = build(ws.files())
                rounds[-1]["rolled_back_to"] = decision.rollback_to[:8]
            hint = (decision.to_model + "\n" if decision.to_model else "") + ("\n".join(errors[:20]))
            if decision.next_strategy:
                strategy = decision.next_strategy
            if decision.verdict in ("done", "stop"):
                break
        else:
            decision = Decision("stop", "L00", "循环到达兜底上限而守卫没有叫停（守卫失灵）",
                                to_user="自动修复到达上限，已停下并退回报错最少的版本。")
            if best[1] != ws.head():
                ws.rollback(best[1], "兜底上限")
                errors = build(ws.files())
    final = build(ws.files())
    report = {
        "label": label, "verdict": decision.verdict if final else "done", "code": decision.code,
        "reason": decision.reason, "to_user": decision.to_user, "rounds": rounds,
        "errors_before": len(start_errors), "errors_after": len(final),
        "commits": len(ws.history()), "seconds": round(time.monotonic() - t0, 2),
        "lesson": decision.lesson,
    }
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
    return report
