"""用户选择回流：记录每次选了哪种风格，同行业多数人选的排到前面（推荐越用越准）。

隐私：只存行业、给了哪些候选、选了哪个，以及原话的哈希（用来去重）；不存用户原话。
"""
from __future__ import annotations

import hashlib
import json
import os
import time

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runs", "choices.jsonl")


def record(product_type: str, offered: list[str], chosen: str, text: str, path: str = DEFAULT_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%d %H:%M"), "product_type": product_type, "offered": offered, "chosen": chosen,
           "text_hash": hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def stats(path: str = DEFAULT_PATH) -> dict:
    """{行业: {风格: 次数}}；同一句话重复选只算最后一次。"""
    if not os.path.exists(path):
        return {}
    last = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            last[(r["product_type"], r["text_hash"])] = r["chosen"]
    out = {}
    for (pt, _), style in last.items():
        out.setdefault(pt, {}).setdefault(style, 0)
        out[pt][style] += 1
    return out


def favourite(product_type: str, path: str = DEFAULT_PATH, min_votes: int = 2):
    """同行业至少 min_votes 次、且占一半以上的风格；没有就返回 None。"""
    s = stats(path).get(product_type, {})
    total = sum(s.values())
    if total < min_votes:
        return None
    style, n = max(s.items(), key=lambda kv: (kv[1], kv[0]))
    return (style, n, total) if n * 2 > total else None
