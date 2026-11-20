#!/usr/bin/env python3
"""旧版 Python 兼容检查：很多 Mac 自带的是 Python 3.9，所以所有代码必须能在 3.9 上导入。

两件事：
  1. 用本机能找到的较老解释器（3.9/3.10/3.11）逐个解析所有 .py 文件。
     新版 Python（3.12+）放宽了 f-string 语法，用它自己检查发现不了“花括号里有反斜杠”这类问题（D25）。
  2. 没写 from __future__ import annotations 的文件里，函数签名不能用 X | None 这种写法（3.9 导入时就会报错）。
用法：python3 -I checks/py_compat.py
"""
import glob
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
files = [f for f in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True) if "__pycache__" not in f]
olds = [p for p in (shutil.which(f"python3.{v}") for v in (9, 10, 11)) if p]
olds += sorted(glob.glob(os.path.expanduser("~/.local/share/uv/python/cpython-3.9*/bin/python3.9")))[:1]
problems = []
for py in olds:
    code = "import ast,sys\nbad=[]\nfor f in sys.argv[1:]:\n    try: ast.parse(open(f,encoding='utf-8').read())\n    except SyntaxError as e: bad.append(f+': '+str(e))\nprint('\\n'.join(bad))"
    out = subprocess.run([py, "-I", "-c", code] + files, capture_output=True, text=True, timeout=120).stdout.strip()
    problems += [f"{os.path.basename(py)} 解析失败：{x.replace(ROOT + os.sep, '')}" for x in out.splitlines() if x]
union = re.compile(r"^\s*def [^\n]*(?:\w|\])\s*\|\s*(?:None|\w)", re.M)
for f in files:
    src = open(f, encoding="utf-8").read()
    if "from __future__ import annotations" not in src and union.search(src):
        problems.append(f"{os.path.relpath(f, ROOT)}：函数签名用了 X | Y，但没有 from __future__ import annotations（3.9 导入会报错）")
for p in problems:
    print("✗ " + p)
print(f"旧版 Python 兼容：用 {len(olds)} 个旧解释器检查了 {len(files)} 个文件，{len(problems)} 个问题")
sys.exit(1 if problems else 0)
