#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「batch5 A档 21 封待发清单」Excel。

数据来源：直接复用 发送开发信.py 的 parse_letter / recipients_of /
compliance_check，**不手工誊抄**，避免抄错。时区/档位从批注行里正则提取。

用法：
    python3 生成发送清单.py
产出：
    开发信项目/📋待发清单-batch5_A档21封.xlsx
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent

# 复用主脚本的解析/校验逻辑（单一真源）
sys.path.insert(0, str(ROOT))
import importlib.util

spec = importlib.util.spec_from_file_location("sd", ROOT / "发送开发信.py")
sd = importlib.util.module_from_spec(spec)
sys.modules["sd"] = sd
spec.loader.exec_module(sd)

# A 档 21 封（用户确认的发送名单；161/165/167/153 已暂缓，不计入）
A_TIER = [
    "{{COMPANY}}", "TN-Electrical",
    "{{COMPANY}}", "{{COMPANY}}",
    "{{COMPANY}}", "{{COMPANY}}", "{{COMPANY}}",
    "{{COMPANY}}", "{{COMPANY}}",
    "{{COMPANY}}", "{{COMPANY}}", "{{COMPANY}}",
    "{{COMPANY}}", "{{COMPANY}}", "{{COMPANY}}",
    "{{COMPANY}}", "{{COMPANY}}",
    "{{COMPANY}}", "{{COMPANY}}",
    "Access-Electrical-Supply", "{{COMPANY}}",
]

COMPANY = {
    "{{COMPANY}}": "{{COMPANY}}",
    "TN-Electrical": "T & N Electrical Contracting Ltd.",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}} & Electrical",
    "{{COMPANY}}": "{{COMPANY}} & Service",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "{{COMPANY}}": "{{COMPANY}}",
    "Access-Electrical-Supply": "Access Electrical Supply",
    "{{COMPANY}}": "{{COMPANY}}",
}


def buyer_no(text: str) -> str:
    """买家编号有三种载体，按序尝试：
    ① H1 标题  `# 开发信 — XXX（买家 132）`     ← 本批主流
    ② 头部引用  `> 买家编号：**129**`             ← 129/130 用
    ③ 批注块内  `买家编号：**129**`
    """
    for rx in (r"买家\s*(\d+)\s*[）)]", r"买家编号[：:]\s*\*\*(\d+)\*\*"):
        m = re.search(rx, text)
        if m:
            return m.group(1)
    return ""


def tier_of(full: str, notes: str) -> str:
    """档位判定——只认「收件人」那一行，禁止扫全文。

    踩过的坑：Montgomery 的批注里有一行
    `- 备选（第二轮）：\\`info@…\\`（B 档，已验证存在）`
    ——它是**备选邮箱**的档位，不是**主送**档位。早期版本先扫 notes 再扫全文，
    于是把主送 A 档误判成 B 档。现改为：
      ① 优先在头部引用块里抓「收件人：…（**A 档 · 说明**）」
      ② 回退到批注里的「主送依据：**A 档**」（只匹配「主送依据」，不匹配「备选」）
    """
    # ① 头部「收件人：**姓名 · 职务** ｜ `mail`（X 档 · …）」，允许 **X 档** 加粗包裹
    m = re.search(r"收件人[：:][^\n]*?[（(]\s*\*{0,2}\s*([ABC])\s*档", full)
    if m:
        return m.group(1)
    # ② 批注「主送依据：**X 档 …**」
    m = re.search(r"主送依据[：:]\s*\*{0,2}\s*([ABC])\s*档", notes)
    if m:
        return m.group(1)
    # ③ 「邮箱档位：**A** — …」
    m = re.search(r"邮箱档位[^\n]*?([ABC])\s*[（(]", notes)
    if m:
        return m.group(1)
    m = re.search(r"邮箱档位[^\n]{0,8}\*{0,2}([ABC])\*{0,2}", notes)
    return m.group(1) if m else ""


def tz_of(full: str, notes: str) -> str:
    """提取「省/州 + 时区缩写 + 北京窗口」。

    原文样例：
      头部  `> 拟发送时段：ON 省 = 东部时区（ET）｜当地工作日 08:00–10:00 = **北京 20:00–22:00（夏令时）**`
      批注  `- **发送时段**：客户 **BC 省 = 太平洋时区（PT）**；目标送达当地工作日 **08:00–10:00**`
             （批注体**不给**北京窗口 → 需按 PT/ET/CT/MT 自算）
    """
    src = full + "\n" + notes
    prov = ""
    m = re.search(r"([A-Z]{2})\s*(?:省|州)", src)
    if not m:
        m = re.search(r"\b([A-Z]{2})\s*=\s*\**\s*(?:山地|中部|东部|太平洋|山区)时区", src)
    if m:
        prov = m.group(1)
    tzabbr = ""
    m = re.search(r"(太平洋|东部|中部|山地|山区)时区[^\n]{0,8}?[（(]([A-Z]{2,3})", src)
    if m:
        tzabbr = m.group(2)
    # 北京窗口：优先读原文（头部有），读不到再按夏令时（UTC-7/-4/-5/-6）自算
    win = ""
    m = re.search(r"北京\s*\**\s*(\d{1,2}:\d{2}\s*[–\-~至]\s*\d{1,2}:\d{2})", src)
    if m:
        win = re.sub(r"\s+", "", m.group(1))
    elif tzabbr:
        OFF = {"PT": 15, "MT": 14, "CT": 15, "ET": 12}  # 当地 08:00 → 北京 = 8 + delta
        # UTC-7 → 北京 +15h；UTC-6 → +14h（但 +8:00 与 +8:30 起送窗口不同，取 08:00 起算）
        delta = {"PT": 15, "MT": 14, "CT": 14, "ET": 12}.get(tzabbr, 0)
        if delta:
            h1 = (8 + delta) % 24
            h2 = (10 + delta) % 24
            win = f"{h1:02d}:00–{h2:02d}:00"
    parts = [p for p in (prov, tzabbr, win) if p]
    return " ".join(parts)


def country_of(full: str, name: str) -> str:
    """国家判定：看省/州代码。加拿大省码 vs 美国州码不重叠。"""
    CA = {"BC", "AB", "SK", "MB", "ON", "QC", "NB", "NS", "PE", "NL"}
    US = {"TX", "UT", "CA", "NY", "WA", "OR", "AZ", "CO", "IL"}
    m = re.search(r"([A-Z]{2})\s*(?:省|州)", full)
    if not m:
        # UTB 的写法是 `UT = **山地时区（MT，MST/UTC-7）**`，省码后跟 `=` 而非「州」
        m = re.search(r"\b([A-Z]{2})\s*=\s*\**\s*(?:山地|中部|东部|太平洋|山区)时区", full)
    if m:
        code = m.group(1)
        if code in CA:
            return "加拿大"
        if code in US:
            return "美国"
    # 回退：按项目知识——美国样本极少（Shermco=TX, UTB=UT）
    if name in ("{{COMPANY}}", "{{COMPANY}}"):
        return "美国"
    return "加拿大"


def product_of(notes: str) -> str:
    """产品切片：优先读批注；回退按国家。"""
    seg = "配电级(E541627)"
    if "E541626" in notes and "E541627" in notes:
        return "E541627+E541626"
    if "E541626" in notes:
        return "E541626"
    if "E541627" in notes:
        return "E541627"
    return seg


rows = []
for name in A_TIER:
    f = sd.CLIENTS / f"开发信-{name}.md"
    if not f.exists():
        print(f"⛔ 缺文件：{f}")
        continue
    subjects, body, notes = sd.parse_letter(f)
    full = f.read_text(encoding="utf-8")
    body = sd.trim_signature_tail(body)
    problems = sd.compliance_check(body, sd.load_signature())
    wc = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", body))
    rc = sd.recipients_of(notes)
    rows.append({
        "no": buyer_no(full),
        "company": COMPANY.get(name, name),
        "file": f.name,
        "to": rc[0] if rc else "（批注未标）",
        "subj": subjects[0] if subjects else "（无）",
        "wc": wc,
        "tier": tier_of(full, notes),
        "country": country_of(full, name),
        "tz": tz_of(full, notes),
        "prod": product_of(notes),
        "ok": not problems,
        "problems": "；".join(problems),
    })

rows.sort(key=lambda r: int(r["no"]) if r["no"].isdigit() else 999)

# ---------------- 写 Excel ----------------
wb = Workbook()
ws = wb.active
ws.title = "待发清单_A档21封"

HEAD = ["序", "买家编号", "公司", "信件文件", "收件人邮箱", "主题行（备选1）",
        "词数", "档位", "国家", "时区/北京窗口", "产品切片", "红线自检"]
ws.append(HEAD)

for i, r in enumerate(rows, 1):
    ws.append([
        i, r["no"], r["company"], r["file"], r["to"], r["subj"],
        r["wc"], r["tier"], r["country"], r["tz"], r["prod"],
        "✅ 通过" if r["ok"] else f"⛔ {r['problems']}",
    ])

# 样式
thin = Side(style="thin", color="BFBFBF")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
head_fill = PatternFill("solid", fgColor="1F4E79")
head_font = Font(bold=True, color="FFFFFF", size=11)

for c in range(1, len(HEAD) + 1):
    cell = ws.cell(row=1, column=c)
    cell.fill = head_fill
    cell.font = head_font
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = border

for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(HEAD)):
    for cell in row:
        cell.border = border
        cell.alignment = Alignment(vertical="center", wrap_text=(cell.column in (4, 5, 6, 10, 12)))

widths = [5, 9, 34, 44, 34, 46, 7, 7, 9, 26, 18, 22]
for i, w in enumerate(widths, 1):
    ws.column_dimensions[get_column_letter(i)].width = w
ws.freeze_panes = "A2"
ws.row_dimensions[1].height = 30

# ---------------- 汇总页 ----------------
ws2 = wb.create_sheet("汇总")
ok = sum(1 for r in rows if r["ok"])
ca = sum(1 for r in rows if r["country"] == "加拿大")
us = sum(1 for r in rows if r["country"] == "美国")
a_t = sum(1 for r in rows if r["tier"] == "A")
b_t = sum(1 for r in rows if r["tier"] == "B")
body_wc = [r["wc"] for r in rows]

summary = [
    ["batch5 待发清单（A档22封中已完成的 21 封）— 汇总", ""],
    ["", ""],
    ["待发封数", f"{len(rows)} 封"],
    ["红线自检通过", f"{ok} / {len(rows)}"],
    ["邮箱档位 A（具名决策人 · 可主送）", f"{a_t} 封"],
    ["邮箱档位 B（角色/公示邮箱 · 亦具名）", f"{b_t} 封"],
    ["加拿大客户", f"{ca} 封"],
    ["美国客户", f"{us} 封"],
    ["", ""],
    ["词数区间", f"{min(body_wc)} – {max(body_wc)} 词（规范 60–150）"],
    ["主题行备选", "每封 3 条，本表列备选 1"],
    ["", ""],
    ["第二批（另见暂缓清单）", "161 Beaver / 165 {{COMPANY}} / 167 AESCO / 153 Steinmetz"],
    ["永久排除", "138 ETAC / 141 Trinity / Rionex / {{COMPANY}} / Maddox"],
    ["", ""],
    ["发送时间窗口", "务必按客户当地工作日 08:00–10:00（夏令时）"],
    ["加拿大周末/法定假日", "一律不发"],
    ["", ""],
    ["表内档位说明", "B 档 ≠ 不可发。157/169/170 均为自有具名决策人邮箱（第一方官网公示），照常主送"],
]
for r_ in summary:
    ws2.append(r_)
ws2["A1"].font = Font(bold=True, size=14)
for r_ in range(1, ws2.max_row + 1):
    ws2.cell(row=r_, column=1).alignment = Alignment(horizontal="left")
    ws2.cell(row=r_, column=2).alignment = Alignment(horizontal="left")
ws2.column_dimensions["A"].width = 32
ws2.column_dimensions["B"].width = 60

out = ROOT / "开发信项目" / "📋待发清单-batch5_A档21封.xlsx"
wb.save(out)

print(f"✅ 已生成：{out}")
print(f"   共 {len(rows)} 封 ｜ 红线通过 {ok}/{len(rows)} ｜ 词数 {min(body_wc)}–{max(body_wc)}")
print()
for r in rows:
    flag = "✅" if r["ok"] else f"⛔ {r['problems']}"
    print(f"  {r['no']:>4} | {r['company'][:30]:<30} | {r['to']:<36} | {r['wc']:>3}词 | {flag}")
if any(not r["ok"] for r in rows):
    sys.exit(2)
