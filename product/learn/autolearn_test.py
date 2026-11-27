#!/usr/bin/env python3
"""自动上网学习的测试：假 GitHub 搜索接口 + 假网站，全在本机，不上网。"""
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time

TMP = tempfile.mkdtemp(prefix="autolearn-test-")
os.environ["AISITE_CORPUS"] = os.path.join(TMP, "corpus")
os.environ["AISITE_EVENTS"] = os.path.join(TMP, "events.jsonl")
os.environ["AISITE_PRIORS_FILE"] = os.path.join(TMP, "priors.json")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("通过 " if cond else "失败 ") + name + ("" if cond else f"  ← {detail}"))


SITE = """<!doctype html><html><head><title>Clinic</title><link rel="stylesheet" href="/s.css"></head><body>
<header><nav><a href="#">Home</a></nav></header>
<section class="hero"><h1>Care close to home</h1><a class="btn" href="#book">Book</a></section>
<section class="services"><h2>Services</h2><div class="card">A</div><div class="card">B</div><div class="card">C</div></section>
<section class="testimonials"><h2>Patients</h2><blockquote>x</blockquote></section>
<section class="contact"><h2>Contact</h2><form><input></form></section>
<footer>f</footer></body></html>"""
CSS = "body{font-family:Inter,sans-serif;color:#1f2937;background:#ffffff}.btn{background:#0e7490;color:#fff;border-radius:8px}h1{font-size:48px}"
HITS = {"calls": [], "mode": "ok"}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/search/repositories"):
            HITS["calls"].append(self.path)
            if HITS["mode"] == "limit":
                self.send_response(403); self.end_headers(); return
            items = [
                {"full_name": "good/clinic-a", "language": "HTML", "size": 900, "stargazers_count": 50, "license": {"spdx_id": "MIT"}},
                {"full_name": "good/clinic-b", "language": "CSS", "size": 400, "stargazers_count": 20, "license": None},
                {"full_name": "fork/x", "language": "HTML", "size": 10, "fork": True},
                {"full_name": "big/y", "language": "HTML", "size": 999999},
                {"full_name": "py/z", "language": "Python", "size": 10},
                {"full_name": "bad/../evil", "language": "HTML", "size": 10},
            ]
            b = json.dumps({"items": items}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
        elif self.path == "/robots.txt":
            self.send_response(404); self.end_headers()
        elif self.path == "/s.css":
            self.send_response(200); self.send_header("Content-Type", "text/css"); self.end_headers(); self.wfile.write(CSS.encode())
        else:
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(SITE.encode())


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
os.environ["AISITE_GH_API"] = BASE

import autolearn as A  # noqa: E402
import corpus  # noqa: E402

# 不让真实的清单文件混进来
A.USER_LISTS = [os.path.join(TMP, "my_list.tsv")]
A.HEADS_FILE = os.path.join(TMP, "heads.tsv")
open(A.HEADS_FILE, "w").write("")


def reset():
    shutil.rmtree(os.environ["AISITE_CORPUS"], ignore_errors=True)
    HITS["calls"].clear()
    HITS["mode"] = "ok"


def fake_search(q, page):
    return [{"repo": f"https://github.com/t/{q.replace(' ', '-')}-{page}-{i}", "stars": 1, "license": None} for i in range(3)]


def feeder_ok(calls):
    def f(it, ind, lic):
        calls.append(it)
        return {"ok": True, "why": "收下"}
    return f


def main():
    # 1 真的搜索接口：过滤 fork、太大、非网页语言、怪名字；读许可证
    reset()
    hits = A.gh_search("clinic website", 1)
    names = [h["repo"] for h in hits]
    check("搜索：只留网页类、非 fork、不太大的仓库", names == ["https://github.com/good/clinic-a", "https://github.com/good/clinic-b"], names)
    check("搜索：许可证读出来，没有的记空", hits[0]["license"] == "MIT" and hits[1]["license"] is None, hits)
    check("搜索：请求里带了 fork:false 和大小限制", "fork%3Afalse" in HITS["calls"][0] and "size%3A%3C" in HITS["calls"][0] and "stars%3A%3E%3D3" in HITS["calls"][0], HITS["calls"][:1])

    # 2 缺口优先
    order = [i for i, _ in A.gaps()]
    check("选题：空语料时每个行业都是缺口", len(order) == len(A.QUERIES), order)

    # 3 只列不喂
    reset()
    calls = []
    r = A.run_once(dry_run=True, feeder=feeder_ok(calls), search=fake_search, pause=0)
    check("试列：排出了清单但一个都没喂", r["ok"] and len(r["plan"]) > 0 and calls == [], (len(r["plan"]), calls))
    check("试列：一次搜索次数有上限（6 次）", len({t['from'] for t in r["plan"]}) <= 6, {t['from'] for t in r["plan"]})

    # 4 自己的清单排在最前
    reset()
    open(A.USER_LISTS[0], "w").write("https://example.org/mine\tLegal Services\n")
    r = A.run_once(dry_run=True, feeder=feeder_ok([]), search=fake_search, pause=0)
    check("选题：你自己的清单排第一", r["plan"][0]["item"] == "https://example.org/mine" and r["plan"][0]["industry"] == "Legal Services", r["plan"][:1])
    os.remove(A.USER_LISTS[0])
    open(A.HEADS_FILE, "w").write("".join(f"https://head{i}.example/\tBakery/Cafe\n" for i in range(8)))
    r = A.run_once(dry_run=True, feeder=feeder_ok([]), search=fake_search, pause=0)
    open(A.HEADS_FILE, "w").write("")
    check("选题：各类来源轮流排，头部网站不会全堆在前面", "head" not in r["plan"][1]["item"] and "head" in r["plan"][0]["item"], [t["item"] for t in r["plan"][:3]])

    # 5 收满就停
    reset()
    calls = []
    r = A.run_once(max_new=3, feeder=feeder_ok(calls), search=fake_search, pause=0, do_trial=False)
    check("上限：最多收 3 个就停", len(r["got"]) == 3 and len(calls) == 3 and "收满" in r["stopped"], (len(r["got"]), r["stopped"]))

    # 6 再跑一次：成功过的不再拉，搜索往后翻页
    calls2 = []
    r2 = A.run_once(max_new=3, feeder=feeder_ok(calls2), search=fake_search, pause=0, do_trial=False)
    check("不重复：上次收下的这次不再拉", not set(calls) & set(calls2) and len(calls2) == 3, (calls, calls2))
    st = A.load_state()
    check("翻页：同一个搜索词这次翻到了第 2 页", any(v == 2 for v in st["pages"].values()), st["pages"])

    # 7 连续失败就停（防死循环）
    reset()
    calls = []

    def bad(it, ind, lic):
        calls.append(it)
        return {"ok": False, "why": "仓库不存在或不公开"}
    r = A.run_once(max_new=10, fail_stop=4, feeder=bad, search=fake_search, pause=0)
    check("防失控：连续失败 4 次就停下", len(calls) == 4 and "连续失败" in r["stopped"], (len(calls), r["stopped"]))
    ev = open(os.environ["AISITE_EVENTS"], encoding="utf-8").read()
    check("防失控：停下时发了 guard.stop 事件（实况页能看到）", '"guard.stop"' in ev)

    # 8 失败的来源：不马上重试；隔 7 天后最多再试 1 次
    calls = []
    A.run_once(max_new=10, fail_stop=99, max_try=4, feeder=bad, search=lambda q, p: [], pause=0)
    st = A.load_state()
    failed = [k for k, v in st["seen"].items() if not v["ok"]]
    check("重试：刚失败的这次不重试", calls == [] and len(failed) == 4, (calls, failed))
    for k in failed:
        st["seen"][k]["t"] -= 8 * 86400
    A.save_state(st)
    A.run_once(max_new=10, fail_stop=99, max_try=10, feeder=bad, search=lambda q, p: [], pause=0)
    retried = list(calls)
    st = A.load_state()
    for k in failed:
        st["seen"][k]["t"] -= 8 * 86400
    A.save_state(st)
    calls.clear()
    A.run_once(max_new=10, fail_stop=99, max_try=10, feeder=bad, search=lambda q, p: [], pause=0)
    check("重试：隔 7 天再试一次，试满 2 次就不再碰", sorted(retried) == sorted(failed) and calls == [], (retried, calls))

    # 8b 环境问题（断网、内网解析）不记在来源头上
    reset()

    def offline(it, ind, lic):
        return {"ok": False, "why": "不抓内网或本机地址"}
    r = A.run_once(max_new=10, max_try=5, fail_stop=3, feeder=offline, search=fake_search, pause=0)
    check("环境问题：照样算连续失败（会停），但不记成来源坏了", "连续失败" in r["stopped"] and not A.load_state()["seen"], (r["stopped"], A.load_state()["seen"]))

    # 9 重复/已喂过不算失败
    reset()
    n = {"i": 0}

    def dup(it, ind, lic):
        n["i"] += 1
        return {"ok": False, "why": "内容和已有的一条重复"}
    r = A.run_once(max_new=10, max_try=8, fail_stop=3, feeder=dup, search=fake_search, pause=0)
    check("防误停：重复的来源不算连续失败", n["i"] == 8 and not r["stopped"], (n["i"], r["stopped"]))

    # 10 GitHub 限流：停止搜索，不硬撞
    reset()
    HITS["mode"] = "limit"
    r = A.run_once(dry_run=True, feeder=feeder_ok([]))
    check("限流：搜索被限流就停，只请求了 1 次", len(HITS["calls"]) == 1 and any("限流" in x for x in r["notes"]), (HITS["calls"], r["notes"]))

    # 11 锁：同时只跑一个
    reset()
    os.makedirs(os.environ["AISITE_CORPUS"], exist_ok=True)
    open(A._lock_path(), "w").write(str(os.getpid()))
    r = A.run_once(dry_run=True, search=fake_search)
    check("锁：已经有一个在跑时拒绝再开", not r["ok"] and "在跑" in r["why"], r)
    open(A._lock_path(), "w").write("999999")  # 进程不存在的旧锁
    r = A.run_once(dry_run=True, search=fake_search)
    check("锁：主人已经不在的旧锁自动作废", r["ok"], r)
    check("锁：跑完锁会删掉", not os.path.exists(A._lock_path()))

    # 12 真喂：本机假网站 → 真的 corpus.feed_one，存的只是数字
    reset()
    open(A.USER_LISTS[0], "w").write(f"{BASE}/clinic\tMedical Clinic\n")
    r = A.run_once(max_new=1, max_try=1, search=lambda q, p: [], pause=0, do_trial=False, allow_private=True)
    os.remove(A.USER_LISTS[0])
    specs = corpus.load()
    check("真喂：读本机网站收下 1 个标本", len(r["got"]) == 1 and len(specs) == 1 and specs[0]["industry"] == "Medical Clinic", (r, len(specs)))
    raw = open(corpus.path(), encoding="utf-8").read() + open(A._state_path(), encoding="utf-8").read()
    check("真喂：语料和状态里不留网页原文", "Care close to home" not in raw and "Patients" not in raw)
    check("真喂：收下后重算了规律", "Medical Clinic" in r["priors"], r["priors"])
    st = A.load_state()
    check("状态：记了运行历史", st["runs"] and st["runs"][-1]["got"] == 1, st["runs"])

    # 13 默认不碰内网地址
    reset()
    open(A.USER_LISTS[0], "w").write(f"{BASE}/clinic\tMedical Clinic\n")
    r = A.run_once(max_new=1, max_try=1, search=lambda q, p: [], pause=0, do_trial=False)
    os.remove(A.USER_LISTS[0])
    check("安全：默认拒绝本机/内网地址", not r["got"] and r["skipped"] and "内网" in r["skipped"][0][1], r["skipped"])

    # 14 定时：非 Mac 不写任何东西
    if sys.platform != "darwin":
        msg = A.install_schedule("03:17")
        check("定时：不是 Mac 时只给提示、不改系统", "Mac" in msg and not os.path.exists(A.PLIST), msg)
    check("定时：时间格式不对会拒绝", "格式" in A.install_schedule("25:99") or sys.platform != "darwin")

    # 15 令牌只从环境读，不写进状态
    os.environ["GITHUB_TOKEN"] = "ghp_testtoken_should_not_persist"
    reset()
    A.gh_search("x", 1)
    A.run_once(dry_run=True, search=fake_search)
    st_raw = open(A._state_path(), encoding="utf-8").read()
    os.environ.pop("GITHUB_TOKEN")
    check("密钥：GitHub 令牌不落盘", "ghp_testtoken" not in st_raw)

    srv.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"自动学习：{len(PASS)}/{len(PASS) + len(FAIL)} 通过")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
