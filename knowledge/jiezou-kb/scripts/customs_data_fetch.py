#!/usr/bin/env python3
"""海关数据抓取/解析 CLI。

抓取是探索性的、可重跑的，**只写 data/，永不写 entries/**。
把某个买家变成知识库条目是判断动作，由 lead_scoring.py 负责。

常用命令
    # 看有哪些适配器
    python3 scripts/customs_data_fetch.py --list-adapters

    # 零风险：只打印可点的查询链接，不抓任何东西
    python3 scripts/customs_data_fetch.py --print-urls --hs 8504.21,8504.22,8504.33

    # 加拿大官方开放数据（联网，免费）
    python3 scripts/customs_data_fetch.py --adapter canada_cid --inspect
    python3 scripts/customs_data_fetch.py --adapter canada_cid --hs 8504.21,8504.22 --country CA

    # 离线：解析本地 CSV（广交会名录 / 各平台导出文件）
    python3 scripts/customs_data_fetch.py --adapter local_csv \
        --file "/path/to/广交会采购商名录.csv" --profile cantonfair \
        --country 美国,加拿大 --limit 20000

    # 未来：付费平台导出文件
    python3 scripts/customs_data_fetch.py --adapter local_csv \
        --file "<导出文件>" --profile importyeti
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import customs_adapters as ca
import customs_normalize as cn
import kblib

DATA_DIR = kblib.ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORM_DIR = DATA_DIR / "normalized"

# 变压器相关 HS 码（JIEZOU 主力在 8504.21/22/23 与 8504.33/34）
DEFAULT_HS = ["8504.21", "8504.22", "8504.23", "8504.31", "8504.32", "8504.33", "8504.34", "8504.90"]


def coverage_histogram(records):
    """统计有多少条记录带上了关键字段——用来诚实反映数据完整度。"""
    total = len(records) or 1
    have = {
        "票数": sum(1 for r in records if (r.get("shipment_count") or 0) > 0),
        "重量": sum(1 for r in records if (r.get("quantity_kg") or 0) > 0),
        "金额": sum(1 for r in records if (r.get("value_usd") or 0) > 0),
        "日期": sum(1 for r in records if r.get("last_shipment_date")),
        "供应商": sum(1 for r in records if r.get("supplier_name")),
        "联系方式": sum(1 for r in records if r.get("contact_email") or r.get("contact_phone")),
        "HS码": sum(1 for r in records if r.get("hs_code6")),
    }
    return {k: round(v / total * 100) for k, v in have.items()}


def main():
    ap = argparse.ArgumentParser(description="海关数据抓取/解析")
    ap.add_argument("--adapter", default="", help="适配器名，逗号分隔")
    ap.add_argument("--list-adapters", action="store_true", help="列出可用适配器")
    ap.add_argument("--print-urls", action="store_true", help="只打印可点的查询链接，不抓取")

    ap.add_argument("--hs", default="", help="HS 码，逗号分隔，如 8504.21,8504.22")
    ap.add_argument("--keyword", default="", help="关键词，逗号分隔")
    ap.add_argument("--country", default="", help="国家（2 位码或名称），逗号分隔，留空不限")
    ap.add_argument("--category", default="", help="产品类别（广交会名录用），逗号分隔")
    ap.add_argument("--limit", type=int, default=0, help="最多产出多少条记录")

    ap.add_argument("--file", default="", help="local_csv 适配器的输入文件")
    ap.add_argument("--profile", default="manual", help="列名预设：cantonfair/importyeti/52wmb/trademo/manual")
    ap.add_argument("--map", default="", help="列名覆盖，形如 buyer_name=公司名称,hs_code=HS")

    ap.add_argument("--inspect", action="store_true", help="打印来源的真实列名（首次接入时用）")
    ap.add_argument("--offline", action="store_true", help="禁用一切联网")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存，重新下载")
    ap.add_argument("--cache-ttl-days", type=int, default=30)
    ap.add_argument("--min-interval", type=float, default=3.0, help="同一主机两次请求的最小间隔（秒）")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--out-prefix", default="", help="输出文件名前缀")
    ap.add_argument("--preview", type=int, default=12, help="打印前多少条记录")
    args = ap.parse_args()

    if args.list_adapters:
        print("可用适配器：\n")
        for a in ca.list_adapters():
            flag = "联网" if a.requires_network else "离线"
            ok, reason = a.available()
            status = "可用" if ok else f"不可用（{reason}）"
            print(f"  {a.name:12} [{flag}] {status}")
            print(f"      {a.description}")
            print()
        return 0

    query = ca.Query(
        hs_codes=[h for h in args.hs.split(",") if h.strip()],
        keywords=[k.strip() for k in args.keyword.split(",") if k.strip()],
        country=args.country,
        categories=[c.strip() for c in args.category.split(",") if c.strip()],
        limit=args.limit,
        refresh=args.refresh,
        offline=args.offline,
    )

    names = [n.strip() for n in args.adapter.split(",") if n.strip()]
    if not names:
        names = ["canada_cid"] if not args.file else ["local_csv"]

    if args.print_urls:
        print("以下是可直接点开的查询链接（本命令不抓取任何数据）：\n")
        seen = set()
        for name in names:
            try:
                adapter = ca.get_adapter(name)
            except KeyError as exc:
                print(f"  [跳过] {exc}")
                continue
            for url in adapter.print_manual_urls(query):
                if url not in seen:
                    seen.add(url)
                    print(f"  {url}")
        return 0

    cache = ca.Cache(ttl_days=args.cache_ttl_days, min_interval=args.min_interval,
                     offline=args.offline, timeout=args.timeout)

    column_map = {}
    for item in args.map.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            column_map[k.strip()] = v.strip()

    records = []
    for name in names:
        try:
            adapter = ca.get_adapter(name)
        except KeyError as exc:
            print(f"[跳过] {exc}", file=sys.stderr)
            continue

        if name == "local_csv":
            adapter.configure(file=args.file, profile=args.profile, column_map=column_map)

        ok, reason = adapter.available(cache)
        if not ok:
            print(f"[跳过] {name}：{reason}", file=sys.stderr)
            if name == "canada_cid" and not args.offline:
                print("      可改用 --print-urls 拿查询链接，或稍后重试。", file=sys.stderr)
            continue

        if args.inspect and hasattr(adapter, "inspect"):
            print(f"=== {name} 来源列名探测 ===\n")
            for rep in adapter.inspect(cache):
                print(f"  工作表：{rep['sheet']}")
                print(f"  列名：{rep['columns']}")
                print(f"  自动识别：{rep['detected']}")
                for row in rep["sample_rows"][:3]:
                    print(f"    样例：{row}")
                print()
            print("若识别不全，用 --map buyer_name=列名,hs_code=列名 覆盖。")
            return 0

        print(f"[{name}] 抓取中…", file=sys.stderr)
        try:
            for rec in adapter.fetch(query, cache):
                records.append(rec)
        except ca.OfflineError as exc:
            print(f"[跳过] {name}：{exc}", file=sys.stderr)
            continue
        except (NotImplementedError, ValueError) as exc:
            print(f"[跳过] {name}：{exc}", file=sys.stderr)
            continue

    if not records:
        print("\n没有取到任何记录。", file=sys.stderr)
        print("提示：", file=sys.stderr)
        print("  · 联网源可能是网络不通，试试 --print-urls 拿链接手动查", file=sys.stderr)
        print("  · 离线源请确认 --file 路径与 --profile 是否匹配", file=sys.stderr)
        return 0  # 优雅退出，不抛栈

    # 去重（record_id 相同视为同一条）
    deduped, seen = [], set()
    for r in records:
        rid = r.get("record_id")
        if rid in seen:
            continue
        seen.add(rid)
        deduped.append(r)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + ("-" + args.out_prefix if args.out_prefix else "")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORM_DIR.mkdir(parents=True, exist_ok=True)

    with open(RAW_DIR / f"{run_id}.jsonl", "w", encoding="utf-8") as fh:
        for r in deduped:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")

    norm_path = NORM_DIR / f"{run_id}.csv"
    with open(norm_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ca.NORMALIZED_FIELDS)
        w.writeheader()
        for r in deduped:
            row = dict(r)
            row["raw"] = json.dumps(row.get("raw") or {}, ensure_ascii=False, default=str)
            w.writerow(row)

    hist = coverage_histogram(deduped)
    buyers = len({r["buyer_key"] for r in deduped if r.get("buyer_key")})
    meta = {
        "run_id": run_id, "adapters": names, "record_count": len(deduped),
        "buyer_count": buyers, "coverage_histogram": hist,
        "query": {"hs": query.hs_codes, "keyword": query.keywords,
                  "country": query.country, "categories": query.categories},
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    (NORM_DIR / f"{run_id}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    runs_path = NORM_DIR / "_runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else []
    runs.append(meta)
    runs_path.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n记录 {len(deduped)} 条（去重后）· 买家 {buyers} 家")
    print(f"字段覆盖度：{hist}")
    print(f"输出：{norm_path.relative_to(kblib.ROOT)}")
    if hist.get("票数", 0) == 0:
        print("⚠ 本批数据不含票数/金额/日期，打分的完整度会偏低——"
              "这是来源本身的限制，不是脚本问题。")

    if args.preview:
        print(f"\n前 {min(args.preview, len(deduped))} 条：")
        for r in deduped[: args.preview]:
            print(f"  {r['buyer_name'][:40]:40} {r.get('buyer_country2',''):3} "
                  f"hs={r.get('hs_code6','') or '-':7} 供应商={r.get('supplier_name','') or '-':28} "
                  f"票={r.get('shipment_count') or '-'}")
    print(f"\n下一步：python3 scripts/lead_scoring.py --input {norm_path.relative_to(kblib.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
