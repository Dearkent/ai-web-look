#!/usr/bin/env python3
"""风格可选的测试：三个候选必须是三种不同观感；所有家族 × 多个行业的文字对比度达标；文案初稿不编造事实。"""
import os, sys, tempfile
os.environ.setdefault("AISITE_KNOWLEDGE", tempfile.mkdtemp(prefix="st-know-"))  # 测代码，不受用户喂过的知识影响
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import styles  # noqa: E402
from copywriter import write_copy  # noqa: E402
from plan import plan  # noqa: E402
from understand import understand  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


texts = ["帮我做个咖啡馆的网站，能在线预约", "律师事务所官网，让客户咨询", "卖鲜花的网店", "团队记账 SaaS 官网，注册试用",
         "插画师作品集，接约稿", "牙科诊所，在线挂号"]
for t in texts:
    o = styles.options(understand(t))
    fams = [styles.family(x["id"]) for x in o]
    expect(f"三个候选观感各不相同：{t[:10]}", len(o) == 3 and len(set(fams)) == 3, fams)
o = styles.options(understand("咖啡馆网站，要可爱一点"))
expect("用户点名的风格排第一", o[0]["id"] == "claymorphism" and o[0]["why"] == "你点名的风格", o[0])
o = styles.options(understand("想做一个网店，不要暗黑风格"))
expect("用户说“不要暗黑”：整个深色家族都不出现", all(styles.family(x["id"]) != "dark" for x in o), [x["id"] for x in o])

worst = 99
for fam_style in ["vibrant-and-block-based", "soft-ui-evolution", "minimalism-and-swiss-style", "glassmorphism", "dark-mode-oled",
                  "editorial-grid-magazine", "claymorphism", "neubrutalism", "cyberpunk-ui", "aurora-ui"]:
    for ptype in ["Bakery/Cafe", "SaaS (General)", "Legal Services", "Florist/Plant Shop", "Portfolio/Personal", "Medical Clinic"]:
        p = styles.palette(ptype, styles.profile(fam_style)["dark"], styles.family(fam_style), styles.style_hexes(fam_style))
        c = min(styles.contrast(p["foreground"], p["background"]), styles.contrast(p["on-primary"], p["primary"]),
                styles.contrast(p["band-ink"], p["band"]), styles.contrast(p["muted"], p["background"]),
                styles.contrast(p["link"], p["background"]),  # 链接也是正文文字（D19）
                styles.contrast(p["link"], p["band"]) if (styles._lum(p["band"]) < 0.3) == (styles._lum(p["background"]) < 0.3) else 9)  # 色带上的链接（D24）
        worst = min(worst, c)
        if c < 4.5:
            expect(f"对比度：{fam_style} × {ptype}", False, round(c, 2))
expect(f"对比度：10 种风格 × 6 个行业，文字对比度都不低于 4.5（最低 {worst:.2f}）", worst >= 4.5)

b = understand("健身房官网，让人报名体验课")
res = plan(b)
content = res["files"]["content/zh-CN.json"]
fake = [it["title"] for page in content.values() for sec in page.values() for it in (sec.get("items") or [])
        if any(k in it["title"] for k in ("评价", "数据", "成员", "价格方案"))]
expect("文案初稿不编造评价、数据、团队、价格：都标“待填”", all(t.startswith("（待填") for t in fake), fake)
print(f"风格与文案：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
