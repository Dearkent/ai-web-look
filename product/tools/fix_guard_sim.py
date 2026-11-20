#!/usr/bin/env python3
"""修复回路守卫的模拟测试：每种“停不下来”的修复都要被刹住，正常的修复不能被误杀。

用法：timeout 60 python3 -I -u fix_guard_sim.py
"""
import os, random, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_guard import Attempt, FixGuard, Policy, fingerprint  # noqa: E402

E_TS = "TypeError: Cannot read properties of undefined (reading 'map') at Menu.tsx:{l}:{c}"
E_IMPORT = "Module not found: Can't resolve './Price' in '/tmp/build-{r}/src'"
E_CSS = "PostCSS: Unknown word at styles.css line {l}"
E_HYDR = "Hydration failed because the initial UI does not match what was rendered on the server"

failures = []
passed = []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + (f"  {detail}" if detail and not cond else ""))
    (passed if cond else failures).append(name)


def run(steps, policy=None, memory=None, preflight=None, base=None):
    """steps: 每轮修复后的 Attempt。返回 (每轮决定列表, 守卫)。守卫说停或修好就不再继续。"""
    g = FixGuard(policy or Policy(), memory_path=memory)
    if base is not None:
        g.baseline(*base)
    out = []
    if preflight is not None:
        d = g.preflight(preflight)
        out.append(d)
        if d.verdict == "stop":
            return out, g
    for a in steps:
        d = g.record(a)
        out.append(d)
        if d.verdict in ("stop", "done"):
            break
    return out, g


def A(errs, state="", patch="", snap="", cost=0.1, sec=20, strategy="fast-fix"):
    return Attempt(errors=errs, code_state=state, patch_signature=patch, snapshot=snap,
                   cost=cost, seconds=sec, strategy=strategy)


# 0. 指纹归一化：行号、临时目录变了仍是同一个错；不同的错指纹不同
expect("指纹：行号不同算同一个错",
       fingerprint(E_TS.format(l=12, c=5)) == fingerprint(E_TS.format(l=48, c=9)))
expect("指纹：临时目录不同算同一个错",
       fingerprint(E_IMPORT.format(r="a1b2c3d4")) == fingerprint(E_IMPORT.format(r="9f8e7d6c")))
expect("指纹：不同的错不能混为一谈", fingerprint(E_TS.format(l=1, c=1)) != fingerprint(E_HYDR))
expect("指纹：普通英文单词不被当成哈希抹掉", fingerprint("defaced value") != fingerprint("abcdef0 value"))

# 1. 正常修复：3 → 1 → 0，不能被误杀
d, _ = run([A([E_TS.format(l=1, c=1), E_CSS.format(l=3), E_HYDR], "s1", "p1", "v1"),
            A([E_HYDR], "s2", "p2", "v2"), A([], "s3", "p3", "v3")])
expect("正常修复：两轮后修好，没有被刹车", [x.verdict for x in d] == ["continue", "continue", "done"], [x.verdict for x in d])

# 2. 同一个错反复出现（行号每次都变）：第 2 次提醒，第 3 次停
d, _ = run([A([E_TS.format(l=10 + i, c=i)], f"s{i}", f"p{i}", f"v{i}") for i in range(10)])
expect("同错重复：第 2 轮提醒换思路", d[1].verdict == "nudge" and d[1].code == "G02", d[1])
expect("同错重复：第 3 轮停下（G02）", d[-1].verdict == "stop" and d[-1].code == "G02" and len(d) == 3,
       [(x.verdict, x.code) for x in d])
expect("同错重复：停下时退回存档点", d[-1].rollback_to == "v0", d[-1].rollback_to)
expect("同错重复：给用户的话说明了试过什么", "fast-fix" in d[-1].to_user and "3 轮" in d[-1].to_user, d[-1].to_user)

# 3. 修 A 坏 B、修 B 又坏 A（错误集合振荡，代码每次不同）
d, _ = run([A([E_TS.format(l=1, c=1)], "s1", "p1", "v1"), A([E_IMPORT.format(r="x1x1x1x1")], "s2", "p2", "v2"),
            A([E_TS.format(l=7, c=2)], "s3", "p3", "v3"), A([E_IMPORT.format(r="y2")], "s4", "p4", "v4")])
expect("来回振荡：第 3 轮识别出 A→B→A 并停下（G03）", d[-1].code == "G03" and len(d) == 3, [(x.verdict, x.code) for x in d])

# 4. 代码改回了以前的版本
d, _ = run([A([E_TS.format(l=1, c=1)], "S-A", "p1", "v1"), A([E_CSS.format(l=2)], "S-B", "p2", "v2"),
            A([E_HYDR], "S-A", "p3", "v3")])
expect("代码回到旧版本：停下（G03）", d[-1].code == "G03", [(x.verdict, x.code) for x in d])

# 5. 同一个补丁又打一遍
d, _ = run([A([E_TS.format(l=1, c=1)], "s1", "PATCH", "v1"), A([E_CSS.format(l=2)], "s2", "PATCH", "v2")])
expect("同一补丁重复：停下（G07）", d[-1].code == "G07", [(x.verdict, x.code) for x in d])

# 6. 越修越坏：2 个错 → 8 个错，回滚到最好一版
many = [f"Lint error no-unused-vars '{v}'" for v in "abcdefgh"]
d, _ = run([A([E_TS.format(l=1, c=1), E_CSS.format(l=1)], "s1", "p1", "GOOD"), A(many, "s2", "p2", "BAD"),
            A([E_HYDR], "s3", "p3", "v3"), A([], "s4", "p4", "v4")])
expect("越修越坏：回滚到报错最少的一版（G05）", d[1].code == "G05" and d[1].rollback_to == "GOOD", d[1])
expect("越修越坏：回滚后还能继续修好", d[-1].verdict == "done", [(x.verdict, x.code) for x in d])

# 7. 没有进展（每轮报错不同，数量不降）：先换策略
noisy = lambda i: [f"Error {i}-{k}: something odd in block {chr(65 + i)}{chr(75 + k)}" for k in range(4)]
d, _ = run([A(noisy(i), f"s{i}", f"p{i}", f"v{i}") for i in range(12)], Policy(max_attempts=12))
codes = [(x.verdict, x.code) for x in d]
expect("没有进展：先换策略（G04）", ("switch_strategy", "G04") in codes, codes)
expect("没有进展：策略用完后停下（G04）", codes[-1] == ("stop", "G04"), codes)
expect("没有进展：总轮数不超过上限", len(d) <= 12, len(d))

# 8. 预算：每轮很贵
d, _ = run([A(noisy(i), f"s{i}", f"p{i}", f"v{i}", cost=0.9) for i in range(10)])
expect("花费超限：第 3 轮停下（G06）", d[-1].code == "G06" and len(d) == 3, [(x.verdict, x.code) for x in d])
d, _ = run([A(noisy(i), f"s{i}", f"p{i}", f"v{i}", sec=400) for i in range(10)])
expect("时间超限：第 2 轮停下（G06）", d[-1].code == "G06" and len(d) == 2, [(x.verdict, x.code) for x in d])

# 9. 慢慢在进步但一直修不完：硬上限
d, _ = run([A([f"E{k}" for k in range(10 - i)], f"s{i}", f"p{i}", f"v{i}") for i in range(10)])
expect("一直在进步但修不完：第 5 轮硬上限停下（G01）", d[-1].code == "G01" and len(d) == 5, [(x.verdict, x.code) for x in d])

# 10. 停下以后再调用：不接受新轮次
_, g = run([A([E_HYDR], "s1", "p1", "v1"), A([E_HYDR], "s2", "p2", "v2"), A([E_HYDR], "s3", "p3", "v3")])
late = g.record(A([E_CSS.format(l=9)], "s9", "p9", "v9"))  # 换一个全新的错误，别的刹车都不会触发
expect("停下后再调用：即使换了新错误也仍然是停（G00）", late.verdict == "stop" and late.code == "G00", late)

# 11. 跨会话熔断：同一组错误已在 2 个会话里停过，第 3 个会话开工前直接问人
mem = os.path.join(tempfile.mkdtemp(prefix="fg-"), "fix_memory.json")
for sess in range(2):
    run([A([E_HYDR], f"s{sess}{i}", f"p{sess}{i}", f"v{i}") for i in range(5)], memory=mem)
d, _ = run([A([E_HYDR], "x", "y", "z")], memory=mem, preflight=[E_HYDR])
expect("跨会话熔断：第 3 次会话开工前就停下问人（G08）", d[0].code == "G08" and "不再自动重试" in d[0].to_user, d[0])
d, _ = run([], memory=mem, preflight=[E_CSS.format(l=1)])
expect("跨会话熔断：别的错误不受影响", d[0].verdict == "continue")

# 13. 原始版本基线：第一轮就越修越坏，要退回原始版本
many = [f"Lint error no-unused-vars '{v}'" for v in "abcdefgh"]
d, _ = run([A(many, "s1", "p1", "R1"), A([], "s2", "p2", "R2")], base=([E_TS.format(l=1, c=1), E_CSS.format(l=1)], "ORIG", "s0"))
expect("基线：第一轮把 2 个错改成 8 个，退回原始版本（G05）", d[0].code == "G05" and d[0].rollback_to == "ORIG", d[0])
# 14. 原始版本基线：第一轮什么都没改好（报错与原始完全相同），第 1 轮就提醒，第 2 轮停
d, _ = run([A([E_HYDR], f"t{i}", f"p{i}", f"v{i}") for i in range(5)], base=([E_HYDR], "ORIG", "s0"))
expect("基线：报错与原始相同，第 1 轮提醒、第 2 轮停（G02）", [(x.verdict, x.code) for x in d] == [("nudge", "G02"), ("stop", "G02")],
       [(x.verdict, x.code) for x in d])
# 15. 原始版本基线：代码被改回原始版本也算振荡
d, _ = run([A([E_CSS.format(l=1)], "s1", "p1", "v1"), A([E_IMPORT.format(r="q")], "s0", "p2", "v2")], base=([E_HYDR], "ORIG", "s0"))
expect("基线：代码改回原始版本（G03）", d[-1].code == "G03", [(x.verdict, x.code) for x in d])

# 12. 随机对抗：2000 条随机修复序列，守卫必须在 max_attempts 轮内给出 stop 或 done
rng = random.Random(20261118)
pool = [E_TS.format(l=1, c=1), E_IMPORT.format(r="r"), E_CSS.format(l=1), E_HYDR] + [f"Err{k}" for k in range(8)]
worst = 0
bad = 0
for trial in range(2000):
    p = Policy(max_attempts=rng.randint(1, 8), max_cost=1e9, max_seconds=1e9)
    steps = []
    for i in range(50):
        errs = rng.sample(pool, rng.randint(1, 6))  # 永远修不好
        steps.append(A(errs, f"s{rng.randint(0, 30)}" if rng.random() < .5 else "",
                       f"p{rng.randint(0, 30)}" if rng.random() < .5 else "",
                       f"v{i}" if rng.random() < .7 else ""))
    d, _ = run(steps, p)
    worst = max(worst, len(d))
    if d[-1].verdict not in ("stop", "done") or len(d) > p.max_attempts:
        bad += 1
expect("随机对抗：2000 条永远修不好的序列全部按时停下", bad == 0, f"{bad} 条超限")
expect("随机对抗：最长不超过 8 轮", worst <= 8, worst)

print(f"修复守卫模拟：{len(passed)}/{len(passed) + len(failures)} 通过")
sys.exit(1 if failures else 0)
