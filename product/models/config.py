"""模型设置：哪些服务商填了密钥、每个用途用哪个模型。

* 存在 ~/.aisite/models.json（可用环境变量 AISITE_MODELS 指到别处），文件权限 600，只有你能读。
  它不在 brain 文件夹里，所以打包、导出都不会把密钥带出去。
* 密钥也可以用环境变量给：AISITE_KEY_<服务商ID大写>（例如 AISITE_KEY_DEEPSEEK）；Anthropic 兼容旧的 SITE_BUILDER_API_KEY。
* 也可以写在 .env 文件里（仓库根目录的 .env，或 ~/.aisite/.env；模板见仓库根目录 env.example）：
  只认 AISITE_ 开头的变量和 SITE_BUILDER_API_KEY；已经在环境里的不覆盖。.env 不进 git。
  AISITE_MODEL=服务商:模型（例如 anthropic:claude-sonnet-5-5）= 没在界面里分配过的用途都用它。
* 对外（界面）只给“有没有密钥、末四位”，任何接口都不返回完整密钥。
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

from providers import BY_ID, ROLES

MODEL_RE = re.compile(r"^[\w.:/@+-]{1,120}$")


ENV_OK = re.compile(r"^(AISITE_[A-Z0-9_]{1,60}|SITE_BUILDER_API_KEY)$")


def env_files() -> list[str]:
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    return [os.path.join(root, ".env"), os.path.expanduser("~/.aisite/.env")]


def load_env(files: list[str] | None = None) -> list[str]:
    """读 .env：每行 名字=值（# 开头是注释，值可以带引号）。返回读进来的变量名（不返回值）。"""
    got = []
    for f in files or env_files():
        try:
            lines = open(f, encoding="utf-8").read().splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
            if ENV_OK.match(k) and v and k not in os.environ:
                os.environ[k] = v
                got.append(k)
    return got


def env_default_role() -> dict | None:
    v = os.environ.get("AISITE_MODEL", "")
    if ":" not in v:
        return None
    pid, model = v.split(":", 1)
    pid, model = pid.strip(), model.strip()
    if pid in BY_ID and MODEL_RE.match(model):
        return {"provider": pid, "model": model}
    return None


def path() -> str:
    return os.environ.get("AISITE_MODELS") or os.path.expanduser("~/.aisite/models.json")


def load() -> dict:
    try:
        d = json.load(open(path(), encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("providers", {})
    d.setdefault("roles", {})
    d.setdefault("limits", {"max_calls_per_session": 12, "timeout": 60})
    return d


def save(d: dict):
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # 只有自己能读写
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def check_base_url(url: str) -> str:
    """只允许 https；http 只允许本机（例如 Ollama）。地址里不能带账号密码。"""
    url = (url or "").strip().rstrip("/")
    u = urlparse(url)
    if not url or u.scheme not in ("https", "http") or not u.hostname:
        raise ValueError("接口地址不对：要以 https:// 开头")
    if u.username or u.password:
        raise ValueError("接口地址里不要带账号密码，密钥请填在密钥栏")
    if u.scheme == "http" and u.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("为保护密钥，只有本机地址（127.0.0.1 / localhost）可以用 http，其余必须 https")
    return url


def key_for(pid: str, d: dict | None = None) -> str:
    d = d or load()
    k = (d["providers"].get(pid) or {}).get("key") or os.environ.get(f"AISITE_KEY_{pid.upper()}", "")
    if not k and pid == "anthropic":
        k = os.environ.get("SITE_BUILDER_API_KEY", "")
    return k.strip()


def resolved(pid: str, d: dict | None = None) -> dict:
    """一个服务商的完整连接信息（含密钥，只在本进程内用，不对外返回）。"""
    d = d or load()
    if pid not in BY_ID:
        raise ValueError("没有这个服务商")
    pre, mine = BY_ID[pid], d["providers"].get(pid) or {}
    base = mine.get("base_url") or pre["base_url"]
    if not base:
        raise ValueError("自定义服务商需要先填接口地址")
    return {"id": pid, "name": pre["name"], "protocol": mine.get("protocol") or pre["protocol"], "base_url": check_base_url(base),
            "key": key_for(pid, d), "needs_key": pre["needs_key"]}


def for_role(role: str, d: dict | None = None) -> dict | None:
    """某个用途配置好的模型；没配置返回 None（这时走规则版）。"""
    d = d or load()
    r = d["roles"].get(role)
    if not r or not r.get("provider") or not r.get("model"):
        r = env_default_role()  # 界面里没分配过：看 .env / 环境变量里的 AISITE_MODEL
        if not r:
            return None
    c = resolved(r["provider"], d)
    c["model"] = r["model"]
    c["role"] = role
    return c


def mask(k: str) -> str:
    return ("••••" + k[-4:]) if len(k) >= 8 else ("••••" if k else "")


def public_view() -> dict:
    """给界面看的：不含任何完整密钥。"""
    d = load()
    provs = []
    for pid, pre in BY_ID.items():
        mine = d["providers"].get(pid) or {}
        k = key_for(pid, d)
        src = "已保存" if mine.get("key") else ("环境变量" if k else "")
        provs.append({**{x: pre[x] for x in ("id", "name", "protocol", "key_url", "example_model", "needs_key")},
                      "note": pre.get("note", ""), "base_url": mine.get("base_url") or pre["base_url"],
                      "has_key": bool(k), "key_hint": mask(k), "key_source": src})
    env_role = env_default_role()
    return {"providers": provs, "roles": {r: {"label": ROLES[r], **(d["roles"].get(r) or ({**env_role, "from_env": True} if env_role else {}))} for r in ROLES},
            "limits": d["limits"], "file": path(), "env_files": env_files()}


def set_provider(pid: str, key: str | None = None, base_url: str | None = None, clear_key: bool = False):
    if pid not in BY_ID:
        raise ValueError("没有这个服务商")
    d = load()
    mine = d["providers"].setdefault(pid, {})
    if key is not None and key.strip():
        k = key.strip()
        if len(k) > 400 or re.search(r"\s", k):
            raise ValueError("密钥格式不对（不能有空格或换行，检查是不是复制多了）")
        mine["key"] = k
    if clear_key:
        mine.pop("key", None)
    if base_url is not None:
        if base_url.strip():
            mine["base_url"] = check_base_url(base_url)
        else:
            mine.pop("base_url", None)
    save(d)


def set_role(role: str, pid: str | None, model: str | None):
    if role not in ROLES:
        raise ValueError("没有这个用途")
    d = load()
    if not pid:
        d["roles"].pop(role, None)
    else:
        if pid not in BY_ID:
            raise ValueError("没有这个服务商")
        if not model or not MODEL_RE.match(model.strip()):
            raise ValueError("模型名不对（只能有字母、数字和 . : / @ + - _）")
        d["roles"][role] = {"provider": pid, "model": model.strip()}
    save(d)
