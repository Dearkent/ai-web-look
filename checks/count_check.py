#!/usr/bin/env python3
"""L002 固化：标题里写的“（N 个）”必须等于其下第一张表格的数据行数。

用法：python3 count_check.py <markdown 文件>
"""
import re
import sys


def check(text):
    problems, checked = [], 0
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^#{1,6}\s+(.*?)（(\d+)\s*个", line)
        if not m:
            continue
        claimed = int(m.group(2))
        rows, in_table = 0, False
        for nxt in lines[i + 1:]:
            if re.match(r"^#{1,6}\s", nxt):
                break
            if nxt.startswith("|"):
                in_table = True
                if not re.match(r"^\|\s*-", nxt):
                    rows += 1
            elif in_table:
                break
        rows = max(rows - 1, 0)  # 去掉表头
        checked += 1
        if rows != claimed:
            problems.append(f"不一致：「{m.group(1)}」写 {claimed} 个，表格实有 {rows} 行")
    return checked, problems


if __name__ == "__main__":
    checked, problems = check(open(sys.argv[1], encoding="utf-8").read())
    for p in problems:
        print(p)
    print(f"检查了 {checked} 个带数量的标题，" + ("全部一致" if not problems else f"{len(problems)} 处不一致"))
