#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
企业邮箱直连客户端（IMAP/SMTP · 零依赖）
==========================================
用 Python 标准库直接连腾讯企业邮箱，不依赖任何第三方包、不需要 npm、不需要装 CLI。

相比企业微信机器人发信的优势：
  ✅ 发件人显示名就是你自己的名字（不会出现「XX的机器人」）
  ✅ 发信 + 读信 一次搞定（机器人那边读信还要管理员授权）
  ✅ 邮件进入网页端【已发送】，和你平时发信完全一致
  ✅ 不依赖任何机器人权限

前置条件（都需要管理员配合，一次搞定）：
  1. 管理员：企业微信管理端 →【协作 → 邮件 → 安全管理 → 客户端访问权限】
             开启 IMAP/SMTP 服务范围（含你这个账号）
  2. 你自己：网页版企业邮箱 →【设置 → 收发信设置】开启 IMAP/SMTP 服务
  3. 你自己：网页版企业邮箱 →【设置 → 邮箱绑定】生成「客户端专用密码」
             （开启安全登录后必须用专用密码，不能用登录密码）
  4. 建议：网页版【设置 → 收发信设置】把收取范围设为「全部」，
           并勾选「保存已发送至服务器」

配置文件：~/.config/jiezou-mail/config.json（chmod 600，不进任何仓库）

用法：
  python3 邮箱客户端.py test                          # 测试登录
  python3 邮箱客户端.py list --limit 20               # 列出最近邮件
  python3 邮箱客户端.py list --unread                 # 只看未读
  python3 邮箱客户端.py read --n 3                    # 读第 3 封的正文
  python3 邮箱客户端.py send --to {{CONTACT_EMAIL}} --subject "Hi" --html body.html
  python3 邮箱客户端.py send --to {{CONTACT_EMAIL}} --subject "Hi" --text body.txt --attach f.csv
  python3 邮箱客户端.py send --batch 发送清单.csv      # 按清单批量发（带安全闸）
"""

import argparse
import email
import email.policy
import imaplib
import json
import mimetypes
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, parsedate_to_datetime
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "jiezou-mail" / "config.json"

CONFIG_TEMPLATE = {
    "email": "{{SENDER_EMAIL}}",
    "password": "在这里填客户端专用密码",
    "sender_name": "{{SENDER_NAME}}",
    "imap_host": "imap.exmail.qq.com",
    "imap_port": 993,
    "smtp_host": "smtp.exmail.qq.com",
    "smtp_port": 465,
    "sent_folder": "Sent Messages",
}

PLACEHOLDER = "【待填"


# ---------------------------------------------------------------- 配置

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(CONFIG_TEMPLATE, ensure_ascii=False, indent=2),
            encoding="utf-8")
        os.chmod(CONFIG_PATH, 0o600)
        print(f"已创建配置模板：{CONFIG_PATH}")
        print("请运行 setup 命令填入客户端专用密码：")
        print("    python3 邮箱客户端.py setup")
        sys.exit(1)

    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not cfg.get("password") or "填" in str(cfg.get("password", "")):
        print(f"⚠️  配置里的密码还没填：{CONFIG_PATH}")
        print("   运行以下命令填入（密码不会显示在屏幕上）：")
        print("       python3 邮箱客户端.py setup")
        sys.exit(1)
    return cfg


def cmd_setup(cfg, a):
    """交互式写入凭据 —— 密码用隐藏输入，不经过命令行历史、不出现在对话里。"""
    import getpass

    path = CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    for k, v in CONFIG_TEMPLATE.items():
        data.setdefault(k, v)

    print("=" * 62)
    print(" 企业邮箱凭据配置")
    print("=" * 62)
    print()
    print("密码获取位置：网页版企业邮箱 → 设置 → 邮箱绑定 → 客户端专用密码")
    print("（是「客户端专用密码」，不是你的登录密码）")
    print()

    acct = input(f"邮箱地址 [{data.get('email','')}]: ").strip()
    if acct:
        data["email"] = acct
    name = input(f"发件人显示名 [{data.get('sender_name','')}]: ").strip()
    if name:
        data["sender_name"] = name

    print()
    try:
        pw = getpass.getpass("客户端专用密码（输入时不显示）: ").strip()
    except Exception:
        # 没有 TTY（例如被管道调用）时退化为普通输入
        pw = input("客户端专用密码（会显示在屏幕上）: ").strip()
    if not pw:
        print("未输入密码，已取消。")
        return 1
    data["password"] = pw

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(path, 0o600)
    print()
    print(f"✅ 已写入 {path}（权限 600，不进任何仓库）")
    print()
    print("正在测试登录…")
    print()
    return cmd_test(data, a)


def ctx() -> ssl.SSLContext:
    c = ssl.create_default_context()
    return c


# ---------------------------------------------------------------- 签名内嵌图

# 签名 HTML 里用 cid:xxx 引用的图，这里给出对应文件
SIGNATURE_IMAGES = {
    "logo":      "01.png",
    "certs":     "02.jpg",
    "products":  "03.jpg",
    "facebook":  "04.png",
    "twitter":   "05.png",
    "linkedin":  "06.png",
    "instagram": "07.png",
}
SIG_IMG_DIR = Path(__file__).resolve().parent / "签名图片_压缩"


# ---------------------------------------------------------------- 发送

def html_to_text(html: str) -> str:
    """从 HTML 反推一份**真实可读的纯文本**，用作 multipart/alternative 的 text/plain 段。

    用途：手机通知栏、纯文本客户端、以及邮件预览都会读这一段。
    若让它退化成「请用支持 HTML 的客户端查看」，对北美收件人既无信息量
    又显得可疑。

    处理顺序：
      1. 去掉 <style>/<script>/<!-- -->
      2. 图片 → 用其 alt 文本（签名图无 alt 则丢弃，避免出现 "cid:logo"）
      3. 块级标签与 <br> → 换行
      4. 链接 → `文本 <url>`（纯文本里必须能看到真实地址）
      5. 剥标签、解实体、压缩连续空行
    """
    s = html
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", s)
    s = re.sub(r"(?s)<!--.*?-->", "", s)

    # 图片：有 alt 用 alt，否则整段丢弃（签名图是装饰性的）
    def _img(m):
        alt = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', m.group(0), re.I)
        return alt.group(1) if alt and alt.group(1).strip() else ""
    s = re.sub(r"(?is)<img[^>]*>", _img, s)

    # 链接：保留可读文本与真实 URL
    def _a(m):
        href = re.search(r'href\s*=\s*["\']([^"\']+)["\']', m.group(1), re.I)
        label = re.sub(r"(?s)<[^>]+>", "", m.group(2)).strip()
        if not href:
            return label
        url = href.group(1)
        if url.startswith("mailto:"):
            url = url[7:]
        return f"{label} <{url}>" if label and label != url else (label or url)
    s = re.sub(r"(?is)<a\b([^>]*)>(.*?)</a>", _a, s)

    # 块级 → 换行；<br> → 换行
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|table)\s*>", "\n", s)
    s = re.sub(r"(?i)<(p|div|tr|li|h[1-6]|table)\b[^>]*>", "\n", s)
    s = re.sub(r"(?i)</?t[dh]\b[^>]*>", "  ", s)

    s = re.sub(r"(?s)<[^>]+>", "", s)          # 剥剩余标签
    s = html_mod.unescape(s) if "html_mod" in globals() else \
        __import__("html").unescape(s)
    s = re.sub(r"[ \t\u00a0]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

def build_message(cfg, to, subject, text=None, html=None,
                  cc=None, bcc=None, attachments=None, inline=True) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("sender_name") or "", cfg["email"]))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)

    if html:
        # 🔴 2026-09-28 修复：原本 fallback 硬编码为一句中文提示
        # 「此邮件为 HTML 格式，请用支持 HTML 的客户端查看。」
        # 后果：① 手机通知/预览、纯文本客户端看到的是这句提示而非正文
        #       ② 该句为中文，对北美收件人完全无意义
        #       ③ 部分反垃圾规则会给「无实质纯文本正文」的 HTML-only 邮件加分
        # 现改为：没显式传 text 时，**从 HTML 反推一份真纯文本**。
        plain = text or html_to_text(html)
        msg.set_content(plain)
        msg.add_alternative(html, subtype="html")

        # 把签名图作为内嵌图（Content-ID）挂上去 —— 收件人无需点「显示图片」
        if inline and "cid:" in html:
            html_part = msg.get_payload()[-1]
            for cid, fname in SIGNATURE_IMAGES.items():
                if f"cid:{cid}" not in html:
                    continue
                f = SIG_IMG_DIR / fname
                if not f.exists():
                    continue
                ctype, _ = mimetypes.guess_type(str(f))
                maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
                html_part.add_related(f.read_bytes(), maintype=maintype,
                                      subtype=subtype, cid=cid)
    else:
        msg.set_content(text or "")

    for path in (attachments or []):
        p = Path(path)
        if not p.exists():
            print(f"⚠️  附件不存在，已跳过：{path}")
            continue
        ctype, _ = mimetypes.guess_type(str(p))
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype,
                           filename=p.name)
    return msg


def smtp_send(cfg, msg, recipients, dry=False):
    if dry:
        print("   [dry-run] 未实际发送")
        return True, ""
    try:
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"],
                              context=ctx(), timeout=60) as s:
            s.login(cfg["email"], cfg["password"])
            s.send_message(msg, from_addr=cfg["email"], to_addrs=recipients)
        return True, ""
    except smtplib.SMTPAuthenticationError as e:
        return False, (f"登录失败：{e}\n"
                       "  检查：① 密码是否为「客户端专用密码」而非登录密码 "
                       "② 管理员是否已开启 IMAP/SMTP 服务范围 "
                       "③ 网页端是否已开启客户端服务协议")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def cmd_send(cfg, a):
    to = [x.strip() for x in a.to.split(",") if x.strip()]
    cc = [x.strip() for x in a.cc.split(",") if x.strip()] if a.cc else None
    bcc = [x.strip() for x in a.bcc.split(",") if x.strip()] if a.bcc else None

    text = html = None
    if a.html:
        html = Path(a.html).read_text(encoding="utf-8")
        if PLACEHOLDER in html and not a.force:
            print(f"⛔ 正文里还有【待填…】占位符，已阻止发送：{a.html}")
            print("   确实要发（不建议）：加 --force")
            return 2
    if a.text:
        text = Path(a.text).read_text(encoding="utf-8")

    msg = build_message(cfg, to, a.subject, text, html, cc, bcc, a.attach,
                        inline=not getattr(a, "no_inline", False))
    rcpts = to + (cc or []) + (bcc or [])

    print(f"发件人：{cfg.get('sender_name')} <{cfg['email']}>")
    print(f"收件人：{', '.join(to)}")
    print(f"主题  ：{a.subject}")
    if a.attach:
        print(f"附件  ：{', '.join(Path(x).name for x in a.attach)}")
    print()

    ok, err = smtp_send(cfg, msg, rcpts, dry=a.dry_run)
    if ok:
        print("✅ 已发送" if not a.dry_run else "✅ 校验通过")
        return 0
    print(f"❌ 发送失败：{err}")
    return 1


def cmd_batch(cfg, a):
    """按发送清单批量发。默认 dry-run，逐封间隔，失败不重试。"""
    import csv
    rows = list(csv.DictReader(open(a.batch, encoding="utf-8-sig")))
    if a.ids:
        keep = set()
        for part in a.ids.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-", 1)
                keep.update(str(i).zfill(2) for i in range(int(lo), int(hi) + 1))
            else:
                keep.add(part.zfill(2))
        rows = [r for r in rows if r["序号"] in keep]
    if a.prio:
        rows = [r for r in rows if r["优先级"] == a.prio]
    if a.limit:
        rows = rows[:a.limit]

    if not rows:
        print("没有匹配的记录。")
        return 1

    blocked = [r["序号"] for r in rows
               if PLACEHOLDER in Path(r["正文文件"]).read_text(encoding="utf-8")]
    if blocked and not a.force:
        print(f"⛔ 以下草稿仍有【待填…】占位符，已阻止：{'、'.join(blocked)}")
        return 2

    dry = not a.send
    print(f"模式：{'本地校验（不发送）' if dry else '★ 真实发送 ★'}")
    print(f"待处理：{len(rows)} 封，间隔 {a.interval} 秒")
    print()

    if not dry and not a.yes:
        for r in rows:
            print(f"  {r['序号']}  {r['国家']:4}  {r['公司'][:34]:34} → {r['邮箱']}")
        if input("\n确认发送请输入 yes：").strip().lower() != "yes":
            print("已取消。")
            return 1

    log = Path(a.batch).parent / "发送日志.csv"
    new = not log.exists()
    f = log.open("a", encoding="utf-8-sig", newline="")
    import csv as _csv
    w = _csv.writer(f)
    if new:
        w.writerow(["时间", "序号", "国家", "公司", "邮箱", "主题", "结果", "说明"])

    okn = badn = 0
    for i, r in enumerate(rows, 1):
        body_file = r["正文文件"]
        html = Path(body_file).read_text(encoding="utf-8")
        msg = build_message(cfg, [r["邮箱"]], r["主题"], html=html,
                            inline=not getattr(a, "no_inline", False))
        print(f"[{i}/{len(rows)}] {r['序号']} {r['公司'][:36]} → {r['邮箱']}")
        ok, err = smtp_send(cfg, msg, [r["邮箱"]], dry=dry)
        if ok:
            print("     ✅ " + ("校验通过" if dry else "已发送"))
            okn += 1
        else:
            print(f"     ❌ {err[:150]}")
            badn += 1
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), r["序号"],
                    r["国家"], r["公司"], r["邮箱"], r["主题"],
                    "dry-run" if dry else ("成功" if ok else "失败"),
                    "" if ok else str(err)[:400]])
        f.flush()
        if i < len(rows) and not dry:
            time.sleep(a.interval)
    f.close()
    print(f"\n完成：成功 {okn} / 失败 {badn}")
    print(f"日志：{log}")
    return 0


# ---------------------------------------------------------------- 收取

def imap_connect(cfg):
    m = imaplib.IMAP4_SSL(cfg["imap_host"], cfg["imap_port"], ssl_context=ctx())
    m.login(cfg["email"], cfg["password"])
    return m


def _cjk_score(s: str) -> int:
    return sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")


def smart_decode(b: bytes) -> str:
    """解码邮件头字节。

    腾讯系邮件常把中文写成**裸 GBK 字节且不做 RFC2047 编码**，
    这类字节往往也是合法 UTF-8（解出来是希腊字母/组合符等乱码），
    所以不能简单地「先试 UTF-8」。改用 CJK 字符数打分择优。
    """
    cands = []
    for enc in ("gb18030", "utf-8", "big5"):
        try:
            cands.append((enc, b.decode(enc)))
        except (UnicodeDecodeError, LookupError):
            continue
    if not cands:
        return b.decode("utf-8", errors="replace")
    # CJK 字符多的胜出；同分时 UTF-8 优先（标准情况）
    cands.sort(key=lambda kv: (-_cjk_score(kv[1]), 0 if kv[0] == "utf-8" else 1))
    return cands[0][1]


def raw_header(raw: bytes, name: str) -> str:
    """从原始头部字节里取字段值，支持 RFC2047 与裸 GBK 两种形式。"""
    pat = (rb"^" + name.encode() + rb":[ \t]*(.*?)(?=\r?\n[^\s]|\r?\n\r?\n|\Z)")
    m = re.search(pat, raw, re.S | re.M)
    if not m:
        return ""
    val = re.sub(rb"\r?\n[ \t]+", b" ", m.group(1)).strip()
    if b"=?" in val:                       # 标准 RFC2047 编码字
        out = []
        for txt, enc in email.header.decode_header(val.decode("latin1")):
            if isinstance(txt, bytes):
                out.append(smart_decode(txt) if not enc else
                           txt.decode(enc, errors="replace"))
            else:
                out.append(txt)
        return "".join(out)
    return smart_decode(val)


def fetch_headers(m, num, fields="FROM SUBJECT DATE"):
    """取原始头部字节，返回 dict（键大写）。"""
    typ, d = m.fetch(num, f"(BODY.PEEK[HEADER.FIELDS ({fields})])")
    raw = b"".join(x[1] for x in d if isinstance(x, tuple))
    return raw


def decode_header(s):
    """兼容旧调用：纯字符串走 smart_decode 的等价逻辑。"""
    if not s:
        return ""
    if isinstance(s, bytes):
        return smart_decode(s)
    return s


def cmd_test(cfg, a):
    print(f"配置：{CONFIG_PATH}")
    print(f"账号：{cfg['email']}　发件人：{cfg.get('sender_name')}")
    print()
    print("── SMTP（发信）──")
    try:
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"],
                              context=ctx(), timeout=30) as s:
            s.login(cfg["email"], cfg["password"])
        print(f"  ✅ 登录成功 {cfg['smtp_host']}:{cfg['smtp_port']}")
    except smtplib.SMTPAuthenticationError:
        print("  ❌ 登录被拒：密码或权限问题")
        print("     ① 密码必须是「客户端专用密码」，不是登录密码")
        print("     ② 管理员需在企业微信管理端开启 IMAP/SMTP 服务范围")
        print("     ③ 网页端【设置→收发信设置】需开启客户端服务协议")
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")

    print()
    print("── IMAP（收信）──")
    try:
        m = imap_connect(cfg)
        typ, data = m.select("INBOX", readonly=True)
        if typ == "OK":
            print(f"  ✅ 登录成功 {cfg['imap_host']}:{cfg['imap_port']}")
            print(f"     收件箱邮件数：{data[0].decode()}")
        m.logout()
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")
    return 0


def pad(s: str, w: int) -> str:
    """按显示宽度补齐（CJK 字符按 2 列算），否则中文列会错位。"""
    def width(x):
        return sum(2 if ord(c) > 0x2E80 else 1 for c in x)
    while width(s) > w and s:
        s = s[:-1]
    return s + " " * max(0, w - width(s))


def cmd_list(cfg, a):
    m = imap_connect(cfg)
    m.select(a.folder or "INBOX", readonly=True)
    crit = "UNSEEN" if a.unread else "ALL"
    typ, data = m.search(None, crit)
    ids = data[0].split()
    if not ids:
        print("没有匹配的邮件。")
        m.logout()
        return 0
    ids = ids[-a.limit:][::-1]

    print(f"{'#':>3}  {pad('日期',16)}  {pad('发件人',26)}  主题")
    print("─" * 100)
    for i, num in enumerate(ids, 1):
        raw = fetch_headers(m, num)
        frm = re.sub(r"<.*?>", "", raw_header(raw, "From")).strip().strip('"')
        subj = raw_header(raw, "Subject")
        date_s = raw_header(raw, "Date")
        try:
            dt = parsedate_to_datetime(date_s).strftime("%Y-%m-%d %H:%M")
        except Exception:
            dt = date_s[:16] or "?"
        print(f"{i:>3}  {pad(dt,16)}  {pad(frm,26)}  {subj[:58]}")
    m.logout()
    return 0


def cmd_read(cfg, a):
    m = imap_connect(cfg)
    m.select(a.folder or "INBOX", readonly=True)
    typ, data = m.search(None, "ALL")
    ids = data[0].split()
    if not ids:
        print("收件箱为空。")
        m.logout()
        return 0
    num = ids[-a.n]
    raw = fetch_headers(m, num, "FROM SUBJECT DATE TO")
    print(f"主题：{raw_header(raw, 'Subject')}")
    print(f"发件：{raw_header(raw, 'From')}")
    print(f"收件：{raw_header(raw, 'To')}")
    print(f"时间：{raw_header(raw, 'Date')}")
    print("─" * 80)

    typ, d = m.fetch(num, "(RFC822)")
    msg = email.message_from_bytes(d[0][1], policy=email.policy.default)

    body = None
    for part in msg.walk():
        if part.get_content_type() == "text/plain" and not part.get_filename():
            body = part.get_content()
            break
    if body is None:
        for part in msg.walk():
            if part.get_content_type() == "text/html" and not part.get_filename():
                body = re.sub(r"<[^>]+>", "", part.get_content())[:4000]
                break
    print((body or "（无纯文本正文）")[:4000])

    atts = [p.get_filename() for p in msg.walk() if p.get_filename()]
    if atts:
        print("─" * 80)
        print("附件：" + "、".join(atts))
    m.logout()
    return 0


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="企业邮箱直连客户端（IMAP/SMTP）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="交互式配置凭据（密码隐藏输入）")
    p.set_defaults(fn=cmd_setup, need_cfg=False)

    p = sub.add_parser("test", help="测试 SMTP/IMAP 登录")
    p.set_defaults(fn=cmd_test)

    p = sub.add_parser("list", help="列出邮件")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--unread", action="store_true")
    p.add_argument("--folder", default=None)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("read", help="读某封邮件正文")
    p.add_argument("--n", type=int, default=1, help="倒数第 N 封，默认 1=最新")
    p.add_argument("--folder", default=None)
    p.set_defaults(fn=cmd_read)

    p = sub.add_parser("send", help="发单封邮件")
    p.add_argument("--to", required=False)
    p.add_argument("--cc")
    p.add_argument("--bcc")
    p.add_argument("--subject", required=False)
    p.add_argument("--text", help="纯文本正文文件")
    p.add_argument("--html", help="HTML 正文文件")
    p.add_argument("--attach", action="append", default=[], help="附件路径，可重复")
    p.add_argument("--batch", help="改为按清单批量发送")
    p.add_argument("--ids")
    p.add_argument("--prio")
    p.add_argument("--limit", type=int)
    p.add_argument("--interval", type=int, default=90)
    p.add_argument("--send", action="store_true", help="批量模式：真正发送")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-inline", action="store_true",
                   help="不内嵌签名图片（改用远程引用，仅用于对比测试）")
    p.set_defaults(fn=None)

    args = ap.parse_args()

    # setup 不需要已有配置，其余命令都要
    if getattr(args, "need_cfg", True) is False:
        return cmd_setup({}, args)

    cfg = load_config()

    if args.cmd == "send":
        if args.batch:
            return cmd_batch(cfg, args)
        if not (args.to and args.subject and (args.html or args.text)):
            print("单封发送需要：--to、--subject，以及 --html 或 --text 之一")
            return 1
        return cmd_send(cfg, args)

    return args.fn(cfg, args)


if __name__ == "__main__":
    sys.exit(main() or 0)
