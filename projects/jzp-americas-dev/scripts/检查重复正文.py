#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重复正文闸门：同一封信件文件，不得对同一收件人发第二次
=============================================================
🔴 事故（2026-10-05）
    `开发信-跟进-XXX.md` 这批文件是**已经发过的第 1 轮跟进信**（09-28/09-29 投出）。
    我在 10-05 直接复用它们排程 → **同一封信对同一收件人发了第二遍**。
    实测逐字相同：`{{CONTACT_EMAIL}}` / `{{CONTACT_EMAIL}}` / `{{CONTACT_EMAIL}}` …

    根因：**只检查了「文件存不存在」，没检查「这封信对这个人发过没有」。**

    `今日跟进名单-20261005.md` 其实写了「第 2 轮需**换角度**，不可重复首封与第 1 轮」——
    这条规则**只写在文档里，没落到代码**。⇒ 又一次验证：
    **写在文档里的规则，不落到代码就等于没有。**

用法
----
  python3 检查重复正文.py --build            # 从所有队列重建登记表
  python3 检查重复正文.py --check <队列.json>  # 预检某队列
  python3 检查重复正文.py --show             # 看登记表摘要
"""
import argparse, glob, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / ".workbuddy-ai/已用信件登记.json"


def build():
    """从全部 发信队列*.json 重建 {信件文件: {收件人: [发出日期]}}"""
    reg = {}
    files = [p for p in ROOT.glob("发信队列*.json") if ".bak" not in p.name]
    for p in files:
        try:
            q = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(q, list):
            continue
        for it in q:
            if it.get("status") != "sent":
                continue
            letter = it.get("letter") or ""
            # 🔴 只认**真实发出时刻**（sent_at）。缺 sent_at 的 sent 项回退 scheduled_at_bj。
            #    绝不能拿 pending 项的 scheduled_at_bj 当「已发」—— 会把「计划」记成「事实」，
            #    导致闸门把自己的计划误判为重复（本次踩过）。
            when = (it.get("sent_at") or it.get("scheduled_at_bj") or "")[:10]
            for a in (it.get("to") or []):
                reg.setdefault(letter, {}).setdefault(a.lower(), []).append(when)
    for k in reg:
        for a in reg[k]:
            reg[k][a] = sorted(set(reg[k][a]))
    REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(v) for v in reg.values())
    print(f"✅ 登记表重建：{len(reg)} 个信件文件 / {n} 个（信件×收件人）组合 → {REG}")
    print("   ⚠️ 本表只覆盖**有队列记录**的发送；更早的手工发送不在内。")
    return 0


def check(queue):
    if not REG.exists():
        print("⚠️ 登记表不存在，先跑 --build"); return 1
    reg = json.loads(REG.read_text(encoding="utf-8"))
    q = json.loads(Path(queue).read_text(encoding="utf-8"))
    items = q if isinstance(q, list) else q.get("items", [])
    dup = []
    for it in items:
        if it.get("status") not in (None, "pending"):
            continue
        letter = it.get("letter") or ""
        for a in (it.get("to") or []):
            prev = reg.get(letter, {}).get(a.lower())
            if prev:
                dup.append((letter, a, prev))
    print(f"队列 {queue}：{len(items)} 项")
    if not dup:
        print("  ✅ 无重复（同一封信未对同一收件人发过）")
        return 0
    print(f"  🔴 发现 {len(dup)} 项重复：\n")
    for letter, a, prev in dup:
        print(f"    ⛔ {letter}")
        print(f"       收件人 {a} 已于 {', '.join(prev)} 收到过**同一封信件文件**")
    print("\n  ⇒ 处置：为该客户**新写一封（换角度）**，不要复用已发过的文件。")
    return 1


def show():
    if not REG.exists():
        print("登记表不存在"); return 1
    reg = json.loads(REG.read_text(encoding="utf-8"))
    rows = sorted(((l, a, d) for l, m in reg.items() for a, d in m.items()),
                  key=lambda x: x[2][-1], reverse=True)
    print(f"登记表共 {len(rows)} 条（信件×收件人）\n")
    for l, a, d in rows[:40]:
        print(f"  {d[-1]} | {a:38} | {l}")
    if len(rows) > 40:
        print(f"  …（共 {len(rows)} 条）")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.build: sys.exit(build())
    if a.check: sys.exit(check(a.check))
    if a.show: sys.exit(show())
    ap.print_help()
