#!/usr/bin/env python3
"""E62 实况：事件只记数字和短标签、不记用户原话；任务/步骤嵌套共用编号；记事件出错不影响正事；
文件太大自动换新；读增量；工作台 /live 页面要令牌、快照和事件流（SSE）真的推送新事件；
真实建站按“规划 → 图纸检查 → 生成 → 浏览器检查”的顺序记；页面在真实浏览器里能连上、画出卡片、没有脚本错误。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="live-test-")
EV = os.path.join(TMP, "events.jsonl")
os.environ["AISITE_EVENTS"] = EV
os.environ["AISITE_LIVE_SECONDS"] = "8"
sys.path.insert(0, HERE)
import events  # noqa: E402

ok = total = 0


def check(name, cond, detail=""):
    global ok, total
    total += 1
    ok += bool(cond)
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  —— {detail}"))


def rows():
    try:
        return [json.loads(x) for x in open(EV, encoding="utf-8")]
    except OSError:
        return []


# ---- 事件本身
events.emit("note", 文字="x" * 500, 危险="<script>alert(1)</script>", 列表=list(range(50)), 嵌套={"a": {"b": {"c": {"d": 1}}}})
r = rows()[-1]
check("长字符串截短到 80 字、去掉尖括号之类的字符", len(r["文字"]) == 80 and "<" not in r["危险"], r)
check("列表最多 12 项、嵌套不超过两层", len(r["列表"]) == 12 and isinstance(r["嵌套"]["a"]["b"], str), r)
check("不认识的事件种类不记", events.emit("hack.anything", x=1) is None)
with events.run("build", 行业="Bakery/Cafe") as rid:
    with events.run("autofix") as inner:
        with events.stage("plan") as st:
            st.out(pages=5)
r = rows()
check("嵌套任务共用外层编号；外层结束才记 run.end", inner == rid and [x["kind"] for x in r[-4:]] == ["run.start", "stage.start", "stage.end", "run.end"]
      and all(x["run"] == rid for x in r[-4:]), [x["kind"] for x in r[-5:]])
check("步骤结束带耗时和结果数字", r[-2]["stage"] == "plan" and r[-2]["pages"] == 5 and isinstance(r[-2]["ms"], int))
try:
    with events.run("build"):
        raise RuntimeError("boom")
except RuntimeError:
    pass
check("任务出错也记结束：ok=false 和错误类型", rows()[-1]["ok"] is False and rows()[-1]["error"] == "RuntimeError")
os.environ["AISITE_EVENTS"] = "/proc/不能写/events.jsonl"
check("事件文件写不了：返回空，不抛错", events.emit("note", a=1) is None)
os.environ["AISITE_EVENTS"] = EV
pos = os.path.getsize(EV)
events.emit("note", n=1)
new, pos2 = events.read(pos)
check("增量读取：只读到新的一条", len(new) == 1 and new[0]["n"] == 1 and pos2 == os.path.getsize(EV), new)
old_max = events.MAX_BYTES
events.MAX_BYTES = 200
events.emit("note", n=2)
events.emit("note", n=3)
events.MAX_BYTES = old_max
check("文件太大换新，旧的留一份 .1", os.path.exists(EV + ".1") and rows()[-1]["n"] == 3)
got, _ = events.read(10 ** 9)
check("位置超过文件长度（换过新文件）：从头读", got and got[-1]["n"] == 3, got)

# ---- 真实建站的事件顺序
sys.path.insert(0, os.path.join(HERE, "..", "text2site"))
import styles  # noqa: E402
from make_site import build_one  # noqa: E402
from understand import understand  # noqa: E402
SECRET_TEXT = "我家狗叫旺财，帮我做个咖啡馆网站"
b = understand(SECRET_TEXT)
start = os.path.getsize(EV)
build_one(b, styles.options(b)[0]["id"], tempfile.mkdtemp(), run_browser=True)
evs, _ = events.read(start)
stages = [e["stage"] for e in evs if e["kind"] == "stage.end"]
check("真实建站：规划 → 图纸检查 → 生成 → 浏览器检查", stages == ["plan", "blueprint", "generate", "browser"], stages)
check("事件里没有用户原话", "旺财" not in json.dumps(evs, ensure_ascii=False))

# ---- 工作台接口和页面
import server  # noqa: E402
srv, app = server.serve(0, os.path.join(TMP, "work"))
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"


def get(path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    return urllib.request.urlopen(req, timeout=20)


html = get("/live").read().decode()
check("/live 页面带本次启动的令牌", f'content="{app.token}"' in html)
try:
    get("/api/live/snapshot")
    check("快照没有令牌被拒", False)
except urllib.error.HTTPError as e:
    check("快照没有令牌被拒", e.code == 403)
snap = json.load(get(f"/api/live/snapshot?token={app.token}"))
check("快照：最近事件 + 当前位置 + 真实指标", snap["events"] and snap["pos"] > 0 and "stats" in snap, list(snap))
got_lines = []


def listen():
    try:
        with get(f"/api/live?token={app.token}&since={snap['pos']}") as resp:
            for line in resp:
                got_lines.append(line.decode())
                if any("推送测试" in x for x in got_lines):
                    return
    except Exception as e:  # noqa: BLE001
        got_lines.append(f"ERR {e}")


th = threading.Thread(target=listen, daemon=True)
th.start()
time.sleep(1.0)
events.emit("note", 标签="推送测试")
th.join(10)
check("事件流（SSE）把新事件推给页面", any("推送测试" in x for x in got_lines) and any(x.startswith("event: ev") for x in got_lines), got_lines[-3:])
try:
    get("/api/live")
    check("事件流没有令牌被拒", False)
except urllib.error.HTTPError as e:
    check("事件流没有令牌被拒", e.code == 403)

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 1440, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(base + "/live")
        pg.wait_for_function("document.getElementById('mode').textContent === '实时'", timeout=8000)
        n0 = pg.locator(".card").count()
        with events.run("build", 行业="Bakery/Cafe"):
            with events.stage("browser") as st:
                st.out(problems=2, kinds=["溢出"])
        pg.wait_for_function(f"document.querySelectorAll('.card').length > {n0}", timeout=8000)
        bad = pg.locator(".card.bad").count()
        check("页面：连上实时、新事件画成卡片（有问题的标红）、没有脚本错误", bad >= 1 and not errs, (bad, errs[:3]))
        # 不闪：几种窗口尺寸下，事件不断涌入时各块尺寸不变、主区有高度、卡片不会刚出现就被删、没有横向溢出
        def stable(page):
            for i in range(6):
                with events.run("build", 行业="Bakery/Cafe"):
                    with events.stage("browser") as st:
                        st.out(problems=i % 2, kinds=["很长很长的问题类型名字" * 3] if i % 2 else [])
            return page.evaluate("""() => new Promise(res => { const ids=['agents','chart','log','main','rings','tiles','stages']; const hist={}; let n=0;
              const t=setInterval(() => { ids.forEach(id => { const q=document.getElementById(id).getBoundingClientRect(); (hist[id]=hist[id]||new Set()).add(Math.round(q.width)+'x'+Math.round(q.height)); });
                if (++n>=40) { clearInterval(t); res({changing:Object.keys(hist).filter(k=>hist[k].size>1), main:document.getElementById('main').getBoundingClientRect().height,
                  cards:document.querySelectorAll('.card').length, ox:document.documentElement.scrollWidth>innerWidth}); } }, 50); })""")
        bad_vp = []
        for w, h, d in ((1512, 982, 2), (1280, 720, 2), (720, 900, 2), (390, 844, 3)):
            q = br.new_page(viewport={"width": w, "height": h}, device_scale_factor=d)
            q.goto(base + "/live")
            q.wait_for_function("document.getElementById('mode').textContent === '实时'", timeout=8000)
            r = stable(q)
            if r["changing"] or r["main"] < 300 or r["cards"] < 2 or r["ox"]:
                bad_vp.append(((w, h), r))
            q.close()
        check("不闪：四种窗口尺寸下尺寸不跳、主区有高度、卡片不被立刻删、不横向溢出", not bad_vp, bad_vp)
        br.close()
except ImportError:
    check("页面：本机没有 Playwright，跳过浏览器检查", True)
srv.shutdown()
print(f"实况：{ok}/{total} 通过")
sys.exit(0 if ok == total else 1)
