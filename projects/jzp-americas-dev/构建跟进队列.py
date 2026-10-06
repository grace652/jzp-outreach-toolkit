#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建「跟进信」发送队列（错峰排程）
====================================

用户 2026-09-28 要求：把今天该发的 38 封跟进信发出去，
**不要同一时间发，避免垃圾邮箱检测**。

排程原则（关键）
----------------
1. **窗口仍开放的优先** —— 只有 MT / PT / AKT 三组的「客户当地上午」还没过，
   必须先把它们排进窗口内；否则一旦被 ET/CT 占掉时间，这些窗口就永久错过。
2. **已过窗口的排后面** —— ET / CT / AT 的当地上午已过（用户已确认"不必卡 9–10 点"），
   放在最后，仍按固定间隔错峰。
3. **全局最小间隔 MIN_GAP** —— 任意两封之间至少隔 N 分钟，杜绝"同刻并发"
   （群发特征）。窗口内若放不下，组内间隔自动压缩，但绝不重叠。
4. **绝不越窗** —— 窗口开放的组，最后一封不得晚于窗口结束。

时差（9 月夏令时，北京 − 当地）
-------------------------------
ET 12h ｜ CT 13h ｜ MT 14h ｜ PT 15h ｜ AKT 16h ｜ AT 11h
→ 当地 09:00 对应的北京时间：ET 21:00 / CT 22:00 / MT 23:00 / PT 00:00 / AKT 00:00 / AT 20:00
  （AKT 与 PT 同为 00:00，但 AKT 对应当地 08:00 —— 对方 7:30 上班，是刻意提前）
"""
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENTS = ROOT / "开发信项目" / "clients"
QUEUE = ROOT / "发信队列.json"
BACKUP = ROOT / "发信队列-batch5备份.json"
BJ = timezone(timedelta(hours=8))

MIN_GAP = 6      # 全局最小间隔（分钟）—— 用户要求"不要同一时间发"
LEAD = 4         # 最早时刻 = now + LEAD 分钟（留出构建与校验时间）

TZ_DELTA = {"ET": 12, "CT": 13, "MT": 14, "PT": 15, "AKT": 16, "AT": 11}
TZ_CN = {"ET": "美东", "CT": "美中", "MT": "美山", "PT": "美西",
         "AKT": "阿拉斯加", "AT": "大西洋"}

# 目标当地起始小时（默认 09:00）。
# ⚠️ AKT 特例：阿拉斯加客户 07:30 上班，老项目既定口径是**当地 08:00–09:00**
#    （见 `发送时间对照表.md`：阿拉斯加「00:00–01:30（当地 8:00–9:00）」）。
#    跟进信表头也写的是「00:00–01:00（阿拉斯加 AKT）」，故此处对齐 08:00 起。
TZ_LOCAL_START = {"AKT": 8}

# slug → 时区（取自 📋待发清单-跟进-20260928.xlsx 的「时区」列）
SLUG_TZ = {}


def load(mod, fn):
    spec = importlib.util.spec_from_file_location(mod, ROOT / fn)
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod] = m
    spec.loader.exec_module(m)
    return m


def slug_of(p: Path) -> str:
    return p.stem.replace("开发信-跟进-", "")


def window_bj(tz: str, now: datetime):
    """返回 (窗口起, 窗口止) 的北京时间。

    基准是**客户当地今天**的目标时段（默认 09:00–10:00；AKT 为 08:00–09:00）。
    ⚠️ 注意「客户当地今天」：北京 23:50 时，美东还是当天中午、美西还是当天上午，
    所以算出来的窗口可能落在**北京次日凌晨** —— 这是正常的，因为
    **北京凌晨 = 收件人白天**。排程跨日不等于"跨到对方下班"。
    """
    d = TZ_DELTA[tz]
    h = TZ_LOCAL_START.get(tz, 9)
    local_now = now - timedelta(hours=d)
    ws_local = local_now.replace(hour=h, minute=0, second=0, microsecond=0)
    we_local = ws_local + timedelta(hours=1)
    return ws_local + timedelta(hours=d), we_local + timedelta(hours=d)


def main():
    sd = load("sd", "发送开发信.py")
    AV = load("AV", "地址验证.py")

    # 统一用**朴素**北京时间（与队列里 "YYYY-MM-DD HH:MM" 字符串口径一致），
    # 避免 aware/naive 混用导致 `can't compare offset-naive and offset-aware`。
    now = datetime.now(BJ).replace(tzinfo=None, second=0, microsecond=0)
    print(f"构建时刻（北京）：{now:%Y-%m-%d %H:%M}")
    print(f"最小间隔：{MIN_GAP} 分钟 ｜ 最早发送：{now + timedelta(minutes=LEAD):%H:%M}\n")

    files = sorted(CLIENTS.glob("开发信-跟进-*.md"))
    print(f"发现跟进信 {len(files)} 封\n")

    items = []
    for f in files:
        slug = slug_of(f)
        tz = SLUG_TZ.get(slug)
        if not tz:
            print(f"  ⛔ {slug}：无时区映射，跳过")
            continue
        subs, body, notes = sd.parse_letter(f)
        to = sd.recipients_of(notes)
        cc = sd.cc_of(notes)
        if not subs or not body or not to:
            print(f"  ⛔ {slug}：解析不全（主题{len(subs)}/正文{bool(body)}/收件人{to}）")
            continue
        problems = list(sd.compliance_check(sd.trim_signature_tail(body),
                                            sd.load_signature(), followup=True))
        # MX 校验（3 次重试，防 DNS 抖动假阴性）
        for a in to + cc:
            v = None
            for attempt in range(3):
                v = AV.verify(a, do_probe=False, polite_delay=0)
                if not v["verdict"].startswith("⛔"):
                    break
                if "MX" not in "".join(v.get("notes") or []):
                    break
                if attempt < 2:
                    import time
                    time.sleep(1.5 * (attempt + 1))
            if v and v["verdict"].startswith("⛔"):
                problems.append(f"地址验证：{a} — {v['notes'][-1]}")
        ws, we = window_bj(tz, now)
        items.append({
            "letter": f.name, "slug": slug, "to": to, "cc": cc,
            "subject": subs[0], "tz": tz,
            "window_start_bj": ws.strftime("%Y-%m-%d %H:%M"),
            "window_end_bj": we.strftime("%Y-%m-%d %H:%M"),
            "window_open": we > now,
            "local_label": TZ_CN.get(tz, tz),
            "dst": True,
            "status": "pending" if not problems else "blocked",
            "blocked_reason": "; ".join(problems) if problems else "",
            "queued_at": now.strftime("%Y-%m-%d %H:%M"),
            "sent_at": None, "scheduled_at_bj": None, "scheduled_at_local": None,
        })

    ok = [i for i in items if i["status"] == "pending"]
    bad = [i for i in items if i["status"] != "pending"]
    print(f"通过闸门：{len(ok)} 封 ｜ 被拦：{len(bad)} 封")
    for b in bad:
        print(f"  ⛔ {b['slug']}: {b['blocked_reason']}")
    print()

    # ---------- 排程 ----------
    cursor = now + timedelta(minutes=LEAD)
    open_items = [i for i in ok if i["window_open"]]
    exp_items = [i for i in ok if not i["window_open"]]

    # 1) 窗口开放的：按 (窗口起, 时区) 分组，组内均匀铺开且不越窗
    groups = {}
    for i in open_items:
        groups.setdefault(i["window_start_bj"], []).append(i)
    for key in sorted(groups):
        grp = groups[key]
        ws = datetime.strptime(grp[0]["window_start_bj"], "%Y-%m-%d %H:%M")
        we = datetime.strptime(grp[0]["window_end_bj"], "%Y-%m-%d %H:%M")
        start = max(cursor, ws)
        avail = int((we - start).total_seconds() // 60)
        gap = max(1, min(MIN_GAP, avail // max(1, len(grp))))
        for i in grp:
            i["scheduled_at_bj"] = start.strftime("%Y-%m-%d %H:%M")
            start += timedelta(minutes=gap)
        cursor = max(cursor, start)

    # 2) 窗口已过：接在最后，按固定间隔（时区偏东的先发，当地上午刚过的排前面）
    exp_items.sort(key=lambda x: -TZ_DELTA[x["tz"]])
    for i in exp_items:
        i["scheduled_at_bj"] = cursor.strftime("%Y-%m-%d %H:%M")
        cursor += timedelta(minutes=MIN_GAP)

    # 补 scheduled_at_local
    for i in ok:
        bj = datetime.strptime(i["scheduled_at_bj"], "%Y-%m-%d %H:%M")
        i["scheduled_at_local"] = (bj - timedelta(hours=TZ_DELTA[i["tz"]])).strftime("%Y-%m-%d %H:%M")

    # ---------- 落盘 ----------
    if QUEUE.exists() and not BACKUP.exists():
        shutil.copy2(QUEUE, BACKUP)
        print(f"已备份原队列 → {BACKUP.name}")
    allitems = sorted(items, key=lambda x: (x["scheduled_at_bj"] is None, x["scheduled_at_bj"] or ""))
    QUEUE.write_text(json.dumps(allitems, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 报告 ----------
    print(f"{'时刻(北京)':<17}{'当地':<17}{'时区':<6}{'收件人':<40}{'抄送':<30}公司")
    print("-" * 128)
    for i in allitems:
        if not i["scheduled_at_bj"]:
            continue
        ccx = ",".join(i["cc"]) if i["cc"] else "—"
        print(f"{i['scheduled_at_bj']:<17}{i['scheduled_at_local']:<17}"
              f"{i['tz']:<6}{','.join(i['to'])[:38]:<40}{ccx[:28]:<30}{i['slug']}")
    print("-" * 128)
    if allitems and allitems[-1]["scheduled_at_bj"]:
        first = allitems[0]["scheduled_at_bj"]
        last = allitems[-1]["scheduled_at_bj"]
        f_dt = datetime.strptime(first, "%Y-%m-%d %H:%M")
        l_dt = datetime.strptime(last, "%Y-%m-%d %H:%M")
        span = (l_dt - f_dt).total_seconds() / 60
        print(f"共 {len(ok)} 封 ｜ {first} → {last} ｜ 跨度 {span:.0f} 分钟 "
              f"（平均间隔 {span/max(1,len(ok)-1):.1f} 分钟）")
    print(f"\n✅ 已写入 {QUEUE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
