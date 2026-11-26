#!/usr/bin/env python3
"""AI 建站工作台 · 原型服务器（只用标准库）。

流程：输入一句话 → 看系统读懂了什么、回答问题 → 三种风格的首页并排预览、点选一个 → 生成整站并检查 → 浏览整站。
每次选择都记进学习大脑（runs/choices.jsonl），同行业用户最常选的风格以后会排在前面。
喂养：/api/feed 接收一段话或网页源码，抽取、试跑、采纳（feed.py）；/api/knowledge 查看学到的；/api/undo 撤回。
自我纠错：选定风格后用 autofix.run 生成 —— 检查出问题自己修（封闭修补清单 + 刹车），修好的记成预防，后台验证能否推广。

安全：
  * 只监听 127.0.0.1；请求体不超过 16 KB；一句话不超过 500 字；所有输入都校验。
  * 静态文件只从本会话的输出目录里取，路径解析后必须仍在该目录内（防 ../ 越权）。
  * 风格只能从本会话给出的候选里选；会话 ID 只接受服务器生成的格式。
用法：python3 -I server.py [端口] [工作目录]
"""
from __future__ import annotations

import http.server
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import time
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "..", "text2site"), os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "gen")):
    sys.path.insert(0, p)
import autofix  # noqa: E402
sys.path.insert(0, os.path.join(HERE, "..", "models"))
import client as model_client  # noqa: E402
import config as model_config  # noqa: E402
import llm_copy  # noqa: E402
import site_audit  # noqa: E402
import llm_understand  # noqa: E402
import generate as gen_site  # noqa: E402
import photos as photo_lib  # noqa: E402
from plan import plan as _plan  # noqa: E402
import edit  # noqa: E402
import events  # noqa: E402
import live  # noqa: E402
import feed  # noqa: E402
import learned  # noqa: E402
import prefs  # noqa: E402
import styles  # noqa: E402
from make_site import build_one, summary  # noqa: E402
from understand import apply_answers, understand  # noqa: E402

MAX_BODY = 16 * 1024
MAX_FEED_BODY = 600 * 1024  # 喂网页源码用；只有 /api/feed 允许这么大
MAX_IMAGE_BODY = 21 * 1024 * 1024  # 上传照片（base64 后约 15MB 原图）；只有 /api/image/upload 允许这么大
KID = re.compile(r"\bK\d{3}\b")
MAX_TEXT = 500
SID = re.compile(r"^[0-9a-f]{12}$")
LOCK = threading.Lock()  # 生成和检查串行做，避免同时开很多个浏览器


class App:
    def __init__(self, work: str, choices_path: str | None = None, knowledge: str | None = None):
        self.work = os.path.abspath(work)
        os.makedirs(self.work, exist_ok=True)
        self.choices = choices_path or prefs.DEFAULT_PATH
        if knowledge:
            os.environ["AISITE_KNOWLEDGE"] = os.path.abspath(knowledge)
        self.generalizing = set()

    # ---------- 会话 ----------
    def _dir(self, sid):
        if not SID.match(sid or ""):
            raise ValueError("会话编号不对")
        d = os.path.join(self.work, sid)
        if not os.path.isdir(d):
            raise ValueError("会话不存在")
        return d

    def _load(self, sid):
        with open(os.path.join(self._dir(sid), "session.json"), encoding="utf-8") as f:
            return json.load(f)

    def _save(self, s):
        with open(os.path.join(self.work, s["sid"], "session.json"), "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False)

    def _used(self, s):
        """这份需求用到了哪些喂养学到的知识（理解里和风格推荐里引用的 K 编号）。"""
        ids = set(KID.findall(json.dumps([s["brief"], s["options"]], ensure_ascii=False)))
        return [{"id": k["id"], "what": feed.describe(k)} for k in learned.items() if k["id"] in ids]

    def _view(self, s):
        b = s["brief"]
        return {"session": s["sid"], "understood": summary(b), "used_learning": self._used(s),
                "understood_by": s.get("understood_by", {"how": "rules"}),
                "questions": [{"id": q["id"], "question": q["question"], "default": q["default_if_unanswered"],
                               "answer": q.get("answer", "")} for q in b["open_questions"]],
                "options": s["options"], "chosen": s.get("chosen")}

    def _options(self, brief):
        return styles.options(brief, learned=prefs.favourite(brief["product_type"]["value"], self.choices))

    # ---------- 接口 ----------
    def start(self, body):
        text = str(body.get("text", "")).strip()
        if not text or len(text) > MAX_TEXT:
            raise ValueError(f"请用 1 到 {MAX_TEXT} 个字描述你想要的网站")
        sid = secrets.token_hex(6)
        os.makedirs(os.path.join(self.work, sid))
        s = {"sid": sid, "text": text, "model_calls": 0}
        with events.run("understand"), events.stage("understand", 字数=len(text)) as st:  # 只记字数，不记原话
            b, rep = llm_understand.understand_with_model(text, self._conn("understand", s), self._budget(s))
            st.out(行业=b.get("product_type", {}).get("value", ""), questions=len(b.get("open_questions", []) or []),
                   by=str((rep or {}).get("how", "rules")) if isinstance(rep, dict) else "rules")
        b["id"] = "site-" + sid
        s.update(brief=b, options=self._options(b), understood_by=rep)
        self._save(s)
        return self._view(s)

    def answer(self, body):
        s = self._load(body.get("session"))
        answers = {str(k): str(v)[:60] for k, v in (body.get("answers") or {}).items()}
        s["brief"] = apply_answers(s["text"], s["brief"], answers)
        s["options"] = self._options(s["brief"])
        s.pop("previews", None)
        self._save(s)
        return self._view(s)

    def _slot(self, s, style):
        """每次生成都放进新的版本目录，不在原地删了重建：页面上正在加载的旧预览不会因此 404（D15）。"""
        s["rev"] = s.get("rev", 0) + 1
        name = f"{style}--{s['rev']}"
        return name, os.path.join(self.work, s["sid"], name)

    def preview(self, body):
        s = self._load(body.get("session"))
        out = []
        with LOCK, events.run("preview", 行业=s["brief"]["product_type"]["value"], 风格数=len(s["options"])):
            for o in s["options"]:
                name, d = self._slot(s, o["id"])
                pre = [x["fix"] for x in autofix.prevent(s["brief"], o["id"])]  # 预览也用上以前的教训
                r = build_one(s["brief"], o["id"], d, run_browser=False, fixes=pre,  # 预览只要快；选定后再做浏览器检查
                              copy_overlay=self._copy(s, s["brief"], o["id"]))
                out.append({"style": o["id"], "url": f"/s/{s['sid']}/{name}/", "blueprint_errors": len(r["blueprint_errors"])})
        s["previews"] = out
        self._save(s)
        return {"session": s["sid"], "previews": out, "copy_by": s.get("copy_by", {"how": "rules"})}

    def choose(self, body):
        s = self._load(body.get("session"))
        style = str(body.get("style", ""))
        if style not in [o["id"] for o in s["options"]]:
            raise ValueError("只能从给出的三种风格里选")
        out, r = self._build(s, s["brief"], style)
        s["chosen"] = style
        out["version"] = 1  # 给用户看的版本号：第几次成型的网站（预览不算）
        s["history"] = [{"brief": s["brief"], "style": style, "result": out}]
        self._save(s)
        rec = prefs.record(s["brief"]["product_type"]["value"], [o["id"] for o in s["options"]], style, s["text"], self.choices)
        fam = next((o["family"] for o in s["options"] if o["id"] == style), style)
        out["learned"] = f"已记录你的选择：{styles._zh_type(rec['product_type'])}这类网站选了“{fam}”。以后同行业的推荐会参考。"
        return out

    def _build(self, s, brief, style, extras=None):
        """生成一个版本（带自我纠错），返回 (给界面的结果, 构建结果)。extras：对话修改里用户自己写的文字、字号圆角间距。"""
        extras = extras or {}
        with LOCK, events.run("site", 行业=brief["product_type"]["value"], 风格=style):
            name, d = self._slot(s, style)
            overlay = json.loads(json.dumps(self._copy(s, brief, style) or {}))
            for sec, fields in (extras.get("copy") or {}).items():  # 用户亲手写的文字最优先
                overlay.setdefault(sec, {}).update(fields)
            pics = {"dir": os.path.join(self.work, s["sid"], "photos"), "map": extras.get("images") or {}}
            r = autofix.run(brief, style, os.path.join(d, "rounds"), run_browser=True,  # 检查出问题会自己修，有刹车
                            copy_overlay=overlay or None, tweaks=extras.get("tweaks") or None, photos=pics if pics["map"] else None)
            with events.stage("deliver") as st:
                for part in ("project", "site"):  # 最终版本放到固定位置，静态路由只认这一个
                    shutil.move(r[part], os.path.join(d, part))
                    r[part] = os.path.join(d, part)
                st.out(problems=len(r["blueprint_errors"] + r["browser_problems"]), version=s["rev"])
        rep = r["selffix"]
        if any(x["scope"] == "narrow" for x in rep["learned"]):
            self._generalize_later()
        site = json.load(open(os.path.join(r["project"], "site.json"), encoding="utf-8"))
        tmp = dict(s, brief=brief)
        return {"session": s["sid"], "style": style, "version": s["rev"], "url": f"/s/{s['sid']}/{name}/",
                "pages": [{"title": p["title"], "url": f"/s/{s['sid']}/{name}" + (p["path"] if p["path"] == "/" else p["path"] + "/")}
                          for p in site["pages"]],
                "blueprint_errors": r["blueprint_errors"], "browser_problems": r["browser_problems"],
                "not_yet": r["notes"].get("not_yet", []), "learned": "", "browser_skipped": r["notes"].get("browser_skipped", ""),
                "selffix": {"prevented": [p["why"] for p in rep["prevented"]],
                            "fixed": [f"{x['zh']} → {x['how']}" for x in rep["fixed"]],
                            "reverted": rep["reverted"], "unfixed": rep["unfixed"], "stop": rep["stop"],
                            "rounds": len(rep["rounds"]),
                            "remembered": [f"{x['id']}：{x['what']}" + ("（先只用于同行业同风格，验证后再推广）" if x["scope"] == "narrow" else "")
                                           for x in rep["learned"]]},
                "used_learning": self._used(tmp), "copy_by": s.get("copy_by", {"how": "rules"}),
                "audit": self._audit(r)}, r

    @staticmethod
    def _audit(r):
        """上线前体检；再加一条：哪些区块因为没有真实内容先不显示（生成器记在 hidden.json）。"""
        a = site_audit.audit(r["site"], r["browser_problems"])
        hf = os.path.join(r["project"], "hidden.json")
        hid = json.load(open(hf, encoding="utf-8")) if os.path.exists(hf) else []
        if hid:
            labels = "、".join(dict.fromkeys(h["label"] for h in hid))
            a["items"].append({"cat": "合规", "ok": False, "pending": True,
                               "msg": f"有 {len(hid)} 个区块先不显示，等你的真实内容：{labels}",
                               "fix": "这些内容系统不能替你编；有了真实的评价、数字、团队介绍再加上，空着不如不放"})
        return a

    # ---------- 对话式修改 ----------
    def edit(self, body):
        s = self._load(body.get("session"))
        text = str(body.get("text", "")).strip()[:MAX_TEXT]
        if not s.get("history"):
            raise ValueError("先选一个风格生成网站，再来改")
        if not text:
            raise ValueError("说说想怎么改。" + edit.HELP)
        ops, unknown = edit.parse(text)
        cur = s["history"][-1]
        if unknown:
            self._backlog(unknown)
        if any(o["op"] == "undo" for o in ops):
            if len(s["history"]) < 2:
                return dict(cur["result"], edit={"done": [], "refused": ["已经是第一版了，没有可以撤销的"], "unknown": unknown, "kept": True})
            s["history"].pop()
            prev = s["history"][-1]
            s["brief"], s["chosen"] = prev["brief"], prev["style"]  # 附加设置跟着版本走（history 里的 extras）
            self._save(s)
            return dict(prev["result"], edit={"done": ["回到了上一版"], "refused": [], "unknown": unknown, "kept": False}, teach=[])
        nb, style, done, refused, extras = edit.apply(cur["brief"], cur["style"], ops, cur.get("extras"))
        if not done:
            msg = [] if ops else ["没看懂要改什么。" + edit.HELP]
            return dict(cur["result"], edit={"done": [], "refused": refused + msg, "unknown": unknown, "kept": True}, teach=[])
        out, r = self._build(s, nb, style, extras)
        before = len(cur["result"]["blueprint_errors"]) + len(cur["result"]["browser_problems"])
        after = len(out["blueprint_errors"]) + len(out["browser_problems"])
        if after > before:  # 改完反而有问题、自我纠错也没修好：不把网站改坏，保留上一版
            self._save(s)
            return dict(cur["result"], edit={"done": [], "refused": refused + ["改完后出现了问题，自我纠错也没修好，所以保留了上一版："
                                                                                   + "；".join((out["blueprint_errors"] + out["browser_problems"])[:2])],
                                             "unknown": unknown, "kept": True}, teach=[])
        s["brief"], s["chosen"] = nb, style
        out["version"] = cur["result"]["version"] + 1
        s["history"].append({"brief": nb, "style": style, "result": out, "extras": extras})
        s["history"] = s["history"][-20:]
        self._save(s)
        return dict(out, edit={"done": done, "refused": refused, "unknown": unknown, "kept": False}, teach=edit.teach(nb, ops, done))

    # ---------- 图片 ----------
    def _cur_site(self, s):
        cur = (s.get("history") or [None])[-1]
        if not cur:
            raise ValueError("先选一个风格生成网站，再来换图片")
        m = re.match(r"^/s/([0-9a-f]{12})/([a-z0-9-]+--\d+)/$", cur["result"]["url"])
        return cur, m.group(2), os.path.join(self.work, s["sid"], m.group(2))

    def images(self, body):
        """当前版本里所有放图的位置，每个位置现在是照片还是示意插图，带缩略图地址。"""
        s = self._load(body.get("session"))
        cur, name, d = self._cur_site(s)
        mine = (cur.get("extras") or {}).get("images") or {}
        base = f"/s/{s['sid']}/{name}/assets/"
        out = []
        for x in gen_site.image_slots(os.path.join(d, "project")):
            ph = mine.get(x["key"])
            out.append(dict(x, kind="photo" if ph else "art", alt=(ph or {}).get("alt", ""),
                            thumb=base + (f'photos/{ph["base"]}-{ph["widths"][0]}.webp' if ph else "art/" + gen_site.art_name(x["key"]))))
        return {"session": s["sid"], "slots": out}

    def _with_images(self, s, change, what):
        """改图片也是出一个新版本（能撤销、能导出旧版），走和对话修改一样的保护：改完更糟就保留上一版。"""
        cur, _, d = self._cur_site(s)
        keys = {x["key"] for x in gen_site.image_slots(os.path.join(d, "project"))}
        extras = json.loads(json.dumps(cur.get("extras") or {}))
        imgs = extras.setdefault("images", {})
        change(imgs, keys)
        out, r = self._build(s, cur["brief"], cur["style"], extras)
        before = len(cur["result"]["blueprint_errors"]) + len(cur["result"]["browser_problems"])
        after = len(out["blueprint_errors"]) + len(out["browser_problems"])
        if after > before:
            self._save(s)
            return dict(cur["result"], edit={"done": [], "refused": ["换完图片后检查出了问题，所以保留了上一版："
                                                                     + "；".join((out["blueprint_errors"] + out["browser_problems"])[:2])],
                                             "unknown": [], "kept": True}, teach=[])
        out["version"] = cur["result"]["version"] + 1
        s["history"].append({"brief": cur["brief"], "style": cur["style"], "result": out, "extras": extras})
        s["history"] = s["history"][-20:]
        self._save(s)
        return dict(out, edit={"done": [what], "refused": [], "unknown": [], "kept": False}, teach=[])

    def image_upload(self, body):
        import base64
        import binascii
        s = self._load(body.get("session"))
        key = str(body.get("key", ""))
        try:
            data = base64.b64decode(str(body.get("data", "")), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("照片内容不对，请重新选择文件")
        _, _, d = self._cur_site(s)
        if key not in {x["key"] for x in gen_site.image_slots(os.path.join(d, "project"))}:
            raise ValueError("没有这个放图的位置")
        try:
            meta = photo_lib.ingest(data, os.path.join(self.work, s["sid"], "photos"))
        except photo_lib.PhotoError as e:
            raise ValueError(str(e))
        label = next(x["label"] for x in gen_site.image_slots(os.path.join(d, "project")) if x["key"] == key)
        meta["alt"] = photo_lib.clean_alt(body.get("alt")) or label.split(" · ")[0] + "的照片"

        def change(imgs, keys):
            imgs[key] = meta
        return self._with_images(s, change, f"{label} 换成了你的照片（已去掉拍摄地点等信息、压缩到网页大小）")

    def image_alt(self, body):
        s = self._load(body.get("session"))
        key, alt = str(body.get("key", "")), photo_lib.clean_alt(body.get("alt"))
        cur, _, _ = self._cur_site(s)
        if key not in ((cur.get("extras") or {}).get("images") or {}):
            raise ValueError("这个位置还没有换成照片")
        if not alt:
            raise ValueError("写一句这张照片拍的是什么（看不见图片的人靠它了解内容）")

        def change(imgs, keys):
            imgs[key] = dict(imgs[key], alt=alt)
        return self._with_images(s, change, f"照片说明改成了：{alt}")

    def image_reset(self, body):
        s = self._load(body.get("session"))
        key = str(body.get("key", ""))
        cur, _, _ = self._cur_site(s)
        if key not in ((cur.get("extras") or {}).get("images") or {}):
            raise ValueError("这个位置本来就是示意插图")

        def change(imgs, keys):
            imgs.pop(key, None)
        return self._with_images(s, change, "这个位置换回了示意插图")

    # ---------- 模型 ----------
    def _conn(self, role, s):
        """这个用途配置的模型；没配置或配置不完整返回 None（走规则版），原因记进会话。"""
        try:
            c = model_config.for_role(role)
        except ValueError as e:
            s.setdefault("model_notes", []).append(f"{role}：{e}")
            return None
        if c:
            c["timeout"] = model_config.load()["limits"].get("timeout", 60)
        return c

    def _budget(self, s):
        """一个会话最多调用模型多少次（在设置里改）；超了就退回规则版，不会越用越贵。"""
        app, limit = self, int(model_config.load()["limits"].get("max_calls_per_session", 12))

        class B:
            def take(self_inner):
                if s.get("model_calls", 0) >= limit:
                    raise model_client.ModelError("budget", f"{limit} 次")
                s["model_calls"] = s.get("model_calls", 0) + 1
        return B()

    def _copy(self, s, brief, style):
        """文案改写层：同一份需求只调用一次模型，所有风格的预览和成品共用；需求变了（如改名）才重写。"""
        key = json.dumps([brief.get("site_name"), brief["product_type"]["value"], brief["audience"]["primary"],
                          [g["kind"] for g in brief["goals"]], [f["kind"] for f in brief["features"]]], ensure_ascii=False)
        if s.get("copy_key") == key:
            return s.get("copy_overlay") or None
        conn = self._conn("copy", s)
        if not conn:
            s.update(copy_key=key, copy_overlay={}, copy_by={"how": "rules", "note": "没有为“写文案”配置模型，用规则初稿"})
            return None
        res = _plan(json.loads(json.dumps(brief)), style)
        pages = {k[len("pages/"):-len(".json")]: v for k, v in res["files"].items() if k.startswith("pages/")}
        overlay, rep = llm_copy.write_with_model(brief, res["files"]["content/zh-CN.json"], pages, conn, self._budget(s))
        s.update(copy_key=key, copy_overlay=overlay, copy_by=rep)
        return overlay or None

    def models(self, body=None):
        v = model_config.public_view()
        v["log"] = list(reversed(model_client.LOG[-10:]))
        return v

    def models_save(self, body):
        pid = str(body.get("provider", ""))
        with LOCK:
            if pid:
                model_config.set_provider(pid, key=body.get("key"), base_url=body.get("base_url"),
                                          clear_key=bool(body.get("clear_key")))
            for role, r in (body.get("roles") or {}).items():
                r = r or {}
                model_config.set_role(str(role), r.get("provider") or None, r.get("model"))
            if isinstance(body.get("limits"), dict):
                d = model_config.load()
                lim = body["limits"]
                d["limits"]["max_calls_per_session"] = max(1, min(50, int(lim.get("max_calls_per_session", 12))))
                d["limits"]["timeout"] = max(10, min(180, int(lim.get("timeout", 60))))
                model_config.save(d)
        return self.models()

    def models_test(self, body):
        """测试连接：发一句很短的话，看能不能拿到回复、多久。"""
        pid, model = str(body.get("provider", "")), str(body.get("model", "")).strip()
        conn = model_config.resolved(pid)
        if not model or not model_config.MODEL_RE.match(model):
            raise ValueError("先填模型名")
        conn.update(model=model, role="test")
        try:
            r = model_client.chat(conn, "你是连通性测试。", "只回复两个字：好的", max_tokens=20, timeout=30)
            return {"ok": True, "seconds": r["seconds"], "reply": r["text"].strip()[:40]}
        except model_client.ModelError as e:
            return {"ok": False, "error": str(e), "kind": e.kind}

    def models_quick(self, body):
        """一键接入：先用填的密钥真打一次（不先保存），通了才保存密钥并把所有用途都交给它；不通就什么都不改。"""
        pid = str(body.get("provider", ""))
        if pid not in model_config.BY_ID:
            raise ValueError("先选服务商")
        key = str(body.get("key") or "").strip()
        model = str(body.get("model") or "").strip() or model_config.BY_ID[pid].get("example_model", "")
        conn = model_config.resolved(pid)
        if key:
            if len(key) > 400 or any(c.isspace() for c in key):
                raise ValueError("密钥格式不对（不能有空格或换行，检查是不是复制多了）")
            conn["key"] = key
        if body.get("base_url"):
            conn["base_url"] = model_config.check_base_url(str(body["base_url"]))
        if model_config.BY_ID[pid].get("needs_key") and not conn.get("key"):
            raise ValueError("先粘贴密钥")
        if not model:  # 这家没有默认模型名：列出来让人选
            try:
                return {"ok": False, "need_model": True, "models": model_client.list_models(conn)[:80],
                        "error": "这家要选一个模型名：从下拉里选一个再点一次"}
            except model_client.ModelError as e:
                return {"ok": False, "error": str(e), "kind": e.kind}
        if not model_config.MODEL_RE.match(model):
            raise ValueError("模型名不对（只能有字母、数字和 . : / @ + - _）")
        conn.update(model=model, role="test")
        bases = [conn["base_url"]] + ([] if body.get("base_url") else [b for b in model_config.BY_ID[pid].get("alt_base_urls", []) if b != conn["base_url"]])
        r, used, last = None, None, None
        for b in bases:  # 同一家有国内/海外两个地址（如 Kimi Code）：密钥不对时换另一个地址再试一次
            conn["base_url"] = model_config.check_base_url(b)
            try:
                r, used = model_client.chat(conn, "你是连通性测试。", "只回复两个字：好的", max_tokens=20, timeout=30), b
                break
            except model_client.ModelError as e:
                last = e
                if e.kind != "auth":
                    break
        if r is None:
            return {"ok": False, "error": str(last), "kind": last.kind, "tried": len(bases)}
        with LOCK:
            model_config.set_provider(pid, key=key or None,
                                      base_url=body.get("base_url") or (used if used != model_config.BY_ID[pid]["base_url"] else None))
            for role in model_config.ROLES:
                model_config.set_role(role, pid, model)
        return {"ok": True, "seconds": r["seconds"], "reply": r["text"].strip()[:40], "provider": pid, "model": model,
                "roles": list(model_config.ROLES)}

    def models_list(self, body):
        conn = model_config.resolved(str(body.get("provider", "")))
        try:
            return {"ok": True, "models": model_client.list_models(conn)}
        except model_client.ModelError as e:
            return {"ok": False, "error": str(e), "kind": e.kind}

    def export(self, sid, version, domain="", icp=""):
        """导出某个版本（默认当前版本）的网站压缩包。"""
        s = self._load(sid)
        hist = s.get("history") or []
        if not hist:
            raise ValueError("还没有生成网站")
        v = int(version) if str(version).isdigit() else hist[-1]["result"]["version"]
        h = next((x for x in hist if x["result"]["version"] == v), None)
        if not h:
            raise ValueError("没有这个版本")
        m = re.match(r"^/s/([0-9a-f]{12})/([a-z0-9-]+--\d+)/$", h["result"]["url"])
        site = os.path.realpath(os.path.join(self.work, m.group(1), m.group(2), "site"))
        if not site.startswith(self.work + os.sep) or not os.path.isdir(site):
            raise ValueError("找不到这个版本的文件")
        safe = re.sub(r"[^\w\u4e00-\u9fa5-]+", "-", h["brief"].get("site_name") or "website").strip("-")[:30] or "website"
        domain, icp = check_publish(domain, icp)
        return f"{safe}-v{v}", export_zip(site, f"{safe}-v{v}", domain, icp)

    def _backlog(self, unknown):
        """看不懂的修改要求记下来（待学清单），以后据此扩充能改的范围。"""
        os.makedirs(learned.knowledge_dir(), exist_ok=True)
        with open(os.path.join(learned.knowledge_dir(), "edit_backlog.jsonl"), "a", encoding="utf-8") as f:
            for u in unknown:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "text": u[:80]}, ensure_ascii=False) + "\n")

    def _generalize_later(self):
        """新学到的纠错经验：后台做对照实验，验证能否推广到别的行业（和生成共用一把锁，不会同时开很多浏览器）。"""
        def work():
            with LOCK:
                for e in autofix.generalize():
                    self.generalizing.discard(e["id"])
        self.generalizing |= {e["id"] for e in autofix._load()["entries"] if e["status"] == "active" and e["scope"] == "narrow"}
        threading.Thread(target=work, daemon=True).start()

    # ---------- 喂养 ----------
    def feed(self, body):
        text = str(body.get("text", ""))[:feed.MAX_TEXT]
        doc = body.get("html")
        if doc is not None and (not isinstance(doc, str) or len(doc) > feed.MAX_HTML):
            raise ValueError("网页源码必须是文字，且不超过 512 KB")
        if not text.strip() and not doc:
            raise ValueError("请喂一段话（例如“猫咖是咖啡馆”“律所别用深色”），或一个网页源码")
        for_type = str(body.get("for", ""))[:20] or None
        with LOCK:
            return feed.add(text, doc, for_type, source="workbench")

    def knowledge(self, body=None):
        m = autofix._load()
        return {"learned": feed.listing(all_=True),
                "fix_memory": [{"id": e["id"], "what": f"{autofix.CAUSE_ZH[e['cause']]} → {autofix.FIX_CSS[e['fix']][0]}",
                                "scope": "验证中" if e["id"] in self.generalizing else
                                ("所有带这个病因的网站" if e["scope"] == "general" else f"仅 {e['product_type']} × {e['family']}"),
                                "wins": e["wins"], "prevented": e.get("prevented", 0), "misses": e["misses"], "status": e["status"]}
                               for e in m["entries"]],
                "unfixed": m["unfixed"], "suggestions": autofix.suggestions(), "edit_backlog": self._backlog_summary()}

    def _backlog_summary(self):
        p = os.path.join(learned.knowledge_dir(), "edit_backlog.jsonl")
        if not os.path.exists(p):
            return []
        count = {}
        for line in open(p, encoding="utf-8"):
            t = json.loads(line)["text"]
            count[t] = count.get(t, 0) + 1
        return [{"text": t, "count": n} for t, n in sorted(count.items(), key=lambda kv: -kv[1])[:10]]

    def undo(self, body):
        kid = str(body.get("id", ""))
        if not KID.fullmatch(kid):
            raise ValueError("知识编号不对")
        with LOCK:
            if not feed.undo(kid):
                raise ValueError("没有这条有效的知识")
        return self.knowledge()

    # ---------- 静态文件 ----------
    def static(self, path):
        m = re.match(r"^/s/([0-9a-f]{12})/([a-z0-9-]+--\d+)(/.*)?$", path)
        if not m:
            return None
        sid, style, rest = m.group(1), m.group(2), unquote(m.group(3) or "/")
        root = os.path.realpath(os.path.join(self.work, sid, style, "site"))
        f = os.path.realpath(os.path.join(root, rest.lstrip("/")))
        if not (f == root or f.startswith(root + os.sep)):
            return None  # 越权路径
        if os.path.isdir(f):
            f = os.path.join(f, "index.html")
        return f if os.path.isfile(f) else None


DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
ICP_RE = re.compile(r"^[\u4e00-\u9fa5]ICP备\d{6,10}号(-\d{1,3})?$")


def check_publish(domain: str, icp: str) -> tuple[str, str]:
    """导出参数：域名（可选，用来生成 sitemap 和规范网址）、ICP 备案号（可选，加到每页页脚并链接到工信部备案网站）。"""
    d = (domain or "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if d and not DOMAIN_RE.match(d):
        raise ValueError("域名格式不对，例如 www.example.com（不要带路径）")
    i = (icp or "").strip()
    if i and not ICP_RE.match(i):
        raise ValueError("备案号格式不对，例如 京ICP备12345678号 或 京ICP备12345678号-1")
    return d, i


def export_zip(site_dir: str, name: str, domain: str = "", icp: str = "") -> bytes:
    """把一个版本的网站打成压缩包：链接改成显式的 index.html（双击就能离线打开，也能直接传到任何静态托管），附一份说明。"""
    import io
    import zipfile
    link = re.compile(r'(href|action)="(?!https?:|mailto:|tel:|data:|#|/)([^"#?]*?)(/?)((?:[?#][^"]*)?)"')

    def fix(m):
        attr, path, slash, tail = m.groups()
        if slash or path in ("", ".", "..") or path.endswith(("/.", "/..")):
            target = (path.rstrip("/") + "/" if path not in ("",) else "") + "index.html"
            return f'{attr}="{target}{tail}"'
        return m.group(0)
    buf, pages = io.BytesIO(), []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(site_dir):
            for f in sorted(files):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, site_dir).replace(os.sep, "/")
                data = open(full, "rb").read()
                if f.endswith(".html"):
                    html_ = link.sub(fix, data.decode("utf-8"))
                    if domain:  # 规范网址：告诉搜索引擎这页的正式地址
                        url = f"https://{domain}/" + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)
                        html_ = html_.replace("</head>", f'<link rel="canonical" href="{url}"><meta property="og:url" content="{url}"></head>', 1)
                        if 'content="noindex"' not in html_:
                            pages.append(url)
                    if icp:
                        html_ = html_.replace("</footer>", f'<p class="beian"><a href="https://beian.miit.gov.cn/" target="_blank" '
                                                           f'rel="noopener noreferrer">{icp}</a></p></footer>', 1)
                    data = html_.encode("utf-8")
                if rel == "robots.txt" and domain:
                    data = data.decode("utf-8").rstrip("\n").encode("utf-8") + f"\nSitemap: https://{domain}/sitemap.xml\n".encode("utf-8")
                z.writestr(f"{name}/{rel}", data)
        if domain:
            z.writestr(f"{name}/sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                       + "".join(f"<url><loc>{u}</loc></url>" for u in sorted(pages)) + "</urlset>\n")
        z.writestr(f"{name}/说明.txt", EXPORT_README)
    return buf.getvalue()


EXPORT_README = """这是 AI 建站工作台生成的静态网站。

怎么看：双击 index.html 就能在浏览器里打开，所有页面之间的链接都能点。

怎么上线：把整个文件夹上传到任意静态网站托管即可，不需要服务器程序。例如：
  - 国内：腾讯云 COS、阿里云 OSS 的“静态网站托管”（面向公众的网站通常需要先备案）
  - 境外：Cloudflare Pages、Netlify、GitHub Pages

上线前请注意：
  1. 页面里写着“（待填：…）”的地方，是不能替你编的真实信息（评价、价格、团队、地址等），请换成真实内容。
  2. 预约、联系表单目前只会跳到“已收到”页，不会真的把内容发给你。需要接一个表单服务（例如腾讯问卷、Formspree）或自己的后台后才能收到。
  3. 没换成你照片的位置用的是示意插图（一看就是插图，不会被当成实拍），可以直接上线；想换成真实照片，在工作台右边“图片”里上传。
     上传的照片已经去掉了拍摄地点、手机型号等信息，并压缩成网页大小。
  4. 在中国大陆的服务器上线：先办 ICP 备案（导出时填上备案号会自动加到每页页脚），开通后 30 天内办公安联网备案。
  5. 隐私政策页里的“待填”要按实际情况写清楚（收集什么、用来做什么、保存多久、怎么联系删除），最好请专业人士看一下。
  6. 导出时填了域名，会附带 sitemap.xml 和每页的规范网址，上线后可以提交到百度、必应等搜索引擎的站长平台。
"""


def make_handler(app: App, token: str = "", port_ref: list | None = None):
    page = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
    page = page.replace("</head>", f'<meta name="aisite-token" content="{token}">\n</head>', 1)
    live_page = open(os.path.join(HERE, "live.html"), encoding="utf-8").read()
    live_page = live_page.replace("</head>", f'<meta name="aisite-token" content="{token}">\n</head>', 1)

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, data, ctype="application/json; charset=utf-8"):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            """防 DNS 重绑定：只接受用 127.0.0.1/localhost 加本端口访问；有 Origin 时也必须是本机这个端口。"""
            port = self.server.server_address[1]
            ok = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host", "") not in ok:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in {f"http://{h}" for h in ok}

        def _token_ok(self, q=None) -> bool:
            """所有会改东西或给出数据包的请求都要带本次启动的令牌（写在页面里，别的网站拿不到）。"""
            import hmac
            got = self.headers.get("X-AISite-Token") or ((q or {}).get("token") or [""])[0]
            return bool(token) and hmac.compare_digest(got, token)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "只能从本机用 127.0.0.1 或 localhost 访问"})
            u = urlparse(self.path)
            path = u.path
            if path == "/api/export":
                from urllib.parse import parse_qs
                q = parse_qs(u.query)
                if not self._token_ok(q):
                    return self._send(403, {"error": "缺少令牌"})
                try:
                    name, data = app.export((q.get("session") or [""])[0], (q.get("version") or [""])[0],
                                            (q.get("domain") or [""])[0], (q.get("icp") or [""])[0])
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                from urllib.parse import quote  # 中文文件名按 RFC 5987 编码，HTTP 头里只能放 ASCII
                self.send_header("Content-Disposition", f"attachment; filename=\"website.zip\"; filename*=UTF-8''{quote(name)}.zip")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == "/":
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/live":
                return self._send(200, live_page.encode("utf-8"), "text/html; charset=utf-8")
            if path in ("/api/live", "/api/live/snapshot"):
                from urllib.parse import parse_qs
                q = parse_qs(u.query)
                if not self._token_ok(q):
                    return self._send(403, {"error": "缺少令牌"})
                if path == "/api/live/snapshot":
                    return self._send(200, live.snapshot())
                try:
                    since = max(0, int((q.get("since") or ["0"])[0]))
                except ValueError:
                    since = 0
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    live.stream(lambda b: (self.wfile.write(b), self.wfile.flush()), since,
                                max_seconds=float(os.environ.get("AISITE_LIVE_SECONDS", "1800")))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                return
            if path == "/api/knowledge":
                return self._send(200, app.knowledge())
            if path == "/api/models":
                return self._send(200, app.models())
            if path == "/favicon.ico":  # 浏览器会自动来要图标；给空响应，免得每页一个 404
                self.send_response(204); self.end_headers(); return
            f = app.static(path)
            if not f:
                return self._send(404, {"error": "没有这个文件"})
            ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
            with open(f, "rb") as fh:
                self._send(200, fh.read(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))

        def do_POST(self):
            if not self._host_ok():
                return self._send(403, {"error": "只能从本机用 127.0.0.1 或 localhost 访问"})
            if not self._token_ok():
                return self._send(403, {"error": "缺少或错误的令牌（请从工作台页面操作）"})
            n = int(self.headers.get("Content-Length") or 0)
            lim = {"/api/feed": MAX_FEED_BODY, "/api/image/upload": MAX_IMAGE_BODY}.get(urlparse(self.path).path, MAX_BODY)
            if n > lim:
                return self._send(413, {"error": "照片太大，最大 15MB" if lim == MAX_IMAGE_BODY else "请求太大"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("请求格式不对")
                route = {"/api/start": app.start, "/api/answer": app.answer, "/api/preview": app.preview,
                         "/api/choose": app.choose, "/api/feed": app.feed, "/api/undo": app.undo,
                         "/api/edit": app.edit, "/api/models/save": app.models_save, "/api/models/test": app.models_test,
                         "/api/models/list": app.models_list, "/api/models/quick": app.models_quick, "/api/images": app.images, "/api/image/upload": app.image_upload,
                         "/api/image/alt": app.image_alt, "/api/image/reset": app.image_reset}.get(urlparse(self.path).path)
                if not route:
                    return self._send(404, {"error": "没有这个接口"})
                return self._send(200, route(body))
            except (ValueError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # 生成或检查本身出错：告诉页面，不让服务挂掉
                return self._send(500, {"error": f"{type(e).__name__}: {str(e)[:200]}"})
    return H


def serve(port=0, work="/tmp/aisite-work", choices=None, knowledge=None):
    import secrets
    app = App(work, choices, knowledge)
    app.token = secrets.token_urlsafe(24)  # 每次启动换一个
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, app.token))
    srv.daemon_threads = True  # 实况页面的长连接不挡住关机
    return srv, app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    model_config.load_env()
    srv, _ = serve(port, sys.argv[2] if len(sys.argv) > 2 else "/tmp/aisite-work")
    print(f"工作台已启动：http://127.0.0.1:{srv.server_address[1]}/ （只在本机可访问，Ctrl+C 停止）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
