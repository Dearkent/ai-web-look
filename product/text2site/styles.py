#!/usr/bin/env python3
"""风格 → 设计令牌（DTCG 2025.10）。风格可选：每个需求给 3 种候选，同一套线框分别套上，让用户看着挑。

从知识库读：
  styles.csv  的 CSS/Technical Keywords、Design System Variables、Effects & Animation → 圆角、边框、阴影、毛玻璃、深浅色、动效时长、标题大写
  colors.csv  的行业配色 → 主色、背景、文字等（风格是深色时换成深色底，再按对比度修正）
  typography.csv 的字体搭配 → 按风格关键词与搭配气质的重合度挑一组；中文字体放在回退里
所有文字颜色都按 WCAG 对比度检查：正文至少 4.5:1，按钮文字至少 4.5:1（知识库 Accessibility 字段的要求）。
"""
from __future__ import annotations

import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import kb  # noqa: E402
from understand import KB_DIR  # noqa: E402

SERIF_ZH = ['"Noto Serif SC"', '"Songti SC"', '"SimSun"', "serif"]
SANS_ZH = ['"PingFang SC"', '"Microsoft YaHei"', '"Noto Sans SC"', "system-ui", "sans-serif"]
TECH_STYLE = "ai-native-ui"
DIVERSE = ["minimalism-and-swiss-style", "soft-ui-evolution", "neubrutalism", "dark-mode-oled",
           "glassmorphism", "editorial-grid-magazine", "claymorphism", "flat-design"]


def _rows(name):
    with open(os.path.join(KB_DIR, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


_STYLES = {r["Style ID"]: r for r in _rows("styles.csv")}
_COLORS = {r["Product Type"]: r for r in _rows("colors.csv")}
_TYPO = _rows("typography.csv")


# ---------------- 颜色与对比度 ----------------
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lum(h):
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _best_on(bg):
    return "#FFFFFF" if contrast("#FFFFFF", bg) >= contrast("#111111", bg) else "#111111"


def _hue(h):
    import colorsys
    return colorsys.rgb_to_hls(*_rgb(h))[0] * 360


def _near_brand(cands, brand):
    """风格自带颜色里挑色相最接近品牌主色的，既保留风格的鲜明，又和品牌协调。"""
    d = lambda h: min(abs(_hue(h) - _hue(brand)), 360 - abs(_hue(h) - _hue(brand)))
    return sorted(cands, key=d)


def _mix(h, other, t):
    a, b = _rgb(h), _rgb(other)
    return "#" + "".join(f"{round((x * (1 - t) + y * t) * 255):02X}" for x, y in zip(a, b))


# ---------------- 风格家族：决定“看起来像什么” ----------------
FAMILY_WORDS = [
    ("tech", ["ai-native", "high-tech"]),  # 第十四轮：用户要“科技感、高端”。深色精密：网格 + 光束首屏、细线卡片
    ("dark", ["dark", "cyberpunk", "hud", "terminal", "oled", "cinema", "vaporwave", "retro-futurism", "chromatic"]),
    ("glass", ["glass", "aurora", "gradient", "liquid", "spatial", "dimensional", "3d"]),
    ("block", ["brutal", "vibrant", "memphis", "bauhaus", "y2k", "maximalism", "pixel", "pop", "flat"]),
    ("editorial", ["editorial", "magazine", "academia", "typography", "vintage", "film", "paper", "e-ink"]),
    ("minimal", ["minimal", "swiss", "monochrome", "zero-interface", "accessible", "inclusive", "apple"]),
    ("soft", ["soft", "neumorph", "clay", "organic", "nature", "biophilic", "tactile", "biomimetic"]),
]
FAMILY_ZH = {"tech": "科技感", "block": "大色块", "soft": "柔和圆润", "minimal": "极简", "glass": "毛玻璃渐变", "dark": "深色", "editorial": "杂志排版"}


def _zh_type(pt: str) -> str:
    import lexicon as L
    return (L.PRODUCT.get(pt) or [pt])[0]


def family(style_id: str) -> str:
    key = (style_id + " " + _STYLES[style_id]["Style Category"]).lower()
    for fam, words in FAMILY_WORDS:
        if any(w in key for w in words):
            return fam
    p = profile(style_id)
    return "dark" if p["dark"] else "glass" if p["glass"] else "block" if p["shadow"] == "hard" else "minimal" if p["radius"] == 0 else "soft"


def style_hexes(style_id: str) -> list[str]:
    r = _STYLES[style_id]
    return [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}", r.get("Primary Colors", "") + " " + r.get("Secondary Colors", ""))]


# ---------------- 风格画像 ----------------
def profile(style_id: str) -> dict:
    r = _STYLES[style_id]
    text = " ".join(r.get(k, "") for k in ("CSS/Technical Keywords", "Design System Variables", "Effects & Animation")).lower()
    m = re.search(r"border-radius:\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*px", text) or re.search(r"--(?:border-)?radius[\w-]*:\s*(\d+)(?:\s*[-–]\s*(\d+))?px", text)
    radius = 0 if re.search(r"border-radius:\s*0(?![\d.])", text) else (round((int(m.group(1)) + int(m.group(2) or m.group(1))) / 2) if m else 8)
    bw = re.search(r"border:\s*(\d+)px", text)
    border = min(int(bw.group(1)), 6) if bw else 1
    if re.search(r"box-shadow:\s*none|no shadows?|shadow:\s*none", text):
        shadow = "none"
    elif re.search(r"box-shadow:\s*-?\d+px\s+-?\d+px\s+0(px)?\s", text):
        shadow = "hard"
    elif "inset" in text or "neumorph" in text:
        shadow = "inset"
    elif "glow" in text or "neon" in text:
        shadow = "glow"
    else:
        shadow = "soft"
    dm = re.search(r"(\d{2,4})\s*[-–]\s*(\d{2,4})\s*ms", text) or re.search(r"(\d{2,4})\s*ms", text)
    duration = round((int(dm.group(1)) + int(dm.group(dm.lastindex))) / 2) if dm else 250
    dark = r.get("Preferred Mode", "").lower() == "dark" or "dark" in r["Style Category"].lower() or "oled" in text
    return {"id": style_id, "name": r["Style Category"], "radius": radius, "border": border, "shadow": shadow,
            "glass": "backdrop-filter" in text or "blur(" in text, "dark": dark, "duration": max(80, min(duration, 800)),
            "uppercase": "uppercase" in text, "keywords": r.get("Keywords", ""), "best_for": r.get("Best For", ""),
            "avoid_for": r.get("Do Not Use For", "")}


def font_pair(style_id: str) -> dict:
    words = set(re.findall(r"[a-z]+", (_STYLES[style_id].get("Keywords", "") + " " + _STYLES[style_id]["Style Category"]).lower()))
    def score(t):
        tw = set(re.findall(r"[a-z]+", (t["Mood/Style Keywords"] + " " + t["Font Pairing Name"]).lower()))
        return (len(words & tw), -int(t["No"]))
    best = max(_TYPO, key=score)
    serif_head = best["Category"].lower().startswith("serif")
    head = [f'"{best["Heading Font"]}"'] + (SERIF_ZH if serif_head else SANS_ZH)
    body = [f'"{best["Body Font"]}"'] + SANS_ZH
    return {"name": best["Font Pairing Name"], "heading": head, "body": body}


def palette(product_type: str, dark: bool, fam: str = "soft", hexes: list[str] | None = None, brand: list[str] | None = None) -> dict:
    """行业配色给品牌主色（按钮、强调）；风格家族和风格自带颜色决定背景、色带和整体观感。"""
    c = _COLORS.get(product_type) or _COLORS["SaaS (General)"]
    p = {k: c[v] for k, v in (("primary", "Primary"), ("secondary", "Secondary"), ("accent", "Accent"), ("background", "Background"),
                               ("foreground", "Foreground"), ("card", "Card"), ("muted", "Muted Foreground"), ("border", "Border"))}
    if brand:  # 品牌色（用户给的或喂养学到的参考网站颜色）优先当主色；风格颜色按与它的色相远近排
        p["primary"] = brand[0].upper()
        if len(brand) > 1:
            p["accent"] = brand[1].upper()
        hexes = [b.upper() for b in brand] + list(hexes or [])
    anchor = p["primary"]
    light = _near_brand([h for h in (hexes or []) if _lum(h) > 0.35 and h not in ("#FFFFFF",)], anchor)
    vivid = _near_brand([h for h in (hexes or []) if 0.04 < _lum(h) < 0.75 and h not in ("#000000", "#FFFFFF")], anchor)
    if fam == "tech":
        # 深墨蓝底（带一点行业主色的色调），细线边框，主色提亮到深底上够亮
        canvas = _mix(p["primary"], "#05070D", 0.93)
        p.update(background=canvas, card=_mix(canvas, "#FFFFFF", 0.045), foreground="#E8ECF4", muted="#9AA6B8",
                 border=_mix(canvas, "#FFFFFF", 0.13))
        p["band"], p["band-2"] = _mix(canvas, "#FFFFFF", 0.025), canvas
        for _ in range(8):
            if contrast(p["primary"], canvas) >= 4.5:
                break
            p["primary"] = _mix(p["primary"], "#FFFFFF", 0.2)
        if contrast(p["accent"], canvas) < 3:
            p["accent"] = _mix(p["accent"], "#FFFFFF", 0.45)
    elif fam == "dark" or dark:
        p.update(background="#0E1116", card="#171B22", foreground="#E9EDF2", muted="#A4AEBB", border="#2A313C")
        p["band"], p["band-2"] = "#141922", "#0E1116"
    elif fam == "block":
        p.update(background="#FFFFFF", card="#FFFFFF", foreground="#111111", border="#111111")
        p["band"] = vivid[0] if vivid else p["accent"]
        p["band-2"] = vivid[1] if len(vivid) > 1 else p["secondary"]
    elif fam == "minimal":
        p.update(background="#FFFFFF", card="#FFFFFF", foreground="#111111", border="#E5E5E5")
        p["band"] = next((h for h in light if _lum(h) > 0.8), "#F6F6F4")
        p["band-2"] = "#FFFFFF"
    elif fam == "glass":
        a = vivid[0] if vivid else p["primary"]
        b = vivid[1] if len(vivid) > 1 else p["accent"]
        p["band"], p["band-2"] = _mix(a, "#FFFFFF", 0.55), _mix(b, "#FFFFFF", 0.55)
        p.update(background=_mix(a, "#FFFFFF", 0.8), card="#FFFFFF", foreground="#111827", border="#FFFFFF")
    elif fam == "editorial":
        p.update(background="#FBFAF7", card="#FBFAF7", foreground="#151515", border="#151515")
        p["band"], p["band-2"] = "#F1EEE7", "#FBFAF7"
    else:  # soft
        base = light[0] if light else p["primary"]
        # 第十四轮：用户觉得粉色“不够高端”——底色先去掉一半饱和度再冲淡，只留一点暖意，不再整页粉/整页蓝
        base = _mix(base, "#8C8A86", 0.55)
        p.update(background=_mix(base, "#FFFFFF", 0.93), card="#FFFFFF", border=_mix(base, "#FFFFFF", 0.72))
        p["band"], p["band-2"] = _mix(base, "#FFFFFF", 0.85), _mix(base, "#FFFFFF", 0.96)
    for _ in range(6):  # 有界：主色在背景上至少 3:1，最多调 6 次
        if contrast(p["primary"], p["background"]) >= 3:
            break
        p["primary"] = _mix(p["primary"], "#FFFFFF" if _lum(p["background"]) < 0.3 else "#000000", 0.25)
    if contrast(p["foreground"], p["background"]) < 4.5:
        p["foreground"] = _best_on(p["background"])
    if contrast(p["muted"], p["background"]) < 4.5:
        p["muted"] = _mix(p["foreground"], p["background"], 0.25)
    p["on-primary"] = _best_on(p["primary"])
    p["band-ink"] = _best_on(p["band"])
    # 链接是正文大小的文字，要 4.5:1（主色只保证了 3:1，够按钮、不够文字链接：D19）
    toward, link, t = ("#FFFFFF" if _lum(p["background"]) < 0.3 else "#000000"), p["primary"], 0.0
    on = [p["background"]] + ([p["band"]] if (_lum(p["band"]) < 0.3) == (_lum(p["background"]) < 0.3) else [])  # 链接也会出现在色带区块上
    while min(contrast(link, c) for c in on) < 4.5 and t < 1:
        t = round(t + 0.1, 2)
        link = _mix(p["primary"], toward, t)
    p["link"] = link
    return p


def _hex(h, alpha=None):
    v = {"colorSpace": "srgb", "components": [round(x, 3) for x in _rgb(h)], "hex": h.upper()}
    if alpha is not None:
        v["alpha"] = alpha
    return {"$value": v}


def tokens(style_id: str, product_type: str, brand: list[str] | None = None) -> dict:
    pr, fp = profile(style_id), font_pair(style_id)
    fam = family(style_id)
    pal = palette(product_type, pr["dark"], fam, style_hexes(style_id), brand)
    ink = "#000000" if not pr["dark"] else "#000000"
    shadow = {
        "none": [],
        "soft": [{"color": _hex(ink, 0.08)["$value"], "offsetX": {"value": 0, "unit": "px"}, "offsetY": {"value": 2, "unit": "px"},
                  "blur": {"value": 8, "unit": "px"}, "spread": {"value": 0, "unit": "px"}}],
        "hard": [{"color": _hex(pal["foreground"])["$value"], "offsetX": {"value": 4, "unit": "px"}, "offsetY": {"value": 4, "unit": "px"},
                  "blur": {"value": 0, "unit": "px"}, "spread": {"value": 0, "unit": "px"}}],
        "inset": [{"color": _hex(ink, 0.10)["$value"], "offsetX": {"value": 4, "unit": "px"}, "offsetY": {"value": 4, "unit": "px"},
                   "blur": {"value": 10, "unit": "px"}, "spread": {"value": 0, "unit": "px"}},
                  {"color": _hex("#FFFFFF", 0.7)["$value"], "offsetX": {"value": -4, "unit": "px"}, "offsetY": {"value": -4, "unit": "px"},
                   "blur": {"value": 10, "unit": "px"}, "spread": {"value": 0, "unit": "px"}}],
        "glow": [{"color": _hex(pal["primary"], 0.45)["$value"], "offsetX": {"value": 0, "unit": "px"}, "offsetY": {"value": 0, "unit": "px"},
                  "blur": {"value": 16, "unit": "px"}, "spread": {"value": 0, "unit": "px"}}],
    }[pr["shadow"]]
    return {
        "$description": f"风格 {pr['name']}（{style_id}，{FAMILY_ZH[fam]}）× 行业配色 {product_type}；由 text2site/styles.py 从知识库生成",
        "$extensions": {"aisite": {"family": fam, "style_id": style_id}},
        "color": {"$type": "color", **{k: _hex(v) for k, v in pal.items()},
                  "card-surface": _hex(pal["card"], 0.6 if pr["glass"] else 1.0)},
        "radius": {"$type": "dimension", "md": {"$value": {"value": pr["radius"], "unit": "px"}},
                   "lg": {"$value": {"value": round(pr["radius"] * 1.5), "unit": "px"}}},
        "border": {"$type": "dimension", "width": {"$value": {"value": pr["border"], "unit": "px"}}},
        "surface": {"$type": "dimension", "blur": {"$value": {"value": 12 if pr["glass"] else 0, "unit": "px"}}},
        "shadow": {"$type": "shadow", "card": {"$value": shadow}},
        "font": {"$type": "fontFamily", "heading": {"$value": fp["heading"]}, "body": {"$value": fp["body"]}},
        "heading": {"transform": {"$value": "uppercase" if pr["uppercase"] else "none"}},
        "duration": {"$type": "duration", "base": {"$value": {"value": pr["duration"], "unit": "ms"}}},
    }


def options(brief: dict, n: int = 3, learned=None) -> list[dict]:
    """给出 n 种风格候选：用户点名的 → 同行业用户最常选的 → 知识库推荐的 → 补齐差异大的。每个都说明为什么推荐。
    learned：prefs.favourite() 的结果 (风格, 票数, 总数)，没有就是 None。"""
    pref = brief["style_preference"]
    avoided = {a.split("：", 1)[1] for a in brief.get("brand", {}).get("avoid", []) if a.startswith("风格：")}
    usable = {k for k, v in kb.vocab()["styles"].items() if v["status"] != "deprecated"} & set(_STYLES)
    out, looks = [], set()

    def look(sid):
        return family(sid)

    avoided_fams = {family(a) for a in avoided if a in _STYLES}  # 说了“不要暗黑”，整个深色家族都排除
    avoided_fams |= {a.split("：", 1)[1].split("（", 1)[0] for a in brief.get("brand", {}).get("avoid", []) if a.startswith("家族：")}
    if "dark" in avoided_fams:  # 科技感也是深色底：说了不要暗黑，就一起不要
        avoided_fams.add("tech")
    ptype = brief["product_type"]["value"]

    def add(sid, why):
        if sid in usable and sid not in avoided and family(sid) not in avoided_fams and sid not in [o["id"] for o in out] and len(out) < n:
            out.append({"id": sid, "name": _STYLES[sid]["Style Category"], "family": FAMILY_ZH[family(sid)], "why": why})
            looks.add(look(sid))
    src = pref.get("source")
    if src == "user" and pref["style_ids"]:
        add(pref["style_ids"][0], "你点名的风格")
    import learned as _K  # 喂养学到的：纠正里的“偏好某风格”、参考网站的观感家族
    for k in _K.for_type(ptype, "correction"):
        if k.get("prefer_style"):
            add(k["prefer_style"], f"你教过：{_zh_type(ptype)}用这个风格（{k['id']}）")
    for k in _K.for_type(ptype, "site_ref")[-1:]:
        fam = k["family"]
        pick = next((s for s in pref["style_ids"] + DIVERSE if s in usable and family(s) == fam), None)
        if pick:
            add(pick, f"接近你喂的参考网站的观感：{FAMILY_ZH[fam]}（{k['id']}）")
    if learned:
        add(learned[0], f"同行业用户最常选（{learned[1]}/{learned[2]} 次）")
    for i, sid in enumerate(pref["style_ids"]):
        if src == "user" and i == 0:
            continue
        elif family(sid) not in looks:  # 同一家族只留一个，三个选项要看得出区别
            add(sid, f"适合{_zh_type(brief['product_type']['value'])}这类网站")
    # 每次都给一个“科技感”选项（用户 11-25 要求）：没有的话，放在知识库推荐之后、换个感觉之前
    if "tech" not in looks and "tech" not in avoided_fams:
        if len(out) >= n and out[-1]["why"].startswith(("适合", "换个感觉")):
            looks.discard(family(out.pop()["id"]))
        add(TECH_STYLE, "科技感：深色精密，适合想显得专业、高端的网站")
    for sid in DIVERSE:  # 补齐时优先挑观感不同的，让三个选项真的有差别
        if len(out) < n and look(sid) not in looks:
            add(sid, "换个感觉：和前面的不一样")
    for sid in DIVERSE:
        add(sid, "换个感觉")
    return out
