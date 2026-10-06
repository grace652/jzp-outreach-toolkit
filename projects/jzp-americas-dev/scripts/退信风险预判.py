#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""退信风险预判
===============
用户口径（2026-10-05）：
  · **已在退信库（明确退信）** → 不发，**只需提一嘴**，不用解释
  · **未退过信但风险偏高** → **报出退信概率**，由用户判断

本脚本只读、不发送。

口径来源
--------
基准率 —— **本项目实测**（`已发送全量.json` × `退信黑名单.json`）：
    角色邮箱（info@/sales@/contact@/…）  49 个地址 → 退信 7 → **14.3%**
    具名邮箱                            216 个地址 → 退信 9 → **4.2%**
风险系数 —— **经验值（未单独验证）**，见 04_do_not_say.md §十。

用法
----
  python3 退信风险预判.py --check {{CONTACT_EMAIL}} {{CONTACT_EMAIL}}
  python3 退信风险预判.py --queue 发信队列-跟进1002.json
  python3 退信风险预判.py --check {{CONTACT_EMAIL}} --json
"""

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SENT = ROOT / ".workbuddy-ai/已发送全量.json"

ROLE_RE = re.compile(
    r"^(info|sales|contact|support|customerservice|custsvc|feedback|supplier|office|admin|"
    r"service|inquiries|inquiry|hello|mail|general|estimating|bids|purchasing|salesna|"
    r"utilitysalescanada|accounts|accounting|hr|careers)@", re.I)

# 基准率（本项目实测 2026-10-05）
BASE_ROLE = 14.3
BASE_NAMED = 4.2

# 经验系数（未单独验证）
K_M365 = 1.8          # Microsoft 365 域 —— 本项目有反制史（550 5.4.1）
K_GATEWAY = 1.6       # Mimecast / Barracuda 网关
K_COLD = 1.3          # 该域本项目从未成功送达过
K_WARM = 0.7          # 该域曾成功送达
K_SMTP250 = 0.6       # 地址 SMTP 实测 250


def load_ds():
    spec = importlib.util.spec_from_file_location("ds", ROOT / "定时发送.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ds"] = mod
    spec.loader.exec_module(mod)
    return mod


def dig_mx(domain: str) -> list:
    """查 MX。**必须指定 @8.8.8.8** —— 本机 TUN 会劫持 DNS（见 ~/.workbuddy-ai/MEMORY.md）。"""
    try:
        out = subprocess.run(["dig", "+short", "MX", domain, "@8.8.8.8"],
                             capture_output=True, text=True, timeout=8).stdout
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def sent_history():
    """返回 (该域发过信的次数, 是否该域曾成功送达)。"""
    if not SENT.exists():
        return {}
    rows = json.loads(SENT.read_text(encoding="utf-8"))
    hist = {}
    for r in rows:
        for a in r["to"]:
            d = a.split("@")[-1].lower()
            hist[d] = hist.get(d, 0) + 1
    return hist


def predict(addr: str, ds, blmap: dict, bounced_domains: set, hist: dict) -> dict:
    """返回 dict(level, prob, prob_range, reasons[], gate)"""
    a = addr.lower()
    dom = a.split("@")[-1]
    rec = blmap.get(a)
    if rec:
        # A 级：明确退信 —— 不发，不解释
        return dict(addr=addr, level="A", gate="不发",
                    prob=None, prob_range="—", reasons=[],
                    one_line=f"⛔ {addr} 已退信（{rec.get('category','?')}）→ 不发")

    # 域级闸门（同域退过信 → 跟进信不发）
    if dom in bounced_domains:
        return dict(addr=addr, level="A", gate="不发（跟进信）",
                    prob=None, prob_range="—", reasons=[],
                    one_line=f"⛔ {addr} 同域曾有地址退信（{dom}）→ 跟进信不发")

    base = BASE_ROLE if ROLE_RE.match(a) else BASE_NAMED
    k, reasons = 1.0, []
    mx = dig_mx(dom)
    mxt = " ".join(mx).lower()
    if "outlook.com" in mxt or "protection.outlook" in mxt:
        k *= K_M365; reasons.append(f"M365 域 ×{K_M365}")
    if "mimecast" in mxt:
        k *= K_GATEWAY; reasons.append(f"Mimecast 网关 ×{K_GATEWAY}")
    if "barracuda" in mxt:
        k *= K_GATEWAY; reasons.append(f"Barracuda 网关 ×{K_GATEWAY}")
    if not mx:
        reasons.append("⚠️ 查不到 MX（可能查询失败或域异常）")
    n = hist.get(dom, 0)
    if n == 0:
        k *= K_COLD; reasons.append(f"首次触达该域 ×{K_COLD}")
    else:
        k *= K_WARM; reasons.append(f"该域已发 {n} 封且未退信 ×{K_WARM}")
    if ROLE_RE.match(a):
        reasons.append(f"角色邮箱（基准 {BASE_ROLE}%）")
    else:
        reasons.append(f"具名邮箱（基准 {BASE_NAMED}%）")

    p = base * k
    lo, hi = max(0.5, p * 0.6), min(60.0, p * 1.5)
    lvl = "C" if p < 6 else ("B" if p < 15 else "B+")
    return dict(addr=addr, level=lvl, gate="可发", prob=round(p, 1),
                prob_range=f"{lo:.1f}–{hi:.1f}%", reasons=reasons,
                one_line=f"{addr}  预估退信 ≈{p:.1f}%（{lo:.1f}–{hi:.1f}%）")


def main():
    ap = argparse.ArgumentParser(description="退信风险预判")
    ap.add_argument("--check", nargs="*", help="地址清单")
    ap.add_argument("--queue", help="队列文件")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ds = load_ds()
    blmap = ds.load_blacklist()
    bdoms = ds.bounced_domains()
    hist = sent_history()

    addrs = list(a.check or [])
    if a.queue:
        q = json.loads(Path(a.queue).read_text(encoding="utf-8"))
        items = q if isinstance(q, list) else q.get("items", [])
        addrs = [x for it in items if it.get("status") in (None, "pending")
                 for x in (it.get("to") or [])]
    if not addrs:
        print("用法：--check {{CONTACT_EMAIL}}  ｜  --queue <队列.json>")
        return 1

    res = [predict(x, ds, blmap, bdoms, hist) for x in addrs]
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0

    A = [r for r in res if r["level"] == "A"]
    B = [r for r in res if r["level"] != "A"]

    print("=" * 78)
    print(f"退信风险预判 — 共 {len(res)} 个地址")
    print("=" * 78)

    if A:
        print(f"\n【A · 明确退信 → 不发】{len(A)} 个（一句带过，不解释）")
        for r in A:
            print(f"  {r['one_line']}")
    if B:
        print(f"\n【B · 未退过信，风险预判】{len(B)} 个（供你判断发不发）")
        print(f"  {'地址':38}{'预估退信':16}依据")
        print("  " + "-" * 74)
        for r in sorted(B, key=lambda x: -(x["prob"] or 0)):
            print(f"  {r['addr']:38}{r['prob_range']:16}{'｜'.join(r['reasons'])[:80]}")

    if B:
        print("\n⚠️ 系数为**经验值（未单独验证）**；基准率 14.3%/4.2% 为**本项目实测**。")
        print("   预估退信 >15% 的建议改走电话或换具名联系人。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
