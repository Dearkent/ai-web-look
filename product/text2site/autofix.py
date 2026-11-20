#!/usr/bin/env python3
"""自我纠错：生成 → 检查 → 诊断 → 修补 → 复查，有刹车；修好的变成“预防”，下次提前避开。

一次构建的流程（run）：
  0. 预防：查纠错记忆，这次的需求带有某个已知病因（例如名字里有很长的英文单词），就提前用上对应修补。
  1. 生成并检查（图纸检查 + 真实浏览器）。
  2. 有问题 → 按问题类别 + 浏览器诊断选修补（封闭清单 generate.FIX_CSS，不写任意代码）。
     不认识的问题不瞎修：直接报告“这个我还不会自动修”，并记进待学清单。
  3. 重新生成、复查，交给 FixGuard 判断（最多 4 轮、原地打转、振荡、越修越坏都会停）。
     修补带来新问题 → 撤回这个修补（不会为了消掉一个报错去藏起另一个）。
  4. 修好的写进纠错记忆：哪类问题、用了哪个修补、病因是什么。
记忆本身也会被纠正：
  * 预防用上了却仍然出同样的问题 → 记一次失手；失手多于成功 → 停用。
  * generalize：在另外两个行业 × 风格家族上做对照实验（去掉修补问题会出现、加上就消失），
    通过了才把适用范围从“同行业同家族”放宽到“所有带这个病因的网站”（举一反十，但要先验证）。
  * 推广建议：同一修补在 3 次以上、2 个以上行业里成功 → 建议写进生成器默认样式（要经过验证门，不自动改代码）。

用法：python3 -I autofix.py memory | generalize | demo
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, "..", "gen"))
import learned  # noqa: E402
from fix_guard import Attempt, FixGuard, Policy  # noqa: E402
from generate import FIX_CSS  # noqa: E402
from make_site import build_one  # noqa: E402

LONG_WORD = re.compile(r"[A-Za-z0-9_\-.@/:]{15,}")

# 问题类别 → 怎么选修补。诊断类别（浏览器给的 kind）→ 修补名。
OVERFLOW_BY_KIND = {"text": "wrap-long-words", "media": "media-fit", "table": "table-scroll", "pre": "pre-wrap"}
SIMPLE = {"首屏内容看不见": "reveal-visible", "点按区域太小": "tap-targets"}
# 每个修补对应的“病因”：从需求里能看出来的特征。病因相同的别的网站，下次就提前用上这个修补。
CAUSE = {"wrap-long-words": "long_word", "reveal-visible": "motion", "media-fit": "media", "table-scroll": "table", "pre-wrap": "code"}
CAUSE_ZH = {"long_word": "名字或文字里有很长的英文单词/网址", "motion": "页面带入场动画", "media": "页面有图片或嵌入内容",
            "table": "页面有表格", "code": "页面有代码块"}
CATEGORY_ZH = {"横向溢出": "手机上内容比屏幕宽", "首屏内容看不见": "首屏内容看不见", "点按区域太小": "手机上按钮或链接太小不好点"}


def memory_path() -> str:
    return os.path.join(learned.knowledge_dir(), "fix_memory.json")


def _load() -> dict:
    try:
        return json.load(open(memory_path(), encoding="utf-8"))
    except (OSError, ValueError):
        return {"entries": [], "unfixed": []}


def _save(m: dict):
    os.makedirs(learned.knowledge_dir(), exist_ok=True)
    tmp = memory_path() + ".tmp"
    json.dump(m, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, memory_path())


def features(brief: dict) -> dict:
    words = " ".join([brief.get("site_name", ""), brief.get("brand", {}).get("name", ""), brief["audience"]["primary"]])
    return {"long_word": bool(LONG_WORD.search(words)), "motion": brief["style_preference"]["motion_tier"] != "Subtle",
            "media": False, "table": False, "code": False}


def category(problem: str) -> str:
    m = re.match(r"浏览器·([^：（(]+)", problem)
    return m.group(1) if m else ("图纸" if re.match(r"[A-Z]\d", problem) else problem[:12])


def _family(style_id):
    import styles
    return styles.family(style_id)


def _promoted() -> set:
    import generate
    return set() if os.environ.get("AISITE_SIMULATE_OLD_GENERATOR") == "1" else set(generate.PROMOTED)


def prevent(brief: dict, style_id: str) -> list[dict]:
    """返回要提前用上的修补 [{"fix","entry","why"}]。已经升格进默认样式的不用再提前加。"""
    f, out = features(brief), []
    for e in _load()["entries"]:
        if e["status"] != "active" or not f.get(e["cause"]) or e["fix"] in _promoted():
            continue
        if e["scope"] == "narrow" and (e["product_type"], e["family"]) != (brief["product_type"]["value"], _family(style_id)):
            continue
        out.append({"fix": e["fix"], "entry": e["id"], "why": f"{CAUSE_ZH[e['cause']]} → 提前{FIX_CSS[e['fix']][0]}（{e['id']}）"})
    return out


def choose(problems: list[str], detail: dict, tried: set) -> tuple[list[str], list[str]]:
    """返回 (这一轮要加的修补, 不会修的问题)。"""
    add, unknown = [], []
    for p in problems:
        c = category(p)
        if c == "横向溢出":
            kinds = [w["kind"] for ws in detail.get("wide", {}).values() for w in ws]
            picks = [OVERFLOW_BY_KIND[k] for k in kinds if k in OVERFLOW_BY_KIND]
            picks = [x for x in dict.fromkeys(picks) if x not in tried]
            if picks:
                add += picks
            else:
                unknown.append(p + ("（诊断：" + "、".join(sorted(set(kinds))) + "）" if kinds else ""))
        elif c in SIMPLE and SIMPLE[c] not in tried:
            add.append(SIMPLE[c])
        else:
            unknown.append(p)
    return list(dict.fromkeys(add)), list(dict.fromkeys(unknown))


def _sig(xs) -> str:
    return hashlib.sha1(",".join(sorted(xs)).encode()).hexdigest()[:12]


def run(brief: dict, style_id: str, out: str, run_browser: bool = True, learn: bool = True, use_memory: bool = True,
        copy_overlay: dict | None = None, tweaks: dict | None = None) -> dict:
    """带自我纠错的构建。返回最后一版（或报错最少的一版）的构建结果，外加 "selffix" 报告。"""
    t0 = time.time()
    pre = prevent(brief, style_id) if use_memory else []
    fixes = [p["fix"] for p in pre]
    guard = FixGuard(Policy(max_attempts=4, max_seconds=240))
    rounds, unknown_all, credited, reverted = [], [], {}, []
    detail = {}
    r = build_one(brief, style_id, os.path.join(out, "r0"), run_browser, fixes, detail, copy_overlay, tweaks)
    problems = r["blueprint_errors"] + r["browser_problems"]
    rounds.append({"round": 0, "fixes": list(fixes), "problems": problems})
    guard.baseline(problems, snapshot="r0", code_state=_sig(fixes))
    best = (len(problems), r, list(fixes))
    tried = set(fixes)
    stop_reason = "第一次生成就没有问题" if not problems else ""
    n = 0
    while problems:
        add, unknown = choose(problems, detail, tried)
        unknown_all += [u for u in unknown if u not in unknown_all]
        if not add:
            stop_reason = "剩下的问题我还不会自动修，已记进待学清单"
            break
        n += 1
        tried |= set(add)
        before = {category(p) for p in problems}
        cand = fixes + add
        prev_detail, detail = detail, {}
        r2 = build_one(brief, style_id, os.path.join(out, f"r{n}"), run_browser, cand, detail, copy_overlay, tweaks)
        p2 = r2["blueprint_errors"] + r2["browser_problems"]
        after = {category(p) for p in p2}
        rounds.append({"round": n, "fixes": list(cand), "added": add, "problems": p2})
        d = guard.record(Attempt(errors=p2, code_state=_sig(cand), patch_signature=_sig(add), snapshot=f"r{n}",
                                 seconds=time.time() - t0, strategy="+".join(add)))
        harmful, useless = after - before, not (before - after) and len(p2) >= len(problems)
        if harmful or useless:  # 带来新问题或没效果：撤回，不拿新问题换旧问题，也不留没用的修补
            reverted.append({"fixes": add, "why": "带来新问题：" + "、".join(sorted(harmful)) if harmful else "没有效果"})
            detail = prev_detail
            if d.verdict == "stop":
                stop_reason = f"刹车 {d.code}：{d.reason}"
                break
            continue
        for c in before - after:
            credited[c] = add
        fixes, problems, r = cand, p2, r2
        if len(p2) < best[0]:
            best = (len(p2), r2, list(cand))
        if d.verdict == "done":
            stop_reason = f"第 {n} 轮修好"
            break
        if d.verdict == "stop":
            stop_reason = f"刹车 {d.code}：{d.reason}"
            break
    if problems and best[0] < len(problems):
        _, r, fixes = best
        problems = r["blueprint_errors"] + r["browser_problems"]
    report = {"prevented": pre, "rounds": rounds, "fixed": [], "unfixed": unknown_all, "reverted": reverted,
              "final_fixes": fixes, "stop": stop_reason, "remaining": problems, "learned": [], "misses": []}
    for c, fx in credited.items():
        report["fixed"].append({"category": c, "zh": CATEGORY_ZH.get(c, c), "fixes": fx,
                                "how": "；".join(FIX_CSS[x][0] for x in fx)})
    if learn:
        _learn(brief, style_id, report)
    r = dict(r)
    r["selffix"] = report
    return r


def _learn(brief, style_id, report):
    m = _load()
    ptype, fam = brief["product_type"]["value"], _family(style_id)
    remaining = {category(p) for p in report["remaining"]}
    # 预防失手：提前用了修补，同类问题还是出现了
    for p in report["prevented"]:
        e = next(x for x in m["entries"] if x["id"] == p["entry"])
        cat = e["category"]
        if cat in {category(x) for x in report["rounds"][0]["problems"]}:
            e["misses"] += 1
            report["misses"].append(e["id"])
            if e["misses"] >= 2 and e["misses"] > e["wins"]:
                e["status"], e["retired_reason"] = "retired", f"提前用了 {e['misses']} 次仍出同样问题"
        else:
            e["prevented"] = e.get("prevented", 0) + 1
    f = features(brief)
    for fx in report["fixed"]:
        for fix in fx["fixes"]:
            cause = CAUSE.get(fix)
            if not cause or not f.get(cause):
                continue  # 看不出病因的修补不做预防，免得乱用
            e = next((x for x in m["entries"] if x["fix"] == fix and x["cause"] == cause and x["status"] == "active"), None)
            if e is None:
                e = {"id": "M%03d" % (len(m["entries"]) + 1), "category": fx["category"], "fix": fix, "cause": cause,
                     "scope": "narrow", "product_type": ptype, "family": fam, "wins": 0, "misses": 0, "prevented": 0,
                     "industries": [], "status": "active", "since": time.strftime("%Y-%m-%d %H:%M")}
                m["entries"].append(e)
            e["wins"] += 1
            if ptype not in e["industries"]:
                e["industries"].append(ptype)
            report["learned"].append({"id": e["id"], "what": f"{CAUSE_ZH[cause]} → {FIX_CSS[fix][0]}", "scope": e["scope"]})
    for u in report["unfixed"]:
        c = category(u)
        row = next((x for x in m["unfixed"] if x["category"] == c), None)
        if row is None:
            m["unfixed"].append({"category": c, "count": 1, "example": u[:160]})
        else:
            row["count"] += 1
    _save(m)


GENERAL_PROBES = [("帮我做个律师事务所的官网", "minimalism-and-swiss-style"), ("开了家健身房，想让人报名体验课", "neubrutalism"),
                  ("帮我做个花店的网站", "soft-ui-evolution")]
CAUSE_SAMPLE = {"long_word": lambda b: b.update(site_name="Supercalifragilisticexpialidociousstudio") or
                b["brand"].update(name=b["site_name"])}


def generalize(entry_id: str | None = None, probes: int = 2) -> list[dict]:
    """对照实验：在别的行业 × 风格家族上，带着病因各建两次（不加修补 / 加修补）。
    不加时出现该类问题、加了就消失 → 这个修补对这个病因普遍有效，范围放宽到 general。"""
    from understand import understand
    m = _load()
    out = []
    for e in m["entries"]:
        if e["status"] != "active" or e["scope"] != "narrow" or (entry_id and e["id"] != entry_id):
            continue
        if e["cause"] not in CAUSE_SAMPLE:
            out.append({"id": e["id"], "ok": False, "reason": "这个病因还没有对照样本，保持窄范围"})
            continue
        results = []
        for text, sid in [p for p in GENERAL_PROBES if _family(p[1]) != e["family"]][:probes]:
            b = understand(text)
            CAUSE_SAMPLE[e["cause"]](b)
            d0 = tempfile.mkdtemp(prefix="gen0-")
            r0 = build_one(b, sid, d0, True, [])
            r1 = build_one(b, sid, tempfile.mkdtemp(prefix="gen1-"), True, [e["fix"]])
            had = any(category(p) == e["category"] for p in r0["browser_problems"])
            gone = not any(category(p) == e["category"] for p in r1["browser_problems"])
            new = {category(p) for p in r1["browser_problems"]} - {category(p) for p in r0["browser_problems"]}
            results.append({"case": f"{b['product_type']['value']} × {_family(sid)}", "without": had, "with_fixed": gone, "new": sorted(new)})
        ok = bool(results) and all(x["without"] and x["with_fixed"] and not x["new"] for x in results)
        if ok:
            e["scope"] = "general"
            e["generalized"] = {"at": time.strftime("%Y-%m-%d %H:%M"), "cases": [x["case"] for x in results]}
        e["last_check"] = results
        out.append({"id": e["id"], "ok": ok, "results": results})
    _save(m)
    return out


def suggestions() -> list[str]:
    """该写进生成器默认样式的修补（只是建议，要人确认 + 过验证门）；已经升格的写明。"""
    out = []
    for e in _load()["entries"]:
        if e["fix"] in _promoted():
            out.append(f"{e['id']}：{FIX_CSS[e['fix']][0]} 已升格进生成器默认样式，不用再单独修")
        elif e["status"] == "active" and e["scope"] == "general" and e["wins"] >= 3 and len(e["industries"]) >= 2:
            out.append(f"{e['id']}：{FIX_CSS[e['fix']][0]} 已在 {len(e['industries'])} 个行业成功 {e['wins']} 次，建议写进生成器默认样式")
    return out


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["memory"])[0]
    if cmd == "memory":
        print(json.dumps(_load(), ensure_ascii=False, indent=1))
    elif cmd == "generalize":
        print(json.dumps(generalize(), ensure_ascii=False, indent=1))
    elif cmd == "suggest":
        print("\n".join(suggestions()) or "暂无")
