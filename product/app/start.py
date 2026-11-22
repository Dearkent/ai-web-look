#!/usr/bin/env python3
"""一条命令启动 AI 建站工作台。

    python3 product/app/start.py            # 自检 → 启动 → 自动打开浏览器
    python3 product/app/start.py --check    # 只自检，不启动
    python3 product/app/start.py --port 9000 --no-open
    python3 product/app/start.py --setup    # 缺 jsonschema、Pillow 时自动装（start.sh / start.bat 默认这样运行）

只监听本机 127.0.0.1；每次启动生成一个新令牌，别的网页没法偷偷调用它。
生成的网站放在 ~/.aisite/work（可用 --work 改）；学到的知识在 brain/knowledge；模型密钥在 ~/.aisite/models.json（只有你能读）。
"""
from __future__ import annotations

import argparse
import os
import shlex
import socket
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "gen"))


ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))


def _has(mod: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(mod) is not None


def install_cmd(pkgs: list[str]) -> list[str]:
    """在当前 Python 里装依赖的命令：虚拟环境里直接装，否则装到用户目录（不需要管理员权限，不动系统）。"""
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    return [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q"] + ([] if in_venv else ["--user"]) + pkgs


REQUIRED = ["jsonschema>=4.18", "Pillow>=10"]  # 和 requirements.txt 的必需部分一致


def checks() -> list[tuple[str, bool, str]]:
    """返回 [(项目, 是否就绪, 说明或怎么补)]。前三项是必需的；缺浏览器检查不影响启动，只是少一道检查。"""
    out = [("Python 3.9 或更新", sys.version_info >= (3, 9), f"当前 {sys.version.split()[0]}")]
    ok = _has("jsonschema") and _has("referencing") and _has("PIL")
    out.append(("依赖 jsonschema、Pillow", ok, "已安装" if ok else "没装：运行 " + shlex.join(install_cmd(REQUIRED)) + "，或用 --setup 自动装"))
    import browser_check
    ok, why = browser_check.ready()
    out.append(("浏览器检查（Playwright + Chrome）", ok, f"Chrome：{browser_check.find_chrome()}" if ok else why + "；不影响使用，只是少一道检查"))
    work = os.path.expanduser("~/.aisite")
    try:
        os.makedirs(work, exist_ok=True)
        open(os.path.join(work, ".w"), "w").close()
        os.remove(os.path.join(work, ".w"))
        out.append(("可写入 ~/.aisite", True, work))
    except OSError as e:
        out.append(("可写入 ~/.aisite", False, str(e)))
    return out


def free_port(preferred: int) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI 建站工作台")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--work", default=os.path.expanduser("~/.aisite/work"))
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--setup", action="store_true", help="缺必需依赖时自动安装（start.sh / start.bat 默认带上）")
    ns = ap.parse_args(argv)
    rows = checks()
    for name, ok, note in rows:
        print(("✓ " if ok else "✗ ") + name + "：" + note)
    if not rows[1][1] and ns.setup:  # 首次运行：自动装必需依赖（jsonschema、Pillow；装到当前 Python 的用户目录或虚拟环境）
        import subprocess
        print("首次运行，正在安装必需依赖 jsonschema、Pillow……")
        r = subprocess.run(install_cmd(REQUIRED), capture_output=True, text=True)
        if r.returncode != 0:
            print("自动安装失败：" + (r.stderr or r.stdout).strip()[-300:])
        import importlib
        importlib.invalidate_caches()
        import site
        if hasattr(site, "getusersitepackages") and site.getusersitepackages() not in sys.path:
            sys.path.append(site.getusersitepackages())
        rows = checks()
        for name, ok, note in rows[1:2]:
            print(("✓ " if ok else "✗ ") + name + "：" + note)
    if not rows[0][1] or not rows[1][1] or not rows[3][1]:
        print("缺少必需条件，没有启动。")
        return 2
    if ns.check:
        return 0
    from server import serve
    port = free_port(ns.port)
    srv, app = serve(port, ns.work)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"\n工作台已启动：{url}\n（只在本机可访问；关掉这个窗口或按 Ctrl+C 停止）")
    if not ns.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
