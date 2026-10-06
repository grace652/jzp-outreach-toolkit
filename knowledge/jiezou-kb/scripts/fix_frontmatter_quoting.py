#!/usr/bin/env python3
"""修正 frontmatter 中未加引号、含 ": " 的非法 YAML 值。

背景：条目正文里写「（B/L: PLKQSH26056631）」这类内容时，整行会变成
    历史订单: 2026-05-24 一票 4 包 36,920 kg（B/L: PLKQSH26056631）
值里出现的 ": " 在严格 YAML 里是非法的（pyyaml 会抛
"mapping values are not allowed here"）。内置宽松解析器能容忍，
所以问题一直潜伏着——一旦哪天装了 pyyaml，整个库就读不出来。

本脚本只给「需要引号」的值补上双引号，其余字节原样保留。

用法：
    python3 scripts/fix_frontmatter_quoting.py --dry-run   # 只看会改什么
    python3 scripts/fix_frontmatter_quoting.py --apply     # 实际写入
"""
import argparse
import sys
from pathlib import Path

import kblib


def _offending_lines(text):
    """返回 [(行号, key, 原始值)]，即 frontmatter 里需要补引号的行。"""
    lines = text.split("\n")
    block = kblib._frontmatter_block(lines)
    if not block:
        return []
    hits = []
    for i in range(block[0] + 1, block[1]):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, raw = line.partition(":")
        if not sep:
            continue
        key, raw = key.strip(), raw.strip()
        if not raw:
            continue
        if raw[0] in "\"'":          # 已经加过引号
            continue
        if ": " in raw or raw.endswith(":") or " #" in raw:
            hits.append((i + 1, key, raw))
    return hits


def main():
    ap = argparse.ArgumentParser(description="修正 frontmatter 里的非法 YAML 值")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="只打印将要修改的内容")
    g.add_argument("--apply", action="store_true", help="实际写入文件")
    args = ap.parse_args()

    files = sorted(kblib.ENTRIES_DIR.rglob("*.md"))
    changed_files = 0
    changed_lines = 0

    for path in files:
        text = path.read_text(encoding="utf-8")
        hits = _offending_lines(text)
        if not hits:
            continue
        changed_files += 1
        rel = path.relative_to(kblib.ROOT).as_posix()
        print(f"\n{rel}")
        out = text
        for lineno, key, raw in hits:
            changed_lines += 1
            fixed = kblib.quote_scalar(raw)
            print(f"  L{lineno} {key}:")
            print(f"    - {raw}")
            print(f"    + {fixed}")
            out = kblib.set_frontmatter_field(out, key, raw)
        if args.apply:
            path.write_text(out, encoding="utf-8")

    if changed_files == 0:
        print("没有需要修正的行——所有条目的 frontmatter 都是合法 YAML。")
        return 0

    verb = "已写入" if args.apply else "待修改（未写入）"
    print(f"\n{verb}：{changed_files} 个文件 / {changed_lines} 行")
    if not args.apply:
        print("确认无误后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
