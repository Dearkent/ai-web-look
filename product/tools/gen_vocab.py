#!/usr/bin/env python3
"""从 UI UX Pro Max 的 CSV 生成封闭词表 vocab.json，并生成 vocab.schema.json 供三份图纸引用。

只读取 CSV 数据，不执行对方仓库里的任何代码（经验 P011：规则只当数据）。
用法：python3 -I gen_vocab.py <CSV 目录> <来源提交号> <输出目录>
"""
import csv, json, sys, os

src, commit, out = sys.argv[1], sys.argv[2], sys.argv[3]

def rows(name):
    with open(os.path.join(src, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))

styles = rows("styles.csv")
landing = rows("landing.csv")
motion = rows("motion.csv")
products = rows("products.csv")

style_status = {}
for r in styles:
    style_status[r["Style ID"]] = {
        "name": r["Style Category"],
        "type": r["Type"],
        "status": r["Status"],
        "aliases": [a.strip() for a in r["Aliases"].split("|") if a.strip()] if r["Aliases"] else [],
        "replacement": ({"domain": r["Replacement Domain"], "id": r["Replacement ID"]}
                        if r["Replacement ID"] else None),
    }

patterns = {r["Pattern ID"]: {"name": r["Pattern Name"], "section_order": r["Section Order"],
                               "cta": r["Primary CTA Placement"],
                               "aliases": [a.strip() for a in r["Aliases"].split("|") if a.strip()]}
            for r in landing}

motion_cats = sorted({r["Category"] for r in motion})
motion_pairs = sorted({(r["Category"], r["Intensity Tier"]) for r in motion})

AGENTS = {  # 与调研档案“多 Agent 分工与任务路由”一节一一对应
    "orchestrator": "编排 Agent：理解请求、分派、汇总、向用户确认",
    "requirements": "需求分析 Agent：一句话 → 需求简报，最多问 3 个问题",
    "architect": "信息架构 Agent：站点地图、导航、用户流程",
    "design-director": "设计总监 Agent：选风格、定配色字体，产出 DESIGN.md + 设计令牌",
    "layout": "布局 Agent：每页区块顺序和对应组件，产出页面线框",
    "content": "文案 / 图片 Agent：写文案、生成或选图",
    "engineer": "工程 Agent：写代码、装依赖",
    "motion": "动效 Agent：在风格允许的档位内加动效",
    "reviewer": "审查 Agent：截图视觉评审、无障碍与性能检查",
    "fixer": "修复 Agent：读报错并修复",
    "learner": "学习 Agent：反思、整理、入库",
}

vocab = {
    "source": {"repo": "nextlevelbuilder/ui-ux-pro-max-skill", "commit": commit, "license": "MIT",
               "note": "仅提取 ID 与名称等事实数据"},
    "styles": style_status,
    "landing_patterns": patterns,
    "product_types": sorted({r["Product Type"] for r in products}),
    "motion_categories": motion_cats,
    "motion_available": [list(p) for p in motion_pairs],
    "motion_tiers": ["Subtle", "Standard", "Complex"],
    "agents": AGENTS,
}

usable_styles = sorted(k for k, v in style_status.items() if v["status"] != "deprecated")
schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://aisite.local/schemas/vocab.schema.json",
    "title": "封闭词表（由 gen_vocab.py 生成，勿手改）",
    "$defs": {
        "styleId": {"enum": usable_styles, "description": "风格 ID；已弃用的 ID 不在此列，检查脚本会给出替代"},
        "anyStyleId": {"enum": sorted(style_status), "description": "含已弃用 ID，仅用于提示替代"},
        "landingPatternId": {"enum": sorted(patterns)},
        "productType": {"enum": vocab["product_types"]},
        "motionCategory": {"enum": motion_cats},
        "motionTier": {"enum": vocab["motion_tiers"]},
        "agentId": {"enum": list(AGENTS)},
    },
}

os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "vocab.json"), "w", encoding="utf-8") as f:
    json.dump(vocab, f, ensure_ascii=False, indent=1)
with open(os.path.join(out, "vocab.schema.json"), "w", encoding="utf-8") as f:
    json.dump(schema, f, ensure_ascii=False, indent=1)
print(f"风格 {len(style_status)}（可用 {len(usable_styles)}）· 落地页模式 {len(patterns)} · "
      f"产品类型 {len(vocab['product_types'])} · 动效类别 {len(motion_cats)} · Agent {len(AGENTS)}")
