#!/usr/bin/env python3
"""三份图纸（需求简报 / 网站结构 / 页面线框）的确定性检查。

用法：python3 -I check_blueprints.py <项目目录> [--json]
项目目录结构：brief.json  site.json  pages/<id>.json  design/tokens.json（可选）

每条问题带：级别、错误码、位置、说明、下一步（经验 P009：报错要告诉下一步怎么做）。
有“错误”级问题时退出码为 1。
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMAS = os.path.join(HERE, "..", "schemas")
TIER = {"Subtle": 1, "Standard": 2, "Complex": 3}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validators():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    reg = Registry()
    docs = {}
    for name in ("vocab", "brief", "site", "page"):
        d = _load(os.path.join(SCHEMAS, f"{name}.schema.json"))
        docs[name] = d
        res = Resource.from_contents(d)
        reg = reg.with_resource(d["$id"], res).with_resource(f"{name}.schema.json", res)
    return {n: Draft202012Validator(docs[n], registry=reg, format_checker=Draft202012Validator.FORMAT_CHECKER)
            for n in ("brief", "site", "page")}


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, code, where, msg, hint):
        self.items.append({"level": level, "code": code, "where": where, "msg": msg, "hint": hint})

    def err(self, *a):
        self.add("错误", *a)

    def warn(self, *a):
        self.add("提醒", *a)

    @property
    def errors(self):
        return [i for i in self.items if i["level"] == "错误"]


def _token_paths(tokens, prefix=""):
    out = set()
    for k, v in tokens.items():
        if k.startswith("$"):
            continue
        if isinstance(v, dict):
            p = f"{prefix}.{k}" if prefix else k
            if "$value" in v:
                out.add(p)
            out |= _token_paths(v, p)
    return out


def _walk_sections(sections, path="sections"):
    for i, s in enumerate(sections):
        p = f"{path}[{i}]"
        yield p, s
        yield from _walk_sections(s.get("children", []), p + ".children")


def check(project):
    r = Report()
    vocab = _load(os.path.join(SCHEMAS, "vocab.json"))
    V = _validators()

    def schema_check(kind, doc, fname):
        ok = True
        for e in sorted(V[kind].iter_errors(doc), key=lambda e: list(e.absolute_path)):
            ok = False
            where = f"{fname}:" + "/".join(str(x) for x in e.absolute_path)
            hint = "按 schemas/%s.schema.json 修正该字段" % kind
            val = e.instance
            msg = e.message[:200]
            if e.validator == "enum" and isinstance(val, str):
                import difflib
                near = difflib.get_close_matches(val, [str(x) for x in e.validator_value], n=3, cutoff=0.4)
                msg = f"“{val}”不在封闭词表里（共 {len(e.validator_value)} 项）"
                hint = f"最接近的合法值：{'、'.join(near)}" if near else hint
            if isinstance(val, str) and val in vocab["styles"] and vocab["styles"][val]["status"] == "deprecated":
                rep = vocab["styles"][val]["replacement"]
                hint = f"“{val}”已弃用，改用 {rep['domain']}:{rep['id']}" + \
                       ("（它现在是落地页模式，应写进 landing_pattern / pattern 字段）" if rep["domain"] == "landing" else "")
            r.err("B001", where, msg, hint)
        return ok

    # ---------- 载入 ----------
    try:
        brief = _load(os.path.join(project, "brief.json"))
        site = _load(os.path.join(project, "site.json"))
    except FileNotFoundError as e:
        r.err("B000", os.path.basename(e.filename), "缺少文件", "项目目录必须有 brief.json 和 site.json")
        return r
    schema_check("brief", brief, "brief.json")
    schema_check("site", site, "site.json")

    pages_by_id, wire = {}, {}
    for p in site.get("pages", []):
        pages_by_id.setdefault(p["id"], p)
        wf = os.path.join(project, p["wireframe"])
        if not os.path.exists(wf):
            r.err("S024", f"site.json:pages/{p['id']}", f"线框文件 {p['wireframe']} 不存在",
                  "让布局 Agent 产出该页线框，或修正 wireframe 路径")
            continue
        w = _load(wf)
        if schema_check("page", w, p["wireframe"]):
            wire[p["id"]] = w
        if w.get("page_id") != p["id"]:
            r.err("S024", p["wireframe"], f"page_id 是 {w.get('page_id')!r}，应为 {p['id']!r}", "两边改成同一个 ID")

    tokens = None
    if os.path.exists(os.path.join(project, site.get("style", {}).get("tokens", "-"))):
        tokens = _token_paths(_load(os.path.join(project, site["style"]["tokens"])))

    goals = {g["id"]: g for g in brief.get("goals", [])}
    feats = {f["id"]: f for f in brief.get("features", [])}
    assets = {a["id"] for a in brief.get("content_assets", [])}
    entities = {e["id"] for e in site.get("data_entities", [])}

    # ---------- 简报 ----------
    for q in brief.get("open_questions", []):
        if q.get("blocking") and not q.get("answer"):
            r.err("B010", f"brief.json:open_questions/{q['id']}", f"阻塞性问题未回答：{q['question']}",
                  "先拿到用户回答再交给下游 Agent；或把 blocking 改成 false 并采用默认值")

    # ---------- 网站结构 ----------
    if site.get("brief_id") != brief.get("id"):
        r.err("S020", "site.json:brief_id", f"指向 {site.get('brief_id')!r}，简报是 {brief.get('id')!r}", "改成当前简报的 id")
    seen_id, seen_path = set(), {}
    for p in site.get("pages", []):
        if p["id"] in seen_id:
            r.err("S021", f"site.json:pages/{p['id']}", "页面 id 重复", "每个页面 id 唯一")
        seen_id.add(p["id"])
        if p["path"] in seen_path:
            r.err("S021", f"site.json:pages/{p['id']}", f"路径 {p['path']} 与 {seen_path[p['path']]} 重复", "改路径")
        seen_path[p["path"]] = p["id"]
    if "/" not in seen_path:
        r.err("S023", "site.json:pages", "没有路径为 / 的首页", "把首页的 path 设为 /")
    for p in site.get("pages", []):
        par, chain = p.get("parent"), {p["id"]}
        while par:  # 有界：每步要么把 par 加进 chain，要么遇到缺失或成环就 break，最多走页面数步
            if par not in pages_by_id:
                r.err("S022", f"site.json:pages/{p['id']}", f"父页面 {par!r} 不存在", "改为已有页面 id 或 null")
                break
            if par in chain:
                r.err("S022", f"site.json:pages/{p['id']}", "父子关系成环", "检查 parent 链")
                break
            chain.add(par)
            par = pages_by_id[par].get("parent")

    served = {g for p in site.get("pages", []) for g in p.get("serves_goals", [])}
    for p in site.get("pages", []):
        for g in p.get("serves_goals", []):
            if g not in goals:
                r.err("S025", f"site.json:pages/{p['id']}", f"服务的目标 {g} 不在简报里", "删掉或回到需求分析补目标")
        for f in p.get("implements_features", []):
            if f not in feats:
                r.err("S026", f"site.json:pages/{p['id']}", f"实现的功能 {f} 不在简报里", "删掉或回到需求分析补功能")
        for d in p.get("data", []):
            if d not in entities:
                r.err("P057", f"site.json:pages/{p['id']}", f"数据实体 {d} 未声明", "在 data_entities 里声明")
    for gid, g in goals.items():
        if gid not in served:
            (r.err if g["priority"] != "P2" else r.warn)(
                "S025", f"brief.json:goals/{gid}", f"目标“{g['description']}”没有任何页面负责",
                "让信息架构 Agent 给它分配页面（serves_goals）")
    impl = {f for p in site.get("pages", []) for f in p.get("implements_features", [])}
    for fid, f in feats.items():
        if f["priority"] == "P0" and fid not in impl:
            r.err("S026", f"brief.json:features/{fid}", f"P0 功能 {f['kind']} 没有页面实现", "在某个页面的 implements_features 里加上")

    missing = set(brief.get("locales", [])) - set(site.get("locales", [site.get("default_locale")]))
    if missing:
        r.err("S034", "site.json:locales", f"简报要求的语言 {sorted(missing)} 网站结构里没有", "在 locales 里加上，并安排文案 Agent 产出对应语言")
    style = site.get("style", {})
    sid = style.get("style_id")
    if sid and sid not in brief.get("style_preference", {}).get("style_ids", []):
        r.warn("S033", "site.json:style/style_id", f"选用的风格 {sid} 不在简报的候选里",
               "确认设计总监偏离简报是有意的，并在对话里告诉用户")
    site_tier = TIER.get(style.get("motion_tier"), 2)

    # ---------- 链接图（导航 + 按钮 + 面包屑） ----------
    links = {pid: set() for pid in pages_by_id}
    header = [p["id"] for p in site.get("pages", []) if p["nav"]["header"]]
    footer = [p["id"] for p in site.get("pages", []) if p["nav"]["footer"]]
    for pid, p in pages_by_id.items():
        links[pid] |= set(header) | set(footer)
        par, seen = p.get("parent"), {pid}
        while par in pages_by_id and par not in seen:  # 有界：seen 集合防环（S022 已单独报错），最多走页面数步
            seen.add(par)
            links[pid].add(par)
            par = pages_by_id[par].get("parent")

    # ---------- 页面线框 ----------
    for pid, w in wire.items():
        f = pages_by_id[pid]["wireframe"]
        ids = {}
        for path, s in _walk_sections(w["sections"]):
            if s["id"] in ids:
                r.err("P053", f"{f}:{path}", f"区块 id {s['id']} 重复", "同一页内区块 id 唯一")
            ids[s["id"]] = s
        tier_cap = TIER.get(w.get("style_overrides", {}).get("motion_tier"), site_tier)
        for k, ref in w.get("style_overrides", {}).get("tokens", {}).items():
            if tokens is not None and ref.strip("{}") not in tokens:
                r.err("P056", f"{f}:style_overrides/tokens/{k}", f"令牌 {ref} 不存在", "只能引用 tokens.json 里已有的令牌")
        has_primary = False
        for path, s in _walk_sections(w["sections"]):
            loc = f"{f}:{path}({s['id']})"
            for a in s.get("actions", []):
                has_primary |= bool(a.get("primary"))
                t = a["target"]
                if "page" in t:
                    if t["page"] not in pages_by_id:
                        r.err("P050", loc, f"按钮“{a['label']}”跳到不存在的页面 {t['page']}", "改成已有页面，或先让信息架构 Agent 加页面")
                        continue
                    links[pid].add(t["page"])
                    if "section" in t and t["page"] in wire:
                        tgt = {x["id"] for _, x in _walk_sections(wire[t["page"]]["sections"])}
                        if t["section"] not in tgt:
                            r.err("P051", loc, f"按钮“{a['label']}”指向 {t['page']}#{t['section']}，该区块不存在", "改锚点")
                elif "section" in t and t["section"] not in ids:
                    r.err("P051", loc, f"按钮“{a['label']}”指向本页 #{t['section']}，该区块不存在", "改锚点")
                elif "submit" in t:
                    if t["submit"] not in feats:
                        r.err("P052", loc, f"表单提交到未声明的功能 {t['submit']}", "回到需求简报补功能")
                    if t.get("then"):
                        if t["then"] in pages_by_id:
                            links[pid].add(t["then"])
                        else:
                            r.err("P050", loc, f"提交后跳到不存在的页面 {t['then']}", "改成已有页面")
            for m in s.get("motion", []):
                if TIER[m["tier"]] > tier_cap:
                    r.err("P054", loc, f"动效 {m['category']}/{m['tier']} 超过允许档位",
                          "降档，或在页面 style_overrides.motion_tier 里说明理由后放宽")
                if [m["category"], m["tier"]] not in vocab["motion_available"]:
                    r.warn("P055", loc, f"知识库里没有 {m['category']}/{m['tier']} 这一档的参数",
                           "动效 Agent 将无参考可依，建议换成知识库已有的档位")
            if s.get("data") and s["data"] not in entities:
                r.err("P057", loc, f"绑定的数据实体 {s['data']} 未声明", "在 site.json 的 data_entities 里声明")
            if s.get("feature") and s["feature"] not in feats:
                r.err("P058", loc, f"区块实现的功能 {s['feature']} 不在简报里", "回到需求简报补功能")
            for name, slot in s.get("slots", {}).items():
                if slot.get("asset") and slot["asset"] not in assets:
                    r.err("P059", f"{loc}.slots.{name}", f"引用的素材 {slot['asset']} 不在简报里", "在 content_assets 里登记")
        if pages_by_id[pid].get("serves_goals") and not has_primary:
            r.warn("P060", f, "本页负责转化目标，却没有主按钮（primary）", "给最关键的按钮加 primary: true")

    # ---------- 用户流程 ----------
    flows_goals = set()
    for fl in site.get("flows", []):
        flows_goals.add(fl["goal"])
        loc = f"site.json:flows/{fl['id']}"
        if fl["goal"] not in goals:
            r.err("S025", loc, f"流程对应的目标 {fl['goal']} 不在简报里", "改目标编号")
        steps = fl["steps"]
        bad = [s for s in steps if s not in pages_by_id]
        if bad:
            r.err("S027", loc, f"流程里的页面不存在：{bad}", "改成已有页面 id")
            continue
        for a, b in zip(steps, steps[1:]):
            if b not in links.get(a, set()):
                r.err("S028", loc, f"{a} → {b} 之间没有任何链接（导航、按钮、面包屑都没有）",
                      f"在 {a} 页加一个跳到 {b} 的按钮，或把 {b} 放进导航")
        cw = fl.get("completes_with")
        if cw:
            last = steps[-1]
            acts = {a["id"] for _, x in _walk_sections(wire.get(last, {}).get("sections", [])) for a in x.get("actions", [])}
            if last in wire and cw["action"] not in acts:
                r.err("S031", loc, f"流程要求在 {last} 页点击 {cw['action']}，该按钮不存在", "改按钮 id，或在该页加上这个按钮")
        clicks = len(steps) - 1 + (1 if cw else 0)
        if clicks > fl.get("max_clicks", 3):
            r.err("S029", loc, f"需要 {clicks} 次点击，超过 {fl.get('max_clicks', 3)}", "缩短路径")
    for gid, g in goals.items():
        if g["priority"] == "P0" and gid not in flows_goals:
            r.err("S030", f"brief.json:goals/{gid}", "P0 目标没有对应的用户流程", "在 site.json 的 flows 里补一条")

    # ---------- 分工计划 ----------
    plan = {w["id"]: w for w in site.get("work_plan", [])}
    for wid, w in plan.items():
        for d in w.get("depends_on", []):
            if d not in plan:
                r.err("W040", f"site.json:work_plan/{wid}", f"依赖的 {d} 不存在", "改依赖编号")
    state = {}

    def dfs(n):
        state[n] = 1
        for d in plan[n].get("depends_on", []):
            if d in plan and (state.get(d) == 1 or (d not in state and dfs(d))):
                return True
        state[n] = 2
        return False
    for wid in plan:
        if wid not in state and dfs(wid):
            r.err("W040", "site.json:work_plan", "依赖关系成环", "去掉环上的某条依赖")
            break
    produced = {w["produces"]: w["agent"] for w in plan.values()}
    for p in site.get("pages", []):
        ag = produced.get(p["wireframe"])
        if ag is None:
            r.err("W041", f"site.json:pages/{p['id']}", f"{p['wireframe']} 没有安排给任何 Agent", "在 work_plan 里加一项，由 layout 产出")
        elif ag != "layout":
            r.err("W041", f"site.json:pages/{p['id']}", f"{p['wireframe']} 由 {ag} 产出，应由 layout 产出", "改 agent")
    for key, ag in (("design_md", "design-director"), ("tokens", "design-director")):
        f = style.get(key)
        if f and produced.get(f) not in (None, ag):
            r.err("W041", f"site.json:style/{key}", f"{f} 应由 {ag} 产出", "改 agent")
    return r


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rep = check(args[0])
    if "--json" in sys.argv:
        print(json.dumps(rep.items, ensure_ascii=False, indent=1))
    else:
        for i in rep.items:
            print(f"{i['level']} {i['code']}  {i['where']}\n    {i['msg']}\n    → 下一步：{i['hint']}")
        print(f"图纸检查：错误 {len(rep.errors)}，提醒 {len(rep.items) - len(rep.errors)}")
    sys.exit(1 if rep.errors else 0)


if __name__ == "__main__":
    main()
