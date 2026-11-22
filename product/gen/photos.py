"""用户自己的照片：校验、去掉隐私信息、压缩成网页用的尺寸。

照片来自用户电脑，可能有问题，所以每一步都设上限：
  * 只收 JPEG / PNG / WebP（看文件开头的“魔数”，不信扩展名）；SVG、HTML、GIF 一律不收——
    SVG 和 HTML 里可以藏脚本；
  * 文件最大 15MB，像素最多 4000 万（防“解压炸弹”：几 KB 的文件解开要几十 GB 内存）；
  * 用 Pillow 重新解码再编码：原文件里的 EXIF（拍摄地点 GPS、手机型号、拍摄时间）、
    附加在文件末尾的其它数据全部丢掉，只留像素和色彩配置；手机竖拍的方向先摆正；
  * 输出 WebP 两个宽度（1600、800，不放大），网页用 srcset 按屏幕挑。
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import warnings

MAX_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 40_000_000
MIN_SIDE = 200
WIDTHS = (1600, 800)
ALT_MAX = 120


class PhotoError(ValueError):
    """给用户看的错误，说清楚哪里不行、怎么办。"""


def sniff(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return ""


def clean_alt(text: str) -> str:
    """图片说明：去掉控制字符和尖括号，限长。"""
    t = re.sub(r"[\x00-\x1f\x7f<>]", "", str(text or "")).strip()
    return t[:ALT_MAX]


def ingest(data: bytes, out_dir: str) -> dict:
    """处理一张照片，写进 out_dir，返回 {"base", "w", "h", "widths", "sha"}。不合格抛 PhotoError。"""
    try:
        from PIL import Image, ImageOps
    except ImportError as e:  # requirements.txt 里有；没装时给出明确提示
        raise PhotoError("处理照片需要 Pillow：请运行 start.sh --setup（或 pip install Pillow）") from e
    if not data:
        raise PhotoError("没有收到照片内容")
    if len(data) > MAX_BYTES:
        raise PhotoError(f"照片太大（{len(data) / 1048576:.1f}MB），最大 15MB。可以先用手机或电脑压缩一下")
    fmt = sniff(data)
    if not fmt:
        raise PhotoError("只支持 JPG、PNG、WebP 格式的照片（SVG、GIF、HEIC 等请先另存为 JPG）")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)  # 超过上限的警告也当错误
            probe = Image.open(io.BytesIO(data), formats=[fmt])
            if probe.width * probe.height > MAX_PIXELS:
                raise PhotoError("照片像素太多（超过 4000 万），请缩小后再传")
            probe.verify()  # 检查文件结构是否完整
            im = Image.open(io.BytesIO(data), formats=[fmt])
            im.seek(0)  # 动图只取第一帧
            im.load()
    except PhotoError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise PhotoError("照片像素太多（超过 4000 万），请缩小后再传")
    except Exception as e:  # 损坏、截断、伪装成图片的文件
        raise PhotoError("这个文件打不开，可能已损坏或不是真正的照片") from e
    im = ImageOps.exif_transpose(im)  # 按拍摄方向摆正（之后 EXIF 不再保留）
    if min(im.size) < MIN_SIDE:
        raise PhotoError(f"照片太小（{im.width}×{im.height}），至少要 {MIN_SIDE} 像素宽高，放到网页上会糊")
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    im = im.convert("RGBA" if has_alpha else "RGB")
    icc = im.info.get("icc_profile")
    sha = hashlib.sha256(data).hexdigest()[:16]
    base = f"p-{sha}"
    os.makedirs(out_dir, exist_ok=True)
    widths = []
    for w in WIDTHS:
        if w > im.width and widths:  # 不放大；最小的那档总要有一份
            continue
        tw = min(w, im.width)
        th = round(im.height * tw / im.width)
        small = im.resize((tw, th), Image.LANCZOS) if tw != im.width else im
        kw = {"quality": 80, "method": 4}
        if icc:
            kw["icc_profile"] = icc
        small.save(os.path.join(out_dir, f"{base}-{tw}.webp"), "WEBP", **kw)  # 不传 exif：拍摄信息不进网站
        widths.append(tw)
    widths = sorted(set(widths))
    big = widths[-1]  # 网页上 width/height 属性按最大那份写（防止加载时页面跳动）
    return {"base": base, "w": big, "h": round(im.height * big / im.width), "widths": widths, "sha": sha}
