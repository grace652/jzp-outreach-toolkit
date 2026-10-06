#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发送前地址验证器
================
在发信前把「死地址」剔掉，降低退信率。

为什么需要它
------------
实测用户邮箱里 14 个退信地址，**7 个是角色邮箱（info@/contact@）、2 个是 ISP 邮箱**，
A 档具名公司邮箱一个都没退。→ 低档位邮箱需要发前验证。

三层验证（可靠性递减，用时递增）
--------------------------------
| 层 | 手段 | 可靠性 | 耗时 | 说明 |
|---|---|---|---|---|
| L1 | 语法 + 规则 | 高 | 瞬间 | 格式、一次性邮箱域名、角色邮箱标注 |
| L2 | **MX 查询** | **高** | ~0.2s | 域名没有 MX = 收不了信 = 死域名 |
| L3 | SMTP RCPT 探活 | **低** | ~5-20s | ⚠️ 大厂会回假 250，见下 |

🔴 **L3 的可靠性必须说清楚**
--------------------------------
Gmail、Microsoft 365、Yahoo 等**为了防地址采集，对任何 RCPT TO 都回 250**。
所以「探活返回 250」**不能证明邮箱存在**，只能证明服务器收下了这个请求。

因此本工具的判定逻辑是：
- **无 MX** → ⛔ 确定不发（可靠）
- **RCPT 明确 5xx** → ⛔ 确定不发（可靠）
- **RCPT 250 且非 catch-all** → ✅ 可发（较可靠）
- **RCPT 250 但是 catch-all** → ⚠️ 存疑（无法判定）
- **灰名单 / 超时 / 大厂假 250** → ⚠️ 存疑

⚠️ **探活本身有风险**：短时间大量 RCPT 探测会被对方视为地址采集，可能损害发信 IP 信誉。
**务必限速**（本工具默认 3 秒/地址），且只对低档位地址用。

用法
----
  python3 地址验证.py {{CONTACT_EMAIL}} {{CONTACT_EMAIL}}          # 完整验证（L1+L2+L3）
  python3 地址验证.py --mx-only {{CONTACT_EMAIL}}        # 只做 L1+L2（快、安全）
  python3 地址验证.py --queue                  # 验证发信队列里的所有地址
  python3 地址验证.py --queue --mx-only        # 队列 + 只查 MX
  python3 地址验证.py --batch 地址列表.txt      # 从文件读地址（每行一个）
"""

import argparse
import importlib.util
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "发信队列.json"
RESULT = ROOT / "地址验证结果.json"

SYNTAX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
ROLE_LOCAL = {"info", "contact", "feedback", "supplier", "sales", "support",
              "admin", "office", "enquiries", "inquiries", "service", "help",
              "mail", "hello", "team", "hr", "accounts", "billing"}
# 一次性/临时邮箱域名（命中 → 不发）
DISPOSABLE = {"mailinator.com", "guerrillamail.com", "10minutemail.com",
              "tempmail.com", "throwaway.email", "yopmail.com", "trashmail.com",
              "sharklasers.com", "getnada.com", "maildrop.cc", "temp-mail.org"}
# 已知收不了信/无效的 TLD
BAD_TLD = {"invalid", "local", "test", "example", "localhost"}

# 大厂域名（RCPT 会回假 250，探活无意义）
FALSE_250_HINT = ("google.com", "outlook.com", "protection.outlook.com",
                  "yahoo.com", "yahoodns.net", "mimecast.com", "pphosted.com",
                  "barracudanetworks.com", "proofpoint.com")


def dig_mx(domain: str) -> list:
    """查 MX 记录。返回 [(优先级, 主机名), ...]，按优先级排序。

    会过滤掉不合法的主机名（实测沙箱 DNS 偶尔返回 `~` 之类的异常值）。
    注意：`0 .` 是「null MX」——域名声明自己不收信，同样视为不可用。
    """
    try:
        out = subprocess.run(["/usr/bin/dig", "+short", "MX", domain],
                             capture_output=True, text=True, timeout=12).stdout
    except Exception:
        return []
    rows = []
    for line in out.strip().split("\n"):
        parts = line.split()
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        host = parts[1].rstrip(".")
        # 合法性校验：必须有至少一个点，且只含合法字符
        if host in ("", ".") or "." not in host:
            continue
        if not re.fullmatch(r"[A-Za-z0-9._-]+", host):
            continue
        rows.append((int(parts[0]), host))
    return sorted(rows)


def smtp_probe(mx_host: str, addr: str, timeout: int = 12) -> tuple:
    """SMTP RCPT 探活。返回 (判定, 说明)。

    判定值：'exists' / 'no_such' / 'greylist' / 'unknown' / 'conn_fail'
    """
    try:
        s = socket.create_connection((mx_host, 25), timeout=timeout)
    except Exception as e:
        return "conn_fail", f"连不上 {mx_host}:25（{type(e).__name__}）"

    def cmd(line, expect=None):
        if line:
            s.sendall((line + "\r\n").encode())
        buf = b""
        while True:
            chunk = s.recv(1024)
            if not chunk:
                break
            buf += chunk
            # 多行响应：末行是 "250 xxx"（第 4 个字符是空格）
            if len(buf) >= 4 and buf[3:4] == b" ":
                break
        return buf.decode("utf-8", errors="replace").strip()

    try:
        banner = cmd(None)
        if not banner.startswith("220"):
            return "unknown", f"banner 异常：{banner[:60]}"
        cmd("EHLO jiezougroup.com")
        code = cmd("MAIL FROM:<{{SENDER_EMAIL}}>")[:3]
        if code != "250":
            return "unknown", f"MAIL FROM 被拒：{code}"
        resp = cmd(f"RCPT TO:<{addr}>")
        code = resp[:3]
        if code in ("250", "251"):
            return "exists", resp[:90]
        if code in ("450", "451", "452"):
            return "greylist", f"灰名单/临时：{resp[:80]}"
        if code.startswith("5"):
            return "no_such", resp[:90]
        return "unknown", resp[:80]
    except Exception as e:
        return "unknown", f"{type(e).__name__}: {e}"
    finally:
        try:
            s.sendall(b"QUIT\r\n")
        except Exception:
            pass
        s.close()


def catchall_probe(mx_host: str, domain: str) -> bool:
    """用一个几乎不可能存在的随机地址试探，若也回 250 → 该域是 catch-all。"""
    import random, string
    fake = "".join(random.choices(string.ascii_lowercase, k=18)) + "@" + domain
    verdict, _ = smtp_probe(mx_host, fake)
    return verdict == "exists"


def verify(addr: str, do_probe: bool, polite_delay: float) -> dict:
    r = {"address": addr, "verdict": "", "level": "", "notes": []}

    # ---- L1 语法与规则 ----
    if not SYNTAX.match(addr):
        r["verdict"], r["level"] = "⛔ 不发", "L1"
        r["notes"].append("语法不合法")
        return r
    local, _, domain = addr.rpartition("@")
    domain = domain.lower()
    if domain in DISPOSABLE:
        r["verdict"], r["level"] = "⛔ 不发", "L1"
        r["notes"].append("一次性/临时邮箱域名")
        return r
    if domain.rsplit(".", 1)[-1] in BAD_TLD:
        r["verdict"], r["level"] = "⛔ 不发", "L1"
        r["notes"].append("无效 TLD")
        return r
    if local.lower() in ROLE_LOCAL:
        r["notes"].append("角色邮箱（B 档）")

    # ---- L2 MX ----
    mxs = dig_mx(domain)
    if not mxs:
        r["verdict"], r["level"] = "⛔ 不发", "L2"
        r["notes"].append("域名没有 MX 记录 → 收不了信")
        return r
    r["mx"] = [h for _, h in mxs][:2]
    r["notes"].append(f"MX：{', '.join(r['mx'])}")

    if not do_probe:
        r["verdict"], r["level"] = "✅ 可发（仅查 MX）", "L2"
        return r

    # ---- L3 SMTP 探活 ----
    mx = mxs[0][1]
    if any(h in mx for h in FALSE_250_HINT):
        r["notes"].append(f"MX 属大厂（{mx}）→ RCPT 一律回 250，探活不可信")
        r["verdict"], r["level"] = "⚠️ 存疑（大厂假 250）", "L3"
        return r

    time.sleep(polite_delay)
    verdict, detail = smtp_probe(mx, addr)
    r["probe"] = detail
    if verdict == "no_such":
        r["verdict"], r["level"] = "⛔ 不发", "L3"
        r["notes"].append(f"服务器明确拒收：{detail[:70]}")
        return r
    if verdict == "exists":
        time.sleep(polite_delay)
        if catchall_probe(mx, domain):
            r["verdict"], r["level"] = "⚠️ 存疑（catch-all）", "L3"
            r["notes"].append("该域是 catch-all，任何地址都回 250 → 无法判定")
        else:
            r["verdict"], r["level"] = "✅ 可发", "L3"
        return r
    if verdict == "greylist":
        r["verdict"], r["level"] = "⚠️ 存疑（灰名单）", "L3"
        r["notes"].append(detail[:80])
        return r
    r["verdict"], r["level"] = "⚠️ 存疑", "L3"
    r["notes"].append(detail[:80])
    return r


def main():
    ap = argparse.ArgumentParser(description="发送前地址验证")
    ap.add_argument("addresses", nargs="*", help="要验证的邮箱地址")
    ap.add_argument("--mx-only", action="store_true", help="只做 L1+L2（快、安全，不探活）")
    ap.add_argument("--queue", action="store_true", help="验证发信队列里的地址")
    ap.add_argument("--batch", help="从文件读地址，每行一个")
    ap.add_argument("--delay", type=float, default=3.0, help="探活间隔秒数，默认 3")
    args = ap.parse_args()

    addrs = list(args.addresses)
    if args.batch:
        addrs += [l.strip() for l in Path(args.batch).read_text(encoding="utf-8").split("\n")
                  if l.strip() and "@" in l]
    if args.queue:
        if QUEUE.exists():
            q = json.loads(QUEUE.read_text(encoding="utf-8"))
            for i in q:
                if i.get("status") in ("pending", "blocked"):
                    addrs += i.get("to", [])
        else:
            print("找不到发信队列，先跑 定时发送.py --build")
    addrs = list(dict.fromkeys(addrs))          # 去重保序

    if not addrs:
        print("没有要验证的地址。用法见文件头。")
        return 1

    do_probe = not args.mx_only
    print(f"验证 {len(addrs)} 个地址"
          f"（{'L1+L2+L3 含探活' if do_probe else 'L1+L2 仅查 MX'}）\n")

    results = []
    for a in addrs:
        r = verify(a, do_probe, args.delay)
        results.append(r)
        print(f"  {r['verdict']:<22}{a}")
        for n in r["notes"]:
            print(f"      · {n}")

    RESULT.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print()
    bad = [r for r in results if r["verdict"].startswith("⛔")]
    doubt = [r for r in results if r["verdict"].startswith("⚠️")]
    good = [r for r in results if r["verdict"].startswith("✅")]
    print(f"结果：✅ 可发 {len(good)} ／ ⚠️ 存疑 {len(doubt)} ／ ⛔ 不发 {len(bad)}")
    print(f"明细：{RESULT}")
    if bad:
        print()
        print("建议剔除的地址：")
        for r in bad:
            print(f"  {r['address']}   （{r['notes'][-1][:60]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
