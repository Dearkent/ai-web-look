"""喂养学到的知识：读取与应用（只读这里；写入、试跑、撤回都在 feed.py）。

知识存在 knowledge/learned.json（可用环境变量 AISITE_KNOWLEDGE 指到别的目录，测试用）。
每条知识只含封闭字段，绝不含可执行的东西：
  word        新说法 → 已知行业，外加该行业常用功能       {"word","product_type","features"}
  correction  某行业的纠正：不要某功能 / 不要某风格家族 / 偏好某风格   {"product_type","avoid_feature"|"avoid_family"|"prefer_style"}
  site_ref    喜欢的网站抽出来的观感：家族、颜色、深浅、衬线  {"product_type","family","colors","dark","serif"}
规则：用户这一次说的话永远优先于学到的知识（学到的只补“没说的部分”）。
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def knowledge_dir() -> str:
    return os.environ.get("AISITE_KNOWLEDGE") or os.path.normpath(os.path.join(HERE, "..", "..", "knowledge"))


def path() -> str:
    return os.path.join(knowledge_dir(), "learned.json")


_override: list | None = None  # 试跑时临时替换整个知识库（feed.py 用），不落盘


def items(include_inactive: bool = False) -> list[dict]:
    if _override is not None:
        data = _override
    else:
        try:
            data = json.load(open(path(), encoding="utf-8")).get("items", [])
        except (OSError, ValueError):
            data = []
    return [x for x in data if include_inactive or x.get("status") == "active"]


class trial:
    """with learned.trial(候选知识列表): ... —— 在内存里试用，不写文件。"""

    def __init__(self, data: list[dict]):
        self.data = data

    def __enter__(self):
        global _override
        self.prev, _override = _override, self.data
        return self

    def __exit__(self, *a):
        global _override
        _override = self.prev


def product_words() -> dict[str, list[tuple[str, str]]]:
    """{行业: [(说法, 知识ID)]}，给 detect_product 用。"""
    out: dict = {}
    for x in items():
        if x["kind"] == "word":
            out.setdefault(x["product_type"], []).append((x["word"], x["id"]))
    return out


def for_type(product_type: str, kind: str) -> list[dict]:
    return [x for x in items() if x["kind"] == kind and x["product_type"] == product_type]
