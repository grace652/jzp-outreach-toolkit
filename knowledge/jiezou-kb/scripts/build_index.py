#!/usr/bin/env python3
"""扫描 entries/ 重建 index/index.json。

用法：python build_index.py
"""
import json
import sys

import kblib


def main():
    records = kblib.scan_entries()
    records.sort(key=lambda r: (r["type"], r["id"]))
    kblib.INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    kblib.INDEX_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"索引已更新：{len(records)} 条记录 → index/index.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
