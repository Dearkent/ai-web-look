#!/usr/bin/env python3
"""需求简报 → 网站结构 + 页面线框 + 设计规范（DESIGN.md、tokens.json）。

规则（第一版，确定性，产物必须通过图纸检查器）：
  * 首页区块顺序来自知识库 landing.csv 的 Section Order（英文短语 → 我们的区块类型）。
  * 每个目标对应一个承接页（预约 → 预约页 + 预约成功页；联系 → 联系页 + 提交成功页；……），流程不超过 3 次点击。
  * 每个功能落到一个页面或区块；第一版做不了的功能（在线支付、购物车、会员登录、站内搜索）如实列进“暂未实现”。
  * 有表单就加隐私政策页。
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import kb  # noqa: E402
import styles  # noqa: E402

SECTION_WORDS = [  # 顺序有意义：先匹配更具体的短语
    ("how it works", "steps"), ("value prop", "value-props"), ("social proof", "testimonials"), ("call-to-action", "cta"),
    ("email capture", "newsletter"), ("newsletter", "newsletter"), ("testimonial", "testimonials"), ("review", "testimonials"),
    ("pricing", "pricing"), ("price", "pricing"), ("faq", "faq"), ("footer", "footer"), ("hero", "hero"),
    ("feature", "features"), ("benefit", "value-props"), ("gallery", "gallery"), ("portfolio", "gallery"), ("project", "gallery"),
    ("showcase", "gallery"), ("screenshot", "gallery"), ("listing", "gallery"), ("stat", "stats"), ("metric", "stats"),
    ("logo", "logos"), ("trust", "logos"), ("client", "logos"), ("cert", "logos"), ("step", "steps"), ("process", "steps"),
    ("agenda", "steps"), ("schedule", "steps"), ("journey", "steps"), ("team", "team"), ("speaker", "team"),
    ("comparison", "comparison"), ("contact", "contact-form"), ("form", "contact-form"), ("cta", "cta"),
    ("categor", "features"), ("about", "content"), ("problem", "content"), ("solution", "content"), ("chapter", "content"),
    ("video", "content"), ("demo", "content"), ("intro", "content"), ("mission", "content"), ("detail", "content"),
]
VARIANT = {"hero": "split-right", "value-props": "grid-3", "features": "grid-3", "testimonials": "carousel", "pricing": "grid-3",
           "faq": "list", "cta": "stack", "gallery": "bento", "stats": "grid-4", "logos": "inline", "steps": "grid-3",
           "team": "grid-4", "comparison": "stack", "contact-form": "stack", "newsletter": "stack", "content": "stack",
           "menu": "grid-4", "booking-form": "stack", "map": "split-left", "blog-list": "list"}
FOOD = {"Bakery/Cafe", "Restaurant/Food Service", "Brewery/Winery"}
NOT_YET = {"payment": "在线支付", "cart": "购物车", "membership": "会员登录", "search": "站内搜索"}


def landing_sections(pattern_id: str) -> tuple[list[str], list[str]]:
    order = kb.vocab()["landing_patterns"].get(pattern_id, {}).get("section_order", "")
    out, unknown = [], []
    for part in order.split(">"):
        p = part.strip().lower()
        if not p:
            continue
        t = next((t for w, t in SECTION_WORDS if w in p), None)
        if t is None:
            unknown.append(part.strip())
        elif not out or out[-1] != t:
            out.append(t)
    return out, unknown


def _sec(sid, typ, slots=None, actions=None, motion=None, **extra):
    s = {"id": sid, "type": typ, "component": f"registry:{typ}",
         "layout": {"variant": VARIANT.get(typ, "stack"), **({"mobile": "stack"} if VARIANT.get(typ, "stack") != "stack" else {})},
         "slots": slots or {"heading": {"kind": "text", "max_chars": 24}}}
    if actions:
        s["actions"] = actions
    if motion:
        s["motion"] = motion
    s.update(extra)
    return s


def plan(brief: dict, style_id: str | None = None) -> dict:
    """返回 {文件路径: 内容}，可直接写成一个图纸项目；外加 notes（暂未实现、解析不了的知识库段落）。"""
    ptype = brief["product_type"]["value"]
    name, aud = brief.get("site_name", "我的网站"), brief["audience"]["primary"]
    tier = brief["style_preference"]["motion_tier"]
    style_id = style_id or styles.options(brief)[0]["id"]
    feats = {f["kind"]: f for f in brief["features"]}
    fid = lambda kind: feats[kind]["id"] if kind in feats else None
    goals = brief["goals"]
    reveal = [{"category": "Scroll Reveal", "tier": tier}]
    hover = [{"category": "Hover Micro-interaction", "tier": tier}]

    pages, wires, flows, entities = [], {}, [], {}
    notes = {"not_yet": [NOT_YET[k] for k in feats if k in NOT_YET], "unknown_sections": []}

    def page(pid, title, path, parent, kind, sections, header=False, footer=False, order=50, **kw):
        pages.append({"id": pid, "title": title, "path": path, "parent": parent, "kind": kind,
                      "wireframe": f"pages/{pid}.json", "nav": {"header": header, "footer": footer, "order": order}, **kw})
        wires[pid] = {"schema_version": "page/0.1", "page_id": pid, "sections": sections}

    def form_page(pid, title, path, feature_kind, fields, entity, goal_ids, header, order, label):
        done = f"{pid}-done"
        if fid(feature_kind) is None:
            return None
        entities[entity] = [{"name": f, "type": "phone" if f == "phone" else ("email" if f == "email" else "text"), "required": True}
                            for f in fields]
        page(pid, title, path, "home", "form",
             [_sec("form", "booking-form" if feature_kind == "booking" else "contact-form",
                   {"heading": {"kind": "text", "max_chars": 16, "brief": f"{title}：一句话说明会发生什么"},
                    "fields": {"kind": "form_fields", "fields": fields}},
                   [{"id": "submit", "label": label, "primary": True, "target": {"submit": fid(feature_kind), "then": done}}],
                   feature=fid(feature_kind), data=entity)],
             header=header, order=order, serves_goals=goal_ids, implements_features=[fid(feature_kind)], data=[entity])
        page(done, f"{title}成功", path + "/done", pid, "thanks",
             [_sec("done", "content", {"heading": {"kind": "text", "max_chars": 12}, "body": {"kind": "text"}},
                   [{"id": "back", "label": "回到首页", "target": {"page": "home"}}])], seo={"index": False})
        return pid, done

    # ---------- 承接页 ----------
    targets = {}  # 目标 → (承接页, 成功页)
    for g in goals:
        k = g["kind"]
        if k == "booking" and "booking" not in targets:
            targets[k] = form_page("booking", "预约", "/booking", "booking", ["date", "time", "people", "phone"], "reservation",
                                   [g["id"]], True, 2, "确认预约")
        elif k in ("leads", "signup", "community", "recruit") and "contact" not in targets:
            title = {"leads": "联系我们", "signup": "报名", "community": "加入我们", "recruit": "加入团队"}[k]
            targets["contact"] = targets[k] = form_page("contact", title, "/contact", "contact_form",
                                                       ["name", "phone", "message"], "contact-request", [g["id"]], True, 4, "提交")
        elif k in ("leads", "signup", "community", "recruit"):
            targets[k] = targets["contact"]
    catalog_page = None
    if "catalog" in feats or any(g["kind"] in ("sell", "inform") for g in goals):
        if "catalog" not in feats:
            feats["catalog"] = {"id": f"F{len(brief['features']) + 1}", "kind": "catalog"}
            brief["features"].append({"id": feats["catalog"]["id"], "kind": "catalog", "priority": "P1", "source": "inferred"})
        pid, title, ent = ("menu", "菜单", "menu-item") if ptype in FOOD else \
            (("products", "商品", "product") if any(g["kind"] == "sell" for g in goals) else ("services", "服务项目", "service"))
        entities[ent] = [{"name": "name", "type": "text", "required": True}, {"name": "price", "type": "money"},
                         {"name": "photo", "type": "image"}]
        next_page = targets.get("booking") or targets.get("contact")
        acts = [{"id": "next", "label": "预约" if next_page and next_page[0] == "booking" else "咨询", "primary": True,
                 "target": {"page": next_page[0]}}] if next_page else []
        gids = [g["id"] for g in goals if g["kind"] in ("sell", "inform")]
        page(pid, title, f"/{pid}", "home", "listing",
             [_sec("list", "menu" if pid == "menu" else "gallery", {"items": {"kind": "list", "count": 8, **({} if pid == "menu" else {"item_image": True})}}, data=ent,
                   feature=feats["catalog"]["id"], motion=[{"category": "Stagger List", "tier": tier}]),
              _sec("cta", "cta", {"heading": {"kind": "text", "max_chars": 14}}, acts)],
             header=True, footer=True, order=1, serves_goals=gids, implements_features=[feats["catalog"]["id"]], data=[ent])
        catalog_page = pid
        for g in goals:
            if g["kind"] in ("sell", "inform"):
                targets[g["kind"]] = (pid, None)
    if "gallery" in feats:
        entities["work"] = [{"name": "title", "type": "text", "required": True}, {"name": "image", "type": "image", "required": True}]
        gids = [g["id"] for g in goals if g["kind"] == "showcase"]
        nxt = targets.get("contact")
        page("work", "作品", "/work", "home", "listing",
             [_sec("grid", "gallery", {"items": {"kind": "list", "count": 9, "item_image": True}}, data="work", feature=fid("gallery"), motion=reveal),
              _sec("cta", "cta", {"heading": {"kind": "text"}},
                   [{"id": "next", "label": "联系我", "primary": True, "target": {"page": nxt[0]}}] if nxt else None)],
             header=True, footer=True, order=1, serves_goals=gids, implements_features=[fid("gallery")], data=["work"])
        if gids:
            targets["showcase"] = ("work", None)
    if "map" in feats:
        page("visit", "到店", "/visit", "home", "contact",
             [_sec("map", "map", {"map": {"kind": "embed"}, "hours": {"kind": "text", "brief": "营业时间与地址"}}, feature=fid("map"))],
             header=True, footer=True, order=3, implements_features=[fid("map")])
    if "blog" in feats:
        entities["post"] = [{"name": "title", "type": "text", "required": True}, {"name": "body", "type": "rich_text"}]
        page("blog", "动态", "/blog", "home", "blog_index",
             [_sec("posts", "blog-list", {"items": {"kind": "list", "count": 6}}, data="post", feature=fid("blog"))],
             header=True, footer=True, order=5, implements_features=[fid("blog")], data=["post"])
    story = _sec("story", "content", {"heading": {"kind": "text"}, "body": {"kind": "rich_text", "brief": f"{name}的故事"},
                                      "photo": {"kind": "image", "brief": "店面、团队或工作中的样子"}})
    story["layout"] = {"variant": "split-left", "mobile": "stack"}
    page("about", "关于", "/about", "home", "about", [story], footer=True, order=6)
    if any(p["kind"] == "form" for p in pages):
        page("privacy", "隐私政策", "/privacy", "home", "legal",
             [_sec("body", "content", {"body": {"kind": "rich_text", "brief": "收集哪些信息、怎么用、怎么删除"}})], footer=True, order=9)

    # ---------- 首页 ----------
    pattern = brief["style_preference"].get("landing_pattern") or "hero-features-cta"
    order, unknown = landing_sections(pattern)
    notes["unknown_sections"] = unknown
    main = next((targets[g["kind"]][0] for g in goals if g["kind"] in targets and targets[g["kind"]]), None)
    p0 = goals[0]
    hero_acts = [{"id": "primary", "label": {"booking": "立即预约", "sell": "去看看", "leads": "联系我们", "signup": "马上报名",
                                             "showcase": "看作品", "inform": "了解更多"}.get(p0["kind"], "了解更多"),
                  "primary": True, "target": {"page": main}}] if main else []
    if catalog_page and catalog_page != main:
        hero_acts.append({"id": "secondary", "label": "看" + {"menu": "菜单", "products": "商品", "services": "服务"}[catalog_page],
                          "target": {"page": catalog_page}})
    secs = []
    for t in order:
        n = sum(1 for s in secs if s["type"] == t)
        sid = t if n == 0 else f"{t}-{n + 1}"
        if t == "footer":
            continue
        if t == "hero":
            secs.append(_sec("hero", "hero", {"heading": {"kind": "text", "max_chars": 18, "brief": f"一句话说清{name}能给{aud}带来什么"},
                                              "body": {"kind": "text", "max_chars": 50},
                                              "image": {"kind": "image", "asset": "A2", "brief": f"{name}的代表性画面"}},
                             hero_acts, reveal))
        elif t in ("cta",):
            secs.append(_sec(sid, "cta", {"heading": {"kind": "text", "max_chars": 16}},
                             [dict(hero_acts[0], id=f"{sid}-go")] if hero_acts else None))
        elif t == "contact-form":
            if "contact" in [p["id"] for p in pages]:
                secs.append(_sec(sid, "cta", {"heading": {"kind": "text"}},
                                 [{"id": f"{sid}-go", "label": "联系我们", "primary": True, "target": {"page": "contact"}}]))
        elif t == "newsletter":
            continue  # 第一版没有邮件订阅功能，不放空壳
        elif t == "faq":
            secs.append(_sec(sid, "faq", {"heading": {"kind": "text", "max_chars": 12}, "items": {"kind": "list", "count": 5}}, **({"feature": fid("faq")} if fid("faq") else {})))
        elif t in ("features", "value-props", "steps", "stats", "team", "logos", "testimonials", "pricing", "gallery", "comparison", "content"):
            secs.append(_sec(sid, t, {"heading": {"kind": "text", "max_chars": 20}, "items": {"kind": "list", "count": 3}},
                             motion=hover if t in ("features", "value-props") else None))
    if catalog_page and not any(s["type"] == "menu" for s in secs):
        pos = 2 if len(secs) > 2 else len(secs)
        secs.insert(pos, _sec("catalog-teaser", "menu" if catalog_page == "menu" else "gallery",
                              {"items": {"kind": "list", "count": 4, **({} if catalog_page == "menu" else {"item_image": True})}},
                              [{"id": "more", "label": "查看全部", "target": {"page": catalog_page}}],
                              data={"menu": "menu-item", "products": "product", "services": "service"}[catalog_page]))
    if "faq" in feats and not any(s["type"] == "faq" for s in secs):
        secs.append(_sec("faq", "faq", {"heading": {"kind": "text", "max_chars": 12}, "items": {"kind": "list", "count": 5}}, feature=fid("faq")))
    if not any(s["type"] == "cta" for s in secs) and hero_acts:
        secs.append(_sec("cta", "cta", {"heading": {"kind": "text"}}, [dict(hero_acts[0], id="cta-go")]))
    home_feats = [fid("faq")] if any(s.get("feature") == fid("faq") for s in secs) and fid("faq") else []
    pages.insert(0, {"id": "home", "title": "首页", "path": "/", "parent": None, "kind": "home", "pattern": pattern,
                     "serves_goals": [g["id"] for g in goals], "implements_features": home_feats,
                     "wireframe": "pages/home.json", "nav": {"header": True, "footer": True, "order": 0},
                     "seo": {"title": f"{name}"[:60], "description": f"{name}：{goals[0]['description']}"[:160]}})
    wires["home"] = {"schema_version": "page/0.1", "page_id": "home", "pattern": pattern, "sections": secs}
    # 每页的搜索标题和描述：描述 20 字以上、说清这一页是干什么的（上线体检发现描述太短：D23）
    aud = brief["audience"]["primary"]
    purpose = {"form": "在线填写并提交，我们会尽快联系你确认", "legal": "说明我们收集哪些信息、怎么用、怎么删除",
               "about": "了解我们是谁、为什么开始、想做什么", "confirmation": "提交成功，我们会尽快与你联系",
               "listing": "看看我们做过的作品和案例", "contact": "地址、营业时间和怎么过来", "blog_index": "最新的动态和消息",
               "catalog": "看看我们提供什么、价格是多少", "success": "提交成功，我们会尽快与你联系"}
    for p in pages:
        seo = p.setdefault("seo", {})
        if p["id"] == "home":
            seo["description"] = f"{name}：{goals[0]['description']}。" + (f"为{aud}准备。" if aud and aud != "潜在顾客" else "欢迎了解。")
        else:
            seo.setdefault("title", f"{p['title']} · {name}"[:60])
            seo.setdefault("description", f"{name}的{p['title']}页：{purpose.get(p['kind'], goals[0]['description'])}。")
        seo["description"] = seo["description"][:160]
    for k in ("faq",):  # 首页实现了 FAQ
        pass

    # ---------- 流程 ----------
    for i, g in enumerate(goals):
        tgt = targets.get(g["kind"])
        if not tgt:
            continue
        steps = ["home"] + ([tgt[0]] if tgt[0] != "home" else []) + ([tgt[1]] if tgt[1] else [])
        flows.append({"id": f"FL{i + 1}", "goal": g["id"], "steps": steps})
    for g in goals:  # 没有承接页的目标由首页负责
        if not targets.get(g["kind"]):
            flows.append({"id": f"FL{len(flows) + 1}", "goal": g["id"], "steps": ["home"]})

    files = []
    plan_items = [("design-director", "design/DESIGN.md", []), ("design-director", "design/tokens.json", ["W1"])]
    plan_items += [("layout", f"pages/{p['id']}.json", ["W2"]) for p in pages]
    n_layout = len(plan_items)
    plan_items += [("content", f"content/{loc}.json", [f"W{i}" for i in range(3, n_layout + 1)]) for loc in brief["locales"]]
    plan_items += [("engineer", "src/", [f"W{len(plan_items)}"])]
    plan_items += [("motion", "src/motion", [f"W{len(plan_items)}"]), ("reviewer", "review/report.json", [f"W{len(plan_items) + 1}"])]
    work = [{"id": f"W{i + 1}", "agent": a, "produces": p, **({"depends_on": d} if d else {})} for i, (a, p, d) in enumerate(plan_items)]

    prof = styles.profile(style_id)
    site = {"schema_version": "site/0.1", "id": brief["id"] + "-site", "brief_id": brief["id"],
            "default_locale": brief["locales"][0], "locales": brief["locales"],
            "style": {"style_id": style_id, "motion_tier": tier, "color_mode": "dark" if prof["dark"] else "light",
                      "design_md": "design/DESIGN.md", "tokens": "design/tokens.json"},
            "pages": pages, "flows": flows,
            "data_entities": [{"id": k, "fields": v} for k, v in entities.items()], "work_plan": work}
    tok = styles.tokens(style_id, ptype, brief.get("brand", {}).get("colors"))
    fp = styles.font_pair(style_id)
    design_md = (f"# {name} · 设计规范\n\n由文字生成（text2site），风格 **{prof['name']}**（`{style_id}`），行业配色 **{ptype}**。\n\n"
                 f"- 圆角 {prof['radius']}px，边框 {prof['border']}px，阴影：{prof['shadow']}，毛玻璃：{'是' if prof['glass'] else '否'}，"
                 f"{'深色' if prof['dark'] else '浅色'}底\n- 字体搭配：{fp['name']}\n- 动效档位：{tier}，基础时长 {prof['duration']}ms，"
                 f"尊重系统“减少动态效果”设置\n- 适合：{prof['best_for']}\n- 不适合：{prof['avoid_for']}\n")
    from copywriter import write_copy  # noqa: E402  文案 Agent 第一版（文件不能叫 copy.py：会和标准库重名）
    out = {"brief.json": brief, "site.json": site, "design/tokens.json": tok, "design/DESIGN.md": design_md}
    for loc in brief["locales"][:1]:  # 第一版只写主语言；其他语言等翻译 Agent
        out[f"content/{loc}.json"] = write_copy(brief, wires)
    out.update({f"pages/{pid}.json": w for pid, w in wires.items()})
    return {"files": out, "notes": notes}


def write_project(result: dict, root: str):
    for rel, obj in result["files"].items():
        f = os.path.join(root, rel)
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1))
