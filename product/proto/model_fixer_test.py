#!/usr/bin/env python3
"""模型修复者测试（假的流式回复，不调用真实模型）。"""
import itertools, json, os, sys, tempfile
os.environ["AISITE_MODELS"] = os.path.join(tempfile.mkdtemp(prefix="mf-"), "models.json")  # 不碰真实的模型设置
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from model_fixer import ModelFixer, ModelUnavailable, http_transport  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


def chunks(text, k=37):
    for i in range(0, len(text), k):
        yield text[i:i + k]


FILES = {"site.json": '{"id":"x"}', "custom/site.js": "document.querySelector('#a').addEventListener('click',f)"}
ERR = ["浏览器·脚本报错：/menu/ → Cannot read properties of null (reading 'addEventListener')"]
good = {"reason": "元素不存在时没判断", "changes": [{"op": "write", "path": "custom/site.js", "content": "var a=document.querySelector('#a'); if(a){a.addEventListener('click',f)}"}]}

f = ModelFixer(transport=lambda req: chunks(json.dumps(good, ensure_ascii=False)))
ch = f(FILES, ERR, "", "fast-fix", 1)
expect("正常回复：解析出 1 条改动", len(ch) == 1 and ch[0].path == "custom/site.js" and "if(a)" in ch[0].content, ch)

wrapped = "好的，修复如下：\n```json\n" + json.dumps(good, ensure_ascii=False) + "\n```\n希望有帮助。"
expect("包在说明文字和代码块里也能解析", len(ModelFixer(transport=lambda r: chunks(wrapped))(FILES, ERR, "", "fast-fix", 1)) == 1)

f = ModelFixer(transport=lambda r: chunks('{"reason": "x", "changes": [{"op": "write", "path": "a.html"}]}'))
expect("格式不对：返回空改动", f(FILES, ERR, "", "fast-fix", 1) == [] and "缺少 content" in f.last_note, f.last_note)
req2 = f.build_request(FILES, ERR, "", "fast-fix", 2)
expect("格式不对：下一轮提示里告诉模型哪里不对", "上一轮你的回复有问题：第 1 条 write 缺少 content" in req2["messages"][0]["content"])

f = ModelFixer(transport=lambda r: chunks("我想想。" + "{不是 JSON"))
expect("不是 JSON：返回空改动并说明", f(FILES, ERR, "", "fast-fix", 1) == [] and f.last_note, f.last_note)

forever = lambda r: itertools.cycle(["我再检查一下这个文件。", "我再检查一下这个文件。"])  # 永远不结束的流
f = ModelFixer(transport=forever)
expect("无限复读的流：被复读检测中断（不会永远读下去）", f(FILES, ERR, "", "fast-fix", 1) == [] and "复读" in f.last_note, f.last_note)

endless_new = lambda r: (f"第{i}段新内容，" for i in itertools.count())  # 永远不结束、也不复读
f = ModelFixer(transport=endless_new)
expect("无限但不复读的流：被长度上限中断", f(FILES, ERR, "", "fast-fix", 1) == [] and "超过" in f.last_note, f.last_note)


def broken(r):
    yield '{"reason": "'
    raise TimeoutError("读超时")


f = ModelFixer(transport=broken)
expect("网络中断：这一轮作废并记下原因，不抛出", f(FILES, ERR, "", "fast-fix", 1) == [] and "TimeoutError" in f.last_note, f.last_note)

req = ModelFixer().build_request(FILES, ERR, "同样的报错又出现了", "deep-debug", 3)
u = req["messages"][0]["content"]
expect("请求里有报错、守卫提醒、策略说明和相关文件",
       ERR[0] in u and "同样的报错又出现了" in u and "两个不同的根因假设" in u and "--- custom/site.js" in u, u[:300])
expect("请求里提到报错的文件排在前面", u.index("--- custom/site.js") < u.index("--- site.json"))
big = {f"pages/p{i}.json": "x" * 9000 for i in range(10)}
u = ModelFixer().build_request(big, ERR, "", "fast-fix", 1)["messages"][0]["content"]
expect("文件太多时有篇幅上限（截断并注明省略）", len(u) < 60000 and "省略，超出篇幅" in u and "截断" in u, len(u))

old = os.environ.pop("SITE_BUILDER_API_KEY", None)
try:
    next(http_transport({"model": "m"}))
    expect("没有密钥：明确报未配置", False)
except ModelUnavailable as e:
    expect("没有密钥：明确报未配置，不尝试联网", "未配置" in str(e))
finally:
    if old is not None:
        os.environ["SITE_BUILDER_API_KEY"] = old
# 工作台“模型设置”里给“修复”配了模型 → 默认就用它（OpenAI 兼容协议也行）
sys.path.insert(0, os.path.join(HERE, "..", "models"))
import config  # noqa: E402
from fake_provider import KEY, Fake  # noqa: E402
fake = Fake(lambda proto, body: json.dumps(good, ensure_ascii=False))
try:
    config.set_provider("custom", key=KEY, base_url=fake.openai_url)
    config.set_role("fix", "custom", "ok")
    f = ModelFixer()
    ch = f(FILES, ERR, "", "fast-fix", 1)
    expect("按“模型设置”配的服务商修复：OpenAI 兼容协议也能用，解析出改动", f.model == "ok" and len(ch) == 1
           and fake.requests[-1]["path"] == "/oai/chat/completions", (f.model, ch))
    config.set_role("fix", None, None)
finally:
    fake.close()
print(f"模型修复者：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
