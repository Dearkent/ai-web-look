#!/usr/bin/env python3
"""反向测试修复守卫：逐个拆掉刹车，模拟测试必须失败。否则说明那条测试是摆设（L015）。"""
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "fix_guard.py"), encoding="utf-8").read()
CUTS = [
    ("拆掉 G01 硬上限", 'if n >= self.p.max_attempts:\n            return stop("G01"', 'if False:\n            return stop("G01"'),
    ("拆掉 G02 同错停止", "if streak >= self.p.same_error_stop:", "if False:"),
    ("拆掉 G03 错误集合振荡", "if len(seq) >= 3 and es == seq[-3][1]", "if False and es == seq[-3][1]"),
    ("拆掉 G03 代码回到旧版本", "if a.code_state and any(", "if False and any("),
    ("拆掉 G04 没有进展", "if n >= w and before and min(counts[-w:])", "if False and min(counts[-w:])"),
    ("拆掉 G05 越修越坏回滚", "if counts[-1] >= max(best_count * self.p.regression_factor", "if False and max(best_count * self.p.regression_factor"),
    ("拆掉 G06 预算", "if self.cost >= self.p.max_cost or", "if False and"),
    ("拆掉 G07 同补丁重复", "if a.patch_signature and any(", "if False and any("),
    ("拆掉 G08 跨会话熔断", "if trips >= self.p.session_trips_to_block:", "if False:"),
    ("拆掉 指纹归一化", "for pat, rep in _NORMALIZERS:", "for pat, rep in []:"),
    ("拆掉 原始版本基线", "pool = ([self.base] if self.base else []) + self.history", "pool = self.history"),
    ("拆掉 停下后拒绝新轮次", "if self.stopped:\n            return Decision(\"stop\", \"G00\"", "if False:\n            return Decision(\"stop\", \"G00\""),
]
caught = 0
for name, old, new in CUTS:
    if old not in SRC:
        print(f"无法施加  {name}（源码已变，更新本脚本）"); continue
    tmp = tempfile.mkdtemp(prefix="fgm-")
    try:
        shutil.copy(os.path.join(HERE, "fix_guard_sim.py"), tmp)
        open(os.path.join(tmp, "fix_guard.py"), "w", encoding="utf-8").write(SRC.replace(old, new, 1))
        try:
            r = subprocess.run([sys.executable, "-I", os.path.join(tmp, "fix_guard_sim.py")], capture_output=True, text=True, timeout=60)
            failed = r.returncode != 0
            why = next((l for l in r.stdout.splitlines() if l.startswith("失败")), "")
        except subprocess.TimeoutExpired:
            failed, why = True, "超时（刹车拆掉后真的停不下来）"
        caught += failed
        print(("测试发现  " if failed else "测试没发现  ") + name + (f"  ← {why[:60]}" if failed else ""))
    finally:
        shutil.rmtree(tmp)
print(f"守卫反向测试：{caught}/{len(CUTS)} 被发现")
sys.exit(0 if caught == len(CUTS) else 1)
