#!/usr/bin/env python3
"""模型修复者：把报错、守卫的提醒和相关文件交给模型，要它只回一批 JSON 改动。

* 接口与模拟修复者相同：fixer(files, errors, hint, strategy, round) → [Change]。
* 流式读取回复，边读边过复读检测（RepeatGuard）；复读、超长、超时都会中断，绝不无限读下去。
* 回复解析不了、格式不对时返回空改动，并在下一轮提示里告诉模型上一轮哪里不对（经验 P006）。
* 密钥只从 SITE_BUILDER_API_KEY 读，不碰任何其他凭据；没有密钥就明确报“未配置”，不假装能用。
* transport 可替换：测试用假的流，产品里换成真实的 HTTP 流。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from repeat_guard import RepeatGuard  # noqa: E402
from workspace import Change  # noqa: E402

MAX_OUTPUT_CHARS = 200_000
FILE_BUDGET = 40_000
PER_FILE = 8_000


class ModelUnavailable(RuntimeError):
    pass


SYSTEM = """你是 AI 建站工作台里的“修复 Agent”。你只做一件事：根据报错，给出一批最小的文件改动，让报错消失。

什么时候改什么：
- 报错以“图纸·”开头：改图纸文件（brief.json、site.json、pages/*.json），必须符合图纸格式，只能引用已存在的页面、区块、素材、功能。
- 报错以“浏览器·”开头：多数是 custom/site.js 或 custom/site.css 的问题；页面结构问题回到 pages/*.json 改。
- 不要改与报错无关的文件；不要为了消除报错而删掉功能。

输出格式（只输出这一个 JSON 对象，不要任何其他文字）：
{"reason": "一句话根因", "changes": [{"op": "write", "path": "相对路径", "content": "完整的新文件内容"}]}
op 只能是 write、delete、rename（rename 要给 "to"）。路径必须在项目内，不能碰 .git。
如果收到“上一轮的修法没有命中根因”之类的提醒，必须换一种修法，不要重复上一轮。"""


def http_transport(request: dict, timeout: float = 120.0):
    """真实的流式 HTTP 调用（Anthropic Messages API 的 SSE 格式）。逐段产出文本。"""
    key = os.environ.get("SITE_BUILDER_API_KEY")
    if not key:
        raise ModelUnavailable("未配置 SITE_BUILDER_API_KEY，模型修复者不能真实调用")
    url = os.environ.get("SITE_BUILDER_API_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
    req = urllib.request.Request(url, data=json.dumps(dict(request, stream=True)).encode("utf-8"), method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:  # 每行一个 SSE 字段；连接在 timeout 秒没有数据就会抛出
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            ev = json.loads(line[5:] or "{}")
            if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                yield ev["delta"]["text"]
            elif ev.get("type") == "message_stop":
                return


def configured_transport(role: str = "fix"):
    """按工作台“模型设置”里给“修复”配的服务商和模型调用（两种协议都行，一次拿完整回复再交给复读检测）。
    没配置返回 None。"""
    sys.path.insert(0, os.path.join(HERE, "..", "models"))
    import client
    import config
    conn = config.for_role(role)
    if not conn:
        return None, None

    def transport(request: dict, timeout: float = 120.0):
        try:
            r = client.chat(conn, request.get("system", ""), request["messages"][-1]["content"],
                            max_tokens=int(request.get("max_tokens", 8000)), timeout=timeout)
        except client.ModelError as e:
            raise ModelUnavailable(str(e))
        yield r["text"]
    return transport, conn["model"]


class ModelFixer:
    def __init__(self, transport=None, model: str | None = None, max_tokens: int = 8000):
        if transport is None:
            transport, configured = configured_transport()
            model = model or configured
        self.transport = transport or http_transport
        self.model, self.max_tokens = model or "claude-sonnet-5-5", max_tokens
        self.last_note = ""      # 上一轮回复的问题，下一轮告诉模型
        self.notes: list[str] = []
        self.requests: list[dict] = []

    # ---------- 组织输入 ----------
    def _files_block(self, files: dict, errors: list[str]) -> str:
        mentioned = {f for f in files if any(f in e for e in errors)}
        order = sorted(files, key=lambda f: (f not in mentioned, not f.startswith("custom/"), f))
        out, used = [], 0
        for f in order:
            text = files[f]
            if len(text) > PER_FILE:
                text = text[:PER_FILE] + f"\n…（截断，原文 {len(files[f])} 字符）"
            if used + len(text) > FILE_BUDGET:
                out.append(f"--- {f}（省略，超出篇幅）")
                continue
            used += len(text)
            out.append(f"--- {f}\n{text}")
        return "\n".join(out)

    def build_request(self, files, errors, hint, strategy, rnd) -> dict:
        how = {"fast-fix": "直接给出最小修复。",
               "deep-debug": "先在 reason 里列出两个不同的根因假设并说明选哪个、为什么，再给改动。",
               "rewrite-file": "允许整份重写出问题的那个文件，但保持它原有的功能。"}.get(strategy, "")
        user = (f"第 {rnd} 轮修复。策略：{strategy}。{how}\n\n"
                + (f"上一轮你的回复有问题：{self.last_note}\n\n" if self.last_note else "")
                + (f"守卫的提醒和当前报错：\n{hint}\n\n" if hint else "")
                + "当前报错（共 %d 条）：\n" % len(errors) + "\n".join(errors[:30])
                + "\n\n项目文件：\n" + self._files_block(files, errors))
        return {"model": self.model, "max_tokens": self.max_tokens, "system": SYSTEM,
                "messages": [{"role": "user", "content": user}]}

    # ---------- 解析输出 ----------
    @staticmethod
    def parse(text: str) -> tuple[list[Change], str]:
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b <= a:
            return [], "回复里没有 JSON 对象"
        try:
            obj = json.loads(text[a:b + 1])
        except ValueError as e:
            return [], f"JSON 解析失败：{e}"
        raw = obj.get("changes")
        if not isinstance(raw, list) or not raw:
            return [], "缺少 changes 列表或列表为空"
        out = []
        for i, c in enumerate(raw, 1):
            if not isinstance(c, dict) or c.get("op") not in ("write", "delete", "rename") or not isinstance(c.get("path"), str):
                return [], f"第 {i} 条改动格式不对（需要 op 和 path）"
            if c["op"] == "write" and not isinstance(c.get("content"), str):
                return [], f"第 {i} 条 write 缺少 content"
            if c["op"] == "rename" and not isinstance(c.get("to"), str):
                return [], f"第 {i} 条 rename 缺少 to"
            out.append(Change(op=c["op"], path=c["path"], content=c.get("content", ""), to=c.get("to", "")))
        return out, ""

    # ---------- 一轮 ----------
    def __call__(self, files, errors, hint, strategy, rnd) -> list[Change]:
        req = self.build_request(files, errors, hint, strategy, rnd)
        self.requests.append(req)
        guard, text, note = RepeatGuard(), [], ""
        try:
            n = 0
            for piece in self.transport(req):
                text.append(piece)
                n += len(piece)
                if guard.feed(piece):
                    note = guard.describe()
                    break
                if n > MAX_OUTPUT_CHARS:
                    note = f"回复超过 {MAX_OUTPUT_CHARS} 字符，已中断"
                    break
            else:
                if guard.finish():
                    note = guard.describe()
        except ModelUnavailable:
            raise
        except Exception as e:  # 网络中断、超时：这一轮作废，交给守卫计数
            note = f"模型调用失败：{type(e).__name__} {str(e)[:120]}"
        changes = []
        if not note:
            changes, note = self.parse("".join(text))
        self.last_note = note
        self.notes.append(note)
        return changes
