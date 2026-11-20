#!/usr/bin/env python3
"""自查：大脑自己的脚本里不许有“可能停不下来”的写法。

规则（违反即报）：
  R1 Python 的每个 while 循环，同一行或上一行要写“# 有界：<为什么一定会结束>”。
  R2 Python 里 subprocess.run / check_output / call / Popen.communicate 必须带 timeout。
  R3 Shell 里的 git clone / git fetch / curl / wget 必须套 timeout。
  R4 Shell 里的 while 循环要写“# 有界：”。
  R5 不许对无检出克隆做 `git grep ... HEAD`（会逐个下载对象而卡住，L016）。
用法：python3 -I loop_audit.py <目录或文件>...
"""
import ast, os, re, sys

BOUND = re.compile(r"#\s*有界[:：]")
problems = []


def py_file(path):
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        problems.append((path, e.lineno or 0, "R0", "语法错误，无法审计"))
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            here = lines[node.lineno - 1]
            prev = lines[node.lineno - 2] if node.lineno > 1 else ""
            if not (BOUND.search(here) or BOUND.search(prev)):
                problems.append((path, node.lineno, "R1", "while 循环没有写明为什么一定会结束"))
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
            if (owner == "subprocess" and name in ("run", "check_output", "call", "check_call")) or name == "communicate":
                if not any(k.arg == "timeout" for k in node.keywords):
                    problems.append((path, node.lineno, "R2", f"{owner + '.' if owner else ''}{name} 没有 timeout"))
    doc = ast.get_docstring(tree, clean=False)
    skip = set(range(1, src[:src.find(doc) + len(doc)].count("\n") + 2)) if doc else set()
    for i, l in enumerate(lines, 1):
        if i in skip:
            continue
        if re.search(r"git\s+grep\b.*\bHEAD\b", l) and "noqa: R5" not in l:
            problems.append((path, i, "R5", "对 HEAD 做 git grep；无检出克隆会卡住，改用 git show 读单个文件"))


def sh_file(path):
    for i, l in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
        code = l.split("#", 1)[0]
        if re.search(r"\b(git\s+(clone|fetch)|curl|wget)\b", code) and not re.search(r"\btimeout\s+\d", code):
            problems.append((path, i, "R3", "网络命令没有套 timeout"))
        if re.match(r"\s*while\b", code) and not BOUND.search(l):
            problems.append((path, i, "R4", "shell while 循环没有写明为什么一定会结束"))
        if re.search(r"git\s+grep\b.*\bHEAD\b", code):
            problems.append((path, i, "R5", "对 HEAD 做 git grep；无检出克隆会卡住"))


targets = sys.argv[1:] or ["."]
n_files = 0
for t in targets:
    walk = [(os.path.dirname(t), [], [os.path.basename(t)])] if os.path.isfile(t) else os.walk(t)
    for root, dirs, files in walk:
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "examples")]
        for f in files:
            p = os.path.join(root, f)
            if f.endswith(".py"):
                n_files += 1; py_file(p)
            elif f.endswith(".sh"):
                n_files += 1; sh_file(p)
for p, ln, code, msg in problems:
    print(f"{code}  {p}:{ln}  {msg}")
print(f"死循环自查：{n_files} 个脚本，{len(problems)} 处问题")
sys.exit(1 if problems else 0)
