#!/usr/bin/env python3
"""文案 Agent 第一版（模板，不依赖模型）：按需求简报给每个区块写初稿，写进 content/<语言>.json。

原则：
  * 读得通、和这家店有关（用名字、受众、目标、功能拼出来），但一看就知道是初稿，等真实文案替换。
  * 不编造事实：顾客评价、数据、团队成员、价格一律留成“（待填：…）”，绝不写成像真的一样（编造评价会误导访客）。
  * 有模型时，模型按同一格式产出 content 文件即可替换这一版。
"""
from __future__ import annotations

FOOD = {"Bakery/Cafe", "Restaurant/Food Service", "Brewery/Winery"}
TAGLINE = {"booking": "提前约好，到了就有位置", "sell": "喜欢就带回家", "leads": "说出你的需求，我们来想办法", "signup": "现在报名，马上开始",
           "showcase": "让作品替我们说话", "inform": "先来认识一下我们", "community": "和志同道合的人一起", "recruit": "我们在找你",
           "download": "装上就能用"}
# 首屏副标题：一句话说清访客能得到什么（第十五轮“大师审稿”：不再把功能名堆成一串）
SUB = {"booking": "在线选好时间，来了不用等。", "sell": "看得清、挑得快，下单就送到。", "leads": "把情况告诉我们，很快给你答复。",
       "signup": "几分钟填完，马上就能开始。", "showcase": "做过的作品都在这里，你自己判断。", "inform": "我们是谁、做什么、在哪里，一页看完。",
       "community": "一群想法相近的人，在这里认识彼此。", "recruit": "想把一件事做好的人，我们一起。", "download": "下载安装，打开就能用。"}
CTA = {"booking": "现在就预约", "sell": "挑一件喜欢的", "leads": "聊聊你的需求", "signup": "马上报名", "showcase": "看看更多作品",
       "inform": "了解更多", "community": "加入我们", "recruit": "投递简历", "download": "立即下载"}
FEATURE_COPY = {"booking": ("在线预约", "选好时间和人数，一步提交，不用打电话排队。"),
                "contact_form": ("随时联系", "留下需求和联系方式，我们会尽快回复。"),
                "map": ("好找", "地址、营业时间和路线都写清楚了。"),
                "catalog": ("一眼看清", "内容和价格都列明白，来之前心里有数。"),
                "gallery": ("真实作品", "放的都是做过的案例，不靠嘴说。"),
                "faq": ("常见问题", "大家常问的，先替你回答好。"),
                "blog": ("最新动态", "新品、活动和消息都在这里。"),
                "multilingual": ("中英双语", "外地和外国朋友也看得懂。")}
BENEFITS = {
    "food": [("现做现卖", "每一份都是点了才做。"), ("坐得舒服", "座位宽松，适合一个人待会儿，也适合几个人聊聊。"),
             ("不用排队", "提前在线预约，到店就有位置。")],
    "service": [("专业", "做这一行很多年，知道你担心什么。"), ("省心", "流程说清楚，进度随时能问。"), ("说到做到", "约好的时间和价格不临时变。")],
    "creative": [("有想法", "每个项目都从你的目标出发。"), ("看得见", "过程中给你看草稿，不闷头做。"), ("准时交付", "约好的时间就交。")],
    "tech": [("上手快", "几分钟就能用起来。"), ("稳定", "关键数据有备份，出了问题有人管。"), ("按需付费", "用多少付多少。")],
}
FIELD_ZH = {"date": "日期", "time": "时间", "people": "人数", "phone": "电话", "name": "称呼", "message": "想说的话", "email": "邮箱",
            "company": "公司", "team_size": "团队人数", "brief": "需求简述", "budget": "预算"}
FOOD_ITEMS = {"Bakery/Cafe": ["拿铁", "美式", "手冲", "燕麦拿铁", "可颂", "芝士蛋糕", "抹茶拿铁", "柠檬茶"],
              "Restaurant/Food Service": ["招牌菜", "时令小炒", "家常汤", "主食", "凉菜", "甜品", "饮品", "套餐"],
              "Brewery/Winery": ["招牌精酿", "小麦啤", "IPA", "黑啤", "果啤", "无醇", "小食", "拼盘"]}


def _group(ptype):
    if ptype in FOOD:
        return "food"
    if ptype in ("Portfolio/Personal", "Creative Agency", "Photography Studio", "Marketing Agency", "Wedding/Event Planning"):
        return "creative"
    if ptype in ("SaaS (General)", "AI/Chatbot Platform", "Micro SaaS", "Developer Tool / IDE", "Open Source Project Landing"):
        return "tech"
    return "service"


def _hero_heading(ptype: str, goal: str, svcs: list[str]) -> str:
    """首屏标题：有服务名就说“做什么 + 怎么找我们”，18 个字以内；放不下就只用第一项；再放不下用通用承诺。"""
    if svcs and ptype not in FOOD:
        tail = {"Legal Services": "找专业律师", "Dental Practice": "在线约好再来", "Medical Clinic": "在线约好再来"}.get(
            ptype, "在线就能约" if goal == "booking" else "交给我们")
        for picked in (svcs[:2], svcs[:1]):
            h = ("与" if ptype == "Legal Services" else "、").join(picked) + "，" + tail
            if len(h) <= 18:
                return h
    if ptype in FOOD:  # 吃喝的店：说“来坐坐”，比“先来认识一下我们”有温度
        return {"Bakery/Cafe": "进来坐坐，喝杯好咖啡", "Restaurant/Food Service": "进来坐坐，吃顿好的",
                "Brewery/Winery": "进来坐坐，喝一杯"}[ptype] if goal in ("booking", "inform") else TAGLINE.get(goal, "欢迎")
    return TAGLINE.get(goal, "欢迎")


def _service_body(ptype: str, svc: str, feats: list[str]) -> str:
    """服务卡片的一句说明：只说网站上真能做的事（预约/留言），不替店家承诺效果和价格。"""
    if "booking" in feats:
        return f"可以在线预约{svc}，来之前先把情况告诉我们。"
    if "contact_form" in feats:
        return f"想了解{svc}，留下联系方式，我们来联系你。"
    return f"想了解{svc}，欢迎来问。"


def write_copy(brief: dict, wires: dict) -> dict:
    name, aud = brief.get("site_name", "我的网站"), brief["audience"]["primary"]
    named = name not in ("", "我的网站")  # 没给名字时，标题里不写“我的网站”这种占位名
    ptype = brief["product_type"]["value"]
    p0 = brief["goals"][0]["kind"]
    feats = [f["kind"] for f in brief["features"]]
    svcs = [x["name"] for x in brief.get("services", [])]
    benefits = BENEFITS[_group(ptype)]
    out = {}
    for pid, w in wires.items():
        page = out.setdefault(pid, {})
        for s in w["sections"]:
            t, c = s["type"], {}
            slots = s.get("slots", {})
            if t == "hero":
                # 标题只说一个承诺（名字在页头和网页标题里已经有了）；副标题一句话说好处。
                # 用户说了服务名就用上（第二十二轮：律所和牙科首屏一模一样，读不出是做什么的）
                c = {"heading": _hero_heading(ptype, p0, svcs), "body": SUB.get(p0, "")}
            elif t == "features" and s["id"] == "services":
                c = {"heading": "我们能帮你", "items": [{"title": x, "body": _service_body(ptype, x, feats)} for x in svcs]}
            elif t == "steps" and s["id"] == "how" and p0 == "signup":
                c = {"heading": "怎么开始", "items": [{"title": "留下联系方式", "body": "在“报名”页填好称呼和联系方式，一分钟就够。"},
                                                    {"title": "我们联系你", "body": "收到后会尽快回复，告诉你下一步怎么做。"},
                                                    {"title": "开始使用", "body": "按我们发给你的方式开始，有问题随时问。"}]}
            elif t == "steps" and s["id"] == "how":
                meet = {"Legal Services": "按约好的时间来面谈", "Dental Practice": "按约好的时间到诊所", "Medical Clinic": "按约好的时间到诊所"}.get(
                    ptype, "按约好的时间到店" if _group(ptype) in ("food", "service") else "按约好的时间开始")
                c = {"heading": "怎么预约", "items": [{"title": "选时间", "body": "在“预约”页选好" + ("项目和" if svcs else "") + "方便的时间，留下称呼和电话。"},
                                                    {"title": "等确认", "body": "我们看到后会联系你确认，有变动也会提前说。"},
                                                    {"title": "来见面", "body": meet + "，不用排队等。"}]}
            elif t in ("value-props", "features"):
                items = [FEATURE_COPY[f] for f in feats if f in FEATURE_COPY][:3] if t == "features" else []
                items = (items + benefits)[:slots.get("items", {}).get("count", 3)]
                c = {"heading": ("为什么选" + (name if named else "我们")) if t == "value-props" else "你能在这里做什么",
                     "items": [{"title": a, "body": b} for a, b in items]}
            elif t == "menu":
                names = FOOD_ITEMS.get(ptype, [f"项目 {i + 1}" for i in range(8)])
                n = slots.get("items", {}).get("count", 4)
                # 价格不知道就不写（不在每一行挂“价格待填”）；待补的在体检里提醒
                c = {"heading": "菜单" if ptype in FOOD else "项目", "items": [{"title": x, "body": ""} for x in names[:n]]}
            elif t == "gallery":
                n = slots.get("items", {}).get("count", 6)
                c = {"heading": {"creative": "作品", "food": "店里", "tech": "产品"}.get(_group(ptype), "案例"), "items": [{"title": "", "body": ""} for i in range(n)]}
            elif t in ("testimonials", "stats", "team", "logos", "pricing", "comparison"):
                label = {"testimonials": "真实顾客评价", "stats": "真实数据", "team": "团队成员", "logos": "合作伙伴标志",
                         "pricing": "价格方案", "comparison": "对比内容"}[t]
                n = slots.get("items", {}).get("count", 3)
                c = {"heading": {"testimonials": "大家怎么说", "stats": "一些数字", "team": "我们是谁", "logos": "合作过的伙伴",
                                 "pricing": "价格", "comparison": "怎么选"}[t],
                     "items": [{"title": f"（待填：{label}）", "body": ""} for _ in range(n)]}
            elif t == "steps":
                c = {"heading": "怎么开始", "items": [{"title": "1. 看看我们", "body": "了解提供什么。"}, {"title": "2. 联系或预约", "body": "选个方便的时间。"},
                                                    {"title": "3. 到店或开工", "body": "剩下的交给我们。"}]}
            elif t == "faq":
                # 给访客看的问题（D31：以前把建站时问用户的问题当成了网站上的常见问题）。答案不能替店家编，留“待填”
                qa = []
                if "booking" in feats:
                    qa += [("要提前多久预约？", "（待填：例如至少提前一天）"), ("可以改约或取消吗？", "（待填：改约和取消的规则）")]
                if any(g["kind"] == "sell" for g in brief["goals"]):
                    qa += [("怎么付款？", "（待填：支持的付款方式）"), ("多久能收到？", "（待填：发货或交付时间）")]
                qa += [("营业时间？", "（待填：营业时间）"),
                       ("在哪里？怎么过来？", "“到店”页有地址和地图。" if "visit" in wires else "（待填：地址和交通）"),
                       ("怎么联系你们？", "页面上方有联系方式和表单。" if ("contact" in wires or "booking" in wires) else "（待填：电话或邮箱）")]
                c = {"heading": "常见问题", "items": [{"title": a, "body": b} for a, b in qa[:slots.get("items", {}).get("count", 5)]]}
            elif t == "cta":
                c = {"heading": CTA.get(p0, "了解更多")}
            elif t in ("booking-form", "contact-form"):
                c = {"heading": "预约" if t == "booking-form" else "联系我们", "labels": FIELD_ZH}
            elif t == "map":
                c = {"hours": "（待填：地址和营业时间）"}
            elif t == "blog-list":
                c = {"items": [{"title": "（待填：第一篇动态）", "body": ""}]}
            elif t == "content":
                if pid.endswith("-done"):
                    c = {"heading": "已收到", "body": "我们会尽快联系你。"}
                elif pid == "privacy":
                    c = {"body": (f"收集什么：你在{name}网站表单里填写的姓名、联系方式和留言（待填：按实际表单核对）。"
                                  "用来做什么：只用于回复你的预约或咨询，不出售，也不提供给其他人（待填：如果用了表单服务商，写明是哪一家）。"
                                  "保存多久：处理完后保存不超过（待填：例如 6 个月），到期删除。"
                                  "你的权利：可以随时查询、更正、删除你的信息，或撤回同意，请联系（待填：电话或邮箱）。"
                                  "更新日期：（待填）。上线前请找专业人士确认本说明。")}
                elif pid == "about":
                    c = {"heading": f"关于{name}" if named else "关于我们", "body": f"（待填：{name if named else '你'}的故事——为什么开始、想为{aud}做什么）"}
                else:
                    c = {"heading": "（待填）"}
            page[s["id"]] = c
    return out
