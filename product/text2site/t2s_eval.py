#!/usr/bin/env python3
"""文字 → 网站 评测集：期望答案在运行前写好，不按结果改答案。

每句检查：产品类型、首要目标（P0）、必须识别出的功能、风格点名是否生效；
然后整条流水线（理解 → 规划 → 文案 → 生成 → 图纸检查 → 真实浏览器检查）必须 0 图纸错误、0 浏览器问题。
用法：timeout 600 python3 -I -u t2s_eval.py [--no-browser]
"""
import os, shutil, sys, tempfile
# 评测的是代码，不是某个用户喂过的知识：默认用空知识库（喂养学到的东西另有 selflearn_test 测）
os.environ.setdefault("AISITE_KNOWLEDGE", tempfile.mkdtemp(prefix="t2s-know-"))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from make_site import build_one  # noqa: E402
from styles import options  # noqa: E402
from understand import understand  # noqa: E402

CASES = [  # (句子, 期望产品类型, 期望 P0 目标, 必须有的功能, 期望第一个风格（None 表示不检查）)
    ("帮我做个咖啡馆的网站，叫“巷口咖啡”，能让附近上班的人在线预约座位，顺便看看菜单，别太花哨",
     "Bakery/Cafe", "booking", ["booking", "catalog"], None),
    ("我是独立插画师，想要一个作品集网站，让品牌方能看到作品并联系我约稿，要有点动感",
     "Portfolio/Personal", "showcase", ["gallery", "contact_form"], "motion-driven"),
    ("我们做了一个团队记账的 SaaS，要一个官网让人注册试用，大客户可以预约演示，要中英双语",
     "SaaS (General)", "signup", ["multilingual"], None),
    ("开了家牙科诊所，想让病人在网上挂号，页面要干净简洁", "Dental Practice", "booking", ["booking"], "minimalism-and-swiss-style"),
    ("帮律师事务所做个官网，主要是让潜在客户咨询，显得专业稳重", "Legal Services", "leads", ["contact_form"], None),
    ("我在大理开民宿，想让游客直接在网站上预订房间，风格清新自然", "Hotel/Hospitality", "booking", ["booking"], "organic-biophilic"),
    ("卖手工花束的小花店，想在网上展示商品，客户可以下单", "Florist/Plant Shop", "sell", ["catalog"], None),
    ("健身房招新会员，想让人报名体验课，要酷炫一点", "Fitness/Gym App", "signup", ["contact_form"], "motion-driven"),
    ("社区里的火锅店，想放菜单和地址，方便大家找到我们", "Restaurant/Food Service", "inform", ["catalog", "map"], None),
    ("做一个年度设计峰会的报名页面，介绍嘉宾和议程", "Conference / Symposium Landing Page", "signup", ["contact_form"], None),
    ("我们是一家装修公司，想展示案例，让业主留下联系方式报价", "Home Decoration & Interior Design", "showcase", ["gallery", "contact_form"], None),
    ("宠物医院的网站，可以预约看诊，告诉大家怎么走", "Veterinary Clinic", "booking", ["booking", "map"], None),
    ("给我们的公益基金会做个网站，介绍项目，招募志愿者", "Non-profit/Charity", "inform", ["contact_form"], None),
    ("想做一个卖二手相机的网店，不要暗黑风格，要复古一点", "E-commerce", "sell", ["catalog"], "vintage-analog-retro-film"),
]

# 留出集：在修改词表之前写好，只用来检验，不用来调词表（防止只对评测集有效）
HELD_OUT = [
    ("我开了家瑜伽馆，想让学员在线约课", "Fitness/Gym App", "booking", ["booking"], None),
    ("帮我们的烘焙工作室做个网站，接受蛋糕定制预订", "Bakery/Cafe", "booking", ["booking"], None),
    ("社区诊所，想让居民在线挂号", "Medical Clinic", "booking", ["booking"], None),
    ("我是摄影师，想展示作品，也接拍摄预约", "Portfolio/Personal", "showcase", ["gallery", "booking"], None),
    ("做一个开源项目的介绍页，让开发者了解和下载", "Open Source Project Landing", "inform", [], None),
    ("小区门口的理发店，想让熟客在网上排号预约", "Beauty/Spa/Wellness Service", "booking", ["booking"], None),
]
ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


understood = 0
for text, ptype, p0, feats, style in CASES:
    b = understand(text)
    got_feats = {f["kind"] for f in b["features"]}
    first = options(b)[0]["id"]
    checks = [b["product_type"]["value"] == ptype, b["goals"][0]["kind"] == p0, set(feats) <= got_feats,
              style is None or first == style]
    understood += all(checks)
    expect(f"理解：{text[:18]}…", all(checks),
           f"类型 {b['product_type']['value']} / P0 {b['goals'][0]['kind']} / 功能 {sorted(got_feats)} / 风格 {first}")
print(f"理解准确：{understood}/{len(CASES)}")
held = 0
for text, ptype, p0, feats, style in HELD_OUT:
    b = understand(text)
    got = {f["kind"] for f in b["features"]}
    good = b["product_type"]["value"] == ptype and b["goals"][0]["kind"] == p0 and set(feats) <= got
    held += good
    print(("留出·通过  " if good else "留出·失败  ") + text[:20] + ("" if good else f"  类型 {b['product_type']['value']} / P0 {b['goals'][0]['kind']} / 功能 {sorted(got)}"))
print(f"留出集理解：{held}/{len(HELD_OUT)}（只报告，不计入通过与否）")

browser = "--no-browser" not in sys.argv
built = 0
for text, *_ in CASES:
    b = understand(text)
    tmp = tempfile.mkdtemp(prefix="t2s-")
    try:
        r = build_one(b, options(b)[0]["id"], tmp, browser)
        good = r["pages"] and not r["blueprint_errors"] and not r["browser_problems"]
        built += bool(good)
        expect(f"生成：{text[:18]}…（{len(r['pages'])} 页）", good, (r["blueprint_errors"] + r["browser_problems"])[:3])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
print(f"整站生成且检查全过：{built}/{len(CASES)}")
print(f"文字建站评测：理解 {understood}/{len(CASES)}，留出 {held}/{len(HELD_OUT)}，生成 {built}/{len(CASES)}")
sys.exit(1 if bad else 0)
