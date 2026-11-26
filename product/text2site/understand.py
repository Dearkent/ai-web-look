#!/usr/bin/env python3
"""文字 → 需求简报（brief/0.1）。

第一版用词表 + 知识库推理，不依赖模型：
  * 产品类型：词表命中打分（长词权重高）；命中不了就降为低把握度并提问。
  * 目标与功能：触发词，按在原文里出现的先后排优先级；否定说法（“不要…”）不算。
  * 风格：用户说了风格词就优先；再按知识库 products.csv 的推荐（经 kb.resolve_combo 解析成 ID）。
  * 每个推断都写来源（user / inferred / kb / default）和把握度；最多 3 个问题，每个都有默认答案。
以后有模型时，模型的结果也必须产出同样格式、通过同一个检查器（模型只是更聪明的这一步）。
"""
from __future__ import annotations

import csv
import datetime as dt
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import kb  # noqa: E402
import lexicon as L  # noqa: E402
import learned  # noqa: E402

# 设计知识表随仓库一起发（product/kb/uiux，MIT，来源见同目录“来源.md”）；不再依赖开发机上的某个路径
KB_DIR = os.environ.get("UIUX_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kb", "uiux")

DEFAULT_GOALS = {  # 用户没说目标时，按行业给默认
    "Bakery/Cafe": ["inform", "booking"], "Restaurant/Food Service": ["inform", "booking"],
    "Hotel/Hospitality": ["booking"], "Beauty/Spa/Wellness Service": ["booking"], "Dental Practice": ["booking"],
    "Medical Clinic": ["booking"], "Fitness/Gym App": ["signup"], "Portfolio/Personal": ["showcase", "leads"],
    "E-commerce": ["sell"], "E-commerce Luxury": ["sell"], "Florist/Plant Shop": ["sell"],
    "SaaS (General)": ["signup", "leads"], "AI/Chatbot Platform": ["signup"], "Online Course/E-learning": ["signup"],
    "Legal Services": ["leads"], "B2B Service": ["leads"], "Real Estate/Property": ["leads"],
    "Conference / Symposium Landing Page": ["signup"], "Non-profit/Charity": ["community"],
}
GOAL_DESC = {"booking": "在线预约", "sell": "在线购买或下单", "leads": "让潜在客户联系我们", "signup": "注册或报名",
             "showcase": "展示作品和实力", "inform": "让访客了解我们提供什么", "community": "吸引人加入",
             "recruit": "招到合适的人", "download": "引导下载"}
GOAL_FEATURE = {"booking": "booking", "leads": "contact_form", "signup": "contact_form", "community": "contact_form",
                "recruit": "contact_form", "showcase": "gallery", "sell": "catalog", "inform": "catalog"}


def _norm(t: str) -> str:
    return t.lower().replace(" ", "")


def _negated(text: str, i: int) -> bool:
    before = text[max(0, i - 4):i]
    return any(n in before for n in L.NEGATIONS)


def _first_hits(text: str, table: dict) -> list[tuple[int, str, str]]:
    """返回 [(首次出现位置, 键, 命中词)]，跳过被否定的命中。"""
    out = []
    for key, words in table.items():
        best = None
        for w in sorted(words, key=len, reverse=True):
            for m in re.finditer(re.escape(w.lower()), text):
                if not _negated(text, m.start()):
                    if best is None or m.start() < best[0]:
                        best = (m.start(), key, w)
                    break
        if best:
            out.append(best)
    return sorted(out)


def _products_row(ptype: str) -> dict:
    with open(os.path.join(KB_DIR, "products.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["Product Type"] == ptype:
                return r
    return {}


def _word_score(w: str, text: str) -> float:
    """长词更可信；含义宽泛的词减半；紧跟“店/馆/所…”的词加倍（“社区里的火锅店”里，火锅店才是行业）。"""
    lw = w.lower()
    sc = len(lw) ** 2 * (0.5 if lw in L.AMBIGUOUS else 1.0)
    if any(text[m.end():m.end() + 1] in L.SHOP_SUFFIX and text[m.end():m.end() + 1] for m in re.finditer(re.escape(lw), text)):
        sc *= 2
    return sc


def detect_product(text: str):
    scores, taught = {}, {}
    for ptype, words in L.PRODUCT.items():
        for w in words:
            if w.lower() in text:
                scores.setdefault(ptype, []).append(w)
    for ptype, pairs in learned.product_words().items():  # 喂养学到的说法：用户亲口教的，分数 ×1.5
        for w, kid in pairs:
            if w.lower() in text and w not in scores.get(ptype, []):
                scores.setdefault(ptype, []).append(w)
                taught[w] = kid
    if not scores:
        return "B2B Service", "low", []
    total = lambda ws: sum(_word_score(w, text) * (1.5 if w in taught else 1.0) for w in ws)
    rank = sorted(scores.items(), key=lambda kv: (-total(kv[1]), kv[0]))
    best, words = rank[0]
    second = total(rank[1][1]) if len(rank) > 1 else 0
    top = total(words)
    conf = "high" if top >= 9 and top >= 2 * second else ("medium" if top > second else "low")
    return best, conf, words


def style_candidates(text: str, ptype: str):
    """返回 (用户点名的风格, 用户排除的风格, 知识库推荐的风格, 知识库推荐的落地页, 解析说明)。"""
    wanted, avoided = [], []
    for key, words in L.STYLE.items():
        for w in words:
            for m in re.finditer(re.escape(w), text):
                (avoided if _negated(text, m.start()) else wanted).append(key)
    wanted = list(dict.fromkeys(k for k in wanted if k not in avoided))
    row = _products_row(ptype)
    kb_styles, kb_landing, unresolved = [], [], []
    if row:
        for col in ("Primary Style Recommendation", "Secondary Styles"):
            for part in re.split(r"[,，]", row.get(col, "")):
                if part.strip():
                    x = kb.resolve_combo(part.strip(), "style")
                    kb_styles += [i.split(":", 1)[1] for i in x["ids"] if i.startswith("style:")]
                    kb_landing += [i.split(":", 1)[1] for i in x["ids"] if i.startswith("landing:")]
                    unresolved += x["unresolved"]
        x = kb.resolve_combo(row.get("Landing Page Pattern", ""), "landing")
        kb_landing += [i.split(":", 1)[1] for i in x["ids"] if i.startswith("landing:")]
        unresolved += x["unresolved"]
    usable = {k for k, v in kb.vocab()["styles"].items() if v["status"] != "deprecated"}
    kb_styles = [s for s in dict.fromkeys(kb_styles) if s in usable and s not in avoided]
    return wanted, avoided, kb_styles, list(dict.fromkeys(kb_landing)), unresolved


def understand(text: str, brief_id: str | None = None, force_type: str | None = None) -> dict:
    """force_type：模型理解出的行业（已校验在词表里）。规则把握不高时由它决定行业，其余仍按规则推。"""
    raw = text.strip()
    t = _norm(raw)
    ptype, pconf, pwords = detect_product(t)
    forced = bool(force_type and force_type != ptype and force_type in L.PRODUCT)
    if forced:
        ptype, pconf = force_type, "medium"

    # 目标：按出现先后；第一个是 P0
    ghits = _first_hits(t, L.GOALS)
    if ptype == "Portfolio/Personal":  # 作品集里的“作品”是展示，不是卖
        ghits = [h for h in ghits if h[1] != "sell"]
    goals = []
    for i, (_, g, w) in enumerate(ghits[:4]):
        goals.append({"id": f"G{i + 1}", "kind": g, "priority": "P0" if i == 0 else "P1",
                      "description": GOAL_DESC[g], "source": "user"})
    if not goals:
        for i, g in enumerate(DEFAULT_GOALS.get(ptype, ["inform", "leads"])):
            goals.append({"id": f"G{i + 1}", "kind": g, "priority": "P0" if i == 0 else "P1",
                          "description": GOAL_DESC[g], "source": "default"})

    # 功能：触发词 + 每个目标需要的功能
    feats, seen = [], set()
    for _, f, w in _first_hits(t, L.FEATURES):
        if f not in seen:
            seen.add(f); feats.append({"kind": f, "source": "user"})
    for g in goals:
        f = GOAL_FEATURE.get(g["kind"])
        if f and f not in seen:
            seen.add(f); feats.append({"kind": f, "source": "inferred"})
    p0_feature = GOAL_FEATURE.get(goals[0]["kind"])
    features = [{"id": f"F{i + 1}", "kind": f["kind"], "priority": "P0" if f["kind"] == p0_feature else "P1",
                 "source": f["source"]} for i, f in enumerate(feats)]

    # 风格与动效档位
    wanted, avoided, kb_styles, kb_landing, unresolved = style_candidates(t, ptype)
    style_ids = list(dict.fromkeys(wanted + kb_styles))[:3] or ["minimalism-and-swiss-style"]
    calm = any(w in t for w in L.CALM)
    lively = any(w in t for w in L.LIVELY) and not calm
    tier = "Subtle" if calm else ("Complex" if lively else "Standard")
    landing = kb_landing[0] if kb_landing else "hero-features-cta"

    # 名称、受众、语言、地区
    m = re.search(r"(?:叫做|名叫|名字叫|叫)\s*[“\"「『]?([A-Za-z0-9][A-Za-z0-9&'.\- ]{0,39}[A-Za-z0-9.]|[^”\"」』，,。！!？?\s]{1,16})", raw) or \
        re.search(r"[“\"「『]([^”\"」』]{1,16})[”\"」』]", raw)
    name = m.group(1) if m else None
    am = re.search(r"(?:给|面向|让|方便|吸引)([^，,。；;！!？?]{1,14}?(?:的人|族|们|顾客|客户|学生|家长|用户|品牌方|老板|游客))", raw) or \
        re.search(r"(?:给|面向|让|方便|吸引)([^，,。；;！!？?]{2,14}?)(?:看|用|能|可以|来|知道|找到|，|。|$)", raw)
    audience = am.group(1).strip() if am else None
    if audience and (audience.startswith(("我", "咱")) or any(w in audience for w in ("网站", "做个", "做一个", "官网"))):
        audience = None  # “给我的咖啡馆做个网站”里的“给”不是在说访客（D21）
    locales = ["zh-CN", "en"] if any(w in t for w in L.TWO_LANG) else ["zh-CN"]
    region = "global" if any(w in t for w in ["海外", "国外", "全球"]) else "cn-mainland"

    assets = [{"id": "A1", "kind": "logo", "provided": "logo" in t or "标志" in t},
              {"id": "A2", "kind": "photo", "description": "主要图片", "provided": any(w in t for w in ["照片", "图片", "拍了"])}]

    # 问题：最多 3 个，按影响大小
    qs = []
    if pconf == "low":
        qs.append(("你的网站是做什么的？（比如咖啡馆、律所、网店）", "决定页面和风格的推荐", ["product_type"],
                   f"先按“{ptype}”生成，可以随时改"))
    if any(f["kind"] == "booking" for f in features):
        qs.append(("预约需要先付定金吗？", "决定要不要接在线支付", ["features"], "不收定金，只登记"))
    if any(g["kind"] == "sell" for g in goals) and not any(f["kind"] == "payment" for f in features):
        qs.append(("要在网站上直接付款，还是展示商品后让客户联系下单？", "决定要不要做购物车和支付", ["features"], "先展示商品并留联系方式"))
    if not name:
        qs.append(("网站叫什么名字？", "显示在页头和标题里", ["site_name"], "暂用“我的网站”"))
    # 知识库解析不了的段落（如落地页的修饰词 Conversion）只降把握度、记进 kb_trace，不拿去问用户
    questions = [{"id": f"Q{i + 1}", "question": q, "why": w, "affects": a, "default_if_unanswered": d, "blocking": False}
                 for i, (q, w, a, d) in enumerate(qs[:3])]

    style_conf = "high" if wanted else ("medium" if kb_styles else "low")
    bid = brief_id or ("site-" + dt.datetime.now().strftime("%m%d%H%M%S"))
    brief = {
        "schema_version": "brief/0.1", "id": bid, "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "original_request": raw, "site_name": name or "我的网站", "locales": locales,
        "product_type": {"value": ptype, "source": "inferred" if (pwords or forced) else "default", "confidence": pconf,
                         "kb_trace": {"rule": ("模型理解；" if forced else "") + "词表命中：" + ("、".join(pwords) if pwords else "无"),
                                      "resolved": [f"style:{s}" for s in kb_styles] + [f"landing:{x}" for x in kb_landing],
                                      "unresolved": unresolved}},
        "goals": goals,
        "audience": {"primary": audience or "潜在顾客", "source": "user" if audience else "default"},
        "brand": {"name": name or "我的网站"} | ({"avoid": [f"风格：{a}" for a in avoided]} if avoided else {}),
        "style_preference": {"style_ids": style_ids, "landing_pattern": landing, "motion_tier": tier, "color_mode": "light",
                             "source": "user" if wanted else "kb", "confidence": style_conf,
                             "kb_trace": {"rule": f"products.csv: {ptype}" + ("；用户点名风格优先" if wanted else ""),
                                          "resolved": [f"style:{s}" for s in style_ids], "unresolved": unresolved}},
        "content_assets": assets,
        "features": features,
        "constraints": {"hosting_region": region},
        "open_questions": questions,
    }
    if brief["style_preference"]["confidence"] == "low" and not brief["style_preference"]["kb_trace"]["unresolved"]:
        brief["style_preference"]["kb_trace"].pop("unresolved")
    _apply_learned(brief, t, pwords, wanted)
    return brief


def _apply_learned(brief: dict, t: str, pwords: list[str], wanted: list[str]):
    """把喂养学到的知识用到这份简报上；只补用户这次没说的部分。用到的知识 ID 写进说明里（K001…），界面据此显示“用了哪些经验”。"""
    ptype = brief["product_type"]["value"]
    pt = brief["product_type"]["kb_trace"]
    feats = brief["features"]
    have = {f["kind"] for f in feats}
    user_feats = {f["kind"] for f in feats if f.get("source") == "user"}

    def add_feat(kind, kid):
        if kind not in have:
            feats.append({"id": f"F{len(feats) + 1}", "kind": kind, "priority": "P1", "source": "kb", "note": f"学自 {kid}"})
            have.add(kind)

    taught = {w: kid for pairs in learned.product_words().values() for w, kid in pairs}
    for w in pwords:
        if w in taught:
            pt["rule"] += f"（“{w}”学自 {taught[w]}）"
            k = next(x for x in learned.items() if x["id"] == taught[w])
            for f in k.get("features", []):
                add_feat(f, k["id"])
    for k in learned.for_type(ptype, "correction"):
        if k.get("avoid_feature"):
            f = k["avoid_feature"]
            if f in user_feats:  # 这次用户明确要了，就听这次的
                continue
            if f in have:
                brief["features"] = feats = [x for x in feats if x["kind"] != f]
                have.discard(f)
                gs = [g for g in brief["goals"] if not (g.get("source") == "default" and GOAL_FEATURE.get(g["kind"]) == f)]
                if not gs:
                    gs = [{"kind": "inform", "description": GOAL_DESC["inform"], "source": "default"}]
                for i, g in enumerate(gs):
                    g["id"], g["priority"] = f"G{i + 1}", "P0" if i == 0 else "P1"
                brief["goals"] = gs
                p0f = GOAL_FEATURE.get(gs[0]["kind"])
                for i, x in enumerate(feats):
                    x["id"] = f"F{i + 1}"
                    x["priority"] = "P0" if x["kind"] == p0f else "P1"
            brief["brand"].setdefault("avoid", []).append(f"功能：{f}（学自 {k['id']}）")
        if k.get("avoid_family"):
            import styles as _S  # 延迟导入，避免循环
            if not any(_S.family(s) == k["avoid_family"] for s in wanted):
                brief["brand"].setdefault("avoid", []).append(f"家族：{k['avoid_family']}（学自 {k['id']}）")
    refs = learned.for_type(ptype, "site_ref")
    if refs and not brief["brand"].get("colors") and refs[-1].get("colors"):
        brief["brand"]["colors"] = refs[-1]["colors"][:3]
        pt["rule"] += f"（品牌色参考 {refs[-1]['id']}）"


if __name__ == "__main__":
    import json
    print(json.dumps(understand(" ".join(sys.argv[1:])), ensure_ascii=False, indent=1))


def apply_answers(text: str, brief: dict, answers: dict) -> dict:
    """把用户对问题的回答写回需求简报。返回新的简报（原话不变）。
    规则：回答“做什么的” → 带上回答重新理解；名字 → 改名；定金/付款 → 加在线支付功能；回答写进 question.answer。"""
    qs = {q["id"]: q for q in brief.get("open_questions", [])}
    extra = [a.strip() for qid, a in answers.items() if qid in qs and "做什么" in qs[qid]["question"] and a.strip()]
    b = understand(text + ("。" + "。".join(extra) if extra else ""), brief["id"]) if extra else json_copy(brief)
    if extra:
        b["original_request"] = text
    qs_new = {q["question"]: q for q in b.get("open_questions", [])}
    for qid, ans in answers.items():
        ans = (ans or "").strip()[:60]
        if qid not in qs or not ans:
            continue
        q = qs[qid]["question"]
        if "叫什么名字" in q:  # 英文店名常常很长（品牌名、域名），放宽到 40 个字符；撑破屏幕交给自我纠错
            b["site_name"] = ans[:40]
            b.setdefault("brand", {})["name"] = ans[:40]
        elif ("定金" in q or "直接付款" in q) and not any(n in ans for n in ("不", "没", "无需", "联系")):
            if not any(f["kind"] == "payment" for f in b["features"]):
                b["features"].append({"id": f"F{len(b['features']) + 1}", "kind": "payment", "priority": "P1", "source": "user"})
        if q in qs_new:
            qs_new[q]["answer"] = ans
    return b


def json_copy(o):
    import json
    return json.loads(json.dumps(o))
