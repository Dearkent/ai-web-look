#!/usr/bin/env python3
"""原型端到端测试：真的建 git 仓库、真的改文件、真的回滚。

用法：timeout 120 python3 -I -u proto_test.py
"""
import difflib, json, os, re, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from fix_guard import Decision, FixGuard, Policy  # noqa: E402
from fix_loop import run  # noqa: E402
from site_build import build  # noqa: E402
from workspace import Change, Rejected, Workspace  # noqa: E402

SITE = {
    "index.html": '<!doctype html><html><head><title>巷口咖啡</title></head><body>\n<h1 id="top">巷口咖啡</h1>\n'
                  '<a href="menu.html">菜单</a>\n<a href="bookin.html">预约</a>\n<img src="shop.jpg">\n</body></html>\n',
    "menu.html": '<!doctype html><html><head></head><body>\n<a href="index.html">首页</a>\n'
                 '<p id="latte">拿铁</p>\n<p id="latte">燕麦拿铁</p>\n</body></html>\n',
    "booking.html": '<!doctype html><html><head><title>预约</title></head><body>\n<a href="/visit.html">到店</a>\n</body></html>\n',
}
passed, failed = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (passed if cond else failed).append(name)


def fresh():
    root = tempfile.mkdtemp(prefix="proto-")
    ws = Workspace(os.path.join(root, "site"))
    ws.init(SITE)
    return ws, root


# ---------------- 模拟修复者 ----------------
def good(files, errors, hint, strategy, rnd, per_round=2):
    """正常的修复者：每轮修前两个报错。"""
    files, touched = dict(files), set()
    pages = [p for p in files if p.endswith(".html")]
    for e in errors[:per_round]:
        if m := re.match(r"死链：(\S+?):\d+ → (\S+) 不存在", e):
            f, href = m.groups()
            best = difflib.get_close_matches(href.lstrip("/"), pages, n=1, cutoff=0.6)
            files[f] = files[f].replace(f'href="{href}"', f'href="{best[0] if best else "index.html"}"', 1)
        elif m := re.match(r"图片缺少 alt：(\S+?):\d+（(.+)）", e):
            f, src = m.groups()
            files[f] = files[f].replace(f'<img src="{src}">', f'<img src="{src}" alt="店内照片">', 1)
        elif m := re.match(r"缺少 <title>：(\S+)", e):
            f = m.group(1)
            files[f] = files[f].replace("<head>", "<head><title>页面</title>", 1)
        elif m := re.match(r"重复 id「(.+)」：(\S+?):\d+", e):
            i, f = m.groups()
            k = files[f].rfind(f'id="{i}"')
            files[f] = files[f][:k] + f'id="{i}-2"' + files[f][k + len(f'id="{i}"'):]
        else:
            continue
        touched.add(f)
    return [Change("write", p, files[p]) for p in sorted(touched)]


def noop(files, errors, hint, strategy, rnd):
    """原地打转：每轮加一句不同的注释，报错一个没少。"""
    return [Change("write", "index.html", files["index.html"] + f"<!-- 尝试 {rnd} -->\n")]


def same_patch(files, errors, hint, strategy, rnd):
    """原地打转：每轮都打同一个补丁。"""
    return [Change("write", "notes.txt", "这里应该修好了\n")]


def oscillate(files, errors, hint, strategy, rnd):
    """来回振荡：修好 alt 就弄坏菜单链接，修好链接又弄丢 alt。"""
    s = files["index.html"]
    if rnd % 2:
        s = s.replace('<img src="shop.jpg">', '<img src="shop.jpg" alt="店内">').replace('href="menu.html"', 'href="menus.html"')
    else:
        s = s.replace('<img src="shop.jpg" alt="店内">', '<img src="shop.jpg">').replace('href="menus.html"', 'href="menu.html"')
    return [Change("write", "index.html", s)]


def vandal_then_learn(files, errors, hint, strategy, rnd):
    """先乱改一通（报错暴涨）；看到“已撤销”的反馈后改正做法。没有反馈就会一直乱改。"""
    if "已撤销" in hint:
        return good(files, errors, hint, strategy, rnd, per_round=5)
    bad = "".join(f'<a href="gone{k}-{rnd}.html">x</a>\n' for k in range(8))
    return [Change("write", p, files[p].replace("<title>", "<titel>").replace("</body>", bad + "</body>"))
            for p in sorted(files) if p.endswith(".html")]


def escaper(files, errors, hint, strategy, rnd):
    """越权：一批改动里夹带一条写到项目外面的。"""
    return [Change("write", "index.html", files["index.html"].replace('href="bookin.html"', 'href="booking.html"')),
            Change("write", "../escape.html", "<p>不该出现</p>")]


# ---------------- 1. 正常修复 ----------------
ws, root = fresh()
log = os.path.join(root, "fix_runs.jsonl")
rep = run(ws, build, good, FixGuard(Policy()), log_path=log, label="good")
expect("正常修复：修好（5 个报错 → 0）", rep["verdict"] == "done" and rep["errors_before"] == 5 and rep["errors_after"] == 0, rep)
expect("正常修复：每轮一个提交（初始 1 + 3 轮）", rep["commits"] == 1 + len(rep["rounds"]) == 4, rep["commits"])
expect("正常修复：留下修复记录", os.path.exists(log) and json.loads(open(log).read().splitlines()[0])["label"] == "good")
shutil.rmtree(root)

# ---------------- 2. 原地打转（每轮不同的无效改动） ----------------
ws, root = fresh()
t0 = ws.tree()
rep = run(ws, build, noop, FixGuard(Policy()))
expect("原地打转：第 1 轮提醒、第 2 轮停（G02）", [r["code"] for r in rep["rounds"]] == ["G02", "G02"] and rep["verdict"] == "stop", rep["rounds"])
expect("原地打转：内容退回原始版本", ws.tree() == t0)
expect("原地打转：给用户的话说清楚了", "自动修复已停止" in rep["to_user"] and "试了 2 轮" in rep["to_user"], rep["to_user"])
shutil.rmtree(root)

# ---------------- 3. 同一个补丁反复打 ----------------
ws, root = fresh()
rep = run(ws, build, same_patch, FixGuard(Policy()))
expect("同一补丁：第 2 轮停（G07）", rep["code"] == "G07" and len(rep["rounds"]) == 2, rep["rounds"])
shutil.rmtree(root)

# ---------------- 4. 来回振荡 ----------------
ws, root = fresh()
t0 = ws.tree()
rep = run(ws, build, oscillate, FixGuard(Policy()))
expect("来回振荡：识别出代码改回原样并停下（G03）", rep["code"] == "G03" and len(rep["rounds"]) == 2, rep["rounds"])
expect("来回振荡：停下后内容是报错最少的版本", len(build(ws.files())) <= 5)
shutil.rmtree(root)

# ---------------- 5. 越修越坏，然后从反馈里学会 ----------------
ws, root = fresh()
c0 = ws.history()[-1]
rep = run(ws, build, vandal_then_learn, FixGuard(Policy()))
codes = [r["code"] for r in rep["rounds"]]
expect("越修越坏：第 1 轮被撤销（G05）并退回原始版本", codes[0] == "G05" and rep["rounds"][0].get("rolled_back_to"), rep["rounds"])
expect("越修越坏：看到反馈后修好", rep["verdict"] == "done" and rep["errors_after"] == 0, rep)
hist = ws.history()
expect("回滚不改写历史：最初的提交还在，提交只增不减", hist[-1] == c0 and len(hist) == 1 + len(rep["rounds"]) + 1, len(hist))
shutil.rmtree(root)

# ---------------- 6. 越权路径：整批拒绝，什么都不写 ----------------
ws, root = fresh()
before = ws.files()
rep = run(ws, build, escaper, FixGuard(Policy()))
expect("越权：项目外没有出现文件", not os.path.exists(os.path.join(root, "escape.html")))
expect("越权：同批里合法的那条也没写（全有或全无）", ws.files() == before)
expect("越权：拒绝原因写回给修复者", "补丁被整批拒绝" in rep["rounds"][0]["note"] and "越出项目目录" in rep["rounds"][0]["note"], rep["rounds"][0])
expect("越权：第 2 轮同样的补丁被叫停（G07）", rep["code"] == "G07", rep["code"])
for bad in ([Change("write", ".git/config", "x")], [Change("write", "/etc/passwd", "x")],
            [Change("delete", "nope.html")], [Change("write", "a.html", "1"), Change("write", "a.html", "2")]):
    try:
        ws.apply(bad, "不该成功")
        expect(f"预检拒绝 {bad[0].op} {bad[0].path}", False)
    except Rejected:
        expect(f"预检拒绝 {bad[0].op} {bad[0].path}", True)
shutil.rmtree(root)

# ---------------- 7. 写到一半失败：全部恢复原样，不产生提交 ----------------
import workspace as _w  # noqa: E402
ws, root = fresh()
before, n0 = ws.files(), len(ws.history())
_real, _calls = _w.os.replace, []


def _flaky(a, b):  # 故障注入：第二次落盘时失败
    _calls.append(b)
    if len(_calls) == 2:
        raise OSError("磁盘写入失败（模拟）")
    return _real(a, b)


_w.os.replace = _flaky
try:
    ws.apply([Change("write", "menu.html", "<p>已改</p>"), Change("write", "index.html", "<p>也改</p>"),
              Change("write", "new.html", "<p>新文件</p>")], "中途会失败")
    expect("中途失败：应当报错", False)
except RuntimeError as e:
    expect("中途失败：报“已全部恢复原样”", "已全部恢复原样" in str(e), str(e))
finally:
    _w.os.replace = _real
expect("中途失败：已写的第一个文件恢复原样、没有残留临时文件", ws.files() == before and not list(ws.root.rglob("*.writing")),
       sorted(ws.files()))
expect("中途失败：没有产生新提交", len(ws.history()) == n0)
why = ws.preflight([Change("rename", "booking.html", to="index.html/sub.html")])
expect("预检拒绝：改名目标的上级是一个文件", len(why) == 1 and "上级是一个文件" in why[0], why)
why = ws.preflight([Change("write", "index.html/x.html", "<p>x</p>")])
expect("预检拒绝：写入路径的上级是一个文件", len(why) == 1 and "上级是一个文件" in why[0], why)
expect("预检放行：正常改名", ws.preflight([Change("rename", "booking.html", to="pages/booking.html")]) == [])
shutil.rmtree(root)

# ---------------- 8. 守卫失灵：循环自己的兜底上限 ----------------
class BrokenGuard(FixGuard):
    def record(self, a):
        return Decision("continue")


ws, root = fresh()
rep = run(ws, build, noop, BrokenGuard(Policy(max_attempts=4)))
expect("守卫失灵：循环在兜底上限停下（L00）", rep["code"] == "L00" and len(rep["rounds"]) == 5, (rep["code"], len(rep["rounds"])))
expect("守卫失灵：退回报错最少的版本", rep["errors_after"] == 5)
shutil.rmtree(root)

print(f"原型端到端：{len(passed)}/{len(passed) + len(failed)} 通过")
sys.exit(1 if failed else 0)
