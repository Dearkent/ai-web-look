#!/usr/bin/env python3
"""一条命令启动 + 导出 + 没有 Chrome 时的退路。期望在运行前写好。
用法：timeout 300 python3 -I start_test.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "gen"))
sys.path.insert(0, os.path.join(HERE, "..", "text2site"))
os.environ["AISITE_KNOWLEDGE"] = tempfile.mkdtemp(prefix="st-know-")
ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "start.py"), "--check"], capture_output=True, text=True, timeout=60)
expect("自检：列出 Python、依赖、浏览器检查、写入目录四项并通过", r.returncode == 0 and r.stdout.count("✓") == 4, r.stdout)

home = tempfile.mkdtemp(prefix="st-home-")
env = dict(os.environ, HOME=home)
p = subprocess.Popen([sys.executable, "-I", "-u", os.path.join(HERE, "start.py"), "--no-open", "--port", "0", "--work",
                      os.path.join(home, "work")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
url, t0 = None, time.time()
try:
    while time.time() - t0 < 30 and url is None:
        line = p.stdout.readline()
        if "工作台已启动：" in line:
            url = line.split("工作台已启动：", 1)[1].strip()
    expect("一条命令启动：打印出本机地址", bool(url and url.startswith("http://127.0.0.1:")), url)
    page = urllib.request.urlopen(url, timeout=10).read().decode("utf-8")
    expect("启动后页面带本次的令牌", 'name="aisite-token" content="' in page and len(page.split('content="')[1].split('"')[0]) >= 24)
    try:
        urllib.request.urlopen(urllib.request.Request(url + "api/start", data=b'{"text":"x"}', method="POST",
                                                      headers={"Content-Type": "application/json"}), timeout=10)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    expect("启动后的接口：没有令牌就拒绝", code == 403, code)
finally:
    p.terminate()
    p.wait(timeout=10)

# 没有 Chrome 的电脑：照样生成，并说清楚跳过了浏览器检查
import browser_check  # noqa: E402
from make_site import build_one  # noqa: E402
from understand import understand  # noqa: E402

real = browser_check.find_chrome
browser_check.find_chrome = lambda: None
try:
    res = build_one(understand("帮我做个花店的网站"), "soft-ui-evolution", tempfile.mkdtemp(), run_browser=True)
finally:
    browser_check.find_chrome = real
expect("没有 Chrome：网站照样生成，提示跳过了浏览器检查和怎么补", os.path.exists(os.path.join(res["site"], "index.html"))
       and "Chrome" in res["notes"].get("browser_skipped", "") and not res["browser_problems"], res["notes"])

from server import export_zip  # noqa: E402
import io  # noqa: E402
import zipfile  # noqa: E402

d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, "about"))
open(os.path.join(d, "index.html"), "w").write('<a href="./">首</a><a href="about/">关</a><a href="about/#team">队</a>'
                                              '<a href="https://x.cn/">外</a><a href="#top">顶</a><link href="styles.css">')
open(os.path.join(d, "about", "index.html"), "w").write('<a href="../">首</a><form action="../done/"></form>')
z = zipfile.ZipFile(io.BytesIO(export_zip(d, "站")))
home_html, about_html = z.read("站/index.html").decode(), z.read("站/about/index.html").decode()
expect("导出改链接：目录链接改成 index.html，锚点保留，外链、页内锚点、资源不动",
       'href="./index.html"' in home_html and 'href="about/index.html"' in home_html and 'href="about/index.html#team"' in home_html
       and 'href="https://x.cn/"' in home_html and 'href="#top"' in home_html and 'href="styles.css"' in home_html, home_html)
expect("导出改链接：上级目录和表单去向也改", 'href="../index.html"' in about_html and 'action="../done/index.html"' in about_html, about_html)
expect("导出带中文说明（含“表单不会真的发出去”的提醒）", "不会真的" in z.read("站/说明.txt").decode())

print(f"\n一键启动与导出：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
