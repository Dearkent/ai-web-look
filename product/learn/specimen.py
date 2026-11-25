#!/usr/bin/env python3
"""设计标本：把一个网站（一个文件夹、一个网页文件、或一段 HTML+CSS）读成一条“设计特征”。

规矩（用户定的）：第三方的东西只当数据读，不运行、不拷贝。
  * 只用标准库的 html.parser 和正则静态解析。脚本（<script>）整段跳过，不执行，不联网。
  * 只保存数字、颜色值、类别（区块类型、风格家族）、字体名（过滤成字母数字）和来源。
    不保存标题、正文、图片、链接；页面文字只在内存里用来猜行业，用完就丢。
  * CSS 只统计“这个页面真的用到的”规则：选择器里的类名和标签都出现在页面上才算，
    避免 Bootstrap 之类整套框架 CSS 把颜色和字号统计带歪。Tailwind 类名按官方刻度换算成数值。
"""
from __future__ import annotations

import colorsys
import hashlib
import html.parser
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "text2site"))

MAX_HTML = 2 * 1024 * 1024
MAX_CSS = 4 * 1024 * 1024
MAX_PAGES = 4
SKIP_DIRS = {"node_modules", ".git", "vendor", "vendors", "bower_components", "__pycache__", ".github", "test", "tests", "example-assets"}
PREFER_DIRS = ("dist", "docs", "public", "build", "site", "www", "html", "src")

# ---------------------------------------------------------------- 颜色
NAMED = {"white": "#FFFFFF", "black": "#000000", "transparent": None, "inherit": None, "currentcolor": None, "initial": None}


def hex6(h: str) -> str | None:
    h = h.strip().lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    elif len(h) == 8:
        h = h[:6]
    if len(h) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        return None
    return "#" + h.upper()


def parse_color(v: str) -> str | None:
    v = v.strip().lower()
    m = re.match(r"#([0-9a-f]{3,8})\b", v)
    if m:
        return hex6(m.group(1))
    m = re.match(r"rgba?\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})(?:[\s,/]+([\d.]+%?))?", v)
    if m:
        a = m.group(4)
        if a is not None and (float(a.rstrip("%")) / (100 if a.endswith("%") else 1)) < 0.5:
            return None  # 半透明的叠加色不算品牌色
        return "#" + "".join(f"{min(int(x), 255):02X}" for x in m.groups()[:3])
    m = re.match(r"hsla?\(\s*([\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%", v)
    if m:
        r, g, b = colorsys.hls_to_rgb(float(m.group(1)) / 360 % 1, float(m.group(3)) / 100, float(m.group(2)) / 100)
        return "#" + "".join(f"{round(x * 255):02X}" for x in (r, g, b))
    return NAMED.get(v.split()[0]) if v else None


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def lum(h):
    def ch(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def hls(h):
    return colorsys.rgb_to_hls(*rgb(h))


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# Tailwind 调色板：每个颜色名的色相/饱和度 + 每个色阶的亮度（近似官方值，只为统计深浅和色相）
TW_HUE = {"slate": (215, .16), "gray": (220, .09), "zinc": (240, .05), "neutral": (0, 0), "stone": (25, .06),
          "red": (0, .72), "orange": (25, .9), "amber": (38, .92), "yellow": (48, .95), "lime": (84, .8), "green": (142, .7),
          "emerald": (160, .84), "teal": (173, .8), "cyan": (189, .9), "sky": (199, .89), "blue": (217, .91), "indigo": (239, .84),
          "violet": (258, .9), "purple": (271, .81), "fuchsia": (292, .84), "pink": (330, .81), "rose": (350, .89)}
TW_L = {"50": .97, "100": .94, "200": .87, "300": .77, "400": .64, "500": .53, "600": .45, "700": .37, "800": .27, "900": .2, "950": .12}
TW_TEXT = {"xs": 12, "sm": 14, "base": 16, "lg": 18, "xl": 20, "2xl": 24, "3xl": 30, "4xl": 36, "5xl": 48, "6xl": 60, "7xl": 72, "8xl": 96, "9xl": 128}
TW_ROUND = {"none": 0, "sm": 2, "": 4, "md": 6, "lg": 8, "xl": 12, "2xl": 16, "3xl": 24}
TW_MAXW = {"7xl": 1280, "6xl": 1152, "5xl": 1024, "4xl": 896, "screen-xl": 1280, "screen-lg": 1024, "screen-2xl": 1536}


def tw_color(name: str, shade: str) -> str | None:
    if name == "white":
        return "#FFFFFF"
    if name == "black":
        return "#000000"
    if name not in TW_HUE or shade not in TW_L:
        return None
    hh, ss = TW_HUE[name]
    r, g, b = colorsys.hls_to_rgb(hh / 360, TW_L[shade], ss)
    return "#" + "".join(f"{round(x * 255):02X}" for x in (r, g, b))


# ---------------------------------------------------------------- 区块分类
SECTION_RULES = [  # 按顺序匹配：(类型, 词)。词在 id/class 或区块标题里出现就算
    ("testimonials", ["testimonial", "review", "what-people", "what-our", "client-say", "customers-say", "评价", "口碑"]),
    ("pricing", ["pricing", "price", "plans", "价格", "套餐"]),
    ("faq", ["faq", "question", "常见问题", "问答"]),
    ("team", ["team", "staff", "our-people", "团队", "医生", "律师团队"]),
    ("logos", ["logo", "partner", "brand", "trusted", "sponsor", "合作伙伴"]),
    ("stats", ["stat", "counter", "number", "fact", "metric", "数据"]),
    ("steps", ["step", "process", "how-it-works", "how it works", "timeline", "workflow", "流程", "步骤"]),
    ("gallery", ["portfolio", "gallery", "showcase", "our-work", "works", "projects", "作品", "案例"]),
    ("menu", ["menu-section", "food-menu", "our-menu", "菜单", "价目"]),
    ("newsletter", ["newsletter", "subscribe", "订阅"]),
    ("blog-list", ["blog", "news", "article", "posts", "动态", "文章"]),
    ("contact-form", ["contact", "get-in-touch", "联系"]),
    ("map", ["map", "location", "地址", "到店"]),
    ("cta", ["cta", "call-to-action", "get-started", "signup", "sign-up", "download", "join", "开始"]),
    ("features", ["feature", "service", "benefit", "why", "what-we-do", "offer", "capabilit", "solution", "功能", "服务", "优势"]),
    ("content", ["about", "story", "mission", "intro", "who-we", "关于", "故事"]),
]
HERO_WORDS = ["hero", "masthead", "banner", "jumbotron", "splash", "landing-header", "showcase-top", "首屏"]
LANDMARK = {"header", "nav", "section", "footer", "main", "article", "aside"}


class _Scan(html.parser.HTMLParser):
    """一遍扫完：收集页面用到的类名/标签、内联样式和 <style>、外链 CSS 地址、区块和猜行业用的少量文字。"""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.classes, self.tags, self.ids = set(), set(), set()
        self.css, self.links, self.inline = [], [], []
        self.tw = []  # (类名, 所在区块序号)
        self.blocks = []  # 每个区块的特征
        self.stack = []  # [(tag, 是否开启了区块)]
        self.cur = None  # 当前区块序号
        self.skip = 0  # 在 <script>/<template> 里
        self.in_style = False
        self.in_title = False
        self.head_text = []  # 只用来猜行业：title、description、h1、h2
        self.heading_tag = None
        self.nav_links = 0
        self.in_nav = 0
        self.body_classes = []
        self.html_classes = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in ("script", "template", "noscript", "svg"):
            if tag not in self.VOID:
                self.skip += 1
                self.stack.append((tag, False))
            return
        if self.skip:
            if tag not in self.VOID:
                self.stack.append((tag, False))
            return
        cls = a.get("class", "").split()
        self.tags.add(tag)
        self.classes.update(cls)
        if a.get("id"):
            self.ids.add(a["id"])
        if a.get("style"):
            self.inline.append(a["style"])
        if tag == "body":
            self.body_classes = cls
        if tag == "html":
            self.html_classes = cls
        if tag == "style":
            self.in_style = True
        if tag == "title":
            self.in_title = True
        if tag == "meta" and a.get("name", "").lower() == "description":
            self.head_text.append(a.get("content", "")[:300])
        if tag == "link" and "stylesheet" in a.get("rel", "").lower() and a.get("href"):
            self.links.append(a["href"])
        opened = False
        key = " ".join(cls + [a.get("id", "")]).lower()
        if tag in ("section", "header", "footer", "article") and not self._in_block() or (
                tag == "div" and not self._in_block() and self._depth_ok() and (a.get("id") or any(w in key for w in HERO_WORDS))):
            self.blocks.append({"tag": tag, "key": key, "h": "", "h1": 0, "btn": 0, "img": 0, "form": 0, "quote": 0,
                                "details": 0, "price": 0, "words": 0, "li": 0, "cards": 0})
            self.cur = len(self.blocks) - 1
            opened = True
        if tag == "nav":
            self.in_nav += 1
        if self.in_nav and tag == "a":
            self.nav_links += 1
        b = self.blocks[self.cur] if self.cur is not None else None
        if b is not None:
            if tag == "h1":
                b["h1"] += 1
            if tag in ("button",) or (tag == "a" and any(c.startswith(("btn", "button")) or c in ("cta",) for c in cls)):
                b["btn"] += 1
            if tag in ("img", "picture", "video"):
                b["img"] += 1
            if tag == "form" or tag == "input" and a.get("type", "") in ("email", "text", "tel"):
                b["form"] += 1
            if tag == "blockquote":
                b["quote"] += 1
            if tag == "details":
                b["details"] += 1
            if tag == "li":
                b["li"] += 1
            if any("card" in c for c in cls):
                b["cards"] += 1
        for c in cls:
            self.tw.append((c, self.cur))
        if tag in ("h1", "h2", "h3"):
            self.heading_tag = tag
        if tag not in self.VOID:
            self.stack.append((tag, opened))

    def _in_block(self):
        return any(o for _, o in self.stack)

    def _depth_ok(self):
        return sum(1 for t, _ in self.stack if t in ("div", "main")) <= 3

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
        if tag == "title":
            self.in_title = False
        if tag in ("h1", "h2", "h3"):
            self.heading_tag = None
        if tag == "nav" and self.in_nav:
            self.in_nav -= 1
        # 弹到对应的开标签（容错：HTML 常常不闭合）
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                popped = self.stack[i:]
                del self.stack[i:]
                if any(t in ("script", "template", "noscript", "svg") for t, _ in popped):
                    self.skip = sum(1 for t, _ in self.stack if t in ("script", "template", "noscript", "svg"))
                if any(o for _, o in popped):
                    self.cur = None
                break

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_style:
            self.css.append(data)
            return
        t = data.strip()
        if not t:
            return
        if self.in_title:
            self.head_text.append(t[:200])
        if self.heading_tag in ("h1", "h2"):
            self.head_text.append(t[:120])
        b = self.blocks[self.cur] if self.cur is not None else None
        if b is not None:
            if self.heading_tag and not b["h"]:
                b["h"] = t[:60].lower()  # 只在分类时用，不进结果
            cjk = len(re.findall(r"[一-鿿]", t))
            b["words"] += len(re.findall(r"[A-Za-z0-9']+", t)) + (cjk + 1) // 2
            if re.search(r"[$€£¥]\s?\d|\d+\s?(?:/mo|/month|元|/月)", t):
                b["price"] += 1


def classify(b: dict, first_content: bool) -> str:
    key, h = b["key"].replace("_", "-"), b["h"]
    if b["tag"] == "footer" or re.search(r"\bfooter\b", key):
        return "footer"
    if any(w in key for w in HERO_WORDS):
        return "hero"
    toks = set(re.split(r"[\s-]+", key))
    for t, words in SECTION_RULES:  # id/class 说得最准，先看它
        if any(w in key for w in words) or (t == "menu" and toks & {"menu", "products", "product", "shop", "store", "collection", "dishes", "drinks"}):
            return t
    if b["h1"] or (first_content and b["btn"] and b["words"] < 120):
        return "hero"
    if b["quote"] >= 2:
        return "testimonials"
    if b["price"] >= 2:
        return "pricing"
    if b["details"] >= 3:
        return "faq"
    if b["form"]:
        return "contact-form"
    for t, words in SECTION_RULES:
        if any(w in h for w in words):
            return t
    if b["tag"] == "header" and not b["words"]:
        return "header"
    return "content"


# ---------------------------------------------------------------- CSS
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
DECL = re.compile(r"([a-zA-Z-]+)\s*:\s*([^;]+)")
VAR_DEF = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+)")
SCSS_VAR = re.compile(r"\$([\w-]+)\s*:\s*([^;{}]+);")


def _len_px(v: str, base=16.0) -> float | None:
    m = re.match(r"\s*(-?\d*\.?\d+)\s*(px|rem|em)?\b", v)
    if not m:
        return None
    n, u = float(m.group(1)), m.group(2) or ("px" if float(m.group(1)) == 0 else None)
    if u is None:
        return None
    return n * (base if u in ("rem", "em") else 1)


def _clamp_max(v: str) -> str:
    """clamp(a, b, c) / min() / max() → 取最大的那个长度（标题实际会到的大小）。"""
    m = re.match(r"\s*(?:clamp|min|max)\((.*)\)", v)
    if not m:
        return v
    vals = [_len_px(x) for x in m.group(1).split(",")]
    vals = [x for x in vals if x is not None]
    return f"{max(vals)}px" if vals else v


def _selector_used(sel: str, used_classes: set, used_tags: set, used_ids: set) -> bool:
    sel = sel.strip()
    if not sel or sel.startswith("@") or re.fullmatch(r"(?:from|to|\d+%)(?:\s*,\s*(?:from|to|\d+%))*", sel):
        return False
    for part in sel.split(","):
        last = re.split(r"\s+|>|\+|~", part.strip())[-1] if part.strip() else ""
        last = re.sub(r"::?[\w-]+(\([^)]*\))?", "", last)  # 去掉 :hover ::before
        if not last or last == "*":
            continue
        classes = re.findall(r"\.([\w-]+)", last)
        ids = re.findall(r"#([\w-]+)", last)
        tag = re.match(r"[a-zA-Z][\w-]*", last)
        if classes and not all(c in used_classes for c in classes):
            continue
        if ids and not all(i in used_ids for i in ids):
            continue
        if tag and tag.group(0).lower() not in used_tags | {"html", "body", ":root"}:
            continue
        if not (classes or ids or tag) and not last.startswith(":root"):
            continue
        return True
    return False


def css_rules(css: str):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in RULE.finditer(css):
        yield m.group(1).strip(), m.group(2)


def _resolve(v: str, vars_: dict, depth=0) -> str:
    if depth > 4:
        return v
    def sub(m):
        name, fb = m.group(1), m.group(2)
        return _resolve(vars_.get(name, fb or ""), vars_, depth + 1)
    v = re.sub(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\))?[^()]*))?\)", sub, v)
    return re.sub(r"\$([\w-]+)", lambda m: _resolve(vars_.get("$" + m.group(1), m.group(0)), vars_, depth + 1), v)


# ---------------------------------------------------------------- 主流程
def find_entry(root: str) -> list[str]:
    """在一个文件夹里找代表页面：优先 dist/docs/public 下的 index.html，然后最浅的 index.html，再加几个同目录页面。"""
    cands = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        rel = os.path.relpath(dp, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > 4:
            dns[:] = []
            continue
        for f in fns:
            if f.lower().endswith((".html", ".htm")):
                cands.append((dp, f, depth))
    if not cands:
        return []
    def rank(c):
        dp, f, depth = c
        first = os.path.relpath(dp, root).split(os.sep)[0]
        pref = PREFER_DIRS.index(first) if first in PREFER_DIRS else len(PREFER_DIRS)
        return (f.lower() not in ("index.html", "index.htm"), depth, pref, f)
    best = sorted(cands, key=rank)[0]
    same = sorted(f for dp, f, _ in cands if dp == best[0] and f != best[1] and not re.search(r"404|error|test|example", f, re.I))
    return [os.path.join(best[0], best[1])] + [os.path.join(best[0], f) for f in same[:MAX_PAGES - 1]]


def _read(p, limit):
    try:
        with open(p, "rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def collect(root_or_file: str) -> dict | None:
    """读一个文件夹或一个 .html 文件，返回 {"pages": [html...], "css": [css...], "base": 目录}。外链只读本地文件，不联网。"""
    if os.path.isfile(root_or_file):
        pages, root = [root_or_file], os.path.dirname(root_or_file)
    else:
        root = root_or_file
        pages = find_entry(root)
    if not pages:
        return None
    docs, css, total = [], [], 0
    for p in pages:
        doc = _read(p, MAX_HTML)
        docs.append(doc)
        for href in re.findall(r"<link[^>]+rel=[\"']?stylesheet[^>]*>", doc, re.I):
            m = re.search(r"href=[\"']([^\"']+)", href)
            if not m or re.match(r"(?:https?:)?//", m.group(1)):
                continue
            f = os.path.normpath(os.path.join(os.path.dirname(p), m.group(1).split("?")[0].split("#")[0]))
            if not f.startswith(os.path.abspath(root)) and not os.path.abspath(f).startswith(os.path.abspath(root)):
                continue  # 不出这个文件夹
            if os.path.isfile(f) and total < MAX_CSS:
                c = _read(f, MAX_CSS - total)
                total += len(c)
                css.append(c)
    if not css and os.path.isdir(root):  # 没有编译好的 CSS：读源码里的 .css/.scss（变量和规则也能说明设计）
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
            for f in sorted(fns):
                if f.endswith((".css", ".scss")) and not f.endswith(".min.css") and total < MAX_CSS:
                    c = _read(os.path.join(dp, f), MAX_CSS - total)
                    total += len(c)
                    css.append(c)
    return {"pages": docs, "css": css, "base": root}


EN_INDUSTRY = [  # 英文模板猜行业：(词, 行业)；先具体后宽泛
    (["coffee", "cafe", "café", "bakery", "barista"], "Bakery/Cafe"), (["restaurant", "food", "chef", "dining", "pizza", "burger"], "Restaurant/Food Service"),
    (["dental", "dentist", "teeth"], "Dental Practice"), (["clinic", "medical", "doctor", "health care", "healthcare", "hospital"], "Medical Clinic"),
    (["law", "lawyer", "attorney", "legal"], "Legal Services"), (["hotel", "resort", "booking room"], "Hotel/Hospitality"),
    (["spa", "salon", "beauty", "wellness"], "Beauty/Spa/Wellness Service"), (["gym", "fitness", "workout", "yoga"], "Fitness/Gym App"),
    (["wedding", "event planning"], "Wedding/Event Planning"), (["conference", "summit", "meetup", "event"], "Conference / Symposium Landing Page"),
    (["photograph", "photo studio"], "Photography Studio"), (["real estate", "property", "realtor", "apartment"], "Real Estate/Property"),
    (["course", "learning", "academy", "education", "school"], "Online Course/E-learning"), (["nonprofit", "non-profit", "charity", "donate"], "Non-profit/Charity"),
    (["travel", "tour", "trip"], "Travel/Tourism Agency"), (["podcast"], "Podcast Platform"), (["blog", "magazine"], "Magazine/Blog"),
    (["shop", "store", "ecommerce", "e-commerce", "cart"], "E-commerce"), (["ai ", "chatbot", " gpt", "machine learning"], "AI/Chatbot Platform"),
    (["open source", "github", "documentation", "docs"], "Open Source Project Landing"), (["agency", "studio", "creative"], "Creative Agency"),
    (["marketing", "seo"], "Marketing Agency"), (["resume", "portfolio", "freelancer", "personal", "developer", "designer"], "Portfolio/Personal"),
    (["saas", "startup", "app", "software", "platform", "product", "dashboard", "api"], "SaaS (General)"),
]


def guess_industry(text: str) -> tuple[str | None, str]:
    t = " " + text.lower() + " "
    try:
        from understand import detect_product
        pt, conf, words = detect_product(t)
        if conf != "low" and words:
            return pt, "中文词：" + "、".join(words[:3])
    except Exception:
        pass
    for words, pt in EN_INDUSTRY:
        hit = [w for w in words if w in t]
        if hit:
            return pt, "英文词：" + hit[0].strip()
    return None, ""


FAMILIES = ["block", "soft", "minimal", "glass", "dark", "editorial", "tech"]


def extract(bundle: dict, source: dict, industry: str | None = None) -> dict | None:
    """一个网站 → 一条标本（只含数字和类别）。读不出东西返回 None。"""
    if not bundle or not bundle.get("pages"):
        return None
    scans = []
    for doc in bundle["pages"]:
        s = _Scan()
        try:
            s.feed(doc)
        except Exception:
            continue
        scans.append(s)
    if not scans:
        return None
    home = scans[0]
    used_c = set().union(*(s.classes for s in scans))
    used_t = set().union(*(s.tags for s in scans))
    used_i = set().union(*(s.ids for s in scans))
    css = "\n".join(bundle.get("css", []) + [c for s in scans for c in s.css])
    vars_ = {m.group(1): m.group(2).strip() for m in VAR_DEF.finditer(css)}
    vars_.update({"$" + m.group(1): m.group(2).strip() for m in SCSS_VAR.finditer(css)})

    colors, bgs, texts, sizes, radii, pads, maxw = {}, [], [], [], [], [], []
    shadows = hard = thick = grads = blur = glow = 0
    fonts, head_fonts = [], []
    body_size, body_lh, h1_size, body_bg, body_fg = None, None, None, None, None

    def add_color(c, w=1):
        if c:
            colors[c] = colors.get(c, 0) + w

    for sel, body in css_rules(css):
        if not _selector_used(sel, used_c, used_t, used_i):
            continue
        sl = sel.lower()
        is_body = bool(re.search(r"(?:^|,)\s*(?:html|body|:root)\s*(?:,|$)", sl))
        is_h1 = bool(re.search(r"(?:^|,|\s)h1\b|\.display-[1-4]|hero[\w-]*\s+h1|\.h1\b", sl))
        is_head = bool(re.search(r"\bh[1-3]\b|heading|title|display", sl))
        is_big = bool(re.search(r"hero|masthead|jumbotron|banner|display|headline|heading|title|\bh1\b|\.h1\b", sl))
        for prop, val in DECL.findall(body):
            prop = prop.lower()
            val = _resolve(re.sub(r"\s*!important\s*$", "", val.strip()), vars_)
            if prop in ("color", "background-color", "background", "border-color", "fill"):
                c = parse_color(val)
                if prop.startswith("background") and "gradient" in val:
                    grads += 1
                    for g in re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)", val):
                        add_color(parse_color(g))
                if c:
                    add_color(c, 2 if prop != "border-color" else 1)
                    if prop.startswith("background"):
                        bgs.append(c)
                        if is_body:
                            body_bg = c
                    elif prop == "color":
                        texts.append(c)
                        if is_body:
                            body_fg = c
            elif prop == "font-size":
                px = _len_px(_clamp_max(val))
                if px and 8 <= px <= 200:
                    sizes.append(px)
                    if is_body:
                        body_size = px
                    if is_h1 or is_big:
                        h1_size = max(h1_size or 0, px)
            elif prop == "line-height" and is_body:
                m = re.match(r"\s*([\d.]+)\s*(px)?", val)
                if m:
                    body_lh = float(m.group(1)) / ((body_size or 16) if m.group(2) else 1)
            elif prop == "font-family":
                first = re.sub(r"[^A-Za-z0-9 \-]", "", val.split(",")[0]).strip()[:40]
                cat = "serif" if re.search(r"\bserif\b", val.lower().replace("sans-serif", "")) or re.search(r"georgia|times|garamond|playfair|merriweather|lora|serif display|songti|宋", val.lower()) else (
                    "mono" if re.search(r"mono|courier|code", val.lower()) else "sans")
                if first:
                    fonts.append((first, cat))
                    if is_head:
                        head_fonts.append((first, cat))
            elif prop.startswith("border") and "radius" in prop:
                px = _len_px(val)
                if px is not None and px < 200:
                    radii.append(px)
            elif prop in ("padding", "padding-top", "padding-bottom", "padding-block") and re.search(r"section|hero|masthead|\bpy|banner|jumbotron|page-section", sl):
                px = _len_px(_clamp_max(val.split()[0]))
                if px and 16 <= px <= 240:
                    pads.append(px)
            elif prop == "max-width" and re.search(r"container|wrapper|inner|content|main", sl):
                px = _len_px(val)
                if px and 700 <= px <= 1800:
                    maxw.append(px)
            elif prop == "box-shadow" and val != "none":
                shadows += 1
                if re.match(r"-?\d+px\s+-?\d+px\s+0(px)?\s", val):
                    hard += 1
                if re.search(r"0\s+0\s+\d{2,}px", val):
                    glow += 1
            elif prop in ("backdrop-filter", "-webkit-backdrop-filter") and "blur" in val:
                blur += 1
            if prop.startswith("border") and "radius" not in prop and re.search(r"\b[3-9]px\s+solid", val):
                thick += 1

    # Tailwind（以及类似的工具类）
    tw_sizes, tw_bg_body = [], None
    for cls, blk in [(c, b) for s in scans for c, b in s.tw]:
        if re.match(r"(?:dark|hover|focus|active|group-hover|peer-\w+|disabled|placeholder|focus-within|focus-visible):", cls):
            continue
        c = re.sub(r"^(?:sm|md|lg|xl|2xl):", "", cls)
        m = re.fullmatch(r"(bg|text|border|from|via|to)-(white|black|[a-z]+)(?:-(\d{2,3}))?(?:/\d+)?", c)
        if m and (m.group(2) in ("white", "black") or m.group(3)):
            col = tw_color(m.group(2), m.group(3) or "")
            if col:
                add_color(col, 1)
                if m.group(1) == "bg":
                    bgs.append(col)
                elif m.group(1) == "text":
                    texts.append(col)
                elif m.group(1) in ("from", "via", "to"):
                    grads += 1 if m.group(1) == "from" else 0
            continue
        m = re.fullmatch(r"text-(xs|sm|base|lg|[2-9]?xl)", c)
        if m:
            tw_sizes.append(TW_TEXT[m.group(1)])
            continue
        m = re.fullmatch(r"rounded(?:-(none|sm|md|lg|xl|2xl|3xl))?", c)
        if m:
            radii.append(TW_ROUND[m.group(1) or ""])
            continue
        m = re.fullmatch(r"(?:py|pt|pb)-(\d{1,2})", c)
        if m and blk is not None and 8 <= int(m.group(1)) <= 48:
            pads.append(int(m.group(1)) * 4)
            continue
        m = re.fullmatch(r"max-w-(7xl|6xl|5xl|4xl|screen-xl|screen-lg|screen-2xl)", c)
        if m:
            maxw.append(TW_MAXW[m.group(1)])
            continue
        if re.fullmatch(r"shadow(?:-(sm|md|lg|xl|2xl|inner))?", c):
            shadows += 1
        elif re.fullmatch(r"backdrop-blur(?:-\w+)?", c):
            blur += 1
        elif re.fullmatch(r"bg-gradient-to-\w+", c):
            grads += 1
        elif re.fullmatch(r"font-serif", c):
            fonts.append(("serif", "serif"))
        elif re.fullmatch(r"border-[4-8]", c):
            thick += 1
    for c in home.body_classes + home.html_classes:
        m = re.fullmatch(r"bg-(white|black|[a-z]+)(?:-(\d{2,3}))?", c)
        if m:
            tw_bg_body = tw_color(m.group(1), m.group(2) or "") or tw_bg_body
        m = re.fullmatch(r"text-(xs|sm|base|lg|xl)", c)
        if m:
            body_size = TW_TEXT[m.group(1)]
    sizes += tw_sizes
    if tw_sizes and not h1_size:
        h1_size = max(tw_sizes)

    # 页面底色和正文色
    bg = body_bg or tw_bg_body
    if not bg and "dark" in " ".join(home.html_classes + home.body_classes):
        bg = "#111827"
    bg_known = bg is not None
    bg = bg or "#FFFFFF"
    fg = body_fg or (max(texts, key=texts.count) if texts else ("#FFFFFF" if lum(bg) < .2 else "#212529"))
    dark = lum(bg) < 0.18
    vivid = sorted((c for c in colors if 0.03 < lum(c) < 0.8 and hls(c)[2] > 0.3 and 0.2 < hls(c)[1] < 0.85),
                   key=lambda c: -colors[c])
    accent = vivid[0] if vivid else None

    # 结构
    seq, raw = [], []
    first_content = True
    for b in home.blocks:
        t = classify(b, first_content)
        if t in ("header",):
            continue
        if t != "footer":
            first_content = False
        if t == "hero" and "hero" in raw:  # 后面再出现的大横幅（内页头图、促销条）不算首屏
            t = "content"
        raw.append(t)
        if t != "footer" and (not seq or seq[-1] != t or t == "content"):
            seq.append(t)
    if seq and "hero" in seq and seq[0] != "hero":  # 首屏前面只是导航条之类的
        i = seq.index("hero")
        seq = seq[i:] if i <= 1 else seq
    hero = next((b for b, t in zip(home.blocks, [classify(b, i == 0) for i, b in enumerate(home.blocks)]) if t == "hero"), None)

    words = " ".join(home.head_text)
    ind, why = (industry, "喂的时候标注") if industry else guess_industry(words + " " + " ".join(source.get("hints", [])))

    head_cat = (head_fonts or fonts or [("", "sans")])[0][1]
    radius = statistics.median(radii) if radii else None
    base = body_size or (statistics.mode([s for s in sizes if 13 <= s <= 20]) if any(13 <= s <= 20 for s in sizes) else 16)
    h1 = h1_size or (max(sizes) if sizes else None)
    if h1 and h1 < base * 1.2:  # 读到的“最大标题”比正文还小，说明没读准，不报
        h1 = None

    # 风格家族：和 feed.parse_html 同一套判断，加上“科技感”（深底 + 渐变/发光/毛玻璃）
    if dark and (grads >= 2 or glow or blur):
        fam = "tech"
    elif dark:
        fam = "dark"
    elif blur and grads >= 1:
        fam = "glass"
    elif (hard >= 1 and hard + thick >= 2) or thick >= 4:
        fam = "block"
    elif head_cat == "serif":
        fam = "editorial"
    elif radius is not None and radius >= 12:
        fam = "soft"
    else:
        fam = "minimal"

    sid = hashlib.sha1(("|".join(sorted(bundle["pages"][:1])) + "|".join(bundle.get("css", [])[:2])).encode("utf-8", "replace")).hexdigest()[:12]
    spec = {
        "id": sid, "source": {k: v for k, v in source.items() if k in ("kind", "repo", "path", "url", "license", "name")},
        "industry": ind, "industry_why": why, "family": fam,
        "color": {"bg": bg, "bg_known": bg_known, "fg": fg, "dark": dark, "accent": accent, "palette": vivid[:5],
                  "n_colors": len(colors), "accent_hue": round(hls(accent)[0] * 360) if accent else None,
                  "accent_sat": round(hls(accent)[2], 2) if accent else None,
                  "text_contrast": round(contrast(bg, fg), 1)},
        "type": {"base": round(base, 1), "h1": round(h1, 1) if h1 else None, "ratio": round(h1 / base, 2) if h1 and base else None,
                 "line_height": round(body_lh, 2) if body_lh and 1 <= body_lh <= 2.4 else None, "heading_cat": head_cat,
                 "fonts": sorted({f for f, _ in fonts if f.lower() not in ("inherit", "initial", "var", "sans-serif", "serif")})[:4],
                 "n_sizes": len({round(s) for s in sizes})},
        "space": {"section_pad": round(statistics.median(pads)) if pads else None,
                  "container": round(statistics.median(maxw)) if maxw else None},
        "shape": {"radius": round(radius, 1) if radius is not None else None, "shadows": shadows, "hard_shadows": hard,
                  "thick_borders": thick, "gradients": grads, "blur": blur, "glow": glow},
        "structure": {"sections": seq[:16], "n_sections": len([t for t in raw if t != "footer"]), "has_footer": "footer" in raw,
                      "nav_links": home.nav_links, "hero_words": hero["words"] if hero else None,
                      "hero_buttons": hero["btn"] if hero else None, "hero_image": bool(hero and hero["img"]),
                      "pages": len(bundle["pages"])},
    }
    return spec


def from_path(path: str, source: dict | None = None, industry: str | None = None) -> dict | None:
    src = dict(source or {"kind": "file", "name": os.path.basename(os.path.abspath(path))})
    return extract(collect(path), src, industry)


if __name__ == "__main__":
    import json
    for p in sys.argv[1:]:
        print(json.dumps(from_path(p), ensure_ascii=False, indent=1))
