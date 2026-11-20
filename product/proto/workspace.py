#!/usr/bin/env python3
"""存档与回滚工作区：AI 每轮改动都要经过这里。

规则（学自 Dyad，经验 P004 / P005；只读学习，未复用代码）：
  * 整批预检：一批改动里只要有一条不安全（越出项目目录、碰 .git、超大、目标不存在……），整批都不做，并说清是哪条、为什么。
  * 全有或全无：预检通过后再写；写到一半失败，已写的全部恢复原样。
  * 一轮一个提交：每轮改动成功后提交一次，提交号就是存档点。
  * 回滚不改写历史：退回某个存档点 = 新增一个“内容等于那个存档点”的提交；历史只增不减，回滚本身也能撤销。
所有 git 调用都带超时（经验 L016）。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT = 30
MAX_FILE_BYTES = 512 * 1024
PROTECTED = (".git",)


@dataclass
class Change:
    op: str                 # write | delete | rename
    path: str
    content: str = ""
    to: str = ""            # rename 的目标


class Rejected(Exception):
    """整批预检没通过。reasons 是每条被拒改动的说明。"""

    def __init__(self, reasons):
        super().__init__("；".join(reasons))
        self.reasons = reasons


def patch_signature(changes: list[Change]) -> str:
    h = hashlib.sha1()
    for c in changes:
        h.update(f"{c.op}\0{c.path}\0{c.to}\0{c.content}\0".encode("utf-8"))
    return h.hexdigest()[:12]


class Workspace:
    def __init__(self, root: str):
        self.root = Path(root).resolve()

    # ---------- git ----------
    def _git(self, *args, check=True) -> str:
        r = subprocess.run(["git", "-C", str(self.root), "-c", "user.name=builder", "-c", "user.email=builder@local",
                            "-c", "commit.gpgsign=false", *args],
                           capture_output=True, text=True, timeout=GIT_TIMEOUT)
        if check and r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} 失败：{r.stderr.strip()[:300]}")
        return r.stdout.strip()

    def init(self, files: dict[str, str], message="初始版本") -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q", "-b", "main")
        for p, text in files.items():
            f = self.root / p
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        return self.commit(message)

    def commit(self, message: str) -> str:
        self._git("add", "-A")
        self._git("commit", "-q", "--allow-empty", "-m", message)
        return self.head()

    def head(self) -> str:
        return self._git("rev-parse", "HEAD")

    def tree(self, rev="HEAD") -> str:
        """内容哈希：两个版本内容完全相同，tree 哈希就相同（守卫用它识别“改回旧版本”）。"""
        return self._git("rev-parse", f"{rev}^{{tree}}")

    def history(self) -> list[str]:
        return self._git("rev-list", "HEAD").split()

    def files(self) -> dict[str, str]:
        out = {}
        for p in self._git("ls-files").splitlines():
            out[p] = (self.root / p).read_text(encoding="utf-8")
        return out

    # ---------- 预检 ----------
    def _inside(self, rel: str) -> Path | None:
        if not rel or os.path.isabs(rel) or "\0" in rel:
            return None
        full = (self.root / rel).resolve()
        try:
            parts = full.relative_to(self.root).parts
        except ValueError:
            return None
        if not parts or parts[0] in PROTECTED:
            return None
        return full

    def preflight(self, changes: list[Change]) -> list[str]:
        reasons, targets = [], set()
        if not changes:
            return ["这一批没有任何改动"]
        for i, c in enumerate(changes, 1):
            tag = f"第 {i} 条（{c.op} {c.path}）"
            p = self._inside(c.path)
            if p is None:
                reasons.append(f"{tag}：路径越出项目目录或碰到受保护目录")
                continue
            dest = self._inside(c.to) if c.op == "rename" else p
            if dest is not None and any(a.is_file() for a in dest.parents if a != self.root and self.root in a.parents):
                reasons.append(f"{tag}：目标路径的上级是一个文件")
                continue
            if c.op == "write":
                if len(c.content.encode("utf-8")) > MAX_FILE_BYTES:
                    reasons.append(f"{tag}：内容超过 {MAX_FILE_BYTES // 1024} KB")
                if p.is_dir():
                    reasons.append(f"{tag}：目标是一个目录")
            elif c.op == "delete":
                if not p.is_file():
                    reasons.append(f"{tag}：要删除的文件不存在")
            elif c.op == "rename":
                q = self._inside(c.to)
                if q is None:
                    reasons.append(f"{tag}：改名目标越出项目目录或碰到受保护目录")
                elif not p.is_file():
                    reasons.append(f"{tag}：要改名的文件不存在")
                elif q.exists():
                    reasons.append(f"{tag}：改名目标已存在")
            else:
                reasons.append(f"{tag}：不认识的操作")
            for t in (c.path, c.to) if c.op == "rename" else (c.path,):
                if t in targets:
                    reasons.append(f"{tag}：同一批里重复改动 {t}")
                targets.add(t)
        return reasons

    # ---------- 应用 ----------
    def apply(self, changes: list[Change], message: str) -> str:
        """预检 → 全有或全无地写入 → 提交。返回新的存档点（提交号）。"""
        reasons = self.preflight(changes)
        if reasons:
            raise Rejected(reasons)
        backup = {}  # 路径 → 原内容（None 表示原来不存在）
        try:
            for c in changes:
                for rel in ((c.path, c.to) if c.op == "rename" else (c.path,)):
                    f = self.root / rel
                    if rel not in backup:
                        backup[rel] = f.read_bytes() if f.is_file() else None
                f = self.root / c.path
                if c.op == "write":
                    f.parent.mkdir(parents=True, exist_ok=True)
                    tmp = f.with_name(f.name + ".writing")
                    tmp.write_text(c.content, encoding="utf-8")
                    os.replace(tmp, f)
                elif c.op == "delete":
                    f.unlink()
                elif c.op == "rename":
                    q = self.root / c.to
                    q.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(f), str(q))
        except Exception as e:
            for rel, data in backup.items():  # 恢复原样
                f = self.root / rel
                if data is None:
                    if f.is_file():
                        f.unlink()
                else:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_bytes(data)
            for stray in self.root.rglob("*.writing"):
                stray.unlink()
            raise RuntimeError(f"写入中途失败，已全部恢复原样：{e}") from e
        return self.commit(message)

    def rollback(self, snapshot: str, reason: str) -> str:
        """退回到 snapshot 的内容，但用一个新提交来做，不改写历史。"""
        self._git("rev-parse", "--verify", f"{snapshot}^{{commit}}")
        self._git("read-tree", "-u", "--reset", snapshot)  # 工作区和暂存区都变成那个版本，多出来的文件一并删掉
        return self.commit(f"回滚到 {snapshot[:8]}：{reason}")
