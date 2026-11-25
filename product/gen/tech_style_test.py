"""科技感风格（第十四轮，用户 11-25：“前端不够科技感，粉色简洁但不够高端”）。

    python3 -I tech_style_test.py
"""
from __future__ import annotations

import colorsys
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "text2site")):
    sys.path.insert(0, p)
import browser_check  # noqa: E402
import edit  # noqa: E402
import make_site  # noqa: E402
import styles  # noqa: E402
import understand  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    (ok if cond else bad).append(name)
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  ← {str(detail)[:300]}"))


texts = {"咖啡馆": "巷口咖啡，社区里的小咖啡馆，想让附近的人来店里坐坐，可以在线订座，展示菜单和店里的环境",
         "AI 产品": "做一个AI写作助手的产品官网，要定价和注册",
         "律所": "帮律所做个官网，让客户在线咨询",
         "花店": "小花店，想卖花束，可以在线下单",
         "牙科": "牙科诊所，想让病人在线预约"}
briefs = {k: understand.understand(v) for k, v in texts.items()}
opts = {k: styles.options(b) for k, b in briefs.items()}
expect("选项：每个行业的三个风格里都有一个“科技感”，并说明为什么",
       all(sum(o["family"] == "科技感" for o in v) == 1 and len(v) == 3 for v in opts.values())
       and all(next(o for o in v if o["family"] == "科技感")["why"] for v in opts.values()),
       {k: [o["family"] for o in v] for k, v in opts.items()})
expect("选项：三个风格的观感仍然各不相同", all(len({o["family"] for o in v}) == 3 for v in opts.values()))
no_dark = understand.understand("小花店的网站，不要暗黑风格")
nd = styles.options(no_dark)
expect("选项：说了“不要暗黑”就不硬塞科技感（它也是深色底）", all(o["family"] not in ("科技感", "深色") for o in nd) and len(nd) == 3,
       [o["family"] for o in nd])

pal = {k: styles.palette(b["product_type"]["value"], False, "tech") for k, b in briefs.items()}
expect("配色：深墨底，正文、次要文字、主色、链接在深底上都够清楚（4.5:1）",
       all(styles._lum(p["background"]) < 0.02 and styles.contrast(p["foreground"], p["background"]) >= 7
           and styles.contrast(p["muted"], p["background"]) >= 4.5 and styles.contrast(p["primary"], p["background"]) >= 4.5
           and styles.contrast(p["link"], p["background"]) >= 4.5 and styles.contrast(p["on-primary"], p["primary"]) >= 4.5 for p in pal.values()),
       {k: (p["background"], p["primary"], p["link"]) for k, p in pal.items()})
expect("配色：底色带一点行业主色的色调（不同行业的深底不完全一样）", len({p["background"] for p in pal.values()}) >= 4)


def sat(h):
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[2]


soft = styles.palette("Bakery/Cafe", False, "soft", styles.style_hexes("soft-ui-evolution"))
expect("柔和风格：底色和色带不再是整页粉色（饱和度压低，接近暖白）",
       styles._lum(soft["background"]) > 0.85 and sat(soft["background"]) < 0.35 and sat(soft["band"]) < 0.3,
       (soft["background"], soft["band"], round(sat(soft["background"]), 2), round(sat(soft["band"]), 2)))

b = briefs["咖啡馆"]
_, st, done, refused, _ = edit.apply(b, "soft-ui-evolution", edit.parse("换成科技感的")[0], {})
_, st2, done2, _, _ = edit.apply(b, "soft-ui-evolution", edit.parse("来点未来感，科技风一点")[0], {})
_, st3, _, _, _ = edit.apply(b, "soft-ui-evolution", edit.parse("高级一点")[0], {})
expect("对话修改：“换成科技感的”“科技风一点”都换到科技感风格（“高级”仍是极简黑白）", st == styles.TECH_STYLE and st2 == styles.TECH_STYLE
       and st3 == "minimalist-monochrome", (st, st2, done, refused, done2))

out = tempfile.mkdtemp(prefix="tech-")
probs_all = {}
for k in ("咖啡馆", "AI 产品", "牙科"):
    r = make_site.build_one(briefs[k], styles.TECH_STYLE, os.path.join(out, k), run_browser=browser_check.ready()[0])
    probs_all[k] = r["blueprint_errors"] + r["browser_problems"]
    if k == "AI 产品":
        html = open(os.path.join(r["site"], "index.html"), encoding="utf-8").read()
        css = open(os.path.join(r["site"], "styles.css"), encoding="utf-8").read()
        tok = json.load(open(os.path.join(r["project"], "design", "tokens.json"), encoding="utf-8"))
        arts = [f for f in os.listdir(os.path.join(r["site"], "assets", "art"))]
        svg = open(os.path.join(r["site"], "assets", "art", arts[0]), encoding="utf-8").read()
expect("生成：科技感网站用 fam-tech 外观（首屏网格+光束、细线卡片、半透明吸顶导航）",
       'class="fam-tech"' in html and ".fam-tech .t-hero::before" in css and ".fam-tech .t-hero::after" in css
       and "backdrop-filter:blur(14px)" in css and tok["$extensions"]["aisite"]["family"] == "tech")
expect("生成：插图也换成科技感画法（深底、网格、渐变发光线条），仍然只有图形", "mask" in svg and "url(#s)" in svg
       and not re.search(r"<script|href|<text", svg))
if browser_check.ready()[0]:
    expect("浏览器检查：咖啡馆、AI 产品、牙科三个行业用科技感都是 0 问题（对比度、点按区域、溢出）",
           not any(probs_all.values()), probs_all)
print(f"\n科技感风格：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
