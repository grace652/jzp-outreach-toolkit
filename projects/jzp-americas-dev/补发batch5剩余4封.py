#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补发 batch5 剩余 4 封（美西）
============================

背景
----
2026-09-28 batch5 共 21 封，其中 17 封已投递。
剩余 4 封（全部美西）在 23:51:57 因 `发信队列.json` 被**另一个并发会话**
整体覆盖为「跟进信队列」而未能发出。

设计目标：**与并发会话零冲突**
------------------------------
1. 使用**独立队列文件** `发信队列-batch5剩余.json`，绝不读写 `发信队列.json`。
2. 不启动守护进程、不碰 `.daemon.lock`（该锁属于另一会话的守候进程）。
3. 只读信件原文与黑名单，只写自己的队列文件与日志。
4. 幂等：已 status=sent 的跳过，中断后重跑不会重发。

用法
----
  python3 补发batch5剩余4封.py --status
  python3 补发batch5剩余4封.py --run --send --yes
"""

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENTS = ROOT / "开发信项目" / "clients"

# 🔴 本脚本专属队列——与并发会话的 发信队列.json 完全隔离
QUEUE = ROOT / "发信队列-batch5剩余.json"
LOG = ROOT / "补发日志-batch5剩余4封.log"

BJ = timezone(timedelta(hours=8))

# 4 封待补发的信（来源：发信队列-batch5备份.json 的 pending 项，逐字照抄）
SEED = [
    {
        "letter": "开发信-{{COMPANY}}.md",
        "to": ["{{CONTACT_EMAIL}}"],
        "subject": "Transformer supply — British Columbia",
        "local_label": "美西",
        "scheduled_at_bj": "2026-09-29 00:05",
        "window_end_bj": "2026-09-29 01:00",
    },
    {
        "letter": "开发信-{{COMPANY}}.md",
        "to": ["{{CONTACT_EMAIL}}"],
        "subject": "Transformer supply — British Columbia",
        "local_label": "美西",
        "scheduled_at_bj": "2026-09-29 00:20",
        "window_end_bj": "2026-09-29 01:00",
    },
    {
        "letter": "开发信-TN-Electrical.md",
        "to": ["{{CONTACT_EMAIL}}"],
        "subject": "Transformer supply — British Columbia",
        "local_label": "美西",
        "scheduled_at_bj": "2026-09-29 00:35",
        "window_end_bj": "2026-09-29 01:00",
    },
    {
        "letter": "开发信-{{COMPANY}}.md",
        "to": ["{{CONTACT_EMAIL}}"],
        "subject": "Transformer supply — British Columbia",
        "local_label": "美西",
        "scheduled_at_bj": "2026-09-29 00:50",
        "window_end_bj": "2026-09-29 01:00",
    },
]


def load_sender():
    """复用 定时发送.py 的模块加载器与黑名单逻辑（该文件带 __main__ 守卫，导入无副作用）。"""
    spec = importlib.util.spec_from_file_location("ds_sched", ROOT / "定时发送.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ds_sched"] = mod
    spec.loader.exec_module(mod)
    return mod


def read_queue():
    if not QUEUE.exists():
        items = []
        for i, e in enumerate(SEED):
            items.append({
                **e,
                "status": "pending",
                "sent_at": None,
                "error": "",
                "queued_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"),
            })
        write_queue(items)
        return items
    return json.loads(QUEUE.read_text(encoding="utf-8"))


def write_queue(items):
    QUEUE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def log(msg):
    line = f"[{datetime.now(BJ).strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def cmd_status(ds, items):
    print(f"队列文件：{QUEUE.name}（与并发会话的 发信队列.json 隔离）")
    now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    print(f"当前北京时间：{now}\n")
    for i in items:
        due = "已到点" if i["scheduled_at_bj"] <= now else "未到点"
        print(f"  {i['status']:<8} {i['scheduled_at_bj']}  {due:<6}  "
              f"{i['local_label']}  {','.join(i['to'])}")
        if i.get("sent_at"):
            print(f"            └ 实际发出 {i['sent_at']}")
        if i.get("error"):
            print(f"            └ 错误 {i['error']}")
    pend = sum(1 for i in items if i["status"] == "pending")
    sent = sum(1 for i in items if i["status"] == "sent")
    print(f"\n合计：待发 {pend} / 已发 {sent} / 共 {len(items)}")
    return 0


def cmd_run(ds, args, items):
    now = datetime.now(BJ)
    nows = now.strftime("%Y-%m-%d %H:%M")
    due = [i for i in items
           if i["status"] == "pending" and i["scheduled_at_bj"] <= nows]
    if not due:
        nxt = min((i["scheduled_at_bj"] for i in items
                   if i["status"] == "pending"), default=None)
        print(f"当前 {nows}，没有到点的信。")
        if nxt:
            print(f"下一封的计划时刻：{nxt}")
        return 0

    if not args.send:
        print(f"当前 {nows}　【预演】到点待发 {len(due)} 封（未加 --send）")
        for i in due:
            print(f"  {i['scheduled_at_bj']} → {','.join(i['to'])}")
        return 0

    sd = ds.load_sd()
    mailer = sd.load_mailer()
    cfg = mailer.load_config()
    sig = sd.load_signature()
    BL = ds.load_blacklist()

    okn = badn = 0
    for i in due:
        f = CLIENTS / i["letter"]
        if not f.exists():
            i["status"] = "failed"
            i["error"] = f"信件文件不存在：{f.name}"
            log(f"❌ {f.name}：信件文件不存在")
            badn += 1
            write_queue(items)
            continue

        blocked = False
        for a in i["to"]:
            hit, why = ds.is_blocked(a, datetime.now(BJ), BL)
            if hit:
                i["status"] = "skipped"
                i["error"] = why
                log(f"⛔ 跳过 {i['letter']}：{a} — {why}")
                blocked = True
                break
        if blocked:
            write_queue(items)
            continue

        subjects, body, notes = sd.parse_letter(f)
        body = sd.trim_signature_tail(body)
        html = sd.build_html(body, sig)
        to = i["to"]
        subject = subjects[0] if subjects else i["subject"]
        msg = mailer.build_message(cfg, to, subject, html=html, inline=True,
                                   cc=None)
        ok, err = mailer.smtp_send(cfg, msg, to)
        stamp = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            i["status"] = "sent"
            i["sent_at"] = stamp
            log(f"✅ [{stamp}] {i['letter']} → {', '.join(to)}")
            okn += 1
        else:
            i["status"] = "failed"
            i["error"] = str(err)
            log(f"❌ [{stamp}] {i['letter']} → {', '.join(to)}：{err}")
            badn += 1
        write_queue(items)

    print(f"\n完成：成功 {okn} / 失败 {badn}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="补发 batch5 剩余 4 封（独立队列）")
    ap.add_argument("--run", action="store_true", help="发送已到点的信")
    ap.add_argument("--send", action="store_true", help="--run 时真正发送")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    ap.add_argument("--status", action="store_true", help="查看队列")
    args = ap.parse_args()

    ds = load_sender()
    items = read_queue()

    if args.status or not args.run:
        return cmd_status(ds, items)
    if not args.yes:
        print("需要 --yes 才执行发送。")
        return 1
    return cmd_run(ds, args, items)


if __name__ == "__main__":
    sys.exit(main() or 0)
