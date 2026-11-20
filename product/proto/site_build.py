#!/usr/bin/env python3
"""原型用的“构建”：检查一个静态小站，报出错误（带文件和行号，模拟真实报错的样子）。

检查四类问题：缺 <title>、站内死链、图片缺 alt、同页 id 重复。
真实产品里这一步换成真正的构建 + 浏览器控制台 + 无障碍扫描；修复回路不关心错误从哪来。
"""
from html.parser import HTMLParser


class _Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = False
        self.links, self.imgs_no_alt, self.ids = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        if tag == "title":
            self.title = True
        if tag == "a" and a.get("href"):
            self.links.append((a["href"], line))
        if tag == "img" and not (a.get("alt") or "").strip():
            self.imgs_no_alt.append((a.get("src", "?"), line))
        if a.get("id"):
            self.ids.append((a["id"], line))


def build(files: dict[str, str]) -> list[str]:
    pages = {p for p in files if p.endswith(".html")}
    errors = []
    for p in sorted(pages):
        s = _Scan()
        s.feed(files[p])
        if not s.title:
            errors.append(f"缺少 <title>：{p}")
        for href, line in s.links:
            if href.startswith(("http://", "https://", "mailto:", "tel:", "#")):
                continue
            target = href.split("#")[0].lstrip("/") or "index.html"
            if target not in pages:
                errors.append(f"死链：{p}:{line} → {href} 不存在")
        for src, line in s.imgs_no_alt:
            errors.append(f"图片缺少 alt：{p}:{line}（{src}）")
        seen = set()
        for i, line in s.ids:
            if i in seen:
                errors.append(f"重复 id「{i}」：{p}:{line}")
            seen.add(i)
    return errors
