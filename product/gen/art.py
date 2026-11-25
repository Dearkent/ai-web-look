"""示意插图：用户还没给照片时，按网站的风格配色和行业画一张原创的 SVG 插图。

为什么不用“网上找图”：版权说不清，也可能被当成店里的实拍。这里的插图：
  * 全部用几何图形现画，不引用任何外部文件、不含脚本、不含文字（不会和页面文案打架）；
  * 同一个位置每次画出来都一样（按位置算随机种子），重新生成网站不会“换图”；
  * 一看就是插图，不冒充实拍；工作台和上线体检会提醒“还有几张示意插图，建议换成你的照片”。

风格家族决定画法：大色块（实色块+硬阴影）、柔和圆润（圆斑+柔光）、极简（细线）、
毛玻璃渐变（模糊光斑+半透明卡片）、深色（暗底发光线条）、杂志排版（纸色+网点+细线）。
"""
from __future__ import annotations

import hashlib
import random

# 行业 → 图案。按英文行业名里的关键词匹配，第一个命中的算数；都不命中用“闪光”
MOTIF_WORDS = [
    ("cup", ["cafe", "bakery", "restaurant", "food", "brewery", "winery"]),
    ("paw", ["veterinary", "pet"]),
    ("tooth", ["dental"]),
    ("heart", ["medical", "clinic", "pharmacy", "senior", "mental", "health", "non-profit", "charity", "childcare"]),
    ("leaf", ["beauty", "spa", "wellness", "florist", "plant", "agriculture", "farm", "sustainable", "climate", "energy"]),
    ("dumbbell", ["fitness", "gym", "sports"]),
    ("book", ["course", "learning", "bootcamp", "magazine", "blog", "news", "museum"]),
    ("house", ["real estate", "property", "home", "interior", "construction", "architecture", "coworking", "hotel"]),
    ("mountain", ["travel", "tourism"]),
    ("camera", ["photography", "portfolio", "creative", "wedding", "event", "theater", "cinema", "podcast", "conference"]),
    ("bag", ["e-commerce", "shop", "store", "luxury"]),
    ("chart", ["insurance", "finance", "bank", "marketing", "b2b", "job", "recruitment", "membership", "logistics", "delivery"]),
    ("car", ["automotive", "car"]),
    ("window", ["saas", "ai", "chatbot", "open source", "platform", "app"]),
]


def motif_for(product_type: str) -> str:
    key = (product_type or "").lower()
    for m, words in MOTIF_WORDS:
        if any(w in key for w in words):
            return m
    return "spark"


# 一组卡片（作品、商品）如果全是同一个图案会很单调：按序号在主图案和两个相近图案之间轮换
RELATED = {"cup": ("leaf", "house"), "paw": ("heart", "house"), "tooth": ("heart", "spark"), "heart": ("leaf", "spark"),
           "leaf": ("heart", "spark"), "dumbbell": ("heart", "spark"), "book": ("window", "spark"), "house": ("leaf", "spark"),
           "mountain": ("camera", "house"), "camera": ("mountain", "spark"), "bag": ("spark", "heart"), "chart": ("window", "spark"),
           "car": ("mountain", "spark"), "window": ("chart", "spark"), "spark": ("leaf", "mountain")}


def motif_at(motif: str, index: int | None) -> str:
    if index is None:
        return motif
    return ((motif,) + RELATED.get(motif, ("spark", "leaf")))[index % 3]


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def mix(a, b, t):
    """a 和 b 按比例混色，t=0 是 a，t=1 是 b。"""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def lum(h):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ok_hex(h, fallback):
    h = (h or "").strip()
    if len(h) == 7 and h[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in h[1:]):
        return h.upper()
    return fallback


def colors_from_tokens(tokens: dict) -> dict:
    """从设计令牌（DTCG）里取颜色；取不到的用安全的默认值。引用（{color.primary}）最多解 4 层。"""
    col = (tokens or {}).get("color", {})

    def get(name, fallback):
        v, seen = col.get(name, {}), 0
        while seen < 4:
            val = v.get("$value") if isinstance(v, dict) else None
            if isinstance(val, dict):
                return _ok_hex(val.get("hex"), fallback)
            if isinstance(val, str) and val.startswith("{color.") and val.endswith("}"):
                v, seen = col.get(val[7:-1], {}), seen + 1
                continue
            if isinstance(val, str):
                return _ok_hex(val, fallback)
            break
        return fallback
    c = {k: get(k, d) for k, d in (("primary", "#2F5BD3"), ("secondary", "#6B7280"), ("accent", "#F59E0B"), ("background", "#FFFFFF"),
                                   ("foreground", "#111111"), ("card", "#FFFFFF"), ("border", "#E5E7EB"), ("band", ""), ("band-2", ""))}
    c["band"] = c["band"] or mix(c["primary"], c["background"], 0.8)
    c["band-2"] = c["band-2"] or c["background"]
    return c


# ---------- 图案：都画在 200×200 的格子里，中心 (100,100) ----------
def _motif(m: str, ink: str, fill: str, sw: float, filled: bool) -> str:
    f = fill if filled else "none"
    s = f'stroke="{ink}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"'
    if m == "cup":
        return (f'<ellipse cx="96" cy="150" rx="62" ry="12" fill="{f}" {s}/>'
                f'<path d="M50 78h92l-8 58a14 14 0 0 1-14 12H72a14 14 0 0 1-14-12z" fill="{f}" {s}/>'
                f'<path d="M140 90a18 18 0 1 1-4 34" fill="none" {s}/>'
                f'<path d="M78 60c-8-10 8-16 0-28M98 60c-8-10 8-16 0-28M118 60c-8-10 8-16 0-28" fill="none" {s}/>')
    if m == "paw":
        return (f'<path d="M100 104c22 0 44 26 40 44-3 14-22 12-40 12s-37 2-40-12c-4-18 18-44 40-44z" fill="{f}" {s}/>'
                + "".join(f'<ellipse cx="{x}" cy="{y}" rx="13" ry="17" fill="{f}" {s}/>' for x, y in ((58, 84), (84, 58), (116, 58), (142, 84))))
    if m == "tooth":
        return (f'<path d="M64 46c14-8 26 2 36 2s22-10 36-2c18 10 12 40 4 58-6 14-6 50-20 50-12 0-10-34-20-34s-8 34-20 34'
                f'c-14 0-14-36-20-50-8-18-14-48 4-58z" fill="{f}" {s}/>')
    if m == "heart":
        return (f'<path d="M100 160C60 132 36 108 36 80a30 30 0 0 1 64-14 30 30 0 0 1 64 14c0 28-24 52-64 80z" fill="{f}" {s}/>'
                f'<path d="M100 82v40M80 102h40" fill="none" {s}/>')
    if m == "leaf":
        return (f'<path d="M100 164C48 150 40 86 92 40c56 34 58 104 8 124z" fill="{f}" {s}/>'
                f'<path d="M100 164c-2-40 0-80-8-124M98 96l-22-14M100 124l24-18" fill="none" {s}/>')
    if m == "dumbbell":
        return (f'<rect x="34" y="64" width="22" height="72" rx="6" fill="{f}" {s}/><rect x="144" y="64" width="22" height="72" rx="6" fill="{f}" {s}/>'
                f'<rect x="16" y="78" width="18" height="44" rx="5" fill="{f}" {s}/><rect x="166" y="78" width="18" height="44" rx="5" fill="{f}" {s}/>'
                f'<path d="M56 100h88" fill="none" {s}/>')
    if m == "book":
        return (f'<path d="M100 56c-18-12-44-14-64-8v104c20-6 46-4 64 8 18-12 44-14 64-8V48c-20-6-46-4-64 8z" fill="{f}" {s}/>'
                f'<path d="M100 56v104M52 76c12-2 24 0 34 4M52 100c12-2 24 0 34 4M114 80c10-4 22-6 34-4" fill="none" {s}/>')
    if m == "house":
        return (f'<path d="M36 96l64-54 64 54" fill="none" {s}/><path d="M52 84v74h96V84" fill="{f}" {s}/>'
                f'<rect x="88" y="114" width="24" height="44" rx="3" fill="none" {s}/><rect x="62" y="100" width="18" height="18" fill="none" {s}/>'
                f'<rect x="120" y="100" width="18" height="18" fill="none" {s}/>')
    if m == "mountain":
        return (f'<circle cx="146" cy="56" r="16" fill="{f}" {s}/>'
                f'<path d="M20 160l52-80 30 44 22-28 56 64z" fill="{f}" {s}/><path d="M60 98l12-18 12 18" fill="none" {s}/>')
    if m == "camera":
        return (f'<rect x="30" y="64" width="140" height="94" rx="14" fill="{f}" {s}/><path d="M74 64l10-18h32l10 18" fill="none" {s}/>'
                f'<circle cx="100" cy="111" r="30" fill="none" {s}/><circle cx="100" cy="111" r="14" fill="none" {s}/>'
                f'<circle cx="148" cy="84" r="4" fill="{ink}"/>')
    if m == "bag":
        return (f'<path d="M46 72h108l-8 92H54z" fill="{f}" {s}/><path d="M76 86V64a24 24 0 0 1 48 0v22" fill="none" {s}/>')
    if m == "chart":
        return (f'<path d="M34 160h136" fill="none" {s}/>'
                + "".join(f'<rect x="{x}" y="{y}" width="20" height="{160 - y}" rx="3" fill="{f}" {s}/>' for x, y in ((46, 120), (78, 100), (110, 82), (142, 60)))
                + f'<path d="M44 96l34-22 32 10 44-40M138 44h16v16" fill="none" {s}/>')
    if m == "car":
        return (f'<path d="M28 126v-20l22-6 20-30h60l22 30 20 6v20z" fill="{f}" {s}/>'
                f'<circle cx="64" cy="128" r="16" fill="{fill}" {s}/><circle cx="136" cy="128" r="16" fill="{fill}" {s}/><path d="M80 100h40" fill="none" {s}/>')
    if m == "window":
        return (f'<rect x="26" y="44" width="148" height="112" rx="12" fill="{f}" {s}/><path d="M26 68h148" fill="none" {s}/>'
                f'<circle cx="42" cy="56" r="3" fill="{ink}"/><circle cx="54" cy="56" r="3" fill="{ink}"/><circle cx="66" cy="56" r="3" fill="{ink}"/>'
                f'<path d="M44 92h56M44 108h40M44 124h48" fill="none" {s}/><rect x="112" y="86" width="44" height="50" rx="6" fill="none" {s}/>')
    # spark
    return (f'<path d="M100 30c6 40 30 64 70 70-40 6-64 30-70 70-6-40-30-64-70-70 40-6 64-30 70-70z" fill="{f}" {s}/>'
            f'<path d="M156 44c2 10 8 16 18 18-10 2-16 8-18 18-2-10-8-16-18-18 10-2 16-8 18-18z" fill="{f}" {s}/>')


def _place(motif_svg: str, cx: float, cy: float, size: float) -> str:
    k = size / 200
    return f'<g transform="translate({cx - 100 * k:.1f} {cy - 100 * k:.1f}) scale({k:.3f})">{motif_svg}</g>'


def draw(colors: dict, family: str, motif: str, seed: str, w: int = 800, h: int = 600) -> str:
    """画一张插图，返回完整的 SVG 文本。colors 用 colors_from_tokens 的结果。"""
    rnd = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12], 16))
    c = {k: _ok_hex(v, "#888888") for k, v in colors.items()}
    pri, sec, acc, bg, fg, band = c["primary"], c["secondary"], c["accent"], c["background"], c["foreground"], c["band"]
    cx, cy, m = w * rnd.uniform(0.46, 0.56), h * rnd.uniform(0.47, 0.55), min(w, h)
    defs, body = "", ""
    if family == "block":
        base = band if lum(band) > 0.08 else pri
        body += f'<rect width="{w}" height="{h}" fill="{base}"/>'
        for _ in range(3):
            x, y, s = rnd.uniform(0, w * .8), rnd.uniform(0, h * .7), rnd.uniform(m * .18, m * .34)
            body += f'<rect x="{x:.0f}" y="{y:.0f}" width="{s:.0f}" height="{s * rnd.uniform(.5, 1.2):.0f}" fill="{rnd.choice([sec, acc, bg])}" stroke="#111111" stroke-width="6"/>'
        disc = m * .62
        body += f'<circle cx="{cx + 14:.0f}" cy="{cy + 14:.0f}" r="{disc / 2:.0f}" fill="#111111"/><circle cx="{cx:.0f}" cy="{cy:.0f}" r="{disc / 2:.0f}" fill="{bg}" stroke="#111111" stroke-width="6"/>'
        body += _place(_motif(motif, "#111111", pri, 9, True), cx, cy, disc * .74)
    elif family == "minimal":
        body += f'<rect width="{w}" height="{h}" fill="{band}"/>'
        y0 = h * rnd.uniform(.74, .8)
        r = m * rnd.uniform(.3, .36)
        body += f'<circle cx="{cx + m * .12:.0f}" cy="{cy - m * .06:.0f}" r="{r:.0f}" fill="{mix(pri, band, .78)}"/>'
        body += f'<path d="M0 {y0:.0f}H{w}" stroke="{fg}" stroke-width="3"/>'
        body += f'<circle cx="{w * rnd.uniform(.74, .84):.0f}" cy="{h * rnd.uniform(.18, .26):.0f}" r="{m * .05:.0f}" fill="{pri}"/>'
        body += _place(_motif(motif, fg, band, 4, True), cx, cy, m * .62)
    elif family == "glass":
        defs += f'<filter id="b" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="{m * .07:.0f}"/></filter>'
        defs += f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{mix(pri, "#FFFFFF", .55)}"/><stop offset="1" stop-color="{mix(acc, "#FFFFFF", .5)}"/></linearGradient>'
        body += f'<rect width="{w}" height="{h}" fill="url(#g)"/>'
        for col in (pri, acc, sec):
            body += f'<circle cx="{rnd.uniform(0, w):.0f}" cy="{rnd.uniform(0, h):.0f}" r="{rnd.uniform(m * .2, m * .34):.0f}" fill="{col}" opacity=".55" filter="url(#b)"/>'
        cw, ch = m * .62, m * .62
        body += (f'<rect x="{cx - cw / 2:.0f}" y="{cy - ch / 2:.0f}" width="{cw:.0f}" height="{ch:.0f}" rx="{m * .06:.0f}" '
                 f'fill="#FFFFFF" fill-opacity=".45" stroke="#FFFFFF" stroke-opacity=".8" stroke-width="2"/>')
        body += _place(_motif(motif, mix(pri, "#000000", .35), "#FFFFFF", 6, True), cx, cy, cw * .78)
    elif family == "tech":
        # 深底 + 细网格（中间亮、四周淡出）+ 一道主色光 + 发光线条图案
        defs += f'<filter id="b" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="{m * .08:.0f}"/></filter>'
        defs += (f'<radialGradient id="fade" cx=".5" cy=".45" r=".6"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".9"/>'
                 f'<stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></radialGradient><mask id="m"><rect width="{w}" height="{h}" fill="url(#fade)"/></mask>')
        defs += f'<linearGradient id="s" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{mix(pri, "#FFFFFF", .35)}"/><stop offset="1" stop-color="{mix(acc, "#FFFFFF", .3)}"/></linearGradient>'
        base_c = bg if lum(bg) < 0.08 else mix(pri, "#05070D", .93)
        body += f'<rect width="{w}" height="{h}" fill="{base_c}"/>'
        body += f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{m * .42:.0f}" ry="{m * .3:.0f}" fill="{pri}" opacity=".45" filter="url(#b)"/>'
        step = max(28, round(m / 14))
        grid = "".join(f'<path d="M{x} 0V{h}"/>' for x in range(step, w, step)) + "".join(f'<path d="M0 {y}H{w}"/>' for y in range(step, h, step))
        body += f'<g stroke="{mix(base_c, "#FFFFFF", .16)}" stroke-width="1" mask="url(#m)">{grid}</g>'
        body += _place(_motif(motif, "url(#s)", "none", 4.5, False), cx, cy, m * .58)
    elif family == "dark":
        defs += f'<filter id="b" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="{m * .06:.0f}"/></filter>'
        body += f'<rect width="{w}" height="{h}" fill="{mix(bg, "#000000", .2)}"/>'
        for _ in range(2):
            body += f'<circle cx="{rnd.uniform(w * .2, w * .8):.0f}" cy="{rnd.uniform(h * .2, h * .8):.0f}" r="{m * .26:.0f}" fill="{rnd.choice([pri, acc])}" opacity=".35" filter="url(#b)"/>'
        step = max(24, round(m / 12))
        body += "".join(f'<path d="M{x} 0V{h}" stroke="{mix(fg, bg, .9)}" stroke-width="1"/>' for x in range(step, w, step))
        glow = mix(pri, "#FFFFFF", .35)
        body += _place(_motif(motif, glow, "none", 5, False), cx, cy, m * .6)
    elif family == "editorial":
        paper = mix(bg, "#E8E2D4", .35)
        defs += f'<pattern id="d" width="12" height="12" patternUnits="userSpaceOnUse"><circle cx="3" cy="3" r="2.4" fill="{fg}" opacity=".55"/></pattern>'
        body += f'<rect width="{w}" height="{h}" fill="{paper}"/>'
        bx = w * rnd.uniform(.52, .6)
        body += f'<rect x="{bx:.0f}" y="0" width="{w - bx:.0f}" height="{h * .58:.0f}" fill="{pri}"/>'
        body += f'<rect x="{w * .08:.0f}" y="{h * .5:.0f}" width="{w * .34:.0f}" height="{h * .4:.0f}" fill="url(#d)"/>'
        body += f'<rect x="{w * .04:.0f}" y="{h * .05:.0f}" width="{w * .92:.0f}" height="{h * .9:.0f}" fill="none" stroke="{fg}" stroke-width="2"/>'
        body += _place(_motif(motif, fg, paper, 4, True), cx, cy, m * .66)
    else:  # soft
        defs += f'<radialGradient id="r" cx=".3" cy=".25" r=".9"><stop offset="0" stop-color="{mix(band, "#FFFFFF", .5)}"/><stop offset="1" stop-color="{band}"/></radialGradient>'
        body += f'<rect width="{w}" height="{h}" fill="url(#r)"/>'
        for col in (mix(pri, band, .55), mix(acc, band, .6)):
            x, y, r = rnd.uniform(w * .1, w * .9), rnd.uniform(h * .1, h * .9), rnd.uniform(m * .14, m * .26)
            body += f'<ellipse cx="{x:.0f}" cy="{y:.0f}" rx="{r * 1.3:.0f}" ry="{r:.0f}" fill="{col}" opacity=".8"/>'
        disc = m * .6
        body += f'<circle cx="{cx:.0f}" cy="{cy + 8:.0f}" r="{disc / 2:.0f}" fill="{mix(pri, band, .75)}" opacity=".6"/><circle cx="{cx:.0f}" cy="{cy:.0f}" r="{disc / 2:.0f}" fill="#FFFFFF"/>'
        body += _place(_motif(motif, pri, mix(pri, "#FFFFFF", .82), 7, True), cx, cy, disc * .72)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            + (f"<defs>{defs}</defs>" if defs else "") + body + "</svg>\n")


def favicon(colors: dict, initial: str) -> str:
    """网站小图标：主色圆角方块 + 品牌名第一个字。字只能是一个普通字符（防注入）。"""
    ch = (initial or "·")[:1]
    if ch in '<>&"\'' or not ch.isprintable():
        ch = "·"
    c = {k: _ok_hex(v, "#2F5BD3") for k, v in colors.items()}
    ink = "#FFFFFF" if lum(c["primary"]) < 0.4 else "#111111"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="{c["primary"]}"/>'
            f'<text x="32" y="44" text-anchor="middle" font-size="34" font-family="system-ui,sans-serif" font-weight="700" fill="{ink}">{ch}</text></svg>\n')
