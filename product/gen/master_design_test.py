"""第十五轮“大师审稿”：少，但更好（Rams）；一个页面只有一个主要动作（乔布斯）；字号阶梯、网格和留白（Vignelli）。

    python3 -I master_design_test.py
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import re
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "text2site"), os.path.join(HERE, "..", "app")):
    sys.path.insert(0, p)
import browser_check  # noqa: E402
import make_site  # noqa: E402
import styles  # noqa: E402
import understand  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    (ok if cond else bad).append(name)
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  ← {str(detail)[:300]}"))


out = tempfile.mkdtemp(prefix="master-")
cases = {"cafe": "社区里的小咖啡馆，想让附近的人来店里坐坐，可以在线订座，展示菜单和店里的环境，还要常见问题",
         "named": "巷口咖啡，社区里的小咖啡馆，可以在线订座，展示菜单",
         "law": "帮律所做个官网，让客户在线咨询",
         "ai": "做一个AI写作助手的产品官网，要定价和注册"}
sites = {}
run_b = browser_check.ready()[0]
for k, t in cases.items():
    b = understand.understand(t)
    if k == "named":
        qid = next(q["id"] for q in b["open_questions"] if "叫什么名字" in q["question"])
        b = understand.apply_answers(t, b, {qid: "巷口咖啡"})
    sid = {"cafe": "soft-ui-evolution", "named": "soft-ui-evolution", "law": "accessible-and-ethical", "ai": styles.TECH_STYLE}[k]
    r = make_site.build_one(b, sid, os.path.join(out, k), run_browser=run_b)
    home = open(os.path.join(r["site"], "index.html"), encoding="utf-8").read()
    sites[k] = (b, r, home)

heads = {k: re.search(r'<section id="hero"[^>]*>.*?</section>', h, re.S).group(0) for k, (_, _, h) in sites.items()}
h1s = {k: re.sub(r"<[^>]+>", "", re.search(r"<h[12][^>]*>(.*?)</h[12]>", v, re.S).group(1)) for k, v in heads.items()}
subs = {k: re.sub(r"<[^>]+>", "", re.search(r"<p[^>]*>(.*?)</p>", v, re.S).group(1)) for k, v in heads.items()}
expect("首屏标题只说一个承诺：不再是“名字：口号”，也不出现“我的网站”",
       all("：" not in h and "我的网站" not in h and 4 <= len(h) <= 18 for h in h1s.values()), h1s)
expect("首屏副标题一句话说好处：不再把功能名用顿号堆成一串，不超过 20 个字",
       all("、" not in s and len(s) <= 20 and s.endswith("。") for s in subs.values()), subs)
primaries = {k: len(re.findall(r'class="btn primary"', v)) for k, v in heads.items()}
expect("首屏只有一个主要按钮（第二个动作是文字链接样式）", all(n == 1 for n in primaries.values()), primaries)
css = open(os.path.join(sites["cafe"][1]["site"], "styles.css"), encoding="utf-8").read()
expect("首屏第二个动作降为文字链接（CSS 规则存在）", ".t-hero .btn:not(.primary){border-color:transparent;background:none;text-decoration:underline" in css)

all_heads = {k: re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", h) for k, (_, _, h) in sites.items()}
expect("没给名字时，页面上的标题都不出现占位名“我的网站”（页头品牌和页脚除外）",
       all("我的网站" not in "".join(v) for k, v in all_heads.items() if k != "named"), {k: v[:4] for k, v in all_heads.items()})
expect("给了名字时，理由区块用真名（为什么选巷口咖啡）", any("为什么选巷口咖啡" in x for x in all_heads["named"]), all_heads["named"])

cafe_home = sites["cafe"][2]
menu = re.search(r'<section id="[^"]*" class="t-menu.*?</section>', cafe_home, re.S)
expect("菜单：不再每行挂“价格待填”，也没有空段落", menu and "价格待填" not in menu.group(0) and "<p class=\"muted\"></p>" not in menu.group(0))

for k in ("law", "ai"):
    b, r, home = sites[k]
    hid = json.load(open(os.path.join(r["project"], "hidden.json"), encoding="utf-8"))
    sites[k] = (b, r, home, hid)
law_hid, ai_hid = sites["law"][3], sites["ai"][3]
expect("没有真实内容的区块（数字、对比、介绍）先不上页面，记进待补清单",
       {h["label"] for h in law_hid} >= {"数字", "介绍"} and {h["label"] for h in ai_hid} >= {"对比", "介绍"}
       and "（待填：真实数据）" not in sites["law"][2] and "（待填：对比内容）" not in sites["ai"][2], (law_hid, ai_hid))
import server  # noqa: E402
aud = server.App._audit(sites["law"][1])
item = next((x for x in aud["items"] if "先不显示" in x["msg"]), None)
expect("体检：提醒“有 N 个区块先不显示，等你的真实内容”，列为上线前再做", item and item["pending"] and "数字" in item["msg"], item)

blurb = re.search(r'<footer class="site"><div class="about"><strong>[^<]*</strong><p class="muted">([^<]*)</p>', cafe_home)
expect("页脚一句话用首屏副标题（不再是“注册或报名。欢迎了解。”这种内部目标名）", blurb and blurb.group(1) == subs["cafe"], blurb and blurb.group(1))
expect("字号阶梯和留白：正文 17px、行高 1.7；二级标题、首屏标题、区块留白都用流式尺寸",
       "body{font-size:17px;line-height:1.7}" in css and "section h2{font-size:clamp(26px,3.2vw,36px)" in css
       and ".t-hero h1,.t-hero h2{font-size:clamp(36px,5.6vw,64px)" in css and "section{padding:clamp(56px,8vw,104px) 20px}" in css)

if run_b:
    from playwright.sync_api import sync_playwright
    r_block = make_site.build_one(sites["cafe"][0], "vibrant-and-block-based", os.path.join(out, "block"), run_browser=False)
    res = {}
    for key, root in (("soft", sites["cafe"][1]["site"]), ("block", r_block["site"])):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(browser_check._Quiet, directory=root))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(executable_path=browser_check.CHROME, headless=True, args=["--no-sandbox"])
                pg = b.new_page(viewport={"width": 1280, "height": 900})
                pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                res[key] = pg.evaluate("""() => { const c = document.querySelector('.t-value-props .card, .t-features .card');
                  const m = document.querySelector('.t-menu .card'); const s = c && getComputedStyle(c); const ms = m && getComputedStyle(m);
                  return {bg: s && s.backgroundColor, top: s && s.borderTopWidth, left: s && s.borderLeftWidth,
                          menuFlex: ms && ms.display, menuBottom: ms && ms.borderBottomWidth}; }""")
                b.close()
        finally:
            srv.shutdown()
            srv.server_close()
    s_, k_ = res["soft"], res["block"]
    expect("特色/理由去掉盒子：只留一道 2px 主色细线和留白（大色块风格保留它的粗框，这是它的性格）",
           s_["bg"] in ("rgba(0, 0, 0, 0)", "transparent") and s_["top"] == "2px" and s_["left"] == "0px" and k_["left"] == "3px", res)
    expect("菜单是价目单排版：名字和价格一行，细线分隔", s_["menuFlex"] == "flex" and s_["menuBottom"] == "1px", s_)
    probs = {k: v[1]["browser_problems"] for k, v in sites.items()}
    expect("浏览器检查：四个网站 0 问题（对比度、点按区域、溢出、图片）", not any(probs.values()), probs)
else:
    print("跳过浏览器部分：" + browser_check.ready()[1])

print(f"\n大师审稿：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
