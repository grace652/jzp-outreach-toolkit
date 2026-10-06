#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
9/30 跟进信 · 独立队列构建
==========================
把 `开发信项目/clients/开发信-跟进-*.md`（本批 11 封）构建成**独立队列**
`发信队列-跟进0930.json`，供 `定时发送.py --daemon --queue` 消费。

为什么不直接用 `定时发送.py --build`
------------------------------------
`--build` 会把投递时刻算成「收件人当地 09:00–10:00」对应的北京时刻。
但**用户 2026-10-01 授权本批破例**：按北京时间排 10/1 凌晨发出。

🔴 **项目铁律不改**（`项目流程-邮件开发.md` §2.1 与 `定时发送.py` 的窗口逻辑保持原样）——
本脚本只在**队列里写死 `scheduled_at_bj`** 来实现这次一次性例外。

依据：已通读 `定时发送.py:cmd_daemon`（L965–1027），守护进程投递时
**不复检时区窗口**，只做「等到 scheduled_at_bj → 重读队列 → 查退信黑名单 → 投递」。

用法
----
  python3 构建跟进队列-0930.py            # 构建队列
  python3 构建跟进队列-0930.py --dry-run  # 只校验，不落盘
"""

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENTS = ROOT / "开发信项目" / "clients"
QUEUE = ROOT / "发信队列-跟进0930.json"
BJ = timezone(timedelta(hours=8))


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------
# 排程表：北京时刻由用户指定（本批破例），当地时刻仅作记录
# tz 代号与 `定时发送.py` 的 TZ_OFFSET_DST 对齐；UAE 是本脚本新增（仅记录用）
# ---------------------------------------------------------------
TZ_OFFSET = {"ET": -4, "CT": -5, "MT": -6, "PT": -7, "AK": -8, "UAE": 4}
TZ_LABEL = {"ET": "美东", "CT": "美中", "MT": "美山", "PT": "美西",
            "AK": "阿拉斯加", "UAE": "阿联酋"}

PLAN = [
    # (slug, tz, 北京时刻, 备注)
    ("Premier-Electric",        "AK",  "2026-10-01 01:00", "当地 9/30 09:00 ✅ 落在合法窗口内"),
    ("{{COMPANY}}", "PT",  "2026-10-01 01:10", "当地 9/30 10:10（上午偏晚）"),
    ("{{COMPANY}}",          "PT",  "2026-10-01 01:20", "当地 9/30 10:20"),
    ("{{COMPANY}}",           "PT",  "2026-10-01 01:30", "当地 9/30 10:30"),
    ("Canem",                   "PT",  "2026-10-01 01:40", "当地 9/30 10:40"),
    ("EC-Electric",             "PT",  "2026-10-01 01:50", "当地 9/30 10:50"),
    ("{{COMPANY}}",          "PT",  "2026-10-01 02:00", "当地 9/30 11:00"),
    ("{{COMPANY}}",             "PT",  "2026-10-01 02:10", "当地 9/30 11:10"),
    ("{{COMPANY}}",         "ET",  "2026-10-01 02:20", "⚠️ 当地 9/30 13:20（破例代价）"),
    ("{{COMPANY}}",            "ET",  "2026-10-01 02:30", "⚠️ 当地 9/30 13:30（破例代价）"),
    ("{{COMPANY}}",            "UAE", "2026-10-01 13:00", "当地 10/1 09:00 ✅ 单独排其合法窗口"),
]


def mx_ok(av, addr: str, retries: int = 3):
    """MX 校验（与 `定时发送.py:cmd_build` 同口径：MX 类失败重试 3 次）。"""
    for i in range(retries):
        r = av.verify(addr, do_probe=False, polite_delay=0)
        if r["verdict"].startswith("⛔") and "MX" in " ".join(r["notes"]):
            if i < retries - 1:
                continue
        return r
    return r


def main():
    ap = argparse.ArgumentParser(description="9/30 跟进信独立队列构建")
    ap.add_argument("--dry-run", action="store_true", help="只校验，不落盘")
    args = ap.parse_args()

    sd = _load("sd", "发送开发信.py")
    av = _load("av", "地址验证.py")
    sc = _load("sc", "定时发送.py")

    sig = sd.load_signature()
    BL = sc.load_blacklist()
    now = datetime.now(BJ)

    items, problems = [], []
    print(f"构建队列：{len(PLAN)} 封\n")

    for slug, tz, bj_str, note in PLAN:
        letter = f"开发信-跟进-{slug}.md"
        f = CLIENTS / letter
        if not f.exists():
            problems.append(f"⛔ 信件不存在：{letter}")
            continue

        subs, body, notes = sd.parse_letter(f)
        body = sd.trim_signature_tail(body)
        to = sd.recipients_of(notes)
        cc = sd.cc_of(notes)
        wc = len(body.split())

        # ---- 逐项校验 ----
        errs = []
        if not subs:
            errs.append("取不到主题行")
        if not to:
            errs.append("取不到收件人（检查 `- **收件人**：…（`email`）` 那一行）")
        if not (20 <= wc <= 150):
            errs.append(f"词数异常（{wc}）")
        try:
            sd.compliance_check(body, sig, followup=True)
        except SystemExit as e:
            errs.append(f"红线未过：{e}")
        except Exception as e:
            errs.append(f"红线检查异常：{e}")
        for a in to + cc:
            # 🔴 2026-10-05：跟进信走**零退信**口径（strict_followup=True）
            if sc.is_blocked(a, now, BL, strict_followup=True)[0]:
                errs.append(f"退信闸门拦截：{a} — "
                            f"{sc.is_blocked(a, now, BL, strict_followup=True)[1]}")
            mv = mx_ok(av, a)
            if mv["verdict"].startswith("⛔"):
                errs.append(f"MX 校验不通过：{a} — {'; '.join(mv['notes'])}")

        if errs:
            problems.append(f"⛔ {letter}\n     " + "\n     ".join(errs))
            print(f"  ⛔ {slug:<26} {'; '.join(errs)}")
            continue

        # ---- 时刻 ----
        when = datetime.strptime(bj_str, "%Y-%m-%d %H:%M").replace(tzinfo=BJ)
        off = TZ_OFFSET[tz]
        local = when.astimezone(timezone(timedelta(hours=off)))
        items.append({
            "letter": letter,
            "to": to,
            "cc": cc,
            "subject": subs[0],
            "tz": tz,
            "local_label": TZ_LABEL[tz],
            # 窗口字段仅作记录（守护进程投递时不复检窗口）
            "window_start_bj": f"{bj_str}",
            "window_end_bj": f"{bj_str}",
            "window_start_local": local.strftime("%Y-%m-%d %H:%M"),
            "window_end_local": local.strftime("%Y-%m-%d %H:%M"),
            "dst": True,
            "status": "pending",
            "blocked_reason": "",
            "queued_at": now.strftime("%Y-%m-%d %H:%M"),
            "sent_at": None,
            "scheduled_at_bj": bj_str,
            "scheduled_at_local": local.strftime("%Y-%m-%d %H:%M"),
            "_note": note,
        })
        print(f"  ✅ {slug:<26} {bj_str} → 当地 {local:%m-%d %H:%M}  "
              f"{','.join(to)}" + (f" cc {','.join(cc)}" if cc else "") + f"  [{wc} 词]")

    print()
    if problems:
        print("发现问题：")
        for p in problems:
            print("  " + p)
        print()

    # 同一分钟去重
    seen = {}
    for i in items:
        k = i["scheduled_at_bj"]
        if k in seen:
            print(f"⚠️ 同一时刻两封：{seen[k]} 与 {i['letter']}（{k}）")
        seen[k] = i["letter"]

    if args.dry_run:
        print(f"（--dry-run）可入队 {len(items)} 封，未落盘。")
        return 0

    if problems:
        print("⛔ 存在校验问题，**拒绝落盘**（修好再跑）。")
        return 1

    QUEUE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已写 {QUEUE.name}：{len(items)} 封")
    print(f"   最早 {items[0]['scheduled_at_bj']} ／ 最晚 {max(i['scheduled_at_bj'] for i in items)}（北京）")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
