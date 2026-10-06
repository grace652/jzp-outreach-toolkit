#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch8 排重校验器 —— 输入候选公司名/域名，输出是否命中基线。

用法：
    python3 scripts/check_dedup.py "{{COMPANY}}" "wpe.ca" ...
    python3 scripts/check_dedup.py --file candidates.txt
    python3 scripts/check_dedup.py --file candidates.txt --quiet   # 只输出命中项

匹配规则（吸收 2026-09-30 的教训）：
  · 归一化：小写、& -> and、去标点、压缩空白
  · 全词匹配（关键词作为独立词出现）
  · 子串匹配仅在「两侧都 >= 8 字符」时才算命中（防 kline ⊂ franklinempire 类假阳性）
  · 域名单独比对一个域名集合（含退信域名）
"""
import argparse
import re
import sys
from pathlib import Path

BASE = Path(Path(__file__).resolve().parents[1] / "线索资产")
BASELINE = BASE / "_dedup_baseline_batch10.txt"      # 可用 --baseline 覆盖

BOUNCE = [
    "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}",
    "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}",
    "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}",
    "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}", "{{COMPANY_DOMAIN}}",
]


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_baseline(path=None):
    d = {}
    for line in (path or BASELINE).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        k = parts[0].strip()
        src = parts[1].strip() if len(parts) > 1 else "?"
        if k:
            d[k] = src
    return d


def variants(s: str):
    """归一化变体集合 —— 用于跨「空格 / & 写法」差异的比对。

    🔴 2026-10-05：v2 基线里存的是**无空格、无 and** 的形式（`turtlehughes`、`valardconstruction`），
    而检索 agent 报的是 `{{COMPANY}}`（`norm` 后变成 `turtle and hughes`）→ 对不上。
    故同时产出三种变体：原样 / 去空格 / 去「and」再去空格。
    """
    n = norm(s)
    out = {n, n.replace(" ", "")}
    out.add(n.replace(" and ", " ").replace(" ", ""))
    return {x for x in out if x}


def match(name: str, baseline: dict):
    """返回命中列表 [(关键词, 来源, 方式)]

    🔴 2026-10-02：长度 < 5 的短关键词只做全词匹配（防 `k line` ⊂ `allteck line`）。
    🔴 2026-10-05：增加「去空格前缀」与多变体比对（修 `{{COMPANY}}` / `{{COMPANY}}` 漏网）。
    """
    n = norm(name)
    hits = []
    if not n:
        return hits
    if n in baseline:
        hits.append((n, baseline[n], "全等"))
        return hits

    nv = variants(name)
    for k, src in baseline.items():
        if not k:
            continue
        # 全词匹配
        if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", n):
            hits.append((k, src, "全词"))
            continue
        # 多变体「去空格前缀」比对
        kv = variants(k)
        matched = None
        for a in nv:
            for b in kv:
                if len(a) < 5 or len(b) < 5:
                    continue
                short, long_ = (a, b) if len(a) <= len(b) else (b, a)
                if len(short) >= 5 and long_.startswith(short):
                    matched = "去空格前缀"
                    break
            if matched:
                break
        if matched:
            hits.append((k, src, matched))
            continue
        # 子串：仅限「关键词 >= 5 字符」且两侧都 >= 8 字符
        if len(k) < 5:
            continue
        idx = n.find(k)
        if idx > 0 and len(n) - (idx + len(k)) >= 8:
            hits.append((k, src, "子串(两侧>=8)"))
            continue
        # 反向包含：查询名较长、被关键词完整包含，且长度接近（差 <= 15 字符）
        if len(n) >= 12 and n in k and (len(k) - len(n)) <= 15:
            hits.append((k, src, "反向包含(长度差<=15)"))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--baseline", help="覆盖基线文件路径（默认 batch10）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    names = list(args.names)
    if args.file:
        names += [l.strip() for l in Path(args.file).read_text(encoding="utf-8").splitlines() if l.strip()]

    if not names:
        print("没有输入。用法：check_dedup.py \"公司名\" ...")
        return 1

    bl_path = Path(args.baseline) if args.baseline else BASELINE
    baseline = load_baseline(bl_path)
    print(f"基线 {bl_path.name} ｜ 关键词 {len(baseline)} 条 ｜ 退信域名 {len(BOUNCE)} 个\n")

    clean, dirty = [], []
    for name in names:
        hits = match(name, baseline)
        dom = name.split("/")[0].strip().lower()
        bhit = [b for b in BOUNCE if dom == b or dom.endswith("." + b)]
        if hits or bhit:
            dirty.append((name, hits, bhit))
        else:
            clean.append(name)

    if not args.quiet:
        print("=== ✅ 干净（未命中基线/退信）===")
        for c in clean:
            print("  " + c)
        print()

    print("=== ⛔ 命中 ===")
    if not dirty:
        print("  （无）")
    for name, hits, bhit in dirty:
        print(f"  {name}")
        for k, src, how in hits:
            print(f"      ← 基线[{src}] 「{k}」 ({how})")
        for b in bhit:
            print(f"      ← 退信域名 「{b}」")

    print(f"\n汇总：输入 {len(names)} ｜ 干净 {len(clean)} ｜ 命中 {len(dirty)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
