#!/usr/bin/env python3
"""L012 固化：读码笔记里引用的每条代码事实，都要能在源码里重新检索到。

事实清单是 TSV：仓库目录<TAB>文件路径<TAB>要找的文字（或 "lines=N" 表示文件应有 N 行）<TAB>说明
用法：python3 cite_check.py evals/facts/xxx.tsv
"""
import re
import subprocess
import sys
from pathlib import Path

ok = bad = 0
for line in open(sys.argv[1], encoding="utf-8"):
    if not line.strip() or line.startswith("#"):
        continue
    repo, path, needle, note = (line.rstrip("\n").split("\t") + [""])[:4]
    f = Path(repo) / path
    if f.exists():
        text = f.read_text(encoding="utf-8", errors="replace")
    else:  # 无检出克隆：只按路径取单个文件（不做全库 git grep，会逐个下载对象而卡住，见 L016）
        try:
            r = subprocess.run(["git", "-C", repo, "show", f"HEAD:{path}"], capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            print(f"读取超时  {path}  （{note}）"); bad += 1; continue
        if r.returncode != 0:
            print(f"缺失文件  {path}  （{note}）"); bad += 1; continue
        text = r.stdout.decode("utf-8", errors="replace")
    if needle.startswith("lines="):
        n = text.count("\n")
        good = n == int(needle[6:])
        detail = f"实际 {n} 行"
    else:
        good = needle in text
        detail = ""
        if not good:  # 注释或字符串被折行时：合并换行和行首注释符再比一次（L014）
            flat = re.sub(r"\s*\n\s*(#|//|\*)?\s*", " ", text)
            good = re.sub(r"\s+", " ", needle) in flat
            detail = "（跨行匹配）" if good else ""
    print(f"{'核对通过' if good else '对不上'}  {path}  {needle[:40]}  {detail}（{note}）")
    ok += good; bad += not good
print(f"事实核对：{ok} 条通过，{bad} 条对不上")
