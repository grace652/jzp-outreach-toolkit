#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理「定时任务」在应用库里留下的残留（**操作对象是应用库，不是项目数据**）

背景（用户 2026-10-01）：
> 「这个定时任务由于一些问题，开了好多对话，如果没有影响，你帮我删除了」

自动化本身已全部删除（`automation_update mode=delete`，列表为 0），
但它在应用库 `~/.workbuddy-ai/workbuddy.db` 里留下了：

| 表 | 内容 | 本机数量 |
|---|---|---|
| `sessions` | `is_background_automation = 1` 的会话（= 那「好多对话」）| **21** |
| `session_usage` | 上述会话的用量行 | 21 |
| `automation_runs` | 已删自动化的运行记录 | 21 |
| `automation_runtime_state` | 已删自动化的运行时状态 | 6 |
| `automations` | 已软删（`deleted_at` 非空）的自动化本体 | 9 |

🔴 **安全前提（已逐条核实）**：
1. **全库无任何外键约束**（`PRAGMA foreign_key_list` 全为空）→ 删除不会违反约束
2. 21 个会话**全部**落在 `jzp-americas-dev` 一个 cwd 下，边界清晰
3. **28 个非自动化会话（含用户本人的对话）不在范围内**，绝不动
4. 删前**整库备份**（含 `-wal` / `-shm`），可整库回滚

用法：
  python3 scripts/清理自动化残留.py --dry-run   # 只统计，不写
  python3 scripts/清理自动化残留.py             # 备份 + 清理 + 复核
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path.home() / ".workbuddy-ai" / "workbuddy.db"
BACKUP_DIR = Path.home() / ".workbuddy-ai" / "_backup-before-cleanup"


def counts(cur):
    q = lambda s: cur.execute(s).fetchone()[0]
    return {
        "automation_sessions": q("SELECT COUNT(*) FROM sessions WHERE is_background_automation = 1"),
        "user_sessions": q("SELECT COUNT(*) FROM sessions WHERE is_background_automation IS NULL"),
        "session_usage_total": q("SELECT COUNT(*) FROM session_usage"),
        "automation_runs": q("SELECT COUNT(*) FROM automation_runs"),
        "runtime_state": q("SELECT COUNT(*) FROM automation_runtime_state"),
        "automations_softdeleted": q("SELECT COUNT(*) FROM automations WHERE deleted_at IS NOT NULL"),
        "automations_total": q("SELECT COUNT(*) FROM automations"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DB.exists():
        raise SystemExit(f"⛔ 找不到应用库：{DB}")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    before = counts(con.cursor())
    con.close()
    print("改前：")
    for k, v in before.items():
        print(f"  {k:<24} {v}")

    if args.dry_run:
        print("\n（--dry-run，未写任何东西）")
        return 0

    # ---- 备份（整库 + WAL/SHM）----
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(DB) + suffix)
        if src.exists():
            dst = BACKUP_DIR / f"workbuddy.db.{stamp}{suffix}"
            shutil.copy2(src, dst)
            print(f"已备份 → {dst}")
    print()

    # ---- 清理（单事务）----
    con = sqlite3.connect(DB)
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute("""DELETE FROM session_usage WHERE session_id IN
                       (SELECT id FROM sessions WHERE is_background_automation = 1)""")
        u = cur.rowcount
        cur.execute("DELETE FROM sessions WHERE is_background_automation = 1")
        s = cur.rowcount
        cur.execute("""DELETE FROM automation_runs WHERE automation_id IN
                       (SELECT id FROM automations WHERE deleted_at IS NOT NULL)""")
        r = cur.rowcount
        cur.execute("""DELETE FROM automation_runtime_state WHERE automation_id IN
                       (SELECT id FROM automations WHERE deleted_at IS NOT NULL)""")
        t = cur.rowcount
        cur.execute("DELETE FROM automations WHERE deleted_at IS NOT NULL")
        a = cur.rowcount
        con.commit()
        print(f"已删除：sessions {s} ｜ session_usage {u} ｜ automation_runs {r} ｜ "
              f"runtime_state {t} ｜ automations {a}")
    except Exception as e:
        con.rollback()
        raise SystemExit(f"⛔ 出错已回滚：{type(e).__name__} {e}")
    finally:
        con.close()

    # ---- 复核 ----
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    after = counts(con.cursor())
    con.close()
    print("\n改后：")
    for k, v in after.items():
        print(f"  {k:<24} {v}")

    ok = (after["automation_sessions"] == 0
          and after["automations_softdeleted"] == 0
          and after["user_sessions"] == before["user_sessions"])   # 🔴 用户会话必须一字不变
    print()
    print("✅ 复核通过：自动化会话已清空，用户会话数未变（%d）" % after["user_sessions"]
          if ok else "❌ 复核失败，请从备份回滚")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
