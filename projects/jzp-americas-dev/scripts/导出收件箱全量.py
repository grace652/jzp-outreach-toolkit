#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测导出收件箱（INBOX）全量头部 —— 用于核对「客户回复」与「退信」。

产出：.workbuddy-ai/收件箱全量.json
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(Path(__file__).resolve().parents[1])
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def load_mailer():
    spec = importlib.util.spec_from_file_location("mailer", ROOT / "邮箱客户端.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mailer"] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    mc = load_mailer()
    cfg = mc.load_config()
    m = mc.imap_connect(cfg)
    m.select("INBOX", readonly=True)
    typ, d = m.search(None, "ALL")
    ids = d[0].split()
    print(f"INBOX 共 {len(ids)} 封，读取头部…")
    out = []
    for i, num in enumerate(ids, 1):
        raw = mc.fetch_headers(m, num, "FROM TO SUBJECT DATE")
        frm = mc.raw_header(raw, "From") or ""
        to = mc.raw_header(raw, "To") or ""
        subj = mc.raw_header(raw, "Subject") or ""
        date = mc.raw_header(raw, "Date") or ""
        out.append(dict(
            n=num.decode() if isinstance(num, bytes) else str(num),
            date=date, frm=frm,
            from_email=(EMAIL_RE.findall(frm) or [""])[0].lower(),
            to=[e.lower() for e in EMAIL_RE.findall(to)],
            subject=subj))
        if i % 100 == 0:
            print(f"   …{i}/{len(ids)}")
    m.logout()
    p = ROOT / ".workbuddy-ai/收件箱全量.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ 导出 {len(out)} 封 → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
