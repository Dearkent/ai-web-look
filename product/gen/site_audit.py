#!/usr/bin/env python3
"""上线前体检：SEO、性能、无障碍、合规四项打分（0–100），每一项都说清楚哪里不行、怎么改。

只做静态检查（读生成好的文件），不联网、不运行页面脚本；无障碍里需要真实浏览器量的那几项（对比度、点按区域、字号、
图片替代文字、输入框标签、横向溢出）直接用 browser_check 的结果。需要域名才能做的（sitemap、规范网址）在没填域名时
列为“待定”，不计分。

    python3 -I site_audit.py <网站目录>
"""
from __future__ import annotations

import html.parser
import json
import os
import posixpath
import re
import sys

ABSOLUTE = ["最佳", "最好", "最优", "最低价", "第一", "唯一", "顶级", "国家级", "世界级", "全网", "首选", "极致", "绝对", "万能", "史无前例", "独一无二"]
EXTERNAL_FONT = re.compile(r"fonts\.googleapis|fonts\.gstatic|use\.typekit|fonts\.bunny", re.I)


class _Page(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.lang, self.headings, self.links, self.scripts, self.styles = "", {}, "", [], [], [], []
        self.landmarks, self.text, self.forms, self.consent, self.imgs, self.ext = set(), [], 0, 0, [], []
        self._in, self._skip, self._a = None, 0, None

    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title":
            self._in = "title"
        elif tag == "meta":
            k = a.get("name") or a.get("property")
            if k:
                self.meta[k] = a.get("content", "")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append(int(tag[1]))
        elif tag in ("header", "main", "footer", "nav"):
            self.landmarks.add(tag)
        elif tag == "a":
            self._a = {"href": a.get("href", ""), "text": "", "label": a.get("aria-label", "")}
        elif tag == "script":
            self._skip += 1
            if a.get("src"):
                self.scripts.append({"src": a["src"], "defer": "defer" in a or "async" in a})
                if a["src"].startswith(("http:", "https:", "//")):
                    self.ext.append(a["src"])
        elif tag == "link" and "stylesheet" in (a.get("rel") or ""):
            self.styles.append(a.get("href", ""))
            if a.get("href", "").startswith(("http:", "https:", "//")):
                self.ext.append(a["href"])
        elif tag == "style":
            self._skip += 1
        elif tag == "form":
            self.forms += 1
        elif tag == "input" and a.get("name") == "consent" and a.get("type") == "checkbox" and "required" in a:
            self.consent += 1
        elif tag == "img":
            self.imgs.append(a)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in = None
        elif tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._a is not None:
            self.links.append(self._a)
            self._a = None

    def handle_data(self, d):
        if self._in == "title":
            self.title += d
        elif not self._skip:
            self.text.append(d)
            if self._a is not None:
                self._a["text"] += d


def _pages(site: str) -> dict[str, _Page]:
    out = {}
    for root, _, files in os.walk(site):
        for f in files:
            if f.endswith(".html"):
                p = _Page()
                p.feed(open(os.path.join(root, f), encoding="utf-8").read())
                out["/" + os.path.relpath(os.path.join(root, f), site).replace(os.sep, "/")] = p
    return out


def audit(site: str, browser_problems: list[str] | None = None, domain: str = "") -> dict:
    pages = _pages(site)
    items = []

    def add(cat, ok, msg, fix="", pending=False):
        items.append({"cat": cat, "ok": bool(ok), "msg": msg, "fix": "" if ok else fix, "pending": pending})

    # ---------- SEO
    bad_title = [u for u, p in pages.items() if not 2 <= len(p.title.strip()) <= 60]
    add("SEO", not bad_title, "每页都有 2–60 字的标题" if not bad_title else f"{len(bad_title)} 页标题缺失或太长：{bad_title[0]}", "检查页面标题")
    bad_desc = [u for u, p in pages.items() if not 10 <= len(p.meta.get("description", "").strip()) <= 160 and "noindex" not in p.meta.get("robots", "")]
    add("SEO", not bad_desc, "每页都有 10–160 字的描述" if not bad_desc else f"{len(bad_desc)} 页缺少合适的描述：{bad_desc[0]}",
        "在需求里写清楚这家店做什么，描述会跟着更具体")
    bad_h1 = [u for u, p in pages.items() if p.headings.count(1) != 1]
    add("SEO", not bad_h1, "每页恰好一个一级标题" if not bad_h1 else f"{len(bad_h1)} 页一级标题不是一个：{bad_h1[0]}", "每页保留一个主标题")
    add("SEO", all(p.meta.get("og:title") for p in pages.values()), "分享到微信/社交平台时有标题和描述（og 标签）", "生成器补上 og 标签")
    add("SEO", os.path.exists(os.path.join(site, "robots.txt")), "有 robots.txt", "生成器补上 robots.txt")
    has_map = os.path.exists(os.path.join(site, "sitemap.xml"))
    add("SEO", has_map, "有 sitemap.xml（搜索引擎靠它找全页面）" if has_map else "还没有 sitemap.xml",
        "导出时填上网站域名，就会生成 sitemap 和规范网址", pending=not has_map and not domain)

    # ---------- 性能
    sizes = {}
    for root, _, files in os.walk(site):
        for f in files:
            sizes["/" + os.path.relpath(os.path.join(root, f), site).replace(os.sep, "/")] = os.path.getsize(os.path.join(root, f))
    shared = sum(v for k, v in sizes.items() if k.endswith((".css", ".js")))
    heaviest = max((sizes.get(u, 0) for u in pages), default=0) + shared
    add("性能", heaviest <= 200_000, f"最重的页面（含样式和脚本）{heaviest // 1024} KB，不超过 200 KB" if heaviest <= 200_000 else f"最重的页面 {heaviest // 1024} KB，偏重",
        "减少脚本和大图")
    # 打开页面时立刻要发的请求：样式、脚本、不懒加载的图片（懒加载的图片滚到附近才下载，不算）
    reqs = max((len(p.scripts) + len(p.styles) + sum(1 for i in p.imgs if i.get("loading") != "lazy") for p in pages.values()), default=0)
    add("性能", reqs <= 8, f"打开每页最多立刻发 {reqs} 个请求" if reqs <= 8 else f"有页面一打开就要发 {reqs} 个请求", "合并样式和脚本，图片用懒加载")
    # 图片体积：每张最大的那份不超过 400 KB；每页图片（按默认的 src 算）合计不超过 1.5 MB
    def img_files(u, i):
        out = []
        for part in [i.get("src", "")] + [c.strip().split(" ")[0] for c in (i.get("srcset") or "").split(",") if c.strip()]:
            if part and not part.startswith(("http:", "https:", "//", "data:")):
                out.append(posixpath.normpath(posixpath.join(posixpath.dirname(u), part)))
        return out
    big, page_img = [], 0
    for u, p in pages.items():
        tot = 0
        for i in p.imgs:
            fs = img_files(u, i)
            if fs:
                tot += sizes.get(fs[0], 0)
            big += [f for f in fs if sizes.get(f, 0) > 400_000]
        page_img = max(page_img, tot)
    add("性能", not big and page_img <= 1_500_000, f"图片都压缩过（单张不超过 400 KB，每页合计 {page_img // 1024} KB）" if not big and page_img <= 1_500_000
        else (f"有图片太大：{big[0]}" if big else f"有页面图片合计 {page_img // 1024} KB，偏重"), "照片从工作台上传会自动压缩；直接放进来的大图先压缩")
    blocking = [s["src"] for p in pages.values() for s in p.scripts if not s["defer"]]
    add("性能", not blocking, "脚本都延后加载，不挡首屏" if not blocking else f"有脚本会挡住首屏：{blocking[0]}", "给脚本加 defer")
    ext = sorted({x for p in pages.values() for x in p.ext})
    css_text = "".join(open(os.path.join(site, k.lstrip("/")), encoding="utf-8", errors="replace").read() for k in sizes if k.endswith(".css"))
    ext_font = bool(EXTERNAL_FONT.search(css_text)) or any(EXTERNAL_FONT.search(x) for x in ext)
    add("性能", not ext and not ext_font, "不依赖外部服务器的字体和脚本（国内访问不会卡在境外资源上）" if not ext and not ext_font
        else "依赖外部资源：" + ", ".join(ext[:2] or ["外部字体"]), "把字体和脚本放到自己的网站里，或用系统字体")
    noisize = sum(1 for p in pages.values() for i in p.imgs if not (i.get("width") and i.get("height")))
    add("性能", noisize == 0, "图片都写了宽高（加载时页面不跳动）" if noisize == 0 else f"{noisize} 张图片没写宽高", "给图片写上宽高")

    # ---------- 无障碍
    bp = browser_problems or []
    for key, ok_msg in (("文字对比度不够", "文字和背景对比度够"), ("点按区域太小", "按钮和链接够大，手指好点"), ("字太小", "没有小于 12px 的字"),
                        ("图片缺替代文字", "图片都有替代文字"), ("输入框没有标签", "输入框都有标签"), ("横向溢出", "手机上不会左右晃")):
        hit = [x for x in bp if key in x]
        add("无障碍", not hit, ok_msg if not hit else hit[0][:80], "看自我纠错的结果，或在对话修改里调整")
    nolang = [u for u, p in pages.items() if not p.lang]
    add("无障碍", not nolang, "每页标明了语言（读屏软件按中文读）" if not nolang else f"有 {len(nolang)} 页没标明语言：{nolang[0]}", "html 标签加 lang")
    skips = [u for u, p in pages.items() if any(b - a > 1 for a, b in zip(p.headings, p.headings[1:]))]
    add("无障碍", not skips, "标题层级不跳级" if not skips else f"{len(skips)} 页标题跳级：{skips[0]}", "按 h1→h2→h3 的顺序")
    marks = [u for u, p in pages.items() if not {"header", "main", "footer"} <= p.landmarks]
    add("无障碍", not marks, "每页都有页头、主体、页脚区域" if not marks else f"{len(marks)} 页缺少页面区域标记", "用 header/main/footer")
    empty = [lk["href"] for p in pages.values() for lk in p.links if not lk["text"].strip() and not lk["label"]]
    add("无障碍", not empty, "链接都有文字" if not empty else f"{len(empty)} 个链接没有文字", "给链接加文字或 aria-label")

    # ---------- 合规（国内上线）
    forms = sum(p.forms for p in pages.values())
    consent = sum(p.consent for p in pages.values())
    has_priv = any("privacy" in u for u in pages)
    add("合规", not forms or has_priv, ("收集信息的表单配了隐私政策页" if has_priv else "有收集个人信息的表单，但没有隐私政策页")
        if forms else "没有收集个人信息的表单", "加隐私政策页")
    add("合规", not forms or consent >= forms, ("每个表单提交前都要勾选同意隐私政策" if consent >= forms else
                                               f"有 {forms - consent} 个表单没有“同意隐私政策”的必选勾选") if forms else "无表单，不需要勾选同意",
        "表单加同意勾选（个人信息保护法要求告知并取得同意）")
    alltext = "".join("".join(p.text) for p in pages.values())
    words = sorted({w for w in ABSOLUTE if w in alltext})
    add("合规", not words, "没有广告法禁用的绝对化用语" if not words else "出现了广告法风险词：" + "、".join(words[:4]),
        "在对话修改里把这些词换掉（例如“最好喝”→“很好喝”）")
    todo = alltext.count("待填")
    add("合规", todo == 0, "没有待填内容" if todo == 0 else f"还有 {todo} 处“待填”（评价、价格、地址、故事、隐私政策细节等）",
        "上线前换成真实内容；这些是系统不能替你编的", pending=False)
    arts = sum(1 for p in pages.values() for i in p.imgs if i.get("data-art") is not None)
    add("合规", arts == 0, "图片都是你自己的照片" if arts == 0 else f"还有 {arts} 处用的是示意插图（不是实拍）",
        "在工作台右边“图片”里换成你自己的照片；插图本身可以直接上线，只是不能当成店里的真实样子", pending=arts > 0)
    beian = "beian.miit.gov.cn" in "".join(lk["href"] for p in pages.values() for lk in p.links)
    add("合规", beian, "页脚有 ICP 备案号" if beian else "页脚还没有 ICP 备案号",
        "在中国大陆服务器上线需要先备案，导出时填上备案号就会加到页脚；境外服务器可忽略", pending=not beian)

    scores = {}
    for cat in ("SEO", "性能", "无障碍", "合规"):
        xs = [x for x in items if x["cat"] == cat and not x["pending"]]
        scores[cat] = round(100 * sum(x["ok"] for x in xs) / len(xs)) if xs else 100
    return {"scores": scores, "items": items, "pages": len(pages)}


if __name__ == "__main__":
    r = audit(sys.argv[1])
    print(json.dumps(r["scores"], ensure_ascii=False))
    for x in r["items"]:
        print(("✓ " if x["ok"] else ("… " if x["pending"] else "✗ ")) + f"[{x['cat']}] {x['msg']}" + (f" → {x['fix']}" if x["fix"] else ""))
