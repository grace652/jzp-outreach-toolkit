#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 10/02 跟进信队列（31 封）

窗口（收件人当地 09:00–10:00）：
  AT 2 家 → 北京 20:00–21:00  ⚠️ **构建时已过**（当地 10:45）→ 按 10/01 先例**当天补发**
  ET 15 家 → 北京 21:00–22:00 ⚠️ **构建时剩 15 分钟** → 立即起发，紧密排布
  CT 10 家 → 北京 22:00–23:00
  PT 4 家 → 北京 00:00–01:00（10/03）

约束：全局**任意两封不同分钟**。
"""
import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(Path(__file__).resolve().parents[1])
TODAY = "2026-10-02"
WORK = ROOT / f".workbuddy-ai/今日工作单-{TODAY}.json"
QUEUE = ROOT / f"发信队列-跟进1002.json"
BJ = timezone(timedelta(hours=8))
TZ_OFF = {"AT": -3, "ET": -4, "CT": -5, "MT": -6, "PT": -7}
TZ_CN = {"AT": "大西洋", "ET": "美东", "CT": "美中", "MT": "美山", "PT": "美西"}

WINDOW = {
    "AT": ("2026-10-02 21:46", "2026-10-02 21:47"),   # ⚠️ 授权补发（当地约 10:46–10:47）
    "ET": ("2026-10-02 21:48", "2026-10-02 22:02"),   # 当地 09:48–10:02（窗口尾）
    "CT": ("2026-10-02 22:03", "2026-10-02 22:58"),   # 当地 09:03–09:58
    "PT": ("2026-10-03 00:02", "2026-10-03 00:58"),   # 当地 09:02–09:58
}


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, ROOT / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    sd = load("sdq2", "发送开发信.py")
    av = load("avq2", "地址验证.py")
    sc = load("scq2", "定时发送.py")
    sig = sd.load_signature()
    BL = sc.load_blacklist()
    now = datetime.now(BJ)

    work = json.loads(WORK.read_text(encoding="utf-8"))
    md = (ROOT / "开发信项目/工作区/开发信跟进表.md").read_text(encoding="utf-8")

    groups = defaultdict(list)
    for x in work:
        b = re.search(rf"^### {x['num']}\.\s.*?(?=^### |\Z)", md, re.S | re.M)
        ft = re.sub(r"[（(].*", "", re.search(r"\*\*信文件\*\*：(.+)", b.group(0)).group(1)
                    ).strip().strip("`").replace("clients/", "")
        slug = ft.replace("开发信-", "开发信-跟进-")
        if "第 2 次" in x["round"]:
            slug = slug.replace("开发信-跟进-", "开发信-跟进-第2轮-")
        x["_file"] = slug
        groups[x["tz"]].append(x)

    used, items, problems = set(), [], []
    for tz in ("AT", "ET", "CT", "PT"):
        rows = sorted(groups.get(tz, []), key=lambda y: y["num"])
        if not rows:
            continue
        w0, w1 = (datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=BJ) for s in WINDOW[tz])
        step = (w1 - w0).total_seconds() / 60.0 / max(len(rows) - 1, 1)
        for i, x in enumerate(rows):
            f = ROOT / "开发信项目/clients" / x["_file"]
            if not f.exists():
                problems.append(f"#{x['num']} 文件不存在 {x['_file']}")
                continue
            subs, body, notes = sd.parse_letter(f)
            body = sd.trim_signature_tail(body)
            to, cc = sd.recipients_of(notes), sd.cc_of(notes)
            wc = len(body.split())
            errs = []
            if not subs: errs.append("无主题")
            if not to: errs.append("无收件人")
            if not (20 <= wc <= 100): errs.append(f"词数 {wc}")
            try:
                sd.compliance_check(body, sig, followup=True)
            except SystemExit as e:
                errs.append(f"红线：{e}")
            for a in to + cc:
                # 🔴 2026-10-05：跟进信走**零退信**口径（strict_followup=True）
                bl, why = sc.is_blocked(a, now, BL, strict_followup=True)
                if bl: errs.append(f"闸门：{a} {why}")
                v = av.verify(a, do_probe=False, polite_delay=0)
                if v["verdict"].startswith("⛔"): errs.append(f"MX：{a}")
            if errs:
                problems.append(f"#{x['num']} {x['_file']}: {'; '.join(errs)}")
                continue
            when = w0 + timedelta(minutes=round(step * i))
            while when.strftime("%Y-%m-%d %H:%M") in used:
                when += timedelta(minutes=1)
            used.add(when.strftime("%Y-%m-%d %H:%M"))
            loc = when.astimezone(timezone(timedelta(hours=TZ_OFF[tz])))
            items.append(dict(letter=x["_file"], to=to, cc=cc, subject=subs[0], tz=tz,
                              local_label=TZ_CN[tz],
                              scheduled_at_bj=when.strftime("%Y-%m-%d %H:%M"),
                              scheduled_at_local=loc.strftime("%Y-%m-%d %H:%M"),
                              status="pending", blocked_reason="",
                              queued_at=now.strftime("%Y-%m-%d %H:%M"), sent_at=None))
    items.sort(key=lambda y: y["scheduled_at_bj"])
    print(f"入队 {len(items)}/{len(work)} 封\n")
    for x in items:
        print(f"  北京 {x['scheduled_at_bj']} → {x['local_label']} {x['scheduled_at_local'][5:]}  {x['to'][0]}")
    if problems:
        print("\n⛔ 未入队：")
        for p in problems: print("  " + p)
        return 1
    print(f"\n同刻冲突：{len(items) - len({x['scheduled_at_bj'] for x in items})}（应为 0）")
    QUEUE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已写 {QUEUE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
