"""知识库名称 → ID 解析。图纸里一律写 ID；知识库内部（如 products.csv）按名称引用，需要经过这里。"""
import json, os, re

_V = None

def vocab():
    global _V
    if _V is None:
        here = os.path.dirname(os.path.abspath(__file__))
        _V = json.load(open(os.path.join(here, "..", "schemas", "vocab.json"), encoding="utf-8"))
    return _V

def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def resolve(name, domain):
    """domain: 'style' 或 'landing'。返回 (id, 说明)；找不到返回 (None, 原因)。
    已弃用的风格会顺着 replacement 跳到新的域和 ID。"""
    v = vocab()
    table = v["styles"] if domain == "style" else v["landing_patterns"]
    n = _norm(name)
    for k, e in table.items():
        names = [k, e["name"]] + e.get("aliases", [])
        if any(_norm(x) == n for x in names):
            rep = e.get("replacement") if domain == "style" else None
            if e.get("status") == "deprecated" and rep:
                return (f"{rep['domain']}:{rep['id']}", f"“{name}”已弃用，改用 {rep['domain']}:{rep['id']}")
            return (f"{domain}:{k}", "命中")
    return (None, f"“{name}”在 {domain} 词表里找不到")

def resolve_combo(text, domain):
    """解析“A + B”这类组合名。返回 {'ids': [...], 'unresolved': [...], 'notes': [...]}。
    先整串匹配别名；不行再逐段匹配，本域找不到就跨域（风格 ↔ 落地页）并跟随弃用跳转。
    解析不了的段落原样保留在 unresolved 里，调用方据此降低置信度或向用户提问。"""
    rid, why = resolve(text, domain)
    if rid:
        return {"ids": [rid], "unresolved": [], "notes": [why] if why != "命中" else []}
    out = {"ids": [], "unresolved": [], "notes": []}
    other = "landing" if domain == "style" else "style"
    for part in [x.strip() for x in text.split("+") if x.strip()]:
        for d in (domain, other):
            rid, why = resolve(part, d)
            if rid:
                if rid not in out["ids"]:
                    out["ids"].append(rid)
                if why != "命中" or d != domain:
                    out["notes"].append(f"{part} → {rid}" + ("（跨域）" if d != domain else ""))
                break
        else:
            out["unresolved"].append(part)
    return out
