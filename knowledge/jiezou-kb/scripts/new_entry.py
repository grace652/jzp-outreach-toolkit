#!/usr/bin/env python3
"""交互式创建新条目。

用法：python new_entry.py <类型> <名称>
示例：python new_entry.py 竞争对手 "XX电气"
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import build_index
import kblib


def safe_filename(name):
    """去掉文件名里不允许的字符（实现已上移到 kblib，此处保留以兼容既有调用）。"""
    return kblib.safe_filename(name)


def prompt_fields(fields):
    """依次询问专属字段，回车跳过。"""
    answers = {}
    for field in fields:
        name = field.get("name", "")
        hint = field.get("hint", "")
        suffix = f"（{hint}）" if hint else ""
        try:
            answers[name] = input(f"  {name}{suffix}，回车可跳过: ").strip()
        except EOFError:
            answers[name] = ""
    return answers


def main():
    parser = argparse.ArgumentParser(description="创建新的知识库条目")
    parser.add_argument("类型", help="实体类型，需与 schema/ 下的 JSON 文件同名")
    parser.add_argument("名称", help="条目名称（同时作为文件名）")
    args = parser.parse_args()

    entity_type, name = vars(args)["类型"], vars(args)["名称"]

    schema = kblib.load_schema(entity_type)
    if schema is None:
        types = "、".join(kblib.available_types())
        sys.exit(f"[错误] 找不到 schema/{entity_type}.json。可用类型：{types}")

    entries_dir = kblib.ENTRIES_DIR / entity_type
    entries_dir.mkdir(parents=True, exist_ok=True)

    target = entries_dir / f"{safe_filename(name)}.md"
    if target.exists():
        sys.exit(f"[错误] 条目已存在：{target.relative_to(kblib.ROOT).as_posix()}")

    # id：类型前缀 + 自增序号（优先读 index.json，没有则现场扫描）
    prefix = schema.get("prefix") or entity_type
    records = kblib.load_index()
    entry_id = kblib.next_id(records, prefix)

    # 收集专属字段
    fields = schema.get("fields", [])
    print(f"正在创建[{entity_type}]条目：{name}（id: {entry_id}）")
    print("请依次填写以下字段，直接回车可跳过：")
    answers = prompt_fields(fields) if fields else {}

    # 用模板做骨架：保留模板里的所有键，再填入实际值
    template_path = kblib.ROOT / "templates" / f"{entity_type}.md"
    if template_path.exists():
        fm, body = kblib.parse_frontmatter(template_path.read_text(encoding="utf-8"))
    else:
        print(f"[警告] 缺少 templates/{entity_type}.md，使用空白模板", file=sys.stderr)
        fm, body = {}, "\n"

    today = date.today().isoformat()
    fm.update({
        "id": entry_id,
        "type": entity_type,
        "name": name,
        "created": fm.get("created") or today,
        "updated": today,
        "tags": fm.get("tags") or [],
        "related": fm.get("related") or [],
        "source": fm.get("source") or "",
    })
    fm.update(answers)

    target.write_text(kblib.dump_frontmatter(fm, body), encoding="utf-8")
    print(f"已写入：{target.relative_to(kblib.ROOT).as_posix()}")

    # 自动刷新索引
    build_index.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
