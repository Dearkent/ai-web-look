#!/usr/bin/env python3
"""一句话 → 网站。风格可选：先给 3 种风格的并排预览，选定后生成整站。

用法：
  python3 -I make_site.py "帮我做个咖啡馆网站……" --out 目录 --preview        # 3 种风格各生成一份，输出对比页 preview.html
  python3 -I make_site.py "帮我做个咖啡馆网站……" --out 目录 --style soft-ui-evolution   # 用选定风格生成整站
每份产物都过两道检查：图纸检查器（必须 0 错误）和真实浏览器检查（报告问题数）。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "gen")):
    sys.path.insert(0, p)
import browser_check  # noqa: E402
import check_blueprints  # noqa: E402
import generate  # noqa: E402
import styles  # noqa: E402
from plan import plan, write_project  # noqa: E402
from understand import understand  # noqa: E402

GOAL_ZH = {"booking": "预约", "sell": "购买", "leads": "获客咨询", "signup": "报名注册", "showcase": "展示", "inform": "介绍信息",
           "community": "招募成员", "recruit": "招聘", "download": "下载"}
FEAT_ZH = {"booking": "预约表单", "contact_form": "联系表单", "map": "地图与到店", "gallery": "作品集", "catalog": "商品或菜单列表",
           "cart": "购物车", "payment": "在线支付", "multilingual": "多语言", "blog": "动态文章", "faq": "常见问题",
           "newsletter": "邮件订阅", "membership": "会员", "search": "搜索"}


def build_one(brief, style_id, out, run_browser=True, fixes=(), detail=None, copy_overlay=None, tweaks=None):
    """fixes：自我纠错选用的修补名（generate.FIX_CSS 里的）；detail：传空字典进来拿浏览器诊断。"""
    import copy
    b = copy.deepcopy(brief)
    res = plan(b, style_id)
    if copy_overlay:  # 模型改写过、校验通过的文案（llm_copy），按区块类型套上
        from llm_copy import apply_overlay
        res["files"] = apply_overlay(res["files"], copy_overlay)
    proj, site = os.path.join(out, "project"), os.path.join(out, "site")
    write_project(res, proj)
    if fixes:
        json.dump(list(fixes), open(os.path.join(proj, "fixes.json"), "w", encoding="utf-8"), ensure_ascii=False)
    if tweaks:
        json.dump(dict(tweaks), open(os.path.join(proj, "tweaks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    skipped = ""
    ok, why = browser_check.ready() if run_browser else (True, "")
    if not ok:  # 本机缺 Chrome 或 Playwright：照样生成，但说清楚没做浏览器检查
        run_browser, skipped = False, "跳过了浏览器检查：" + why
    rep = check_blueprints.check(proj)
    errors = [f"{i['code']} {i['where']} {i['msg']}" for i in rep.errors]
    pages = generate.generate(proj, site) if not errors else []
    browser = browser_check.check(site, detail) if pages and run_browser else []
    return {"style": style_id, "project": proj, "site": site, "pages": pages, "blueprint_errors": errors,
            "blueprint_warnings": [f"{i['code']} {i['msg']}" for i in rep.items if i["level"] != "错误"],
            "browser_problems": browser, "notes": dict(res["notes"], **({"browser_skipped": skipped} if skipped else {}))}


def _inline_home(site_dir):
    """把首页做成可以放进 iframe srcdoc 的独立 HTML：内联样式，去掉外部脚本。"""
    h = open(os.path.join(site_dir, "index.html"), encoding="utf-8").read()
    css = open(os.path.join(site_dir, "styles.css"), encoding="utf-8").read()
    h = h.replace('<link rel="stylesheet" href="styles.css">', f"<style>{css}</style>")
    h = re.sub(r'<script src="[^"]*" defer></script>', "", h)
    h = re.sub(r'href="(?!#)[^"]*"', 'href="#"', h)  # 预览里不跳转
    h = re.sub(r'action="[^"]*"', 'action="#"', h)
    return h


def summary(brief):
    """给用户看的“我读懂的是这样”：用大白话，不露内部代号（行业英文名放括号里备查）。"""
    import lexicon as L
    pt, conf = brief["product_type"]["value"], brief["product_type"]["confidence"]
    words = "、".join((L.PRODUCT.get(pt) or [])[:2]) or pt
    sure = {"high": "", "medium": "（大概是，不对可以在下面说）", "low": "（不太确定，请在下面告诉我做什么）"}[conf]
    goals = [GOAL_ZH[g["kind"]] for g in brief["goals"]]
    aim = ("最想让访客" + goals[0] + ("，其次" + "、".join(goals[1:]) if goals[1:] else "")) if goals else "介绍信息"
    if all(g.get("source") == "default" for g in brief["goals"]):
        aim += "（按行业常见做法）"
    return {"行业": f"{words}（{pt}）{sure}", "名字": brief.get("site_name"), "目标": aim,
            "要有的页面和功能": "、".join(FEAT_ZH.get(f["kind"], f["kind"]) for f in brief["features"]),
            "给谁看": brief["audience"]["primary"]}


def preview_page(text, brief, results, opts):
    s = summary(brief)
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in s.items())
    qs = "".join(f"<li>{html.escape(q['question'])}<span class='muted'>　不回答就：{html.escape(q['default_if_unanswered'])}</span></li>"
                 for q in brief["open_questions"]) or "<li class='muted'>没有需要问的</li>"
    cards = []
    for o, r in zip(opts, results):
        p = styles.profile(o["id"])
        fp = styles.font_pair(o["id"])
        ok = not r["blueprint_errors"]
        status = (f"图纸检查通过 · 浏览器检查 {len(r['browser_problems'])} 个问题" if ok else "图纸检查未通过")
        doc = html.escape(_inline_home(r["site"]), quote=True) if ok else ""
        cards.append(
            f"<article class='opt' id='opt-{html.escape(o['id'])}'><header><h3>{html.escape(o['name'])}</h3>"
            f"<p class='why'>{html.escape(o['why'])}</p>"
            f"<p class='spec'>圆角 {p['radius']}px · 边框 {p['border']}px · 阴影 {p['shadow']} · {'毛玻璃 · ' if p['glass'] else ''}"
            f"{'深色' if p['dark'] else '浅色'} · 字体 {html.escape(fp['name'])}</p>"
            f"<p class='spec ok'>{html.escape(status)}</p></header>"
            f"<div class='frame'><iframe title='{html.escape(o['name'])} 首页预览' srcdoc=\"{doc}\" loading='lazy'></iframe></div>"
            f"<p class='pick'>选这个：<code>--style {html.escape(o['id'])}</code></p></article>")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>风格预览 · {html.escape(brief.get('site_name', ''))}</title><style>
body{{margin:0;font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#1d1d1f;background:#f5f5f2}}
main{{max-width:1400px;margin:0 auto;padding:28px 20px 60px}} h1{{font-size:26px;margin:0 0 6px}} .muted{{color:#6b6b6b}}
.ask{{background:#fff;border:1px solid #e3e3de;border-radius:12px;padding:16px 18px;margin:18px 0}} .ask blockquote{{margin:0 0 12px;font-size:17px}}
.ask table{{border-collapse:collapse}} .ask th{{text-align:left;padding:3px 14px 3px 0;color:#6b6b6b;font-weight:500;white-space:nowrap;vertical-align:top}}
.ask td{{padding:3px 0}} .ask ul{{margin:6px 0 0 18px;padding:0}}
.bar{{display:flex;gap:8px;align-items:center;margin:18px 0 10px}} .bar button{{border:1px solid #cfcfc8;background:#fff;border-radius:999px;padding:6px 14px;cursor:pointer;font:inherit}}
.bar button[aria-pressed=true]{{background:#1d1d1f;color:#fff;border-color:#1d1d1f}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
.opt{{background:#fff;border:1px solid #e3e3de;border-radius:12px;overflow:hidden;display:flex;flex-direction:column}}
.opt header{{padding:14px 16px 8px}} .opt h3{{margin:0 0 4px;font-size:18px}} .why{{margin:0 0 6px}} .spec{{margin:0;font-size:12.5px;color:#6b6b6b}} .spec.ok{{color:#2f6f3e}}
.frame{{position:relative;height:620px;overflow:hidden;border-top:1px solid #eee;background:#fff}}
.frame iframe{{border:0;transform-origin:0 0;position:absolute;top:0;left:0;height:1800px}}
.pick{{margin:0;padding:10px 16px;font-size:13px;border-top:1px solid #eee}} code{{background:#f1f1ec;padding:2px 6px;border-radius:6px}}
</style></head><body><main>
<h1>同一份需求，三种风格</h1><p class="muted">由一句话自动生成。三个预览用的是同一套页面结构，只换了风格，方便对比。</p>
<section class="ask"><blockquote>“{html.escape(text)}”</blockquote><table>{rows}</table>
<p style="margin:12px 0 0"><b>还想确认的问题</b>（不回答也能生成，会用括号里的默认做法）：</p><ul>{qs}</ul></section>
<div class="bar" role="group" aria-label="预览宽度"><span class="muted">预览宽度</span>
<button type="button" data-w="1280" aria-pressed="true">电脑</button><button type="button" data-w="390" aria-pressed="false">手机</button></div>
<div class="grid">{''.join(cards)}</div></main>
<script>(function(){{var W=1280;function fit(){{document.querySelectorAll('.frame').forEach(function(f){{var i=f.querySelector('iframe');if(!i)return;
var s=Math.min(1,f.clientWidth/W);i.style.width=W+'px';i.style.transform='scale('+s+')';}});}}
document.querySelectorAll('.bar button').forEach(function(b){{b.addEventListener('click',function(){{W=+b.getAttribute('data-w');
document.querySelectorAll('.bar button').forEach(function(x){{x.setAttribute('aria-pressed',x===b?'true':'false');}});fit();}});}});
window.addEventListener('resize',fit);fit();}})();</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("--out", required=True)
    ap.add_argument("--style")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    brief = understand(a.text)
    opts = styles.options(brief)
    os.makedirs(a.out, exist_ok=True)
    report = {"text": a.text, "understood": summary(brief), "questions": [q["question"] for q in brief["open_questions"]],
              "style_options": opts}
    if a.preview:
        results = [build_one(brief, o["id"], os.path.join(a.out, o["id"]), not a.no_browser) for o in opts]
        with open(os.path.join(a.out, "preview.html"), "w", encoding="utf-8") as f:
            f.write(preview_page(a.text, brief, results, opts))
        report["builds"] = results
    else:
        sid = a.style or opts[0]["id"]
        if sid not in styles._STYLES:
            sys.exit(f"不认识的风格 ID：{sid}")
        report["builds"] = [build_one(brief, sid, a.out, not a.no_browser)]
    with open(os.path.join(a.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    for r in report["builds"]:
        print(f"{r['style']}：{len(r['pages'])} 页 · 图纸错误 {len(r['blueprint_errors'])} · 浏览器问题 {len(r['browser_problems'])}")
        for e in (r["blueprint_errors"] + r["browser_problems"])[:5]:
            print("   ", e)
    print("理解：", json.dumps(report["understood"], ensure_ascii=False))
    if a.preview:
        print("对比页：", os.path.join(a.out, "preview.html"))


if __name__ == "__main__":
    main()
