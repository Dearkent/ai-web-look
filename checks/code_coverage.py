#!/usr/bin/env python3
"""每个图纸错误码都必须有反例：检查器里出现的错误码，变异测试里都要有一条故意触发它的改法。"""
import re, sys
codes = set(re.findall(r'"([BSPW]\d{3})"', open(sys.argv[1], encoding="utf-8").read()))
tested = set(re.findall(r'"([BSPW]\d{3})", "', open(sys.argv[2], encoding="utf-8").read()))
missing = sorted(codes - tested)
print(f"错误码反例覆盖：{len(codes) - len(missing)}/{len(codes)}" + (f"，缺 {missing}" if missing else ""))
sys.exit(1 if missing else 0)
