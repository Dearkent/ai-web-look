#!/usr/bin/env python3
"""反向测试原型：逐个拆掉保护措施，端到端测试必须失败（经验 L015）。"""
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
CUTS = [  # (名称, 文件, 原文, 改成)
    ("拆掉 写入失败时的恢复", "workspace.py", "            for rel, data in backup.items():  # 恢复原样", "            for rel, data in []:"),
    ("拆掉 越出目录检查", "workspace.py", "        if not parts or parts[0] in PROTECTED:\n            return None", "        pass"),
    ("拆掉 上级是文件检查", "workspace.py", "if dest is not None and any(", "if False and any("),
    ("拆掉 回滚（变成什么都不做）", "workspace.py", '        self._git("read-tree", "-u", "--reset", snapshot)', "        pass"),
    ("拆掉 每轮提交", "workspace.py", "        return self.commit(message)\n\n    def rollback", "        return self.head()\n\n    def rollback"),
    ("拆掉 把反馈写回给修复者", "fix_loop.py", '            hint = (decision.to_model + "\\n" if decision.to_model else "")', '            hint = ""\n            _x = (decision.to_model + "\\n" if decision.to_model else "")'),
    ("拆掉 循环兜底上限", "fix_loop.py", '            decision = Decision("stop", "L00"', '            decision = Decision("stop", ""'),
    ("拆掉 补丁没落地时不报代码状态", "fix_loop.py", "code_state=ws.tree() if applied else \"\"", "code_state=ws.tree()"),
]
caught = 0
for name, fname, old, new in CUTS:
    src = open(os.path.join(HERE, fname), encoding="utf-8").read()
    if old not in src:
        print(f"无法施加  {name}（源码已变，更新本脚本）"); continue
    tmp = tempfile.mkdtemp(prefix="pm-")
    try:
        shutil.copytree(HERE, os.path.join(tmp, "proto"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(TOOLS, os.path.join(tmp, "tools"), ignore=shutil.ignore_patterns("__pycache__"))
        open(os.path.join(tmp, "proto", fname), "w", encoding="utf-8").write(src.replace(old, new, 1))
        try:
            r = subprocess.run([sys.executable, "-I", os.path.join(tmp, "proto", "proto_test.py")],
                               capture_output=True, text=True, timeout=120)
            failed = r.returncode != 0
            why = next((l for l in (r.stdout + r.stderr).splitlines() if l.startswith(("失败", "Traceback"))), "")
        except subprocess.TimeoutExpired:
            failed, why = True, "超时"
        caught += failed
        print(("测试发现  " if failed else "测试没发现  ") + name + (f"  ← {why[:70]}" if failed else ""))
    finally:
        shutil.rmtree(tmp)
print(f"原型反向测试：{caught}/{len(CUTS)} 被发现")
sys.exit(0 if caught == len(CUTS) else 1)
