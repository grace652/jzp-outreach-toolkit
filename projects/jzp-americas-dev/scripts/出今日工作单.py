#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产出「今日跟进」工作单（含实测线程主题，供写信环节用）

给每一家输出：编号 / 公司 / 州省 / 邮箱 / 次数(轮次) / **实测最近一次发出的主题**
（写信时的 `Re:` 必须用它 —— 信件里的备选未必是实际发出去的那条）。
"""

import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import timedelta, timezone, datetime
from pathlib import Path

import openpyxl

ROOT = Path(Path(__file__).resolve().parents[1])
import os
TODAY = os.environ.get("JZP_TODAY", "2026-10-02")   # 可用 JZP_TODAY 覆盖
TERMINAL = {"已成交", "已退订（对方拒联）", "已放弃", "已退信", "个人处理", "无回应"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
DATE_RE = re.compile(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})")
MONTH = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

# 州/省 → 时区（与 定时发送.py 的 STATE_TZ 同口径）
ST = {}
for c in "CT DE FL GA IN KY ME MD MA MI NH NJ NY NC OH PA RI SC VT VA WV DC".split():
    ST[c] = "ET"
for c in "AL AR IL IA KS LA MN MS MO OK TN TX WI".split():
    ST[c] = "CT"
for c in "CO ID MT NM UT WY".split():
    ST[c] = "MT"
for c in "CA NV OR WA".split():
    ST[c] = "PT"
ST.update({"AK": "AK", "HI": "HI", "AZ": "AZ"})
for c in "ON QC".split():
    ST[c] = "ET"
for c in "NS NB PE NL".split():
    ST[c] = "AT"
for c in "MB SK NT NU".split():
    ST[c] = "CT"
ST["AB"] = "MT"
for c in "BC YT".split():
    ST[c] = "PT"
TZ_CN = {"ET": "美东", "CT": "美中", "MT": "美山", "PT": "美西", "AK": "阿拉斯加",
         "AT": "大西洋", "AZ": "亚利桑那"}


def to_iso(s):
    m = DATE_RE.search(s or "")
    return f"{int(m.group(3)):04d}-{MONTH[m.group(2)]:02d}-{int(m.group(1)):02d}" if m else None


# 中文州/省名 → 时区（表格的「国家/地区」列写的是中文名，不是 2 字母码）
CN_TZ = [
    ("密西西比", "CT"), ("阿拉巴马", "CT"), ("田纳西", "CT"), ("明尼苏达", "CT"),
    ("密苏里", "CT"), ("得克萨斯", "CT"), ("德州", "CT"), ("俄亥俄州", "ET"), ("印第安纳", "ET"),
    ("密歇根", "ET"), ("俄亥俄", "ET"), ("佐治亚", "ET"), ("西弗吉尼亚", "ET"),
    ("马里兰", "ET"), ("新泽西", "ET"), ("宾夕法尼亚", "ET"), ("宾州", "ET"), ("纽约", "ET"), ("纽约州", "ET"),
    ("伊利诺伊", "CT"), ("爱荷华", "CT"), ("威斯康星", "CT"), ("北达科他", "CT"),
    ("南达科他", "CT"), ("堪萨斯", "CT"), ("俄克拉何马", "CT"), ("路易斯安那", "CT"),
    ("科罗拉多", "MT"), ("犹他", "MT"), ("新墨西哥", "MT"), ("蒙大拿", "MT"),
    ("怀俄明", "MT"), ("爱达荷", "MT"), ("加州", "PT"), ("加利福尼亚", "PT"),
    ("华盛顿州", "PT"), ("俄勒冈", "PT"), ("内华达", "PT"), ("亚利桑那", "AZ"),
    ("阿拉斯加", "AK"), ("夏威夷", "HI"),
    # 加拿大
    ("安大略", "ET"), ("安省", "ET"), ("魁北克", "ET"),
    ("不列颠哥伦比亚", "PT"), ("BC", "PT"),
    ("阿尔伯塔", "MT"), ("阿省", "MT"),
    ("曼尼托巴", "CT"), ("萨斯喀彻温", "CT"),
    ("新斯科舍", "AT"), ("新不伦瑞克", "AT"), ("纽芬兰", "AT"), ("爱德华王子岛", "AT"),
]


def tz_of(region, raw):
    txt = (region or "") + " " + (raw or "")
    m = re.search(r"·\s*([A-Z]{2})\b", txt)
    if m and m.group(1) in ST:
        return ST[m.group(1)]
    for cn, code in CN_TZ:
        if cn in txt:
            return code
    return "?"


def main():
    wb = openpyxl.load_workbook(ROOT / "开发信项目/工作区/开发信跟进表.xlsx")
    rows = []
    for ws in wb.worksheets:
        for r in range(5, ws.max_row + 1):
            n = ws.cell(r, 1).value
            if n is None:
                continue
            nxt = str(ws.cell(r, 15).value or "")
            st = str(ws.cell(r, 13).value or "")
            if nxt != TODAY or st in TERMINAL:
                continue
            raw = str(ws.cell(r, 12).value or "")
            rows.append(dict(num=n, name=str(ws.cell(r, 3).value or ""),
                             region=str(ws.cell(r, 4).value or ""), status=st,
                             cnt=ws.cell(r, 14).value or 0, raw=raw,
                             emails=[e.lower() for e in EMAIL_RE.findall(raw)]))

    spec = importlib.util.spec_from_file_location("mailer", ROOT / "邮箱客户端.py")
    mc = importlib.util.module_from_spec(spec)
    sys.modules["mailer"] = mc
    spec.loader.exec_module(mc)
    m = mc.imap_connect(mc.load_config())
    m.select('"Sent Messages"', readonly=True)
    typ, d = m.search(None, "ALL")
    per_dom = defaultdict(list)
    for num in d[0].split():
        raw = mc.fetch_headers(m, num, "TO CC SUBJECT DATE")
        blob = mc.raw_header(raw, "To") + " " + mc.raw_header(raw, "CC")
        iso, subj = to_iso(mc.raw_header(raw, "Date")), mc.raw_header(raw, "Subject")
        for e in set(x.lower() for x in EMAIL_RE.findall(blob)):
            per_dom[e].append((iso, e, subj))   # 🔴 按**精确地址**索引
    m.logout()

    out = []
    for x in rows:
        seen, hits = set(), []
        for e in x["emails"]:
            for iso, ad, sj in per_dom.get(e, []):      # 🔴 精确地址匹配（按域名会把所有 gmail 都算进来）
                if (ad, sj) in seen:
                    continue
                seen.add((ad, sj))
                hits.append((iso, ad, sj))
        hits = [h for h in hits if h[0]]
        hits.sort()
        last = hits[-1] if hits else (None, None, None)
        base = re.sub(r"^(?:(?:re|fw|fwd)\s*:\s*)+", "", last[2] or "", flags=re.I).strip()
        x["tz"] = tz_of(x["region"], x["raw"])
        # 档位：邮箱列里写「B 档」= 角色邮箱 → 必须点名转交；否则 A 档
        x["tier"] = "B" if re.search(r"\bB\s*档", x["raw"]) else "A"
        x["round"] = ("第 2 次（D0+8）" if int(x["cnt"] or 0) >= 1 else "第 1 次（D0+3）")
        x["last_send"] = last[0]
        x["last_subject"] = last[2]
        x["re_subject"] = ("Re: " + base) if base else ""
        out.append(x)

    out.sort(key=lambda y: y["num"])
    print(f"今日（{TODAY}）需跟进：{len(out)} 家\n")
    print(f"{'#':<6}{'档':<4}{'公司':<32}{'时区':<8}{'轮次':<15}{'邮箱':<40}实测最近主题")
    for x in out:
        print(f"{x['num']:<6}{x['tier']:<4}{x['name'][:30]:<32}{TZ_CN.get(x['tz'],x['tz']):<8}"
              f"{x['round']:<15}{(x['emails'][0] if x['emails'] else '—'):<40}"
              f"{(x['last_subject'] or '')[:44]}")
    from collections import Counter
    print()
    print('  档位分布:', dict(Counter(y['tier'] for y in out)))
    print('  时区分布:', dict(Counter(y['tz'] for y in out)))
    print('  轮次分布:', dict(Counter(y['round'] for y in out)))
    (ROOT / f".workbuddy-ai/今日工作单-{TODAY}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写 .workbuddy-ai/今日工作单.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
