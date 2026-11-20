#!/usr/bin/env python3
"""修复回路 × 真实构建：咖啡馆图纸 + 一段有真实 bug 的交互脚本，用真实 Chrome 报错。

修复者仍是模拟的（没有模型密钥），但其余全部是真的：git 存档与回滚、图纸检查、生成、浏览器报错、守卫判断。
用法：timeout 300 python3 -I -u real_loop_test.py [修复记录输出路径]
"""
import json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from fix_guard import FixGuard, Policy  # noqa: E402
from fix_loop import run  # noqa: E402
from model_fixer import ModelFixer  # noqa: E402
from real_build import build  # noqa: E402
from workspace import Change, Workspace  # noqa: E402

EX = os.path.join(HERE, "..", "examples", "cafe")
LOG = sys.argv[1] if len(sys.argv) > 1 else None
BUGGY = ("// 点菜单卡片时高亮（模型写的交互）\n"
         "document.querySelector('#menu-teaser .card').addEventListener('click', function (e) {\n"
         "  e.currentTarget.classList.toggle('picked');\n});\n")
FIXED = ("// 点菜单卡片时高亮；没有菜单区块的页面直接跳过\n"
         "document.querySelectorAll('#menu-teaser .card').forEach(function (card) {\n"
         "  card.addEventListener('click', function () { card.classList.toggle('picked'); });\n});\n")
ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


def project_files(extra=None):
    files = {}
    for d, _, fs in os.walk(EX):
        for f in fs:
            p = os.path.join(d, f)
            files[os.path.relpath(p, EX)] = open(p, encoding="utf-8").read()
    files.update(extra or {})
    return files


def fresh(extra):
    root = tempfile.mkdtemp(prefix="rl-")
    ws = Workspace(os.path.join(root, "w"))
    ws.init(project_files(extra))
    return ws, root


# 0. 构建本身：干净的图纸 0 报错；带 bug 的脚本在没有菜单区块的 4 个页面上真实报错
clean = build(project_files())
expect("真实构建：干净的咖啡馆图纸 0 报错", clean == [], clean)
errs = build(project_files({"custom/site.js": BUGGY}))
expect("真实构建：bug 脚本在 4 个页面触发真实的浏览器报错", len(errs) == 4 and all("Cannot read properties of null" in e for e in errs), errs)


# 1. 模拟“像模型一样”的修复者：读到 null 报错就加判断
def js_fixer(files, errors, hint, strategy, rnd):
    if any("Cannot read properties of null" in e for e in errors):
        return [Change("write", "custom/site.js", FIXED)]
    return []


ws, root = fresh({"custom/site.js": BUGGY})
rep = run(ws, build, js_fixer, FixGuard(Policy()), log_path=LOG, label="真实构建·脚本空值修复")
expect("修复回路 × 真实浏览器：1 轮修好", rep["verdict"] == "done" and len(rep["rounds"]) == 1 and rep["errors_after"] == 0, rep)
shutil.rmtree(root)

# 2. 同样的链路，但修复者是模型接口（假的流式回复），验证“解析模型输出 → 预检 → 提交 → 浏览器验证”整条链
reply = json.dumps({"reason": "没有菜单区块的页面上 querySelector 返回 null",
                    "changes": [{"op": "write", "path": "custom/site.js", "content": FIXED}]}, ensure_ascii=False)
mf = ModelFixer(transport=lambda req: (reply[i:i + 50] for i in range(0, len(reply), 50)))
ws, root = fresh({"custom/site.js": BUGGY})
rep = run(ws, build, mf, FixGuard(Policy()), log_path=LOG, label="真实构建·模型接口（模拟回复）")
expect("模型接口 × 真实浏览器：解析回复后 1 轮修好", rep["verdict"] == "done" and rep["errors_after"] == 0, rep)
expect("模型接口：请求里带着真实的浏览器报错", "Cannot read properties of null" in mf.requests[0]["messages"][0]["content"])
shutil.rmtree(root)

# 3. 模型一直复读：每轮都被中断、拿不到改动，守卫在上限内停下，网站退回原样
loop = lambda req: iter(["我先检查一下文件。"] * 10000)
mf = ModelFixer(transport=loop)
ws, root = fresh({"custom/site.js": BUGGY})
t0 = ws.tree()
rep = run(ws, build, mf, FixGuard(Policy()), log_path=LOG, label="真实构建·模型复读")
expect("模型复读：每轮都被复读检测中断", mf.notes and all("复读" in n for n in mf.notes), mf.notes)
expect("模型复读：守卫在 5 轮内停下", rep["verdict"] == "stop" and len(rep["rounds"]) <= 5, (rep["code"], len(rep["rounds"])))
expect("模型复读：网站内容保持原样", ws.tree() == t0)
shutil.rmtree(root)

# 4. 修复者改坏了图纸（按钮指向不存在的页面）：图纸检查先拦住，下一轮按提示改回
def careless(files, errors, hint, strategy, rnd):
    if any("Cannot read properties of null" in e for e in errors):
        home = files["pages/home.json"].replace('"page": "booking"', '"page": "reserve"', 1)
        return [Change("write", "custom/site.js", FIXED), Change("write", "pages/home.json", home)]
    if any("图纸·P050" in e for e in errors):
        return [Change("write", "pages/home.json", files["pages/home.json"].replace('"page": "reserve"', '"page": "booking"'))]
    return []


ws, root = fresh({"custom/site.js": BUGGY})
rep = run(ws, build, careless, FixGuard(Policy()), log_path=LOG, label="真实构建·改坏图纸后改回")
expect("改坏图纸：图纸检查报出死链（P050）", rep["rounds"][0]["errors"] >= 1, rep["rounds"])
expect("改坏图纸：第 2 轮改回后全部修好", rep["verdict"] == "done" and rep["errors_after"] == 0 and len(rep["rounds"]) == 2, rep)
shutil.rmtree(root)

print(f"真实构建回路：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
