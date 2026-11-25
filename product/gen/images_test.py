"""图片：示意插图、用户照片处理、生成器接入、体检和浏览器检查。

    python3 -I images_test.py          # 含真实浏览器检查（没装 Chrome 会跳过那几项并说明）
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (HERE, os.path.join(HERE, "..", "text2site")):
    sys.path.insert(0, p)
import art  # noqa: E402
import photos  # noqa: E402
from PIL import Image  # noqa: E402

ok, bad = [], []


def expect(name, cond, detail=""):
    (ok if cond else bad).append(name)
    print(("通过  " if cond else "失败  ") + name + ("" if cond else f"  ← {str(detail)[:300]}"))


def jpeg(w, h, color=(180, 120, 60), exif=None, quality=90):
    b = io.BytesIO()
    kw = {"quality": quality}
    if exif is not None:
        kw["exif"] = exif
    Image.new("RGB", (w, h), color).save(b, "JPEG", **kw)
    return b.getvalue()


# ---------- 示意插图
SAFE_TAGS = {"svg", "defs", "rect", "circle", "ellipse", "path", "g", "filter", "feGaussianBlur", "linearGradient",
             "radialGradient", "stop", "pattern", "text", "mask"}
cols = {"primary": "#92400E", "secondary": "#B45309", "accent": "#F59E0B", "background": "#FEF3C7", "foreground": "#78350F",
        "card": "#FFFFFF", "border": "#FDE68A", "band": "#FDE7B0", "band-2": "#FEF3C7"}
motifs = [m for m, _ in art.MOTIF_WORDS] + ["spark"]
fams = ["block", "soft", "minimal", "glass", "dark", "editorial", "tech"]
probs = []
for f in fams:
    for m in motifs:
        svg = art.draw(cols, f, m, f"home/hero/{m}", 800, 600)
        try:
            root = ET.fromstring(svg)
            tags = {el.tag.split("}")[-1] for el in root.iter()}
            if not tags <= SAFE_TAGS - {"text"}:
                probs.append((f, m, tags - SAFE_TAGS))
        except ET.ParseError as e:
            probs.append((f, m, str(e)))
        low = svg.lower()
        if any(x in low for x in ("<script", "href", "url(http", "javascript:", "onload", "<image", "<foreignobject")):
            probs.append((f, m, "外部引用或脚本"))
expect(f"插图：7 种风格 × {len(motifs)} 种图案都是合法 SVG，只有图形元素，没有脚本、外链、文字", not probs, probs[:3])
expect("插图：同一个位置每次画得一样，不同位置不一样",
       art.draw(cols, "soft", "cup", "a/b/c") == art.draw(cols, "soft", "cup", "a/b/c") != art.draw(cols, "soft", "cup", "a/b/d"))
expect("插图：一组卡片轮换三种相近图案，不会九张全一样",
       len({art.motif_at("cup", i) for i in range(9)}) == 3 and art.motif_at("cup", None) == "cup")
expect("插图：行业对上图案（咖啡馆→杯子、牙科→牙齿、看不懂的→闪光）",
       art.motif_for("Bakery/Cafe") == "cup" and art.motif_for("Dental Practice") == "tooth" and art.motif_for("???") == "spark"
       and art.motif_for("Veterinary Clinic") == "paw")
sys.path.insert(0, os.path.join(HERE, "..", "text2site"))
import lexicon  # noqa: E402
generic = [pt for pt in lexicon.PRODUCT if art.motif_for(pt) == "spark"]
expect("插图：知识库里的行业大多有专门图案（用通用闪光的不超过 3 个）", len(generic) <= 3, generic)
weird = art.colors_from_tokens({"color": {"primary": {"$value": "{color.primary}"}, "accent": {"$value": {"hex": "red;}<x>"}},
                                          "background": {"$value": {"hex": "#0e1116"}}}})
expect("插图：颜色只认 #RRGGBB；循环引用、乱写的颜色都用安全的默认值",
       weird["primary"] == "#2F5BD3" and weird["accent"] == "#F59E0B" and weird["background"] == "#0E1116")
fav = art.favicon(cols, "<")
expect("网站图标：品牌首字是特殊字符时不原样放进 SVG", "<text" in fav and "><<" not in fav and "&" not in fav
       and ET.fromstring(fav) is not None and art.favicon(cols, "巷").count("巷") == 1)

# ---------- 用户照片
tmp = tempfile.mkdtemp(prefix="img-")
GPS_MARK = b"ZZGPSHOMEZZ"
ex = Image.Exif()
ex[0x010F] = "PhoneMakerZZ"           # 手机厂商
ex[0x0132] = "2026:11:20 10:00:00"    # 拍摄时间
ex[0x9286] = GPS_MARK.decode()        # 用户备注里藏一段，代表各种元数据
ex[0x8825] = {1: "N", 2: (1.0, 17.0, 0.0), 3: "E", 4: (103.0, 51.0, 0.0)}  # GPS
raw = jpeg(1200, 900, exif=ex.tobytes())
expect("照片样本：原图确实带着拍摄地点和手机信息", GPS_MARK in raw and b"PhoneMakerZZ" in raw)
meta = photos.ingest(raw, os.path.join(tmp, "p"))
files = [os.path.join(tmp, "p", f'{meta["base"]}-{w}.webp') for w in meta["widths"]]
blob = b"".join(open(f, "rb").read() for f in files)
outs = [Image.open(f) for f in files]
expect("照片：处理后拍摄地点、手机型号、拍摄时间全部去掉（文件里找不到，图片也读不出 EXIF）",
       GPS_MARK not in blob and b"PhoneMakerZZ" not in blob and b"2026:11:20" not in blob
       and all(not o.getexif() and "exif" not in o.info for o in outs), [o.info.keys() for o in outs])
expect("照片：1200 宽的图出 800 和 1200 两份 WebP，不放大", meta["widths"] == [800, 1200] and all(o.format == "WEBP" for o in outs)
       and meta["w"] == 1200 and meta["h"] == 900, meta)
m3 = photos.ingest(jpeg(3000, 2000), os.path.join(tmp, "p"))
m5 = photos.ingest(jpeg(500, 400), os.path.join(tmp, "p"))
expect("照片：大图压到 1600 和 800；小图只留原尺寸一份", m3["widths"] == [800, 1600] and m3["h"] == 1067 and m5["widths"] == [500], (m3, m5))
exo = Image.Exif()
exo[0x0112] = 6  # 手机竖着拍：需要顺时针转 90 度
mo = photos.ingest(jpeg(400, 300, exif=exo.tobytes()), os.path.join(tmp, "p"))
expect("照片：手机竖拍的按方向摆正（400×300 + 方向 6 → 300×400）", (mo["w"], mo["h"]) == (300, 400), mo)
poly = jpeg(600, 400) + b"<script>alert(1)</script><svg onload=alert(2)>"
mp = photos.ingest(poly, os.path.join(tmp, "p"))
pb = b"".join(open(os.path.join(tmp, "p", f'{mp["base"]}-{w}.webp'), "rb").read() for w in mp["widths"])
expect("照片：图片后面夹带的脚本不会跟进网站（重新编码只留像素）", b"<script" not in pb and b"onload" not in pb)


def refused(data, word):
    try:
        photos.ingest(data, os.path.join(tmp, "x"))
        return False, "没拒绝"
    except photos.PhotoError as e:
        return word in str(e), str(e)


big_png = io.BytesIO()
Image.new("1", (8000, 6000)).save(big_png, "PNG")  # 4800 万像素，文件却很小：“解压炸弹”
cases = [("SVG（可能藏脚本）", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "只支持"),
         ("HTML 改名成 .jpg", b"<!doctype html><script>alert(1)</script>", "只支持"),
         ("GIF", b"GIF89a" + b"\x00" * 100, "只支持"),
         ("空文件", b"", "没有收到"),
         ("超过 15MB", b"\xff\xd8\xff" + b"\x00" * (15 * 1024 * 1024 + 10), "太大"),
         ("太小（100×100）", jpeg(100, 100), "太小"),
         ("截断的 JPEG", jpeg(800, 600)[:400], "打不开"),
         ("解压炸弹（4800 万像素）", big_png.getvalue(), "像素太多")]
res = {n: refused(d, w) for n, d, w in cases}
expect("照片：SVG、HTML、GIF、空文件、超大、太小、损坏、解压炸弹都拒绝，并说清原因",
       all(v[0] for v in res.values()), {k: v[1] for k, v in res.items() if not v[0]})
expect("照片说明：去掉尖括号和控制字符，最长 120 字",
       photos.clean_alt('<b>店\x00门"口</b>') == 'b店门"口/b' and len(photos.clean_alt("长" * 500)) == 120)

# ---------- 生成器接入
import make_site  # noqa: E402
import understand  # noqa: E402
import styles  # noqa: E402
import generate  # noqa: E402
import site_audit  # noqa: E402
import browser_check  # noqa: E402
import re  # noqa: E402

brief = understand.understand("巷口咖啡，社区里的小咖啡馆，想让附近的人来店里坐坐，可以在线订座，也想展示菜单和店里的环境")
sid = styles.options(brief)[1]["id"]
out = tempfile.mkdtemp(prefix="imgsite-")
r = make_site.build_one(brief, sid, os.path.join(out, "a"), run_browser=False)
site = r["site"]
html_all = {p: open(os.path.join(site, p), encoding="utf-8").read() for p in r["pages"]}
imgs = [(p, m) for p, h in html_all.items() for m in re.findall(r"<img\b[^>]*>", h)]
slots = generate.image_slots(r["project"])
arts_in_html = sorted({re.search(r'data-art="([^"]+)"', m).group(1) for _, m in imgs if "data-art" in m})
expect("生成：首页首屏、关于页、作品页的每张卡片都有图（没有灰色占位框了）",
       len(imgs) >= 11 and 'class="ph"' not in "".join(html_all.values()), len(imgs))
expect("生成：放图位置清单和网页里的图一一对应", sorted(x["key"] for x in slots) == arts_in_html, (len(slots), len(arts_in_html)))
expect("生成：每张图都写了宽高；插图 alt 为空并标为装饰；首屏图优先加载，其余懒加载",
       all(re.search(r'\swidth="\d+"', m) and re.search(r'\sheight="\d+"', m) and 'alt=""' in m for _, m in imgs)
       and all(('fetchpriority="high"' in m) == ("/hero/" in m) for _, m in imgs)
       and all('loading="lazy"' in m for _, m in imgs if "/hero/" not in m), imgs[:2])
expect("生成：插图文件、网站小图标都写出来了，不依赖外部网址",
       all(os.path.exists(os.path.join(site, "assets", "art", generate.art_name(k))) for k in arts_in_html)
       and os.path.exists(os.path.join(site, "assets", "favicon.svg")) and 'href="data:,"' not in html_all["index.html"]
       and not re.search(r'src="(https?:)?//', "".join(html_all.values())))
# 换上照片
pdir = os.path.join(out, "photos")
hero_key = next(x["key"] for x in slots if x["key"].startswith("home/hero/"))
card_key = next(x["key"] for x in slots if x["key"].endswith("/2"))
mh = dict(photos.ingest(jpeg(2400, 1600, (40, 90, 160)), pdir), alt='店门口"招牌" <夜景>')
mc = dict(photos.ingest(jpeg(900, 900, (200, 60, 60)), pdir), alt="拿铁")
bogus = {"base": "../../etc/passwd", "w": 10, "h": 10, "widths": [10], "alt": "x"}
missing = {"base": "p-0123456789abcdef", "w": 800, "h": 600, "widths": [800], "alt": "不存在的文件"}
r2 = make_site.build_one(brief, sid, os.path.join(out, "b"), run_browser=False,
                         photos={"dir": pdir, "map": {hero_key: mh, card_key: mc, "about/story/photo": bogus, "work/grid/items/5": missing}})
home = open(os.path.join(r2["site"], "index.html"), encoding="utf-8").read()
hero_img = re.search(r"<img\b[^>]*fetchpriority[^>]*>", home).group(0)
expect("照片：首屏换成照片，带 800/1600 两档 srcset、真实宽高和你写的说明（引号尖括号已转义）",
       ".webp" in hero_img and "800w" in hero_img and "1600w" in hero_img and 'width="1600" height="1067"' in hero_img
       and 'alt="店门口&quot;招牌&quot; &lt;夜景&gt;"' in hero_img, hero_img)
work = open(os.path.join(r2["site"], "work", "index.html"), encoding="utf-8").read()
about = open(os.path.join(r2["site"], "about", "index.html"), encoding="utf-8").read()
expect("照片：用到的照片拷进网站；乱写的文件名、找不到的文件不用，那个位置退回插图",
       sorted(os.listdir(os.path.join(r2["site"], "assets", "photos"))) == sorted(f'{m["base"]}-{w}.webp' for m in (mh, mc) for w in m["widths"])
       and "passwd" not in about and 'data-art="about/story/photo"' in about and 'data-art="work/grid/items/5"' in work
       and 'alt="拿铁"' in work)

# ---------- 体检
a = site_audit.audit(r2["site"])
it = {x["msg"]: x for x in a["items"]}
art_item = next(x for x in a["items"] if "示意插图" in x["msg"])
expect("体检：提醒还有几处示意插图（列为上线前再做，不扣分）", art_item["pending"] and not art_item["ok"] and re.search(r"\d+ 处", art_item["msg"]))
expect("体检：照片压缩过，图片体积这项通过；懒加载的图不算进“一打开就要发的请求”",
       any(x["ok"] and "图片都压缩过" in x["msg"] for x in a["items"]) and a["scores"]["性能"] == 100, [x["msg"] for x in a["items"] if x["cat"] == "性能"])
heavy = tempfile.mkdtemp(prefix="heavy-")
shutil.copytree(r2["site"], heavy, dirs_exist_ok=True)
with open(os.path.join(heavy, "assets", "photos", f'{mh["base"]}-1600.webp'), "ab") as f:
    f.write(b"\0" * 500_000)
ah = site_audit.audit(heavy)
expect("体检：直接塞进来的大图（超过 400 KB）会被指出来", any((not x["ok"]) and "图片太大" in x["msg"] for x in ah["items"]))

# ---------- 浏览器检查
ready, why = browser_check.ready()
if ready:
    clean = browser_check.check(r2["site"])
    expect("浏览器：换了照片的网站没有问题（替代文字、图片能打开、宽高都对）", not clean, clean[:3])
    broken = tempfile.mkdtemp(prefix="broken-")
    shutil.copytree(r2["site"], broken, dirs_exist_ok=True)
    os.remove(os.path.join(broken, "assets", "art", generate.art_name("about/story/photo")))
    p = os.path.join(broken, "about", "index.html")
    h = open(p, encoding="utf-8").read()
    h = re.sub(r'(<img\b[^>]*?) width="\d+"', r"\1", h, count=1)
    h = h.replace('alt=""', "", 1)
    open(p, "w", encoding="utf-8").write(h)
    probs = browser_check.check(broken)
    expect("浏览器：图片打不开、没写宽高、没有 alt 属性都能查出来",
           any("图片打不开" in x for x in probs) and any("没写宽高" in x for x in probs) and any("图片缺替代文字" in x for x in probs), probs)
else:
    print("跳过浏览器两项：" + why)

print(f"\n图片：{len(ok)}/{len(ok) + len(bad)} 通过")
sys.exit(1 if bad else 0)
