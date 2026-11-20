#!/usr/bin/env python3
"""复读检测测试：真复读必须在流式中途被拦下；正常输出（含大量相似条目）不能误伤。"""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from repeat_guard import RepeatGuard  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


def stream(text, seed=0):
    """按随机长度切块，模拟流式到达。返回 (是否拦下, 拦下时已读多少字符)。"""
    rng, g, i = random.Random(seed), RepeatGuard(), 0
    while i < len(text):  # 有界：i 每次至少加 1
        k = rng.randint(1, 60)
        if g.feed(text[i:i + k]):
            return True, i + k, g
        i += k
    return g.finish(), len(text), g


normal = json.dumps({"changes": [{"op": "write", "path": f"pages/p{i}.json",
                                  "content": f"第 {i} 页的内容，价格 {i * 7} 元"} for i in range(60)]}, ensure_ascii=False)
hit, _, _ = stream(normal)
expect("正常：60 条相似但不同的改动不误伤", not hit)

css = "".join(f".item-{i}{{margin:{i}px;padding:4px}}\n" for i in range(200))
expect("正常：200 行相似 CSS 不误伤", not stream(css)[0])

table = "| 序号 | 名称 |\n|---|---|\n" + "".join(f"| {i} | 名称{i} |\n" for i in range(100))
expect("正常：100 行表格不误伤", not stream(table)[0])

prose = "我先读一下报错。" * 3 + "根因是菜单数据为空时没有判断。我加上空值判断，然后重新构建。" + "这样就修好了。"
expect("正常：句子偶尔重复 3 次不误伤", not stream(prose)[0])

sentence = "好的，我来修复这个问题。我需要先检查一下文件。"
loop = sentence * 200
hit, at, g = stream(loop)
expect("复读：同一句无限重复，流式中途就拦下", hit and at < 2000, (hit, at))
expect("复读：找到的重复单元确实是那句话（起点可以在句中）", g.hit[2] in sentence * 2 and len(g.hit[2]) == len(sentence) and "连续重复" in g.describe(), g.describe())

block = ('{"op":"write","path":"pages/home.json","content":"<section id=\\"hero\\">同一个区块</section>"},\n') * 80
hit, at, _ = stream(normal[:3000] + block)
expect("复读：正常开头之后陷入同一大段重复，也能拦下", hit and at < 3000 + 2500, (hit, at))

think = "嗯" * 1000
expect("复读：单字重复（周期太短也要算）", stream(think)[0] or RepeatGuard(min_period=1).feed(think))

for seed in range(5):
    h, at, _ = stream(loop, seed)
    if not h or at > 2000:
        expect(f"复读：随机切块 {seed} 也能拦下", False, (h, at))
        break
else:
    expect("复读：5 种随机切块方式都能在 2000 字内拦下", True)

print(f"复读检测：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
