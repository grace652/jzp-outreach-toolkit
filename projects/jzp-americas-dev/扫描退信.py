#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
退信扫描器
==========
扫描 `{{SENDER_EMAIL}}` 收件箱，识别**退信（DSN / bounce）**，提取失败地址与
原始 SMTP 报错，分类后并入 `退信黑名单.json`（`定时发送.py` 的退信闸门数据源），
并重新生成两份**可随时查阅**的报告：

    · 退信处理清单.md   —— 人工可读（沿用原文件结构）
    · 退信报告.html     —— 配色面板，便于快速浏览

为什么需要它
------------
项目此前**没有退信扫描脚本**：`扫描回复.py` 的 SKIP_SUBJECT 明确跳过退信，
只能靠人工翻邮箱 + 手改 JSON。本脚本把这条链路固化下来。

流程定位
--------
    发送层投递 → 收件端退信 → 【本脚本】扫描 → 入库 → 闸门自动拦截后续投递

只读原则
--------
全程 `BODY.PEEK`，**不标已读、不改动邮箱内任何邮件**。

用法
----
  python3 扫描退信.py                # 扫描并入库（同时刷新两份报告）
  python3 扫描退信.py --dry-run      # 只看结果，不写任何文件
  python3 扫描退信.py --days 7       # 只回看最近 7 天
  python3 扫描退信.py --show         # 只打印当前黑名单，不连邮箱
"""

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BLACKLIST = ROOT / "退信黑名单.json"
REPORT_MD = ROOT / "退信处理清单.md"
REPORT_HTML = ROOT / "退信报告.html"
BJ = timezone(timedelta(hours=8))
SELF_DOMAIN = "jiezougroup.com"

# 扫描范围（腾讯企业邮实测文件夹名）。
# Junk 可能吞掉退信；Deleted Messages 是回收站（实测无退信，但保留以防误删）。
FOLDERS = ["INBOX", "Junk", '"Deleted Messages"']

# 冷却期与 `定时发送.py` 保持一致（本脚本不重新定义语义，只引用）
COOLDOWN_DAYS = {
    "硬退信-地址不存在": None,
    "软退信-暂时停用": 30,
    "软退信-服务商拒收": 14,
    "待人工判定": 30,
}
CAT_ORDER = ["硬退信-地址不存在", "软退信-服务商拒收", "软退信-暂时停用", "待人工判定"]


# ---------------------------------------------------------------- 模块加载

def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 识别退信

# 命中其一即视为退信（主题或发件人）
BOUNCE_SUBJECT = (
    "退信", "退信通知", "无法投递", "不能投递", "未送达", "投递失败",
    "delivery status notification", "undelivered", "undeliverable",
    "couldn't be delivered", "could not be delivered", "wasn't delivered",
    "returned mail", "mail delivery failed", "delivery failure",
    "failure notice", "returned to sender", "delivery has failed",
    "message not delivered", "delivery incomplete",
)
BOUNCE_FROM = ("mailer-daemon", "postmaster", "mail-daemon", "maildaemon")

# 🔴 严格地址校验：抽取结果必须**整体**长得像个邮箱地址。
# 背景（实测 bug）：退信正文里有一句「请联系你的收件人（{{CONTACT_EMAIL}}）或其所在服务商。」
#   宽松模式 `^\s*([^\s,;<>]+@[^\s,;<>]+)\s*$` 会把**整行**当成地址抓进来，
#   产出 `请联系你的收件人（{{CONTACT_EMAIL}}）或其所在服务商。` 这种垃圾，
#   还会污染整域封锁的域名解析。故所有候选一律过这道闸。
ADDR_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
                     r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+$")

# 正文里抽取失败收件人的模式（按可靠性排序）
RECIP_PATTERNS = [
    r"Final-Recipient:\s*rfc822;\s*([^\s;<>]+@[^\s;<>]+)",
    r"X-Failed-Recipients:\s*([^\s,;<>]+@[^\s,;<>]+)",
    r"收件人邮件地址[（(]\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)\s*[）)]",
    r"收件人[（(]\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)\s*[）)]",
    # 腾讯企业邮「定时邮件退信通知」格式：`收件人：{{CONTACT_EMAIL}}`
    r"收件人[：:]\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    r"以下收件人[^：:]*[：:]\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    # Mimecast/EXO 网关格式：`The message you sent to xxx@yyy couldn't be delivered`
    r"you sent to\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    r"wasn'?t delivered to\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    r"could not be delivered to\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    r"not delivered to\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    r"delivery to\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)\s+failed",
    r"your message to\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    r"message to\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)\s+(?:cannot|can't|was not)",
    r"failed recipient[s]?[：:]\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)",
    # 兜底：裸地址（必须独占一行，且严格符合 ADDR_RE）
    r"^\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\s*$",
]

# 原始信件主题（用于回溯是哪封）
ORIG_SUBJECT_PATTERNS = [
    r"^\s*Subject:\s*(.+)$",
    r"原邮件主题[：:]\s*(.+)$",
    r"原始邮件主题[：:]\s*(.+)$",
    r"邮件主题[：:]\s*(.+)$",
    # 腾讯/QQ 退信把原主题写成「主 题：xxx」（中间有空格）
    r"^\s*主\s*题[：:]\s*(.+)$",
]

# 分类：按「先硬后软」顺序匹配
HARD_KEYS = (
    "5.1.1", "550 5.1.1", "address could not be found", "mailbox not found",
    "mailbox unavailable", "no such user", "nosuchuser", "user unknown",
    "does not exist", "recipient address rejected: user unknown",
    "地址不存在", "不存在", "could not be found", "unknown user",
    "invalid recipient", "unrouteable address", "no mailbox",
)
DISABLED_KEYS = (
    "554.30", "554 30", "mailbox is disabled", "暂时停用", "disabled",
    "account is disabled", "account disabled", "suspended",
)
SOFT_KEYS = (
    "5.4.1", "5.7.1", "access denied", "accessdenied", "服务商拒收",
    "拒绝接收", "拒收", "blocked", "blacklist", "spam", "policy",
    "rejected", "quota", "rate limit", "greylist", "temporarily",
    "deferred", "try again later", "4.7.1",
)

# 🔴 体积型退信 —— **不计入黑名单**（2026-10-02 用户明确要求）
#
# 成因：**我方附件过大**，收件方服务器按收件人配额拒收。**与收件地址本身无关**。
# 实测样本（Purcee / {{CONTACT_EMAIL}}，2026-10-02）：
#   `550 5.2.3 RESOLVER.RST.RecipSizeLimit; message too large for this recipient`
#   `Your message is too large to send … The maximum message size that's allowed is 36 MB.
#    This message is 67 MB.`
#
# 为什么必须排除：`classify()` 对这类文本**匹配不到任何关键词** → 落到「待人工判定」
# → **30 天冷却封锁** → 把刚回信的**热线索误锁一个月**。这是最坏的一种误判。
#
# 处置：**跳过，不入库、不进报告、不写任何文件**（只在控制台提示一句）。
# 真正要修的是**附件体积**，不是客户地址。
SIZE_KEYS = (
    "message too large", "messagesizeexceeded", "message size exceeds",
    "recipsizelimit", "5.2.3", "exceeds the maximum message size",
    "maximum message size", "message is too large", "attachment size",
    "exceeds size limit", "邮件过大", "附件过大", "邮件大小超出",
)


def is_size_bounce(text: str) -> bool:
    """体积型退信 = 我方附件超限，**不是地址问题** → 一律不记入黑名单。"""
    low = (text or "").lower()
    return any(k.lower() in low for k in SIZE_KEYS)


def classify(text: str) -> str:
    low = (text or "").lower()
    if any(k.lower() in low for k in HARD_KEYS):
        return "硬退信-地址不存在"
    if any(k.lower() in low for k in DISABLED_KEYS):
        return "软退信-暂时停用"
    if any(k.lower() in low for k in SOFT_KEYS):
        return "软退信-服务商拒收"
    return "待人工判定"


def extract_recipients(text: str) -> list:
    """按可靠性顺序抽取候选失败地址（去重保序）。"""
    out = []
    for pat in RECIP_PATTERNS:
        for m in re.finditer(pat, text, re.I | re.M):
            a = m.group(1).strip().strip("<>").strip(".,;:").lower()
            if not ADDR_RE.match(a):          # 🔴 严格校验，挡住「整行被当成地址」的垃圾
                continue
            if a in out:
                continue
            if a.endswith("@" + SELF_DOMAIN) or "jiezougroup" in a:
                continue
            if a.startswith(("mailer-daemon@", "postmaster@")):
                continue
            out.append(a)
    return out


def extract_orig_subject(text: str) -> str:
    for pat in ORIG_SUBJECT_PATTERNS:
        m = re.search(pat, text, re.I | re.M)
        if m:
            s = m.group(1).strip()
            # 腾讯格式会把下一行「时 间：…」也吃进来 → 在它前面截断
            s = re.split(r"\s*时\s*间[：:]", s)[0].strip()
            if s and "mailer-daemon" not in s.lower():
                return s[:120]
    return ""


CSS_RE = re.compile(r"@media[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", re.S)


def make_reason(blob: str, addr: str) -> str:
    """从退信正文里截出一段**人能看懂**的原因。

    🔴 两个坑（实测）：
      1. 腾讯企业邮的退信正文**以 CSS 开头**（`@media (max-width:420px){…}`），
         直接取前 280 字会全是样式表，看不到任何退信原因。
      2. 直接按关键词取前后 60/220 字会**从词中间切断**（出现「接收。」这种残句）。
    """
    t = CSS_RE.sub(" ", blob)
    t = " ".join(t.split())
    for key in ("said:", "Access denied", "不存在", "does not exist",
                "permanent failure", "5.4.1", "5.1.1", "554", "550"):
        i = t.find(key)
        if i < 0:
            continue
        s = max(0, i - 90)
        cuts = [t.rfind(ch, 0, s) for ch in "。；;."]
        cuts = [c for c in cuts if c >= 0]
        if cuts:
            s = max(cuts) + 1
        return t[s:i + 200].strip()
    if addr:
        i = t.lower().find(addr.lower())
        if i >= 0:
            return t[max(0, i - 140):i + 160].strip()
    return t[:280]


# 🔴 截断点：退信正文之后会**引用原始邮件全文**（含我们自己的 To/Cc）。
# 若在整段里抽地址，会把「我们抄送过、但并未退信」的地址也算成退信（假阳性）。
# 实测：`{{CONTACT_EMAIL}}` 的 9/29 退信里，9/23 那封的引用块也含它 →
# 会把 9/23 的退信误记成 walt@ 的退信。故只扫**退信正文段**。
ORIG_MARKERS = [
    r"-{2,}\s*原始邮件\s*-{2,}",
    r"={2,}\s*原始邮件\s*={2,}",
    r"-{2,}\s*Original Message\s*-{2,}",
    r"-{2,}\s*Forwarded message\s*-{2,}",
    r"-{2,}\s*原始邮件\s*$",
    r'^\s*From:\s*"?{{SENDER_NAME}}',
    r'^\s*From:\s*"?周浩然',
    r"^\s*From:\s*ian@jiezougroup\.com",
]


def dsn_portion(blob: str) -> str:
    """只保留退信正文段，砍掉后面引用的原始邮件。"""
    cut = len(blob)
    for pat in ORIG_MARKERS:
        m = re.search(pat, blob, re.I | re.M)
        if m:
            cut = min(cut, m.start())
    return blob[:cut]


def plain_body(msg) -> str:
    """取退信可读正文。

    🔴 必须覆盖三种载体（实测踩过）：
      1. `text/plain` / `text/html` —— 人读的退信说明
      2. **`message/delivery-status`** —— 标准 DSN 的机器段，`Final-Recipient:` /
         `Status:` / `Diagnostic-Code:` 都在这里。**漏掉它 → 拿不到失败地址**。
         实测：postmaster 的「Your message couldn't be delivered」全是这种结构，
         只读 text/plain 会一个字都抽不到。
      3. 腾讯企业邮的退信是**单个 base64 的 text/html**，没有 text/plain。
    """
    import html as H
    chunks = []
    for p in msg.walk():
        ct = p.get_content_type()
        if ct == "message/delivery-status":
            try:
                for blk in p.get_payload():
                    chunks.append(blk.as_string() if hasattr(blk, "as_string") else str(blk))
            except Exception:
                pass
        elif ct == "text/plain":
            try:
                chunks.append(p.get_content())
            except Exception:
                pass
        elif ct == "text/html":
            try:
                chunks.append(re.sub(r"<[^>]+>", " ", H.unescape(p.get_content())))
            except Exception:
                pass
    body = "\n".join(chunks)
    body = re.sub(r"[ \t]+", " ", body or "")
    return re.sub(r"\n{3,}", "\n\n", body).strip()


# ---------------------------------------------------------------- 黑名单合并

def parse_bl_date(s: str):
    """解析 `Wed, 23 Sep 2026 13:27:37 +0800` → 带时区的 datetime。"""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        return datetime.strptime(s[:16].strip(), "%a, %d %b %Y").replace(tzinfo=BJ)
    except Exception:
        return None


def fmt_date(dt) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z") if dt else ""


def norm_date(s: str) -> str:
    """把日期归一化成 UTC `YYYY-MM-DD HH:MM`。

    🔴 为什么必须归一化：同一个退信事件，头里的 `Date` 可能是
    `Thu, 17 Sep 2026 07:00:16 -0700`，而库里存的是 `+0800` 写法 ——
    **同一时刻、字符串不同**。若按原始字符串比对，会被误判为「新退信」而重复计数。
    """
    d = parse_bl_date(s)
    if d is None:
        return (s or "")[:16]
    if d.tzinfo is None:
        d = d.replace(tzinfo=BJ)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def load_blacklist_raw() -> list:
    if not BLACKLIST.exists():
        return []
    try:
        return json.loads(BLACKLIST.read_text(encoding="utf-8"))
    except Exception:
        return []


def merge(existing: list, found: list) -> tuple:
    """把扫描结果并入现有黑名单。返回 (合并后列表, 变更说明)。"""
    idx = {r["address"].lower(): r for r in existing if r.get("address")}
    notes = []
    for f in found:
        a = f["address"].lower()
        d = f["first_date"]
        if a in idx:
            rec = idx[a]
            # 🔴 计数按「**不同退信日期**」算，不按扫描次数。
            #    背景（实测 bug）：退信邮件长期留在收件箱，每跑一次扫描都会重新命中；
            #    若直接 count+1，重扫一次就把所有历史退信的次数都抬高 1，数据失真。
            #    故用 seen_dates 记录已见过的退信日期；同一封邮件重扫不会重复计数。
            seen = rec.get("seen_dates")
            if not seen:
                # 兼容旧记录（无 seen_dates）：以 first_date 初始化，**不**改变既有 count
                seen = [norm_date(rec.get("first_date", ""))] if rec.get("first_date") else []
            key = norm_date(d)
            is_new_event = bool(key) and key not in seen
            if is_new_event:
                seen.append(key)
                rec["count"] = int(rec.get("count", 1)) + 1
            rec["seen_dates"] = seen
            # 末次退信取**最新**；首次退信取**最早**
            # 🔴 旧记录只有 first_date、没有 last_date —— 必须先补齐，
            #    否则 `last_date is None` 会把**更早**的退信误当成"最新"，
            #    导致冷却日算早（实测：walt@ 的 9/23 退信把 9/29 的锚点顶掉了）。
            if not rec.get("last_date"):
                rec["last_date"] = rec.get("first_date", "")
            prev_last = parse_bl_date(rec.get("last_date") or "")
            prev_first = parse_bl_date(rec.get("first_date") or "")
            inc = parse_bl_date(d)
            if inc and (prev_last is None or inc > prev_last):
                rec["last_date"] = d
                rec["last_reason"] = f["reason"]
            if inc and prev_first and inc < prev_first:
                # 实测：同一封退信可同时报多个失败地址 ——
                # `{{COMPANY_DOMAIN}}` 的 9/23 退信里同时有 jchamblee@ 与 walt@，
                # 但项目原记录只登记了 jchamblee@。故首次日期可能被"补早"。
                rec["first_date"] = d
            # 分类升级：待人工判定 → 有明确分类时覆盖
            if rec.get("category") == "待人工判定" and f["category"] != "待人工判定":
                rec["category"] = f["category"]
                rec["reason"] = f["reason"]
                notes.append(f"  ↻ {a}：分类由「待人工判定」修正为「{f['category']}」")
            elif not rec.get("reason") and f.get("reason"):
                rec["reason"] = f["reason"]      # 旧记录原因为空 → 补上
            if is_new_event:
                notes.append(f"  +1 {a}（新退信 {d[:16]}，累计 {rec['count']} 次）")
        else:
            rec = dict(f)
            rec["last_date"] = d
            rec["seen_dates"] = [norm_date(d)] if d else []
            rec["orig_subject"] = f.get("_orig_subject", "")
            existing.append(rec)
            idx[a] = rec
            notes.append(f"  ＋ {a}：{f['category']}（{d[:16]}）")

    # ---- 整域封锁：同域 ≥2 个不同地址退信 ----
    by_dom = {}
    for r in existing:
        a = r.get("address", "")
        if "@" not in a:
            continue
        by_dom.setdefault(a.split("@")[-1].lower(), set()).add(a.lower())
    for dom, addrs in by_dom.items():
        if len(addrs) < 2:
            continue
        for r in existing:
            if r.get("address", "").lower().split("@")[-1] == dom:
                if r.get("block_scope") != "domain":
                    notes.append(f"  🔒 {r['address']}：新增整域封锁（{dom} 已累计 {len(addrs)} 个地址退信）")
                r["domain"] = dom
                r["block_scope"] = "domain"
                r["domain_note"] = f"该域已累计 {len(addrs)} 个地址退信，整域封锁"
    return existing, notes


def cooldown_end(rec: dict):
    """返回冷却到期日（None = 永久）。"""
    days = COOLDOWN_DAYS.get(rec.get("category", "待人工判定"), 30)
    if days is None:
        return None
    anchor = parse_bl_date(rec.get("last_date") or rec.get("first_date", ""))
    if anchor is None:
        return None
    return anchor + timedelta(days=days)


# ---------------------------------------------------------------- 报告

def render_md(items: list, scanned: int, found_n: int, added_n: int) -> str:
    now = datetime.now(BJ)
    groups = {}
    for r in items:
        groups.setdefault(r.get("category", "待人工判定"), []).append(r)
    for v in groups.values():
        v.sort(key=lambda r: r.get("address", ""))

    roles = [r["address"] for r in items
             if r.get("address", "").split("@")[0].lower() in
             ("info", "contact", "sales", "support", "feedback", "supplier",
              "admin", "office", "hello", "service", "enquiries", "enquiry")]
    blocked_domains = sorted({r["domain"] for r in items
                              if r.get("block_scope") == "domain" and r.get("domain")})

    L = ["# 退信处理清单", "",
         f"> 数据来源：`扫描退信.py` 实测扫描 `{{SENDER_EMAIL}}` 收件箱",
         f"> 最近扫描：**{now:%Y-%m-%d %H:%M}（北京）**｜ 收件箱命中 **{scanned}** 封退信 / **{found_n}** 个地址"
         f"（其中新增 **{added_n}** 个）｜ 库内共 **{len(items)}** 个地址",
         "> 机器可读版：`退信黑名单.json`（`定时发送.py` 自动读取）",
         "> 可查阅面板：`退信报告.html`", "",
         "---", "",
         "## 一、怎么分类（决定怎么处理）", "",
         "| 类别 | 含义 | 处理 | 冷却期 |", "|---|---|---|---|",
         "| **硬退信-地址不存在** | 地址本身是错的 | ⛔ **永久排除**，不要再发 | 永久 |",
         "| **软退信-服务商拒收** | 地址可能有效，但对方服务器拒收 | ⏸ 冷却后可重试，**但要换发法** | 14 天 |",
         "| **软退信-暂时停用** | 对方邮箱被停用 | ⏸ 冷却后重试 | 30 天 |",
         "| **待人工判定** | 原因不明确 | ⏸ 保守拦截，人工确认 | 30 天 |", "",
         "**核心区别**：硬退信是**地址错了**（再发也是错）；软退信是**通路被挡**（换条路可能通）。", "",
         "---", ""]

    CN_NUM = ["二", "三", "四", "五"]
    for i, cat in enumerate(CAT_ORDER):
        rows = groups.get(cat)
        if not rows:
            continue
        L += [f"## {CN_NUM[i]}、{cat}（{len(rows)} 个）", "",
              "| 地址 | 首退 | 末退 | 次数 | 冷却到 | 原因（截断） |", "|---|---|---|---|---|---|"]
        for r in rows:
            end = cooldown_end(r)
            cd = "**永久**" if end is None else f"{end:%Y-%m-%d}"
            L.append("| `{}` | {} | {} | {} | {} | {} |".format(
                r["address"],
                (r.get("first_date") or "")[:16],
                (r.get("last_date") or "")[:16] or "—",
                r.get("count", 1), cd,
                (r.get("reason") or "").replace("|", "/")[:80]))
        L.append("")

    if blocked_domains:
        L += ["## 六、🔒 整域封锁（同域 ≥2 个地址退信）", "",
              "> 对方服务商按**域**拒绝时，换地址没有意义 —— 该域**全部地址**拦截。", "",
              "| 域名 | 命中地址数 |", "|---|---|"]
        for d in blocked_domains:
            n = sum(1 for r in items if r.get("domain") == d)
            L.append(f"| **`{d}`** | {n} |")
        L.append("")

    repeats = [r for r in items if int(r.get("count", 1)) > 1]
    L += ["## 七、⚠️ 规律与注意", "",
          f"- 库内 **{len(items)}** 个退信地址，其中 **{len(roles)}** 个是角色邮箱"
          "（`info@` / `contact@` / `sales@` / `feedback@` / `supplier@` 等）",
          f"- **重复退信 {len(repeats)} 个**：" +
          ("、".join(f"`{r['address']}`（{r['count']} 次）" for r in repeats) or "无"),
          "- **A 档（具名 + 公司域）并非免疫** —— 退信成因可能是收件端**按域策略拒绝**，"
          "这类退信换地址无效，只能整域回避",
          "- **同一封退信可同时报多个失败地址** —— 如 `{{COMPANY_DOMAIN}}` 的 9/23 退信里"
          "同时含 `jchamblee@` 与 `walt@`。人工登记容易只记第一个，**必须跑扫描**",
          "- **换发法**：软退信冷却到期后，须 ① 换主题 ② 重写正文 ③ 去链接 "
          "④ 纯文本 ⑤ 间隔 ≥2 周；**不得原文重发**", "",
          "### 🔴 一个待修的闸门口径（建议，未改代码）", "",
          "本表的「冷却到」按**最后一次**退信日计算（保守）。但 `定时发送.py:is_blocked` "
          "目前锚定的是 **`first_date`（首次）** —— 对**重复退信**会**提前放行**。",
          "",
          "> 例：`{{CONTACT_EMAIL}}` 首退 9/15、二退未记 → 按首次算 9/29 即解禁，"
          "但实际它已连退 2 次，再发大概率再退。",
          "",
          "建议改为锚定 `last_date or first_date`（一行改动）。"
          "**本次未擅自修改发送脚本**，仅在此记录。", "",
          "---", "",
          "## 八、自动闸门（已生效）", "",
          "`定时发送.py` 已接入退信闸门：",
          "- 建队列时自动跳过黑名单地址",
          "- **发送前再查一次**（防止排队期间地址失效）",
          "- 硬退信 → 永久拦；软退信 → 冷却期内拦，到期自动放行",
          "- **整域封锁**：同域累计 ≥2 个地址退信 ⇒ 该域全部地址拦截", "",
          "**维护方式**：跑 `python3 扫描退信.py` 自动增量更新；"
          "或手工把新退信追加到 `退信黑名单.json`。", ""]
    return "\n".join(L)


def render_html(items: list, scanned: int, newn: int) -> str:
    now = datetime.now(BJ)
    groups = {}
    for r in items:
        groups.setdefault(r.get("category", "待人工判定"), []).append(r)

    def esc(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    colors = {
        "硬退信-地址不存在": ("#b91c1c", "#fef2f2", "#fecaca"),
        "软退信-服务商拒收": ("#b45309", "#fffbeb", "#fde68a"),
        "软退信-暂时停用": ("#a16207", "#fefce8", "#fef08a"),
        "待人工判定": ("#475569", "#f8fafc", "#e2e8f0"),
    }
    blocked_domains = sorted({r["domain"] for r in items
                              if r.get("block_scope") == "domain" and r.get("domain")})

    cards = []
    for cat in CAT_ORDER:
        rows = groups.get(cat)
        if not rows:
            continue
        fg, bg, bd = colors[cat]
        trs = []
        for r in sorted(rows, key=lambda x: x.get("address", "")):
            end = cooldown_end(r)
            cd = "永久" if end is None else f"{end:%Y-%m-%d}"
            dom_badge = ('<span class="badge dom">整域封锁</span>'
                         if r.get("block_scope") == "domain" else "")
            trs.append(
                f"<tr><td class='addr'>{esc(r['address'])} {dom_badge}</td>"
                f"<td>{(r.get('first_date') or '')[:16]}</td>"
                f"<td>{(r.get('last_date') or '')[:16] or '—'}</td>"
                f"<td class='num'>{r.get('count', 1)}</td>"
                f"<td class='cd'>{cd}</td>"
                f"<td class='reason'>{esc((r.get('reason') or '')[:150])}</td></tr>")
        cards.append(
            f"<section class='card' style='--fg:{fg};--bg:{bg};--bd:{bd}'>"
            f"<h2><span class='dot'></span>{esc(cat)}"
            f"<span class='count'>{len(rows)}</span></h2>"
            "<table><thead><tr><th>地址</th><th>首退</th><th>末退</th>"
            "<th>次数</th><th>冷却到</th><th>原因</th></tr></thead><tbody>"
            + "".join(trs) + "</tbody></table></section>")

    dom_card = ""
    if blocked_domains:
        lis = "".join(
            f"<li><code>{esc(d)}</code> —— 命中 {sum(1 for r in items if r.get('domain') == d)} 个地址</li>"
            for d in blocked_domains)
        dom_card = (f"<section class='card' style='--fg:#7c3aed;--bg:#faf5ff;--bd:#ddd6fe'>"
                    f"<h2><span class='dot'></span>整域封锁"
                    f"<span class='count'>{len(blocked_domains)}</span></h2>"
                    f"<ul class='doms'>{lis}</ul>"
                    "<p class='hint'>对方服务商按<b>域</b>拒绝时，换地址没有意义 —— "
                    "该域全部地址一律拦截。</p></section>")

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>退信报告 · jiezougroup</title>
<style>
  :root{{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--panel:#fff;--page:#f6f8fb}}
  *{{box-sizing:border-box}}
  body{{margin:0;padding:28px 22px 60px;background:var(--page);color:var(--ink);
       font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif}}
  .wrap{{max-width:1180px;margin:0 auto}}
  header{{margin-bottom:22px}}
  h1{{margin:0 0 6px;font-size:23px;letter-spacing:-.01em}}
  .sub{{color:var(--muted);font-size:13px}}
  .kpis{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0 24px}}
  .kpi{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
       padding:13px 18px;min-width:132px}}
  .kpi b{{display:block;font-size:23px;line-height:1.2}}
  .kpi span{{color:var(--muted);font-size:12px}}
  .card{{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--fg);
        border-radius:12px;padding:16px 18px;margin-bottom:16px}}
  .card h2{{margin:0 0 12px;font-size:15px;color:var(--fg);display:flex;align-items:center;gap:9px}}
  .dot{{width:9px;height:9px;border-radius:50%;background:var(--fg);display:inline-block}}
  .count{{margin-left:auto;background:var(--bg);border:1px solid var(--bd);color:var(--fg);
         border-radius:999px;padding:1px 10px;font-size:12px;font-weight:600}}
  table{{width:100%;border-collapse:collapse;font-size:12.5px}}
  th{{text-align:left;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);
     padding:7px 8px;white-space:nowrap}}
  td{{border-bottom:1px solid #f1f5f9;padding:7px 8px;vertical-align:top}}
  tr:last-child td{{border-bottom:none}}
  .addr{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;white-space:nowrap}}
  .num,.cd{{text-align:center;white-space:nowrap}}
  .reason{{color:var(--muted);word-break:break-word}}
  .badge{{font-size:10.5px;padding:1px 7px;border-radius:999px;margin-left:6px;
         background:#faf5ff;color:#7c3aed;border:1px solid #ddd6fe;font-weight:600}}
  .doms{{margin:0;padding-left:20px}} .doms code{{font-size:12.5px}}
  .hint{{color:var(--muted);font-size:12.5px;margin:10px 0 0}}
  footer{{color:var(--muted);font-size:12px;margin-top:26px;border-top:1px solid var(--line);padding-top:14px}}
  code{{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}}
</style></head><body><div class="wrap">
<header>
  <h1>退信报告</h1>
  <div class="sub">账号 <code>{{SENDER_EMAIL}}</code> ｜ 最近扫描 {now:%Y-%m-%d %H:%M}（北京）
    ｜ 本次新识别 <b>{newn}</b> 条</div>
</header>
<div class="kpis">
  <div class="kpi"><b>{len(items)}</b><span>库内退信地址</span></div>
  <div class="kpi"><b>{len(groups.get('硬退信-地址不存在', []))}</b><span>硬退信（永久）</span></div>
  <div class="kpi"><b>{len(groups.get('软退信-服务商拒收', [])) + len(groups.get('软退信-暂时停用', []))}</b><span>软退信（冷却）</span></div>
  <div class="kpi"><b>{len(groups.get('待人工判定', []))}</b><span>待人工判定</span></div>
  <div class="kpi"><b>{len(blocked_domains)}</b><span>整域封锁</span></div>
</div>
{''.join(cards)}
{dom_card}
<footer>由 <code>扫描退信.py</code> 生成 ｜ 数据源 <code>退信黑名单.json</code>（<code>定时发送.py</code> 退信闸门自动读取）
｜ 冷却期：硬=永久，软-服务商拒收=14 天，软-暂时停用=30 天，待判=30 天</footer>
</div></body></html>"""


# ---------------------------------------------------------------- 主流程

def cmd_show():
    items = load_blacklist_raw()
    if not items:
        print("黑名单为空。")
        return 0
    now = datetime.now(BJ)
    print(f"退信黑名单：{len(items)} 个地址\n")
    for r in sorted(items, key=lambda x: (CAT_ORDER.index(x.get("category", "待人工判定"))
                                          if x.get("category") in CAT_ORDER else 9,
                                          x.get("address", ""))):
        end = cooldown_end(r)
        cd = "永久" if end is None else f"{end:%Y-%m-%d}"
        flag = "🔒" if r.get("block_scope") == "domain" else "  "
        active = ""
        if end is not None and now.replace(tzinfo=None) < end.replace(tzinfo=None):
            active = "（冷却中）"
        print(f"{flag} {r['address']:<42} {r.get('category',''):<12} "
              f"x{r.get('count',1)} 冷却到 {cd} {active}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="退信扫描与入库")
    ap.add_argument("--days", type=int, default=0, help="只看最近 N 天（0=全部）")
    ap.add_argument("--dry-run", action="store_true", help="只扫描，不写任何文件")
    ap.add_argument("--show", action="store_true", help="只打印当前黑名单（不连邮箱）")
    args = ap.parse_args()

    if args.show:
        return cmd_show()

    mc = _load("mailer", "邮箱客户端.py")
    cfg = mc.load_config()

    import email
    m = mc.imap_connect(cfg)
    cutoff = datetime.now(BJ) - timedelta(days=args.days) if args.days else None

    found, scanned, seen_addr, unparsed = [], 0, set(), []
    size_skipped = []          # 🔴 体积型退信：**只统计，不记录、不入库**（见 is_size_bounce）
    for box in FOLDERS:
        try:
            typ, d = m.select(box, readonly=True)
        except Exception as e:
            print(f"  ⚠️ 跳过文件夹 {box}：{e}")
            continue
        n = int(d[0]) if d and d[0] else 0
        print(f"扫描 {box}（{n} 封）…")
        if not n:
            continue
        typ, dd = m.search(None, "ALL")
        for num in dd[0].split():
            raw = mc.fetch_headers(m, num, "FROM SUBJECT DATE")
            subj = mc.raw_header(raw, "Subject")
            frm = mc.raw_header(raw, "From")
            date = mc.raw_header(raw, "Date")
            low_s, low_f = subj.lower(), frm.lower()
            if not (any(s in low_s for s in BOUNCE_SUBJECT)
                    or any(s in low_f for s in BOUNCE_FROM)):
                continue
            dt = parse_bl_date(date)
            if cutoff and dt and dt < cutoff:
                continue
            typ, dd2 = m.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(dd2[0][1], policy=email.policy.default)
            body = plain_body(msg)
            dsn = dsn_portion(body)          # 🔴 只扫退信正文段，不扫后面引用的原邮件
            blob = subj + "\n" + dsn
            addrs = extract_recipients(blob)
            if not addrs:
                unparsed.append((date, frm, subj))
                continue
            # 🔴 体积型退信：**我方附件超限，与收件地址无关 → 跳过，不入库、不进报告**。
            #    若照常走 classify()，会落到「待人工判定」→ 30 天冷却 → 把热线索误锁一个月。
            if is_size_bounce(blob):
                size_skipped.append((date, addrs[0], subj[:80]))
                continue
            scanned += 1
            cat = classify(blob)
            reason = make_reason(blob, addrs[0])
            # 原主题：优先从正文里找 `Subject:`；找不到时退回退信主题里引号内的部分
            #（Mimecast/EXO 格式：`Your message couldn't be delivered - "Transformer supply, Salt Lake City"`）
            osubj = extract_orig_subject(body)
            if not osubj:
                mq = re.search(r'[-—:]\s*"([^"]{4,120})"', subj)
                osubj = mq.group(1).strip() if mq else ""
            for a in addrs:
                if a in seen_addr:
                    continue
                seen_addr.add(a)
                found.append({
                    "address": a,
                    "category": cat,
                    "reason": reason,
                    "first_date": date,
                    "count": 1,
                    "_orig_subject": osubj,
                })
    m.logout()
    print()

    print(f"识别到 {scanned} 封退信，涉及 {len(found)} 个地址\n")
    for f in found:
        print(f"  · {f['address']:<44} {f['category']:<12} {(f.get('_orig_subject') or '')[:52]}")
    print()
    if unparsed:
        print(f"⚠️ {len(unparsed)} 封疑似退信但**未能识别失败地址**（需人工看原文）：")
        for date, frm, subj in unparsed:
            print(f"  ? {date[:31]} | {frm[:34]} | {subj[:56]}")
        print()

    # 🔴 体积型退信：**只提示，不记录**（用户 2026-10-02 明确要求）。
    #    原因：是我方附件超限，与收件地址无关；记进去会把热线索误锁。
    if size_skipped:
        print(f"ℹ️ 已忽略 {len(size_skipped)} 封**体积型退信**"
              f"（我方附件超限，非地址问题 → **不入库、不进报告**）：")
        for date, a, subj in size_skipped:
            print(f"  ✂ {date[:31]} | {a:<38} | {subj[:52]}")
        print("  ⚠️ 这类退信要修的是**附件体积**（建议 ≤ 20 MB 或走云盘链接），"
              "**不要动退信黑名单**。")
        print()

    existing = load_blacklist_raw()
    merged, notes = merge(existing, found)
    print(f"入库变更（{len(notes)} 条）：")
    for n in notes:
        print(n)
    print()

    if args.dry_run:
        print("（--dry-run：未写入任何文件）")
        return 0

    for r in merged:
        r.pop("_orig_subject", None)
    merged.sort(key=lambda x: (CAT_ORDER.index(x["category"])
                               if x.get("category") in CAT_ORDER else 9,
                               x.get("address", "")))
    BLACKLIST.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    added = len([n for n in notes if n.startswith("  ＋")])
    REPORT_MD.write_text(render_md(merged, scanned, len(found), added), encoding="utf-8")
    REPORT_HTML.write_text(render_html(merged, scanned, added), encoding="utf-8")

    print(f"已更新：{BLACKLIST.name}")
    print(f"已更新：{REPORT_MD.name}")
    print(f"已更新：{REPORT_HTML.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
