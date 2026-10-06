#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发信发送器（企业微信邮箱通道）
================================
读 `发信草稿/发送清单.csv`，逐封调用 `wecom-cli mail send` 发送。

安全设计（默认最保守）：
  1. **默认只做本地校验（dry-run）**，必须显式加 `--send` 才真正发送
  2. 正文里若仍有【待填…】占位符 → **拒绝发送**（除非加 --force）
  3. 逐封发送，默认间隔 90 秒，避免触发风控
  4. 全程写发送日志，失败不重试、继续下一封（失败原因如实记录）
  5. 需要交互确认：不加 --yes 时，发送前打印清单并要求输入 yes

用法：
  python3 发送草稿.py                          # 本地校验全部
  python3 发送草稿.py --test {{CONTACT_EMAIL}}   # 只做自测：把第 1 封发给自己
  python3 发送草稿.py --send --ids 1,2,3 --yes # 发指定几封
  python3 发送草稿.py --send --prio A --yes    # 发全部 A 级
  python3 发送草稿.py --send --ids 1-5 --yes --interval 120
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIST_CSV = ROOT / "发信草稿" / "发送清单.csv"
LOG_CSV = ROOT / "发信草稿" / "发送日志.csv"
# node 可执行文件目录（wecom-cli 用）。未设置则不改 PATH，走系统默认查找。
BIN_DIR = os.environ.get("JZP_NODE_BIN", "")
PLACEHOLDER = "【待填"


def run_cli(args: list, dry_run: bool) -> tuple:
    """调用 wecom-cli，返回 (成功?, 输出文本)。"""
    env = dict(os.environ)
    if BIN_DIR:
        env["PATH"] = f"{BIN_DIR}:{env.get('PATH', '')}"
    cmd = ["wecom-cli", "mail", "send"]
    if dry_run:
        cmd.append("--dry-run")
    cmd += args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
        return p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return False, "调用超时（180s）"


def parse_ids(spec: str) -> set:
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(str(i).zfill(2) for i in range(int(a), int(b) + 1))
        else:
            out.add(part.zfill(2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="真正发送（不加则只做本地校验）")
    ap.add_argument("--test", metavar="EMAIL", help="自测模式：把第 1 封发到这个地址（通常是自己的邮箱）")
    ap.add_argument("--ids", help="指定序号，如 1,2,3 或 1-5")
    ap.add_argument("--prio", help="按优先级筛选，如 A")
    ap.add_argument("--interval", type=int, default=90, help="每封间隔秒数，默认 90")
    ap.add_argument("--limit", type=int, help="最多发多少封")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    ap.add_argument("--force", action="store_true", help="即使正文仍有【待填】占位符也发送（不建议）")
    args = ap.parse_args()

    if not LIST_CSV.exists():
        print(f"找不到 {LIST_CSV}\n请先运行：python3 生成草稿.py")
        return 1

    rows = list(csv.DictReader(LIST_CSV.open(encoding="utf-8-sig")))

    # ---- 自测模式 ----
    if args.test:
        rows = rows[:1]
        for r in rows:
            r["邮箱"] = args.test
        print(f"自测模式：把第 1 封（{rows[0]['公司']}）发到 {args.test}\n")

    # ---- 筛选 ----
    else:
        if args.ids:
            keep = parse_ids(args.ids)
            rows = [r for r in rows if r["序号"] in keep]
        if args.prio:
            rows = [r for r in rows if r["优先级"] == args.prio]
        if args.limit:
            rows = rows[:args.limit]

    if not rows:
        print("没有匹配的草稿。")
        return 1

    # ---- 占位符检查 ----
    blocked = []
    for r in rows:
        body = Path(r["正文文件"]).read_text(encoding="utf-8")
        if PLACEHOLDER in body or PLACEHOLDER in r["主题"]:
            blocked.append(r["序号"])

    if blocked and not args.force:
        print("⛔ 以下草稿的正文或主题里仍有【待填…】占位符，已阻止发送：")
        print("   " + "、".join(blocked))
        print()
        print("   解决：编辑 生成草稿.py 顶部的 CONFIG，填好 SENDER_NAME / SENDER_EMAIL /")
        print("        SENDER_PHONE / LEAD_TIME，重跑 python3 生成草稿.py")
        print("   确实要强发（不建议）：加 --force")
        return 2

    dry = not args.send
    mode = "本地校验（不发送）" if dry else "★ 真实发送 ★"
    print(f"模式：{mode}")
    print(f"待处理：{len(rows)} 封，间隔 {args.interval} 秒")
    print()

    if not dry and not args.yes:
        print("即将发送：")
        for r in rows:
            print(f"  {r['序号']}  {r['国家']:4}  {r['公司'][:36]:36}  → {r['邮箱']}")
        print()
        ans = input("确认发送请输入 yes：").strip().lower()
        if ans != "yes":
            print("已取消。")
            return 1

    log_path = LOG_CSV
    write_header = not log_path.exists()
    log_f = log_path.open("a", encoding="utf-8-sig", newline="")
    log_w = csv.writer(log_f)
    if write_header:
        log_w.writerow(["时间", "序号", "国家", "公司", "收件人", "邮箱", "主题", "结果", "说明"])

    ok_n = fail_n = 0
    for i, r in enumerate(rows, 1):
        payload = {
            "to": {"emails": [r["邮箱"]]},
            "subject": r["主题"],
            "file_path": r["正文文件"],
            "content_type": "html",     # v2：正文为 HTML，以便携带企业签名
        }
        cli_args = ["--json", json.dumps(payload, ensure_ascii=False)]

        print(f"[{i}/{len(rows)}] {r['序号']} {r['公司'][:40]} → {r['邮箱']}")

        success, out = run_cli(cli_args, dry)

        if dry:
            # dry-run 只验证请求能否构造，返回体是请求预览
            ok = '"url": "/mail/send"' in out
            print("     本地校验：" + ("通过" if ok else "失败"))
            log_w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r["序号"],
                            r["国家"], r["公司"], r["收件人"], r["邮箱"], r["主题"],
                            "dry-run-通过" if ok else "dry-run-失败",
                            "" if ok else out[:300].replace("\n", " ")])
            log_f.flush()
            ok_n += ok
            fail_n += (not ok)
            continue

        # 真实发送
        if success and '"errcode"' not in out:
            print("     ✅ 已发送")
            log_w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r["序号"],
                            r["国家"], r["公司"], r["收件人"], r["邮箱"], r["主题"],
                            "成功", ""])
            ok_n += 1
        else:
            # 解析 error.message / error.instruction
            msg = instr = ""
            try:
                j = json.loads(out)
                err = j.get("error") or j
                msg = err.get("message") or err.get("errmsg") or ""
                instr = err.get("instruction") or err.get("help_message") or ""
            except Exception:
                msg = out[:300].replace("\n", " ")
            print(f"     ❌ 失败：{msg[:120]}")
            if instr:
                print(f"        建议：{instr[:200]}")
            log_w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r["序号"],
                            r["国家"], r["公司"], r["收件人"], r["邮箱"], r["主题"],
                            "失败", f"{msg} | {instr}"[:500]])
            fail_n += 1
        log_f.flush()

        if i < len(rows):
            time.sleep(args.interval)

    log_f.close()

    print()
    print(f"完成：成功 {ok_n} / 失败 {fail_n}")
    print(f"日志：{log_path}")
    if fail_n and not dry:
        print("\n⚠️ 有失败项。请查看日志里的失败原因，不要盲目重试——")
        print("   若是权限类错误（如 851008），需先在企业微信侧申请对应能力。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
