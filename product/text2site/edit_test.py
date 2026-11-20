#!/usr/bin/env python3
"""对话式修改：一句话 → 修改操作 → 新简报。期望在运行前写好。
用法：python3 -I edit_test.py"""
import os
import sys
import tempfile

os.environ["AISITE_KNOWLEDGE"] = tempfile.mkdtemp(prefix="edit-know-")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edit  # noqa: E402
from understand import understand  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  {detail}"))
    (ok if cond else bad).append(name)


P = edit.parse
expect("一句话两处：颜色 + 加相册", P("把按钮换成绿色，再加一个相册")[0] == [{"op": "color", "hex": "#2E7D32", "zh": "绿色"},
                                                                     {"op": "add_feature", "kind": "gallery"}])
expect("色值", P("主色用 #2a9d8f")[0] == [{"op": "color", "hex": "#2A9D8F", "zh": "#2A9D8F"}])
expect("去掉页面", P("不要博客了")[0] == [{"op": "remove_feature", "kind": "blog"}])
expect("换风格（“复古”不被“复古未来”抢走）", P("换成复古风格")[0] == [{"op": "style", "style": "vintage-analog-retro-film"}])
expect("“深色”是风格不是颜色", P("改成深色的")[0] == [{"op": "style", "style": "dark-mode-oled"}])
expect("改名字（英文带空格）", P("名字改成 Blue Bottle Coffee")[0] == [{"op": "name", "value": "Blue Bottle Coffee"}])
expect("撤销", P("撤销")[0] == [{"op": "undo"}])
expect("看不懂的原样交回（不瞎改）", P("把第二张图片换个位置")[0] == [] and P("把第二张图片换个位置")[1] == ["把第二张图片换个位置"])
b = understand("帮我做个咖啡馆的网站，可以预约")
# 第十一轮：从待学清单里学来的
expect("改文字：整句照收（文字里带逗号也不拆开）", P("标题改成 下班后，来巷口喝一杯")[0] ==
       [{"op": "copy", "section": "hero", "field": "heading", "value": "下班后，来巷口喝一杯"}])
expect("改文字放在一句话最后：前面的照常拆，后面整段是新文字", P("字大一点，标题改成 下班后，来撸猫")[0] ==
       [{"op": "font", "dir": 1}, {"op": "copy", "section": "hero", "field": "heading", "value": "下班后，来撸猫"}])
expect("改文字：介绍、号召", P("介绍改成：提前约好时间")[0][0]["field"] == "body" and P("号召改成 来坐坐吧")[0][0]["section"] == "cta")
expect("字号、圆角、间距能听懂（“字大一点”以前在待学清单里）", [o["op"] for o in P("字大一点，圆角大一点，间距宽松一点")[0]] == ["font", "radius", "density"])
_, _, d, r, ex = edit.apply(b, "soft-ui-evolution", P("字大一点")[0])
_, _, d2, r2, ex2 = edit.apply(b, "soft-ui-evolution", P("字大一点")[0] * 3, ex)
expect("字号一档一档调，到头了会说", ex["tweaks"]["font"] == 1.12 and ex2["tweaks"]["font"] == 1.25 and any("最大" in x for x in r2), (ex2, r2))
_, _, d, r, ex = edit.apply(b, "soft-ui-evolution", P("改成直角")[0])
_, _, d3, r3, ex3 = edit.apply(b, "soft-ui-evolution", P("圆角大一点")[0], ex)
expect("圆角：直角 → 再调大回到小圆角", ex["tweaks"]["radius"] == "square" and ex3["tweaks"]["radius"] == "small", (ex, ex3))
_, _, d, r, ex = edit.apply(b, "soft-ui-evolution", P("标题改成 全城最好喝的咖啡")[0])
expect("改文字：用户自己的话照用，但用了极限词会提醒", ex["copy"]["hero"]["heading"] == "全城最好喝的咖啡" and "广告法" in d[0], d)
_, _, d, r, ex = edit.apply(b, "soft-ui-evolution", [{"op": "copy", "section": "hero", "field": "heading", "value": "很" * 31}])
expect("改文字：太长的不改，说明上限", not ex["copy"] and "最多 30 字" in r[0], r)
expect("改文字、字号这类只属于这个网站，不给“教给它”的建议", edit.teach(b, P("字大一点")[0], ["字号调大（×1.12）"]) == [])

from make_site import build_one  # noqa: E402
_, _, _, _, ex = edit.apply(b, "soft-ui-evolution", P("字大一点，字大一点，改成直角，紧凑一点")[0] + P("标题改成 下班后，来巷口喝一杯")[0])
r = build_one(b, "soft-ui-evolution", tempfile.mkdtemp(), run_browser=True, copy_overlay=ex["copy"], tweaks=ex["tweaks"])
css = open(os.path.join(r["site"], "styles.css"), encoding="utf-8").read()
html = open(os.path.join(r["site"], "index.html"), encoding="utf-8").read()
expect("生成：字号×1.25、直角、紧凑都写进样式最后一层，标题换成用户的话，浏览器检查 0 问题",
       "font-size:20.0px" in css and "border-radius:0px" in css and "padding-top:24px" in css and "下班后，来巷口喝一杯" in html
       and not r["browser_problems"] and not r["blueprint_errors"], (r["browser_problems"][:2], r["blueprint_errors"][:2]))
expect("一次加两个", P("加上地图和动态")[0] == [{"op": "add_feature", "kind": "map"}, {"op": "add_feature", "kind": "blog"}])

b = understand("帮我做个咖啡馆的网站，可以预约")
nb, st, done, refused, _ = edit.apply(b, "soft-ui-evolution", P("加一个相册，加个在线支付，按钮换成绿色，换成复古风格")[0])
expect("应用：加相册、换色、换风格都生效", any(f["kind"] == "gallery" for f in nb["features"]) and nb["brand"]["colors"][0] == "#2E7D32"
       and st == "vintage-analog-retro-film", (done, st))
expect("应用：做不出来的功能不假装加上，说明原因", any("在线支付" in r and "做不出来" in r for r in refused)
       and not any(f["kind"] == "payment" for f in nb["features"]), refused)
expect("应用：不改动原来的简报（撤销靠它）", not any(f["kind"] == "gallery" for f in b["features"]))
nb2, _, done2, _, _ = edit.apply(b, "soft-ui-evolution", P("去掉预约")[0])
expect("应用：去掉预约时，相应的目标也去掉，编号重排", not any(f["kind"] == "booking" for f in nb2["features"])
       and not any(g["kind"] == "booking" for g in nb2["goals"]) and nb2["goals"][0]["id"] == "G1", nb2["goals"])
expect("教给它：去功能、换风格 → 行业层面的建议句", edit.teach(nb2, P("去掉预约，换成复古风格")[0],
                                                     ["去掉了预约", "风格换成复古（vintage-analog-retro-film）"]) ==
       ["咖啡馆不要预约", "咖啡馆要用复古风格"])
expect("教给它：换颜色、改名字是这一个网站的事，不给建议", edit.teach(nb, P("按钮换成绿色，名字改成 X")[0], ["主色改成绿色"]) == [])
fb = understand("开个网店卖手工皂")
_, _, _, ref, _ = edit.apply(fb, "soft-ui-evolution", P("去掉商品")[0])
expect("应用：目标必需的页面不删，说明原因", ref and "必需" in ref[0], ref)

print(f"\n对话式修改：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
