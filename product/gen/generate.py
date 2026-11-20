#!/usr/bin/env python3
"""图纸 → 真实网站。网站结构是唯一事实来源：路由、导航、面包屑、sitemap.xml 都从它生成，
所以按钮和导航不可能指向不存在的页面（图纸检查器已先保证引用存在）。

用法：python3 -I generate.py <图纸项目目录> <输出目录>
产出：每页一个 index.html（/ → index.html，/menu → menu/index.html）、styles.css（由 DTCG 令牌转成 CSS 变量）、
     motion.js（尊重“减少动态效果”设置）、sitemap.xml。
文案和图片还没有生成时，用一眼能看出的占位，并把给文案 Agent 的说明写进 data-brief，方便下游接手。
"""
from __future__ import annotations

import html
import json
import posixpath
import os
import re
import shutil
import sys

E = html.escape


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ---------------- 令牌 → CSS ----------------
def _css_value(val):
    if isinstance(val, str) and val.startswith("{") and val.endswith("}"):
        return "var(--" + val[1:-1].replace(".", "-") + ")"
    if isinstance(val, list):
        if not val:
            return "none"
        if all(isinstance(x, str) for x in val):  # fontFamily
            return ", ".join(val)
        return ", ".join(_css_value(x) for x in val)  # 多层阴影
    if isinstance(val, dict):
        if "hex" in val:
            a = val.get("alpha", 1)
            if a >= 1:
                return val["hex"]
            r, g, b = (round(c * 255) for c in val["components"])
            return f"rgba({r}, {g}, {b}, {a})"
        if "value" in val and "unit" in val:
            return f"{val['value']}{val['unit']}"
        if "offsetX" in val:  # 阴影
            return " ".join(_css_value(val[k]) for k in ("offsetX", "offsetY", "blur", "spread")) + " " + _css_value(val["color"])
    return str(val)


def tokens_css(tokens: dict) -> str:
    out = []

    def walk(node, path):
        for k, v in node.items():
            if k.startswith("$") or not isinstance(v, dict):
                continue
            p = path + [k]
            if "$value" in v:
                out.append((p, v["$value"]))
            else:
                walk(v, p)
    walk(tokens, [])
    lines = [f"  --{'-'.join(p)}: {_css_value(val)};" for p, val in out]
    return ":root {\n" + "\n".join(lines) + "\n}\n"


BASE_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:var(--font-body,system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif);
  background:var(--color-background,#fff);color:var(--color-foreground,#222);line-height:1.6}
h1,h2,h3,.brand{font-family:var(--font-heading,inherit);text-transform:var(--heading-transform,none);line-height:1.25}
.t-hero h2{font-size:clamp(28px,5vw,48px);margin:0 0 12px}
.muted{color:var(--color-muted,#666)}
a{color:var(--color-link,var(--color-primary,#0b57d0))}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
section.page-head{padding:32px 20px 0!important;background:none!important;border:none!important}section.page-head h1{margin:0;font-size:clamp(26px,4vw,38px)}
header.site{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;padding:14px 20px;border-bottom:1px solid var(--color-border,#ddd)}
header.site nav a,footer.site nav a{display:inline-block;padding:12px 4px;margin-right:12px;text-decoration:none}
a.brand{display:inline-block;padding:8px 0}
nav.crumbs{font-size:13px;padding:2px 20px}nav.crumbs a{display:inline-block;padding:12px 2px}
section{padding:40px 20px}
.btn{display:inline-block;padding:10px 18px;border-radius:var(--radius-md,8px);border:var(--border-width,1px) solid var(--color-primary,#0b57d0);text-decoration:none;margin:4px 8px 4px 0;transition:transform var(--duration-base,200ms) ease-out}
.btn:hover{transform:translateY(-1px)}
.btn.primary{background:var(--color-primary,#0b57d0);color:var(--color-on-primary,#fff)}
.grid{display:grid;gap:16px;list-style:none;padding:0;margin:16px 0 0}
.grid .card h3,.grid .card h2{margin:0 0 4px;font-size:17px}.grid .card p{margin:0}
.v-grid-2 .grid{grid-template-columns:repeat(2,1fr)}.v-grid-3 .grid,.v-carousel .grid,.v-bento .grid{grid-template-columns:repeat(3,1fr)}
.v-grid-4 .grid{grid-template-columns:repeat(4,1fr)}
.has-media.v-split-left>.wrap,.has-media.v-split-right>.wrap{display:grid;grid-template-columns:1.1fr 1fr;gap:40px;align-items:center}
.v-split-left>.wrap>.media{order:-1}
.media{margin:0}.ph{min-height:260px;padding:16px;text-align:center;font-size:14px;opacity:.85}
.actions{margin-top:20px}.t-cta{text-align:center}.t-cta h2{margin:0 0 8px}
.t-hero{padding:72px 20px}.t-hero p{font-size:18px;max-width:34em}
.card{color:var(--color-foreground,#222);background:var(--color-card-surface,var(--color-card,#fafafa));border:var(--border-width,1px) solid var(--color-border,#eee);border-radius:var(--radius-md,8px);padding:16px;box-shadow:var(--shadow-card,none);backdrop-filter:blur(var(--surface-blur,0px))}
.ph{background:repeating-linear-gradient(45deg,#0000000d 0 10px,#0000 10px 20px);border-radius:var(--radius-md,8px);min-height:180px;display:flex;align-items:center;justify-content:center}
.todo{outline:1px dashed #c33;outline-offset:2px}
.v-split-right .ph,.v-split-left .ph{min-height:320px}
.consent{display:flex!important;align-items:center;gap:8px;margin:14px 0!important}.consent input{width:24px!important;height:24px;margin:0;flex:none}
form label{display:block;margin:10px 0 4px}form input{width:100%;padding:8px;border:1px solid var(--color-border,#ccc);border-radius:6px}
footer.site{padding:24px 20px;border-top:1px solid var(--color-border,#ddd);font-size:14px}
@media (max-width:767px){.grid{grid-template-columns:1fr!important}.has-media.v-split-left>.wrap,.has-media.v-split-right>.wrap{grid-template-columns:1fr}.t-hero{padding:40px 20px}}
/* ---------- 六种风格家族 ---------- */
.fam-block h1,.fam-block h2{font-weight:800;letter-spacing:-.01em}
.fam-block section:nth-of-type(even){background:var(--color-band);color:var(--color-band-ink)}
.fam-block section:nth-of-type(even) a:not(.primary){color:inherit}.fam-block section:nth-of-type(even) .btn:not(.primary){border-color:currentColor}
.fam-block .card,.fam-block .btn,.fam-block .ph{border:3px solid var(--color-foreground);box-shadow:4px 4px 0 var(--color-foreground)}
.fam-block header.site{border-bottom:3px solid var(--color-foreground)}
.fam-soft .btn{border-radius:999px}.fam-soft .card{border:none;border-radius:var(--radius-lg,20px)}
.fam-soft section:nth-of-type(even){background:var(--color-band)}.fam-soft .ph{border-radius:var(--radius-lg,20px);background-color:var(--color-band)}
.fam-minimal h1{font-size:clamp(36px,7vw,72px);font-weight:700;letter-spacing:-.02em}.fam-minimal .t-hero h1{font-size:clamp(36px,7vw,72px)}
.fam-minimal .card{color:inherit;border:none;border-top:1px solid var(--color-foreground);border-radius:0;background:transparent;box-shadow:none;padding:16px 0}
.fam-minimal .btn{border-radius:0}.fam-minimal .ph{border-radius:0}.fam-minimal section{border-top:1px solid var(--color-border)}
body.fam-glass{background:linear-gradient(135deg,var(--color-band),var(--color-band-2)) fixed}
.fam-glass .card,.fam-glass header.site,.fam-glass .ph{background:rgba(255,255,255,.55);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,.7)}
.fam-glass .btn{border-radius:12px}
.fam-dark .btn.primary{box-shadow:0 0 18px var(--color-primary)}.fam-dark section:nth-of-type(even){background:var(--color-band)}
.fam-dark .ph{background-color:var(--color-card)}
.fam-editorial h1,.fam-editorial h2{font-weight:400}.fam-editorial .t-hero h1{font-size:clamp(34px,6vw,64px)}
.fam-editorial section{border-top:1px solid var(--color-foreground)}
.fam-editorial .card{color:inherit;border:none;border-left:2px solid var(--color-foreground);border-radius:0;background:transparent;box-shadow:none}
.fam-editorial .btn{border-radius:0}
@media (prefers-reduced-motion:no-preference){.reveal{opacity:0;transform:translateY(12px);transition:opacity .4s ease-out,transform .4s ease-out}.reveal.in{opacity:1;transform:none}}
"""

MOTION_JS = """(function(){
  // 动效只是锦上添花：首屏内容从不隐藏；出现动画的信号收不到时，1.5 秒后全部显示（内容不能依赖动画才看得见）
  if(!window.matchMedia||matchMedia('(prefers-reduced-motion: reduce)').matches||!('IntersectionObserver' in window)){return;}
  var h=window.innerHeight||800, els=[].slice.call(document.querySelectorAll('[data-motion]')).filter(function(el){
    return el.getBoundingClientRect().top>h;});
  var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});});
  els.forEach(function(el){el.classList.add('reveal');io.observe(el);});
  setTimeout(function(){els.forEach(function(el){el.classList.add('in');});},1500);
})();
"""


# ---------------- 路由 ----------------
def out_file(path: str) -> str:
    return "index.html" if path == "/" else path.strip("/") + "/index.html"


def href(path: str, section: str = "", here: str | None = None) -> str:
    """页面地址。给了 here（当前页面路径）就返回相对路径：网站放在任何子目录下都能用（工作台预览、子路径托管）。"""
    target = "/" if path == "/" else path.rstrip("/") + "/"
    if here is not None:
        cur = "/" if here == "/" else here.rstrip("/") + "/"
        r = posixpath.relpath(target, cur)
        target = "./" if r == "." else r + "/"
    return target + (f"#{section}" if section else "")


def asset(name: str, here: str) -> str:
    """站点根目录下的文件（styles.css 等）相对当前页面的路径。"""
    depth = 0 if here == "/" else len(here.strip("/").split("/"))
    return "../" * depth + name


MEDIA = ("image", "video", "embed")


def render_slot(name, slot, val=None, sectype="", labels=None):
    """val 来自文案文件 content/<语言>.json；没有就用一眼能看出的占位。"""
    kind, brief = slot.get("kind"), slot.get("brief", "")
    tip = f' data-brief="{E(brief)}"' if brief else ""
    if kind == "image":
        alt = brief or name
        return (f'<figure class="media"><div class="ph" role="img" aria-label="{E(alt)}"{tip}>'
                f'<span>图片待生成：{E(alt)}</span></div></figure>')
    if kind == "embed":
        return f'<figure class="media"><div class="ph"{tip}><span>{E(val or "嵌入内容待配置：" + name)}</span></div></figure>'
    if kind == "list":
        items = val if isinstance(val, list) else [{"title": f"条目 {i + 1}（待填写）", "body": ""} for i in range(slot.get("count", 3))]
        cells = "".join(f'<li class="card"><h3>{E(str(it.get("title", "")))}</h3>'
                        + (f'<p class="muted">{E(str(it.get("body", "")))}</p>' if it.get("body") else "") + "</li>"
                        for it in items)
        return f'<ul class="grid items">{cells}</ul>'
    if kind == "form_fields":
        lab = labels or {}
        return "".join(f'<label for="f-{E(f)}">{E(lab.get(f, f))}</label><input id="f-{E(f)}" name="{E(f)}">'
                       for f in slot.get("fields", []))
    tag = ("h1" if sectype == "hero" else "h2") if name == "heading" else "p"
    if val:
        return f"<{tag}>{E(str(val))}</{tag}>"
    return f'<{tag} class="todo"{tip}>【{E(name)}待写】{E(brief)}</{tag}>'


def render_section(s, pages, content=None, here=None):
    content = content or {}
    variant = s["layout"]["variant"]
    mobile = " m-stack" if s["layout"].get("mobile") == "stack" else ""
    motion = ' data-motion="1"' if s.get("motion") else ""
    if s["type"] in ("header", "footer"):
        return ""  # 页头页脚统一由网站结构生成
    text, media = [], []
    for n, sl in s.get("slots", {}).items():
        html_ = render_slot(n, sl, content.get(n), s["type"], content.get("labels"))
        (media if sl.get("kind") in MEDIA else text).append(html_)
    acts = []
    form_open = form_close = ""
    for a in s.get("actions", []):
        t, cls = a["target"], "btn primary" if a.get("primary") else "btn"
        if "submit" in t:
            then = pages[t["then"]]["path"] if t.get("then") else ""
            form_open = (f'<form data-feature="{E(t["submit"])}" action="{E(href(then, here=here))}" method="get">' if then
                         else f'<form data-feature="{E(t["submit"])}">')
            consent = ""
            if "privacy" in pages:  # 收集个人信息的表单：要先勾选同意隐私政策（个人信息保护法要求告知并取得同意）
                consent = (f'<label class="consent"><input type="checkbox" name="consent" required>'
                           f'<span>我已阅读并同意<a href="{E(href(pages["privacy"]["path"], here=here))}">《隐私政策》</a></span></label>')
            form_close = consent + f'<button class="{cls}" type="submit">{E(a["label"])}</button></form>'
            continue
        if "page" in t:
            url = href(pages[t["page"]]["path"], t.get("section", ""), here)
        elif "section" in t:
            url = f'#{t["section"]}'
        else:
            url = t["url"]
        acts.append(f'<a class="{cls}" href="{E(url)}">{E(a["label"])}</a>')
    body = "".join(text)
    if form_open:
        body = form_open + body + form_close
    if acts:
        body += f'<div class="actions">{"".join(acts)}</div>'
    inner = f'<div class="text">{body}</div>' + "".join(media)
    return (f'<section id="{E(s["id"])}" class="t-{E(s["type"])} v-{E(variant)}{mobile}{" has-media" if media else ""}"{motion}>'
            f'<div class="wrap">{inner}</div></section>')


# 自我纠错用的修补：封闭清单，只能按名字选用，不接受任意 CSS（防止修补本身变成注入通道）。
# 写在项目的 fixes.json 里（["wrap-long-words", ...]），生成时追加到 styles.css 末尾并注明来源。
FIX_CSS = {
    "wrap-long-words": ("长单词、长网址允许在任意位置换行，不撑破屏幕",
                        "h1,h2,h3,h4,p,li,a,span,dd,dt,td,th,label,button,.brand{overflow-wrap:anywhere}"),
    "media-fit": ("图片、视频、嵌入内容不超过容器宽度", "img,video,iframe,svg,canvas,embed,object{max-width:100%;height:auto}"),
    "table-scroll": ("表格太宽时在自己的框里横向滚动", "table{display:block;max-width:100%;overflow-x:auto}"),
    "pre-wrap": ("代码块自动换行", "pre,code{white-space:pre-wrap;overflow-wrap:anywhere}"),
    "reveal-visible": ("入场动画不再把内容先藏起来", ".reveal{opacity:1!important;transform:none!important}"),
    "tap-targets": ("按钮、导航链接、输入框加大到手指好点的尺寸（至少 44px 高）",
                    "nav a,a.btn,button,input,select,textarea,[role=button]{min-height:44px}nav a{display:inline-flex;align-items:center}"),
}


def tweaks_css(t: dict) -> str:
    """对话修改里的“字大一点 / 圆角大一点 / 间距宽松一点”。只接受封闭的取值，在样式最后一层覆盖。"""
    out = []
    f = t.get("font")
    if f is not None:
        f = float(f)
        if not 0.8 <= f <= 1.4:
            raise ValueError("字号倍数超出范围")
        out.append(f"body{{font-size:{16 * f:.1f}px!important}}.t-hero p{{font-size:{18 * f:.1f}px!important}}"
                   f".grid .card h3{{font-size:{17 * f:.1f}px!important}}footer.site{{font-size:{14 * f:.1f}px!important}}"
                   f".t-hero h1,.t-hero h2{{font-size:clamp({28 * f:.0f}px,{5 * f:.1f}vw,{48 * f:.0f}px)!important}}")
    r = t.get("radius")
    if r is not None:
        px = {"square": (0, 0), "small": (4, 4), "large": (18, 999)}.get(r)
        if px is None:
            raise ValueError("圆角取值不对")
        out.append(f".card,.ph,form input,form textarea,form select{{border-radius:{px[0]}px!important}}.btn{{border-radius:{px[1]}px!important}}")
    d = t.get("density")
    if d is not None:
        pad = {"tight": 24, "loose": 64}.get(d)
        if pad is None:
            raise ValueError("间距取值不对")
        out.append(f"section{{padding-top:{pad}px!important;padding-bottom:{pad}px!important}}")
    return ("\n/* 对话修改：字号、圆角、间距 */\n" + "".join(out) + "\n") if out else ""


# 已“升格”的修补：自我纠错在多个行业、多次验证有效后，写进默认样式，每个网站都带上（P024 的最后一级）。
# 测试自我纠错机制时需要一个会出问题的生成器，用环境变量 AISITE_SIMULATE_OLD_GENERATOR=1 模拟升格之前的版本。
PROMOTED = ["wrap-long-words"]


def promoted_css() -> str:
    if os.environ.get("AISITE_SIMULATE_OLD_GENERATOR") == "1":
        return ""
    return "".join(f"\n/* 已升格的修补：{n} — {FIX_CSS[n][0]} */\n{FIX_CSS[n][1]}\n" for n in PROMOTED)


def fixes_css(names) -> str:
    bad = [n for n in names if n not in FIX_CSS]
    if bad:
        raise ValueError(f"未知的修补：{bad}（只能用 FIX_CSS 里的）")
    return "".join(f"\n/* 自动纠错：{n} — {FIX_CSS[n][0]} */\n{FIX_CSS[n][1]}\n" for n in names)


def _no_skipped_headings(html_: str) -> str:
    """标题不跳级（h1 后面直接 h3 → 改成 h2）。只改层级，样式上给卡片里的 h2 和 h3 同样的样子。"""
    prev = [0]

    def fix(m):
        lvl = int(m.group(1))
        new = min(lvl, prev[0] + 1) if prev[0] else lvl
        prev[0] = new
        return f"<h{new}{m.group(2)}>{m.group(3)}</h{new}>"
    return re.sub(r"<h([1-6])(\b[^>]*)>(.*?)</h\1>", fix, html_, flags=re.S)


def generate(project, out):
    site = load(os.path.join(project, "site.json"))
    brief = load(os.path.join(project, "brief.json"))
    pages = {p["id"]: p for p in site["pages"]}
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    tok = os.path.join(project, site["style"]["tokens"])
    css = (tokens_css(load(tok)) if os.path.exists(tok) else "") + BASE_CSS
    css += promoted_css()
    fx = os.path.join(project, "fixes.json")
    if os.path.exists(fx):
        css += fixes_css(load(fx))
    tw = os.path.join(project, "tweaks.json")
    if os.path.exists(tw):
        css += tweaks_css(load(tw))
    open(os.path.join(out, "styles.css"), "w", encoding="utf-8").write(css)
    open(os.path.join(out, "motion.js"), "w", encoding="utf-8").write(MOTION_JS)
    # 模型写的自定义代码（交互、动效）：原样带进网站，每页都引用；它出错会在浏览器检查里暴露
    custom = [f for f in ("site.js", "site.css") if os.path.exists(os.path.join(project, "custom", f))]
    for f in custom:
        shutil.copy(os.path.join(project, "custom", f), os.path.join(out, f))
    has_css, has_js = "site.css" in custom, "site.js" in custom
    order = lambda p: (p["nav"].get("order", 99), p["id"])
    header = sorted([p for p in site["pages"] if p["nav"]["header"]], key=order)
    footer = sorted([p for p in site["pages"] if p["nav"]["footer"]], key=order)
    name = brief.get("site_name") or brief["id"]
    lang = site.get("default_locale", "zh-CN")
    cfile = os.path.join(project, "content", f"{lang}.json")
    content = load(cfile) if os.path.exists(cfile) else {}
    fam = (load(tok).get("$extensions", {}).get("aisite", {}).get("family", "") if os.path.exists(tok) else "")
    body_cls = f' class="fam-{E(fam)}"' if fam else ""
    written = []
    for p in site["pages"]:
        wire = load(os.path.join(project, p["wireframe"]))
        crumbs, par, seen = [], p.get("parent"), {p["id"]}
        while par in pages and par not in seen:  # 有界：seen 防环，最多走页面数步
            seen.add(par)
            crumbs.insert(0, pages[par])
            par = pages[par].get("parent")
        cur_attr = ' aria-current="page"'  # f-string 花括号里不能有反斜杠（Python 3.12 以前），先放进变量（D25）
        nav = lambda ps: "".join(f'<a href="{E(href(x["path"], here=p["path"]))}"{cur_attr if x["id"] == p["id"] else ""}>'
                                 f'{E(x["nav"].get("label") or x["title"])}</a>' for x in ps)
        crumb_html = ("<nav class=\"crumbs\" aria-label=\"面包屑\">" + " / ".join(
            f'<a href="{E(href(c["path"], here=p["path"]))}">{E(c["title"])}</a>' for c in crumbs) + f" / {E(p['title'])}</nav>") if crumbs else ""
        seo = p.get("seo", {})
        title = seo.get("title") or f'{p["title"]} · {name}'
        desc = seo.get("description", "")
        robots = '<meta name="robots" content="noindex">' if seo.get("index") is False else ""
        here = p["path"]
        sections = "".join(render_section(s, pages, content.get(p["id"], {}).get(s["id"]), here) for s in wire["sections"])
        if "<h1" not in sections:  # 每页要有且只有一个一级标题（上线体检发现：D23）
            if "<h2" in sections:  # 有区块标题：第一个升为一级，后面的层级下面统一理顺（不重复显示页面名）
                sections = re.sub(r"<h2([ >])(.*?)</h2>", r"<h1\1\2</h1>", sections, count=1, flags=re.S)
            else:  # 一个标题都没有（如隐私政策正文）：加一行页面标题
                sections = (f'<section class="page-head"><div class="wrap"><h1>{E(name if p["path"] == "/" else p["title"])}</h1></div></section>'
                            + sections)
        sections = _no_skipped_headings(sections)
        doc = (f'<!doctype html><html lang="{E(lang)}"><head><meta charset="utf-8">'
               f'<meta name="viewport" content="width=device-width,initial-scale=1">'
               f'<title>{E(title)}</title><meta name="description" content="{E(desc)}">{robots}'
               f'<meta property="og:type" content="website"><meta property="og:title" content="{E(title)}">'
               f'<meta property="og:description" content="{E(desc)}"><meta property="og:locale" content="{E(lang.replace("-", "_"))}">'
               f'<link rel="icon" href="data:,">'
               f'<link rel="stylesheet" href="{asset("styles.css", here)}">'
               + (f'<link rel="stylesheet" href="{asset("site.css", here)}">' if has_css else "")
               + f'</head><body{body_cls}>'
               f'<header class="site"><a href="{E(href("/", here=here))}" class="brand"><strong>{E(name)}</strong></a><nav aria-label="主导航">{nav(header)}</nav></header>'
               f'{crumb_html}<main>{sections}</main>'
               f'<footer class="site"><nav aria-label="页脚导航">{nav(footer)}</nav></footer>'
               f'<script src="{asset("motion.js", here)}" defer></script>'
               + (f'<script src="{asset("site.js", here)}" defer></script>' if has_js else "")
               + '</body></html>\n')
        f = os.path.join(out, out_file(p["path"]))
        os.makedirs(os.path.dirname(f), exist_ok=True)
        open(f, "w", encoding="utf-8").write(doc)
        written.append(out_file(p["path"]))
    base = site.get("base_url", "").rstrip("/")
    if base:  # sitemap 标准要求完整网址
        urls = "".join(f"<url><loc>{E(base + href(p['path']))}</loc></url>" for p in site["pages"]
                       if p.get("seo", {}).get("index", True) is not False)
        open(os.path.join(out, "sitemap.xml"), "w", encoding="utf-8").write(
            f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    open(os.path.join(out, "robots.txt"), "w", encoding="utf-8").write(
        "User-agent: *\nAllow: /\n" + (f"Sitemap: {base}/sitemap.xml\n" if base else ""))
    return written


if __name__ == "__main__":
    w = generate(sys.argv[1], sys.argv[2])
    print(f"生成 {len(w)} 个页面：" + "、".join(w))
