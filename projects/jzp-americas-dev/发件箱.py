#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发件箱处理器（发送层）
======================
给「写作 agent」准备的稳定接入点。

分工约定
--------
  写作 agent  →  只负责写**正文**，产出 JSON 丢进 `发件箱/`
  发送层（本脚本） →  自动附加企业签名、内嵌图片、发送、归档、记日志

这样写作 agent 不需要懂邮件协议、不需要管签名和图片、不需要处理重试，
只专注把信写好。

用法
----
  python3 发件箱.py                    # 列出待发（默认不发送）
  python3 发件箱.py --check            # 只做格式校验
  python3 发件箱.py --send             # 真正发送（需输入 yes 确认）
  python3 发件箱.py --send --yes       # 跳过交互确认
  python3 发件箱.py --send --limit 3   # 只发前 3 封（小批量试水）
  python3 发件箱.py --interval 120     # 每封间隔秒数，默认 90

目录约定
--------
  发件箱/                  ← 待发 JSON 放这里
  发件箱/_已发送/          ← 发送成功的 JSON 自动移到这里
  发件箱/_失败/            ← 失败的移到这里，并在同目录生成 .error.txt
  发件箱/发送日志.csv      ← 逐封记录

JSON 契约见 `发件箱/README.md`
"""

import argparse
import csv
import importlib.util
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTBOX = ROOT / "发件箱"
DONE = OUTBOX / "_已发送"
FAILED = OUTBOX / "_失败"
LOG = OUTBOX / "发送日志.csv"

PLACEHOLDER = "【待填"

REQUIRED = ("to", "subject")


def load_mailer():
    """复用 邮箱客户端.py 的发送能力，避免重复实现。"""
    spec = importlib.util.spec_from_file_location("mailer", ROOT / "邮箱客户端.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mailer"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_typography():
    """加载**唯一**的正文排版模块（字体 Arial / 11pt / 强调加粗）。

    🔴 2026-09-28：字体与加粗规则收敛到 `邮件排版.py` 一处定义，
    本文件不再硬编码 font-family / font-size。
    """
    spec = importlib.util.spec_from_file_location("typo", ROOT / "邮件排版.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["typo"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_signature():
    """HTML 签名（含 cid 图片）—— 用于 HTML 正文。"""
    inline = ROOT / "签名_内嵌版.html"
    remote = ROOT / "签名.html"
    f = inline if inline.exists() else remote
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def load_text_signature():
    """纯文本签名 —— 用于纯文本正文（开发信项目口径）。

    正文止于 `{{SENDER_NAME}}`，之后两行由此自动追加。见
    `开发信项目/07_正文与签名格式.md`。
    """
    f = ROOT / "开发信项目" / "签名_纯文本.txt"
    if not f.exists():
        return ""
    return f.read_text(encoding="utf-8").strip()


def is_html(s: str) -> bool:
    return bool(re.search(r"<(p|div|br|table|ul|li|html|body)\b", s, re.I))


def build_html(body: str, signature: str, wrap: bool) -> str:
    """wrap=True 时给正文加统一字体样式，再拼签名。

    🔴 2026-09-28 统一：字体（Arial）/ 字号（11pt）取自 `邮件排版.py`（唯一出处）。
    `body` 若为纯文本，先按规范转 HTML（含强调加粗）再套样式。
    """
    T = load_typography()
    if not signature:
        return body
    if wrap:
        if not is_html(body):
            body = T.text_to_html(body)
        body = T.wrap(body)
    return (f'{body}\n'
            f'{T.SIGNATURE_GAP}\n'
            f'{signature}\n')


def resolve(p, base):
    """相对路径按发件箱目录解析。"""
    if not p:
        return None
    q = Path(p)
    return q if q.is_absolute() else (base / q)


def validate(d: dict, path: Path) -> list:
    errs = []
    for k in REQUIRED:
        if not d.get(k):
            errs.append(f"缺少必填字段 `{k}`")
    if not (d.get("html") or d.get("html_file")):
        errs.append("必须提供 `html` 或 `html_file` 之一")
    to = d.get("to")
    if to is not None and not isinstance(to, list):
        errs.append("`to` 必须是数组")
    if to and not all("@" in str(x) for x in to):
        errs.append("`to` 里含非邮箱格式的值")
    for key in ("html_file",):
        if d.get(key):
            f = resolve(d[key], path.parent)
            if not f.exists():
                errs.append(f"`{key}` 指向的文件不存在：{f}")
    for a in (d.get("attach") or []):
        f = resolve(a, path.parent)
        if not f.exists():
            errs.append(f"附件不存在：{f}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="发件箱处理器（给写作 agent 的发送层）")
    ap.add_argument("--send", action="store_true", help="真正发送（不加则只列出）")
    ap.add_argument("--check", action="store_true", help="只做格式校验")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    ap.add_argument("--limit", type=int, help="最多处理多少封")
    ap.add_argument("--interval", type=int, default=90, help="每封间隔秒数，默认 90")
    ap.add_argument("--no-inline", action="store_true", help="不内嵌签名图")
    ap.add_argument("--keep", action="store_true", help="发送后不移动 JSON")
    ap.add_argument("--redirect-to", metavar="EMAIL",
                    help="【测试专用】把所有收件人重定向到这个地址，"
                         "无论 JSON 里写的是谁。绝不发给真实客户。")
    args = ap.parse_args()

    if not OUTBOX.exists():
        OUTBOX.mkdir(parents=True, exist_ok=True)
        print(f"已创建发件箱目录：{OUTBOX}")
        print("把写作 agent 产出的 JSON 放进这个目录即可。契约见 发件箱/README.md")
        return 0

    files = sorted(p for p in OUTBOX.glob("*.json"))
    if not files:
        print(f"发件箱是空的：{OUTBOX}")
        print("把写作 agent 产出的 JSON 放进来即可。契约见 发件箱/README.md")
        return 0

    if args.limit:
        files = files[:args.limit]

    mailer = load_mailer()
    cfg = mailer.load_config()
    signature = load_signature()

    # ---------- 校验 ----------
    ok_items, bad_items = [], []
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            bad_items.append((f, [f"JSON 解析失败：{e}"]))
            continue
        errs = validate(d, f)
        if errs:
            bad_items.append((f, errs))
        else:
            ok_items.append((f, d))

    print(f"发件箱：{OUTBOX}")
    print(f"  待发 {len(ok_items)} 封 / 有问题 {len(bad_items)} 封")
    print()

    if bad_items:
        print("⛔ 以下文件有问题，已跳过：")
        for f, errs in bad_items:
            print(f"   {f.name}")
            for e in errs:
                print(f"      - {e}")
        print()

    if args.check:
        return 1 if bad_items else 0

    if not ok_items:
        return 1

    # ---------- 列出 ----------
    print(f"{'#':>3}  {'收件人':38}  主题")
    print("─" * 100)
    for i, (f, d) in enumerate(ok_items, 1):
        meta = d.get("meta") or {}
        tag = f"[{meta.get('priority','')}] " if meta.get("priority") else ""
        print(f"{i:>3}  {mailer.pad(','.join(d['to'])[:36],38)}  {tag}{d['subject'][:50]}")
    print()

    dry = not args.send
    if dry:
        print("（未加 --send，仅列出。确认无误后加 --send 执行）")
        return 0

    if not args.yes:
        if input("确认发送请输入 yes：").strip().lower() != "yes":
            print("已取消。")
            return 1

    # ---------- 发送 ----------
    for d_ in (DONE, FAILED):
        if not d_.exists():
            d_.mkdir(parents=True)
    new_log = not LOG.exists()
    lf = LOG.open("a", encoding="utf-8-sig", newline="")
    lw = csv.writer(lf)
    if new_log:
        lw.writerow(["时间", "文件", "收件人", "主题", "公司", "结果", "说明"])

    okn = badn = 0
    for i, (f, d) in enumerate(ok_items, 1):
        meta = d.get("meta") or {}
        to = list(d["to"])
        cc = list(d.get("cc") or [])
        bcc = list(d.get("bcc") or [])

        # 【安全闸】重定向模式：无论 JSON 写的是谁，只发到指定地址
        original_to = list(to)
        if args.redirect_to:
            to, cc, bcc = [args.redirect_to], [], []
            print(f"     ⚠️  重定向：原收件人 {', '.join(original_to)} "
                  f"→ {args.redirect_to}（未发给真实客户）")

        if d.get("html"):
            body = d["html"]
        else:
            body = resolve(d["html_file"], f.parent).read_text(encoding="utf-8")

        # 按正文类型选签名：HTML → cid 内嵌签名；纯文本 → 纯文本签名
        if is_html(body):
            has_sig = "jiezoupower" in body.lower() and "<table" in body.lower()
            html = body if has_sig else build_html(body, signature, d.get("wrap", True))
            text_body = d.get("text")
        else:
            html = None
            text_body = body.rstrip()
            sig_txt = load_text_signature()
            if sig_txt and "JZPE POWER TRANSFORMER CO., LTD." not in text_body:
                text_body = text_body + "\n\n" + sig_txt

        if PLACEHOLDER in html and not d.get("force"):
            print(f"[{i}/{len(ok_items)}] ⛔ 正文含【待填…】占位符，跳过：{f.name}")
            lw.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f.name,
                         ",".join(to), d["subject"], meta.get("company", ""),
                         "跳过", "正文含【待填】占位符"])
            lf.flush()
            badn += 1
            continue

        atts = [str(resolve(a, f.parent)) for a in (d.get("attach") or [])]
        msg = mailer.build_message(cfg, to, d["subject"],
                                   text=text_body, html=html,
                                   cc=cc or None, bcc=bcc or None,
                                   attachments=atts,
                                   inline=not args.no_inline)

        print(f"[{i}/{len(ok_items)}] {meta.get('company', f.stem)} → {', '.join(to)}")
        ok, err = mailer.smtp_send(cfg, msg, to + cc + bcc)
        if ok:
            print("     ✅ 已发送")
            okn += 1
            if not args.keep:
                shutil.move(str(f), str(DONE / f.name))
        else:
            print(f"     ❌ {str(err)[:150]}")
            badn += 1
            if not args.keep:
                shutil.move(str(f), str(FAILED / f.name))
                (FAILED / (f.stem + ".error.txt")).write_text(
                    f"{datetime.now()}\n{err}\n", encoding="utf-8")

        note = ""
        if args.redirect_to:
            note = f"重定向自 {','.join(original_to)}"
        elif not ok:
            note = str(err)[:400]
        lw.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f.name,
                     ",".join(original_to if args.redirect_to else to),
                     d["subject"], meta.get("company", ""),
                     ("重定向-" if args.redirect_to else "") + ("成功" if ok else "失败"),
                     note])
        lf.flush()
        if i < len(ok_items):
            time.sleep(args.interval)

    lf.close()
    print()
    print(f"完成：成功 {okn} / 失败 {badn}")
    print(f"日志：{LOG}")
    if not args.keep:
        print(f"已发送归档：{DONE}")
        if badn:
            print(f"失败归档：{FAILED}（含 .error.txt 说明）")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
