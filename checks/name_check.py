#!/usr/bin/env python3
"""自己的 Python 文件不许和标准库模块重名（D13：copy.py 让 from copy import 拿到了标准库）。"""
import os, sys
std = set(sys.stdlib_module_names)
bad = []
for root in sys.argv[1:]:
    for d, dirs, fs in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", ".git", "examples", "fixtures")]
        bad += [os.path.join(d, f) for f in fs if f.endswith(".py") and f[:-3] in std]
for b in bad:
    print("与标准库重名：", b)
print(f"文件名自查：{len(bad)} 个与标准库重名")
sys.exit(1 if bad else 0)
