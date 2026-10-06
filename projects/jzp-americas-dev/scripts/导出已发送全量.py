#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实测导出邮箱「已发送」文件夹全量记录 —— 作为发送量的权威口径。

产出：.workbuddy-ai/已发送全量.json
字段：date(原始), to[], cc[], subject, msgid
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

    typ, boxes = m.list()
    print("== 邮箱文件夹 ==")
    for b in boxes:
        try:
            print("   ", b.decode("utf-8", "replace"))
        except Exception:
            print("   ", b)

    folder = None
    for b in boxes:
        s = b.decode("utf-8", "replace")
        if "Sent" in s or "已发送" in s or "&XfJT0ZAB-" in s:
            folder = s.split(' "/" ')[-1].strip('"')
            break
    print("\n选用已发送文件夹:", folder)
    if not folder:
        print("!! 未找到已发送文件夹")
        return 1

    m.select(f'"{folder}"', readonly=True)
    typ, d = m.search(None, "ALL")
    ids = d[0].split()
    print(f"已发送夹共 {len(ids)} 封，读取头部…")

    out = []
    for i, num in enumerate(ids, 1):
        raw = mc.fetch_headers(m, num, "TO CC SUBJECT DATE MESSAGE-ID")
        to = mc.raw_header(raw, "To") or ""
        cc = mc.raw_header(raw, "CC") or ""
        subj = mc.raw_header(raw, "Subject") or ""
        date = mc.raw_header(raw, "Date") or ""
        mid = mc.raw_header(raw, "Message-ID") or ""
        out.append(dict(
            n=num.decode() if isinstance(num, bytes) else str(num),
            date=date, to=[e.lower() for e in EMAIL_RE.findall(to)],
            cc=[e.lower() for e in EMAIL_RE.findall(cc)],
            subject=subj, msgid=mid.strip()))
        if i % 100 == 0:
            print(f"   …{i}/{len(ids)}")
    m.logout()

    p = ROOT / ".workbuddy-ai/已发送全量.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n✅ 导出 {len(out)} 封 → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
