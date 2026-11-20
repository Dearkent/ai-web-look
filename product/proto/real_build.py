#!/usr/bin/env python3
"""真实构建：图纸检查 → 生成网站 → 真实浏览器检查。修复回路的 build(files) 用它。

图纸本身有错就先只报图纸错误（此时生成没有意义）；图纸通过才生成并用 Chrome 检查。
报错前缀：“图纸·”来自检查器，“浏览器·”来自 Chrome。
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "gen")):
    sys.path.insert(0, p)
import browser_check  # noqa: E402
import check_blueprints  # noqa: E402
import generate  # noqa: E402


def build(files: dict) -> list[str]:
    tmp = tempfile.mkdtemp(prefix="rb-")
    try:
        proj = os.path.join(tmp, "project")
        for rel, text in files.items():
            f = os.path.join(proj, rel)
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(text)
        rep = check_blueprints.check(proj)
        if rep.errors:
            return [f"图纸·{e['code']}：{e['where']} → {e['msg']}（下一步：{e['hint']}）" for e in rep.errors]
        try:
            generate.generate(proj, os.path.join(tmp, "site"))
        except Exception as e:  # 生成器自身出错也是报错，不让回路崩掉
            return [f"生成失败：{type(e).__name__} {str(e)[:200]}"]
        return browser_check.check(os.path.join(tmp, "site"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
