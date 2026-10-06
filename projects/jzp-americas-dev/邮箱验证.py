#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮箱验证.py —— 交接单挖人环节的邮箱可达性验证工具

用途：在「找客户」环节验证具名邮箱是否真实存在。
     本机有唯兔云 TUN + fake-ip DNS 劫持风险，因此一律用公共 DNS（8.8.8.8）。

核心方法（四步，缺一不可）：
  ⓪ 控制地址：先测该域一个「已知真实」的地址（通常 info@，见官网明文）
       🔴 若控制地址拿不到 250 → 本次探测**整体作废**（工具被拦/IP 被拉黑），
          绝不能据此判候选人「不存在」。这是 2026-09-28 实测踩到的真坑：
          M365（Exchange Online）在探测若干次后会用 Spamhaus 拉黑来源 IP，
          随后**连 info@ 都返回 550**，报 `5.7.1 ... blocked using Spamhaus`。
          → 现象：同一地址首次 250、复测 550，结果自相矛盾。
          → 判据：**看 info@ 的脸色**。info@ 250 才说明这一轮可信。
  ① 取 MX 记录（公共 DNS）
  ② catch-all 判定：测一个必然不存在的随机地址
       - 随机地址 550 → 非 catch-all → RCPT 探测有区分力 ✅
       - 随机地址 250 → catch-all → 探测不可信 ⚠️（结论作废）
  ③ 对照组：测几个「格式正确但明显不存在」的姓名
       - 若对照组也 250 → 网关宽松 → 结论作废
       - 若对照组 550 而候选人 250 → 真命中 ✅

⚠️ M365 对 SMTP 探测有主动反制（限流 + Spamhaus 拉黑），
   所以**不要连续多轮重复探测同一域**；一轮拿不到可靠结果就改走别的渠道，
   或隔一段时间再试（本脚本不自动重试，避免加重拉黑）。

⚠️ 单凭 250 不得作为主送依据 —— 见 skill H2/H3/H4，仍须交叉印证。

用法：
    python3 邮箱验证.py <域名> <候选邮箱1> [候选邮箱2 ...]
    python3 邮箱验证.py {{COMPANY_DOMAIN}} {{CONTACT_EMAIL}}

    # 指定控制地址（默认自动在候选里找 info@，找不到则必须显式给）
    python3 邮箱验证.py <域名> <候选...> --control info@<域名>
"""

import re
import smtplib
import subprocess
import sys

PUBLIC_DNS = "8.8.8.8"
PROBE_FROM = "{{SENDER_EMAIL}}"      # 我方真实域名，降低被拒概率
FAKE_LOCAL = "zzz_nonexistent_probe_9987"
FAKE_NAMES = ["john.smith", "jane.doe", "bob.jones"]


def dig(name, rtype, dns=PUBLIC_DNS):
    """用公共 DNS 查询，绕开本机 fake-ip 劫持。"""
    out = subprocess.run(
        ["dig", "+short", f"@{dns}", name, rtype],
        capture_output=True, text=True, timeout=20,
    ).stdout.strip()
    return [l for l in out.split("\n") if l]


def get_mx(domain):
    recs = dig(domain, "MX")
    if not recs:
        return None
    # 取优先级最小（数值最小）的 MX
    best = None
    for r in recs:
        parts = r.split()
        if len(parts) >= 2:
            try:
                prio = int(parts[0])
            except ValueError:
                prio = 999
            if best is None or prio < best[0]:
                best = (prio, parts[-1].rstrip("."))
    return best[1] if best else None


def probe(mx_host, addresses):
    """返回 {address: rcpt_code}。用一次会话连续 RCPT 以省时。"""
    results = {}
    s = smtplib.SMTP(timeout=25)
    try:
        s.connect(mx_host, 25)
        s.ehlo("verify.local")
        s.mail(PROBE_FROM)
        for a in addresses:
            try:
                code, msg = s.rcpt(a)
                results[a] = code
            except Exception as e:
                results[a] = f"ERR:{e}"
        try:
            s.quit()
        except Exception:
            pass
    finally:
        try:
            s.close()
        except Exception:
            pass
    return results


def main():
    args = sys.argv[1:]
    control_override = None
    if "--control" in args:
        i = args.index("--control")
        control_override = args[i + 1].strip()
        del args[i:i + 2]

    if len(args) < 2:
        print(__doc__)
        return 1

    domain = args[0].strip().lower()
    candidates = [a.strip() for a in args[1:] if a.strip()]

    print(f"域名: {domain}")
    mx = get_mx(domain)
    if not mx:
        print("❌ 无 MX 记录 —— 该域不能收信，终止。")
        return 2
    print(f"MX: {mx}")

    # ⓪ 控制地址：必须拿到 250，否则整轮作废
    control = control_override or f"info@{domain}"
    print(f"\n[控制地址] {control} —— 该域官网公开的真实地址，必须 250")
    rc = probe(mx, [control])
    ccode = rc.get(control)
    print(f"   返回: {ccode}")
    if ccode != 250:
        print("🔴 控制地址未通过 → 本次探测整体作废。")
        print("   原因通常是 M365/网关拉黑来源 IP（5.7.1 blocked using Spamhaus）。")
        print("   ⛔ 绝不能据此判定候选邮箱『不存在』。改走官网/LinkedIn/电话等渠道。")
        print("   💡 隔一段时间再试；不要连续重试（会加重拉黑）。")
        return 6
    print("✅ 控制地址通过 → 本轮探测可信。")

    # ① catch-all 判定
    rnd = f"{FAKE_LOCAL}@{domain}"
    r1 = probe(mx, [rnd])
    random_code = r1.get(rnd)
    print(f"\n[catch-all 判定] {rnd} → {random_code}")

    if random_code == 250:
        print("⚠️ 该域为 CATCH-ALL → RCPT 探测结果不可信，本次结论作废。")
        print("   请改用官网/LinkedIn 明文等一手源验证，或走电话/表单（B 档）。")
        return 3
    if not isinstance(random_code, int):
        print(f"⚠️ 探测异常（{random_code}）→ 无法判定，结论不采信。")
        return 4
    print("✅ 非 catch-all → RCPT 探测有区分力。")

    # ② 对照组
    ctrl = [f"{n}@{domain}" for n in FAKE_NAMES]
    print("\n[对照组] 格式正确但应为不存在的姓名：")
    r2 = probe(mx, ctrl)
    ctrl_false_positive = [a for a, c in r2.items() if c == 250]
    for a, c in r2.items():
        print(f"   {'⚠️ 250(异常)' if c == 250 else '✅ ' + str(c)}  {a}")
    if ctrl_false_positive:
        print("⚠️ 对照组出现 250 → 网关宽松，候选人结果不可采信，结论作废。")
        return 5
    print("✅ 对照组全部被拒 → 探测有区分力。")

    # ③ 候选人
    print("\n[候选邮箱]")
    r3 = probe(mx, candidates)
    hits, misses = [], []
    for a, c in r3.items():
        if c == 250:
            hits.append(a)
            print(f"   ✅ 250  {a}")
        else:
            misses.append(a)
            print(f"   ❌ {c}  {a}")

    print("\n=== 结论 ===")
    if hits:
        print(f"命中 {len(hits)} 个（控制地址250 + 非catch-all + 对照组550 + 候选250）：")
        for h in hits:
            print(f"   → {h}")
        print("   ⚠️ 采信前仍须：格式校验 + 至少另一来源交叉印证人名与职务（H3/H5）。")
    else:
        print("无命中。请勿推演凑数 —— 标『未找到』或降级 B 档。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
