#!/usr/bin/env python3
"""按关键词/类型/标签检索知识库。

用法：python search.py "关键词" [--type 类型] [--tag 标签]
示例：python search.py "东南亚" --type 竞争对手
"""
import argparse
import sys

import kblib

CONTEXT_CHARS = 50   # 命中片段：关键词前后各取多少字符
MAX_SNIPPETS = 3     # 每个文件最多显示几处命中


def make_snippet(text, pos, kw_len):
    start = max(0, pos - CONTEXT_CHARS)
    end = min(len(text), pos + kw_len + CONTEXT_CHARS)
    frag = " ".join(text[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{frag}{suffix}"


def find_matches(text_lower, kw_lower):
    positions = []
    start = 0
    while len(positions) < MAX_SNIPPETS:
        pos = text_lower.find(kw_lower, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + len(kw_lower)
    return positions


def main():
    parser = argparse.ArgumentParser(description="检索知识库条目")
    parser.add_argument("关键词", help="要搜索的关键词")
    parser.add_argument("--type", action="append", default=[], metavar="类型",
                        help="按实体类型过滤，可重复传入")
    parser.add_argument("--tag", action="append", default=[], metavar="标签",
                        help="按标签过滤（须同时包含所有指定标签），可重复传入")
    args = parser.parse_args()
    keyword = vars(args)["关键词"]
    types, tags = vars(args)["type"], vars(args)["tag"]

    records = kblib.load_index()

    # 1) 先用索引按 type / tag 缩小范围
    candidates = [
        r for r in records
        if (not types or r.get("type") in types)
        and (not tags or all(t in (r.get("tags") or []) for t in tags))
    ]

    # 2) 再对候选文件做正文关键词匹配（大小写不敏感）
    kw_lower = keyword.lower()
    hits = []
    for rec in candidates:
        path = kblib.ROOT / rec["path"]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        positions = find_matches(text.lower(), kw_lower)
        if positions:
            snippets = [make_snippet(text, p, len(keyword)) for p in positions]
            hits.append((rec, snippets))

    if not hits:
        print(f"未找到匹配「{keyword}」的条目"
              f"{'（当前过滤条件：type=' + ','.join(types) + ' tag=' + ','.join(tags) + '）' if (types or tags) else ''}")
        return 1

    print(f"共 {len(hits)} 个条目匹配「{keyword}」：\n")
    for rec, snippets in hits:
        print(f"[{rec['id']}] {rec['name']}（{rec['type']}）  tags: {rec.get('tags') or []}")
        print(f"  {rec['path']}")
        for snip in snippets:
            print(f"  > {snip}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
