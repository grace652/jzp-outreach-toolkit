#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核对「到期/逾期客户」的真实跟进实况（不靠表格猜）

背景：跟进表存在**漂移** —— 9/29 批次实际发过 21 封，但表里 9/29 到期的有 26 家，
说明部分行**没被推进**。若直接按表格写跟进信，会对**已经跟过**的客户重复发。

做法：拿每家的邮箱，去 `Sent Messages` 实测**实际发出记录**：
  · 最近一次发出的日期 / 主题
  · 是否存在 `Re:` 跟进（= 首封之后发过第二封）
再据此把客户分成三类：
  A 真逾期未跟（最近一次发出 = 首封，且日期已过应跟进日）
  B 已跟过但表格没推进（有 Re: 且日期已覆盖应跟进日）
  C 首封都没发出（查不到任何记录）
"""

import importlib.util
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl

ROOT = Path(Path(__file__).resolve().parents[1])
XLSX = ROOT / "开发信项目/工作区/开发信跟进表.xlsx"
TODAY = "2026-10-01"
TERMINAL = {"已成交", "已退订（对方拒联）", "已放弃", "已退信", "个人处理", "无回应"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
BJ = timezone(timedelta(hours=8))


def load_mailer():
    spec = importlib.util.spec_from_file_location("mailer", ROOT / "邮箱客户端.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mailer"] = mod
    spec.loader.exec_module(mod)
    return mod


def due_rows():
    wb = openpyxl.load_workbook(XLSX)
    out = []
    for ws in wb.worksheets:
        for r in range(5, ws.max_row + 1):
            n = ws.cell(r, 1).value
            if n is None:
                continue
            nxt = str(ws.cell(r, 15).value or "")
            status = str(ws.cell(r, 13).value or "")
            if nxt in ("", "None", "—") or nxt > TODAY or status in TERMINAL:
                continue
            raw = str(ws.cell(r, 12).value or "")
            emails = [e.lower() for e in EMAIL_RE.findall(raw)]
            out.append(dict(num=n, sheet=ws.title, row=r,
                            name=str(ws.cell(r, 3).value or ""),
                            region=str(ws.cell(r, 4).value or ""),
                            status=status, cnt=ws.cell(r, 14).value,
                            nxt=nxt, last=str(ws.cell(r, 16).value or ""),
                            raw_email=raw, emails=emails))
    return out


def main():
    rows = due_rows()
    print(f"到期/逾期（≤ {TODAY}，非终态）：{len(rows)} 家\n")

    mc = load_mailer()
    cfg = mc.load_config()
    m = mc.imap_connect(cfg)
    m.select('"Sent Messages"', readonly=True)
    typ, d = m.search(None, "ALL")
    ids = d[0].split()
    print(f"Sent Messages 共 {len(ids)} 封，读取头部…")

    by_domain = defaultdict(list)   # domain -> [(date, to, subject)]
    for num in ids:
        raw = mc.fetch_headers(m, num, "TO CC SUBJECT DATE")
        to = mc.raw_header(raw, "To")
        cc = mc.raw_header(raw, "CC")
        subj = mc.raw_header(raw, "Subject")
        date = mc.raw_header(raw, "Date")
        for e in set(x.lower() for x in EMAIL_RE.findall(to + " " + cc)):
            by_domain[e.split("@")[-1]].append((date, e, subj))
    m.logout()
    print(f"覆盖 {len(by_domain)} 个域\n")

    cls = {"A 真逾期未跟": [], "B 已跟过(表格没推进)": [], "C 首封都没发": [], "D 无法判定": []}
    for x in rows:
        hits = []
        for e in x["emails"]:
            hits += [(dt, ad, sj) for (dt, ad, sj) in by_domain.get(e.split("@")[-1], [])
                     if ad == e or ad.split("@")[-1] == e.split("@")[-1]]
        # 去重 + 按日期排序
        seen, uniq = set(), []
        for dt, ad, sj in hits:
            k = (ad, sj)
            if k in seen:
                continue
            seen.add(k)
            uniq.append((dt, ad, sj))
        uniq.sort()
        x["sent"] = uniq
        if not uniq:
            cls["C 首封都没发"].append(x)
            continue
        n_re = sum(1 for _, _, sj in uniq if sj.lower().startswith("re:"))
        x["n_re"] = n_re
        last = uniq[-1][0][:16]
        if n_re >= 1:
            cls["B 已跟过(表格没推进)"].append(x)
        else:
            cls["A 真逾期未跟"].append(x)

    for k in cls:
        print(f"=== {k}：{len(cls[k])} 家 ===")
        for x in sorted(cls[k], key=lambda y: (y["nxt"], y["num"])):
            extra = ""
            if x.get("sent"):
                extra = f"｜实测最近 {x['sent'][-1][0][:16]}（Re: {x.get('n_re',0)} 封）"
            print(f"  #{x['num']:<5} 应跟 {x['nxt']}  次数={x['cnt']}  最后={x['last']:<11} "
                  f"{x['name'][:26]:<28}{x['emails'][:2]}{extra}")
        print()

    (ROOT / ".workbuddy-ai/跟进实况核对.json").write_text(
        json.dumps({k: [{kk: vv for kk, vv in x.items() if kk != "sent"} |
                        {"sent_last": (x["sent"][-1][0] if x.get("sent") else None)}
                        for x in v] for k, v in cls.items()},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写 .workbuddy-ai/跟进实况核对.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
