#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""合并「另一台电脑」回传的行业数据

用法
----
  python3 合并回传数据.py <回传文件.json>              # 预览（不落盘）
  python3 合并回传数据.py <回传文件.json> --apply      # 实际合并入库

回传文件格式（由 `另一台电脑-行业数据抓取指令.md` 里的脚本产出）：
  [{"category":..., "source":..., "title":..., "url":..., "date":..., "summary":...}, ...]

本脚本负责把它转成标准条目并入库：
  · 补全 credibility / source_id / tags / audience_slice / usable_in / do_not_say_flags
  · 过禁语 lint（命中则降级为「仅背景」）
  · 按 id 与标题双重去重
  · 写入前自动备份
"""

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "数据" / "industry_news.json"

# 复用主脚本的归一化与 lint 逻辑，避免两套实现漂移
spec = importlib.util.spec_from_file_location("harvester", ROOT / "抓取" / "抓取行业数据.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

# 按来源名推断可信度与 source_id（回传数据不带这两个字段）
SOURCE_MAP = {
    "federal register": ("A", "fedreg"),
    "eia": ("A", "eia"),
    "sec edgar": ("A", "edgar"),
    "utility dive": ("B", "utilitydive"),
    "data center dynamics": ("B", "dcd"),
    "pv magazine usa": ("B", "pvmagazine"),
    "rto insider": ("B", "rtoinsider"),
    "transformer magazine": ("B", "external"),
    "power magazine": ("B", "powermag"),
    "reuters": ("B", "external"),
}
DEFAULT_CRED = ("C", "external")   # 其余按聚合源处理（引用前须人工核实）


def infer_source(name):
    key = (name or "").strip().lower()
    for k, v in SOURCE_MAP.items():
        if k in key:
            return v
    return DEFAULT_CRED


def to_entry(raw):
    """把回传条目转成标准条目。缺出处的直接丢弃。"""
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    pub = H.parse_date_any(raw.get("date"))
    if not title or not url or not pub:
        return None

    cred, sid = infer_source(raw.get("source"))
    summary = (raw.get("summary") or "").strip()
    cat = raw.get("category") or "market_supply"
    if cat not in H.CATEGORY_LABEL:
        cat = "market_supply"

    # 可引用句：取摘要首句；若摘要实质是「标题+来源名」则置空
    quote_en = summary
    if quote_en:
        first = H.re.split(r"(?<=[.!?])\s+", quote_en)[0].strip()
        if len(first) >= 30:
            quote_en = first
        if len(quote_en) > 240:
            quote_en = quote_en[:237].rsplit(" ", 1)[0] + "..."
    if quote_en:
        residue = quote_en
        for part in (title, raw.get("source") or ""):
            if part:
                residue = residue.replace(part, "")
        if len(H.re.sub(r"\s+", "", residue)) < 25:
            quote_en = ""
    needs_rewrite = not quote_en

    ok, issues = H.lint_quote(quote_en)
    if needs_rewrite:
        ok = False
    flags = list(issues)
    usable = ["self", "followup"]
    if needs_rewrite:
        flags.append("仅有标题、无可用摘要 —— 引用前须人工撰写完整句")
    if H.LEADTIME_PRICE_RE.search(quote_en):
        usable = ["self"]
        flags.append("含交期/价格语义 —— 不可用于跟进信正文，仅作背景")
    if not ok and not needs_rewrite:
        usable = ["self"]
    if cred == "C":
        flags.append("聚合源 —— 引用前须打开原链接核实、标注真实媒体名")

    blob = f"{title} {summary}"
    return {
        "id": H.entry_id(sid, url),
        "category": cat,
        "source_id": sid,
        "title": title,
        "summary_zh": "",
        "summary_raw": summary[:500],
        "source_name": (raw.get("source") or "外部回传").strip(),
        "source_url": url,
        "published_at": pub,
        "fetched_at": H.today_str(),
        "credibility": cred,
        "query": "",
        "quote_ready_en": quote_en,
        "quote_lint_ok": ok,
        "tags": H.infer_tags(blob),
        "audience_slice": H.infer_slice(blob),
        "usable_in": usable,
        "do_not_say_flags": flags,
        "status": "new",
        "used_in": [],
        "notes": ["来源：外部回传（另一台电脑抓取）"],
    }


def main():
    ap = argparse.ArgumentParser(description="合并外部回传的行业数据")
    ap.add_argument("file", help="回传 JSON 文件路径")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认只预览）")
    args = ap.parse_args()

    src = Path(args.file).expanduser()
    if not src.exists():
        print(f"⛔ 文件不存在：{src}")
        return 1
    raw_list = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(raw_list, list):
        print("⛔ 回传文件应为 JSON 数组")
        return 1
    print(f"读入回传条目：{len(raw_list)} 条")

    store = H.load_json(STORE, [])
    have_id = {e["id"] for e in store}
    have_title = {H.norm_title(e["title"]) for e in store}

    added, dup, bad = [], 0, 0
    for raw in raw_list:
        e = to_entry(raw)
        if e is None:
            bad += 1
            continue
        if e["id"] in have_id or H.norm_title(e["title"]) in have_title:
            dup += 1
            continue
        have_id.add(e["id"])
        have_title.add(H.norm_title(e["title"]))
        added.append(e)

    print(f"  新增 {len(added)} ｜ 重复 {dup} ｜ 缺出处丢弃 {bad}")
    if added:
        from collections import Counter
        print("  按类别:", dict(Counter(e["category"] for e in added)))
        print("  按可信度:", dict(Counter(e["credibility"] for e in added)))
        print("  可直接引用:", sum(1 for e in added if e["quote_ready_en"]))
        print()
        for e in added[:12]:
            print(f"    [{e['published_at']}] ({e['credibility']}) {e['title'][:60]}")

    if not args.apply:
        print("\n[预览模式] 未写入。确认无误后加 --apply 执行。")
        return 0

    if not added:
        print("\n无新增，未改动文件。")
        return 0

    bak = H.backup_file(STORE)
    if bak:
        print(f"\n备份 → {bak.name}")
    merged = H.dedupe(store + added)
    H.atomic_write_json(STORE, merged)
    H.atomic_write_text(H.INDEX_FILE, H.render_index(merged))
    print(f"✅ 已写 {STORE.name}（{len(store)} → {len(merged)} 条）")
    print(f"✅ 已重渲 {H.INDEX_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
