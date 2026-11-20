#!/usr/bin/env python3
"""修复回路守卫：让“报错 → 修复 → 再报错”的自动修复一定会停下来。

用法（编排 Agent 每轮修复后调用一次）：
    g = FixGuard(Policy(), memory_path="fix_memory.json")
    d = g.preflight(errors)            # 开工前：这个错误以前是否已经让我们停过
    d = g.record(Attempt(...))         # 每轮修复后：继续 / 提醒 / 换策略 / 停下并回滚
保证（由 fix_guard_sim.py 的随机测试验证）：
  * 无论修复结果如何，record() 最多被调用 max_attempts 次就会返回 stop 或 done；
  * 守卫本身没有 while 循环，每次调用的工作量与历史长度成正比。

学自（只读，未复用代码）：
  OpenHands StuckDetector —— 同动作同结果 / 同动作连续报错 / ABAB 来回 / 先提醒一次再判卡住 / 步数与花费上限 / 恢复后清窗；
  VibeSDK LoopDetector —— 同工具同参数重复检测、文本复读直接中断生成（它只提醒不强停，是我们要避免的弱点）；
  Dyad —— 修补失败最多重试 2 次、并检查取消信号。
我们额外补上的：错误指纹归一化（行号变了也算同一个错）、“修 A 坏 B、修 B 坏 A”的错误集合振荡、
代码回到旧版本、错误越修越多时回滚到最好的那一版、以及跨会话熔断（同一个错已让我们停过两次，下次直接问人）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 归一化


_NORMALIZERS = [
    (re.compile(r"\x1b\[[0-9;]*m"), ""),                                 # 终端颜色
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][\d:.]+Z?\b"), "<time>"),      # 时间戳
    (re.compile(r"0x[0-9a-fA-F]+"), "<addr>"),                           # 内存地址
    (re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b"), "<hash>"),        # 提交号、内容哈希（至少含一个数字，免得误伤 defaced 这类单词）
    (re.compile(r"/tmp/[^\s:'\"]+"), "<tmp>"),                           # 临时路径
    (re.compile(r"\?v=[\w-]+|\.[0-9a-f]{8}\.(js|css)"), "<bust>"),       # 构建产物指纹
    (re.compile(r"(:\d+){1,2}\b"), ":<pos>"),                            # 行号:列号
    (re.compile(r"\b(line|col|column|行|列)\s*\d+", re.I), r"\1 <n>"),
    (re.compile(r"\s+"), " "),
]


def fingerprint(message: str) -> str:
    """同一个错误换了行号、时间、临时路径，指纹不变。"""
    s = message.strip()
    for pat, rep in _NORMALIZERS:
        s = pat.sub(rep, s)
    return hashlib.sha1(s.lower().encode("utf-8")).hexdigest()[:12]


def errorset(errors: list[str]) -> frozenset:
    return frozenset(fingerprint(e) for e in errors)


# ---------------------------------------------------------------- 数据


@dataclass
class Policy:
    max_attempts: int = 5          # G01 硬上限：任何情况下最多修这么多轮
    same_error_nudge: int = 2      # G02 同一组错误连续出现第 2 次：提醒换思路
    same_error_stop: int = 3       # G02 连续第 3 次：停
    no_progress_window: int = 3    # G04 连续 3 轮没有比最好成绩更少的错误：先换策略，再不行就停
    regression_factor: float = 2.0  # G05 错误数超过最好成绩的 2 倍（且至少多 3 个）：回滚
    max_cost: float = 2.0          # G06 花费上限（美元）
    max_seconds: float = 600.0     # G06 时间上限（秒）
    session_trips_to_block: int = 2  # G08 同一组错误在 2 个会话里都让我们停过：下次不再自动修


@dataclass
class Attempt:
    errors: list[str]                      # 修完之后仍然存在的报错（原文）
    code_state: str = ""                   # 修完之后代码的内容哈希（所有改动文件拼起来）
    patch_signature: str = ""              # 这次修补本身的哈希（同一个补丁又打一遍 = 原地打转）
    snapshot: str = ""                     # 这一轮之后的存档点 ID，用于回滚
    cost: float = 0.0
    seconds: float = 0.0
    strategy: str = "fast-fix"


@dataclass
class Decision:
    verdict: str                   # done | continue | nudge | switch_strategy | stop
    code: str = ""                 # G01–G08
    reason: str = ""
    to_model: str = ""             # 注入给修复模型的话
    to_user: str = ""              # 停下时给用户看的话
    rollback_to: str | None = None
    next_strategy: str | None = None
    lesson: dict = field(default_factory=dict)  # 交给学习 Agent 的经验草稿


STRATEGY_LADDER = ["fast-fix", "deep-debug", "rewrite-file"]  # 换策略的顺序；用完就停

# ---------------------------------------------------------------- 守卫


class FixGuard:
    def __init__(self, policy: Policy | None = None, memory_path: str | None = None):
        self.p = policy or Policy()
        self.memory_path = memory_path
        self.history: list[tuple[Attempt, frozenset]] = []
        self.nudged_for: set = set()
        self.strategy_i = 0
        self.cost = 0.0
        self.seconds = 0.0
        self.stopped = False
        self.base: tuple[Attempt, frozenset] | None = None

    def baseline(self, errors: list[str], snapshot: str = "", code_state: str = ""):
        """登记修复开始前的样子（不算一轮）。越修越坏时可以退回这里；改回原样也算振荡。"""
        self.base = (Attempt(errors=errors, snapshot=snapshot, code_state=code_state, strategy="原始版本"),
                     errorset(errors))

    # ---------- 跨会话记忆 ----------
    def _mem(self) -> dict:
        if not self.memory_path or not os.path.exists(self.memory_path):
            return {}
        try:
            return json.load(open(self.memory_path, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _remember_trip(self, es: frozenset, code: str):
        if not self.memory_path or not es:
            return
        m = self._mem()
        key = ",".join(sorted(es))
        e = m.setdefault(key, {"trips": 0, "codes": []})
        e["trips"] += 1
        e["codes"] = (e["codes"] + [code])[-10:]
        tmp = self.memory_path + ".tmp"
        json.dump(m, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, self.memory_path)

    def preflight(self, errors: list[str]) -> Decision:
        """开工前调用：同一组错误已经在多个会话里让自动修复停下过，就不要再自动修了。"""
        es = errorset(errors)
        if not es:
            return Decision("done", reason="没有报错")
        trips = self._mem().get(",".join(sorted(es)), {}).get("trips", 0)
        if trips >= self.p.session_trips_to_block:
            self.stopped = True
            return Decision(
                "stop", "G08", f"这组错误已在 {trips} 个会话里让自动修复停下",
                to_user="这个问题之前自动修复过 %d 次都没成功，这次我不再自动重试。"
                        "能否告诉我你期望的效果，或者允许我换一种做法（例如重写这个页面）？" % trips,
                lesson={"fingerprints": sorted(es), "pattern": "跨会话反复失败"})
        return Decision("continue")

    # ---------- 主判断 ----------
    def record(self, a: Attempt) -> Decision:
        if self.stopped:
            return Decision("stop", "G00", "守卫已停止，不接受新的修复轮次")
        es = errorset(a.errors)
        self.history.append((a, es))
        self.cost += a.cost
        self.seconds += a.seconds
        n = len(self.history)

        if not es:
            return Decision("done", reason=f"第 {n} 轮修好")

        counts = [len(h[1]) for h in self.history]
        pool = ([self.base] if self.base else []) + self.history   # 候选“最好版本”包括原始版本
        pcounts = [len(h[1]) for h in pool]
        best_j = min(range(len(pool)), key=lambda i: (pcounts[i], i))
        best = pool[best_j][0]
        best_count = pcounts[best_j]
        seq = pool  # 振荡、连续同错都把原始版本算进去

        def stop(code, reason, rollback=True):
            self.stopped = True
            self._remember_trip(es, code)
            tried = "、".join(dict.fromkeys(h[0].strategy for h in self.history))
            rb = best.snapshot if rollback and best.snapshot else None
            msg = (f"自动修复已停止（{reason}）。一共试了 {n} 轮，用过的办法：{tried}。"
                   + (f"已退回到报错最少的那一版（{best_count} 个报错）。" if rb else "")
                   + "需要你确认下一步：描述期望效果、允许我换做法，或者先保留现状。")
            return Decision("stop", code, reason, to_user=msg, rollback_to=rb,
                            lesson={"fingerprints": sorted(es), "pattern": code, "attempts": n,
                                    "errors_per_attempt": counts, "strategies": tried})

        # G06 预算
        if self.cost >= self.p.max_cost or self.seconds >= self.p.max_seconds:
            return stop("G06", f"花费 {self.cost:.2f} 美元 / {self.seconds:.0f} 秒，达到上限")

        # G07 同一个补丁又打一遍
        if a.patch_signature and any(h[0].patch_signature == a.patch_signature for h in self.history[:-1]):
            return stop("G07", "同一个补丁被重复应用，原地打转")

        # G03 振荡：代码回到以前某个版本，或错误集合 A→B→A
        if a.code_state and any(h[0].code_state == a.code_state for h in seq[:-1]):
            return stop("G03", "代码改回了之前出现过的版本，修复在来回振荡")
        if len(seq) >= 3 and es == seq[-3][1] and es != seq[-2][1]:
            return stop("G03", "修 A 坏 B、修 B 又坏 A，报错在两组之间来回")

        # G02 同一组错误连续出现
        streak = 1
        for h in reversed(seq[:-1]):
            if h[1] != es:
                break
            streak += 1
        if streak >= self.p.same_error_stop:
            return stop("G02", f"同一组报错连续出现 {streak} 次")

        # G05 越修越坏：回滚到最好的一版后继续一次（不算停）
        if counts[-1] >= max(best_count * self.p.regression_factor, best_count + 3) and best.snapshot:
            if n >= self.p.max_attempts:
                return stop("G01", f"达到 {self.p.max_attempts} 轮上限")
            return Decision("continue", "G05", f"报错从 {best_count} 个涨到 {counts[-1]} 个",
                            to_model=f"上一次修改让报错从 {best_count} 个增加到 {counts[-1]} 个，已撤销。"
                                     "请从报错最少的版本重新开始，只改与报错直接相关的代码。",
                            rollback_to=best.snapshot)

        # G01 硬上限（放在所有“继续”分支之前，保证一定终止）
        if n >= self.p.max_attempts:
            return stop("G01", f"达到 {self.p.max_attempts} 轮上限")

        # G04 没有进展：换策略；策略用完就停
        w = self.p.no_progress_window
        before = ([len(self.base[1])] if self.base else []) + counts[:-w]
        if n >= w and before and min(counts[-w:]) >= min(before):
            if self.strategy_i + 1 < len(STRATEGY_LADDER):
                self.strategy_i += 1
                nxt = STRATEGY_LADDER[self.strategy_i]
                return Decision("switch_strategy", "G04", f"连续 {w} 轮没有比最好成绩更好",
                                to_model=f"最近 {w} 轮修复没有减少报错。换用 {nxt}：先重新读相关文件和完整报错，"
                                         "说出根因假设，再动手。",
                                next_strategy=nxt, rollback_to=best.snapshot or None)
            return stop("G04", f"连续 {w} 轮没有进展，所有策略都试过了")

        # G02 提醒：同一组错误第 2 次（每组只提醒一次）
        if streak >= self.p.same_error_nudge and es not in self.nudged_for:
            self.nudged_for.add(es)
            return Decision("nudge", "G02", f"同一组报错连续出现 {streak} 次",
                            to_model="同样的报错又出现了，说明上一次的修法没有命中根因。不要重复上一次的改法："
                                     "先列出两个不同的根因假设，选证据最强的一个，再改。")
        return Decision("continue")
