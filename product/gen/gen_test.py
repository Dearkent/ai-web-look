#!/usr/bin/env python3
"""生成器测试：网站结构是唯一事实来源——导航、面包屑、sitemap、路由都必须与它一致。"""
import json, os, re, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from generate import generate  # noqa: E402
EX = os.path.join(HERE, "..", "examples")
ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


for ex in ("cafe", "saas", "portfolio"):
    site = json.load(open(os.path.join(EX, ex, "site.json"), encoding="utf-8"))
    out = tempfile.mkdtemp(prefix="gen-")
    try:
        written = generate(os.path.join(EX, ex), out)
        expect(f"{ex}：每个页面都生成了", len(written) == len(site["pages"]), written)
        header = [p for p in site["pages"] if p["nav"]["header"]]
        for f in written:
            html = open(os.path.join(out, f), encoding="utf-8").read()
            nav = re.search(r'<nav aria-label="主导航">(.*?)</nav>', html).group(1)
            if len(re.findall(r"<a ", nav)) != len(header):
                expect(f"{ex}：{f} 的主导航条目数与网站结构一致", False, nav)
                break
        else:
            expect(f"{ex}：所有页面的主导航都来自网站结构", True)
        sm = open(os.path.join(out, "sitemap.xml"), encoding="utf-8").read()
        want = [p for p in site["pages"] if p.get("seo", {}).get("index", True) is not False]
        expect(f"{ex}：sitemap 只收录允许索引的页面（{len(want)} 个）", sm.count("<loc>") == len(want))
        expect(f"{ex}：sitemap 用完整网址", all(l.startswith("https://") for l in re.findall(r"<loc>(.*?)</loc>", sm)))
    finally:
        shutil.rmtree(out)

# 缺 base_url：不生成不合规的 sitemap
tmp = tempfile.mkdtemp(prefix="gen-")
try:
    shutil.copytree(os.path.join(EX, "cafe"), os.path.join(tmp, "p"))
    sp = os.path.join(tmp, "p", "site.json")
    d = json.load(open(sp, encoding="utf-8")); d.pop("base_url"); json.dump(d, open(sp, "w", encoding="utf-8"), ensure_ascii=False)
    generate(os.path.join(tmp, "p"), os.path.join(tmp, "out"))
    expect("缺 base_url：不生成 sitemap.xml", not os.path.exists(os.path.join(tmp, "out", "sitemap.xml")))
    # 面包屑：预约成功页在“首页 / 预约座位”之下
    h = open(os.path.join(tmp, "out", "booking", "done", "index.html"), encoding="utf-8").read()
    expect("面包屑：按父子关系生成（相对路径）", '<a href="../../">首页</a> / <a href="../">预约座位</a> / 预约成功' in h, h[:600])
    # 自定义脚本被带进每一页
    os.makedirs(os.path.join(tmp, "p", "custom"))
    open(os.path.join(tmp, "p", "custom", "site.js"), "w").write("console.log(1)")
    generate(os.path.join(tmp, "p"), os.path.join(tmp, "out"))
    expect("自定义脚本：每页都引用", all('site.js" defer' in open(os.path.join(r, f), encoding="utf-8").read()
                                       for r, _, fs in os.walk(os.path.join(tmp, "out")) for f in fs if f == "index.html"))
    # 放在任意子目录下也能用：不许出现以 / 开头的站内链接和资源
    absolute = [f for r, _, fs in os.walk(os.path.join(tmp, "out")) for f in fs if f.endswith(".html")
                and re.search(r'(href|src|action)="/', open(os.path.join(r, f), encoding="utf-8").read())]
    expect("相对路径：页面里没有以 / 开头的站内链接或资源", not absolute, absolute)
finally:
    shutil.rmtree(tmp)
print(f"生成器测试：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
