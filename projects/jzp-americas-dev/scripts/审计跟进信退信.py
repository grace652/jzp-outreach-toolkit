#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计：**二次及以上跟进信是否出现退信**
=============================================
用户规则（2026-10-05）：**二次及以上发送的跟进信，不要出现退信。**

本脚本做两件事：
  ① **回溯审计** —— 拿退信黑名单 × 发件箱实测，找出「首退之后仍发出」的信
     （即：某地址已经退过信，我们却又发了一次 —— 这是规则的直接违反）
  ② **前置预检** —— 给定一批收件人（或直接读跟进队列），按
     `定时发送.is_blocked(..., strict_followup=True)` 预判会不会被拦

只读，不发送任何东西。

用法
----
  python3 审计跟进信退信.py                 # 回溯审计
  python3 审计跟进信退信.py --queue 发信队列-跟进1002.json
  python3 审计跟进信退信.py --check {{CONTACT_EMAIL}} {{CONTACT_EMAIL}}
"""

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BJ = timezone(timedelta(hours=8))
SENT = ROOT / ".workbuddy-ai/已发送全量.json"
BL_FILE = ROOT / "退信黑名单.json"

_DATE_FMTS = ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M %z",
              "%d %b %Y %H:%M:%S %z")


def load_ds():
    """加载 定时发送.py（只取闸门函数，不跑 main）。"""
    spec = importlib.util.spec_from_file_location("ds", ROOT / "定时发送.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ds"] = mod
    spec.loader.exec_module(mod)
    return mod


def parse_dt(s):
    s = re.sub(r"\s*\([^)]*\)\s*$", "", (s or "").strip())
    for f in _DATE_FMTS:
        try:
            dt = datetime.strptime(s, f)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def audit():
    ds = load_ds()
    if not SENT.exists():
        print(f"缺少 {SENT}，先跑 scripts/导出已发送全量.py")
        return 1
    sent = json.loads(SENT.read_text(encoding="utf-8"))
    bl = json.loads(BL_FILE.read_text(encoding="utf-8")) if BL_FILE.exists() else []
    rows = sorted([(parse_dt(r["date"]), r) for r in sent if parse_dt(r["date"])],
                  key=lambda x: x[0])

    def key_of(addr: str) -> str:
        """客户键：公共邮箱域按**完整地址**，其余按**域名**（与项目口径一致）。

        🔴 必须按域聚合，否则会漏判：
          实测 `{{COMPANY_DOMAIN}}` 退的是 `{{CONTACT_EMAIL}}`，跟进却发给了同域 `{{CONTACT_EMAIL}}` ——
          只看精确地址会得出「该地址只发过 1 次、不构成违规」的**假阴性**。
        """
        dom = addr.split("@")[-1].lower()
        return addr.lower() if dom in ds.PUBLIC_MAIL_DOMAINS else dom

    # 每个客户键的「首退日」
    first_bounce = {}
    for e in bl:
        a = (e.get("address") or "").lower()
        if not a or "@" not in a:
            continue
        d = parse_dt(e.get("first_date", ""))
        if d is None:
            continue
        k = key_of(a)
        if k not in first_bounce or d < first_bounce[k]:
            first_bounce[k] = d

    print("=" * 84)
    print("① 回溯审计：退信客户 × 发件箱实测 —— 找出「首退之后仍发出」的信")
    print("=" * 84)
    viol = []
    for k, fd in sorted(first_bounce.items()):
        hits = [(t, r) for t, r in rows
                if any(key_of(x) == k for x in r["to"])]
        if len(hits) < 2:
            continue
        for t, r in hits[1:]:                     # 第 2 封起 = 二次及以上
            if t > fd:
                viol.append((k, fd, t, r))
    viol.sort(key=lambda x: x[2])
    if not viol:
        print("\n✅ 未发现「退信后仍发出」的记录。")
    else:
        print(f"\n⛔ 命中 {len(viol)} 封（= 二次及以上跟进信落在了已退信客户上）：\n")
        for k, fd, t, r in viol:
            rnd = "跟进信" if re.match(r"^\s*(re|fw|fwd)\s*[:：]", r["subject"], re.I) else "非 Re: 触达"
            print(f"  ⛔ {k}")
            print(f"     首退：{fd:%Y-%m-%d}")
            print(f"     违规发出：{t:%Y-%m-%d %H:%M}（{rnd}）  →  {', '.join(r['to'])}")
            print(f"     主题：{r['subject'][:76]}")
            print()

    print("=" * 84)
    print("② 现行闸门复检：这些客户现在还会不会被放行？")
    print("=" * 84)
    now = datetime.now(BJ)
    blmap = ds.load_blacklist()
    for k, fd, t, r in viol:
        print(f"\n  {k}   实际投递地址：{', '.join(r['to'])}")
        for a in r["to"]:
            b1, w1 = ds.is_blocked(a, now, blmap)                        # 首封口径
            b2, w2 = ds.is_blocked(a, now, blmap, strict_followup=True)  # 跟进口径
            print(f"     {a}")
            print(f"        首封口径：{'⛔ 拦截' if b1 else '✅ 放行'}  {w1[:60]}")
            print(f"        跟进口径：{'⛔ 拦截' if b2 else '✅ 放行'}  {w2[:60]}")
    print(f"\n汇总：历史违规 {len(viol)} 封 ｜ 黑名单 {len(bl)} 条")
    return 0


def check(addrs, queue=None):
    ds = load_ds()
    now = datetime.now(BJ)
    blmap = ds.load_blacklist()
    if queue:
        q = json.loads(Path(queue).read_text(encoding="utf-8"))
        items = q if isinstance(q, list) else q.get("items", [])
        print(f"队列 {queue}：{len(items)} 项\n")
        n = 0
        for it in items:
            if it.get("status") not in (None, "pending"):
                continue
            fu = ds.is_followup_item(it)
            for a in (it.get("to") or []):
                b, why = ds.is_blocked(a, now, blmap, strict_followup=fu)
                if b:
                    n += 1
                    print(f"  ⛔ [{ '跟进' if fu else '首封'}] {it.get('letter','?')[:34]:36} {a}")
                    print(f"       {why}")
        print(f"\n拦截 {n} 项")
        return 0
    print(f"预检 {len(addrs)} 个地址（跟进口径）：\n")
    for a in addrs:
        b, why = ds.is_blocked(a, now, blmap, strict_followup=True)
        print(f"  {'⛔ 拦截' if b else '✅ 放行'}  {a:40} {why[:60]}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="跟进信退信审计")
    ap.add_argument("--queue", help="按跟进队列预检")
    ap.add_argument("--check", nargs="*", help="按地址预检")
    a = ap.parse_args()
    if a.queue or a.check:
        return check(a.check or [], a.queue)
    return audit()


if __name__ == "__main__":
    sys.exit(main())
