#!/usr/bin/env python3
"""用真实浏览器检查生成的网站：本机起一个只监听 127.0.0.1 的静态服务器，用 Chrome 打开每一页。

查这些（每条都写成“浏览器·类别：页面 → 细节”，给修复回路当报错用）：
  脚本报错（控制台 error 和未捕获异常）、加载失败（4xx/5xx、请求失败）、站内死链和锚点不存在、
  缺 <title>、缺 lang、图片缺替代文字、图片打不开、图片没写宽高、输入框没有标签、手机宽度（375px）横向溢出、首屏内容看不见；
  视觉审查（手机宽度）：文字对比度不够（正文 4.5:1、大字 3:1）、点按区域太小（< 24×24px）、字太小（< 12px）。
所有等待都有超时（经验 L016）；服务器和浏览器在 finally 里关掉。

用法：python3 -I browser_check.py <网站目录>
"""
from __future__ import annotations

import functools
import http.server
import os
import sys
import threading
from urllib.parse import urldefrag, urljoin, urlparse

def find_chrome() -> str | None:
    """找本机的 Chrome/Chromium：环境变量 CHROME_PATH 优先，其次各系统的常见安装位置。找不到返回 None。"""
    import shutil
    cands = [os.environ.get("CHROME_PATH"), "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
             "/usr/bin/chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Chromium.app/Contents/MacOS/Chromium",
             os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
             os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
             os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
             shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chrome") or ""]
    return next((c for c in cands if c and os.path.isfile(c)), None)


CHROME = find_chrome() or "/usr/bin/google-chrome"


def ready() -> tuple[bool, str]:
    """浏览器检查能不能做：要有 Playwright（Python 包）和本机的 Chrome。不能做时给出怎么补。"""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False, "没装 Playwright（运行 pip install playwright 后重启工作台）"
    if not find_chrome():
        return False, "本机没找到 Chrome（装好 Chrome，或设置环境变量 CHROME_PATH 指向它）"
    return True, ""
PAGE_TIMEOUT_MS = 15000


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _pages(root):
    out = []
    for d, _, fs in os.walk(root):
        if "index.html" in fs:
            rel = os.path.relpath(d, root)
            out.append("/" if rel == "." else "/" + rel.replace(os.sep, "/") + "/")
    return sorted(out)


DOM_PROBE = """() => {
  const r = {title: document.title.trim(), lang: document.documentElement.lang,
             ids: [...document.querySelectorAll('[id]')].map(e => e.id), links: [], noAlt: [], noLabel: [],
             overflow: document.documentElement.scrollWidth - window.innerWidth};
  document.querySelectorAll('a[href]').forEach(a => r.links.push(a.getAttribute('href')));
  r.wide = [];  // 手机上超出屏幕的元素（最深的那几个），用来判断该怎么修
  const W = window.innerWidth;
  [...document.body.querySelectorAll('*')].forEach(e => {
    const b = e.getBoundingClientRect();
    if (b.width === 0 || b.right <= W + 1 || r.wide.length >= 5) return;
    if ([...e.children].some(c => c.getBoundingClientRect().right > W + 1)) return;  // 只要最深的
    const tag = e.tagName.toLowerCase(), own = [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('');
    // 图片只在比它的容器还宽时才算病因；和容器一样宽，说明是容器被别的东西（比如长单词）撑宽了，图片是被连累的（D30）
    const pw = e.parentElement ? e.parentElement.getBoundingClientRect().width : W;
    const kind = ['img','video','iframe','svg','canvas','embed','object'].includes(tag) ? (b.width > pw + 1 ? 'media' : 'box')
      : (e.closest('table') ? 'table' : (e.closest('pre') ? 'pre' : (new RegExp('[A-Za-z0-9_.@:/-]{15,}').test(own) ? 'text' : 'box')));
    r.wide.push({tag: tag, kind: kind});
  });
  // 视觉审查（只在手机宽度用）：文字对比度、点按区域、字号。都是能量出来的硬指标，不靠感觉。
  const lum = c => { const m = (c || '').match(/[0-9.]+/g); if (!m) return null; if (m.length > 3 && +m[3] < 0.9) return null;
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(+m[0]) + 0.7152 * f(+m[1]) + 0.0722 * f(+m[2]); };
  const bgOf = e => { for (let x = e; x; x = x.parentElement) { const st = getComputedStyle(x);
      if (st.backgroundImage !== 'none' || st.backdropFilter && st.backdropFilter !== 'none') return null;  // 背景是图、渐变或毛玻璃：量不准，不判
      const m = st.backgroundColor.match(/[0-9.]+/g); if (m && (m.length < 4 || +m[3] > 0.9)) return st.backgroundColor;
      if (m && m.length > 3 && +m[3] > 0.05) return null; }
    return 'rgb(255,255,255)'; };
  r.lowContrast = []; r.smallText = []; r.tapSmall = [];
  document.querySelectorAll('h1,h2,h3,h4,p,li,a,button,span,label,dd,dt,small,figcaption,strong,em,td,th').forEach(e => {
    if (![...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) return;
    const b = e.getBoundingClientRect(); if (!b.width || !b.height) return;
    const st = getComputedStyle(e); if (st.visibility === 'hidden') return;
    const fs = parseFloat(st.fontSize), txt = e.textContent.trim().slice(0, 12);
    if (fs < 12 && r.smallText.length < 3) r.smallText.push({text: txt, px: fs});
    const bg = bgOf(e), L1 = lum(st.color), L2 = lum(bg); if (L1 === null || L2 === null) return;
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05), need = (fs >= 24 || (fs >= 18.66 && +st.fontWeight >= 700)) ? 3 : 4.5;
    if (ratio < need && r.lowContrast.length < 3) r.lowContrast.push({text: txt, ratio: Math.round(ratio * 100) / 100, need: need});
  });
  document.querySelectorAll('button,input,select,textarea,nav a,a.btn,[role=button]').forEach(e => {
    const b = e.getBoundingClientRect(); if (!b.width || e.type === 'hidden') return;
    if ((b.height < 24 || b.width < 24) && r.tapSmall.length < 3) r.tapSmall.push({text: (e.textContent || e.name || e.tagName).trim().slice(0, 10), w: Math.round(b.width), h: Math.round(b.height)});
  });
  r.hidden = [];  // 首屏里本该看得见、却透明或不可见的内容（比如动画没触发）
  document.querySelectorAll('main section').forEach(s => {
    const b = s.getBoundingClientRect(), cs = getComputedStyle(s);
    if (b.top < window.innerHeight && b.bottom > 0 && b.height > 0 && (parseFloat(cs.opacity) < 0.1 || cs.visibility === 'hidden'))
      r.hidden.push(s.id || s.className);
  });
  // 没有 alt 属性算缺；alt="" 只允许纯装饰图（示意插图 data-art、role=presentation）
  document.querySelectorAll('img').forEach(i => { const deco = i.hasAttribute('data-art') || i.getAttribute('role') === 'presentation';
    if (!i.hasAttribute('alt') || (!deco && !(i.getAttribute('alt') || '').trim())) r.noAlt.push(i.getAttribute('src') || '?'); });
  document.querySelectorAll('[role=img]').forEach(i => { if (!(i.getAttribute('aria-label') || '').trim()) r.noAlt.push('[role=img]'); });
  document.querySelectorAll('input,select,textarea').forEach(f => {
    if (f.type === 'hidden' || f.type === 'submit') return;
    const ok = (f.id && document.querySelector('label[for="' + CSS.escape(f.id) + '"]')) || f.closest('label') || f.getAttribute('aria-label');
    if (!ok) r.noLabel.push(f.name || f.id || f.type);
  });
  return r;
}"""


# 图片：把懒加载的也立刻加载，最多等 4 秒；返回打不开的、没写宽高（加载时页面会跳）的
IMG_PROBE = """async () => {
  const imgs = [...document.querySelectorAll('img')];
  imgs.forEach(i => { i.loading = 'eager'; });
  await Promise.race([Promise.all(imgs.map(i => i.complete ? 0 : new Promise(r => { i.onload = i.onerror = r; }))),
                      new Promise(r => setTimeout(r, 4000))]);
  return {broken: imgs.filter(i => !i.complete || i.naturalWidth === 0).map(i => i.getAttribute('src') || '?'),
          noSize: imgs.filter(i => !i.getAttribute('width') || !i.getAttribute('height')).map(i => i.getAttribute('src') || '?')};
}"""


def check(root: str, detail: dict | None = None) -> list[str]:
    """detail：传一个空字典进来，会填上诊断信息 {"wide": {页面: [{"tag","kind"}]}}，给自我纠错用。"""
    from playwright.sync_api import sync_playwright
    root = os.path.abspath(root)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=root))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    pages = _pages(root)
    errors, probes = [], {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"], timeout=30000)
            try:
                for width, label in ((1280, "桌面"), (375, "手机")):
                    ctx = browser.new_context(viewport={"width": width, "height": 800})
                    for path in pages:
                        page = ctx.new_page()
                        page.set_default_timeout(PAGE_TIMEOUT_MS)
                        seen = []
                        page.on("console", lambda m, s=seen: s.append(("脚本报错", m.text)) if m.type == "error" else None)
                        page.on("pageerror", lambda e, s=seen: s.append(("脚本报错", str(e))))
                        page.on("requestfailed", lambda r, s=seen: s.append(("加载失败", urlparse(r.url).path + "（请求失败）")))
                        page.on("response", lambda r, s=seen: s.append(("加载失败", f"{urlparse(r.url).path}（{r.status}）"))
                                if r.status >= 400 and r.url.startswith(base) else None)
                        try:
                            page.goto(base + path, wait_until="load", timeout=PAGE_TIMEOUT_MS)
                            page.wait_for_timeout(300)  # 首屏内容 0.3 秒内就该看得见；更久才出现的空白对用户同样是问题
                            probe = page.evaluate(DOM_PROBE)
                            if width == 1280:
                                probe["img"] = page.evaluate(IMG_PROBE)
                        except Exception as e:  # 超时或崩溃也是一种报错
                            errors.append(f"浏览器·打不开：{path} → {str(e).splitlines()[0][:160]}")
                            page.close()
                            continue
                        page.close()
                        if width == 1280:
                            probes[path] = probe
                            for kind, msg in dict.fromkeys(seen):  # 去重
                                # 4xx 资源会同时触发控制台报错，只记加载失败那一条
                                if kind == "脚本报错" and "Failed to load resource" in msg:
                                    continue
                                errors.append(f"浏览器·{kind}：{path} → {msg[:200]}")
                        else:
                            if probe["overflow"] > 1:
                                errors.append(f"浏览器·横向溢出（{label} {width}px）：{path} → 内容比屏幕宽 {probe['overflow']}px")
                                if detail is not None:
                                    detail.setdefault("wide", {})[path] = probe.get("wide", [])
                            if width < 500:
                                if probe.get("lowContrast"):
                                    errors.append(f"浏览器·文字对比度不够：{path} → " + "；".join(
                                        f"“{x['text']}” {x['ratio']}:1（至少 {x['need']}:1）" for x in probe["lowContrast"]))
                                if probe.get("tapSmall"):
                                    errors.append(f"浏览器·点按区域太小（{label}）：{path} → " + "；".join(
                                        f"“{x['text']}” {x['w']}×{x['h']}px" for x in probe["tapSmall"]) + "（至少 24×24px）")
                                    if detail is not None:
                                        detail.setdefault("tap", {})[path] = probe["tapSmall"]
                                if probe.get("smallText"):
                                    errors.append(f"浏览器·字太小（{label}）：{path} → " + "；".join(
                                        f"“{x['text']}” {x['px']}px" for x in probe["smallText"]) + "（至少 12px）")
                    ctx.close()
            finally:
                browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
    served = set(pages)
    for path, pr in probes.items():
        if not pr["title"]:
            errors.append(f"浏览器·缺标题：{path}")
        for sec in dict.fromkeys(pr.get("hidden", [])):
            errors.append(f"浏览器·首屏内容看不见：{path} → 区块 {sec}（透明或隐藏，可能是动画没触发）")
        if not pr["lang"]:
            errors.append(f"浏览器·缺 lang：{path}")
        for src in dict.fromkeys((pr.get("img") or {}).get("broken", [])):
            errors.append(f"浏览器·图片打不开：{path} → {src}")
        for src in dict.fromkeys((pr.get("img") or {}).get("noSize", [])):
            errors.append(f"浏览器·图片没写宽高（加载时页面会跳）：{path} → {src}")
        for src in dict.fromkeys(pr["noAlt"]):
            errors.append(f"浏览器·图片缺替代文字：{path} → {src}")
        for name in dict.fromkeys(pr["noLabel"]):
            errors.append(f"浏览器·输入框没有标签：{path} → {name}")
        for h in dict.fromkeys(pr["links"]):
            if h.startswith(("http://", "https://", "mailto:", "tel:")):
                continue
            target, frag = urldefrag(urljoin(path, h))
            target = urlparse(target).path or path
            if target.endswith("/index.html"):  # 指向 index.html 就是指向这个目录（以前误报成死链：D20）
                target = target[: -len("index.html")]
            if not target.endswith("/") and target + "/" in served:
                target += "/"
            if target not in served:
                errors.append(f"浏览器·死链：{path} → {h}")
            elif frag and frag not in probes.get(target, {}).get("ids", []):
                errors.append(f"浏览器·锚点不存在：{path} → {h}")
    return errors


if __name__ == "__main__":
    errs = check(sys.argv[1])
    for e in errs:
        print(e)
    print(f"浏览器检查：{len(errs)} 个问题")
