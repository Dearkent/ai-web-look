#!/usr/bin/env python3
"""上线前体检的测试：生成的网站四项里前三项满分；故意做坏的样本每类问题都要抓到。期望在运行前写好。
用法：timeout 200 python3 -I site_audit_test.py"""
import os
import sys
import tempfile

os.environ["AISITE_KNOWLEDGE"] = tempfile.mkdtemp(prefix="sa-know-")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "text2site"))
import site_audit  # noqa: E402
from make_site import build_one  # noqa: E402
from understand import understand  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


r = build_one(understand("帮我做个咖啡馆的网站，叫巷口咖啡，可以在线预约座位"), "soft-ui-evolution", tempfile.mkdtemp())
a = site_audit.audit(r["site"], r["browser_problems"])
expect("生成的网站：SEO、性能、无障碍都是 100", a["scores"]["SEO"] == 100 and a["scores"]["性能"] == 100 and a["scores"]["无障碍"] == 100, a["scores"])
fails = [x["msg"] for x in a["items"] if not x["ok"] and not x["pending"]]
expect("生成的网站：合规只差“待填”内容（需要用户提供真实信息）", len(fails) == 1 and "待填" in fails[0], fails)
pend = [x["msg"] for x in a["items"] if x["pending"]]
expect("没填域名、备案号时，sitemap 和备案列为“上线时再做”，不扣分", any("sitemap" in m for m in pend) and any("备案" in m for m in pend), pend)
expect("表单都要勾选同意隐私政策", any(x["ok"] and "勾选同意" in x["msg"] for x in a["items"]))

b = site_audit.audit(os.path.join(HERE, "..", "..", "evals", "fixtures", "badsite4"))
msgs = " | ".join(x["msg"] for x in b["items"] if not x["ok"])
for key, what in (("描述", "缺描述或太短"), ("一级标题不是一个", "一级标题不是一个"), ("挡住首屏", "脚本挡首屏"), ("外部资源", "依赖境外字体"),
                  ("没写宽高", "图片没写宽高"), ("没标明语言", "缺语言"), ("跳级", "标题跳级"), ("区域标记", "缺页面区域"),
                  ("没有文字", "空链接"), ("没有隐私政策页", "表单没隐私政策"), ("没有“同意隐私政策”", "表单没同意勾选"), ("广告法", "广告法风险词")):
    hit = key in msgs
    expect(f"做坏的样本：抓到“{what}”", hit, msgs[:300])
expect("做坏的样本：四项分数都明显偏低", all(v < 70 for v in b["scores"].values()), b["scores"])

print(f"\n上线前体检：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
