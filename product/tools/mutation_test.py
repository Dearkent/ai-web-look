#!/usr/bin/env python3
"""变异测试：把一个合格的示例故意改坏，每种改法都必须被 check_blueprints 报出预期的错误码。
检查器“0 错误”只有在它能抓住这些故意的错误时才可信（经验 L014：要有反例）。

用法：python3 -I mutation_test.py <合格示例目录>
"""
import copy, json, os, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_blueprints as cb  # noqa: E402

SRC = sys.argv[1]


def J(rel):
    return json.load(open(os.path.join(SRC, rel), encoding="utf-8"))


def page(site, pid):
    return next(p for p in site["pages"] if p["id"] == pid)


# 每项：(名称, 期望错误码, 改哪个文件, 改法)
MUTATIONS = [
    ("按钮跳到不存在的页面", "P050", "pages/home.json",
     lambda d: d["sections"][1]["actions"][0]["target"].update(page="reserve")),
    ("锚点指向不存在的区块", "P051", "pages/home.json",
     lambda d: d["sections"][1]["actions"].append({"id": "x", "label": "看看", "target": {"section": "nope"}})),
    ("表单提交到未声明的功能", "P052", "pages/booking.json",
     lambda d: d["sections"][1]["actions"][0]["target"].update(submit="F9")),
    ("同页区块 id 重复", "P053", "pages/menu.json",
     lambda d: d["sections"][2].update(id="list")),
    ("动效超过风格档位", "P054", "pages/home.json",
     lambda d: d["sections"][1]["motion"][0].update(tier="Complex")),
    ("页面覆盖引用不存在的令牌", "P056", "pages/home.json",
     lambda d: d.update(style_overrides={"tokens": {"accent": "{color.brand-pink}"}})),
    ("区块绑定未声明的数据实体", "P057", "pages/menu.json",
     lambda d: d["sections"][1].update(data="dish")),
    ("引用简报里没有的素材", "P059", "pages/home.json",
     lambda d: d["sections"][1]["slots"]["image"].update(asset="A9")),
    ("站点指向错误的简报", "S020", "site.json",
     lambda d: d.update(brief_id="other-brief")),
    ("页面路径重复", "S021", "site.json",
     lambda d: page(d, "visit").update(path="/menu")),
    ("父页面成环", "S022", "site.json",
     lambda d: page(d, "home").update(parent="booked")),
    ("没有首页", "S023", "site.json",
     lambda d: page(d, "home").update(path="/home")),
    ("线框文件缺失", "S024", "site.json",
     lambda d: page(d, "visit").update(wireframe="pages/where.json")),
    ("P0 目标无人负责", "S025", "site.json",
     lambda d: [p.update(serves_goals=[g for g in p.get("serves_goals", []) if g != "G1"]) for p in d["pages"]]),
    ("P0 功能无页面实现", "S026", "site.json",
     lambda d: page(d, "booking").update(implements_features=[])),
    ("流程两步之间没有链接", "S028", "site.json",
     lambda d: d["flows"][1].update(steps=["booked", "visit"]) or page(d, "visit")["nav"].update(header=False, footer=False)),
    ("流程点击次数超限", "S029", "site.json",
     lambda d: d["flows"][0].update(max_clicks=1)),
    ("P0 目标没有流程", "S030", "site.json",
     lambda d: d.update(flows=[f for f in d["flows"] if f["goal"] != "G1"])),
    ("简报要求的语言网站没有", "S034", "brief.json",
     lambda d: d.update(locales=["zh-CN", "en"])),
    ("流程完成按钮不存在", "S031", "site.json",
     lambda d: d["flows"][0].update(completes_with={"action": "pay"})),
    ("分工依赖成环", "W040", "site.json",
     lambda d: d["work_plan"][0].update(depends_on=["W2"])),
    ("线框交给了错误的 Agent", "W041", "site.json",
     lambda d: d["work_plan"][2].update(agent="engineer")),
    ("阻塞问题未回答", "B010", "brief.json",
     lambda d: d["open_questions"][0].update(blocking=True)),
    ("使用已弃用的风格 ID", "B001", "brief.json",
     lambda d: d["style_preference"].update(style_ids=["hero-centric-design"])),
    ("未知 Agent", "B001", "site.json",
     lambda d: d["work_plan"][0].update(agent="designer")),
    ("色值写死而非引用令牌", "B001", "pages/home.json",
     lambda d: d.update(style_overrides={"tokens": {"accent": "#FF00AA"}})),
    ("布局用自由文本", "B001", "pages/home.json",
     lambda d: d["sections"][1]["layout"].update(variant="左图右文，留白大一点")),
    # 第四轮补齐：之前没有反例的 6 个码（含 3 个提醒级）
    ("缺少需求简报文件", "B000", "brief.json", lambda d: "__delete__"),
    ("区块实现的功能不在简报里", "P058", "pages/visit.json",
     lambda d: d["sections"][1].update(feature="F9")),
    ("流程里的页面不存在", "S027", "site.json",
     lambda d: d["flows"][1].update(steps=["home", "nowhere"])),
    ("知识库里没有这一档动效参数（提醒）", "P055", "pages/home.json",
     lambda d: d["sections"][3].update(motion=[{"category": "Carousel / Auto-Rotation", "tier": "Subtle"}])),
    ("负责转化的页面没有主按钮（提醒）", "P060", "pages/menu.json",
     lambda d: d["sections"][2]["actions"][0].update(primary=False)),
    ("网站风格偏离简报候选（提醒）", "S033", "site.json",
     lambda d: d["style"].update(style_id="flat-design")),
]


def run():
    base = cb.check(SRC)
    if base.errors:
        print("基线示例本身有错误，变异测试无意义：", [e["code"] for e in base.errors])
        return 1
    caught, missed = 0, []
    for name, code, rel, fn in MUTATIONS:
        tmp = tempfile.mkdtemp(prefix="mut-")
        try:
            shutil.copytree(SRC, tmp, dirs_exist_ok=True)
            d = J(rel)
            if fn(d) == "__delete__":
                os.remove(os.path.join(tmp, rel))
            else:
                json.dump(d, open(os.path.join(tmp, rel), "w", encoding="utf-8"), ensure_ascii=False)
            got = [i["code"] for i in cb.check(tmp).items]  # 错误和提醒都算
            if code in got:
                caught += 1
                extra = f"（另报 {sorted(set(got) - {code})}）" if set(got) - {code} else ""
                print(f"抓到  {code}  {name}{extra}")
            else:
                missed.append(name)
                print(f"漏掉  {code}  {name}  实际报出：{got}")
        finally:
            shutil.rmtree(tmp)
    print(f"变异测试：{caught}/{len(MUTATIONS)} 被抓到")
    return 0 if not missed else 1


if __name__ == "__main__":
    sys.exit(run())
