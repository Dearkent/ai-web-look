"""对话式修改：网站生成以后，用一句话改它。

能改的（封闭清单，抽不出来的不瞎改）：
  颜色      “按钮换成绿色”“主色用 #2a9d8f”                 → 品牌主色（为保证文字看得清，可能会自动调深）
  加页面    “加一个相册”“加上地图”“再加个预约”               → 加功能（会生成对应页面）
  去页面    “去掉相册”“不要博客了”                          → 去功能（目标必需的页面不删，说明原因）
  换风格    “换成复古风格”“改成深色的”                      → 换风格
  改名字    “名字改成 巷口咖啡”“店名叫 Blue Bottle”          → 改站名
  撤销      “撤销”“回到上一版”                              → 回到上一版
  改文字    “标题改成 下班后的一杯咖啡”“介绍改成 …”“号召改成 …” → 首页大标题 / 副标题 / 结尾号召（用户自己的话照用，有广告法风险会提醒）
  字号      “字大一点”“字再小点”                              → 全站字号 ×0.9～×1.25
  圆角      “圆角大一点”“改成直角”                            → 方 / 小 / 大圆角
  间距      “间距宽松一点”“紧凑一点”                          → 区块上下留白
（字号、圆角、间距、改文字是第十一轮从“待学清单”里学来的：之前用户说“字大一点”系统看不懂）
每次修改还会给出“教给它”的建议句（例如“咖啡馆不要博客”），用户点了就走喂养流程，以后同行业都这样。
"""
from __future__ import annotations

import copy
import re

import lexicon as L
import styles as S
from llm_copy import ABSOLUTE as _ABSOLUTE
from understand import GOAL_DESC, GOAL_FEATURE

BUILDABLE = {"booking", "contact_form", "map", "gallery", "catalog", "blog"}  # 这一版生成器真的能做出页面的功能
FEATURE_ZH = {"booking": "预约", "contact_form": "联系表单", "map": "地图（到店页）", "gallery": "相册（作品页）",
              "catalog": "菜单/商品/价目", "blog": "动态（博客）", "cart": "购物车", "payment": "在线支付",
              "membership": "会员登录", "search": "站内搜索", "multilingual": "多语言", "faq": "常见问题", "newsletter": "邮件订阅"}
TEACH_WORD = {"map": "地图", "gallery": "相册", "blog": "博客", "booking": "预约", "contact_form": "联系表单", "catalog": "菜单"}
EXTRA_WORDS = {"catalog": ["价格", "价目表"], "gallery": ["作品集"], "contact_form": ["联系方式"]}
COLORS = {"红": "#C62828", "橙": "#E65100", "黄": "#F9A825", "绿": "#2E7D32", "青": "#00838F", "蓝": "#1565C0", "紫": "#6A1B9A",
          "粉": "#D81B60", "棕": "#6D4C41", "咖啡色": "#6D4C41", "黑": "#212121", "灰": "#546E7A", "金": "#B8860B", "藏青": "#1A237E"}
ADD = re.compile(r"(加|添加|增加|加上|新增|要有|得有|再来|多一个|补上)")
DEL = re.compile(r"(去掉|删掉|删除|不要|取消|拿掉|去除|移除|关掉)")
UNDO = re.compile(r"^(撤销|撤回|回到上一版|恢复上一版|还原|退回上一步|上一版)")
NAME = re.compile(r"(?:名字|店名|站名|网站名|品牌名)(?:改成|换成|改为|叫|用)\s*[“\"「]?([^”\"」，,。！!？?]{1,40})")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
COPY = re.compile(r"(大标题|主标题|标题|标语|口号|副标题|介绍|简介|首页介绍|号召|结尾那句)(?:改成|换成|改为|写成|用)\s*[：:]?\s*[“\"「『]?(.+?)[”\"」』]?\s*$")
COPY_FIELD = {"大标题": ("hero", "heading"), "主标题": ("hero", "heading"), "标题": ("hero", "heading"), "标语": ("hero", "heading"),
              "口号": ("hero", "heading"), "副标题": ("hero", "body"), "介绍": ("hero", "body"), "简介": ("hero", "body"),
              "首页介绍": ("hero", "body"), "号召": ("cta", "heading"), "结尾那句": ("cta", "heading")}
COPY_LIMIT = {"heading": 30, "body": 120}
FONT = re.compile(r"(字|字体|文字|字号)(再|稍微|稍|更)?(大|小)(一)?(点|些)")
RADIUS = re.compile(r"(圆角(再|更)?(大|小)(一)?(点|些))|直角|方一点|圆一点|圆润一点")
DENSITY = re.compile(r"((间距|留白|空白)(再|更)?(大|多|宽松)(一)?(点|些)?|宽松一点)|(紧凑|挤一点|间距(再)?小(一)?点)")
FONT_STEPS = [0.9, 1.0, 1.12, 1.25]
RADIUS_STEPS = ["square", "small", None, "large"]  # None = 风格默认
HELP = ("现在能改：颜色（按钮换成绿色）、加或去掉页面（加一个相册 / 去掉博客）、换风格（换成复古风格）、改名字（名字改成…）、"
        "改文字（标题改成… / 介绍改成… / 号召改成…）、字号（字大一点）、圆角（圆角大一点 / 改成直角）、间距（宽松一点 / 紧凑一点）、撤销")


def _usable() -> set:
    return {k for k, v in S.kb.vocab()["styles"].items() if v["status"] != "deprecated"} & set(S._STYLES)


def _features_in(clause: str) -> list[str]:
    out = []
    for k, ws in L.FEATURES.items():
        if any(w in clause for w in ws + EXTRA_WORDS.get(k, [])):
            out.append(k)
    return out


def parse(text: str) -> tuple[list[dict], list[str]]:
    """一句话 → (修改操作, 没看懂的分句)。"""
    ops, unknown, tail = [], [], None
    text = text.strip()
    for m in COPY.finditer(text):
        before = text[:m.start()]
        if not before.strip() or re.search(r"(?:[，,。；;\n]|然后|再把|并且|同时)\s*[把将]?\s*$", before):
            # “……，标题改成 下班后，来撸猫”：改文字放在最后说，后面整段都是新文字（里面的逗号不拆）
            tail = {"op": "copy", "section": COPY_FIELD[m.group(1)][0], "field": COPY_FIELD[m.group(1)][1], "value": m.group(2).strip()}
            text = re.sub(r"(?:[，,。；;\n]|然后|再把|并且|同时)?\s*[把将]?\s*$", "", before)
            break
    for c in [x.strip() for x in re.split(r"[，,。；;！!\n]|然后|再把|并且|同时", text) if x and x.strip()]:
        cl = c.replace(" ", "") if not NAME.search(c) else c
        if UNDO.match(cl):
            ops.append({"op": "undo"})
            continue
        m = NAME.search(c)
        if m:
            ops.append({"op": "name", "value": m.group(1).strip()})
            continue
        m = COPY.search(c)
        if m:
            ops.append({"op": "copy", "section": COPY_FIELD[m.group(1)][0], "field": COPY_FIELD[m.group(1)][1], "value": m.group(2).strip()})
            continue
        m = FONT.search(cl)
        if m:
            ops.append({"op": "font", "dir": 1 if m.group(3) == "大" else -1})
            continue
        m = RADIUS.search(cl)
        if m:
            d = 1 if (m.group(3) == "大" or "圆" in cl and "圆角" not in cl) else (-9 if ("直角" in cl or "方" in cl) else -1)
            ops.append({"op": "radius", "dir": d})
            continue
        m = DENSITY.search(cl)
        if m:
            ops.append({"op": "density", "value": "tight" if m.group(7) else "loose"})
            continue
        got = False
        m = HEX.search(cl)
        color = None
        if m:
            color = (m.group(0).upper(), m.group(0).upper())
        else:
            for w in sorted(COLORS, key=len, reverse=True):
                if w in cl and re.search(r"(色|换成|改成|用|调成|变成)", cl):
                    color = (COLORS[w], w + ("" if w.endswith("色") else "色"))
                    break
        if color and not any(w in cl for ws in L.STYLE.values() for w in ws):
            ops.append({"op": "color", "hex": color[0], "zh": color[1]})
            got = True
        if not got:
            for key, ws in L.STYLE.items():
                if any(w in cl for w in ws) and not DEL.search(cl):
                    ops.append({"op": "style", "style": key})
                    got = True
                    break
        if not got:
            feats = _features_in(cl)
            if feats and DEL.search(cl):
                ops += [{"op": "remove_feature", "kind": k} for k in feats]
                got = True
            elif feats and ADD.search(cl):
                ops += [{"op": "add_feature", "kind": k} for k in feats]
                got = True
        if not got:
            unknown.append(c)
    if tail:
        ops.append(tail)
    return ops, unknown


def _renumber(brief):
    gs = brief["goals"] or [{"kind": "inform", "description": GOAL_DESC["inform"], "source": "user"}]
    for i, g in enumerate(gs):
        g["id"], g["priority"] = f"G{i + 1}", "P0" if i == 0 else "P1"
    brief["goals"] = gs
    p0f = GOAL_FEATURE.get(gs[0]["kind"])
    for i, f in enumerate(brief["features"]):
        f["id"] = f"F{i + 1}"
        f["priority"] = "P0" if f["kind"] == p0f else "P1"


def apply(brief: dict, style: str, ops: list[dict], extras: dict | None = None):
    """返回 (新简报, 新风格, 改了什么, 没改的及原因, 新附加设置)。不改动传进来的东西。
    附加设置 extras = {"copy": {"hero": {"heading": …}}, "tweaks": {"font": 1.12, "radius": "large", "density": "loose"}}：
    只属于这一个网站，不进需求简报，生成时叠在最上层。"""
    b, done, refused = copy.deepcopy(brief), [], []
    ex = copy.deepcopy(extras or {})
    ex.setdefault("copy", {})
    ex.setdefault("tweaks", {})
    have = lambda k: any(f["kind"] == k for f in b["features"])  # noqa: E731
    for op in ops:
        o = op["op"]
        if o == "color":
            b["brand"]["colors"] = [op["hex"]] + [c for c in b["brand"].get("colors", [])[1:] if c != op["hex"]]
            done.append(f"主色改成{op['zh']}（{op['hex']}；为保证文字看得清，可能会自动调深一些）")
        elif o == "copy":
            v, lim = op["value"], COPY_LIMIT[op["field"]]
            if len(v) > lim or any(x in v for x in ("<", ">", "http", "www.")):
                refused.append(f"{'标题' if op['field'] == 'heading' else '介绍'}太长（最多 {lim} 字）或含网址、符号，没改")
                continue
            ex["copy"].setdefault(op["section"], {})[op["field"]] = v
            risky = [w for w in _ABSOLUTE if w in v]
            where = {"hero.heading": "首页大标题", "hero.body": "首页介绍", "cta.heading": "结尾号召"}[f"{op['section']}.{op['field']}"]
            done.append(f"{where}改成“{v}”" + (f"（提醒：用了“{risky[0]}”，按广告法这类绝对化用语有风险，建议换个说法）" if risky else ""))
        elif o == "font":
            cur = ex["tweaks"].get("font", 1.0)
            i = min(range(len(FONT_STEPS)), key=lambda k: abs(FONT_STEPS[k] - cur))
            j = max(0, min(len(FONT_STEPS) - 1, i + op["dir"]))
            if j == i:
                refused.append("字号已经是" + ("最大" if op["dir"] > 0 else "最小") + "的一档了")
            else:
                ex["tweaks"]["font"] = FONT_STEPS[j]
                done.append(f"字号{'调大' if op['dir'] > 0 else '调小'}（×{FONT_STEPS[j]}）")
        elif o == "radius":
            cur = ex["tweaks"].get("radius")
            i = RADIUS_STEPS.index(cur) if cur in RADIUS_STEPS else 2
            j = 0 if op["dir"] == -9 else max(0, min(len(RADIUS_STEPS) - 1, i + op["dir"]))
            if j == i:
                refused.append("圆角已经是这一档了")
            else:
                if RADIUS_STEPS[j] is None:
                    ex["tweaks"].pop("radius", None)
                else:
                    ex["tweaks"]["radius"] = RADIUS_STEPS[j]
                done.append({"square": "改成直角", "small": "圆角调小", None: "圆角恢复风格默认", "large": "圆角调大"}[RADIUS_STEPS[j]])
        elif o == "density":
            if ex["tweaks"].get("density") == op["value"]:
                refused.append("间距已经是这样了")
            else:
                ex["tweaks"]["density"] = op["value"]
                done.append("间距调宽松" if op["value"] == "loose" else "间距调紧凑")
        elif o == "name":
            b["site_name"] = b["brand"]["name"] = op["value"][:40]
            done.append(f"站名改成“{op['value'][:40]}”")
        elif o == "style":
            if op["style"] == style:
                refused.append(f"现在用的就是 {op['style']}")
            elif op["style"] not in _usable():
                refused.append(f"{op['style']} 这个风格还不能用")
            else:
                style = op["style"]
                done.append(f"风格换成{L.STYLE[style][0]}（{style}）")
        elif o == "add_feature":
            k = op["kind"]
            if k not in BUILDABLE:
                refused.append(f"{FEATURE_ZH.get(k, k)}：这一版还做不出来，先没加")
            elif have(k):
                refused.append(f"已经有{FEATURE_ZH[k]}了")
            else:
                b["features"].append({"id": "F0", "kind": k, "priority": "P1", "source": "user", "note": "对话修改时加的"})
                goal = {"booking": "booking", "contact_form": "leads"}.get(k)
                if goal and not any(g["kind"] == goal for g in b["goals"]):
                    b["goals"].append({"id": "G0", "kind": goal, "description": GOAL_DESC[goal], "priority": "P1", "source": "user"})
                done.append(f"加了{FEATURE_ZH[k]}")
        elif o == "remove_feature":
            k = op["kind"]
            if not have(k):
                refused.append(f"本来就没有{FEATURE_ZH.get(k, k)}")
                continue
            if k == "catalog" and any(g["kind"] in ("sell", "inform") for g in b["goals"]):
                refused.append("菜单/商品页是“" + "、".join(g["description"] for g in b["goals"] if g["kind"] in ("sell", "inform"))
                               + "”这个目标必需的，没删；要删请先说明网站不再做这件事")
                continue
            b["features"] = [f for f in b["features"] if f["kind"] != k]
            b["goals"] = [g for g in b["goals"] if GOAL_FEATURE.get(g["kind"]) != k]
            done.append(f"去掉了{FEATURE_ZH.get(k, k)}")
    _renumber(b)
    return b, style, done, refused, ex


def teach(brief: dict, ops: list[dict], done: list[str]) -> list[str]:
    """把这次修改变成可以喂给它的句子（以后同行业都这样）。只对“行业层面”的修改给建议：去功能、换风格。"""
    ptype = brief["product_type"]["value"]
    word = (L.PRODUCT.get(ptype) or [None])[0]
    if not word or not done:
        return []
    out = []
    for op in ops:
        if op["op"] == "remove_feature" and any(FEATURE_ZH.get(op["kind"], "") in d and "去掉" in d for d in done):
            out.append(f"{word}不要{TEACH_WORD.get(op['kind'], L.FEATURES[op['kind']][0])}")
        elif op["op"] == "style" and any(op["style"] in d for d in done):
            out.append(f"{word}要用{L.STYLE[op['style']][0]}风格")
    return out
