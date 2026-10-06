#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时发送队列
============
按收件人所在时区，把开发信分散到「对方当地上午 9:00–10:00」发出。

为什么需要它
------------
SMTP 协议没有定时能力，IMAP 也没有调度扩展（实测能力列表已确认），
Exchange EWS 端点在本账号不可用。所以「服务端定时」做不到。
本脚本用**本机定时队列**实现等价效果：邮件先排好队，到点才投递。

代价：**运行时段电脑需开机联网**。

时区方法论（来自 `开发信项目/工作区/发送时间对照表.md`）
------------------------------------------------------
    目标时刻 = 对方当地上午 9:00–10:00
    北京发信时间 = 9:00 − 对方时区偏移 + 8

⚠️ **2026-11-01 北美夏令时结束**，所有美加窗口 +1 小时。
   本脚本按日期自动判断夏令时（3 月第二个周日 → 11 月第一个周日）。

用法
----
  python3 定时发送.py --build                  # 扫描信件，建立队列
  python3 定时发送.py --status                 # 查看队列
  python3 定时发送.py --run                    # 发送「窗口已到」的信（预演）
  python3 定时发送.py --run --send --yes       # 真正发送
  python3 定时发送.py --run --send --yes --to {{CONTACT_EMAIL}}   # 【测试】全部重定向
  python3 定时发送.py --run --force-window     # 忽略窗口，立即发（调试用）

配合定时器
----------
  每 30 分钟跑一次 `--run --send --yes` 即可（WorkBuddy 自动化 / launchd / 手动）。
"""

import argparse
import atexit
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENTS = ROOT / "开发信项目" / "clients"
QUEUE = ROOT / "发信队列.json"
BJ = timezone(timedelta(hours=8))

# ============================================================
# 🔴 只处理「本项目（本会话）产出的信件」
# 用户 2026-09-27 明确：**不要动项目中已有的 130 封信**。
# 已有信件是旧格式（正文带职务/邮箱/电话行、部分缺退订句），
# 它们不在本项目管辖范围内。要看全部请加 --all。
# ============================================================
# ============================================================
# 🔴 **本批（batch5 A 档 21 封）排程范围**
#    2026-09-28 用户指令：「这21封在今天发出去包括明天的凌晨，
#    对应对方时间的9-10点」。
#    名单 = 用户已核对过的《📋待发清单-batch5_A档21封.xlsx》21 家，
#    即 batch5 中「已写好 + 红线全过 + 有可投递邮箱」的全部信件。
#
#    ⚠️ 与下方 OWN_LETTERS 的区别：OWN_LETTERS 是**早期 5 封试验信**，
#    本批与之无交集。`--build --batch5` 只排本批，不碰历史信。
# ============================================================
BATCH5_LETTERS = []

OWN_LETTERS = []

# ============================================================
# 🔴 **本批（batch6 A 档 23 封）排程范围**
#    2026-09-29 用户指令：「给这23封设置定时发信任务（今天晚上到明天凌晨）」
#    名单 = batch6 挖人产出中「A 档 + 已写好 + 红线全过」的全部信件（买家 174–223）。
#    ⛔ 不含 B 档 25 家（用户明确「b档先不写」）、
#       不含仅电话 4 家（192/211/216/218，无邮箱）、
#       不含排除/停业 2 家（205 JDD / 210 {{COMPANY}}）。
#    `--build --batch6` 只排本批，不碰历史信。
# ============================================================
BATCH6_LETTERS = []

# ============================================================
# 🔴 **batch6 跟进信 21 封**（2026-09-29 用户指令：
#    「A、B组的都写…都写好告诉我一声，然后开始设定定时发送」）
#    来源：`今日跟进名单-20260929.md` —— 跟进表「下次跟进日 = 2026-09-29」的 24 家，
#    剔除 3 家被退信闸门拦截者（Intel Electric / {{COMPANY}} / Bartle & Gibson）。
#    组成：第 2 次跟进 5 家 + 第 1 次跟进 15 家 + Iconic 特殊试探 1 家 = 21 封。
#    `--build --batch6-all` = 首封 23 + 跟进 21 = **44 封合并入队**。
# ============================================================
BATCH6_FOLLOWUP = []

# ============================================================
# 🔴 **batch4 历史缺口补发 5 封**（2026-09-29 用户指令「补发」）
#    来源：核对 batch4 交接单 vs 跟进表时发现，这 5 家**写了信但从未发出**
#    （已发邮箱逐封取证：Sent Messages 里零命中）。
#    ⚠️ 必须用 `--queue 发信队列-batch4补发.json` 走**独立队列** ——
#       今晚 44 封尚未发完，绝不能重建主队列 `发信队列.json`。
# ============================================================
BATCH4_RESEND = []

# ============================================================
# 🔴 **batch7 A 档 7 封**（2026-09-30 用户指令：
#    「开始写这7封，然后设置发送定时，现在已经是9.30日23.55了，就往后顺吧」）
#    来源：`交接单/batch7_new_224plus/` 里 49 份交接单中的 **A 档 7 家**
#    （具名 + 官网一手源邮箱 → 可主送；B 档 32 家与拦截 10 家本批不发）
#    ⚠️ 用户明说「往后顺」→ 排到 **10/1（周四）当地上午**，不与 9/30 夜间批次重叠。
# ============================================================
BATCH7_A = []

# ============================================================
# 🔴 **batch7 A 档「二次深挖升级」4 封**（2026-10-01 用户指令）
#    「写吧，也排到北京时间10.1日发，**就是现在**，这个任务**不卡对方时间的8-10点了**」
#    来源：二次深挖把 4 家从 B 档升级为 A 档（均一手源）：
#      236 {{COMPANY}}  ← ECI 母集团官网
#      241 {{COMPANY}} ← AZDOT UTRACS 州采购供应商库
#      245 {{COMPANY}} ← Focus on Energy 州能效计划名录
#      248 SECo             ← Arizona Corporation Commission 年报
#    ⚠️ 用户明确**不卡当地 09:00–10:00 窗口** → 排程时刻直接设为「现在之后几分钟内」，
#       由 `--force-window` 或手动改时刻实现。
# ============================================================
BATCH7_A2 = []

# ============================================================
# 🔴 **batch8 A 档 25 封**（2026-10-02 用户指令：
#    「A档的全部都发，在今天凌晨两点前发完，不要卡一个时间点发，
#      也不要集中在一个时间点发，也不要规律性的每隔5分钟发。设置定时任务吧」）
#    来源：`交接单/batch8_new_274plus/` 里 49 份交接单中的 **A 档 25 家**
#    （具名 + 一手源邮箱 → 可主送；B 档 10 家、C 档 2 家、拦截 12 家本批不发）
#    ⚠️ 用户明确**不卡当地 09:00–10:00 窗口** → 排程时刻按北京 01:20–01:56 不规则分散，
#       由 `构建队列-batch8A.py` 写死 `scheduled_at_bj` 实现（不改窗口逻辑）。
# ============================================================
BATCH8_A = []

# ============================================================
# 🔴 **batch9 A 档 30 封**（2026-10-02 用户指令：「开始写信，只写A档的，写完设置定时发送」）
#    来源：`交接单/batch9_new_324plus/` 里 50 份交接单中的 **A 档 30 家**
#    （具名 + 一手源邮箱 → 可主送；B 档 19 家与拦截 1 家本批不发）
#    ⚠️ 按**日常铁律**排（当地工作日 08:00–10:00 送达），**不破例**。
#    ⚠️ 本批含 **Quanta Services 4 家**（342/344/345/347）与 **Groupe Deschênes** 关联 1 家（349），
#       用户在入队前需裁决是否全发。
# ============================================================
BATCH9_A = []

# ============================================================
# 🔴 **batch10 A 档 28 封**（2026-10-05 用户指令：「全部进入写信环节」）
#    来源：`交接单/batch10_new_374plus/` 里 49 份交接单中的 **A 档 28 家**
#    （具名 + 一手源邮箱 → 可主送；B 档 21 家与⛔排除 1 家本批不发）
#    ⚠️ 按**日常铁律**排（当地工作日 08:00–10:00 送达），不破例。
#    ⚠️ 本批 7 组集团关系已写入各交接单「母公司/集团」字段，
#       入队前需按集团归并（GLR→EBC / ONDEL→Groupe ELEM / Westfield→Westfield Groups /
#       Michels→Michels Corp / Bowe&Gant→Greenbelt Capital / PowerRentals→Location CVAC /
#       {{COMPANY}}→IPS Greenville）。
# ============================================================
BATCH10_A = []

# ============================================================
# 🔴 **batch11 A 档 22 封**（2026-10-06 用户指令：「给A档设置定时发送任务」）
#    来源：`交接单/batch11_new_424plus/` 里 50 份交接单中的 **A 档 22 家**
#    （具名 + 一手源邮箱 → 可主送；B 档 23 家 / C 档 2 家 / 无邮箱 3 家本批不发）
#    ⚠️ 按**日常铁律**排（客户当地工作日 09:00–10:00 送达），不破例。
#    ⚠️ **两家带集团冲突标记（已按用户指令照排，可随时撤下）**：
#        444 Enerfab  → 母公司 Quanta Services（2026-07 收购），Quanta 系已发 6 家
#        456 O'Neil   → 母公司 {{COMPANY}} = batch4 买家86，已于 9/29 发出
#    ⚠️ 时区分布：ET 17 封（ON/QC + 美东部）｜CT 2 封（MB / TX）｜MT 2 封（AB / UT）｜AT 1 封（NL）
# ============================================================
BATCH11_A = []

# ============================================================
# 退信闸门
# 硬退信（地址不存在）→ 永久排除
# 软退信（服务商拒收 / 暂时停用）→ 冷却期内排除，之后可重试
# 冷却期按类别区分，见 COOLDOWN_DAYS
# ============================================================
BOUNCE_BLACKLIST = ROOT / "退信黑名单.json"
COOLDOWN_DAYS = {
    "硬退信-地址不存在": None,      # None = 永久
    "软退信-暂时停用": 30,
    "软退信-服务商拒收": 14,
    "待人工判定": 30,
}


def _parse_bl_date(s: str):
    try:
        return datetime.strptime((s or "")[:16].strip(), "%a, %d %b %Y")
    except Exception:
        return None


# 🔴 2026-10-05 新增：跟进信专属「零退信」闸门
# ---------------------------------------------------------------
# 用户 2026-10-05 明确规则：**二次及以上发送的跟进信，不要出现退信。**
#
# 背景（实测事故 2 例）：
#   · `{{CONTACT_EMAIL}}`  首退 9/15 → 9/18 跟进信又发 → 再退 → 9/29 又发 → 三退
#   · `{{CONTACT_EMAIL}}` 首退 9/23 → 9/29 跟进信又发 → 再退
#
# 根因：原闸门对**软退信**只做「冷却期内拦截」。冷却一到期（14/30 天），
#       跟进信会**再次**发往同一个已经退过信的地址 → 又退。
#       而退信伤的是**发信域信誉**，连带拖累所有 A 档的送达率。
#
# 故：**首封**仍按原口径（软退信冷却到期后可换发法重试）；
#     **跟进信**改为「只要退过信就不发」——无论硬软、无论冷却是否到期。
# ---------------------------------------------------------------
_BOUNCED_DOMAINS = None

# 🔴 公共邮箱域：**只能按完整地址判，不能按域判**。
#    理由：`{{CONTACT_EMAIL}}` 退信不代表整个 gmail.com 该被封 ——
#    按域封会把成千上万的正常 Gmail 收件人一起挡掉。
#    （与 `scripts/生成核对报告-20261003.py` 的 PUBLIC 常量同源，34 个）
PUBLIC_MAIL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'yahoo.ca', 'hotmail.com', 'outlook.com',
    '{{COMPANY_DOMAIN}}', 'live.com', 'aol.com', 'icloud.com', 'msn.com',
    'bell.net', 'sympatico.ca', 'shaw.ca', 'telus.net', 'sbcglobal.net',
    'att.net', 'comcast.net', 'verizon.net', '{{COMPANY_DOMAIN}}', '{{COMPANY_DOMAIN}}',
    'cox.net', 'charter.net', 'me.com', 'protonmail.com', 'mail.com',
    'gmx.com', 'videotron.ca', 'rogers.com', 'cogeco.ca', 'eastlink.ca',
    'nbnet.nb.ca', 'mts.net', 'sasktel.net', 'xplornet.com',
}


def bounced_domains() -> set:
    """返回**全部出现过退信的域名**（含仅 1 个地址、未达整域封锁阈值的）。

    与 `load_blacklist()` 的整域封锁（同域 ≥2 个地址）**口径不同**：
      · 整域封锁 = 这个域危险到**连首封都不该发**
      · 本函数   = 这个域**退过信**，跟进信就不要再碰

    ⚠️ **公共邮箱域（gmail/yahoo/…）一律排除** —— 这类域退信是**个人**问题，
    按域封会误伤成千上万正常收件人。这类地址只按**完整地址**判。
    """
    global _BOUNCED_DOMAINS
    if _BOUNCED_DOMAINS is None:
        doms = set()
        try:
            items = json.loads(BOUNCE_BLACKLIST.read_text(encoding="utf-8"))
        except Exception:
            items = []
        for i in items:
            a = (i.get("address") or "").lower()
            if "@" in a:
                doms.add(a.split("@")[-1])
            d = (i.get("domain") or "").lower()
            if d:
                doms.add(d)
        _BOUNCED_DOMAINS = doms - PUBLIC_MAIL_DOMAINS
    return _BOUNCED_DOMAINS


def is_followup_item(item: dict) -> bool:
    """判断队列项 / 信件是否为**二次及以上触达**（跟进信）。

    两条依据任一成立即为跟进信：
      ① 主题以 `Re:` / `Fw:` / `回复:` / `转发:` 开头
      ② 信件文件名含「跟进」
    """
    subj = (item.get("subject") or "").strip()
    if re.match(r"^(re|fw|fwd|回复|转发)\s*[:：]", subj, re.I):
        return True
    return "跟进" in (item.get("letter") or "")


def load_blacklist() -> dict:
    """返回 {地址: 记录}，另含 `{"@域名": 记录}` 形式的**整域封锁**项。

    🔴 2026-09-29 新增整域封锁。
    背景（真实事故）：`{{COMPANY_DOMAIN}}` 在 9/23 已退 `jchamblee@`，
    但 9/29 跟进队列又发了 `walt@` —— **同一个域第二次踩坑**。
    根因：旧逻辑只做「精确地址匹配」，同域换个人名就绕过了闸门。
    而对方服务商（Outlook/EXO `550 5.4.1 Access denied`）是**按域封的**，
    换地址没有意义。

    规则：同一域名累计 **≥2 个地址**退信 ⇒ 整域封锁
    （与 `退信处理清单.md` §二 既有约定一致）。
    """
    if not BOUNCE_BLACKLIST.exists():
        return {}
    try:
        items = json.loads(BOUNCE_BLACKLIST.read_text(encoding="utf-8"))
    except Exception:
        return {}
    bl = {i["address"].lower(): i for i in items if i.get("address")}

    # 整域封锁：取该域**最新**一条退信记录作冷却起点
    #   🔴 2026-10-01 修正：比较的是各记录的 **`last_date or first_date`**，不是 `first_date`。
    #     背景：`扫描退信.py` 会把 `first_date` 规范成**最早**、`last_date` 为**最新**。
    #     若这里仍读 `first_date`，`{{COMPANY_DOMAIN}}` 的域封锚点会从 9/29 退回 9/23
    #     （冷却日 10-13 → 10-07，**域封反而变弱 6 天**）。实测踩到过。
    #   ⚠️ `is_blocked()` 的单地址路径也锚「最新」—— 两条路径口径一致，别再改回只认 first_date。
    def _anchor(rec: dict):
        return _parse_bl_date(rec.get("last_date") or rec.get("first_date", ""))

    doms = {}
    for i in items:
        if i.get("block_scope") != "domain" or not i.get("domain"):
            continue
        dom = i["domain"].lower()
        prev = doms.get(dom)
        if prev is None:
            doms[dom] = i
        else:
            a, b = _anchor(prev), _anchor(i)
            if a is None or (b is not None and b > a):
                doms[dom] = i
    for dom, rec in doms.items():
        bl["@" + dom] = rec
    return bl


def is_blocked(addr: str, now: datetime, bl: dict,
               strict_followup: bool = False) -> tuple:
    """返回 (是否拦截, 原因)。

    先按**精确地址**查；未命中再按**域名**查（整域封锁）。

    🔴 2026-10-01 修：冷却锚点由 `first_date` 改为 **`last_date or first_date`**。
    背景（真实缺口）：地址路径原先锚「**首次**」退信日，而域路径（`load_blacklist`）
    锚「**最新**」—— 同一地址**第二次退信**时冷却期不会重新起算，会**提前放行**。
    例（软退信 14 天）：首退 9/1 → 9/15 解禁；二退 9/10 → 仍按 9/1 算 → 9/15 照样放行。
    实测样本：`{{CONTACT_EMAIL}}`（9/23 + 9/29）冷却日应由 10-07 延到 **10-13**。
    现两条路径**同为「锚最新」**，与 `退信处理清单.md` 的「冷却到」列口径一致。
    兼容性：老记录无 `last_date` 时自动回退 `first_date`，行为不变。

    🔴 2026-10-05 新增 `strict_followup`（跟进信专属「零退信」闸门）。
    `strict_followup=True` 时：
      · 该地址**退过信就不发**（不论硬软、不论冷却是否到期）
      · 该**域**退过信就不发（哪怕只 1 个地址、未达整域封锁阈值）
    依据：用户规则「二次及以上发送的跟进信，不要出现退信」。
    首封路径**不传**此参数，保持「软退信冷却到期后可换发法重试」的原口径。
    """
    rec = bl.get(addr.lower())
    dom = addr.split("@")[-1].lower() if "@" in addr else ""
    if strict_followup:
        if rec:
            when = (rec.get("last_date") or rec.get("first_date") or "")[:16]
            return True, (f"跟进信零退信闸门：该地址退过信"
                          f"（{rec.get('category','?')}，{when}）—— 跟进信不得再触达")
        if dom and dom in bounced_domains():
            return True, (f"跟进信零退信闸门：{dom} 曾有地址退信"
                          f"—— 跟进信不再触碰该域（换人名无效）")
    domain_block = False
    if not rec:
        if dom:
            rec = bl.get("@" + dom)
            domain_block = rec is not None
    if not rec:
        return False, ""
    cat = rec.get("category", "待人工判定")
    days = COOLDOWN_DAYS.get(cat, 30)
    prefix = "整域封锁：" if domain_block else ""
    if days is None:
        return True, f"{prefix}硬退信永久排除（{rec.get('reason','')[:60]}）"
    # 🔴 锚「最后一次」退信（与整域封锁口径一致）；缺 last_date 的老记录回退 first_date
    d = _parse_bl_date(rec.get("last_date") or rec.get("first_date", ""))
    if d is None:
        return True, f"{prefix}{cat}（冷却 {days} 天，日期无法解析，保守拦截）"
    if now.replace(tzinfo=None) < d + timedelta(days=days):
        return True, f"{prefix}{cat}（冷却中，{d + timedelta(days=days):%Y-%m-%d} 后可重试）"
    return False, ""

# ---------------------------------------------------------------- 时区表
# 美国州 → 时区代号；加拿大省 → 时区代号
STATE_TZ = {}
for code in "CT DE FL GA IN KY ME MD MA MI NH NJ NY NC OH PA RI SC VT VA WV DC".split():
    STATE_TZ[code] = "ET"
for code in "AL AR IL IA KS LA MN MS MO OK TN TX WI".split():
    STATE_TZ[code] = "CT"
for code in "AZ".split():
    STATE_TZ[code] = "AZ"          # 🔴 AZ 全年不夏令时（旧表误归 MT）
for code in "CO ID MT NM UT WY".split():
    STATE_TZ[code] = "MT"
for code in "CA NV OR WA".split():
    STATE_TZ[code] = "PT"
STATE_TZ.update({"AK": "AK", "HI": "HI"})
for code in "ON QC".split():
    STATE_TZ[code] = "ET"
# 🔴 2026-09-29 修正：NS/NB/PE/NL 属**大西洋时区**，旧表误归 ET
#    （旧写法：for code in "ON QC NS NB PE NL" → 全部 ET）
for code in "NS NB PE NL".split():
    STATE_TZ[code] = "AT"
for code in "MB SK NT NU".split():
    STATE_TZ[code] = "CT"
for code in "AB".split():
    STATE_TZ[code] = "MT"
for code in "BC YT".split():
    STATE_TZ[code] = "PT"

# 时区代号 → 夏令时 UTC 偏移
TZ_OFFSET_DST = {
    "ET": -4, "CT": -5, "MT": -6, "PT": -7, "AK": -8, "HI": -10,
    # 🔴 2026-09-29 新增两区（batch6 排程时发现旧表有误）
    #    AT = 大西洋时区（NS / NB / PE / NL）。旧表把这些省错归 ET，
    #         导致发信晚 1–1.5 小时（NL 实际为 NDT UTC−2:30）。
    #    AZ = 亚利桑那（MST UTC−7，**全年不实行夏令时**）。
    #         旧表把 AZ 归 MT，夏令时期间会早发 1 小时。
    "AT": -3, "AZ": -7,
    "BR": -3,          # 巴西 圣保罗
    "MX": -6,          # 墨西哥（中部）
}
TZ_CN = {"ET": "美东", "CT": "美中", "MT": "美山", "PT": "美西",
         "AK": "阿拉斯加", "HI": "夏威夷", "AT": "大西洋", "AZ": "亚利桑那",
         "BR": "巴西", "MX": "墨西哥"}

# 🔴 2026-09-29 新增：**不实行夏令时的时区**（in_dst 恒返回 False）
#    亚利桑那（AZ）与夏威夷（HI）全年不调时 —— 若按北美术夏令时规则 +1 小时会算错。
NO_DST = {"AZ", "HI"}

# 🔴 2026-09-29 新增：**时区缩写别名归一化**
#    信件头部常写「大西洋时区（AST，UTC−4；夏令时 ADT UTC−3）」这类**3 字母缩写**，
#    而本脚本内部用 2 字母代号。不归一化会把 "AST" 截成 "AS" 而匹配失败。
TZ_ALIAS = {
    "EST": "ET", "EDT": "ET", "CST": "CT", "CDT": "CT",
    "MST": "MT", "MDT": "MT", "PST": "PT", "PDT": "PT",
    "AST": "AT", "ADT": "AT", "NST": "AT", "NDT": "AT",
    "AKST": "AK", "AKDT": "AK", "HST": "HI",
}

# 🔴 用户 2026-09-28 明确（batch5 排程）：**客户当地上午 9:00–10:00 送达**。
#    旧设定为 8 点，本批改为 9 点起、窗口跨 1 小时。
#    例：北京周一 21:00 发送 → 客户（美东 UTC−4）当地周一 09:00 送达
TARGET_LOCAL_HOUR = 9
WINDOW_SPAN = 1        # 窗口跨度（小时）：当地 09:00–10:00

# 🔴 用户 2026-09-28 明确：**不要同一时间发出**
#    同一时区的信要分散到窗口内的不同时刻 ——
#    「同一秒/同一分钟批量发出」是最典型的垃圾邮件特征。
#    spread=True 时，同一 (时区, 日期) 分组内的信会均匀铺开 + 加随机抖动。
SPREAD_WITHIN_WINDOW = True
SPREAD_JITTER = 0.25   # 抖动幅度 = 子间隔 × 该系数

# 🔴 2026-09-28 新增：**把计划时刻对齐到 5 分钟刻度**
#    原因：本批用「每隔 5 分钟唤醒一次」的外部调度驱动（任务系统最小粒度）。
#    投递判定是 `scheduled_at_bj <= now`，若计划时刻落在 21:19，
#    则实际会在 21:20 那一跳发出 —— 有最多 5 分钟的滑动。
#    把计划时刻直接吸附到 5 分钟刻度上（21:20），滑动即可忽略不计，
#    且仍完整落在客户当地 09:00–10:00 窗口内。
SLOT_MINUTES = 5

# 各时区的夏令时规则（北美统一：3月第2个周日 → 11月第1个周日）
NORTH_AM = {"ET", "CT", "MT", "PT", "AK", "HI", "AT", "AZ"}
EU_DST = {"UK", "DE", "FR", "IT", "NL", "PL", "CZ", "HU"}


def nth_weekday(year, month, weekday, n):
    """某月第 n 个星期 weekday（0=周一）。"""
    d = datetime(year, month, 1)
    shift = (weekday - d.weekday()) % 7
    return 1 + shift + (n - 1) * 7


def in_dst(tzcode: str, when: datetime) -> bool:
    """判断给定北京时刻是否落在该时区的夏令时区间内。

    北美统一规则：3 月第二个周日 → 11 月第一个周日。
    用 naive 比较（两边都去掉 tzinfo），避免 aware/naive 混用报错。
    """
    w = when.replace(tzinfo=None)
    if tzcode in NO_DST:
        return False      # 🔴 2026-09-29：AZ / HI 全年不实行夏令时
    if tzcode in NORTH_AM:
        start = datetime(w.year, 3, nth_weekday(w.year, 3, 6, 2))
        end = datetime(w.year, 11, nth_weekday(w.year, 11, 6, 1))
        return start <= w < end
    if tzcode in EU_DST:
        return True   # 简化：9 月欧洲仍是夏令时
    return False      # 巴西/墨西哥等按不调处理


# ---------------------------------------------------------------- 信件解析

def load_sd():
    spec = importlib.util.spec_from_file_location("sd", ROOT / "发送开发信.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sd"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_verifier():
    """复用 地址验证.py 的 L1+L2（不探活，快且安全）。"""
    spec = importlib.util.spec_from_file_location("av", ROOT / "地址验证.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["av"] = mod
    spec.loader.exec_module(mod)
    return mod


def tz_of_letter(notes: str, body: str, full: str = "") -> str:
    """从信件推时区。

    🔴 **优先级：头部显式时区缩写 > 省/州码 > 国家/地区名 > 窗口文字**
      不能优先用窗口文字——批注里的「北京时间 HH:MM」可能是按旧目标小时写的，
      用它反查时区会整体错位一格（实测：ET 被判成 CT、MT 被判成 PT）。

    🔴 2026-09-28 修复：原实现只扫 `notes`（【中文批注】块），
      但本批有 7 封把省/州码与时区写在**头部引用块**
      （`> 拟发送时段：ON 省 = 东部时区（ET）`），批注里根本没有 →
      时区解析为 ""，`next_window` 返回 None，**这些信永远排不上队**。
      现改为扫 **full（全文）** 优先取「头部/正文里显式写出的时区缩写」，
      这是人工确认过的权威来源，比任何推断都可靠。
    """
    src = full or notes
    # ① 最可靠：显式时区缩写，形如「东部时区（ET）」「大西洋时区（AST，UTC−4；夏令时 ADT UTC−3）」
    #    🔴 2026-09-29：正则扩到 2–4 字母，并经 TZ_ALIAS 归一化
    #       （3 字母缩写 AST/ADT/NST/NDT/EST… → 内部 2 字母代号）。
    m = re.search(r"(?:太平洋|东部|中部|山地|山区|大西洋|纽芬兰)时区[^\n]{0,12}?[（(]\s*([A-Z]{2,4})", src)
    if m:
        code = TZ_ALIAS.get(m.group(1), m.group(1))
        if code in TZ_OFFSET_DST:
            return code
    # ② 省/州码（全文里任意位置，含 UTB 的 `UT = **山地时区…**` 写法）
    #   🔴 2026-09-29 修复：**必须先剥掉签名行再扫**
    #      签名里的 `JZPE POWER TRANSFORMER CO., LTD.` 含 `CO`，
    #      会被当成**科罗拉多州码** → 整封信误判为山地时区（实测 69 封中招，
    #      其中 7 封正文明写「东部时区（ET）」却被判成 MT）。
    src_scan = re.sub(r"(?:JZPE|JIEZOU)\s+POWER[^\n]*", " ", src, flags=re.I)
    src_scan = re.sub(r"\bCO\.?\s*,?\s*LTD\.?", " ", src_scan, flags=re.I)
    for code in re.findall(r"\b([A-Z]{2})\b", src_scan):
        if code in STATE_TZ:
            return STATE_TZ[code]
    # ③ 国家/地区名
    for kw, tz in (("魁北克", "ET"), ("安省", "ET"), ("安大略", "ET"), ("新斯科舍", "ET"),
                   ("阿省", "MT"), ("曼省", "CT"),
                   ("BC", "PT"), ("不列颠哥伦比亚", "PT"),
                   ("巴西", "BR"), ("墨西哥", "MX"), ("秘鲁", "PE"),
                   ("哥伦比亚", "CO"), ("智利", "CL")):
        if kw in src:
            return tz
    # ④ 兜底：按当前目标小时反查
    m = re.search(r"北京时间\s*(\d{1,2}):\d{2}", notes)
    if m:
        h = int(m.group(1))
        for k, off in TZ_OFFSET_DST.items():
            for dst in (True, False):
                o = off if dst else off + 1
                if (TARGET_LOCAL_HOUR - o + 8) % 24 == h:
                    return k
    return ""


def tz_offset(tz: str, when: datetime) -> int:
    """返回该时区在给定时刻的 UTC 偏移（夏令时/冬令时自动判断）。

    🔴 2026-09-29：NO_DST 时区（AZ / HI）**直接返回表内值**，不做 +1 修正 ——
    它们全年不调时，表内值即其唯一偏移（AZ −7 / HI −10）。
    """
    off = TZ_OFFSET_DST.get(tz, -5)
    if tz in NO_DST:
        return off
    if not in_dst(tz, when):
        off += 1          # 冬令时偏移 −1
    return off


def _ceil_slot(dt: datetime, step: int = SLOT_MINUTES) -> datetime:
    """把时刻**向上**吸附到 step 分钟的刻度（+1 分钟余量，避免秒级竞态）。

    例：21:10 → 21:15；21:15:03 → 21:20；21:00:00 整 → 21:05。
    用于「此刻已在窗口内」时，把排程起点抬到当前之后，
    否则 scheduled_at 落在过去虽也会被 `--run` 立刻发出，但展示会很难看。
    """
    t = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    m = t.minute
    up = (m + step - 1) // step * step
    if up >= 60:
        t = t.replace(minute=0) + timedelta(hours=1)
    else:
        t = t.replace(minute=up)
    return t


def next_window(tz: str, now: datetime) -> dict:
    """算下一个发送窗口。

    🔴 以**送达时间**为准：目标 = 客户当地工作日 09:00（窗口跨 WINDOW_SPAN 小时）。
       返回里同时给「北京发送时刻」和「客户当地送达时刻」。

    实现：逐小时扫描未来 10 天，找第一个「当地 09:00 且当地为周一–周五」的时刻。
    ⚠️ 周末判断必须用**当地星期**——北京周六 00:00 可能是当地周五 09:00（应当可发）。

    🔴 2026-09-28 修复（**严重**）：原文的 `if bj < now: continue` 用的是
       **精确到分的 now**，而候选 `bj` 被截断到整点。于是当「当前正处于窗口小时内」
       （例：now=21:10，ET 窗口=21:00–22:00）时，21:00 < 21:10 → 被判「已过」而跳过，
       **整个今晚的窗口被丢弃**，ET 的 7 封信被推到**次日**（实测确实发生）。
       这与「窗口是一段 09:00–10:00 的区间、而不是一个点」的事实矛盾。
       正确判据：只要 `now < 窗口结束时刻`，窗口就仍然可用（此刻正身处窗口内）。
    """
    off = tz_offset(tz, now)
    delta = 8 - off                     # 北京 = 当地 + delta
    cur = now.replace(minute=0, second=0, microsecond=0)
    for i in range(0, 24 * 10):
        bj = cur + timedelta(hours=i)
        local = bj - timedelta(hours=delta)
        if local.hour != TARGET_LOCAL_HOUR:
            continue
        if local.weekday() >= 5:        # 当地周末 → 跳过
            continue
        window_end = bj + timedelta(hours=WINDOW_SPAN)
        # 窗口**尚未结束**即视为可用（含「此刻正在窗口内」的情形）。
        # 注意：窗口起点若已过，不能原样返回——否则 scheduled_at 会落在过去，
        # 由调用方 / build 的吸附逻辑把起点抬到「当前时刻之后」。
        if window_end <= now:
            continue
        # 起点取 max(窗口起点, now 的下一个 5 分钟刻度)，避免排到过去
        start = max(bj, _ceil_slot(now))
        return {
            "bj_start": start,
            "bj_end": window_end,
            "local_start": start - timedelta(hours=delta),
            "local_end": window_end - timedelta(hours=delta),
            "offset": off,
            "dst": in_dst(tz, now),
        }
    # 兜底（不应发生）
    return {"bj_start": now, "bj_end": now + timedelta(hours=2),
            "local_start": now - timedelta(hours=delta),
            "local_end": now + timedelta(hours=2) - timedelta(hours=delta),
            "offset": off, "dst": True}


def fmt_window(w: dict, tz: str) -> str:
    """人类可读：北京发送 → 当地送达。"""
    return (f"北京 {w['bj_start']:%m-%d %H:%M}–{w['bj_end']:%H:%M}"
            f"  →  当地（{TZ_CN.get(tz, tz)}）{w['local_start']:%m-%d %H:%M}–{w['local_end']:%H:%M}")


# ---------------------------------------------------------------- 队列

def read_queue() -> list:
    if not QUEUE.exists():
        return []
    return json.loads(QUEUE.read_text(encoding="utf-8"))


def write_queue(items: list):
    QUEUE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_build(sd, args):
    now = datetime.now(BJ)
    items = []
    scope = sorted(CLIENTS.glob("开发信-*.md"))
    if getattr(args, "batch11_a", False):
        scope = [f for f in scope if f.name in BATCH11_A]
    elif getattr(args, "batch10_a", False):
        scope = [f for f in scope if f.name in BATCH10_A]
    elif getattr(args, "batch9_a", False):
        scope = [f for f in scope if f.name in BATCH9_A]
    elif getattr(args, "batch8_a", False):
        scope = [f for f in scope if f.name in BATCH8_A]
    elif getattr(args, "batch7_a2", False):
        scope = [f for f in scope if f.name in BATCH7_A2]
    elif getattr(args, "batch7_a", False):
        scope = [f for f in scope if f.name in BATCH7_A]
    elif getattr(args, "batch4_resend", False):
        scope = [f for f in scope if f.name in BATCH4_RESEND]
    elif getattr(args, "batch6_all", False):
        allow = set(BATCH6_LETTERS) | set(BATCH6_FOLLOWUP)
        scope = [f for f in scope if f.name in allow]
    elif getattr(args, "batch6", False):
        scope = [f for f in scope if f.name in BATCH6_LETTERS]
    elif getattr(args, "batch5", False):
        scope = [f for f in scope if f.name in BATCH5_LETTERS]
    elif not getattr(args, "all", False):
        scope = [f for f in scope if f.name in OWN_LETTERS]
    BL = load_blacklist()
    if getattr(args, "batch11_a", False):
        print(f"扫描范围：batch11 A 档 {len(BATCH11_A)} 封")
    elif getattr(args, "batch10_a", False):
        print(f"扫描范围：batch10 A 档 {len(BATCH10_A)} 封")
    elif getattr(args, "batch9_a", False):
        print(f"扫描范围：batch9 A 档 {len(BATCH9_A)} 封")
    elif getattr(args, "batch8_a", False):
        print(f"扫描范围：batch8 A 档 {len(BATCH8_A)} 封")
    elif getattr(args, "batch7_a2", False):
        print(f"扫描范围：batch7 A 档二次深挖升级 {len(BATCH7_A2)} 封")
    elif getattr(args, "batch7_a", False):
        print(f"扫描范围：batch7 A 档 {len(BATCH7_A)} 封")
    elif getattr(args, "batch4_resend", False):
        print(f"扫描范围：batch4 补发 {len(BATCH4_RESEND)} 封")
    elif getattr(args, "batch6_all", False):
        print(f"扫描范围：batch6 首封 {len(BATCH6_LETTERS)} 封 + 跟进 {len(BATCH6_FOLLOWUP)} 封")
    elif getattr(args, "batch6", False):
        print(f"扫描范围：batch6 A 档 {len(BATCH6_LETTERS)} 封")
    elif getattr(args, "batch5", False):
        print(f"扫描范围：batch5 A 档 {len(BATCH5_LETTERS)} 封")
    else:
        print(f"扫描范围：{'全部信件' if getattr(args,'all',False) else f'仅本项目产出的 {len(OWN_LETTERS)} 封'}")
    if BL:
        n_addr = sum(1 for k in BL if not k.startswith("@"))
        n_dom = len(BL) - n_addr
        extra = f" + {n_dom} 个整域封锁" if n_dom else ""
        print(f"退信闸门：已载入 {n_addr} 个黑名单地址{extra}")
    for f in scope:
        subjects, body, notes = sd.parse_letter(f)
        rc = sd.recipients_of(notes)
        if not rc:
            continue
        # 🔴 2026-09-28 修复（与 --run 保持一致；此前 --build 漏了这一步）：
        #   校验的必须是**最终投递的正文**，即已裁掉尾部「职务/公司/邮箱」行的版本。
        #   旧代码拿未裁剪的 body 去校验 → 每封都命中「正文里仍有旧式署名行」
        #   → 21 封全部误判为 blocked，队列实际发不出去。
        #   与 发送开发信.py 的 main() 同源：校验前先 trim。
        body = sd.trim_signature_tail(body)
        problems = list(sd.compliance_check(body, sd.load_signature()))
        # 退信闸门
        # 🔴 2026-10-05：跟进信走**零退信**口径（strict_followup=True）
        _is_fu = is_followup_item({"letter": f.name,
                                   "subject": subjects[0] if subjects else ""})
        for a in rc:
            blocked, why = is_blocked(a, now, BL, strict_followup=_is_fu)
            if blocked:
                problems.append(f"退信闸门：{a} — {why}")
                break
        # 地址验证（L1+L2：语法 / 一次性邮箱 / MX 记录）
        if not any(p.startswith("退信闸门") for p in problems):
            for a in rc:
                # 🔴 2026-09-28 修复：MX 查询是**网络调用**，会偶发超时/失败。
                #   实测 136 ABCO（Outlook/M365 网关，MX 确实存在）在首次建队列时
                #   被判「域名没有 MX 记录」→ 整封信被静默拦下、不进队列、永不投递。
                #   这是**假阴性**：重跑一次即恢复。
                #   故对「MX 类」拦截做**重试**（最多 3 次、递增退避），
                #   只有连续失败才认定为真拦截。
                v = None
                for attempt in range(3):
                    v = AV.verify(a, do_probe=False, polite_delay=0)
                    if not v["verdict"].startswith("⛔"):
                        break
                    if "MX" not in "".join(v.get("notes") or []):
                        break          # 非 MX 类拦截（语法/一次性邮箱）→ 无需重试
                    if attempt < 2:
                        import time
                        time.sleep(1.5 * (attempt + 1))   # 1.5s → 3s
                if v and v["verdict"].startswith("⛔"):
                    problems.append(f"地址验证：{a} — {v['notes'][-1]}")
        tz = tz_of_letter(notes, body, f.read_text(encoding="utf-8"))
        w = next_window(tz, now) if tz else None
        # 注：`subjects` 已在循环开头解析（2026-10-05 起），此处不再重复解析
        items.append({
            "letter": f.name,
            "to": rc,
            "subject": subjects[0] if subjects else f.stem,
            "tz": tz or "?",
            "window_start_bj": w["bj_start"].strftime("%Y-%m-%d %H:%M") if w else "",
            "window_end_bj": w["bj_end"].strftime("%Y-%m-%d %H:%M") if w else "",
            "window_start_local": w["local_start"].strftime("%Y-%m-%d %H:%M") if w else "",
            "window_end_local": w["local_end"].strftime("%Y-%m-%d %H:%M") if w else "",
            "local_label": TZ_CN.get(tz, tz),
            "dst": w["dst"] if w else None,
            "status": "pending" if not problems else "blocked",
            "blocked_reason": "; ".join(problems) if problems else "",
            "queued_at": now.strftime("%Y-%m-%d %H:%M"),
            "sent_at": None,
        })
    # ---- 窗口内分散：同一 (时区, 窗口日) 分组均匀铺开 ----
    import random
    groups = {}
    for i in items:
        if i["status"] != "pending" or not i.get("window_start_bj"):
            continue
        groups.setdefault(i["window_start_bj"][:10] + "|" + i["tz"], []).append(i)
    for key, grp in groups.items():
        n = len(grp)
        # 🔴 2026-09-28 重写：**自适应槽位分配**（原实现有 3 处缺陷）
        #
        #  问题背景：若「建队列时已身处窗口内」（例 now=21:2x，ET 窗口 21:00–22:00），
        #  next_window 会把起点抬到当前之后，可用时间只剩十几分钟，而本组有 7 封。
        #  旧的「固定 60 分钟铺开 + floor 吸附」会导致：
        #    ① 后几封漂出当地 10:00（实测 10:00/10:10/10:20/10:30）→ 违约；
        #    ② 相邻两封被 floor 压到同一分钟 → 同刻并发（群发特征）。
        #
        #  新算法：在**客户当地 09:00–10:00 的硬边界内**，把 n 封信分配到
        #  尽可能均匀、且**互不重复**的分钟槽上（取两两间隔 >= MIN_GAP 分钟）。
        #  若窗口太窄放不下（n × MIN_GAP > 可用分钟），则允许间隔自动缩小到 1 分钟；
        #  最后仍冲突才用秒级错开。绝不越窗、绝不并发。
        base = datetime.strptime(grp[0]["window_start_bj"], "%Y-%m-%d %H:%M")
        tz0 = grp[0]["tz"]
        delta0 = 8 - TZ_OFFSET_DST.get(tz0, -5)
        loc_start = (base - timedelta(hours=delta0)).replace(second=0, microsecond=0)
        # 当地窗口的整点起点与硬上界（客户当地 09:00 → 10:00）
        loc_hour0 = loc_start.replace(minute=0)
        bj_lo = loc_hour0 + timedelta(hours=delta0)                 # 北京：当地 09:00
        bj_hi = loc_hour0 + timedelta(hours=WINDOW_SPAN) + timedelta(hours=delta0)  # 当地 10:00
        # 实际可用的起点：不能早于「现在之后」，故取 max
        bj_lo = max(bj_lo, base)
        avail = int((bj_hi - bj_lo).total_seconds() // 60)          # 可用分钟数
        n_eff = max(n, 1)
        # 均匀间隔：优先 5 分钟（与外部调度同刻度），放不下则压缩
        gap = max(1, min(SLOT_MINUTES, avail // n_eff if avail >= n_eff else 1))
        grp.sort(key=lambda x: x["letter"])
        used = set()
        for idx, it in enumerate(grp):
            delta_i = 8 - TZ_OFFSET_DST.get(it["tz"], -5)
            # 均匀落点（居中），并吸附到 gap 刻度
            raw = bj_lo + timedelta(minutes=(idx + 0.5) * avail / n_eff)
            off = int((raw - bj_lo).total_seconds() // 60)
            off = (off // gap) * gap
            sched = bj_lo + timedelta(minutes=min(off, max(0, avail - 1)))
            # 冲突则顺延到下一个未占用槽
            guard = 0
            while sched.strftime("%Y-%m-%d %H:%M") in used and guard < 1000:
                sched += timedelta(minutes=gap)
                if sched >= bj_hi:
                    sched = bj_hi - timedelta(minutes=1)
                    if sched.strftime("%Y-%m-%d %H:%M") in used:
                        break
                guard += 1
            used.add(sched.strftime("%Y-%m-%d %H:%M"))
            it["scheduled_at_bj"] = sched.strftime("%Y-%m-%d %H:%M")
            it["scheduled_at_local"] = (
                sched - timedelta(hours=delta_i)
            ).strftime("%Y-%m-%d %H:%M")
        # 分组内按计划时刻排序展示
        grp.sort(key=lambda x: x["scheduled_at_bj"])

    # ============================================================
    # 🔴 2026-09-29 新增：**跨时区同刻去重**（全局）
    #    分组内已去重，但**不同时区组可能撞到同一分钟**
    #    （实测 batch6 合并队列里 AZ 与 PT 各 1 封撞在 00:45）。
    #    「同一分钟多封发出」是最典型的垃圾邮件特征，故全局再扫一遍；
    #    撞车者顺延 SLOT_MINUTES 分钟，**仍须留在自己的送达窗口内**。
    # ============================================================
    _seen = {}
    for it in sorted([x for x in items if x.get("scheduled_at_bj")],
                     key=lambda x: x["scheduled_at_bj"]):
        key = it["scheduled_at_bj"]
        if key not in _seen:
            _seen[key] = it
            continue
        tz = it.get("tz", "")
        delta_i = 8 - TZ_OFFSET_DST.get(tz, -5)
        hi = datetime.strptime(it["window_end_bj"], "%Y-%m-%d %H:%M")
        sched = datetime.strptime(key, "%Y-%m-%d %H:%M")
        newkey = key
        for _ in range(24):
            sched += timedelta(minutes=SLOT_MINUTES)
            if sched >= hi:
                sched = hi - timedelta(minutes=1)
            newkey = sched.strftime("%Y-%m-%d %H:%M")
            if newkey not in _seen:
                break
        _seen[newkey] = it
        it["scheduled_at_bj"] = newkey
        it["scheduled_at_local"] = (
            sched - timedelta(hours=delta_i)
        ).strftime("%Y-%m-%d %H:%M")

    write_queue(items)
    ok = sum(1 for i in items if i["status"] == "pending")
    bl = sum(1 for i in items if i["status"] == "blocked")
    print(f"已建立队列：{QUEUE}")
    print(f"  可发 {ok} 封 / 被红线拦截 {bl} 封 / 共 {len(items)} 封")

    # 🔴🔴 2026-10-02 新增「静默跳过体检」—— 把文档规则落成代码
    #    `recipients_of()` 取不到收件人时，本函数会 `if not rc: continue` **静默跳过**：
    #      · batch8 漏 5/25（20%）
    #      · batch9 漏 19/30（63%）
    #    两次都**不报错、不提示**，只表现为「可发 N 封」比预期少 —— 极易被当成正常。
    #    此处把「扫描范围」与「实际入队」做差，把被跳过的文件**点名打印**。
    n_scope, n_items = len(scope), len(items)
    if n_scope > n_items:
        built = {i["letter"] for i in items}
        skipped = [f.name for f in scope if f.name not in built]
        print()
        print(f"  🔴🔴 警告：扫描 {n_scope} 封，只入队 {n_items} 封 —— "
              f"**静默跳过 {len(skipped)} 封**！")
        print("      （最常见原因：中文注解段没有可解析的收件人行。"
              "需在**注解段首**加 `- **收件人**：**姓名 · 职务**（`email`）`）")
        for s in skipped:
            print(f"      ⛔ {s}")
        print("      ⇒ 补齐后**重跑 --build**；否则这些信永远不会发出。")
    if bl:
        print()
        print("  被拦截的（红线自检未过）：")
        for i in items:
            if i["status"] == "blocked":
                print(f"    {i['letter'][:42]:<44} {i['blocked_reason'][:60]}")
    return 0


def cmd_status(sd, args):
    items = read_queue()
    if not items:
        print(f"队列为空。先跑：python3 定时发送.py --build")
        return 0
    now = datetime.now(BJ)
    print(f"队列：{QUEUE}    当前北京时间 {now:%Y-%m-%d %H:%M}")
    print()
    print(f"{'状态':<8}{'时区':<11}{'发送（北京）':<17}{'送达（客户当地）':<17}{'收件人':<34}信件")
    print("─" * 128)
    for i in sorted(items, key=lambda x: x.get("scheduled_at_bj") or x.get("window_start_bj") or ""):
        mark = ""
        k = i.get("scheduled_at_bj") or i.get("window_start_bj") or ""
        if i["status"] == "pending" and k and k <= now.strftime("%Y-%m-%d %H:%M"):
            mark = "  ← 到点"
        bj = (i.get("scheduled_at_bj") or i.get("window_start_bj", ""))[5:16]
        lo = (i.get("scheduled_at_local") or i.get("window_start_local", ""))[5:16]
        loc = i.get("local_label", "")
        print(f"{i['status']:<8}{i['tz'] + ' ' + loc:<11}{bj:<17}{lo:<17}"
              f"{(','.join(i['to']))[:32]:<34}{i['letter'][:32]}{mark}")
    print()
    p = sum(1 for i in items if i["status"] == "pending")
    d = sum(1 for i in items if i["status"] == "pending"
            and (i.get("scheduled_at_bj") or "") <= now.strftime("%Y-%m-%d %H:%M"))
    print(f"待发 {p} 封，其中已到点 {d} 封")
    print(f"（发送＝北京时间；送达＝客户当地。目标窗口：当地工作日 {TARGET_LOCAL_HOUR}:00–{TARGET_LOCAL_HOUR + WINDOW_SPAN}:00，窗口内分散发送）")
    return 0


def cmd_run(sd, args):
    items = read_queue()
    if not items:
        print("队列为空。先跑：--build")
        return 0
    now = datetime.now(BJ)
    nows = now.strftime("%Y-%m-%d %H:%M")

    def _due_key(i):
        return i.get("scheduled_at_bj") or i.get("window_start_bj") or ""
    due = [i for i in items
           if i["status"] == "pending"
           and (args.force_window or _due_key(i) <= nows)]
    if args.limit:
        due = due[:args.limit]

    if not due:
        nxt = min((_due_key(i) for i in items if i["status"] == "pending"), default=None)
        print(f"当前 {nows}，没有到点的信。")
        if nxt:
            print(f"下一封的窗口起点：{nxt}")
        return 0

    dry = not args.send
    print(f"当前北京时间 {nows}　{'【预演】' if dry else '★ 真实发送 ★'}")
    print(f"到点待发：{len(due)} 封")
    print()
    for i in due:
        print(f"  发送 北京 {i.get('scheduled_at_bj','')[5:16]}  →  "
              f"送达 {i.get('local_label','')} 当地 {i.get('scheduled_at_local','')[5:16]}"
              f"   {(','.join(i['to']))[:28]:<30}{i['letter'][:30]}")
    print()

    if dry:
        print("（未加 --send，仅预演）")
        return 0
    if not args.yes and input("确认发送请输入 yes：").strip().lower() != "yes":
        print("已取消。")
        return 1

    mailer = sd.load_mailer()
    cfg = mailer.load_config()
    sig = sd.load_signature()
    okn = badn = 0

    BL = load_blacklist()
    for i in due:
        f = CLIENTS / i["letter"]
        subjects, body, notes = sd.parse_letter(f)
        # 🔴 2026-09-28 修复：与 发送开发信.py 主链路保持一致，
        # 必须裁掉正文尾部的「职务/公司/邮箱」行，否则收件人会看到
        # 职务与邮箱重复两次（正文一次 + 图片签名一次）。
        # 依据：正文格式规范.md §一「`{{SENDER_NAME}}` 与图片签名之间零内容」。
        body = sd.trim_signature_tail(body)
        skip = False
        # 🔴 2026-10-05：跟进信走**零退信**口径
        _is_fu = is_followup_item(i)
        for a in i["to"]:
            blocked, why = is_blocked(a, datetime.now(BJ), BL, strict_followup=_is_fu)
            if blocked:
                print(f"  ⛔ 跳过 {i['letter'][:40]}：{a} — {why}")
                i["status"] = "skipped"
                i["blocked_reason"] = why
                skip = True
                break
        if skip:
            write_queue(items)
            continue
        html = sd.build_html(body, sig)
        to = [args.to] if args.to else i["to"]
        if args.to:
            print(f"  ⚠️  重定向：{i['to']} → {args.to}")
        subject = subjects[0] if subjects else i["subject"]
        # 🔴 2026-09-28 新增抄送支持：信封收件人必须含 cc（smtp_send 用 to_addrs）
        cc = i.get("cc") or []
        msg = mailer.build_message(cfg, to, subject, html=html, inline=True,
                                   cc=cc or None)
        ok, err = mailer.smtp_send(cfg, msg, to + cc)
        if ok:
            _cctxt = f" ｜cc {', '.join(cc)}" if cc else ""
            print(f"  ✅ {i['letter'][:44]} → {', '.join(to)}{_cctxt}")
            i["status"] = "sent"
            i["sent_at"] = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
            okn += 1
        else:
            print(f"  ❌ {i['letter'][:44]}：{str(err)[:110]}")
            i["status"] = "failed"
            i["blocked_reason"] = str(err)[:200]
            badn += 1
        write_queue(items)      # 每封落盘，中断也不丢状态

    print()
    print(f"完成：成功 {okn} / 失败 {badn}")
    return 0


def cmd_daemon(sd, args):
    """🔴 2026-09-28 新增：**常驻守候模式**（本批实际使用）。

    为什么需要它：
      外部任务系统的最小调度粒度是**整点**（实测 `FREQ=HOURLY;BYMINUTE=…`
      的 nextRunAt 被推到下一个整点，分钟级 BYMINUTE 不被兑现）。
      而本批 21 封散布在 21:40–00:50 的**分钟级**时刻上，
      靠「每 5 分钟轮询」会整组漂移、甚至整批漏发。
      故改为：**本脚本自己守候**，到点即发，不依赖外部调度精度。

    行为：
      - 读取队列，按 scheduled_at_bj 排序，逐封等待到点后投递。
      - 已 status=sent 的跳过（幂等：中断后重跑不会重发）。
      - 每封之间按计划时刻 sleep，不使用固定间隔。
      - 全部发完或队列清空后自动退出。
      - 可安全中断：已发的标记已写盘，重跑续发。

    用法：
      python3 定时发送.py --daemon --send --yes      # 守候并发完（前台阻塞）
    """
    # 🔴 2026-09-28 单实例锁：防止两个 daemon 同时跑 → 同一封信被投递两次。
    #    背景：当晚实测真的发生过 —— 自动化任务与手动启动各拉起一个进程，
    #    `{{CONTACT_EMAIL}}` 与 `{{CONTACT_EMAIL}}` 各被投递 2 次
    #    （间隔 1 秒，属两次独立 SMTP 投递）。锁是唯一的根治手段。
    LOCK = ROOT / ".daemon.lock"
    if LOCK.exists():
        try:
            old = int(LOCK.read_text().strip())
        except Exception:
            old = 0
        alive = False
        if old:
            try:
                os.kill(old, 0)          # 不真发信号，只探测进程是否存活
                alive = True
            except (ProcessLookupError, PermissionError):
                alive = False
        if alive:
            print(f"⛔ 已有守护进程在运行（PID {old}），本进程退出，避免重复投递。")
            print(f"   如需强制重启：kill {old} 或删除 {LOCK.name}")
            return 0
        print(f"⚠️  发现过期锁（PID {old} 已不存在），继续启动。")
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(lambda: LOCK.unlink(missing_ok=True))
    print(f"🔒 已加锁 {LOCK.name}（PID {os.getpid()}）")

    items = read_queue()
    if not items:
        print("队列为空。先跑：--build --batch5")
        return 0

    def _key(i):
        return i.get("scheduled_at_bj") or i.get("window_start_bj") or ""

    pend = sorted([i for i in items if i["status"] == "pending" and _key(i)],
                  key=_key)
    if not pend:
        print("没有 pending 的信。")
        return 0

    print(f"守候模式启动：待发 {len(pend)} 封")
    print(f"  最早 {_key(pend[0])}  /  最晚 {_key(pend[-1])}（北京时间）")
    print("  （中断后重跑此命令可续发，已发的不会重复）")
    print()

    mailer = sd.load_mailer()
    cfg = mailer.load_config()
    sig = sd.load_signature()
    BL = load_blacklist()
    okn = badn = 0
    # 🔴 2026-09-28 补发节流：守护进程被中断后重跑时，`remain <= 0` 的信会**立即补发**。
    #    若一次性迟到多封，就会在同一秒连发 → 正是用户明确要避免的「同时发」，
    #    也是群发特征。故记录**实际投递时刻**，强制任意两次投递间隔 >= 此值。
    MIN_CATCHUP_GAP = 3          # 分钟
    last_sent = None

    for i in pend:
        when = datetime.strptime(_key(i), "%Y-%m-%d %H:%M").replace(tzinfo=BJ)
        # 到点前守候（每分钟醒一次打印倒计时，便于观察）
        while True:
            now = datetime.now(BJ)
            remain = (when - now).total_seconds()
            if last_sent is not None:
                since = (now - last_sent).total_seconds()
                if since < MIN_CATCHUP_GAP * 60:
                    time.sleep(min(20, max(1, MIN_CATCHUP_GAP * 60 - since)))
                    continue
            if remain <= 0:
                break
            time.sleep(min(30, remain))

        # 重新读盘：防止与其它进程/手动操作冲突
        items = read_queue()
        cur = next((x for x in items if x["letter"] == i["letter"]), None)
        if cur is None or cur.get("status") != "pending":
            continue

        f = CLIENTS / cur["letter"]
        subjects, body, notes = sd.parse_letter(f)
        body = sd.trim_signature_tail(body)
        skip = False
        # 🔴 2026-10-05：跟进信走**零退信**口径
        _is_fu = is_followup_item(cur)
        for a in cur["to"]:
            blocked, why = is_blocked(a, datetime.now(BJ), BL, strict_followup=_is_fu)
            if blocked:
                print(f"  ⛔ 跳过 {cur['letter'][:40]}：{a} — {why}")
                cur["status"] = "skipped"
                cur["blocked_reason"] = why
                skip = True
                break
        if skip:
            write_queue(items)
            continue

        html = sd.build_html(body, sig)
        to = [args.to] if getattr(args, "to", None) else cur["to"]
        cc = cur.get("cc") or []          # 🔴 2026-09-28 抄送支持
        # 🔴 测试重定向必须**同时清掉抄送**：否则 `--to 自己` 只改主送，
        #    抄送人（如 {{CONTACT_EMAIL}}）仍会收到真实邮件 —— 测试变误发。
        if getattr(args, "to", None) and cc:
            print(f"  ⚠️  测试重定向：已忽略抄送 {', '.join(cc)}")
            cc = []
        subject = subjects[0] if subjects else cur["subject"]
        msg = mailer.build_message(cfg, to, subject, html=html, inline=True,
                                   cc=cc or None)
        ok, err = mailer.smtp_send(cfg, msg, to + cc)
        stamp = datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")
        if ok:
            _cctxt = f" ｜cc {', '.join(cc)}" if cc else ""
            print(f"  ✅ [{stamp}] {cur['letter'][:44]} → {', '.join(to)}{_cctxt}")
            cur["status"] = "sent"
            cur["sent_at"] = stamp
            last_sent = datetime.now(BJ)     # 🔴 补发节流用：记录实际投递时刻
            okn += 1
        else:
            print(f"  ⛔ [{stamp}] {cur['letter'][:44]} 发送失败：{err}")
            cur["status"] = "failed"
            cur["blocked_reason"] = str(err)
            badn += 1
        write_queue(items)

    print()
    print(f"守候结束：成功 {okn} 封 / 失败 {badn} 封")
    return 0


def main():
    ap = argparse.ArgumentParser(description="开发信定时发送队列")
    ap.add_argument("--build", action="store_true", help="扫描信件建立/重建队列")
    ap.add_argument("--status", action="store_true", help="查看队列")
    ap.add_argument("--run", action="store_true", help="发送窗口已到的信")
    ap.add_argument("--daemon", action="store_true",
                    help="守候模式：到点即发，发完退出（本批推荐）")
    ap.add_argument("--send", action="store_true", help="--run 时真正发送")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    ap.add_argument("--to", help="【测试】重定向全部收件人")
    ap.add_argument("--limit", type=int, help="本次最多发几封")
    ap.add_argument("--force-window", action="store_true", help="忽略窗口，立即发（调试）")
    ap.add_argument("--all", action="store_true",
                    help="【慎用】连项目中已有的 130 封旧信一起处理（默认只处理本项目产出的信）")
    ap.add_argument("--batch5", action="store_true",
                    help="只处理 batch5 A 档 21 封（用户 2026-09-28 指令的那批）")
    ap.add_argument("--batch6", action="store_true",
                    help="只处理 batch6 A 档 23 封（用户 2026-09-29 指令的那批）")
    ap.add_argument("--batch6-all", dest="batch6_all", action="store_true",
                    help="batch6 首封 23 + 跟进 21 = 44 封合并入队")
    ap.add_argument("--batch4-resend", dest="batch4_resend", action="store_true",
                    help="batch4 历史缺口补发 5 封（需配 --queue 走独立队列）")
    ap.add_argument("--batch7-a", dest="batch7_a", action="store_true",
                    help="batch7 A 档 7 封（需配 --queue 走独立队列）")
    ap.add_argument("--batch7-a2", dest="batch7_a2", action="store_true",
                    help="batch7 A 档二次深挖升级 4 封（需配 --queue 走独立队列）")
    ap.add_argument("--batch8-a", dest="batch8_a", action="store_true",
                    help="batch8 A 档 25 封（需配 --queue 走独立队列）")
    ap.add_argument("--batch9-a", dest="batch9_a", action="store_true",
                    help="batch9 A 档 30 封（需配 --queue 走独立队列）")
    ap.add_argument("--batch11-a", dest="batch11_a", action="store_true",
                    help="batch11 A 档 22 封（需配 --queue 走独立队列）")
    ap.add_argument("--batch10-a", dest="batch10_a", action="store_true",
                    help="batch10 A 档 28 封（需配 --queue 走独立队列）")
    ap.add_argument("--queue", help="【独立队列】覆盖队列文件路径，默认 发信队列.json")
    args = ap.parse_args()

    if args.queue:
        global QUEUE
        QUEUE = Path(args.queue)
        print(f"队列文件（覆盖）：{QUEUE}")

    sd = load_sd()
    if args.build:
        global AV
        AV = load_verifier()
        return cmd_build(sd, args)
    if args.daemon:
        if not args.send:
            print("--daemon 必须配 --send 才真正投递（先 --status 复核）。")
            return 1
        return cmd_daemon(sd, args)
    if args.status or (not args.run):
        return cmd_status(sd, args)
    return cmd_run(sd, args)


if __name__ == "__main__":
    sys.exit(main() or 0)
