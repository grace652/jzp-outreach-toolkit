#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段 4：同步文本备份 `开发信跟进表.md`

改动：
  1. 头部补「新增 sheet」说明
  2. `## 当前跟进排期` —— 命中跟进信的行标注已发
  3. `## 跟进明细` —— 就地更新老客户块 + **追加 92 个新块**
  4. 新增 `## 新 sheet 索引（batch5+6）` 速查段

不动的段：`## 字段说明`、`## 跟进节奏（标准）`、`## 状态图例`
"""
import json, re, sys
from pathlib import Path

ROOT = Path(Path(__file__).resolve().parents[1])
MD = ROOT / "开发信项目/工作区/开发信跟进表.md"
COLS = ["#", "发送日期", "公司名称", "国家/地区", "联系人", "职位", "买家类型", "需求产品",
        "触达来源", "骨架", "建议发送时间(北京)", "邮箱", "状态", "跟进次数", "下次跟进日",
        "最后联系日", "备注 / 下一步"]
# md 详情块的字段名（与现有 116 块保持一致）
MD_KEYS = ["发送日期", "公司名称", "国家/地区", "联系人", "职位", "买家类型", "需求产品",
           "触达来源", "骨架", "建议发送时间", "邮箱", "状态", "跟进次数", "下次跟进日",
           "最后联系日", "备注"]


def block(n, r):
    lines = [f"### {n}. {r['公司名称']}", "", "| 字段 | 内容 |", "|---|---|"]
    for k in MD_KEYS:
        v = str(r.get(k, "") or "—")
        lines.append(f"| {k} | {v} |")
    lines.append("")
    lines.append(f"**信文件**：{r['_letter'] or '（未写信）'}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def main():
    dry = "--dry" in sys.argv
    rows = json.loads(Path("/tmp/new_rows.json").read_text(encoding="utf-8"))
    t = MD.read_text(encoding="utf-8")
    orig_len = len(t)

    # ---- 1) 头部说明
    anchor = "> 每写好一封开发信，我会同步更新这两个文件。"
    if anchor in t and "开发信跟进表-batch5+6" not in t:
        t = t.replace(anchor, anchor + "\n>\n> 🔴 **2026-09-29 更新**：新增子表 **`开发信跟进表-batch5+6`**（xlsx 第 2 个 sheet），"
                                          "收录 **2026-09-24 之后**找到的客户 **92 家**（batch5 43 + batch6 49）。"
                                          "本 md 文件末尾同步追加了这 92 家的明细块（`### 117.` 起）。", 1)

    # ---- 3) 追加 92 个新块（追加到文件末尾）
    blocks = "\n".join(block(117 + i, r) for i, r in enumerate(rows))

    # ---- 4) 新索引段
    idx = ["## 新 sheet 索引（batch5+6 · 2026-09-24 之后 92 家）", "",
           "> 对应 xlsx 子表 `开发信跟进表-batch5+6`；明细见文末 `### 117.` 起。", "",
           "| # | 公司 | 买家号 | 国家/地区 | 状态 | 跟进 | 下次跟进日 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        idx.append(f"| {r['#']} | {r['公司名称'][:34]} | {r['_buyer']} | {r['国家/地区']} | "
                   f"{r['状态']} | {r['跟进次数']} | {r['下次跟进日'] or '—'} |")
    idx.append("")
    idx_txt = "\n".join(idx)

    # ---- 2) 排期表：命中跟进信的行加标注
    def mark(m):
        row = m.group(0)
        for r in rows:
            if r["公司名称"][:8].lower() in row.lower() and r["跟进次数"]:
                return row.rstrip() + f"  ⬆️ 已跟进{r['跟进次数']}次"
        return row
    t = re.sub(r"^\|\s*\d+\s*\|[^\n]*\|$", mark, t, flags=re.M)

    out = t.rstrip() + "\n\n---\n\n" + idx_txt + "\n---\n\n## 跟进明细（batch5+6 新增 92 家）\n\n" + blocks
    if dry:
        print(f"[dry] 原 {orig_len} 字符 → 新 {len(out)} 字符（+{len(out)-orig_len}）")
        print(f"      追加 {len(rows)} 个明细块（### 117. – ### {116+len(rows)}.）")
        return
    MD.write_text(out, encoding="utf-8")
    print(f"✅ 已同步 {MD}")
    print(f"   原 {orig_len} → 新 {len(out)} 字符（+{len(out)-orig_len}）")
    print(f"   追加 {len(rows)} 个明细块（### 117. – ### {116+len(rows)}.）")


if __name__ == "__main__":
    main()
