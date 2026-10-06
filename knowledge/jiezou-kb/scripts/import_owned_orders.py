#!/usr/bin/env python3
"""把自有成交记录（公司成单客户 那种块格式）导入为 entries/自有成交记录/ 条目。

为什么要单独建一个实体类型而不是塞进「客户」：
  历史成交 ≠ 目标客户画像。混进「客户」会污染 `跟进状态` 语义，
  而且 17 条历史记录会把 19 条真实线索淹掉。
  单独成类型后，lead_scoring.py 可以稳定地拿它当「我方历史买家」键集，
  用来判断某家公司是不是「买过我们、后来走了」——那是最有价值的线索原型。

用法：
    python3 scripts/import_owned_orders.py --source "/Users/eric/Downloads/公司成单客户"
    python3 scripts/import_owned_orders.py --source <文件> --apply
"""
import argparse
import re
import sys
from datetime import date
from pathlib import Path

import build_index
import customs_adapters
import customs_normalize as cn
import kblib

DEFAULT_SOURCE = "/Users/eric/Downloads/公司成单客户"

# 容量/型号关键词，用于自动打标签
CAPACITY_RE = r"(\d+(?:\.\d+)?)\s*(MVA|KVA|kVA|mva|kva)"
TYPE_KEYWORDS = {
    "BESS": "储能", "ENERGY STORAGE": "储能", "DRY TYPE": "干变", "DRY-TYPE": "干变",
    "PAD MOUNT": "美变", "PAD-MOUNT": "美变", "PAD MOUNTED": "美变",
    "SUBSTATION": "箱变/变电站", "POLE": "单相柱上", "POWER TRANSFORMER": "主变",
    "OIL FILLED": "油变",
}
COUNTRY_LABEL = {"US": "美国", "CA": "加拿大", "AI": "安圭拉"}


def build_entry_text(order, entry_id, today):
    name = order["name"]
    country2 = cn.country2_of(order["address"], order["name"]) or ""
    country_label = COUNTRY_LABEL.get(country2, country2 or "未识别")
    region = cn.region_of(order["address"])
    date_str = order["date"]
    projects = order["projects"]

    # 标签
    tags = ["内部资料", "老客户"]
    if country_label:
        tags.append(country_label)
    if country2 in cn.TARGET_MARKETS:
        tags.append("北美主攻")
    for proj in projects:
        up = proj.upper()
        for kw, label in TYPE_KEYWORDS.items():
            if kw in up and label not in tags:
                tags.append(label)
    caps = []
    for proj in projects:
        for m in re.finditer(CAPACITY_RE, proj, re.IGNORECASE):
            cap = f"{m.group(1)}{m.group(2).upper()}"
            if cap not in caps:
                caps.append(cap)
    tags += caps[:6]

    area = " ".join(x for x in [country_label, cn.REGION_LABEL.get(region, region)] if x)
    summary_products = " / ".join(projects)[:300] if projects else "（明细待补）"
    # 源文件只精确到月份，展示也用 YYYY-MM，避免伪造出「1 号」这种精度
    month_str = date_str[:7] if date_str else ""

    fm = {
        "id": entry_id,
        "type": "自有成交记录",
        "name": name,
        "created": today,
        "updated": today,
        "tags": tags,
        "related": [],
        "source": "内部成交记录（公司成单客户），2022-03 ~ 2024-07",
        "客户名": name,
        "国家地区": area,
        "成交时间": month_str or "未标注",
        "产品与容量": summary_products,
        "项目名称": f"{len(projects)} 项（见正文成交明细）" if projects else "待补",
    }

    lines = []
    lines.append("## 成交明细")
    lines.append("")
    if projects:
        for proj in projects:
            stamp = month_str or "日期未标注"
            lines.append(f"- {stamp}：{proj}")
    else:
        lines.append("- 待补充")
    lines.append("")
    lines.append("## 客户背景")
    lines.append("")
    if order["address"]:
        lines.append(f"- 地址：{order['address']}")
    if order["website"]:
        lines.append(f"- 官网：{order['website']}")
    # 源数据自相矛盾时明确标出，不要替它选边
    if region in cn.CA_PROVINCES and country2 == "US":
        lines.append(f"- ⚠ 源记录地址同时出现加拿大省份（{region}）与 USA，国别存疑，待核实")
    elif region in cn.US_STATES and country2 == "CA":
        lines.append(f"- ⚠ 源记录地址同时出现美国州（{region}）与 Canada，国别存疑，待核实")
    lines.append(f"- 来源：内部成交记录（公司成单客户），原始块 #{order['block_no']}")
    lines.append("")
    lines.append("## 对开发的意义")
    lines.append("")
    if date_str:
        lines.append(f"- 最近一次成交：{month_str}。之后是否还有采购？建议用海关数据核查其**当前供应商**。")
    lines.append("- 老客户重新激活的转化成本远低于冷开——先确认是「被竞对接走」还是「需求消失」。")
    lines.append("- 若海关数据显示其供应商已变为竞对（如亚威），属于最高优先级线索，参见 leads/index.md 的流失客户专报。")
    lines.append("")

    return kblib.dump_frontmatter(fm, "\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="导入自有成交记录为知识库条目")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="成交记录文件路径")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="只打印计划（默认）")
    g.add_argument("--apply", action="store_true", help="实际写入")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        sys.exit(f"[错误] 找不到文件：{src}")

    orders = customs_adapters.parse_owned_orders(src)
    if not orders:
        sys.exit("[错误] 没有解析出任何成交记录块——检查文件格式是否为「Customer: / ADD: / Project: / Date:」")

    aliases = cn.load_aliases()
    records = kblib.load_index()
    existing = {}
    for r in records:
        if r.get("type") == "自有成交记录":
            existing[cn.company_key(r.get("name", ""), aliases)] = r

    # 按公司去重（同一家公司可能有多笔）
    merged = {}
    for o in orders:
        key = cn.company_key(o["name"], aliases)
        if key in merged:
            merged[key]["projects"] += o["projects"]
            merged[key]["date"] = max(filter(None, [merged[key]["date"], o["date"]]), default="")
            merged[key]["address"] = merged[key]["address"] or o["address"]
        else:
            merged[key] = dict(o)

    entries_dir = kblib.ENTRIES_DIR / "自有成交记录"
    today = date.today().isoformat()

    created = updated = 0
    print(f"解析到 {len(orders)} 个成交块 → {len(merged)} 家去重后的公司\n")

    for key, order in sorted(merged.items(), key=lambda kv: kv[1]["name"]):
        if key in existing:
            updated += 1
            print(f"  SKIP/UPDATE  {order['name']}  （已存在 {existing[key]['id']}）")
            continue

        entry_id = kblib.next_id(records, "cjjl")
        records.append({"id": entry_id, "type": "自有成交记录", "name": order["name"],
                        "tags": [], "updated": today, "path": ""})
        target = entries_dir / f"{kblib.safe_filename(order['name'])}.md"
        created += 1
        print(f"  CREATE       {order['name']}  → {entry_id}  ({target.name})")
        if args.apply:
            entries_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(build_entry_text(order, entry_id, today), encoding="utf-8")

    print(f"\n{'已写入' if args.apply else '计划（未写入）'}：新增 {created}，已存在 {updated}")
    if not args.apply:
        print("确认无误后加 --apply 执行。")
        return 0

    build_index.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
