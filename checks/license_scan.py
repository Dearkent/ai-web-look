#!/usr/bin/env python3
"""L001/L008/L010 固化：扫描仓库里所有 LICENSE/COPYING 文件，找出比根目录更严格的子目录许可。

只读：仓库须是 git 克隆（可为 --no-checkout），通过 git ls-tree / git show 读取，不检出、不执行。
用法：python3 license_scan.py [--all] <仓库目录> [<仓库目录> ...]
  默认只列出“比根目录更严格”的子目录许可；--all 列出所有与根目录不同的。
输出：每个仓库一行根许可；需要注意的子目录逐行列出；失败的仓库输出“错误”行（不静默丢弃）；最后一行汇总。
"""
import re
import subprocess
import sys

SKIP = re.compile(r"(^|/)(node_modules|vendor|third[_-]?party|examples?|fixtures?|tests?|__tests__|docs?|fonts?)/", re.I)
NAME = re.compile(r"(^|/)(licen[cs]e|copying)(\.(md|txt|rst))?$", re.I)

# 顺序即优先级：先认最具体的。MPL / LGPL 的正文会提到 GPL、AGPL，所以必须排在它们前面（L010）。
RULES = [
    ("Commons Clause", "MIT+Commons Clause", 3),
    ("Functional Source", "FSL", 3),
    ("Business Source", "BUSL", 3),
    ("Elastic License", "Elastic-2.0", 3),
    ("Mozilla Public License", "MPL-2.0", 1),
    ("GNU LESSER", "LGPL", 1),
    ("GNU AFFERO", "AGPL-3.0", 3),
    ("GNU GENERAL PUBLIC", "GPL", 2),
    ("Apache License", "Apache-2.0", 0),
    ("Permission is hereby granted, free of charge", "MIT", 0),
    ("MIT License", "MIT", 0),
    ("Redistribution and use in source and binary forms", "BSD", 0),
    ("unencumbered software released into the public domain", "Unlicense", 0),
    ("Creative Commons", "CC", 0),
    ("End User License Agreement", "专有EULA", 4),
    ("Enterprise License", "专有企业许可", 4),
    ("Proprietary and confidential", "专有", 4),
    ("All rights reserved", "保留所有权利", 4),
]
STRICT = {name: rank for _, name, rank in RULES}


def classify(t):
    if not t.strip():
        return "空文件"
    if len(t.strip()) < 120 and "/" in t and "license" in t.lower():
        return "指向:" + t.strip().splitlines()[0]
    low = t.lower()
    for key, name, _ in RULES:
        if key.lower() in low:
            return name
    return "其他"


def rank(name):
    return STRICT.get(name.split("（")[0], 2)  # 认不出的按中等严格处理，宁可多看一眼


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200])
    return r.stdout


def scan(repo, show_all=False):
    files = [f for f in git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
             if NAME.search(f) and not SKIP.search(f)]
    found = {f: classify(git(repo, "show", f"HEAD:{f}")[:6000]) for f in files}
    root = next((v for f, v in found.items() if "/" not in f), "无根LICENSE")
    if root.startswith("指向:"):  # 根 LICENSE 只是一行子包路径：跟随它
        target = root.split(":", 1)[1].strip().lstrip("./")
        root = found.pop(target, root) + f"（经 {target}）"
    base = rank(root) if root != "无根LICENSE" else 4
    subs = {f: v for f, v in found.items() if "/" in f and not v.startswith("指向")}
    if show_all:
        notes = {f: v for f, v in subs.items() if v != root.split("（")[0]}
    else:
        notes = {f: v for f, v in subs.items() if rank(v) > base}
    return root, notes


def main(argv):
    show_all = "--all" in argv
    repos = [a for a in argv if a != "--all"]
    flagged = errors = 0
    for repo in repos:
        name = repo.rstrip("/").split("/")[-1]
        try:
            root, notes = scan(repo, show_all)
        except Exception as e:  # 不静默丢弃（L011）
            print(f"{name}\t错误\t{e}")
            errors += 1
            continue
        print(f"{name}\t根目录\t{root}")
        for f, v in sorted(notes.items()):
            print(f"{name}\t{f}\t{v}")
        flagged += bool(notes)
    label = "与根目录不同" if show_all else "比根目录更严格"
    print(f"汇总：扫描 {len(repos)} 个仓库，{flagged} 个存在{label}的子目录许可，{errors} 个出错")


if __name__ == "__main__":
    main(sys.argv[1:])
