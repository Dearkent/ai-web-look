#!/usr/bin/env python3
"""学习大脑 v0 —— 外置的经验记忆 + 任务调度 + 验证门。

模型本身不会记住上一次会话学到的东西，所以“学习”全部落在这个目录里：
  cards/     经验卡片（每次修复、每次踩坑提炼出的规律）
  self/      自我认知：能力.md、缺陷.md
  tasks.json 任务队列
  journal/   工作日志（按天）
  checks/    把经验固化成的确定性检查脚本
  evals/     验证门：经验要通过评测才算 verified

工作协议（每个任务都走一遍）：
  next → recall（干活前先回忆）→ start → 干活 → log → 反思写卡 → verify → done

用法：
  python3 brain.py next
  python3 brain.py recall "许可证 子目录"
  python3 brain.py start T04
  python3 brain.py log "读完 message-parser.ts"
  python3 brain.py new-card --title "..." --trigger "..." --scope 平台
  python3 brain.py use L001          # 记录某条经验被用上了一次
  python3 brain.py done T04 "产出读码笔记"
  python3 brain.py verify            # 跑验证门
  python3 brain.py feed-design 地址或文件夹… [--for 行业] [--list 清单] [--refresh]   # 喂网站设计（只读版面和颜色）
  python3 brain.py priors build|trial|show                              # 从喂的设计里提炼规律、试跑、查看
  python3 brain.py stats
"""
import argparse
import json
import math
import re
import subprocess
import time
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CARDS = ROOT / "cards"
SELF = ROOT / "self"
JOURNAL = ROOT / "journal"
TASKS = ROOT / "tasks.json"
EVALS = ROOT / "evals" / "cases.json"
TZ = ZoneInfo("Asia/Singapore")


def now():
    return datetime.now(TZ)


# ---------- 卡片读写 ----------
def parse_card(path):
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2)
    meta["_path"] = path
    meta["_body"] = body
    return meta


def write_card(meta):
    path = meta["_path"]
    keys = [k for k in meta if not k.startswith("_")]
    head = "\n".join(f"{k}: {meta[k]}" for k in keys)
    path.write_text(f"---\n{head}\n---\n{meta['_body']}", encoding="utf-8")


def all_cards():
    # L = 我自己怎么干活的经验；P = 给我们要做的产品（建站工作台）的设计经验
    return [parse_card(p) for p in sorted(CARDS.glob("[LP][0-9]*.md"))]


# ---------- 检索：中文二元组 + 英文单词，BM25 风格 ----------
def tokens(text):
    text = text.lower()
    out = re.findall(r"[a-z0-9_.\-/]{2,}", text)
    for run in re.findall(r"[一-鿿]+", text):
        out += [run[i:i + 2] for i in range(len(run) - 1)] or [run]
    return out


# 同义词组（D08：只按字面匹配，“报错”召回不到写着“错误”的卡片）。发现新的漏召回就往这里加。
SYNONYMS = [
    ["报错", "错误", "异常", "失败", "出错", "error", "崩溃"],
    ["回读", "写回", "反馈", "回传", "读回", "看到"],
    ["修复", "自修复", "修正", "fix"],
    ["版本", "提交", "回滚", "撤销", "commit", "rollback"],
    ["风格", "样式", "主题", "设计系统", "style", "theme"],
    ["许可", "许可证", "license", "开源"],
    ["工具", "tool", "工具箱", "toolkit"],
    ["蓝图", "规划", "计划", "blueprint", "plan"],
    ["数量", "计数", "行数", "条数"],
]


def expand(query):
    extra = [w for group in SYNONYMS if any(w in query.lower() for w in group) for w in group]
    return query + " " + " ".join(extra)


def recall(query, k=3, quiet=False, cards=None):
    cards = all_cards() if cards is None else cards
    if not cards:
        return []
    query = expand(query)
    docs = []
    for c in cards:
        weighted = (c.get("title", "") + " ") * 3 + (c.get("trigger", "") + " ") * 2 + c["_body"]
        docs.append(Counter(tokens(weighted)))
    n = len(docs)
    avg = sum(sum(d.values()) for d in docs) / n
    q = set(tokens(query))
    scored = []
    for c, d in zip(cards, docs):
        length = sum(d.values())
        s = 0.0
        for t in q:
            df = sum(1 for x in docs if t in x)
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            tf = d[t]
            s += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / avg))
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    top = scored[:k]
    if not quiet:
        if not top:
            print("（没有相关经验）")
        for s, c in top:
            print(f"[{c.get('id')}] {c.get('title')}  ·{c.get('status')}·  相关度 {s:.2f}")
            print(f"    何时适用：{c.get('trigger')}")
    return top


# ---------- 任务 ----------
def load_tasks():
    return json.loads(TASKS.read_text(encoding="utf-8"))


def save_tasks(tasks):
    TASKS.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def log(text):
    JOURNAL.mkdir(exist_ok=True)
    f = JOURNAL / f"{now():%Y-%m-%d}.md"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"- {now():%H:%M} {text}\n")
    print(f"已记录：{text}")


def cmd_next(_):
    for t in load_tasks():
        if t["status"] in ("doing", "todo"):
            print(f"下一个任务：{t['id']} {t['title']}（{t['status']}）")
            print(f"  要求：{t.get('goal', '')}")
            q = t["title"] + " " + t.get("goal", "")
            cards = all_cards()
            print("\n干活前先回忆——工作方法经验（L）：")
            recall(q, 3, cards=[c for c in cards if c.get("id", "").startswith("L")])
            print("\n——产品设计经验（P）：")
            recall(q, 3, cards=[c for c in cards if c.get("id", "").startswith("P")])
            return
    print("任务队列已清空。")


def set_status(tid, status, note=None):
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == tid:
            t["status"] = status
            t[f"{status}_at"] = now().isoformat(timespec="minutes")
            if note:
                t["note"] = note
            save_tasks(tasks)
            log(f"{tid} → {status}" + (f"：{note}" if note else ""))
            return
    sys.exit(f"找不到任务 {tid}")


# ---------- 卡片命令 ----------
def cmd_new_card(a):
    ids = [int(c["id"][1:]) for c in all_cards() if c.get("id", "").startswith(a.prefix)]
    cid = f"{a.prefix}{(max(ids) + 1) if ids else 1:03d}"
    meta = {
        "id": cid, "title": a.title, "trigger": a.trigger, "scope": a.scope,
        "status": "draft", "hits": "0", "source": a.source or "", "created": f"{now():%Y-%m-%d}",
        "_path": CARDS / f"{cid}.md",
        "_body": "\n## 根因\n\n## 做法\n\n## 反例（什么时候不适用）\n\n## 固化\n（是否已变成 checks/ 下的确定性检查）\n",
    }
    write_card(meta)
    print(f"已创建草稿卡片 {cid}：{meta['_path']}")


def cmd_use(a):
    for c in all_cards():
        if c.get("id") == a.id:
            c["hits"] = str(int(c.get("hits", "0")) + 1)
            c["last_used"] = f"{now():%Y-%m-%d}"
            write_card(c)
            log(f"用上经验 {a.id}：{c.get('title')}")
            return
    sys.exit(f"找不到卡片 {a.id}")


# ---------- 验证门 ----------
def run_bounded(cmd, limit):
    """有界地运行一条命令：超时就杀掉整个进程组。
    只杀 shell 不够——子进程还握着输出管道，读输出会一直等下去（D11）。"""
    import os, signal
    env = dict(os.environ)
    # 验证门里的测试会造假建站（故意出错、假的修复）：它们的事件记到单独的文件，不混进实况的真实记录
    env.setdefault("AISITE_EVENTS", str(ROOT / "runs" / "events-tests.jsonl"))
    p = subprocess.Popen(cmd, shell=True, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, start_new_session=True, env=env)
    try:
        return p.communicate(timeout=limit)[0], limit
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.communicate(timeout=10)
        return None, limit


def cmd_verify(_):
    cases = json.loads(EVALS.read_text(encoding="utf-8"))
    results = {}
    ok_all = True
    run = []
    sys.path.insert(0, str(ROOT / "product" / "app"))
    import events
    gate = events.run("gate", 用例=len(cases))
    gate.__enter__()
    for case in cases:
        t0 = time.time()
        out, limit = run_bounded(case["cmd"], case.get("timeout", 120))
        if out is None:
            out = ""
            print(f"超时  {case['id']}  超过 {limit} 秒，已结束整个进程组")
        missing = [e for e in case["expect"] if e not in out]
        passed = not missing
        ok_all &= passed
        results.setdefault(case["card"], []).append(passed)
        run.append({"id": case["id"], "card": case["card"], "desc": case["desc"],
                    "result": "通过" if passed else ("超时" if out == "" and missing else "失败")})
        events.emit("gate.case", id=case["id"], card=case["card"], ok=passed, ms=int((time.time() - t0) * 1000))
        print(f"{'通过' if passed else '失败'}  {case['id']}  ({case['card']}) {case['desc']}")
        if missing:
            print(f"      缺少输出：{missing}")
            tail = [x for x in (out or "").strip().splitlines() if x.strip()][-3:]
            print("      实际输出：" + (" ⏎ ".join(t[:200] for t in tail) if tail else ("（超时，没有输出）" if out is None else "（空）")))
    for c in all_cards():
        r = results.get(c.get("id"))
        if r is None:
            continue
        new = "verified" if all(r) else "failing"
        if c.get("status") != new:
            c["status"] = new
            write_card(c)
    (ROOT / "evals" / "last_run.json").write_text(json.dumps(
        {"at": now().strftime("%Y-%m-%d %H:%M"), "rows": run}, ensure_ascii=False, indent=1), encoding="utf-8")
    gate.result = {"cards_ok": sum(map(all, results.values())), "cards": len(results)}
    gate.__exit__(None, None, None)
    log(f"验证门：{sum(map(all, results.values()))}/{len(results)} 张卡片通过")
    sys.exit(0 if ok_all else 1)


def cmd_stats(_):
    cards = all_cards()
    st = Counter(c.get("status") for c in cards)
    sc = Counter(c.get("scope") for c in cards)
    tasks = load_tasks()
    ts = Counter(t["status"] for t in tasks)
    defects = len(re.findall(r"^### ", (SELF / "缺陷.md").read_text(encoding="utf-8"), re.M))
    print(f"经验卡片 {len(cards)} 张：" + "，".join(f"{k} {v}" for k, v in st.items()))
    print("作用范围：" + "，".join(f"{k} {v}" for k, v in sc.items()))
    print(f"已固化为检查：{sum(1 for c in cards if re.search(r'^已固化', c['_body'], re.M))} 张")
    print(f"自我缺陷记录：{defects} 条")
    print(f"任务：" + "，".join(f"{k} {v}" for k, v in ts.items()))
    hot = sorted(cards, key=lambda c: -int(c.get("hits", "0")))[:3]
    print("最常用的经验：" + "；".join(f"{c['id']}（{c.get('hits')} 次）" for c in hot))


# ---------- 沟通记录与看板导出 ----------
def cmd_comm(a):
    path = ROOT / "comms.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    rows.append({"seq": len(rows) + 1, "at": now().strftime("%Y-%m-%d %H:%M"), "who": a.who, "kind": a.kind, "text": a.text})
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已记入沟通记录 #{len(rows)}")


def _ids(text):
    """从一段文字里找出 T01、L012、P001-P003 这样的编号（区间展开）。"""
    out = []
    for m in re.finditer(r"\b([TLPDE])(\d{2,3})(?:\s*[-–]\s*\1?(\d{2,3}))?\b", text or ""):
        k, a, b = m.group(1), int(m.group(2)), m.group(3)
        w = len(m.group(2))
        for n in range(a, (int(b) if b else a) + 1)[:50]:
            out.append(f"{k}{n:0{w}d}")
    return out


def _fix_runs():
    """修复记录：每次自动修复一行（守卫的轮数、结果、刹车代码），用来以后校准阈值。"""
    f = ROOT / "runs" / "fix_runs.jsonl"
    rows = []
    if f.exists():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            r = json.loads(line)
            rows.append({"seq": i, "label": r.get("label", ""), "result": "修好" if r["verdict"] == "done" else "停下",
                         "code": r.get("code") or "", "rounds": len(r.get("rounds", [])),
                         "errors_before": r.get("errors_before"), "errors_after": r.get("errors_after"),
                         "seconds": r.get("seconds")})
    return rows


def _roadmap(last):
    """路线图：有证据评测的条目，评测没通过就自动降为“部分完成”，完成度不能自己说了算。"""
    f = ROOT / "roadmap.json"
    if not f.exists():
        return []
    passed = {r["id"] for r in last.get("rows", []) if r["result"] == "通过"}
    out = []
    for r in json.loads(f.read_text(encoding="utf-8")):
        st = r["status"]
        if st == "done" and r["evidence"] and not set(r["evidence"]) <= passed:
            st = "partial"
        score = {"done": 1.0, "partial": 0.5}.get(st, 0.0)
        out.append({"id": r["id"], "phase": r["phase"], "item": r["item"], "weight": r["weight"],
                    "status": {"done": "完成", "partial": "部分", "todo": "未做"}[st],
                    "earned": round(r["weight"] * score, 1), "evidence": "、".join(r["evidence"]), "note": r["note"]})
    return out


def cmd_progress(a):
    last = json.loads((ROOT / "evals" / "last_run.json").read_text(encoding="utf-8"))
    rows = _roadmap(last)
    tw = sum(r["weight"] for r in rows)
    tot = sum(r["earned"] for r in rows) / tw * 100  # 新增条目会让总权重超过 100，按比例折算
    print(f"总完成度：{tot:.1f}%（按权重，总权重 {tw}；有评测证据的条目以最近一次验证门为准）")
    phases = {}
    for r in rows:
        p = phases.setdefault(r["phase"], [0, 0])
        p[0] += r["earned"]; p[1] += r["weight"]
    for k, (e, w) in phases.items():
        print(f"  {k}：{e:.1f}/{w}（{e / w * 100:.0f}%）")


def cmd_export(a):
    """把大脑导出成看板用的六张表（JSON 行）。"""
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    cards = all_cards()
    dtext = (SELF / "缺陷.md").read_text(encoding="utf-8")
    defects = []
    for blk in re.split(r"^### ", dtext, flags=re.M)[1:]:
        head, _, body = blk.partition("\n")
        m = re.match(r"(D\d+)\s*(.*)", head.strip())
        if m:
            lesson = re.search(r"经验[:：]\s*([LP]\d{3})", body)
            defects.append({"id": m.group(1), "title": m.group(2), "lesson": lesson.group(1) if lesson else ""})
    defects.sort(key=lambda d: int(d["id"][1:]))
    last = json.loads((ROOT / "evals" / "last_run.json").read_text(encoding="utf-8")) \
        if (ROOT / "evals" / "last_run.json").exists() else {"at": "", "rows": []}
    comms = json.loads((ROOT / "comms.json").read_text(encoding="utf-8")) if (ROOT / "comms.json").exists() else []
    card_ids = {c["id"] for c in cards}
    task_ids = {t["id"] for t in tasks}
    edges = []
    for t in tasks:
        for i in _ids(t.get("note", "")):
            if i in card_ids:
                edges.append({"source": t["id"], "target": i, "kind": "产出"})
    cur = None  # 日志里“用上经验”归到当时正在做的任务
    for f in sorted(JOURNAL.glob("*.md")):
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.search(r"(T\d{2}) → doing", line)
            if m:
                cur = m.group(1)
            m = re.search(r"用上经验 ([LP]\d{3})", line)
            if m and cur in task_ids and m.group(1) in card_ids:
                edges.append({"source": cur, "target": m.group(1), "kind": "用上"})
    for d in defects:
        if d["lesson"] in card_ids:
            edges.append({"source": d["id"], "target": d["lesson"], "kind": "教训"})
    for r in last["rows"]:
        if r["card"] in card_ids:
            edges.append({"source": r["id"], "target": r["card"], "kind": "验证"})
    seen, uniq = set(), []
    for e in edges:
        k = (e["source"], e["target"], e["kind"])
        if k not in seen:
            seen.add(k); uniq.append(e)
    tables = {
        "tasks": [{"id": t["id"], "title": t["title"], "status": t["status"], "done_at": t.get("done_at", ""),
                   "note": t.get("note", "")} for t in tasks],
        "cards": [{"id": c["id"], "title": c.get("title", ""), "kind": "工作经验" if c["id"][0] == "L" else "产品经验",
                   "status": c.get("status", ""), "hits": int(c.get("hits", "0") or 0),
                   "codified": "是" if re.search(r"^已固化", c["_body"], re.M) else "否",
                   "created": c.get("created", "")} for c in cards],
        "defects": defects,
        "evals": [dict(r, at=last["at"]) for r in last["rows"]],
        "comms": comms,
        "edges": uniq,
        "fix_runs": _fix_runs(),
        "roadmap": _roadmap(last),
    }
    for k, v in tables.items():
        (out / f"{k}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    print("导出：" + "，".join(f"{k} {len(v)} 行" for k, v in tables.items()) + f"（验证门结果时间 {last['at']}）")


def _learn_cli(mod, argv):
    sys.path.insert(0, str(ROOT / "product" / "learn"))
    sys.path.insert(0, str(ROOT / "product" / "app"))
    import importlib
    m = importlib.import_module(mod)
    if mod == "corpus":
        sys.exit(m.main(argv))
    cmd = argv[0] if argv else "show"
    if cmd == "build":
        m.build()
    elif cmd == "trial":
        print(m.trial(run_browser="--no-browser" not in argv))
    print("\n".join(m.show()))


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("feed-design", "priors"):  # 喂网站设计 / 设计先验：参数原样交给 product/learn
        return _learn_cli("corpus" if sys.argv[1] == "feed-design" else "priors", sys.argv[2:])
    p = argparse.ArgumentParser(description="学习大脑 v0（另有：feed-design 喂网站设计、priors build|trial|show 设计先验）")
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("next")
    r = s.add_parser("recall"); r.add_argument("query"); r.add_argument("-k", type=int, default=3)
    st = s.add_parser("start"); st.add_argument("id")
    d = s.add_parser("done"); d.add_argument("id"); d.add_argument("note", nargs="?")
    lg = s.add_parser("log"); lg.add_argument("text")
    n = s.add_parser("new-card")
    n.add_argument("--title", required=True); n.add_argument("--trigger", required=True)
    n.add_argument("--scope", default="平台"); n.add_argument("--source")
    n.add_argument("--prefix", default="L", choices=["L", "P"], help="L=工作经验，P=产品设计经验")
    u = s.add_parser("use"); u.add_argument("id")
    s.add_parser("verify"); s.add_parser("stats")
    cm = s.add_parser("comm"); cm.add_argument("--who", required=True, choices=["用户", "我"])
    cm.add_argument("--kind", default="汇报"); cm.add_argument("text")
    s.add_parser("progress")
    ex = s.add_parser("export"); ex.add_argument("--out", default=str(ROOT / "dashboard"))
    a = p.parse_args()
    {
        "next": cmd_next,
        "recall": lambda a: recall(a.query, a.k),
        "start": lambda a: set_status(a.id, "doing"),
        "done": lambda a: set_status(a.id, "done", a.note),
        "log": lambda a: log(a.text),
        "new-card": cmd_new_card, "use": cmd_use, "verify": cmd_verify, "stats": cmd_stats,
        "comm": cmd_comm, "export": cmd_export, "progress": cmd_progress,
    }[a.cmd](a)


if __name__ == "__main__":
    main()
