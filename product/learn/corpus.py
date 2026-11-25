#!/usr/bin/env python3
"""设计语料库：批量“喂”网站设计。每喂一个，读成一条标本（specimen.py），去重后存进 corpus/specimens.jsonl。

能喂的东西：
  文件夹 / .html 文件     本地的网站或模板
  .zip                    只解出 html/css/scss，限制大小和数量，拒绝 ../ 和绝对路径
  GitHub 仓库地址         git clone --depth 1 到一次性的空目录：不跑安装、不跑脚本、不拉子模块、禁用钩子，读完就删
  网页地址 http(s)        只取 HTML 和它引用的同站 CSS；遵守 robots.txt；拒绝内网地址；限时限大小；不执行脚本
来源清单：一个文本文件，每行“地址或路径 [行业] [许可证]”，# 开头是注释。

存的只是数字和类别（见 specimen.py），公开仓库里也能放。每条都记来源，可以按来源撤回（remove）。
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.robotparser
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import events  # noqa: E402
import specimen  # noqa: E402

CORPUS = os.environ.get("AISITE_CORPUS") or os.path.join(HERE, "corpus")
ZIP_MAX_TOTAL = 60 * 1024 * 1024
ZIP_MAX_FILES = 4000
URL_MAX = 2 * 1024 * 1024
URL_CSS_MAX = 6
UA = "AISiteDesignNotes/1.0 (reads layout and colors only; no content kept)"
REPO = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def path() -> str:
    return os.path.join(CORPUS, "specimens.jsonl")


def load() -> list[dict]:
    try:
        with open(path(), encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]
    except OSError:
        return []


def _key(src: dict) -> str:
    return src.get("repo") or src.get("url") or src.get("name") or ""


def add(spec: dict) -> tuple[bool, str]:
    """去重：同一份内容（id）或同一个来源只收一次。"""
    have = load()
    if any(s["id"] == spec["id"] for s in have):
        return False, "内容和已有的一条重复"
    k = _key(spec["source"])
    if k and any(_key(s["source"]) == k for s in have):
        return False, "这个来源已经喂过"
    if not spec["structure"]["sections"] and not spec["color"]["n_colors"]:
        return False, "读不出版面和颜色"
    spec = dict(spec, at=time.strftime("%Y-%m-%d"))
    os.makedirs(CORPUS, exist_ok=True)
    with open(path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(spec, ensure_ascii=False, sort_keys=True) + "\n")
    return True, "收下"


def remove(match: str) -> int:
    have = load()
    keep = [s for s in have if match not in _key(s["source"]) and s["id"] != match]
    with open(path(), "w", encoding="utf-8") as f:
        for s in keep:
            f.write(json.dumps(s, ensure_ascii=False, sort_keys=True) + "\n")
    return len(have) - len(keep)


# ---------------------------------------------------------------- 各种来源
def _safe_unzip(zp: str, dst: str):
    total = 0
    with zipfile.ZipFile(zp) as z:
        infos = z.infolist()
        if len(infos) > ZIP_MAX_FILES * 4:
            raise ValueError("压缩包里文件太多")
        n = 0
        for i in infos:
            name = i.filename.replace("\\", "/")
            if i.is_dir() or name.startswith("/") or ".." in name.split("/") or not name.lower().endswith((".html", ".htm", ".css", ".scss")):
                continue
            total += i.file_size
            n += 1
            if total > ZIP_MAX_TOTAL or n > ZIP_MAX_FILES:
                raise ValueError("压缩包解开太大")
            out = os.path.join(dst, *name.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(i) as src, open(out, "wb") as f:
                shutil.copyfileobj(src, f, 1 << 16)


def _clone(url: str, dst: str, timeout: int = 120):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1", GIT_CONFIG_NOSYSTEM="1")
    cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=never", "clone", "-q", "--depth", "1",
           "--no-recurse-submodules", "--single-branch", url, dst]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err = (r.stderr.strip().splitlines() or ["?"])[-1]
        raise ValueError("仓库不存在或不公开" if "could not read Username" in err or "not found" in err.lower() else "拉取失败：" + err[:120])


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


class _NoRedirectToPrivate(urllib.request.HTTPRedirectHandler):
    allow_private = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlparse(newurl)
        if u.scheme not in ("http", "https") or (not self.allow_private and not _public_host(u.hostname or "")):
            raise ValueError("跳转到了不允许的地址")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, limit: int, allow_private: bool = False, timeout: int = 15) -> tuple[str, str]:
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("只收 http/https 网址")
    if not allow_private and not _public_host(u.hostname):
        raise ValueError("不抓内网或本机地址")
    h = _NoRedirectToPrivate()
    h.allow_private = allow_private
    opener = urllib.request.build_opener(h)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,text/css;q=0.9,*/*;q=0.1"})
    with opener.open(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("网页太大")
    m = re.search(r"charset=([\w-]+)", ctype)
    return data.decode(m.group(1) if m else "utf-8", "replace"), ctype


def _robots_ok(url: str, allow_private: bool) -> bool:
    u = urllib.parse.urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    try:
        txt, _ = _get(f"{u.scheme}://{u.netloc}/robots.txt", 256 * 1024, allow_private, timeout=8)
        rp.parse(txt.splitlines())
    except Exception:
        return True  # 没有 robots.txt：默认允许
    return rp.can_fetch(UA, url)


def fetch_url(url: str, dst: str, allow_private: bool = False, pause: float = 1.0) -> str:
    """把一个网页（和它的同站 CSS）存成本地文件，交给 specimen 读。返回本地 html 路径。"""
    if not _robots_ok(url, allow_private):
        raise ValueError("网站的 robots.txt 不允许抓取")
    doc, ctype = _get(url, URL_MAX, allow_private)
    if "html" not in ctype and "<html" not in doc[:2000].lower():
        raise ValueError("不是网页")
    host = urllib.parse.urlparse(url).netloc
    os.makedirs(dst, exist_ok=True)
    n = 0
    def local(m):
        nonlocal n
        tag = m.group(0)
        hm = re.search(r"href=[\"']([^\"']+)", tag)
        if not hm or n >= URL_CSS_MAX:
            return tag
        full = urllib.parse.urljoin(url, hm.group(1))
        fu = urllib.parse.urlparse(full)
        if fu.netloc != host and not fu.netloc.endswith("." + host.split(":")[0].split(".", 1)[-1]):
            return tag  # 只取同站（含子域）的 CSS，不去追第三方
        try:
            time.sleep(pause)
            css, _ = _get(full, URL_MAX, allow_private)
        except Exception:
            return tag
        n += 1
        name = f"s{n}.css"
        with open(os.path.join(dst, name), "w", encoding="utf-8") as f:
            f.write(css)
        return f'<link rel="stylesheet" href="{name}">'
    doc = re.sub(r"<link[^>]+rel=[\"']?stylesheet[^>]*>", local, doc, flags=re.I)
    p = os.path.join(dst, "index.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(doc)
    return p


def feed_one(item: str, industry: str | None = None, license_: str | None = None, allow_private: bool = False) -> dict:
    """喂一样东西。返回 {"ok", "why", "spec"?}。所有临时文件都放在一次性目录，结束就删。"""
    tmp = tempfile.mkdtemp(prefix="feed-design-")
    src: dict = {}
    try:
        with events.stage("feed", 来源=item[:80]) as st:
            m = REPO.match(item)
            if m:
                src = {"kind": "repo", "repo": f"https://github.com/{m.group(1)}/{m.group(2)}", "hints": [m.group(2).replace("-", " ")]}
                _clone(src["repo"], os.path.join(tmp, "r"))
                target = os.path.join(tmp, "r")
                lic = next((f for f in os.listdir(target) if f.upper().startswith(("LICENSE", "LICENCE", "COPYING"))), None)
                if lic and not license_:
                    head = open(os.path.join(target, lic), encoding="utf-8", errors="replace").read(400)
                    license_ = next((n for w, n in (("MIT", "MIT"), ("Apache", "Apache-2.0"), ("GNU GENERAL PUBLIC", "GPL"),
                                                    ("BSD", "BSD"), ("Creative Commons", "CC"), ("ISC", "ISC")) if w in head), "其他")
            elif re.match(r"https?://", item):
                src = {"kind": "url", "url": item, "hints": []}
                target = fetch_url(item, os.path.join(tmp, "u"), allow_private=allow_private)
            elif item.lower().endswith(".zip") and os.path.isfile(item):
                src = {"kind": "zip", "name": os.path.basename(item), "hints": [os.path.basename(item)[:-4].replace("-", " ")]}
                _safe_unzip(item, os.path.join(tmp, "z"))
                target = os.path.join(tmp, "z")
            elif os.path.exists(item):
                src = {"kind": "file", "name": os.path.basename(os.path.abspath(item)), "hints": [os.path.basename(os.path.abspath(item)).replace("-", " ")]}
                target = item
            else:
                raise ValueError("认不出来：不是文件、文件夹、压缩包、GitHub 仓库或网址")
            if license_:
                src["license"] = license_
            spec = specimen.from_path(target, src, industry)
            if not spec:
                raise ValueError("里面没找到网页")
            ok, why = add(spec)
            st.out(收下=ok, 行业=spec["industry"] or "", 家族=spec["family"], 区块=len(spec["structure"]["sections"]))
        events.emit("feed.specimen" if ok else "feed.skip", 来源=_key(spec["source"])[-60:], why=why, 行业=spec["industry"] or "",
                    家族=spec["family"], sections=spec["structure"]["sections"][:8], accent=spec["color"]["accent"] or "")
        return {"ok": ok, "why": why, "spec": spec}
    except (ValueError, OSError, subprocess.TimeoutExpired, zipfile.BadZipFile, UnicodeError) as e:
        events.emit("feed.skip", 来源=item[-60:], why=str(e)[:60])
        return {"ok": False, "why": str(e)[:160]}
    except Exception as e:  # 读某个网站时自己的代码出错：记下来（待修），不让一个坏样本打断整批
        why = f"读取时出错（{type(e).__name__}），已记进待修"
        events.emit("feed.skip", 来源=item[-60:], why=why)
        try:
            with open(os.path.join(CORPUS, "errors.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "item": item[:200], "error": f"{type(e).__name__}: {e}"[:300]}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return {"ok": False, "why": why}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def read_list(p: str) -> list[tuple[str, str | None, str | None]]:
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        out.append((parts[0], parts[1] if len(parts) > 1 and parts[1] != "-" else None, parts[2] if len(parts) > 2 else None))
    return out


def feed_many(items, pause: float = 0.5) -> dict:
    got, skipped = [], []
    with events.run("feed", 数量=len(items)) as _rid:
        for it, ind, lic in items:
            r = feed_one(it, ind, lic)
            (got if r["ok"] else skipped).append((it, r["why"]))
            time.sleep(pause)
    return {"got": got, "skipped": skipped}


def refresh() -> dict:
    """提取器改进以后，把语料库里每个来源重读一遍（自我纠错：旧的读法错了，结论跟着改）。拉不到的保留旧记录。"""
    old = load()
    if not old:
        return {"redone": 0, "kept": 0}
    bak = path() + ".bak"
    shutil.copy(path(), bak)
    os.replace(path(), path() + ".old")
    redone, kept = 0, []
    with events.run("refresh", 数量=len(old)):
        for s in old:
            src = s["source"]
            item = src.get("repo") or src.get("url")
            r = feed_one(item, s.get("industry") if s.get("industry_why") == "喂的时候标注" else None, src.get("license")) if item else {"ok": False}
            if r.get("ok"):
                redone += 1
            else:
                kept.append(s)
            time.sleep(0.3)
    with open(path(), "a", encoding="utf-8") as f:
        for s in kept:
            f.write(json.dumps(s, ensure_ascii=False, sort_keys=True) + "\n")
    os.remove(path() + ".old")
    return {"redone": redone, "kept": len(kept)}


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="feed-design", description="喂网站设计给大脑（只读版面和颜色，不运行、不留原文）")
    ap.add_argument("items", nargs="*", help="文件夹、.html、.zip、GitHub 仓库地址或网址")
    ap.add_argument("--for", dest="industry", help="行业（英文类型名，如 Bakery/Cafe）；不填就自己猜")
    ap.add_argument("--list", help="来源清单文件")
    ap.add_argument("--remove", help="按来源（或标本编号）撤回")
    ap.add_argument("--refresh", action="store_true", help="提取器改进后，把所有来源重读一遍")
    a = ap.parse_args(argv)
    if a.refresh:
        r = refresh()
        print(f"重读：更新 {r['redone']} 个，保留旧记录 {r['kept']} 个，语料库现有 {len(load())} 个")
        return 0
    if a.remove:
        print(f"撤回了 {remove(a.remove)} 条")
        return 0
    items = [(x, a.industry, None) for x in a.items] + (read_list(a.list) if a.list else [])
    if not items:
        ap.print_help()
        return 1
    r = feed_many(items)
    for it, why in r["got"]:
        print(f"收下  {it}")
    for it, why in r["skipped"]:
        print(f"跳过  {it}：{why}")
    print(f"喂设计：收下 {len(r['got'])} 个，跳过 {len(r['skipped'])} 个，语料库现有 {len(load())} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
