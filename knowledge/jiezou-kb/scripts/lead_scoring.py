#!/usr/bin/env python3
"""线索打分：把海关数据 + 知识库既有条目 + 手工整理的渠道数据，交叉比对成排好序的线索。

设计要点
1. **只做发现与筛选**。不做群发、不做自动加好友——联系和跟进仍然人工。
2. **规则化、可审计**。每条线索的每个加减分都写进 leads.csv 和条目的「评分明细」，
   任何一个分数都能追溯到具体信号和具体来源。
3. **诚实**。免费数据源（加拿大 CID、广交会名录）拿不到票数/金额/日期，
   这些信号算不出来就不算，并在 coverage（数据完整度）里如实反映——
   避免把「完整度 30% 的 35 分」误读成和「完整度 90% 的 170 分」同一口径。
4. **幂等**。按公司名归一化键匹配已有客户条目，命中就外科手术式更新，
   未命中才新建；永不删除、永不重复。

用法：
    python3 scripts/lead_scoring.py --latest --dry-run
    python3 scripts/lead_scoring.py --input data/normalized/xxx.csv --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import build_index
import customs_normalize as cn
import kblib

NORM_DIR = kblib.ROOT / "data" / "normalized"
LEADS_DIR = kblib.ROOT / "leads"

# 打分权重表：编号 → (分值, 说明)。改这里就能调权重，不用动逻辑。
WEIGHTS = {
    1: (25, "美加主攻市场"),
    2: (8, "次级美洲市场"),
    3: (-15, "非目标市场"),
    4: (30, "亚威买家（竞对已证明需求）"),
    5: (15, "其他中国竞对买家"),
    6: (35, "流失老客户（买过我们、后来走了）"),
    7: (20, "活跃老客户"),
    8: (18, "首次采购/新买家"),
    9: (15, "供应商更替频繁"),
    10: (15, "采购频次高"),
    11: (7, "采购频次中"),
    12: (10, "采购规模大"),
    13: (12, "近期活跃"),
    14: (-10, "沉睡买家"),
    15: (20, "产品强匹配（液浸变压器）"),
    16: (12, "产品匹配（其他变压器）"),
    17: (3, "仅配件"),
    18: (-20, "品类不符"),
    19: (-12, "纯贸易中间商"),
    20: (8, "终端买家/工程商"),
    21: (5, "已在知识库"),
    23: (10, "有可联系入口"),
    24: (-5, "无联系方式"),
}
TOTAL_SIGNALS = 24  # 22 号信号不计分（只是标签），用于 coverage 分母


def _today():
    return date.today()


def _parse_date(s):
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- 知识库集合

def load_kb_sets(aliases):
    """从知识库读取已有的客户/自有成交/合作伙伴条目，建立比对键索引。"""
    customers, owned, partners = {}, {}, {}
    for r in kblib.load_index():
        key = cn.company_key(r.get("name", ""), aliases)
        if not key:
            continue
        text = (kblib.ROOT / r["path"]).read_text(encoding="utf-8")
        status = kblib.get_frontmatter_field(text, "跟进状态")
        item = {"id": r["id"], "path": r["path"], "name": r["name"],
                "status": status, "tags": list(r.get("tags") or [])}
        if r["type"] == "客户":
            customers[key] = item
        elif r["type"] == "自有成交记录":
            owned[key] = item
        elif r["type"] == "合作伙伴":
            partners[key] = item
    return customers, owned, partners


# 客户条目上表示「曾经向我方采购过」的标签。
# 打「流失老客户」信号时，除了查「自有成交记录」，也认这几个标签——
# 有些老客户（如 Soltech）是从别的调研路径发现的，只记在客户条目里。
PRIOR_PURCHASE_TAGS = {"杰走前客户", "Jiezou老客户", "流失老客户"}


def has_prior_purchase(key, customers, owned):
    if key in owned:
        return True
    return bool(PRIOR_PURCHASE_TAGS & set(customers.get(key, {}).get("tags", [])))


# ---------------------------------------------------------------- 聚合

def aggregate(records, aliases, watchlist):
    """把逐条记录聚合成「一家公司一个画像」。"""
    profiles = {}
    for rec in records:
        # 公司名比对键**每次打分时重算**，不信任 CSV 里缓存的值——
        # 别名表是随时可以补的，补完之后旧数据的归一化结果必须跟着更新，
        # 否则新加的别名对这批发好的数据不生效。
        k = cn.company_key(rec.get("buyer_name", ""), aliases)
        c2 = rec.get("buyer_country2") or cn.country2_of(
            rec.get("buyer_country"), rec.get("buyer_address"), rec.get("buyer_region"))
        key = f"{k}@{c2 or '??'}" if k else (rec.get("buyer_key") or "")
        rec["buyer_key"] = key
        if not key:
            continue
        if not rec.get("hs_code6") and rec.get("hs_code"):
            rec["hs_code6"] = cn.hs6(rec["hs_code"])
        p = profiles.setdefault(key, {
            "buyer_key": key,
            "names": [], "countries": set(), "regions": set(), "cities": set(),
            "address": "", "hs6": set(), "hs_codes": set(), "product_descs": [],
            "suppliers": {}, "shipment_count": 0, "quantity_kg": 0.0, "value_usd": 0.0,
            "dates": [], "self_dates": [], "competitor_dates": [],
            "emails": set(), "phones": set(), "contacts": set(),
            "sources": set(), "source_refs": [], "records": [],
        })
        if rec.get("buyer_name"):
            p["names"].append(rec["buyer_name"])
        for field, bucket in (("buyer_country2", "countries"), ("buyer_region", "regions"),
                              ("buyer_city", "cities")):
            if rec.get(field):
                bucket_add = p[bucket]
                bucket_add.add(rec[field])
        if not p["address"] and rec.get("buyer_address"):
            p["address"] = rec["buyer_address"]
        if rec.get("hs_code6"):
            p["hs6"].add(rec["hs_code6"])
        if rec.get("hs_code"):
            p["hs_codes"].add(str(rec["hs_code"]))
        if rec.get("product_desc"):
            p["product_descs"].append(str(rec["product_desc"]))
        sup = rec.get("supplier_name")
        if sup:
            skey = rec.get("supplier_name_norm") or cn.normalize_company(sup)
            p["suppliers"][skey] = p["suppliers"].get(skey, 0) + 1
        p["shipment_count"] += int(rec.get("shipment_count") or 0)
        p["quantity_kg"] += float(rec.get("quantity_kg") or 0)
        p["value_usd"] += float(rec.get("value_usd") or 0)
        for f in ("first_shipment_date", "last_shipment_date"):
            if rec.get(f):
                p["dates"].append(str(rec[f]))
        role = rec.get("supplier_role")
        last = rec.get("last_shipment_date")
        if role == "self" and last:
            p["self_dates"].append(str(last))
        if role == "competitor" and last:
            p["competitor_dates"].append(str(last))
        if rec.get("contact_email"):
            p["emails"].add(str(rec["contact_email"]))
        if rec.get("contact_phone"):
            p["phones"].add(str(rec["contact_phone"]))
        if rec.get("contact_name"):
            p["contacts"].add(str(rec["contact_name"]))
        if rec.get("source"):
            p["sources"].add(str(rec["source"]))
        if rec.get("source_ref"):
            p["source_refs"].append(str(rec["source_ref"]))
        p["records"].append(rec)

    # 收尾派生量
    for p in profiles.values():
        names = sorted(set(p["names"]), key=len, reverse=True)
        p["display_name"] = names[0] if names else ""
        p["country2"] = next(iter(p["countries"]), "")
        p["region"] = next(iter(p["regions"]), "")
        p["city"] = next(iter(p["cities"]), "")
        p["distinct_suppliers"] = len(p["suppliers"])
        top = max(p["suppliers"].values()) if p["suppliers"] else 0
        p["top_supplier_share"] = round(top / p["shipment_count"], 3) if p["shipment_count"] else 0.0
        dates = sorted(d for d in p["dates"] if d)
        p["first_date"] = dates[0] if dates else ""
        p["last_date"] = dates[-1] if dates else ""
        p["last_self"] = max(p["self_dates"]) if p["self_dates"] else ""
        p["last_any"] = p["last_date"]
        roles = set()
        for rec in p["records"]:
            if rec.get("supplier_role"):
                roles.add(rec["supplier_role"])
        p["roles"] = roles
        p["has_self"] = "self" in roles
        p["has_competitor"] = "competitor" in roles
        p["has_yawei"] = any("YAWEI" in s for s in p["suppliers"])
    return profiles


# ---------------------------------------------------------------- 打分

def score_profile(p, kb, aliases, thresholds):
    customers, owned, partners = kb
    bd, tags = [], set()
    score = 0
    evaluable = 0
    today = _today()
    key = p["buyer_key"].split("@")[0]

    def add(num, delta, reason, evaluable_flag=True):
        nonlocal score, evaluable
        bd.append((num, delta, reason))
        score += delta
        if evaluable_flag:
            evaluable += 1

    def skip(num, reason):
        bd.append((num, 0, f"（数据不足，未计分：{reason}）"))

    # 1/2/3 市场
    c2 = p["country2"]
    if c2 in cn.TARGET_MARKETS:
        add(1, WEIGHTS[1][0], f"美加主攻市场（{c2}）")
        tags.add("北美主攻")
    elif c2 in cn.SECONDARY_MARKETS:
        add(2, WEIGHTS[2][0], f"次级美洲市场（{c2}）")
    elif c2:
        add(3, WEIGHTS[3][0], f"非目标市场（{c2}）")
        tags.add("非目标市场")
    else:
        add(3, WEIGHTS[3][0], "国别未识别，按非目标市场处理")
        tags.add("国别未知")

    # 4/5 竞对买家
    if p["has_yawei"]:
        add(4, WEIGHTS[4][0], "亚威买家（竞对已证明该客户有真实重复需求）")
        tags.add("竞争对买家")
    elif p["has_competitor"]:
        add(5, WEIGHTS[5][0], "其他中国竞对买家（已接受中国制造，切换成本低）")
        tags.add("竞争对买家")
    elif p["suppliers"]:
        add(5, 0, "供应商非已知竞对", evaluable_flag=True)
    else:
        skip(4, "来源不含供应商信息")

    # 6/7 自有老客户
    if p["has_self"]:
        if p["last_self"] and p["last_any"] and p["last_self"] < p["last_any"]:
            add(6, WEIGHTS[6][0], f"流失老客户：我方最后成交 {p['last_self']}，之后仍有采购")
            tags.add("流失老客户")
        else:
            add(7, WEIGHTS[7][0], "活跃老客户")
            tags.add("Jiezou老客户")
    elif has_prior_purchase(key, customers, owned) and p["has_competitor"]:
        # 提单数据里只看到竞对供货、看不到我方——但知识库已经确认这家从我方买过
        # （在「自有成交记录」里，或客户条目打了「杰走前客户」等标签）。
        # 两者合起来同样是「被撬走」，而且这是更常见的情形：
        # 自己那份成交史 + 一份竞对提单就够了。
        src = owned[key]["id"] if key in owned else f"{customers[key]['id']} 的标签"
        add(6, WEIGHTS[6][0],
            f"流失老客户：知识库（{src}）确认曾向我方采购，而当前提单显示供应商为竞对")
        tags.add("流失老客户")
    else:
        skip(6, "来源不含我方成交对照")

    # 8 首次采购
    if p["first_date"]:
        fd = _parse_date(p["first_date"])
        if fd and fd >= today - timedelta(days=365) and p["shipment_count"] <= 3:
            add(8, WEIGHTS[8][0], f"首次采购/新买家（首票 {p['first_date']}）")
            tags.add("新买家")
        else:
            add(8, 0, "非首次采购")
    else:
        skip(8, "来源不含采购日期")

    # 9 供应商更替
    if p["suppliers"]:
        if p["distinct_suppliers"] >= 3 and p["top_supplier_share"] < 0.6:
            add(9, WEIGHTS[9][0], f"供应商更替频繁（{p['distinct_suppliers']} 家，最大占比 {p['top_supplier_share']:.0%}）")
            tags.add("供应商不稳")
        else:
            add(9, 0, "供应商集中")
    else:
        skip(9, "来源不含供应商信息")

    # 10/11 频次
    if p["shipment_count"] > 0:
        if p["shipment_count"] >= 6:
            add(10, WEIGHTS[10][0], f"采购频次高（{p['shipment_count']} 票）")
            tags.add("高频采购")
        elif p["shipment_count"] >= 2:
            add(11, WEIGHTS[11][0], f"采购频次中（{p['shipment_count']} 票）")
        else:
            add(11, 0, "仅 1 票")
    else:
        skip(10, "来源不含票数")

    # 12 规模
    if p["quantity_kg"] > 0:
        if p["quantity_kg"] >= 100000:
            add(12, WEIGHTS[12][0], f"采购规模大（{p['quantity_kg']:,.0f} kg）")
            tags.add("大额")
        else:
            add(12, 0, "规模一般")
    else:
        skip(12, "来源不含重量")

    # 13/14 活跃度
    if p["last_date"]:
        ld = _parse_date(p["last_date"])
        if ld and ld >= today - timedelta(days=365):
            add(13, WEIGHTS[13][0], f"近期活跃（最后 {p['last_date']}）")
            tags.add("近期活跃")
        elif ld and ld < today - timedelta(days=730):
            add(14, WEIGHTS[14][0], f"沉睡买家（最后 {p['last_date']}）")
            tags.add("沉睡")
        else:
            add(13, 0, "活跃度一般")
    else:
        skip(13, "来源不含采购日期")

    # 15/16/17/18 产品匹配
    hs6s = p["hs6"]
    if hs6s:
        if hs6s & cn.HS_STRONG:
            add(15, WEIGHTS[15][0], f"液浸变压器强匹配（{'/'.join(sorted(hs6s & cn.HS_STRONG))}）")
            tags.add("产品强匹配")
        elif hs6s & cn.HS_OTHER_XFMR:
            add(16, WEIGHTS[16][0], f"其他变压器匹配（{'/'.join(sorted(hs6s & cn.HS_OTHER_XFMR))}）")
        elif hs6s & cn.HS_PARTS:
            add(17, WEIGHTS[17][0], "仅配件（850490）")
        else:
            add(18, WEIGHTS[18][0], f"品类不符（{','.join(sorted(hs6s))}）")
            tags.add("品类不符")
    elif any(cn.is_transformer_hs(h) for h in p["hs_codes"]):
        add(15, WEIGHTS[15][0], "变压器相关（HS4 8504）")
    else:
        # 广交会名录这类来源没有 HS 码，只有「采购产品类别」文字。
        # 这里用**公司名 + 品类文字**一起判断行业相关性，否则两千条线索会全部同分。
        name_up = p["display_name"].upper()
        blob = " ".join(p["product_descs"]).upper()
        strong_in_name = [k for k in cn.STRONG_INDUSTRY_KEYWORDS if k in name_up]
        strong_in_desc = [k for k in cn.STRONG_INDUSTRY_KEYWORDS if k in blob]
        if strong_in_name or strong_in_desc:
            where = "名称" if strong_in_name else "品类"
            hit = (strong_in_name or strong_in_desc)[0]
            add(16, WEIGHTS[16][0], f"行业相关（{where}含「{hit}」）")
            tags.add("行业相关")
        else:
            skip(15, "来源不含 HS 码，且名称/品类未见行业词")

    # 19/20 贸易商 vs 终端
    is_trader, evidence = cn.looks_like_trader(p["display_name"], p["emails"],
                                               " ".join(p["product_descs"]))
    if is_trader:
        add(19, WEIGHTS[19][0], f"疑似纯贸易中间商（{'；'.join(evidence)}）")
        tags.add("疑似中间商")
    else:
        add(19, 0, "未见明显中间商特征")
    name_up = p["display_name"].upper()
    if any(k in name_up for k in cn.STRONG_INDUSTRY_KEYWORDS):
        add(20, WEIGHTS[20][0], "终端买家/工程商特征")
        tags.add("终端买家")
    else:
        add(20, 0, "行业属性不明")

    # 21 已在知识库
    kb_entry_id = ""
    if key in customers:
        item = customers[key]
        kb_entry_id = item["id"]
        if item["status"] in ("搁置", "已成交"):
            bd.append((21, 0, f"（已在知识库 {item['id']}，状态「{item['status']}」，不加分）"))
            evaluable += 1
            tags.add(f"KB-{item['status']}")
        else:
            add(21, WEIGHTS[21][0], f"已在知识库（{item['id']}）")
            tags.add("已在库")
    elif key in partners:
        add(21, WEIGHTS[21][0], f"已在知识库（合作伙伴 {partners[key]['id']}）")
        tags.add("已在库")
        kb_entry_id = partners[key]["id"]
    elif key in owned:
        # 只在自有成交记录里出现过（还没建客户条目），不算「已在库」
        bd.append((21, 0, f"（仅见于自有成交记录 {owned[key]['id']}，尚未建客户条目）"))
        evaluable += 1

    # 22 命中自有成交记录（标签，不计分）
    if key in owned:
        tags.add("Jiezou老客户")
        bd.append((22, 0, f"命中自有成交记录（{owned[key]['id']}）"))
        kb_entry_id = kb_entry_id or owned[key]["id"]

    # 知名 OEM/同业：只打标签不扣分——卖给他们（OEM 代工）是可能的，
    # 但性质与「终端买家」不同，需要你自己判断，所以不替你加减分。
    oem_hits = cn.is_known_oem(p["display_name"])
    if oem_hits:
        tags.add("知名OEM同业")
        bd.append((22, 0, f"知名变压器 OEM/同业（{'、'.join(oem_hits)}）——非终端买家，需单独判断"))

    # 23/24 联系方式
    if p["emails"] or p["phones"]:
        add(23, WEIGHTS[23][0], f"有可联系入口（{sorted(p['emails'] or p['phones'])[0]}）")
        tags.add("有联系人")
    elif p["sources"] & {"canada_cid"}:
        skip(23, "官方 CID 数据不含联系方式")
    else:
        add(24, WEIGHTS[24][0], "无联系方式，需先挖掘")
        tags.add("缺联系方式")

    coverage = round(evaluable / TOTAL_SIGNALS * 100)
    tier = "A" if score >= thresholds["a"] else \
           "B" if score >= thresholds["b"] else \
           "C" if score >= thresholds["c"] else "D"
    return score, tier, coverage, bd, sorted(tags), kb_entry_id


# ---------------------------------------------------------------- 输入

def read_normalized(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("raw"):
                try:
                    row["raw"] = json.loads(row["raw"])
                except ValueError:
                    row["raw"] = {}
            for f_ in ("shipment_count", "distinct_suppliers"):
                row[f_] = int(float(row.get(f_) or 0))
            for f_ in ("quantity_kg", "value_usd", "top_supplier_share"):
                row[f_] = float(row.get(f_) or 0)
            yield row


def latest_normalized():
    if not NORM_DIR.exists():
        return None
    files = sorted(NORM_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


# ---------------------------------------------------------------- 条目生成

def build_entry_text(p, score, tier, coverage, bd, tags, kb_entry_id, entry_id, today):
    c2 = p["country2"]
    products = " / ".join(dict.fromkeys(p["product_descs"]))[:300] or "（海关数据未含产品描述）"

    fm = {
        "id": entry_id,
        "type": "客户",
        "name": p["display_name"],
        "created": today,
        "updated": today,
        "tags": sorted(set(tags) | {"海关线索", "北美主攻" if c2 in cn.TARGET_MARKETS else "非目标"}),
        "related": [],
        "source": f"海关数据评分 {today}（来源：{'、'.join(sorted(p['sources']))}；明细见 leads/leads.csv）",
        "所在行业": "电力/变压器相关（据海关数据推断）",
        "采购品类": products,
        "历史订单": f"共 {p['shipment_count']} 票" + (
            f"，{p['quantity_kg']:,.0f} kg" if p["quantity_kg"] else "") +
            (f"，最后 {p['last_date']}" if p["last_date"] else ""),
        "跟进状态": "新线索",
        "联系人": (sorted(p["contacts"])[0] if p["contacts"] else
                 (sorted(p["emails"])[0] if p["emails"] else "待补充")),
    }

    sections = build_sections(p, score, tier, coverage, bd, tags)
    parts = [f"## {name}\n\n{body}".rstrip() for name, body in sections.items()]
    parts.append(f"## 跟进记录\n\n- {today}：海关数据评分 {score}"
                 f"（{tier} 级，完整度 {coverage}%），来源 {'、'.join(sorted(p['sources']))}。")
    return kblib.dump_frontmatter(fm, "\n\n".join(parts) + "\n")


def build_sections(p, score, tier, coverage, bd, tags):
    """生成条目正文里的「生成型」小节，返回 {小节名: 正文}。

    新建与更新都走这里——否则更新时只改 frontmatter 和「跟进记录」，
    正文里的「评分明细」会一直停在旧分数上，审计链就断了。
    """
    c2 = p["country2"]
    country_label = {"US": "美国", "CA": "加拿大"}.get(c2, c2 or "未识别")
    area = " ".join(x for x in [country_label, cn.REGION_LABEL.get(p["region"], p["region"])] if x)
    hs_list = "/".join(sorted(p["hs6"])) if p["hs6"] else "未识别"
    products = " / ".join(dict.fromkeys(p["product_descs"]))[:300] or "（海关数据未含产品描述）"
    out = {}

    L = [f"- 国别/地区：{area or '未识别'}",
         f"- HS 编码：{hs_list}",
         f"- 采购品类（原文）：{products}"]
    if p["address"]:
        L.append(f"- 地址：{p['address']}")
    out["需求与偏好"] = "\n".join(L)

    L = ["| 来源 | 票数 | 重量(kg) | 金额(USD) | 首票 | 末票 | 供应商 | 信息来源 |",
         "|---|---|---|---|---|---|---|---|"]
    for rec in p["records"][:20]:
        L.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            rec.get("source", ""), rec.get("shipment_count") or "-",
            f"{float(rec.get('quantity_kg') or 0):,.0f}" if rec.get("quantity_kg") else "-",
            f"{float(rec.get('value_usd') or 0):,.0f}" if rec.get("value_usd") else "-",
            rec.get("first_shipment_date") or "-", rec.get("last_shipment_date") or "-",
            rec.get("supplier_name") or "-", rec.get("source_ref") or "-"))
    if len(p["records"]) > 20:
        L += ["", f"（共 {len(p['records'])} 条记录，此处仅列前 20 条，完整明细见 leads/leads.csv）"]
    out["海关数据"] = "\n".join(L)

    L = ["<!-- 规范：联系人信息必须注明来源（见 README「信息源规范」） -->", "",
         "| 姓名/主体 | 职务/联系方式 | 信息来源 |", "|---|---|---|"]
    rows = 0
    for c in sorted(p["contacts"]):
        L.append(f"| {c} | — | 海关数据记录（{p['source_refs'][0] if p['source_refs'] else '见 leads.csv'}） |")
        rows += 1
    for e in sorted(p["emails"]):
        L.append(f"| 邮箱 | {e} | 来源：见 leads/leads.csv 对应行 |")
        rows += 1
    for ph in sorted(p["phones"]):
        L.append(f"| 电话 | {ph} | 来源：见 leads/leads.csv 对应行 |")
        rows += 1
    if not rows:
        L.append("| 待补充 | — | 来源：未证实（海关数据无联系人字段） |")
    out["联系人"] = "\n".join(L)

    L = []
    if p["shipment_count"]:
        L.append(f"- 票数：{p['shipment_count']}；供应商家数：{p['distinct_suppliers']}；"
                 f"最大供应商占比：{p['top_supplier_share']:.0%}")
    if p["first_date"] or p["last_date"]:
        L.append(f"- 采购区间：{p['first_date'] or '?'} ~ {p['last_date'] or '?'}")
    if p["has_self"]:
        L.append(f"- 我方最后成交：{p['last_self'] or '未知'}"
                 + ("（此后仍有采购，疑似转走）"
                    if p["last_self"] and p["last_self"] < (p["last_any"] or "") else ""))
    if not p["shipment_count"] and not p["first_date"]:
        L.append("- 来源未提供票数/日期，暂无法刻画采购节奏。")
    out["采购习惯"] = "\n".join(L) or "- 待补充"

    L = [f"**总分 {score}（{tier} 级）· 数据完整度 {coverage}%**", "",
         "| # | 分值 | 信号 |", "|---|---|---|"]
    for num, delta, reason in bd:
        L.append(f"| {num} | {delta:+d} | {reason} |")
    if coverage < 40:
        L += ["", "> ⚠ 数据完整度低于 40%，本分数**不可与提单口径的分数直接比较**——"
                  "免费来源缺少票数、金额、日期、供应商等信息。"]
    out["评分明细"] = "\n".join(L)
    return out


# ---------------------------------------------------------------- 输出

def write_leads_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    signal_cols = [f"s{n}" for n in sorted(WEIGHTS)]
    header = (["rank", "buyer_key", "buyer_name", "country", "region", "score", "tier",
               "coverage"] + signal_cols +
              ["tags", "matched_suppliers", "contact_email", "contact_phone",
               "kb_entry_id", "sources", "source_refs"])
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for i, r in enumerate(rows, 1):
            deltas = {n: d for n, d, _ in r["breakdown"]}
            w.writerow([i, r["profile"]["buyer_key"], r["profile"]["display_name"],
                        r["profile"]["country2"], r["profile"]["region"], r["score"], r["tier"],
                        r["coverage"]] +
                       [deltas.get(n, "") for n in sorted(WEIGHTS)] +
                       ["|".join(r["tags"]),
                        "|".join(sorted(r["profile"]["suppliers"])),
                        "|".join(sorted(r["profile"]["emails"])),
                        "|".join(sorted(r["profile"]["phones"])),
                        r["kb_entry_id"],
                        "|".join(sorted(r["profile"]["sources"])),
                        "|".join(r["profile"]["source_refs"][:5])])


def write_leads_index(rows, path, inputs, thresholds):
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = defaultdict(int)
    for r in rows:
        counts[r["tier"]] += 1
    L = [
        "# 线索总表",
        "",
        "> 本文件由 `scripts/lead_scoring.py` 生成，请勿手改。",
        f"> 生成日期：{date.today().isoformat()} · 候选 {len(rows)} 条 · "
        f"A {counts['A']} / B {counts['B']} / C {counts['C']} / D {counts['D']}",
        f"> 输入：{', '.join(str(i) for i in inputs)}",
        "> 完整列表（含全部打分明细）：`leads/leads.csv`",
        f"> 分级阈值：A≥{thresholds['a']} / B≥{thresholds['b']} / C≥{thresholds['c']}",
        "",
    ]

    def table(subset, title, limit=0):
        items = subset[:limit] if limit else subset
        if not items:
            return
        L.append(f"## {title}（{len(subset)}）")
        L.append("")
        L.append("| 排名 | 公司 | 国家/地区 | 分数 | 完整度 | 关键信号 | 联系方式 | KB | 来源 |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(items, 1):
            p = r["profile"]
            key_signals = [reason for num, d, reason in r["breakdown"]
                           if d > 0 and not reason.startswith("（")][:3]
            contact = (sorted(p["emails"])[0] if p["emails"] else
                       (sorted(p["phones"])[0] if p["phones"] else "—"))
            L.append("| {} | {} | {} {} | **{}** | {}% | {} | {} | {} | {} |".format(
                i, p["display_name"], p["country2"], cn.REGION_LABEL.get(p["region"], p["region"]),
                r["score"], r["coverage"], "；".join(key_signals)[:70],
                contact, r["kb_entry_id"] or "—", "、".join(sorted(p["sources"]))))
        L.append("")

    table([r for r in rows if r["tier"] == "A"], "A 级 · 立即跟进")
    table([r for r in rows if r["tier"] == "B"], "B 级 · 优先跟进")
    table([r for r in rows if r["tier"] == "C"], "观察池（C 级）", limit=30)
    table([r for r in rows if r["tier"] == "D"], "暂不跟进（D 级）", limit=10)

    lost = [r for r in rows if "流失老客户" in r["tags"]]
    if lost:
        L.append(f"## 流失客户专报（我方成交过 → 现由他人供货）（{len(lost)}）")
        L.append("")
        L.append("| 公司 | 我方最后成交 | 现供应商 | 差距 | 分数 |")
        L.append("|---|---|---|---|---|")
        for r in lost:
            p = r["profile"]
            L.append("| {} | {} | {} | {} | {} |".format(
                p["display_name"], p["last_self"] or "?", "、".join(sorted(p["suppliers"]))[:40],
                f"{p['last_self']} → {p['last_any']}" if p["last_any"] else "?", r["score"]))
        L.append("")

    low_cov = [r for r in rows if r["coverage"] < 40]
    if low_cov:
        L.append("## 关于数据完整度")
        L.append("")
        L.append(f"- 本次 {len(low_cov)}/{len(rows)} 条线索的数据完整度低于 40%，"
                 "其分数主要由市场匹配、产品匹配、竞对信号构成，**不可与提单口径的分数直接比较**。")
        L.append("- 补齐票数/金额/日期/供应商的最快途径：导出一份美国提单数据"
                 "（ImportYeti / ImportGenius / Trademo），再用 "
                 "`--adapter local_csv --profile importyeti` 导入。")
        L.append("")

    path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="海关数据线索打分")
    ap.add_argument("--input", action="append", default=[], help="归一化 CSV（可重复）")
    ap.add_argument("--latest", action="store_true", help="自动取 data/normalized/ 里最新的一份")
    ap.add_argument("--manual", action="append", default=[], help="手工整理的 CSV（可重复）")
    ap.add_argument("--top", type=int, default=50, help="leads/index.md 里 C 级展示多少条")
    ap.add_argument("--emit-entries", default="A,B", help="为哪些级别生成客户条目，如 A,B / none")
    ap.add_argument("--tier-a", type=int, default=80)
    ap.add_argument("--tier-b", type=int, default=50)
    ap.add_argument("--tier-c", type=int, default=25)
    ap.add_argument("--min-coverage", type=int, default=0, help="过滤掉完整度低于此值的线索")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="只打印结果（默认）")
    g.add_argument("--apply", action="store_true", help="写入 leads/ 并为 A/B 级生成客户条目")
    args = ap.parse_args()

    inputs = list(args.input)
    if args.latest or not inputs:
        latest = latest_normalized()
        if latest is None:
            sys.exit("找不到归一化数据。先跑：python3 scripts/customs_data_fetch.py --adapter local_csv --file <文件> --profile <预设>")
        inputs = [str(latest)]
    for m in args.manual:
        inputs.append(m)

    thresholds = {"a": args.tier_a, "b": args.tier_b, "c": args.tier_c}
    aliases = cn.load_aliases()
    watchlist = cn.load_watchlist()

    records = []
    for path in inputs:
        p = Path(path)
        if not p.exists():
            sys.exit(f"[错误] 找不到输入文件：{p}")
        records += list(read_normalized(p))
    if not records:
        sys.exit("[错误] 输入文件里没有记录")

    profiles = aggregate(records, aliases, watchlist)
    kb = load_kb_sets(aliases)

    rows = []
    for p in profiles.values():
        score, tier, coverage, bd, tags, kb_id = score_profile(p, kb, aliases, thresholds)
        if coverage < args.min_coverage:
            continue
        rows.append({"profile": p, "score": score, "tier": tier, "coverage": coverage,
                     "breakdown": bd, "tags": tags, "kb_entry_id": kb_id})
    rows.sort(key=lambda r: (-r["score"], r["profile"]["display_name"]))

    counts = defaultdict(int)
    for r in rows:
        counts[r["tier"]] += 1
    print(f"候选 {len(rows)} 条：A {counts['A']} / B {counts['B']} / C {counts['C']} / D {counts['D']}")
    print()
    for i, r in enumerate(rows[:25], 1):
        p = r["profile"]
        print(f"  {i:3}. [{r['tier']}] {r['score']:4}  {r['coverage']:3}%  "
              f"{p['display_name'][:38]:38} {p['country2']:3} {'、'.join(r['tags'])[:50]}")

    if not args.apply:
        print("\n（--dry-run）确认无误后加 --apply 执行。")
        return 0

    write_leads_csv(rows, LEADS_DIR / "leads.csv")
    write_leads_index(rows, LEADS_DIR / "index.md", inputs, thresholds)
    print(f"\n已写入 leads/leads.csv、leads/index.md")

    emit = {t.strip().upper() for t in args.emit_entries.split(",") if t.strip()}
    if emit and "NONE" not in emit:
        today = date.today().isoformat()
        index_records = kblib.load_index()
        created = updated = 0
        for r in rows:
            if r["tier"] not in emit:
                continue
            p = r["profile"]
            key = p["buyer_key"].split("@")[0]
            existing = kb[0].get(key)
            # 一家公司只保留一个实体：已作为合作伙伴/自有成交记录存在的，不另建客户条目，
            # 否则同一家公司会出现两个文件，后续检索和更新都会打架。
            other = kb[2].get(key) or kb[1].get(key)
            if other and not existing:
                print(f"  SKIP   {p['display_name']}  （已在知识库：{other['id']} {other['path'].split('/')[1]}，不重复建客户条目）")
                continue
            if existing:
                target = kblib.ROOT / existing["path"]
                cur = target.read_text(encoding="utf-8")
                cur = kblib.upsert_frontmatter_fields(cur, {
                    "updated": today,
                    "历史订单": (f"共 {p['shipment_count']} 票" if p["shipment_count"] else "见正文"),
                })
                # 刷新生成型小节，保证正文里的「评分明细」与最新一次打分一致
                for name, body in build_sections(p, r["score"], r["tier"], r["coverage"],
                                                 r["breakdown"], r["tags"]).items():
                    cur = kblib.replace_section(cur, name, body)
                # 只在状态为空或仍是「新线索」时才改写，绝不覆盖人工推进过的状态
                st = kblib.get_frontmatter_field(cur, "跟进状态")
                if st in ("", "新线索"):
                    cur = kblib.set_frontmatter_field(cur, "跟进状态", "新线索")
                # 同一天重复打分不重复记账，否则 跟进记录 会被重跑刷屏
                stamp = f"- {today}：海关数据评分 {r['score']}（{r['tier']} 级，完整度 {r['coverage']}%）。"
                if stamp not in cur:
                    cur = kblib.append_under_heading(cur, "跟进记录", stamp)
                target.write_text(cur, encoding="utf-8")
                updated += 1
                print(f"  UPDATE {existing['id']}  {p['display_name']}")
            else:
                entry_id = kblib.next_id(index_records, "kh")
                index_records.append({"id": entry_id, "type": "客户", "name": p["display_name"],
                                      "tags": [], "updated": today, "path": ""})
                name = kblib.safe_filename(p["display_name"])[:80]
                target = kblib.ENTRIES_DIR / "客户" / f"{name}.md"
                if target.exists():
                    target = kblib.ENTRIES_DIR / "客户" / f"{name}-{entry_id}.md"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    build_entry_text(p, r["score"], r["tier"], r["coverage"], r["breakdown"],
                                     r["tags"], r["kb_entry_id"], entry_id, today),
                    encoding="utf-8")
                created += 1
                print(f"  CREATE {entry_id}  {p['display_name']}")
        print(f"\n客户条目：新增 {created}，更新 {updated}")
        build_index.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
