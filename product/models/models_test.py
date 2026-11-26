#!/usr/bin/env python3
"""模型接入层测试：用本机假服务模拟两种协议和各种出错，不联网、不用真密钥。期望在运行前写好。
用法：timeout 120 python3 -I models_test.py"""
import json
import os
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["AISITE_MODELS"] = os.path.join(tempfile.mkdtemp(prefix="mt-"), "models.json")
for k in [k for k in os.environ if k.startswith("AISITE_KEY_")] + ["SITE_BUILDER_API_KEY"]:
    os.environ.pop(k, None)
import client  # noqa: E402
import config  # noqa: E402
import providers  # noqa: E402
from fake_provider import KEY, Fake  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


def err(fn):
    try:
        fn()
        return None
    except client.ModelError as e:
        return e


fake = Fake(lambda proto, body: "收到：" + proto)
try:
    r = client.chat(fake.conn("openai"), "系统", "你好")
    q = fake.requests[-1]
    expect("OpenAI 兼容协议：路径、模型、system/user 两条消息、Bearer 密钥都对", r["text"] == "收到：openai" and q["path"] == "/oai/chat/completions"
           and q["body"]["model"] == "ok" and [m["role"] for m in q["body"]["messages"]] == ["system", "user"], q)
    r = client.chat(fake.conn("anthropic"), "系统", "你好")
    q = fake.requests[-1]
    expect("Anthropic 协议：路径、system 放顶层、x-api-key 都对", r["text"] == "收到：anthropic" and q["path"] == "/anth/v1/messages"
           and q["body"]["system"] == "系统" and q["body"]["messages"] == [{"role": "user", "content": "你好"}], q)
    wrong = "sk-wrong-SECRET-9876"
    e = err(lambda: client.chat(fake.conn("openai", key=wrong), "s", "u"))
    expect("密钥不对 → 报“密钥不对”，错误信息里不出现密钥（服务商回显了也要抹掉）", e and e.kind == "auth" and wrong not in str(e), str(e))
    n0 = len(fake.requests)
    e = err(lambda: client.chat(dict(fake.conn("openai"), key=""), "s", "u"))
    expect("没填密钥 → 直接报“还没填密钥”，不发请求", e and e.kind == "no_key" and len(fake.requests) == n0)
    expect("限流一次 → 自动再试一次就成功", client.chat(fake.conn("openai", "rate-once"), "s", "u")["text"] and fake.counts["rate-once"] == 2)
    e = err(lambda: client.chat(fake.conn("openai", "rate"), "s", "u"))
    expect("一直限流 → 只重试一次就停（不无限重试）", e and e.kind == "rate" and fake.counts["rate"] == 2, (e, fake.counts.get("rate")))
    expect("服务端出错一次 → 再试一次成功", client.chat(fake.conn("anthropic", "server-once"), "s", "u")["text"])
    t0 = time.time()
    e = err(lambda: client.chat(fake.conn("openai", "slow"), "s", "u", timeout=1))
    expect("超时 → 最多两次就放弃，报“等太久”", e and e.kind == "timeout" and time.time() - t0 < 6, (e, time.time() - t0))
    e = err(lambda: client.chat(fake.conn("openai", "redirect"), "s", "u"))
    expect("服务商返回跳转 → 不跟随（防止把密钥带到别处）", e and e.kind == "bad_response" and "跳转" in str(e), str(e))
    for m, why in (("garbage", "不是 JSON"), ("huge", "超过 2MB"), ("empty", "空回复")):
        e = err(lambda: client.chat(fake.conn("openai", m), "s", "u"))
        expect(f"回复{why} → 报“看不懂”", e and e.kind == "bad_response", e)
    e = err(lambda: client.chat(dict(fake.conn("openai"), base_url=fake.openai_url + "/nope"), "s", "u"))
    expect("地址不对（404）→ 报“接口地址或模型名不对”", e and e.kind == "not_found", e)
    expect("获取模型列表：两种协议都行", client.list_models(fake.conn("openai")) == ["model-a", "model-b", "ok"]
           and client.list_models(fake.conn("anthropic")) == ["model-a", "model-b", "ok"])
    expect("调用记录不含内容和密钥", all(KEY not in json.dumps(x) and "你好" not in json.dumps(x) for x in client.LOG) and len(client.LOG) > 5)
finally:
    fake.close()

J = client.extract_json
expect("取 JSON：容忍前后文字和代码块", J('好的：\n```json\n{"a": 1}\n```\n以上') == {"a": 1})
expect("取 JSON：字符串里的括号和转义引号不误判", J('{"t": "a}b\\"c{", "n": {"x": 2}} 尾巴') == {"t": 'a}b"c{', "n": {"x": 2}})
expect("取 JSON：没有就报错", isinstance(err(lambda: J("没有对象")), client.ModelError))
b = client.Budget(2)
b.take(); b.take()
expect("调用次数上限：第 3 次报“次数用完”", (err(b.take) or client.ModelError("x")).kind == "budget")

# ---------------- 设置与密钥
config.set_provider("deepseek", key="sk-abcdefgh12345678")
mode = stat.S_IMODE(os.stat(config.path()).st_mode)
expect("密钥文件权限 600（只有自己能读）", mode == 0o600, oct(mode))
view = json.dumps(config.public_view(), ensure_ascii=False)
expect("对外只给末四位，任何地方都没有完整密钥", "sk-abcdefgh12345678" not in view and "••••5678" in view)
expect("密钥文件不在 brain 文件夹里（默认 ~/.aisite），打包不会带走", "/brain/" not in os.path.expanduser("~/.aisite/models.json"))
for url, good in (("http://example.com/v1", False), ("http://127.0.0.1:11434/v1", True), ("https://u:p@x.com/v1", False),
                  ("ftp://x.com", False), ("https://api.deepseek.com/v1/", True)):
    try:
        config.check_base_url(url)
        r = True
    except ValueError:
        r = False
    expect(f"接口地址检查：{url} → {'允许' if good else '拒绝'}", r == good)
os.environ["AISITE_KEY_MOONSHOT"] = "sk-env-moonshot-0000"
os.environ["SITE_BUILDER_API_KEY"] = "sk-legacy-anthropic-1111"
expect("环境变量也能给密钥（含旧的 SITE_BUILDER_API_KEY）", config.key_for("moonshot") == "sk-env-moonshot-0000"
       and config.key_for("anthropic") == "sk-legacy-anthropic-1111")
expect("没配用途 → 走规则版（返回 None）", config.for_role("understand") is None)
try:
    config.set_role("understand", "deepseek", "rm -rf /")
    r = False
except ValueError:
    r = True
expect("模型名有空格等怪字符 → 拒绝", r)
config.set_role("understand", "deepseek", "deepseek-chat")
c = config.for_role("understand")
expect("配好用途 → 拿到协议、地址、密钥、模型", c["protocol"] == "openai" and c["base_url"] == "https://api.deepseek.com/v1"
       and c["key"] == "sk-abcdefgh12345678" and c["model"] == "deepseek-chat")
try:
    config.set_provider("deepseek", key="sk-has space")
    r = False
except ValueError:
    r = True
expect("密钥里有空格（多复制了）→ 提示格式不对", r)

# 填写模板：原样复制过去就能用（全空 → 规则版），填一家的密钥就能连
import shutil
_tpl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models.example.json")
_old = os.environ["AISITE_MODELS"]
for _k in [k for k in os.environ if k.startswith("AISITE_KEY_")] + ["SITE_BUILDER_API_KEY"]:
    os.environ.pop(_k, None)  # 前面的测试设过环境变量密钥，这里要看“只有模板”的情况
os.environ["AISITE_MODELS"] = os.path.join(tempfile.mkdtemp(prefix="mt-tpl-"), "models.json")
shutil.copy(_tpl, os.environ["AISITE_MODELS"])
_tj = json.load(open(_tpl, encoding="utf-8"))
_pv = config.public_view()
expect("填写模板：列出所有服务商（含 Gemini），密钥全空，各用途都走规则版",
       set(_tj["providers"]) == set(providers.BY_ID) and not any(p["has_key"] for p in _pv["providers"])
       and all(config.for_role(r) is None for r in providers.ROLES), [p["id"] for p in _pv["providers"] if p["has_key"]])
expect("填写模板：模板里没有任何真实密钥", all(not (v.get("key") or "") for v in _tj["providers"].values()))
_tj["providers"]["gemini"]["key"] = "AIzaTESTKEY1234567890"
_tj["roles"]["copy"] = {"provider": "gemini", "model": "gemini-x"}
json.dump(_tj, open(os.environ["AISITE_MODELS"], "w", encoding="utf-8"), ensure_ascii=False)
_c = config.for_role("copy")
expect("填写模板：只填 Gemini 的密钥和用途 → 走 OpenAI 兼容协议连 Gemini 官方地址",
       _c["protocol"] == "openai" and _c["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai" and _c["key"].endswith("7890")
       and "AIzaTESTKEY1234567890" not in json.dumps(config.public_view()))
os.environ["AISITE_MODELS"] = _old

# .env：只认 AISITE_ 开头的变量和 SITE_BUILDER_API_KEY；不覆盖已有环境变量；AISITE_MODEL 给没分配的用途兜底
envd = tempfile.mkdtemp(prefix="env-")
ef = os.path.join(envd, ".env")
open(ef, "w", encoding="utf-8").write("# 注释\nexport AISITE_KEY_DEEPSEEK=\"sk-env-1234567890\"\nPATH=/evil\nAISITE_MODEL=deepseek:deepseek-chat\n"
                                      "LD_PRELOAD=/tmp/x.so\nAISITE_KEY_OPENAI=\n = 无名\n")
old_path = os.environ.get("PATH")
os.environ["AISITE_KEY_QWEN"] = "sk-already-here-9999"
open(ef, "a", encoding="utf-8").write("AISITE_KEY_QWEN=sk-from-file-0000\n")
got = config.load_env([ef, os.path.join(envd, "不存在.env")])
expect(".env：读到 AISITE_ 开头的变量（去掉 export 和引号），PATH、LD_PRELOAD、空值都不碰，已有的不覆盖",
       set(got) == {"AISITE_KEY_DEEPSEEK", "AISITE_MODEL"} and os.environ["AISITE_KEY_DEEPSEEK"] == "sk-env-1234567890"
       and os.environ.get("PATH") == old_path and "LD_PRELOAD" not in os.environ and os.environ["AISITE_KEY_QWEN"] == "sk-already-here-9999", got)
d0 = config.load()
d0["roles"] = {}
d0["providers"].pop("deepseek", None)
config.save(d0)
fr = config.for_role("copy")
pv = config.public_view()
expect(".env：AISITE_MODEL 给没分配的用途兜底，密钥来自环境变量；界面只看到末四位并标明来自 .env",
       fr and fr["id"] == "deepseek" and fr["model"] == "deepseek-chat" and fr["key"] == "sk-env-1234567890"
       and pv["roles"]["copy"].get("from_env") and "sk-env-1234567890" not in json.dumps(pv, ensure_ascii=False)
       and next(p for p in pv["providers"] if p["id"] == "deepseek")["key_source"] == "环境变量", (fr and {k: fr[k] for k in ("id", "model")}, pv["roles"]["copy"]))
config.set_role("copy", "anthropic", "claude-sonnet-5-5")
expect(".env：界面里单独分配过的用途以界面为准", config.for_role("copy")["id"] == "anthropic")
for k in ("AISITE_KEY_DEEPSEEK", "AISITE_MODEL", "AISITE_KEY_QWEN"):
    os.environ.pop(k, None)
expect("仓库里的 env.example 模板存在、没有填任何真密钥；.env 被 git 忽略",
       os.path.exists(os.path.join(HERE, "..", "..", "env.example"))
       and not any(l.split("=", 1)[1].strip() for l in open(os.path.join(HERE, "..", "..", "env.example"), encoding="utf-8")
                   if l.startswith("AISITE_KEY_") and "=" in l)
       and ".env*" in open(os.path.join(HERE, "..", "..", ".gitignore"), encoding="utf-8").read())

print(f"\n模型接入：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
