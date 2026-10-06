#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用排重基线构建器 —— 为 batchN 生成排重基线（不修改任何既有基线文件）。

合并来源：
  1. _dedup_keywords_v2.txt          （已触达 clients/ + 交接单 batch1-5）
  2. 目标客户清单-batch6/7/8/… csv    （历次名单的**全部行**：入选 + 剔除 + 备选 —— 均已研究过）
  3. 成交客户 16 家 + 我方代理 POWER ELECTRONICS
  4. 永久排除名录.md

用法：
  python3 scripts/build_baseline.py 9          # 生成 _dedup_baseline_batch9.txt
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(Path(__file__).resolve().parents[1] / "线索资产")

DEALS = [
    "Black & McDonald Limited", "Wilson High Voltage Inc.", "AC Tesla",
    "JS Energy LTD.", "Jungbunzlauer Canada Inc.", "ATD Power Solutions",
    "Drunken Moose Enterprises Inc.", "Pro 1 Electric, Inc.", "iSpice Foods",
    "Domino Highvoltage", "POWER ELECTRONICS", "Boundary Electric",
    "Bibico Electric Inc", "Electric South", "SGE", "Intellogic Engineering Inc.",
    "Anguilla Electricity Company Limited",
]

# 🔴 2026-10-05 新增：已触达的**连锁经销商/集团**。
#    来源：`线索资产/排重核对表.md` §3.2「EECOL / Westburne / Gescan / Wesco（连锁，多批次已触达）」
#    —— 该说明**只写在文档里、从未进过基线**，batch10 实测 EECOL / Westburne **完全不在基线**，
#    检索 agent 把 EECOL 当新线索报了上来。**又一次「写在文档里不落到数据就等于没有」。**
CHAINS = [
    "EECOL Electric", "Westburne", "Gescan", "Wesco Distribution", "Nedco",
    "Rexel", "Sonepar", "Graybar", "Guillevin", "Lumen", "Rexel Canada",
    "State Electric", "Kendall Electric", "Summit Electric Supply", "City Electric Supply",
]


def norm(s: str) -> str:
    s = (s or "").strip().lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# 🔴 2026-10-06 新增：真正把《永久排除名录.md》读进基线。
#    此前本文件 docstring 写着「合并 永久排除名录.md」，**但代码里从未加载** ——
#    实测 batch11 基线里 **13 家已登记排除的公司不在**（Triton / Premier / Core Transformers /
#    BCS Switchgear / Wismer & Rawlings / AVH Supply / Rionex / Crown Mountain / JDD …）。
#    这是本项目**第四次**「写在文档里 ≠ 落到数据里」（前三次：batch7 成交客户、batch9 三字母名、
#    batch10 连锁经销商）。**凡判定，必须落到数据行。**
#
#    ⚠️ 必须跳过 §三「反向陷阱」—— 那一节是**防误杀清单**（名字像竞品、实为真客户），
#    把它们当排除项会**误杀 Beaver Electrical Machinery / RS Breakers and Controls**。
JUNK_PAT = re.compile(r"\.md|\.txt|\.csv|^_|§|^\d+$")


def load_exclusions():
    """解析《永久排除名录.md》表格首列 → 排除公司名列表。

    只取**标题带 ⛔ 的小节**（即真正的排除小节）：
      一 ⛔ 制造商 ／ 二 ⛔ 中国货源代理 ／ 四 ⛔ 我方关联 ／ 五 ⛔ 其他
    显式跳过：
      〇 说明 ／ **三 ⚠️ 反向陷阱（防误杀清单，是客户不是竞品）** ／ 六 使用方式 ／ 附
    """
    path = BASE / "永久排除名录.md"
    if not path.exists():
        return []
    txt = path.read_text(encoding="utf-8")
    names, in_section = [], False
    for line in txt.splitlines():
        if line.startswith("## "):
            # 仅「排除」小节参与；⚠️ 反向陷阱节不参与（否则会误杀真客户）
            in_section = ("⛔" in line) and ("反向" not in line)
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        cell = cells[0].replace("**", "").replace("`", "").strip()
        if not cell or set(cell) <= set("-: ") or cell in ("公司", "实体", "文件"):
            continue
        for part in re.split(r"[/、]", cell):
            part = re.sub(r"[（(].*?[）)]", " ", part).strip()
            if len(part) < 3 or JUNK_PAT.search(part):
                continue
            names.append(part)
    return names


def load_csv_names(path: Path):
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            for c in ("公司全称", "简称"):
                v = (row.get(c) or "").strip()
                if v:
                    out.append(v)
                    # 🔴 2026-10-05 修正：同时登记「去掉括注」的变体。
                    #   实测：batch9 的 `Southern Transformer Services (STS)` 只存了带括注的形式，
                    #   而检索 agent 报上来的是 `Southern Transformer Services` → **匹配不上**。
                    #   例：`XXX (STS)` → 追加 `XXX`
                    stripped = re.sub(r"[（(][^）)]*[）)]", " ", v).strip()
                    if stripped and stripped != v:
                        out.append(stripped)
            d = (row.get("官网") or "").strip()
            if d:
                out.append(d.split("/")[0])
    return out


def main():
    batch = sys.argv[1] if len(sys.argv) > 1 else "9"
    entries = []

    v2 = BASE / "_dedup_keywords_v2.txt"
    n_v2 = 0
    for line in v2.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.append((line, "v2"))
            n_v2 += 1

    csv_counts = {}
    for b in range(6, int(batch)):
        names = load_csv_names(BASE / f"目标客户清单-batch{b}.csv")
        if names:
            entries += [(x, f"batch{b}") for x in names]
            csv_counts[f"batch{b}"] = len(names)

    entries += [(x, "成交客户") for x in DEALS]
    entries += [(x, "连锁已触达") for x in CHAINS]

    excl = load_exclusions()
    entries += [(x, "永久排除") for x in excl]

    seen = {}
    for kw, src in entries:
        k = norm(kw)
        # 🔴 2026-10-02 修正：阈值从 4 降到 3。
        #    旧版把 3 字符以内的关键词静默丢弃 ⇒ **成交客户 SGE（3 字母）没进基线**，
        #    batch9 检索时 `groupesge.ca` 被当成新线索报上来（险些给已成交客户发冷邮件）。
        #    短词容易误命中，改由 check_dedup.py 对「长度<5 的关键词」只做全词匹配来控误报。
        if len(k) < 3:
            continue
        seen.setdefault(k, src)

    out = BASE / f"_dedup_baseline_batch{batch}.txt"
    with out.open("w", encoding="utf-8") as f:
        f.write(f"# batch{batch} 排重基线（自动生成，勿手改）\n")
        f.write("# 来源：v2 + batch6~%s 名单 + 成交客户 16 家 + 我方代理\n" % (int(batch) - 1))
        f.write("# 生成：scripts/build_baseline.py\n")
        for k, src in sorted(seen.items()):
            f.write(f"{k}\t{src}\n")

    print(f"v2 读入           : {n_v2}")
    for k, v in csv_counts.items():
        print(f"{k} 条目        : {v}")
    print(f"成交客户条目      : {len(DEALS)}")
    print(f"连锁已触达条目    : {len(CHAINS)}")
    print(f"永久排除名录条目  : {len(excl)}")
    print(f"归一化后唯一关键词: {len(seen)}")
    for k, v in Counter(seen.values()).most_common():
        print(f"  - {k:10s} {v}")
    print(f"\n写出 -> {out}")


if __name__ == "__main__":
    main()
