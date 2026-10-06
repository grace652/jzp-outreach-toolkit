#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动回复（OOO / 工单确认）专项扫描器
=========================================
背景
----
`扫描回复.py` 的 `SKIP_SUBJECT` 里**主动丢弃** automatic reply / out of office / vacation，
所以自动回复从未进入登记表。但自动回复里有两类**有跟进价值**的信息：

  ① **休假/出差 OOO**：证明该地址**真实可达**（人存在、邮箱有效），
     并给出**返岗日期** → 应据此排「返岗后跟进」；
  ② **工单/系统自动确认**：说明信件**已进入对方系统**（常带 case/ticket 号），
     可判断是否需要走正式供应商注册流程。

本脚本只读、只出报告，不发送任何东西。

用法
----
  python3 扫描自动回复.py                # 扫最近 60 天
  python3 扫描自动回复.py --days 120
  python3 扫描自动回复.py --json         # 同时落 JSON
"""

import argparse
import email
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BJ = timezone(timedelta(hours=8))

# ---------- 判定用词表 ----------
# 头字段直接标记自动回复
AUTO_HEADERS = ("auto-submitted", "x-autoreply", "x-autorespond",
                "x-auto-response-suppress", "x-vacation", "x-autoreply-from")

# 主题里出现即判为自动回复
SUBJ_AUTO = (
    "automatic reply", "auto reply", "auto-reply", "autoreply", "auto:",
    "automatic response", "autoresponse", "auto response",
    "out of office", "out-of-office", "out of the office", "ooo:",
    "away from", "away until", "on vacation", "vacation", "annual leave",
    "on leave", "parental leave", "maternity leave", "sabbatical",
    "abwesenheit", "abwesend", "absence du bureau", "réponse automatique",
    "automatische antwort", "自动回复", "自动答复", "休假", "外出",
    "currently out", "limited access to email", "returning on",
    "received your message", "thank you for contacting", "ticket",
    "case number", "we have received your", "inquiry has been received",
    "acknowledgement", "acknowledgment", "auto acknowledgement",
)

# 正文里出现即判为 OOO
BODY_OOO = (
    "i am currently out of the office", "i will be out of the office",
    "i'm currently out of the office", "i am out of the office",
    "out of the office until", "out of office until",
    "i will be away", "i am away", "i'm away",
    "will be returning on", "returning to the office on",
    "back in the office on", "i will be back on", "i'll be back on",
    "return on", "returning on", "back on monday", "back next week",
    "limited access to email", "with limited access",
    "for immediate assistance", "for urgent matters",
    "please contact the following", "in my absence",
    "on annual leave", "on vacation", "on leave until",
    "currently on leave", "currently on vacation",
    "自动回复", "休假中", "外出期间", "不在办公室",
)

# 正文里出现即判为工单/系统确认
BODY_TICKET = (
    "we have received your", "your inquiry has been received",
    "has been received and will be", "ticket number", "case number",
    "case id", "reference number", "reference #", "your case",
    "has been assigned", "created a ticket", "we will respond",
    "we aim to respond", "response time", "within 24 hours",
    "thank you for contacting", "thank you for your email",
    "automated response", "this is an automated",
)

RETURN_PATTERNS = [
    r"(?:return(?:ing)?(?:\s+to\s+the\s+office)?|back|available)\s*(?:on|by|at)?\s*"
    r"(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rsday)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)?[,]?\s*"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?)",
    r"(?:return(?:ing)?(?:\s+to\s+the\s+office)?|back|available)\s*(?:on|by|at)?\s*"
    r"(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)",
]
CONTACT_PATTERNS = [
    r"(?:contact|email|reach out to|please contact|direct(?:ly)? to)\s+([A-Z][a-zA-Z\.\-']+(?:\s+[A-Z][a-zA-Z\.\-']+)?)",
]


def load_mailer():
    spec = importlib.util.spec_from_file_location("mailer", ROOT / "邮箱客户端.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mailer"] = mod
    spec.loader.exec_module(mod)
    return mod


def plain_body(msg) -> str:
    import html as H
    body = ""
    for p in msg.walk():
        if p.get_content_type() == "text/plain" and not p.get_filename():
            try:
                body = p.get_content(); break
            except Exception:
                pass
    if not body:
        for p in msg.walk():
            if p.get_content_type() == "text/html" and not p.get_filename():
                try:
                    body = re.sub(r"<[^>]+>", " ", H.unescape(p.get_content())); break
                except Exception:
                    pass
    body = re.sub(r"[ \t]+", " ", body or "")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def parse_date(s: str):
    s = (s or "").strip()
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    for f in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
              "%d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M %z"):
        try:
            dt = datetime.strptime(s, f)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    mc = load_mailer()
    cfg = mc.load_config()
    m = mc.imap_connect(cfg)
    m.select("INBOX", readonly=True)

    since = (datetime.now(BJ) - timedelta(days=args.days)).strftime("%d-%b-%Y")
    typ, d = m.search(None, f"(SINCE {since})")
    ids = d[0].split()
    print(f"INBOX 最近 {args.days} 天共 {len(ids)} 封，筛自动回复…")

    hits = []
    for i, num in enumerate(ids, 1):
        raw = mc.fetch_headers(m, num, "FROM SUBJECT DATE")
        subj = mc.raw_header(raw, "Subject") or ""
        frm = mc.raw_header(raw, "From") or ""
        date = mc.raw_header(raw, "Date") or ""
        low_s = subj.lower()
        if not any(k in low_s for k in SUBJ_AUTO):
            continue
        # 取全文（含头）再判
        typ2, dd = m.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(dd[0][1], policy=email.policy.default)
        hdrs = {k.lower(): (v or "") for k, v in msg.items()}
        auto_hdr = any(h in hdrs for h in AUTO_HEADERS) or \
            "auto" in hdrs.get("auto-submitted", "").lower() or \
            hdrs.get("precedence", "").lower() in ("auto_reply", "bulk", "junk")
        body = plain_body(msg)
        low_b = body.lower()
        kind = None
        if any(k in low_b for k in BODY_OOO) or auto_hdr:
            kind = "OOO"
        if any(k in low_b for k in BODY_TICKET):
            kind = "TICKET" if kind != "OOO" else "OOO"
        if not kind:
            kind = "OTHER"
        ret = ""
        for pat in RETURN_PATTERNS:
            mm = re.search(pat, body, re.I)
            if mm:
                ret = mm.group(1); break
        contact = ""
        for pat in CONTACT_PATTERNS:
            mm = re.search(pat, body)
            if mm:
                contact = mm.group(1); break
        addr = (re.search(r"<([^>]+)>", frm) or re.search(r"([^\s<>]+@[^\s<>]+)", frm))
        hits.append(dict(
            n=num.decode() if isinstance(num, bytes) else str(num),
            kind=kind, date=date, frm=frm,
            from_email=(addr.group(1) if addr else "").lower(),
            subject=subj, return_hint=ret, alt_contact=contact,
            body=body[:900],
        ))
        if i % 200 == 0:
            print(f"   …{i}/{len(ids)}  命中 {len(hits)}")
    m.logout()

    order = {"OOO": 0, "TICKET": 1, "OTHER": 2}
    hits.sort(key=lambda r: (order[r["kind"]], r["date"]))

    out_json = ROOT / ".workbuddy-ai/自动回复全量.json"
    out_json.write_text(json.dumps(hits, ensure_ascii=False, indent=1), encoding="utf-8")

    for k, label in (("OOO", "休假/外出（OOO）"), ("TICKET", "工单/系统自动确认"), ("OTHER", "其他自动回复")):
        grp = [h for h in hits if h["kind"] == k]
        print(f"\n{'='*70}\n【{label}】{len(grp)} 条\n{'='*70}")
        for h in grp:
            print(f"\n[{h['date'][:31]}] {h['frm'][:70]}")
            print(f"   主题：{h['subject'][:90]}")
            if h["return_hint"]:
                print(f"   返岗线索：{h['return_hint']}")
            if h["alt_contact"]:
                print(f"   替代联系人：{h['alt_contact']}")
            print(f"   正文：{re.sub(chr(10), ' | ', h['body'][:320])}")
    print(f"\n合计 {len(hits)} 条 → {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
