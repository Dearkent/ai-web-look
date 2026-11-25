#!/usr/bin/env python3
"""喂网站设计 + 设计先验的测试（全部离线：用手写的小网站当夹具，本机起一个服务器测抓取）。

E60 标本：读颜色/字号/留白/区块；只统计页面用到的 CSS；Tailwind 类名；不运行脚本、不留原文；
    压缩包防 ../；网址抓取拒绝内网、遵守 robots.txt；去重；坏样本不打断整批；按来源撤回。
E61 先验：样本不够不提炼；同行不一致不采纳；指纹没变不重复试跑（防“试 → 拒 → 再试”循环）；
    重排只动中间、首屏第一、行动区块最后、不增不减；AISITE_PRIORS=off 整个关掉；试跑通过才采纳。
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="learn-test-")
os.environ["AISITE_CORPUS"] = os.path.join(TMP, "corpus")
os.environ["AISITE_EVENTS"] = os.path.join(TMP, "events.jsonl")
sys.path.insert(0, HERE)
import corpus  # noqa: E402
import priors  # noqa: E402
import specimen  # noqa: E402

ok = total = 0
which = sys.argv[1] if len(sys.argv) > 1 else "all"


def check(name, cond, detail=""):
    global ok, total
    total += 1
    ok += bool(cond)
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  —— {detail}"))


SECRET = "巷口咖啡的独家秘方文案"
SITE = f"""<!doctype html><html><head><title>Lane Coffee Roasters</title>
<meta name="description" content="Specialty coffee and bakery">
<link rel="stylesheet" href="css/style.css"><link rel="stylesheet" href="https://cdn.example.com/x.css">
<style>.hero h1{{font-size:clamp(40px,6vw,64px)}}</style></head>
<body class="bg-white">
<header class="site-header"><nav><a href="#">Menu</a><a href="#">About</a><a href="#">Visit</a></nav></header>
<section class="hero" id="home"><div class="container"></div><h1>{SECRET}</h1><p>Fresh every morning</p><a class="btn btn-primary">Order</a><img src="a.jpg"></section>
<section id="about"><h2>Our story</h2><p>Since 2010</p></section>
<section id="menu" class="py-24"><h2>Menu</h2><ul><li>Latte $5</li><li>Mocha $6</li></ul></section>
<section class="testimonials"><blockquote>Great</blockquote><blockquote>Nice</blockquote></section>
<section id="contact"><h2>Visit us</h2><form><input type="email"></form></section>
<footer class="footer"><p>© 2026</p></footer>
<script>document.body.innerHTML = "<section id='pricing'>hacked</section>"; fetch("https://evil.example.com");</script>
</body></html>"""
CSS = """:root{--brand:#C2410C;--ink:#1F2937}
body{background:#FFFBF5;color:var(--ink);font-size:16px;line-height:1.6;font-family:"Lora",Georgia,serif}
h1,h2{font-family:"Playfair Display",serif}
.hero{padding:96px 0}
.btn-primary{background:var(--brand);border-radius:12px;color:#fff}
.container{max-width:1140px}
.unused-framework-thing{color:#00FF00;background:#00FF00}
.card-unused .x{color:#123456}
section{padding-top:80px;padding-bottom:80px}
"""


def make_site(root, html=SITE, css=CSS):
    os.makedirs(os.path.join(root, "css"), exist_ok=True)
    open(os.path.join(root, "index.html"), "w", encoding="utf-8").write(html)
    open(os.path.join(root, "css", "style.css"), "w", encoding="utf-8").write(css)
    return root


def e60():
    site = make_site(os.path.join(TMP, "site1"))
    s = specimen.from_path(site, {"kind": "file", "name": "site1"})
    check("读出区块顺序：首屏 > 关于 > 菜单 > 评价 > 联系", s["structure"]["sections"] == ["hero", "content", "menu", "testimonials", "contact-form"], s["structure"]["sections"])
    check("页脚单独记、不进顺序", s["structure"]["has_footer"] and "footer" not in s["structure"]["sections"])
    check("脚本不运行：脚本里塞的“价格区”没出现", "pricing" not in s["structure"]["sections"])
    check("底色、正文色来自 body（含 CSS 变量）", s["color"]["bg"] == "#FFFBF5" and s["color"]["fg"] == "#1F2937", s["color"])
    check("品牌色是用到的橙色，不是没用到的框架绿色", s["color"]["accent"] == "#C2410C" and "#00FF00" not in s["color"]["palette"], s["color"])
    check("字号：正文 16、首屏标题取 clamp 的最大值 64、行高 1.6", (s["type"]["base"], s["type"]["h1"], s["type"]["line_height"]) == (16, 64, 1.6), s["type"])
    check("标题是衬线体 → 杂志风格", s["type"]["heading_cat"] == "serif" and s["family"] == "editorial", (s["type"], s["family"]))
    check("留白和版心宽度", s["space"]["container"] == 1140 and 80 <= s["space"]["section_pad"] <= 96, s["space"])
    check("猜行业：英文词 coffee → 咖啡馆", s["industry"] == "Bakery/Cafe", s["industry"])
    check("首屏有按钮和图；导航 3 个链接", s["structure"]["hero_buttons"] >= 1 and s["structure"]["hero_image"] and s["structure"]["nav_links"] == 3, s["structure"])
    dump = json.dumps(s, ensure_ascii=False)
    check("不留原文：标题、正文、链接都不在结果里", SECRET not in dump and "Since 2010" not in dump and "evil" not in dump and "cdn.example" not in dump)
    tw = os.path.join(TMP, "tw")
    os.makedirs(tw)
    open(os.path.join(tw, "index.html"), "w").write("""<html class="dark"><body class="bg-gray-900 text-base">
      <section class="hero py-32"><h1 class="text-6xl font-bold">Ship</h1><a class="btn">Start</a></section>
      <section id="features" class="py-20"><div class="rounded-2xl shadow-lg bg-indigo-600 backdrop-blur-md bg-gradient-to-r from-indigo-500 to-pink-500"></div></section>
      <section id="pricing"><p>$9/mo</p><p>$29/mo</p></section><section id="faq"></section></body></html>""")
    t = specimen.from_path(tw, {"kind": "file", "name": "tw"})
    check("Tailwind：text-6xl → 60px、rounded-2xl → 16、py-32 → 128", t["type"]["h1"] == 60 and t["shape"]["radius"] == 16 and t["space"]["section_pad"] in (80, 104, 128), (t["type"], t["shape"], t["space"]))
    check("Tailwind：深色底 + 渐变 + 毛玻璃 → 科技感", t["color"]["dark"] and t["family"] == "tech", (t["color"]["bg"], t["family"]))
    check("Tailwind 区块：首屏 > 功能 > 价格 > 问答", t["structure"]["sections"] == ["hero", "features", "pricing", "faq"], t["structure"]["sections"])
    bad = os.path.join(TMP, "bad.zip")
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../../escape.html", "<html><section class='hero'><h1>x</h1></section></html>")
        z.writestr("ok/index.html", SITE)
        z.writestr("ok/run.sh", "rm -rf /")
    r = corpus.feed_one(bad)
    check("压缩包：../ 不解出来，脚本文件不解；正常页面照样读", r["ok"] and not os.path.exists(os.path.join(TMP, "..", "escape.html")), r.get("why"))
    r1 = corpus.feed_one(site)
    r2 = corpus.feed_one(site)
    check("去重：同一个网站再喂一次不收", r1["ok"] and not r2["ok"] and ("重复" in r2["why"] or "喂过" in r2["why"]), r2.get("why"))
    r3 = corpus.feed_one("http://127.0.0.1:9/x")
    check("网址：拒绝本机/内网地址", not r3["ok"] and "内网" in r3["why"], r3.get("why"))
    r4 = corpus.feed_one("ftp://example.com/x")
    check("认不出的东西：跳过并说明，不崩", not r4["ok"], r4)
    # 本机服务器：抓取 + robots.txt（测试里放开内网限制）
    web = make_site(os.path.join(TMP, "web"), SITE.replace("Lane Coffee", "Hill Coffee").replace("css/style.css", "/css/style.css"))
    open(os.path.join(web, "robots.txt"), "w").write("User-agent: *\nDisallow: /private/\n")
    os.makedirs(os.path.join(web, "private"))
    shutil.copy(os.path.join(web, "index.html"), os.path.join(web, "private", "index.html"))
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=web, **k)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    d = tempfile.mkdtemp()
    p = corpus.fetch_url(base + "/", d, allow_private=True, pause=0)
    s2 = specimen.from_path(p, {"kind": "url", "url": base})
    check("网址：取到网页和同站 CSS，读出同样的品牌色", s2 and s2["color"]["accent"] == "#C2410C", s2 and s2["color"])
    try:
        corpus.fetch_url(base + "/private/", tempfile.mkdtemp(), allow_private=True, pause=0)
        check("网址：robots.txt 不允许的页面不抓", False, "抓了")
    except ValueError as e:
        check("网址：robots.txt 不允许的页面不抓", "robots" in str(e), e)
    srv.shutdown()
    import specimen as sp
    orig = sp.extract
    sp.extract = lambda *a, **k: (_ for _ in ()).throw(KeyError("boom"))
    other = make_site(os.path.join(TMP, "site-x"), SITE.replace("Lane", "Other"))
    r5 = corpus.feed_one(other)
    sp.extract = orig
    check("读取代码出错：这一个跳过并记进待修，不打断整批", not r5["ok"] and "待修" in r5["why"] and os.path.exists(os.path.join(corpus.CORPUS, "errors.jsonl")), r5)
    n = len(corpus.load())
    check("按来源撤回", corpus.remove("site1") == 1 and len(corpus.load()) == n - 1)
    evs = [json.loads(x) for x in open(os.environ["AISITE_EVENTS"], encoding="utf-8")]
    check("每次喂都记实况事件（收下 / 跳过）", any(e["kind"] == "feed.specimen" for e in evs) and any(e["kind"] == "feed.skip" for e in evs))


def fake(i, ind, seq, fam="minimal"):
    return {"id": f"f{ind[:3]}{i:03d}", "source": {"kind": "file", "name": f"{ind}-{i}"}, "industry": ind, "industry_why": "t", "family": fam,
            "color": {"dark": False}, "type": {"base": 16, "h1": 48 + i, "ratio": 3, "line_height": 1.6, "heading_cat": "sans"},
            "space": {"section_pad": 64, "container": 1140}, "shape": {"radius": 8},
            "structure": {"sections": seq, "hero_words": 12, "hero_buttons": 1, "hero_image": True, "nav_links": 5}}


def e61():
    shutil.rmtree(corpus.CORPUS, ignore_errors=True)
    os.makedirs(corpus.CORPUS)
    rows = [fake(i, "Bakery/Cafe", ["hero", "menu", "features", "testimonials", "contact-form"]) for i in range(6)]
    rows += [fake(i, "Legal Services", ["hero", "features"]) for i in range(3)]
    mixed = [["hero", "features", "testimonials", "faq"], ["hero", "faq", "testimonials", "features"], ["hero", "testimonials", "faq", "features"],
             ["hero", "faq", "features", "testimonials"], ["hero", "testimonials", "features", "faq"], ["hero", "features", "faq", "testimonials"]]
    rows += [fake(i, "SaaS (General)", q) for i, q in enumerate(mixed)]
    with open(corpus.path(), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    d = priors.build()
    cafe, law, saas = (d["industries"][k] for k in ("Bakery/Cafe", "Legal Services", "SaaS (General)"))
    check("样本不够（3 个）不提炼", law["status"] == "样本不够", law["status"])
    check("同行顺序不一致 → 不采纳，写明一致度", saas["status"] == "不采纳" and saas["agreement"] < priors.MIN_AGREE, (saas["status"], saas["agreement"]))
    check("一致的行业进“候选”，顺序：菜单 > 功能 > 评价 > 联系", cafe["status"] == "候选" and cafe["order"] == ["catalog", "features", "testimonials", "contact"], (cafe["status"], cafe["order"]))
    check("离群值不带歪中位数", cafe["type"]["h1"] in (50.5, 51, 50, 51.5), cafe["type"])
    secs = [{"id": i, "type": t} for i, t in (("hero", "hero"), ("value-props", "value-props"), ("faq", "faq"), ("catalog-teaser", "menu"), ("cta", "cta"))]
    same, note = priors.reorder("Bakery/Cafe", secs)
    check("候选还没试跑：生成器不用", same == secs and note == "")
    new, note = priors.reorder("Bakery/Cafe", secs, allow_candidate=True)
    ids = [s["id"] for s in new]
    check("重排：首屏第一、行动区块最后、菜单提前，区块不增不减", ids[0] == "hero" and ids[-1] == "cta" and ids.index("catalog-teaser") < ids.index("value-props")
          and sorted(ids) == sorted(s["id"] for s in secs) and "同行" in note, ids)
    os.environ["AISITE_PRIORS"] = "off"
    off, note2 = priors.reorder("Bakery/Cafe", secs, allow_candidate=True)
    os.environ["AISITE_PRIORS"] = "on"
    check("AISITE_PRIORS=off 整个关掉", off == secs and note2 == "")
    sys.path.insert(0, os.path.join(HERE, "..", "text2site"))
    done = priors.trial(run_browser=False)
    d2 = priors.load()
    check("试跑：真的生成网站、图纸 0 错误才采纳", done.get("Bakery/Cafe") == "采纳" and d2["industries"]["Bakery/Cafe"]["trial"]["candidate"]["errors"] == 0, (done, d2["industries"]["Bakery/Cafe"].get("trial")))
    check("采纳后生成器用上了（试跑记录里有重排说明）", "同行" in d2["industries"]["Bakery/Cafe"]["trial"]["candidate"]["note"], d2["industries"]["Bakery/Cafe"]["trial"])
    priors.build()
    again = priors.trial(run_browser=False)
    check("没有新数据：指纹没变，结论保留、不重复试跑", again == {} and priors.load()["industries"]["Bakery/Cafe"]["status"] == "采纳", again)
    with open(corpus.path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(fake(9, "Bakery/Cafe", ["hero", "features", "menu", "contact-form"])) + "\n")
    d3 = priors.build()
    check("喂了新网站、指纹变了：回到候选，等下次试跑", d3["industries"]["Bakery/Cafe"]["status"] == "候选", d3["industries"]["Bakery/Cafe"]["status"])
    import plan as P
    from understand import understand
    import styles
    b = understand("帮我做个咖啡馆网站，放菜单")
    priors.trial(run_browser=False)
    r = P.plan(b, styles.options(b)[0]["id"])
    check("建站时：采纳的先验写进说明", "同行" in r["notes"].get("design_prior", ""), r["notes"])
    open(priors._path(), "w").write("{坏掉的文件")
    r2 = P.plan(b, styles.options(b)[0]["id"])
    check("先验文件坏了：照原顺序建站，不失败", "design_prior" not in r2["notes"] and r2["files"], r2["notes"])


if which in ("all", "E60"):
    e60()
if which in ("all", "E61"):
    e61()
shutil.rmtree(TMP, ignore_errors=True)
print(f"喂设计与设计先验（{which}）：{ok}/{total} 通过")
sys.exit(0 if ok == total else 1)
