"""从 30 个开源参考里学来、在生成器里重新实现的界面手法（evals/facts/ui_refs.tsv）：
跳到正文、醒目的键盘焦点、手机菜单（没脚本也能用）、原生折叠的常见问题、分栏页脚、步骤编号；以及常见问题不再泄露建站时的内部问题（D31）。

    python3 -I ui_patterns_test.py
"""
from __future__ import annotations

import functools
import http.server
import os
import re
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "text2site")):
    sys.path.insert(0, p)
import browser_check  # noqa: E402
import make_site  # noqa: E402
import styles  # noqa: E402
import understand  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    (ok if cond else bad).append(name)
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  ← {str(detail)[:300]}"))


out = tempfile.mkdtemp(prefix="uip-")
big = understand.understand("巷口咖啡，社区里的小咖啡馆，想让附近的人来店里坐坐，可以在线订座，展示菜单和店里的环境，还要常见问题和到店地图")
small = understand.understand("帮律所做个官网")
sid = styles.options(big)[1]["id"]
r = make_site.build_one(big, sid, os.path.join(out, "big"), run_browser=False)
r2 = make_site.build_one(small, styles.options(small)[0]["id"], os.path.join(out, "small"), run_browser=False)
home = open(os.path.join(r["site"], "index.html"), encoding="utf-8").read()
home2 = open(os.path.join(r2["site"], "index.html"), encoding="utf-8").read()
css = open(os.path.join(r["site"], "styles.css"), encoding="utf-8").read()
body = home.split("<body", 1)[1].split(">", 1)[1]

expect("跳到正文：每页第一个可聚焦的是“跳到正文”，指向 main#main", body.startswith('<a class="skip" href="#main">跳到正文</a>')
       and '<main id="main" tabindex="-1">' in home)
expect("键盘焦点：有醒目的 :focus-visible 样式", ":focus-visible{outline:3px solid" in css)
faq = re.search(r'<section id="faq"[^>]*>.*?</section>', home, re.S)
expect("常见问题：用原生 <details>/<summary> 折叠，有区块标题", faq and faq.group(0).count('<details class="qa">') >= 3
       and "<summary>" in faq.group(0) and "<h2" in faq.group(0), faq.group(0)[:300] if faq else "没有 faq 区块")
inner_q = [q["question"] for q in big.get("open_questions", [])]
expect("常见问题：不再把建站时问你的问题（和“默认：”）放到网站上（D31）",
       faq and "默认：" not in faq.group(0) and not any(q in faq.group(0) for q in inner_q) and "要提前多久预约" in faq.group(0), inner_q)
expect("页脚：品牌名 + 一句介绍 + 导航 + 版权年份", re.search(r'<footer class="site"><div class="about"><strong>[^<]+</strong><p', home)
       and re.search(r'<p class="copy">© 20\d\d ', home))
expect("步骤：有序的步骤区块用 CSS 计数器自动编号（只给真正有先后的内容编号）", ".t-steps .card::before{counter-increment:step" in css)
expect("手机菜单：导航超过 4 项才收进“菜单”按钮（律所 4 项以内不收）",
       'class="menu-btn"' in home and "data-menu" in home and 'class="menu-btn"' not in home2, (home2.count("<nav"),))

ready, why = browser_check.ready()
if ready:
    from playwright.sync_api import sync_playwright
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(browser_check._Quiet, directory=r["site"]))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=browser_check.CHROME, headless=True, args=["--no-sandbox"])
            pg = b.new_page(viewport={"width": 375, "height": 800})
            pg.goto(base)
            vis = lambda sel: pg.locator(sel).first.is_visible()
            closed = (not vis("#site-nav")) and vis(".menu-btn")
            pg.click(".menu-btn")
            opened = vis("#site-nav") and pg.get_attribute(".menu-btn", "aria-expanded") == "true"
            pg.keyboard.press("Escape")
            esc = (not vis("#site-nav")) and pg.evaluate("document.activeElement.className") == "menu-btn" \
                and pg.get_attribute(".menu-btn", "aria-expanded") == "false"
            expect("手机菜单：手机上先收起，点“菜单”展开（aria-expanded 跟着变），按 Esc 收起、焦点回到按钮", closed and opened and esc,
                   (closed, opened, esc))
            pg.goto(base)
            pg.keyboard.press("Tab")
            first = pg.evaluate("document.activeElement.textContent")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(100)
            expect("跳到正文：按 Tab 第一个就是它，回车后焦点到正文", first == "跳到正文" and pg.evaluate("document.activeElement.id") == "main",
                   (first, pg.evaluate("document.activeElement.id")))
            pg.locator("#faq summary").first.focus()
            pg.keyboard.press("Enter")
            expect("常见问题：键盘回车就能展开", pg.evaluate("document.querySelector('#faq details').open"))
            desk = b.new_page(viewport={"width": 1280, "height": 800})
            desk.goto(base)
            expect("手机菜单：电脑宽度下导航直接显示，不出现“菜单”按钮", desk.locator("#site-nav").is_visible() and not desk.locator(".menu-btn").is_visible())
            ctx = b.new_context(java_script_enabled=False, viewport={"width": 375, "height": 800})
            nojs = ctx.new_page()
            nojs.goto(base)
            expect("手机菜单：浏览器不运行脚本时导航照常全部显示（不会被藏起来点不到）",
                   nojs.locator("#site-nav").is_visible() and not nojs.locator(".menu-btn").is_visible())
            b.close()
    finally:
        srv.shutdown()
        srv.server_close()
    probs = browser_check.check(r["site"])
    expect("浏览器检查：用了这些手法的网站 0 问题（点按区域、对比度、溢出都过）", not probs, probs[:3])
else:
    print("跳过浏览器部分：" + why)

print(f"\n界面手法：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
