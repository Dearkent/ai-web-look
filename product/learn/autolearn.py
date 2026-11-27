#!/usr/bin/env python3
"""自动上网学习：自己找网站设计来喂，喂完提炼规律、试跑，过了才用。

每跑一次：
  1. 看哪些行业“样本不够”，优先给它们找（缺口优先）。
  2. 找来源：GitHub 公开仓库搜索（按行业关键词，每次往后翻一页）＋ 头部网站清单 ＋ 你自己的清单。
  3. 一个个喂（corpus.feed_one：只读版面和颜色，不运行代码、不留原文；遵守 robots.txt；不碰内网地址）。
  4. 有新标本就重算规律（priors build），有新“候选”就试跑（priors trial）；指纹没变的不重复试跑。

防死循环、防失控：
  - 每次最多收 N 个新标本、最多尝试 M 个、最多跑 T 分钟；连续失败 K 次就停（guard.stop）。
  - 试过的来源记在 corpus/autolearn_state.json：成功的不再拉；失败的最多再试 1 次，且隔 7 天以上。
  - 同一时间只跑一个（锁文件）；GitHub 限流就停，不硬撞。
  - 每一步都写事件，实况页（/live）上能看着它学。

用法：
  python3 brain.py autolearn                  # 跑一次（默认：最多收 12 个，尝试 30 个，20 分钟）
  python3 brain.py autolearn --dry-run        # 只列出这次会去喂什么，不真喂
  python3 brain.py autolearn --max-new 5 --minutes 10
  python3 brain.py autolearn --install-schedule [--at 03:17]   # Mac：每天定时自动跑（launchd）
  python3 brain.py autolearn --uninstall-schedule

可选环境变量：GITHUB_TOKEN（只读令牌，提高搜索限额；只从环境读，不存盘）、AISITE_GH_API（测试用）。
"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import corpus  # noqa: E402
import events  # noqa: E402
import priors  # noqa: E402

GH_API = os.environ.get("AISITE_GH_API", "https://api.github.com")
UA = "AISiteDesignNotes/1.0 (+https://github.com/Dearkent/ai-web-look; reads layout and colors only)"
RETRY_AFTER_DAYS = 7
MAX_TRIES = 2
REPO_MAX_KB = 40 * 1024  # 超过 40MB 的仓库不拉

# 行业 → GitHub 搜索词（英文，开源模板多用英文命名）。缺口行业会优先搜。
QUERIES = {
    "Bakery/Cafe": ["coffee shop website template", "bakery website html"],
    "Restaurant/Food Service": ["restaurant website template", "food landing page html"],
    "Dental Practice": ["dental clinic website template", "dentist website html"],
    "Medical Clinic": ["medical clinic website template", "hospital website html", "doctor appointment landing page"],
    "Legal Services": ["law firm website template", "lawyer website html"],
    "SaaS (General)": ["saas landing page template", "startup landing page html"],
    "Portfolio/Personal": ["portfolio website template html", "personal website template"],
    "Creative Agency": ["agency website template", "creative studio website html"],
    "E-commerce": ["ecommerce website template html", "online shop landing page"],
    "Magazine/Blog": ["blog website template html", "magazine website template"],
    "B2B Service": ["consulting website template", "business services website html"],
    "Online Course/E-learning": ["online course website template", "elearning landing page html"],
    "Construction/Architecture": ["construction company website template", "architecture firm website html"],
    "Conference / Symposium Landing Page": ["conference website template", "event landing page html"],
    "Open Source Project Landing": ["open source project landing page", "documentation landing page template"],
}

# 头部网站：只静态读首页（很多头部站靠脚本渲染，静态读不到版面就跳过；浏览器读法见 dom_probe.js）。
HEADS_FILE = os.path.join(HERE, "sources", "heads.tsv")
USER_LISTS = [os.path.join(HERE, "sources", "my_list.tsv"), os.path.expanduser("~/.aisite/learn_list.txt")]


# ---------------------------------------------------------------- 状态
def _state_path() -> str:
    return os.path.join(corpus.CORPUS, "autolearn_state.json")


def load_state() -> dict:
    try:
        with open(_state_path(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("seen", {})
    d.setdefault("pages", {})
    d.setdefault("runs", [])
    return d


def save_state(d: dict):
    os.makedirs(corpus.CORPUS, exist_ok=True)
    d["runs"] = d["runs"][-30:]
    tmp = _state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, _state_path())


def _due(seen: dict, item: str, now: float) -> bool:
    s = seen.get(item)
    if not s:
        return True
    if s.get("ok"):
        return False
    return s.get("tries", 1) < MAX_TRIES and now - s.get("t", 0) > RETRY_AFTER_DAYS * 86400


# ---------------------------------------------------------------- 锁
def _lock_path() -> str:
    return os.path.join(corpus.CORPUS, ".autolearn.lock")


def take_lock(stale_s: int = 3 * 3600) -> bool:
    os.makedirs(corpus.CORPUS, exist_ok=True)
    p = _lock_path()
    try:
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < stale_s:
            pid = int(open(p).read().strip() or 0)
            try:
                os.kill(pid, 0)
                return False  # 还有一个在跑
            except (OSError, ValueError):
                pass  # 进程不在了：旧锁作废
        with open(p, "w") as f:
            f.write(str(os.getpid()))
        return True
    except OSError:
        return False


def drop_lock():
    try:
        os.remove(_lock_path())
    except OSError:
        pass


# ---------------------------------------------------------------- 网络（证书兜底：Mac 上 python.org 版常缺证书）
def _fallback_cafile() -> str | None:
    """系统证书能用就用系统的；缺证书时（Mac 上 python.org 版常见）才找 certifi 或系统自带的 cert.pem。"""
    if os.environ.get("SSL_CERT_FILE") or ssl.create_default_context().get_ca_certs():
        return None
    try:
        import certifi  # type: ignore
        return certifi.where()
    except Exception:
        pass
    return "/etc/ssl/cert.pem" if os.path.exists("/etc/ssl/cert.pem") else None


def _ssl_ctx():
    f = _fallback_cafile()
    return ssl.create_default_context(cafile=f) if f else ssl.create_default_context()


def fix_certs():
    """让 corpus 里的 urllib 也能验证证书（只在缺证书时补上，从不关闭验证）。"""
    f = _fallback_cafile()
    if f:
        os.environ["SSL_CERT_FILE"] = f


class RateLimited(Exception):
    pass


def gh_search(q: str, page: int, per_page: int = 10, timeout: int = 20) -> list[dict]:
    """GitHub 仓库搜索。只要 HTML/CSS 的、非 fork、不太大的。返回 [{repo, stars, license}]。"""
    query = f"{q} in:name,description,topics fork:false stars:>=3 size:<{REPO_MAX_KB}"
    url = f"{GH_API}/search/repositories?" + urllib.parse.urlencode(
        {"q": query, "sort": "stars", "order": "desc", "per_page": per_page, "page": page})
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        h["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(url, headers=h)
    ctx = _ssl_ctx() if url.startswith("https:") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            d = json.loads(r.read(2 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise RateLimited("GitHub 搜索限流了（可设 GITHUB_TOKEN 提高额度），这次先停")
        raise ValueError(f"GitHub 搜索出错（{e.code}）")
    out = []
    for it in d.get("items", []):
        lang = (it.get("language") or "").lower()
        if it.get("fork") or it.get("archived") or lang not in ("html", "css", "scss", "javascript", ""):
            continue
        if (it.get("size") or 0) > REPO_MAX_KB:
            continue
        full = it.get("full_name", "")
        if not re.match(r"^[\w.-]+/[\w.-]+$", full):
            continue
        lic = ((it.get("license") or {}).get("spdx_id") or "")
        out.append({"repo": f"https://github.com/{full}", "stars": it.get("stargazers_count", 0),
                    "license": lic if lic and lic != "NOASSERTION" else None})
    return out


# ---------------------------------------------------------------- 选题
def gaps() -> list[tuple[str, int]]:
    """各行业现有标本数，少的排前面（只算有搜索词的行业）。"""
    n = {}
    for s in corpus.load():
        if s.get("industry"):
            n[s["industry"]] = n.get(s["industry"], 0) + 1
    return sorted(((ind, n.get(ind, 0)) for ind in QUERIES), key=lambda x: (x[1] >= priors.MIN_N, x[1], x[0]))


def _read_lists(paths) -> list[tuple[str, str | None, str | None, str]]:
    out = []
    for p in paths:
        if os.path.isfile(p):
            try:
                out += [(it, ind, lic, os.path.basename(p)) for it, ind, lic in corpus.read_list(p)]
            except (OSError, UnicodeError):
                pass
    return out


def plan(state: dict, max_try: int, search=gh_search, per_industry: int = 4, searches: int = 6) -> tuple[list[dict], list[str]]:
    """排出这次要喂的东西。返回 (清单, 备注)。清单每项 {item, industry, license, from}。"""
    now = time.time()
    known = {corpus._key(s["source"]) for s in corpus.load()}
    seen = state["seen"]
    todo, notes, picked = [], [], set()

    def push(item, ind, lic, frm):
        if item in picked or item in known or not _due(seen, item, now):
            return False
        picked.add(item)
        todo.append({"item": item, "industry": ind, "license": lic, "from": frm})
        return True

    # 1) 你自己的清单最优先，2) 头部网站
    for it, ind, lic, frm in _read_lists(USER_LISTS) + _read_lists([HEADS_FILE]):
        push(it, ind, lic, frm)
    # 上次失败、已经隔够 7 天、还没试满的，再给一次机会
    for it, v in sorted(seen.items(), key=lambda kv: kv[1].get("t", 0)):
        if not v.get("ok"):
            push(it, v.get("ind"), v.get("lic"), "重试：" + v.get("from", "")[:40])
    # 3) 缺口行业去 GitHub 搜，每个词每次往后翻一页
    done_search = 0
    for ind, have in gaps():
        if len(todo) >= max_try or done_search >= searches:
            break
        if have >= priors.MIN_N * 3:
            continue  # 已经够多了，不再搜
        got = 0
        for q in QUERIES[ind]:
            if got >= per_industry or done_search >= searches:
                break
            page = state["pages"].get(q, 0) + 1
            if page > 10:
                continue  # 这个词翻得够深了
            try:
                hits = search(q, page)
                done_search += 1
            except RateLimited as e:
                notes.append(str(e))
                events.emit("guard.stop", why=str(e)[:60])
                return todo[:max_try], notes
            except (ValueError, OSError) as e:
                notes.append(f"搜“{q}”失败：{str(e)[:60]}")
                done_search += 1
                continue
            state["pages"][q] = page if hits else 99  # 搜空了就别再翻这个词
            for h in hits:
                if got < per_industry and push(h["repo"], ind, h["license"], f"GitHub 搜索：{q}"):
                    got += 1
        notes.append(f"{ind}：已有 {have} 个，这次排了 {got} 个")
    return interleave(todo)[:max_try], notes


def interleave(todo: list[dict]) -> list[dict]:
    """自己的清单永远最先；其余按来源轮流排（头部网站、各搜索词交替），一类来源全坏也不会挡住别的。"""
    mine = [t for t in todo if t["from"] in [os.path.basename(p) for p in USER_LISTS]]
    groups: dict[str, list[dict]] = {}
    for t in todo:
        if t not in mine:
            groups.setdefault(t["from"].split("：")[0] if t["from"].startswith("重试") else t["from"], []).append(t)
    out = list(mine)
    while any(groups.values()):
        for k in list(groups):
            if groups[k]:
                out.append(groups[k].pop(0))
    return out


# ---------------------------------------------------------------- 一次
ENV_WORDS = ("内网", "超时", "timed out", "urlopen error", "Name or service", "nodename", "Connection", "网络", "拉取失败：fatal: unable to access")


def env_failure(why: str) -> bool:
    return any(w in why for w in ENV_WORDS)


def run_once(max_new: int = 12, max_try: int = 30, minutes: float = 20, fail_stop: int = 6, pause: float = 1.0,
             dry_run: bool = False, do_trial: bool = True, run_browser: bool | None = None,
             feeder=None, search=gh_search, allow_private: bool = False) -> dict:
    feeder = feeder or (lambda it, ind, lic: corpus.feed_one(it, ind, lic, allow_private=allow_private))
    if not take_lock():
        return {"ok": False, "why": "已经有一个自动学习在跑了"}
    t0 = time.time()
    state = load_state()
    res = {"ok": True, "got": [], "skipped": [], "notes": [], "stopped": "", "priors": {}, "trial": {}}
    try:
        with events.run("autolearn", 最多收=max_new, 最多试=max_try, 分钟=minutes):
            with events.stage("plan") as st:
                todo, notes = plan(state, max_try, search=search)
                res["notes"] += notes
                st.out(排了=len(todo))
            res["plan"] = todo
            if dry_run:
                save_state(state)
                return res
            fails = 0
            for t in todo:
                if len(res["got"]) >= max_new:
                    res["stopped"] = f"这次已收满 {max_new} 个"
                    break
                if time.time() - t0 > minutes * 60:
                    res["stopped"] = f"到了 {minutes:g} 分钟上限"
                    break
                if fails >= fail_stop:
                    res["stopped"] = f"连续失败 {fails} 次，先停下（可能断网或被限流）"
                    events.emit("guard.stop", why=res["stopped"][:60])
                    break
                r = feeder(t["item"], t["industry"], t["license"])
                why = str(r.get("why", ""))
                if not r.get("ok") and env_failure(why):
                    # 断网、域名解析不对、超时：是这边环境的问题，不记在来源头上（不占重试次数）
                    res["skipped"].append((t["item"], why[:80]))
                    fails += 1
                    time.sleep(pause)
                    continue
                prev = state["seen"].get(t["item"], {})
                state["seen"][t["item"]] = {"ok": bool(r.get("ok")), "why": str(r.get("why", ""))[:80], "t": time.time(),
                                            "tries": prev.get("tries", 0) + 1, "from": t["from"][:60],
                                            "ind": t["industry"], "lic": t["license"]}
                if r.get("ok"):
                    res["got"].append((t["item"], t["industry"] or ""))
                    fails = 0
                else:
                    res["skipped"].append((t["item"], str(r.get("why", ""))[:80]))
                    # “已经有了/重复”不算失败，网络错误才算
                    why = str(r.get("why", ""))
                    fails = fails if any(w in why for w in ("重复", "已经喂过", "robots", "没找到网页", "读不出")) else fails + 1
                save_state(state)  # 每喂一个就存：中途被杀也不会重复拉
                time.sleep(pause)
            if res["got"]:
                with events.stage("distill") as st:
                    d = priors.build()
                    cand = [k for k, v in d["industries"].items() if v["status"] == "候选"]
                    res["priors"] = {k: v["status"] for k, v in d["industries"].items()}
                    st.out(候选=len(cand))
                if do_trial and cand:
                    if run_browser is None:
                        try:
                            import playwright  # noqa: F401
                            run_browser = True
                        except ImportError:
                            run_browser = False
                    res["trial"] = priors.trial(run_browser=run_browser)
            res["minutes"] = round((time.time() - t0) / 60, 1)
            state["runs"].append({"at": time.strftime("%Y-%m-%d %H:%M"), "got": len(res["got"]), "skipped": len(res["skipped"]),
                                  "stopped": res["stopped"], "trial": res["trial"]})
            save_state(state)
            events.emit("note", 自动学习=f"收下 {len(res['got'])} 个，跳过 {len(res['skipped'])} 个" + (f"；{res['stopped']}" if res["stopped"] else ""))
    finally:
        drop_lock()
    return res


# ---------------------------------------------------------------- Mac 定时
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.aisite.autolearn.plist")


def install_schedule(at: str = "03:17") -> str:
    if sys.platform != "darwin":
        return "定时只做了 Mac 版（launchd）。其他系统可以用 cron 每天跑：python3 brain.py autolearn"
    m = re.match(r"^(\d{1,2}):(\d{2})$", at)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return "时间格式是 时:分，比如 03:17"
    brain = os.path.abspath(os.path.join(HERE, "..", ".."))
    log = os.path.expanduser("~/.aisite/autolearn.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    from xml.sax.saxutils import escape as x
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>Label</key><string>com.aisite.autolearn</string>
 <key>ProgramArguments</key><array><string>{x(sys.executable)}</string><string>{x(os.path.join(brain, 'brain.py'))}</string><string>autolearn</string></array>
 <key>WorkingDirectory</key><string>{x(brain)}</string>
 <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{int(m.group(1))}</integer><key>Minute</key><integer>{int(m.group(2))}</integer></dict>
 <key>StandardOutPath</key><string>{x(log)}</string><key>StandardErrorPath</key><string>{x(log)}</string>
 <key>LowPriorityIO</key><true/><key>Nice</key><integer>10</integer>
</dict></plist>
"""
    with open(PLIST, "w", encoding="utf-8") as f:
        f.write(body)
    import subprocess
    subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    r = subprocess.run(["launchctl", "load", PLIST], capture_output=True, text=True)
    if r.returncode != 0:
        return "写好了定时文件，但 launchctl 加载失败：" + (r.stderr.strip()[:120] or "?")
    return f"好了：每天 {at} 自动学习一次（电脑要开着）。记录在 {log}。关掉：python3 brain.py autolearn --uninstall-schedule"


def uninstall_schedule() -> str:
    if not os.path.exists(PLIST):
        return "没有装定时。"
    import subprocess
    subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    os.remove(PLIST)
    return "已关掉每日自动学习。"


# ---------------------------------------------------------------- 命令行
def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="autolearn", description="自动上网找网站设计来学（只读版面和颜色）")
    ap.add_argument("--max-new", type=int, default=12, help="这次最多收几个新标本")
    ap.add_argument("--max-try", type=int, default=30, help="这次最多尝试几个来源")
    ap.add_argument("--minutes", type=float, default=20, help="最多跑几分钟")
    ap.add_argument("--dry-run", action="store_true", help="只列出会喂什么，不真喂")
    ap.add_argument("--no-trial", action="store_true", help="喂完不试跑")
    ap.add_argument("--install-schedule", action="store_true", help="Mac：每天定时自动跑")
    ap.add_argument("--at", default="03:17", help="定时时间，时:分")
    ap.add_argument("--uninstall-schedule", action="store_true")
    ap.add_argument("--status", action="store_true", help="看最近几次自动学习的结果")
    a = ap.parse_args(argv)
    if a.install_schedule:
        print(install_schedule(a.at))
        return 0
    if a.uninstall_schedule:
        print(uninstall_schedule())
        return 0
    if a.status:
        st = load_state()
        ok = sum(1 for v in st["seen"].values() if v.get("ok"))
        print(f"试过 {len(st['seen'])} 个来源，收下 {ok} 个。")
        for r in st["runs"][-8:]:
            print(f"  {r['at']}  收 {r['got']}  跳 {r['skipped']}  {r.get('stopped', '')}  {r.get('trial') or ''}")
        print("行业缺口：" + "，".join(f"{i} {n}" for i, n in gaps() if n < priors.MIN_N) or "无")
        return 0
    fix_certs()
    r = run_once(a.max_new, a.max_try, a.minutes, dry_run=a.dry_run, do_trial=not a.no_trial)
    if not r["ok"]:
        print(r["why"])
        return 1
    for n in r["notes"]:
        print("· " + n)
    if a.dry_run:
        for t in r["plan"]:
            print(f"  会喂：{t['item']}  [{t['industry'] or '自己猜'}]  来自 {t['from']}")
        return 0
    print(f"收下 {len(r['got'])} 个，跳过 {len(r['skipped'])} 个" + (f"（{r['stopped']}）" if r["stopped"] else "") + f"，用了 {r.get('minutes', 0)} 分钟。")
    for it, ind in r["got"]:
        print(f"  + {it}  {ind}")
    for it, why in r["skipped"][:10]:
        print(f"  - {it}  {why}")
    if r["trial"]:
        print("试跑：" + "，".join(f"{k} {v}" for k, v in r["trial"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
