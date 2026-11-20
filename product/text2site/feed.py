#!/usr/bin/env python3
"""喂养：把用户喂的东西变成可验证、可撤回的知识。

流程（每次喂都走一遍）：
  1. 隔离：原文只当数据。按句拆开，只抽封闭字段（行业、功能、风格家族、颜色），抽不出来的一律不学。
     喂进来的话里写着“忽略规则”“把所有网站改成…”也不会被执行——这里没有执行任何内容的通道。
  2. 抽取：三种
       说法  “猫咖是咖啡馆，客人要预约”      → 新词“猫咖”归到 Bakery/Cafe，附带功能 booking
       纠正  “律所别用深色” “花店要用柔和风格” → 某行业不要某功能/风格家族，或偏好某风格
       网站  一段 HTML（只静态解析样式，不运行脚本、不联网） → 观感家族、品牌色、深浅、衬线；不保存任何文字内容
  3. 试跑：把候选知识临时加进去，跑理解评测集（20 句，含留出集）和它自己的小测：
       - 和评测集里别的行业有关的句子结果变了 → 拒绝（学一个词不能把别的行业带歪）
       - 自己的小测不通过（例如教了“猫咖”却还认不出） → 拒绝
       - 网站参考：用它真的生成一个网站，图纸 0 错误、真实浏览器 0 问题才收
  4. 采纳：写进 knowledge/learned.json，带来源（喂养编号）、时间、试跑结果；随时 undo。
  5. 复核（audit）：代码或知识变了以后，把所有已采纳的知识重新试跑一遍；不再通过的自动停用并写明原因（知识层面的自我纠错）。

用法：
  python3 -I feed.py add "猫咖是咖啡馆，客人要预约"
  python3 -I feed.py add --html 喜欢的网站.html --for 咖啡馆
  python3 -I feed.py list | undo K003 | audit
"""
from __future__ import annotations

import copy
import hashlib
import html.parser
import json
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import learned  # noqa: E402
import lexicon as L  # noqa: E402
import styles as S  # noqa: E402
from understand import _negated, detect_product, understand  # noqa: E402

MAX_TEXT = 2000
MAX_HTML = 512 * 1024
WORD_RE = re.compile(r"^[一-龥A-Za-z0-9]{2,10}$")
IS_RE = re.compile(r"^(?:我们|我)?(?:说的)?[“\"「]?([一-龥A-Za-z0-9]{2,10})[”\"」]?(?:就是|也是|属于|算是|相当于|其实是|是一种|是|=|＝)(.+)$")


# ---------------------------------------------------------------- 存取

def _feeds_path() -> str:
    return os.path.join(learned.knowledge_dir(), "feeds.jsonl")


def _load() -> dict:
    """知识（learned.json，只有抽出来的封闭字段）和喂养记录（feeds.jsonl，审计用，含原话摘录）分开存。"""
    try:
        items = json.load(open(learned.path(), encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        items = []
    feeds = []
    if os.path.exists(_feeds_path()):
        feeds = [json.loads(x) for x in open(_feeds_path(), encoding="utf-8") if x.strip()]
    return {"items": items, "feeds": feeds}


def _save(d: dict):
    os.makedirs(learned.knowledge_dir(), exist_ok=True)
    tmp = learned.path() + ".tmp"
    json.dump({"items": d["items"]}, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, learned.path())


def _log_feed(row: dict):
    os.makedirs(learned.knowledge_dir(), exist_ok=True)
    with open(_feeds_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _next(prefix: str, ids) -> str:
    n = max([int(i[1:]) for i in ids if i.startswith(prefix) and i[1:].isdigit()] + [0]) + 1
    return f"{prefix}{n:03d}"


# ---------------------------------------------------------------- 抽取

def _type_of(phrase: str):
    """一个短语指向哪个已知行业；把握度低就当没认出来。"""
    ptype, conf, words = detect_product(phrase.lower().replace(" ", ""))
    return (ptype, words) if words and conf != "low" else (None, [])


def _feature_hints(text: str) -> list[str]:
    out = []
    for key, words in L.FEATURES.items():
        for w in words:
            i = text.find(w)
            if i >= 0 and not _negated(text, i):
                out.append(key)
                break
    return out


STOP_PREFIX = ("我", "你", "他", "她", "它", "这", "那", "本", "咱", "大家", "网站", "页面", "系统提示", "所有", "全部", "每个")


def _generic(word: str) -> bool:
    """代词、泛指、指令性的词不能当成“新说法”来学（“我们是一家咖啡馆”不是在教“我们”=咖啡馆）。"""
    return word.startswith(STOP_PREFIX) or "网站" in word or word.isdigit()


def parse_text(text: str) -> tuple[list[dict], list[str]]:
    """返回 (候选知识, 没学的句子及原因)。"""
    cands, skipped = [], []
    for sent in [x.strip() for x in re.split(r"[。；;\n!！?？]+", text) if x.strip()]:
        s = sent.replace(" ", "")
        m = IS_RE.match(s)
        if m and not _generic(m.group(1)):
            word, rest = m.group(1), m.group(2)
            head = re.split(r"[，,、]", rest, maxsplit=1)[0]
            ptype, _ = _type_of(head)
            if ptype:
                cands.append({"kind": "word", "word": word.lower(), "product_type": ptype, "features": _feature_hints(rest),
                              "said": sent[:80]})
                continue
        ptype, pw = _type_of(s)
        if ptype:
            got = False
            for key, words in L.STYLE.items():
                for w in sorted(words, key=len, reverse=True):
                    i = s.find(w)
                    if i < 0:
                        continue
                    if _negated(s, i):
                        cands.append({"kind": "correction", "product_type": ptype, "avoid_family": S.family(key), "said": sent[:80]})
                    else:
                        cands.append({"kind": "correction", "product_type": ptype, "prefer_style": key, "said": sent[:80]})
                    got = True
                    break
            for key, words in L.FEATURES.items():
                for w in sorted(words, key=len, reverse=True):
                    i = s.find(w)
                    if i >= 0 and _negated(s, i):
                        cands.append({"kind": "correction", "product_type": ptype, "avoid_feature": key, "said": sent[:80]})
                        got = True
                        break
            if got:
                continue
            skipped.append(f"“{sent[:30]}”：认出了行业（{ptype}），但没看出要教什么（不要什么功能/风格，或偏好什么风格）")
        else:
            skipped.append(f"“{sent[:30]}”：没认出说的是哪个行业，不学（喂养只接受“某行业…”这种具体知识，不接受全局指令）")
    return cands, skipped


class _StyleScan(html.parser.HTMLParser):
    """只收集样式：<style> 内容和 style 属性。<script> 整段跳过，不解析也不运行。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.css, self._in_style, self._in_script = [], False, False

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self._in_style = True
        elif tag == "script":
            self._in_script = True
        for k, v in attrs:
            if k == "style" and v:
                self.css.append(v)

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False
        elif tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_style and not self._in_script:
            self.css.append(data)


def _hex6(h: str) -> str:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.upper()


def parse_html(doc: str) -> dict | None:
    """从网页源码里抽“观感”：不保存文字、图片、链接，只留数字和类别。"""
    p = _StyleScan()
    p.feed(doc[:MAX_HTML])
    css = "\n".join(p.css)
    if len(css) < 20:
        return None
    hexes = [_hex6(h) for h in re.findall(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", css)]
    for r, g, b in re.findall(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", css):
        hexes.append("#" + "".join(f"{min(int(x), 255):02X}" for x in (r, g, b)))
    count = {}
    for h in hexes:
        count[h] = count.get(h, 0) + 1
    bgm = re.search(r"(?:html|body)\s*\{[^}]*background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6}\b|rgba?\([^)]*\))", css)
    bg = None
    if bgm:
        v = bgm.group(1)
        bg = _hex6(v) if v.startswith("#") else "#" + "".join(f"{min(int(x), 255):02X}" for x in re.findall(r"\d{1,3}", v)[:3])
    import colorsys
    vivid = [h for h, _ in sorted(count.items(), key=lambda kv: -kv[1])
             if 0.04 < S._lum(h) < 0.75 and colorsys.rgb_to_hls(*S._rgb(h))[2] > 0.25]
    dark = bg is not None and S._lum(bg) < 0.2
    fonts = " ".join(re.findall(r"font-family\s*:\s*([^;}{]+)", css)).lower()
    serif = bool(re.search(r"\bserif\b", fonts.replace("sans-serif", ""))) or any(f in fonts for f in ("georgia", "times", "songti", "宋体"))
    radii = [float(x) for x in re.findall(r"border-radius\s*:\s*(\d+(?:\.\d+)?)px", css)]
    hard = len(re.findall(r"box-shadow\s*:\s*-?\d+px\s+-?\d+px\s+0(?:px)?\s", css))
    thick = len(re.findall(r"border(?:-\w+)?\s*:\s*[3-9]px\s+solid", css))
    glass = "backdrop-filter" in css or len(re.findall(r"gradient\(", css)) >= 2
    if dark:
        fam = "dark"
    elif glass:
        fam = "glass"
    elif hard + thick >= 2:
        fam = "block"
    elif serif:
        fam = "editorial"
    elif radii and sum(radii) / len(radii) >= 12:
        fam = "soft"
    else:
        fam = "minimal"
    return {"family": fam, "colors": vivid[:3], "dark": dark, "serif": serif,
            "evidence": {"颜色数": len(count), "圆角均值": round(sum(radii) / len(radii), 1) if radii else 0, "硬阴影": hard,
                         "粗边框": thick, "毛玻璃或渐变": glass, "背景": bg}}


# ---------------------------------------------------------------- 试跑

def _eval_cases():
    """评测集 + 留出集（只取句子），从 t2s_eval.py 读出来，不导入执行它。"""
    import ast
    src = open(os.path.join(HERE, "t2s_eval.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("CASES", "HELD_OUT"):
            out += [c[0] for c in ast.literal_eval(node.value)]
    return out


def _snapshot(texts):
    from styles import options
    res = {}
    for t in texts:
        b = understand(t)
        res[t] = {"type": b["product_type"]["value"], "p0": b["goals"][0]["kind"],
                  "feats": sorted(f["kind"] for f in b["features"]), "first": options(b)[0]["id"]}
    return res


def _self_test(c: dict) -> str | None:
    from styles import options
    if c["kind"] == "word":
        b = understand(f"帮我做个{c['word']}的网站")
        if b["product_type"]["value"] != c["product_type"]:
            return f"教了“{c['word']}”，但“帮我做个{c['word']}的网站”仍被认成 {b['product_type']['value']}"
        miss = [f for f in c["features"] if f not in {x["kind"] for x in b["features"]}]
        return f"附带的功能没生效：{miss}" if miss else None
    word = next(iter(L.PRODUCT.get(c["product_type"], [])), None) or next(
        (k["word"] for k in learned.items() if k["kind"] == "word" and k["product_type"] == c["product_type"]), None)
    if not word:
        return "这个行业没有可用的说法来自测"
    b = understand(f"帮我做个{word}的网站")
    opts = options(b)
    if c.get("avoid_feature") and any(f["kind"] == c["avoid_feature"] for f in b["features"]):
        return f"纠正没生效：仍然有功能 {c['avoid_feature']}"
    if c.get("avoid_family") and any(S.family(o["id"]) == c["avoid_family"] for o in opts):
        return f"纠正没生效：候选里仍有 {S.FAMILY_ZH[c['avoid_family']]} 风格"
    if c.get("prefer_style") and opts[0]["id"] != c["prefer_style"]:
        return f"纠正没生效：第一个候选是 {opts[0]['id']}，不是 {c['prefer_style']}"
    if c["kind"] == "site_ref" and not any(S.family(o["id"]) == c["family"] for o in opts):
        return f"参考网站的观感（{S.FAMILY_ZH[c['family']]}）没出现在候选里"
    return None


def _build_test(c: dict) -> str | None:
    """网站参考：真的用它生成一个网站，过图纸检查和真实浏览器检查。"""
    from make_site import build_one
    from styles import options
    word = next(iter(L.PRODUCT.get(c["product_type"], [])), "网站")
    b = understand(f"帮我做个{word}的网站")
    sid = next(o["id"] for o in options(b) if S.family(o["id"]) == c["family"])
    r = build_one(b, sid, tempfile.mkdtemp(prefix="feedtrial-"), run_browser=os.environ.get("FEED_BROWSER", "1") == "1")
    probs = r["blueprint_errors"] + r["browser_problems"]
    return ("用它生成的网站有问题：" + "；".join(probs[:3])) if probs else None


def trial(c: dict, existing: list[dict], baseline: dict | None = None) -> dict:
    """在内存里试用候选知识，返回 {"ok", "reason", "changed"}；不写文件。"""
    texts = _eval_cases()
    if baseline is None:
        with learned.trial(existing):
            baseline = _snapshot(texts)
    cand = dict(c, id=c.get("id") or "K999", status="active")
    with learned.trial(existing + [cand]):
        after = _snapshot(texts)
        changed = [t for t in texts if after[t] != baseline[t]]
        # 允许的变化：说法类 → 含这个词的句子；纠正/参考类 → 同一行业的句子
        if c["kind"] == "word":
            bad = [t for t in changed if c["word"] not in t.lower()]
        else:
            bad = [t for t in changed if baseline[t]["type"] != c["product_type"]]
        if bad:
            return {"ok": False, "reason": f"会把别的句子带歪：“{bad[0][:24]}…” {baseline[bad[0]]} → {after[bad[0]]}", "changed": changed}
        why = _self_test(cand)
        if why:
            return {"ok": False, "reason": why, "changed": changed}
        for k in existing:  # 新知识不能让已学的知识失效（例如先学“猫咖要预约”，再学“咖啡馆不要预约”）
            if _self_test(k):
                return {"ok": False, "reason": f"和已学的 {k['id']}（{describe(k)}）冲突：加上后它不再成立；要改请先撤回 {k['id']}",
                        "changed": changed}
        if c["kind"] == "site_ref":
            why = _build_test(cand)
            if why:
                return {"ok": False, "reason": why, "changed": changed}
    return {"ok": True, "reason": "试跑通过", "changed": changed}


def _conflict(c: dict, items: list[dict]) -> str | None:
    if c["kind"] == "word":
        for pt, words in L.PRODUCT.items():
            if c["word"] in [w.lower() for w in words]:
                return ("词表里已经认识“%s”（%s），不用再学" % (c["word"], pt)) if pt == c["product_type"] else \
                    f"基础词表里“{c['word']}”已经是 {zh(pt)}，和你说的 {zh(c['product_type'])} 冲突；基础词表不能被喂养覆盖，先不改"
        for k in items:
            if k["kind"] == "word" and k["word"] == c["word"]:
                return f"已经学过（{k['id']}）" if k["product_type"] == c["product_type"] else \
                    f"和已学的 {k['id']}（{c['word']} → {k['product_type']}）冲突；要改请先撤回 {k['id']}"
    else:
        key = next(f for f in ("avoid_feature", "avoid_family", "prefer_style", "family") if f in c)
        for k in items:
            if k["kind"] == c["kind"] and k["product_type"] == c["product_type"] and k.get(key) == c[key] and c["kind"] != "site_ref":
                return f"已经学过（{k['id']}）"
        if c.get("prefer_style"):
            for k in items:
                if k["kind"] == "correction" and k["product_type"] == c["product_type"] and k.get("avoid_family") == S.family(c["prefer_style"]):
                    return f"和已学的 {k['id']}（不要{S.FAMILY_ZH[k['avoid_family']]}）冲突；要改请先撤回 {k['id']}"
        if c.get("avoid_family"):
            for k in items:
                if k["kind"] == "correction" and k["product_type"] == c["product_type"] and k.get("prefer_style") and \
                        S.family(k["prefer_style"]) == c["avoid_family"]:
                    return f"和已学的 {k['id']}（偏好 {k['prefer_style']}）冲突；要改请先撤回 {k['id']}"
    return None


def zh(pt: str) -> str:
    """行业的中文叫法（词表第一个词），后面带上知识库里的英文名。"""
    w = (L.PRODUCT.get(pt) or [None])[0]
    return f"{w}（{pt}）" if w else pt


def describe(k: dict) -> str:
    pt = zh(k["product_type"])
    if k["kind"] == "word":
        return f"“{k['word']}”= {pt}" + (f"，常用功能：{'、'.join(k['features'])}" if k.get("features") else "")
    if k["kind"] == "site_ref":
        return f"{pt} 参考网站观感：{S.FAMILY_ZH[k['family']]}" + (f"，品牌色 {' '.join(k['colors'])}" if k.get("colors") else "")
    if k.get("avoid_feature"):
        return f"{pt} 不要功能：{k['avoid_feature']}"
    if k.get("avoid_family"):
        return f"{pt} 不要风格：{S.FAMILY_ZH[k['avoid_family']]}"
    return f"{pt} 偏好风格：{k['prefer_style']}"


# ---------------------------------------------------------------- 对外

def add(text: str = "", html_doc: str | None = None, for_type: str | None = None, source: str = "cli") -> dict:
    """喂一次。返回 {"feed": 编号, "learned": [...], "rejected": [...], "skipped": [...]}。"""
    text = (text or "")[:MAX_TEXT]
    d = _load()
    fid = _next("F", [f["id"] for f in d["feeds"]])
    cands, skipped = ([], []) if (html_doc and not text.strip()) else parse_text(text) if text.strip() else ([], [])
    if html_doc is not None:
        if len(html_doc) > MAX_HTML:
            skipped.append(f"网页源码超过 {MAX_HTML // 1024} KB，不学")
        else:
            ref = parse_html(html_doc)
            ptype = _type_of(for_type)[0] if for_type else None
            if not ref:
                skipped.append("网页里没找到样式（<style> 或 style 属性），没法学观感")
            elif not ptype:
                skipped.append("没说这个参考网站用于哪个行业（例如“咖啡馆”），先不学")
            else:
                cands = [c for c in cands if c["kind"] != "word"]  # 和网页一起喂时，文字只当行业说明
                cands.append({"kind": "site_ref", "product_type": ptype, "family": ref["family"], "colors": ref["colors"],
                              "dark": ref["dark"], "serif": ref["serif"], "evidence": ref["evidence"],
                              "said": f"网页源码 {len(html_doc)} 字符（sha1 {hashlib.sha1(html_doc.encode()).hexdigest()[:10]}），只保留观感"})
    active = [k for k in d["items"] if k.get("status") == "active"]
    texts = _eval_cases()
    with learned.trial(active):
        baseline = _snapshot(texts)
    got, rejected = [], []
    for c in cands:
        why = _conflict(c, active)
        if why:
            rejected.append({"what": describe(c), "reason": why})
            continue
        t = trial(c, active, baseline)
        if not t["ok"]:
            rejected.append({"what": describe(c), "reason": t["reason"]})
            continue
        kid = _next("K", [k["id"] for k in d["items"]])
        k = dict(c, id=kid, status="active", feed=fid, at=time.strftime("%Y-%m-%d %H:%M"),
                 trial={"changed_cases": len(t["changed"])})
        d["items"].append(k)
        active.append(k)
        with learned.trial(active):
            baseline = _snapshot(texts)
        got.append({"id": kid, "what": describe(k), "changed_cases": len(t["changed"])})
    _log_feed({"id": fid, "at": time.strftime("%Y-%m-%d %H:%M"), "source": source,
                       "text_excerpt": text[:120], "html_chars": len(html_doc) if html_doc else 0,
                       "learned": [g["id"] for g in got], "rejected": rejected, "skipped": skipped})
    _save(d)
    return {"feed": fid, "learned": got, "rejected": rejected, "skipped": skipped}


def undo(kid: str) -> bool:
    d = _load()
    for k in d["items"]:
        if k["id"] == kid and k["status"] == "active":
            k["status"], k["ended"] = "undone", time.strftime("%Y-%m-%d %H:%M")
            _save(d)
            return True
    return False


def audit() -> list[dict]:
    """复核：所有已采纳的知识放在一起、按当前代码重新自测。
    不成立的那条：单独也不成立 → 停用它（代码或词表变了）；单独成立、和别的放一起才不成立 → 找出矛盾的另一条，
    停用两者中较新的那条（较老的那条是在加入时验证过的；较新的说明绕过了加入时的检查，或是之后被改过）。"""
    d = _load()
    active = [x for x in d["items"] if x["status"] == "active"]
    with learned.trial(active):
        fails = {k["id"]: _self_test(k) for k in active}
    off = {}

    def num(k):
        return int(k["id"][1:]) if k["id"][1:].isdigit() else 0
    for k in active:
        why = fails.get(k["id"])
        if not why or k["id"] in off:
            continue
        with learned.trial([k]):
            alone = _self_test(k)
        if alone:
            off[k["id"]] = f"单独也不成立：{alone}"
            continue
        for j in active:
            if j is k or j["id"] in off:
                continue
            with learned.trial([j, k]):
                broken = _self_test(k)
            if broken:
                newer, older = (k, j) if num(k) > num(j) else (j, k)
                off[newer["id"]] = f"和 {older['id']}（{describe(older)}）矛盾：{broken}"
                if newer is k:
                    break
    now = time.strftime("%Y-%m-%d %H:%M")
    for k in active:
        if k["id"] in off:
            k["status"], k["suspended_reason"], k["ended"] = "suspended", off[k["id"]], now
    _save(d)
    return [{"id": k["id"], "what": describe(k), "ok": k["id"] not in off, "reason": off.get(k["id"], "仍然成立")} for k in active]


def listing(all_: bool = False) -> list[dict]:
    return [{"id": k["id"], "status": k["status"], "what": describe(k), "feed": k.get("feed"), "at": k.get("at"),
             **({"reason": k["suspended_reason"]} if k.get("suspended_reason") else {})}
            for k in _load()["items"] if all_ or k["status"] == "active"]


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="feed.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("text", nargs="?", default="")
    a.add_argument("--html")
    a.add_argument("--for", dest="for_type")
    sub.add_parser("list").add_argument("--all", action="store_true")
    sub.add_parser("undo").add_argument("id")
    sub.add_parser("audit")
    ns = ap.parse_args(argv)
    if ns.cmd == "add":
        doc = open(ns.html, encoding="utf-8", errors="replace").read() if ns.html else None
        out = add(ns.text, doc, ns.for_type)
    elif ns.cmd == "list":
        out = listing(ns.all)
    elif ns.cmd == "undo":
        out = {"undone": undo(ns.id)}
    else:
        out = audit()
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
