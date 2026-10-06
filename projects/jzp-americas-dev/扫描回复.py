#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
客户回复扫描器
==============
按项目预设流程：**扫描收件箱 → 识别「明确意向」的回复 → 登记 → 交付给用户 → 之后不再跟进**。

流程定位（用户 2026-09-27 明确）
--------------------------------
```
写作 agent（毅冰 mail group 方法论）产出信件
        ↓
发送层（定时队列）投递
        ↓
【本脚本】扫回复 → 判断意向 → 登记 → 交付用户
        ↓
        ⛔ 到此为止，不再自动跟进
```
**用户的判断权在最后一环。** 本脚本只做「识别 + 登记 + 交付」，不代发跟进信。

意向判定标准（用户要求：**回复必须表明有意向**）
------------------------------------------------
| 级别 | 信号 | 处理 |
|---|---|---|
| ✅ **明确意向** | 表示已转/将转采购、索要资料/报价、约谈、询问具体规格 | **登记 + 交付** |
| ⚠️ 需澄清 | 反问你的意图、问合作方式（还没表态） | 登记，标注「需人工回复」 |
| 💬 弱意向 | 泛泛表示「有需求」但无具体动作 | 登记，标注「待观察」 |
| ⛔ 非意向 | 退信、自动回复、工单系统自动确认、营销邮件 | 不登记 |

用法
----
  python3 扫描回复.py                 # 扫描并登记（不发送任何东西）
  python3 扫描回复.py --days 14       # 只看最近 14 天
  python3 扫描回复.py --show          # 打印已登记记录
"""

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "客户回复登记.json"
REPORT = ROOT / "客户回复登记.md"
LAST_SCAN = ROOT / ".扫描回复-last-scan.json"
BJ = timezone(timedelta(hours=8))

# 邮件 Date 头的常见格式（用于「回溯扫描」按日期过滤）
_DATE_FMTS = (
    "%a, %d %b %Y %H:%M:%S %z",   # RFC 2822（标准）
    "%a, %d %b %Y %H:%M:%S %Z",
    "%d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M %z",
)


def parse_date(s: str):
    """把邮件 Date 头解析成带时区的 datetime；失败返回 None（不猜）。"""
    s = (s or "").strip()
    # 去掉常见后缀噪声
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    for f in _DATE_FMTS:
        try:
            dt = datetime.strptime(s, f)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


# ---- 非意向：直接跳过 ----
SKIP_SUBJECT = ("退信", "delivery status notification", "couldn't be delivered",
                "automatic reply", "auto-reply", "autoreply", "automatic response",
                "out of office", "自动回复", "vacation", "邮件已撤回",
                "登录提醒", "verification code", "password", "activity report",
                "welcome to", "启用通知", "请完成您", "assigned you an inquiry")
SKIP_FROM = ("postmaster", "mailer-daemon", "no-reply", "noreply", "donotreply",
             "notification", "jira@", "atlassian", "bounces.", "jiezougroup.com",
             "alibaba.com", "thomasnet", "linkedin.com", "exmail.weixin.qq.com",
             # 用户自己的测试邮箱（他给自己发的测试件，不是客户回复）
             "{{CONTACT_EMAIL}}", "{{CONTACT_EMAIL}}")

# ---- 明确意向信号 ----
INTENT_HIGH = [
    "pass it along to our procurement", "sent over this email to our procurement",
    "forwarded to our procurement", "our procurement team", "procurement manager",
    "send me your information", "send us your", "please send", "send over",
    "your catalog", "catalogue", "spec sheet", "quotation", "quote",
    "we are interested", "we're interested", "we would like to", "we'd like to",
    "let's discuss", "schedule a call", "set up a call", "arrange a call",
    "prequalification", "vendor registration", "supplier registration",
    "we have a requirement", "we have requirements", "our requirement",
    "request for quotation", "rfq",
]
# ---- 需澄清（反问意图，还没表态）----
INTENT_CLARIFY = [
    "was you asking", "are you asking", "are you offering", "do you sell",
    "what exactly", "could you clarify", "can you clarify", "not sure what",
    "are you looking for", "what is it you",
]
# ---- 弱意向 ----
INTENT_WEAK = [
    "we will discuss", "will revert", "keep you posted", "get back to you",
    "lot of requirements", "many requirements", "we may need", "might need",
    "possibly", "maybe later", "not right now",
    # ⚠️ 以下词过于泛化，单独出现不能算意向（如"忙着投标"≠想采购）
    "tender", "bom", "bill of material", "submission",
]
# ---- 明确拒联（触发永久排除）----
REJECT = ["remove me", "remove us", "take us off", "unsubscribe",
          "stop emailing", "do not contact", "don't contact", "not interested",
          "no need to follow up", "we're all set"]


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
    # 剥掉引用的历史邮件
    return re.split(r"\n(?:On .{10,90} wrote:|发件人[:：]|From: |_{5,}|-{5,}原始邮件)", body)[0].strip()


def classify(subj: str, frm: str, body: str) -> tuple:
    """返回 (级别, 理由, 命中句)。"""
    low = body.lower()
    for k in REJECT:
        if k in low:
            return "⛔ 拒联", "对方明确拒联", next(l for l in body.split("\n") if k in l.lower())[:160]
    for k in INTENT_HIGH:
        if k in low:
            line = next((l for l in body.split("\n") if k in l.lower()), "")
            return "✅ 明确意向", f"命中信号：{k}", line.strip()[:200]
    for k in INTENT_CLARIFY:
        if k in low:
            line = next((l for l in body.split("\n") if k in l.lower()), "")
            return "⚠️ 需澄清", f"命中信号：{k}", line.strip()[:200]
    for k in INTENT_WEAK:
        if k in low:
            line = next((l for l in body.split("\n") if k in l.lower()), "")
            return "💬 弱意向", f"命中信号：{k}", line.strip()[:200]
    if body.strip():
        return "❓ 待人工判定", "无命中信号，需人工看原文", body.strip().split("\n")[0][:160]
    return "❓ 待人工判定", "正文为空", ""


def main():
    ap = argparse.ArgumentParser(description="客户回复扫描与登记")
    ap.add_argument("--days", type=int, default=0, help="只看最近 N 天（0=全部）")
    ap.add_argument("--show", action="store_true", help="只打印已登记记录")
    args = ap.parse_args()

    if args.show:
        if not REGISTRY.exists():
            print("还没有登记记录。先跑 python3 扫描回复.py")
            return 0
        recs = json.loads(REGISTRY.read_text(encoding="utf-8"))
        print(f"已登记 {len(recs)} 条\n")
        for r in recs:
            print(f"[{r['level']}] {r['from_name']}  <{r['from_email']}>")
            print(f"   主题：{r['subject'][:70]}")
            print(f"   时间：{r['date'][:31]}")
            print(f"   理由：{r['reason'][:90]}")
            print()
        return 0

    mc = load_mailer()
    cfg = mc.load_config()
    m = mc.imap_connect(cfg)
    m.select("INBOX", readonly=True)
    typ, d = m.search(None, "ALL")
    ids = d[0].split()

    cutoff = None
    if args.days:
        cutoff = datetime.now(BJ) - timedelta(days=args.days)

    old = {}
    old_by_mail = {}
    if REGISTRY.exists():
        for r in json.loads(REGISTRY.read_text(encoding="utf-8")):
            old[r.get("key", "")] = r
            # 🔴 2026-10-01 新增：**按发件人邮箱兜底索引**。
            #    原因：`key = f"{addr}|{subj[:60]}"`，而人工补录时主题常被截断成别的长度
            #    （实测 Zeus：手录 key 用 40 字、脚本算 60 字 → key 不匹配 →
            #     `our_reply` 等自定义字段**被静默抹掉**）。
            #    同一发件人取「最新一条」作兜底。
            em = (r.get("from_email") or "").lower()
            if em:
                cur = old_by_mail.get(em)
                if cur is None or str(r.get("recorded_at") or "") >= str(cur.get("recorded_at") or ""):
                    old_by_mail[em] = r

    import email
    results = []
    for num in ids:
        raw = mc.fetch_headers(m, num, "FROM SUBJECT DATE")
        subj = mc.raw_header(raw, "Subject")
        frm = mc.raw_header(raw, "From")
        date = mc.raw_header(raw, "Date")
        low_s, low_f = subj.lower(), frm.lower()
        if any(s in low_s for s in SKIP_SUBJECT):
            continue
        if any(s in low_f for s in SKIP_FROM):
            continue
        # 🔴 2026-10-01 修复：`--days` 此前是**死代码**（cutoff 算了但循环里从没用）。
        #    现按 **Date 头**（不是 UID）判断，这才叫「回溯扫描」——
        #    UID 会随邮箱整理变动，Date 不会。
        #    ⚠️ 解析不出日期的（极少数）**不跳过**，宁可多看一封，不能漏。
        dt_msg = parse_date(date)
        if cutoff and dt_msg and dt_msg < cutoff:
            continue
        typ, dd = m.fetch(num, "(RFC822)")
        msg = email.message_from_bytes(dd[0][1], policy=email.policy.default)
        body = plain_body(msg)
        if not body:
            continue
        level, reason, quote = classify(subj, frm, body)
        name = re.sub(r"<.*?>", "", frm).strip().strip('"')
        addr = (re.search(r"<([^>]+)>", frm) or re.search(r"([^\s<>]+@[^\s<>]+)", frm))
        addr = addr.group(1) if addr else ""
        key = f"{addr}|{subj[:60]}"
        # 🔴 2026-10-01 修复：**保留老记录里的自定义字段**。
        #    此前整表重建只保留 recorded_at / delivered，
        #    导致人工补录的 `our_reply`（我方回复要点）、`next`（下一步）等字段**被静默抹掉**。
        #    匹配顺序：① 完整 key ② 发件人邮箱兜底（防主题截断长度不一致）。
        prev = old.get(key) or old_by_mail.get((addr or "").lower()) or {}
        # 人工设定的「非脚本词表内」级别要保住（如 ℹ️ 善意引荐 / 🔻 暂不 / 已报价）
        SCRIPT_LEVELS = {"✅ 明确意向", "⛔ 拒联", "⚠️ 需澄清", "💬 弱意向", "❓ 待人工判定", "⛔ 拒联（永久）"}
        manual_level = prev.get("level") if prev.get("level") not in SCRIPT_LEVELS else None
        rec = dict(prev)                      # 先继承老记录（含自定义字段）
        rec.update({                          # 再覆盖本次扫描出来的字段
            "key": key, "level": manual_level or level, "date": date, "from_name": name,
            "from_email": addr, "subject": subj, "reason": reason,
            "quote": quote, "body_excerpt": body[:1200],
            "recorded_at": prev.get("recorded_at")
                           or datetime.now(BJ).strftime("%Y-%m-%d %H:%M"),
            "delivered": prev.get("delivered", False),
        })
        if manual_level:
            rec["level_note"] = "级别由人工设定，脚本不覆盖"
        # 标记「本次扫描新发现」（老记录里没有 → 新的）
        rec["first_seen"] = prev.get("first_seen") or \
            datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
        results.append(rec)
    m.logout()

    # 同线程去重：同一发件人 + 归一化主题。
    # ⚠️ 不能简单「保留最新」——意向信号可能在更早那封里
    #   （如 {{CONTACT_NAME}}：第一封说"转给采购经理"，第二封只说"Sounds good"）。
    # 规则：保留「意向级别最高」的那封；同级时保留最新。
    _pri = {"✅ 明确意向": 0, "⛔ 拒联": 1, "⚠️ 需澄清": 2, "💬 弱意向": 3, "❓ 待人工判定": 4}
    seen = {}
    for r in sorted(results, key=lambda x: x["date"]):
        base = re.sub(r"^(?:(?:re|fw|fwd|回复|转发)\s*[:：]\s*)+", "", r["subject"], flags=re.I).strip().lower()
        k = f"{r['from_email'].lower()}|{base[:50]}"
        cur = seen.get(k)
        if cur is None or _pri.get(r["level"], 9) <= _pri.get(cur["level"], 9):
            seen[k] = r
    results = list(seen.values())

    # 🔴 2026-10-01 新增：**「本次新发现」与「回溯覆盖区间」**
    #    背景：2026-09-30 {{COMPANY}} 的「明确意向」询盘被漏登记 41 小时 ——
    #    原因是**对方回信晚于登记表最后更新时间**（时间窗错配），不是漏看。
    #    所以这里明确报出「本次扫描的时间区间」+「哪些是新的」，
    #    让「有没有漏」这件事**看得见**。
    prev_scan = None
    if LAST_SCAN.exists():
        try:
            prev_scan = json.loads(LAST_SCAN.read_text(encoding="utf-8")).get("last_scan_at")
        except Exception:
            prev_scan = None
    newly = [r for r in results if r.get("first_seen") == datetime.now(BJ).strftime("%Y-%m-%d %H:%M")]
    LAST_SCAN.write_text(json.dumps({
        "last_scan_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M"),
        "scanned_days": args.days or "all",
        "total_registered": len(results),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    order = {"✅ 明确意向": 0, "⛔ 拒联": 1, "⚠️ 需澄清": 2, "💬 弱意向": 3, "❓ 待人工判定": 4}
    results.sort(key=lambda r: (order.get(r["level"], 9), r["date"]), reverse=False)

    # 🔴 2026-10-01 关键修复：**登记表是「累计记录」，不是「本次扫描结果」**。
    #    此前直接 `REGISTRY.write_text(results)` → 用 `--days 1` 扫一次，
    #    就会把窗口外的历史记录**全部删掉**（实测把 7 条清成 0 条）。
    #    改为：以「老记录」为基底，用本次扫描结果**覆盖同一条**，其余保留。
    merged = {}
    for r in json.loads(REGISTRY.read_text(encoding="utf-8")) if REGISTRY.exists() else []:
        merged[r.get("key", "")] = r
    for r in results:
        merged[r["key"]] = r
    # 🔴 2026-10-01 补：**按发件人邮箱去重**。
    #    `key` 含主题前 60 字，人工补录时主题长度可能不同 → 同一个人会出现两条
    #    （实测 Zeus 出现 2 条）。去重时**优先保留字段更多的那条**
    #    （即含 our_reply 等人工字段的），并把另一条的空字段补进来。
    by_mail = {}
    for r in merged.values():
        em = (r.get("from_email") or "").lower()
        if not em:
            by_mail[r.get("key", "")] = r
            continue
        cur = by_mail.get(em)
        if cur is None:
            by_mail[em] = r
            continue
        rich, poor = (r, cur) if len(r) > len(cur) else (cur, r)
        for k, v in poor.items():
            rich.setdefault(k, v)
        by_mail[em] = rich
    results = sorted(by_mail.values(), key=lambda r: (order.get(r["level"], 9), r["date"]))

    REGISTRY.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 生成可读报告 ----
    L = ["# 客户回复登记", "",
         f"> 扫描时间：{datetime.now(BJ):%Y-%m-%d %H:%M}（北京）｜ 共 {len(results)} 条",
         "> 流程：**识别意向 → 登记 → 交付用户 → 之后不再自动跟进**", ""]
    groups = {}
    for r in results:
        groups.setdefault(r["level"], []).append(r)
    for lv in ["✅ 明确意向", "⛔ 拒联", "⚠️ 需澄清", "💬 弱意向", "❓ 待人工判定"]:
        if lv not in groups:
            continue
        L.append(f"## {lv}（{len(groups[lv])} 条）")
        L.append("")
        for r in groups[lv]:
            L.append(f"### {r['from_name']}  ·  `{r['from_email']}`")
            L.append("")
            L.append(f"- **时间**：{r['date']}")
            L.append(f"- **主题**：{r['subject']}")
            L.append(f"- **判定理由**：{r['reason']}")
            if r["quote"]:
                L.append(f"- **关键原句**：> {r['quote']}")
            L.append("")
            L.append("<details><summary>回复原文（前 1200 字）</summary>")
            L.append("")
            L.append("```")
            L.append(r["body_excerpt"])
            L.append("```")
            L.append("</details>")
            L.append("")
    REPORT.write_text("\n".join(L), encoding="utf-8")

    print(f"扫描完成，登记 {len(results)} 条")
    print(f"  本次回溯区间：{'最近 %d 天' % args.days if args.days else '全部'}"
          f"｜上次扫描：{prev_scan or '（首次）'}")
    print()
    if newly:
        print(f"🆕 本次新发现 {len(newly)} 条：")
        for r in newly:
            print(f"   [{r['level']}] {r['from_name']} <{r['from_email']}>  {r['date'][:31]}")
        print()
    else:
        print("🆕 本次没有新发现（与上次扫描相比无新增）")
        print()
    for lv in ["✅ 明确意向", "⛔ 拒联", "⚠️ 需澄清", "💬 弱意向", "❓ 待人工判定"]:
        if lv in groups:
            print(f"  {lv}：{len(groups[lv])} 条")
    print()
    if "✅ 明确意向" in groups:
        print("★ 需交付给你的明确意向客户：")
        for r in groups["✅ 明确意向"]:
            print(f"   {r['from_name']}  <{r['from_email']}>")
            print(f"      {r['quote'][:88]}")
    print()
    print(f"明细：{REPORT}")
    print(f"数据：{REGISTRY}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
