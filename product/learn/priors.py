#!/usr/bin/env python3
"""设计先验：从语料库（corpus/specimens.jsonl）提炼“同行网站通常怎么排、用多大的字、留多少白”，
再经过试跑（真的生成网站、过检查）才让生成器用上。

自我纠错和防死循环：
  * 样本少于 MIN_N 个的行业不提炼——几个样本说明不了什么。
  * 同行做法不一致（区块先后顺序的一致度低于 MIN_AGREE）→ 不采纳顺序，写明原因。
  * 每个先验有指纹（来自哪些标本 + 统计结果）。试跑过的指纹不再重跑：
    没有新数据就不会反复“试 → 拒 → 再试”。喂了新网站、指纹变了，才再试一次。
  * 试跑：同一句需求、同一风格，用先验和不用先验各生成一次。用了先验图纸必须 0 错误、浏览器问题不多于不用时，才采纳。
  * 生成时设环境变量 AISITE_PRIORS=off 可以整个关掉（对照实验和排查问题用）。

用法：python3 -I priors.py build | trial | show
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import corpus  # noqa: E402
import events  # noqa: E402

MIN_N = 5
MIN_AGREE = 0.6
MIN_PRESENCE = 0.3
# 标本里的区块类型 → 生成器里会出现的区块类型（同一类的放在一起比较位置）
GROUP = {"value-props": "features", "features": "features", "menu": "catalog", "gallery": "catalog", "contact-form": "contact",
         "map": "contact", "blog-list": "blog", "newsletter": "cta"}


def _path():
    return os.path.join(corpus.CORPUS, "priors.json")


def load() -> dict:
    try:
        return json.load(open(_path(), encoding="utf-8"))
    except (OSError, ValueError):
        return {"industries": {}}


def _save(d):
    os.makedirs(corpus.CORPUS, exist_ok=True)
    tmp = _path() + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, _path())


def g(t: str) -> str:
    return GROUP.get(t, t)


def _positions(seq: list[str]) -> dict[str, float]:
    """一个网站里每类区块第一次出现的相对位置（0 = 紧跟首屏，1 = 最后）。首屏本身不算。"""
    body = [g(t) for t in seq if t != "hero"]
    out = {}
    for i, t in enumerate(body):
        out.setdefault(t, i / max(1, len(body) - 1))
    return out


def agreement(seqs: list[list[str]]) -> float | None:
    """两两比较：两个网站都有的两类区块，先后顺序一样的比例。"""
    pos = [_positions(s) for s in seqs]
    same = total = 0
    for a, b in itertools.combinations(pos, 2):
        common = sorted(set(a) & set(b))
        for x, y in itertools.combinations(common, 2):
            if a[x] == a[y] or b[x] == b[y]:
                continue
            total += 1
            same += (a[x] < a[y]) == (b[x] < b[y])
    return round(same / total, 2) if total else None


def _med(xs):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    if not xs:
        return None
    if len(xs) >= 5:  # 去掉两头的离群值（四分位距外）
        q1, q3 = xs[len(xs) // 4], xs[(3 * len(xs)) // 4]
        iqr = q3 - q1
        xs = [x for x in xs if q1 - 1.5 * iqr <= x <= q3 + 1.5 * iqr] or xs
    return round(statistics.median(xs), 2)


def summarize(specs: list[dict]) -> dict:
    seqs = [s["structure"]["sections"] for s in specs if len(s["structure"]["sections"]) >= 3]
    pos = [_positions(q) for q in seqs]
    types = sorted({t for p in pos for t in p})
    presence = {t: round(sum(1 for p in pos if t in p) / len(pos), 2) for t in types} if pos else {}
    where = {t: round(statistics.median([p[t] for p in pos if t in p]), 2) for t in types}
    order = [t for t in sorted(types, key=lambda t: where[t]) if presence[t] >= MIN_PRESENCE]
    fam = {}
    for s in specs:
        fam[s["family"]] = fam.get(s["family"], 0) + 1
    return {
        "n": len(specs), "n_layouts": len(seqs), "order": order, "presence": presence, "where": where,
        "agreement": agreement(seqs),
        "family": {k: round(v / len(specs), 2) for k, v in sorted(fam.items(), key=lambda kv: -kv[1])},
        "dark_share": round(sum(1 for s in specs if s["color"]["dark"]) / len(specs), 2),
        "type": {"base": _med([s["type"]["base"] for s in specs]), "h1": _med([s["type"]["h1"] for s in specs]),
                 "ratio": _med([s["type"]["ratio"] for s in specs]), "line_height": _med([s["type"]["line_height"] for s in specs]),
                 "serif_heading_share": round(sum(1 for s in specs if s["type"]["heading_cat"] == "serif") / len(specs), 2)},
        "space": {"section_pad": _med([s["space"]["section_pad"] for s in specs]), "container": _med([s["space"]["container"] for s in specs])},
        "shape": {"radius": _med([s["shape"]["radius"] for s in specs])},
        "hero": {"words": _med([s["structure"]["hero_words"] for s in specs]), "buttons": _med([s["structure"]["hero_buttons"] for s in specs]),
                 "image_share": round(sum(1 for s in specs if s["structure"]["hero_image"]) / len(specs), 2)},
        "nav_links": _med([s["structure"]["nav_links"] for s in specs]),
        "sources": sorted(s["id"] for s in specs),
    }


def fingerprint(summary: dict) -> str:
    keep = {k: summary[k] for k in ("sources", "order", "agreement")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]


def build() -> dict:
    """重算统计。已试跑过的同指纹结论保留；指纹变了的回到“候选”，等下次试跑。"""
    specs = corpus.load()
    old = load()
    by = {}
    for s in specs:
        if s.get("industry"):
            by.setdefault(s["industry"], []).append(s)
    out = {"built_at": time.strftime("%Y-%m-%d %H:%M"), "n": len(specs), "min_n": MIN_N, "min_agree": MIN_AGREE,
           "all": summarize(specs) if specs else {}, "industries": {}}
    with events.stage("distill", 标本=len(specs), 行业=len(by)) as st:
        for ind, ss in sorted(by.items()):
            sm = summarize(ss)
            fp = fingerprint(sm)
            prev = old.get("industries", {}).get(ind, {})
            if len(ss) < MIN_N:
                sm.update(status="样本不够", why=f"只有 {len(ss)} 个，至少要 {MIN_N} 个")
            elif sm["agreement"] is not None and sm["agreement"] < MIN_AGREE:
                sm.update(status="不采纳", why=f"同行的区块顺序不一致（一致度 {sm['agreement']}，低于 {MIN_AGREE}）")
            elif prev.get("fingerprint") == fp and prev.get("status") in ("采纳", "拒绝"):
                sm.update(status=prev["status"], why=prev.get("why", ""), trial=prev.get("trial"))
            else:
                sm.update(status="候选", why="等试跑")
            sm["fingerprint"] = fp
            out["industries"][ind] = sm
        st.out(候选=sum(1 for v in out["industries"].values() if v["status"] == "候选"),
               采纳=sum(1 for v in out["industries"].values() if v["status"] == "采纳"))
    _save(out)
    return out


# ---------------------------------------------------------------- 生成器用
def enabled() -> bool:
    return os.environ.get("AISITE_PRIORS", "on").lower() not in ("off", "0", "no")


def for_industry(ind: str, allow_candidate: bool = False) -> dict | None:
    if not enabled():
        return None
    p = load().get("industries", {}).get(ind)
    if not p or not p.get("order"):
        return None
    if p.get("status") == "采纳" or (allow_candidate and p.get("status") == "候选"):
        return p
    return None


def reorder(ind: str, secs: list[dict], allow_candidate: bool = False) -> tuple[list[dict], str]:
    """按同行的常见顺序重排首页中间的区块：首屏永远第一，最后一个行动按钮区块永远最后，不增不减区块。"""
    p = for_industry(ind, allow_candidate)
    if not p or len(secs) < 4:
        return secs, ""
    where = p["where"]
    head = [s for s in secs[:1] if s["type"] == "hero"]
    tail = [secs[-1]] if secs[-1]["type"] == "cta" else []
    mid = secs[len(head):len(secs) - len(tail)]
    n = len(mid)
    def key(item):
        i, s = item
        t = g(s["type"])
        return (where.get(t, i / max(1, n - 1)), i)
    new_mid = [s for _, s in sorted(enumerate(mid), key=key)]
    out = head + new_mid + tail
    changed = [s["id"] for s in out] != [s["id"] for s in secs]
    note = f"首页区块按 {p['n']} 个同行网站的常见顺序排" + ("" if changed else "（和原来一致）")
    return out, note


# ---------------------------------------------------------------- 试跑
def _word(ind: str) -> str:
    sys.path.insert(0, os.path.join(HERE, "..", "text2site"))
    import lexicon as L
    return next(iter(L.PRODUCT.get(ind, [])), "公司")


def trial(run_browser: bool = True, only: str | None = None) -> dict:
    """把所有“候选”拿去试跑。结论写回 priors.json。"""
    sys.path.insert(0, os.path.join(HERE, "..", "text2site"))
    import tempfile
    from make_site import build_one
    from styles import options
    from understand import understand
    d = load()
    done = {}
    with events.run("trial", 候选=sum(1 for v in d.get("industries", {}).values() if v.get("status") == "候选")):
        for ind, p in d.get("industries", {}).items():
            if p.get("status") != "候选" or (only and ind != only):
                continue
            b = understand(f"帮我做个{_word(ind)}的网站")
            if b["product_type"]["value"] != ind:
                p.update(status="拒绝", why=f"试跑的句子没被认成这个行业（认成了 {b['product_type']['value']}），没法对照")
                done[ind] = p["status"]
                continue
            sid = options(b)[0]["id"]
            res = {}
            for mode in ("off", "candidate"):
                os.environ["AISITE_PRIORS"] = "off" if mode == "off" else "on"
                os.environ["AISITE_PRIORS_CANDIDATE"] = ind if mode == "candidate" else ""
                r = build_one(b, sid, tempfile.mkdtemp(prefix=f"prior-{mode}-"), run_browser=run_browser)
                res[mode] = {"errors": len(r["blueprint_errors"]), "problems": len(r["browser_problems"]),
                             "note": r["notes"].get("design_prior", "")}
            os.environ["AISITE_PRIORS"] = "on"
            os.environ["AISITE_PRIORS_CANDIDATE"] = ""
            ok = res["candidate"]["errors"] == 0 and res["candidate"]["problems"] <= res["off"]["problems"]
            p["trial"] = dict(res, style=sid, at=time.strftime("%Y-%m-%d %H:%M"))
            if ok:
                p.update(status="采纳", why="试跑通过：图纸 0 错误，浏览器问题不比不用时多")
            else:
                p.update(status="拒绝", why=f"试跑没过：图纸 {res['candidate']['errors']} 个错误，浏览器问题 {res['candidate']['problems']} 个（不用时 {res['off']['problems']} 个）")
            done[ind] = p["status"]
    _save(d)
    return done


def candidate_override() -> str:
    return os.environ.get("AISITE_PRIORS_CANDIDATE", "")


def show() -> list[str]:
    d = load()
    lines = [f"语料库 {d.get('n', 0)} 个网站；样本至少 {d.get('min_n', MIN_N)} 个、顺序一致度至少 {d.get('min_agree', MIN_AGREE)} 才提炼"]
    for ind, p in sorted(d.get("industries", {}).items(), key=lambda kv: -kv[1]["n"]):
        lines.append(f"{ind}：{p['n']} 个，{p['status']}（{p['why']}）；顺序 {' > '.join(['hero'] + p['order'])}；"
                     f"一致度 {p['agreement']}；正文 {p['type']['base']}px，首屏标题 {p['type']['h1']}px；留白 {p['space']['section_pad']}px")
    return lines


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "build":
        build()
        print("\n".join(show()))
    elif cmd == "trial":
        print(json.dumps(trial(run_browser="--no-browser" not in sys.argv), ensure_ascii=False))
        print("\n".join(show()))
    else:
        print("\n".join(show()))
