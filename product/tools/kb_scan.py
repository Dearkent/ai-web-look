#!/usr/bin/env python3
"""全量扫描 products.csv 的风格 / 落地页引用能否解析成 ID（只读 CSV）。
用法：python3 -I kb_scan.py <UI UX Pro Max 的 data 目录>"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kb  # noqa: E402
rows = list(csv.DictReader(open(os.path.join(sys.argv[1], "products.csv"), encoding="utf-8")))
full = part = none = 0
for r in rows:
    for col, dom in (("Primary Style Recommendation", "style"), ("Landing Page Pattern", "landing")):
        t = r[col].strip()
        if not t:
            continue
        x = kb.resolve_combo(t, dom)
        if x["ids"] and not x["unresolved"]:
            full += 1
        elif x["ids"]:
            part += 1
        else:
            none += 1
print(f"产品表引用 {full + part + none} 处：完全解析 {full}，部分解析 {part}，完全不能解析 {none}")
