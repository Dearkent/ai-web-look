"""调用模型：两种协议、超时、有限重试、不跟随跳转、密钥不进日志。

    chat(conn, system, user) -> {"text", "seconds", "usage"}     conn 来自 config.for_role / config.resolved（+ "model"）
    list_models(conn) -> [模型名]
    ModelError.kind：no_key / auth / not_found / rate / server / timeout / network / bad_response / budget / config

不会无限重试：限流（429）、服务端错误（5xx）、超时各最多再试一次，等待不超过 10 秒。
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

MAX_RESPONSE = 2 * 1024 * 1024
KIND_ZH = {"no_key": "还没填密钥", "auth": "密钥不对或没有权限", "not_found": "接口地址或模型名不对", "rate": "请求太频繁或额度用完了",
           "server": "服务商那边出错了", "timeout": "等太久没有回应", "network": "连不上服务商（检查网络或代理）",
           "bad_response": "服务商返回的内容看不懂", "budget": "这次的调用次数用完了（防止花太多钱）", "config": "设置不完整"}

LOG: list[dict] = []          # 最近的调用记录（不含内容和密钥），给界面看
_LOG_LOCK = threading.Lock()


class ModelError(RuntimeError):
    def __init__(self, kind: str, detail: str = ""):
        self.kind, self.detail = kind, detail
        super().__init__(KIND_ZH.get(kind, kind) + (f"：{detail}" if detail else ""))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # 跳转可能把密钥带到别的网站：一律不跟
        raise ModelError("bad_response", "服务商返回了跳转，为保护密钥没有跟随")


def _opener(url: str):
    handlers = [_NoRedirect()]
    if urlparse(url).hostname in ("127.0.0.1", "localhost", "::1"):
        handlers.append(urllib.request.ProxyHandler({}))  # 本机服务（如 Ollama）不走代理
    return urllib.request.build_opener(*handlers)


def _scrub(text: str, key: str) -> str:
    return text.replace(key, "••••") if key else text


def _request(conn: dict, method: str, path: str, body: dict | None, timeout: float) -> dict:
    key = conn.get("key", "")
    if conn.get("needs_key", True) and not key:
        raise ModelError("no_key", conn.get("name", ""))
    url = conn["base_url"].rstrip("/") + path
    headers = {"content-type": "application/json", "accept": "application/json"}
    if conn["protocol"] == "anthropic":
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    elif key:
        headers["authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            with _opener(url).open(req, timeout=timeout) as resp:
                raw = resp.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ModelError("bad_response", "回复太大")
            try:
                return json.loads(raw)
            except ValueError:
                raise ModelError("bad_response", "不是 JSON")
        except urllib.error.HTTPError as e:
            msg = _scrub(e.read(2000).decode("utf-8", "replace"), key)
            try:
                j = json.loads(msg)
                msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else (j.get("error") or j.get("message") or msg)
            except ValueError:
                pass
            msg = str(msg)[:200]
            if e.code in (401, 403):
                raise ModelError("auth", msg)
            if e.code == 404:
                raise ModelError("not_found", msg)
            if e.code == 400:
                raise ModelError("bad_response", f"请求被拒绝：{msg}")
            kind = "rate" if e.code == 429 else "server" if e.code >= 500 else "bad_response"
            last = ModelError(kind, f"HTTP {e.code} {msg}")
            if kind in ("rate", "server") and attempt == 0:
                ra = e.headers.get("Retry-After", "")
                time.sleep(min(float(ra), 10.0) if ra.replace(".", "", 1).isdigit() else 1.5)
                continue
            raise last
        except ModelError:
            raise
        except (socket.timeout, TimeoutError):
            last = ModelError("timeout", f"{timeout:.0f} 秒")
            if attempt == 0:
                continue
            raise last
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                last = ModelError("timeout", f"{timeout:.0f} 秒")
                if attempt == 0:
                    continue
                raise last
            raise ModelError("network", _scrub(str(reason), key)[:200])
    raise last or ModelError("network")


def _log(conn, ok, seconds, kind=""):
    with _LOG_LOCK:
        LOG.append({"at": time.strftime("%H:%M:%S"), "role": conn.get("role", ""), "provider": conn.get("id", ""),
                    "model": conn.get("model", ""), "ok": ok, "seconds": round(seconds, 1), "error": KIND_ZH.get(kind, kind)})
        del LOG[:-50]


def chat(conn: dict, system: str, user: str, max_tokens: int = 1500, timeout: float = 60.0, temperature: float = 0.3) -> dict:
    if not conn.get("model"):
        raise ModelError("config", "没有选模型")
    t0 = time.time()
    try:
        if conn["protocol"] == "anthropic":
            j = _request(conn, "POST", "/v1/messages", {"model": conn["model"], "max_tokens": max_tokens, "temperature": temperature,
                                                        "system": system, "messages": [{"role": "user", "content": user}]}, timeout)
            parts = j.get("content") if isinstance(j, dict) else None
            if not isinstance(parts, list):
                raise ModelError("bad_response", "缺少 content")
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
            usage = j.get("usage") or {}
        else:
            j = _request(conn, "POST", "/chat/completions", {"model": conn["model"], "max_tokens": max_tokens, "temperature": temperature,
                                                             "messages": [{"role": "system", "content": system},
                                                                          {"role": "user", "content": user}]}, timeout)
            try:
                text = j["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                raise ModelError("bad_response", "缺少 choices[0].message.content")
            usage = j.get("usage") or {}
        if not isinstance(text, str) or not text.strip():
            raise ModelError("bad_response", "回复是空的")
    except ModelError as e:
        _log(conn, False, time.time() - t0, e.kind)
        raise
    _log(conn, True, time.time() - t0)
    return {"text": text, "seconds": round(time.time() - t0, 2), "usage": usage}


def list_models(conn: dict, timeout: float = 20.0) -> list[str]:
    path = "/v1/models" if conn["protocol"] == "anthropic" else "/models"
    j = _request(conn, "GET", path, None, timeout)
    items = j.get("data") if isinstance(j, dict) else None
    if not isinstance(items, list):
        raise ModelError("bad_response", "模型列表格式不对")
    return sorted({str(x.get("id")) for x in items if isinstance(x, dict) and x.get("id")})[:300]


class Budget:
    """一次会话最多调用多少次模型。超了就报 budget，调用方退回规则版。"""

    def __init__(self, max_calls: int = 12):
        self.max_calls, self.used = max_calls, 0
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            if self.used >= self.max_calls:
                raise ModelError("budget", f"{self.max_calls} 次")
            self.used += 1


def extract_json(text: str):
    """从模型回复里取出第一个完整的 JSON 对象（容忍前后有说明文字或 ``` 包裹）。取不到抛 bad_response。"""
    a = text.find("{")
    while a >= 0:
        depth, inside, esc = 0, False, False
        for i in range(a, len(text)):
            ch = text[i]
            if inside:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    inside = False
                continue
            if ch == '"':
                inside = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[a:i + 1])
                    except ValueError:
                        break
        a = text.find("{", a + 1)
    raise ModelError("bad_response", "回复里没有完整的 JSON")
