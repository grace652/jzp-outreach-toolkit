#!/bin/bash
# ---------------------------------------------------------------
# 项目脚本运行包装器
#
# 为什么需要它：项目里 18 个核心脚本（定时发送 / 发送开发信 / 扫描回复 /
# 扫描退信 / 邮箱客户端 …）是靠「当前工作目录」定位文件的，必须在
# projects/jzp-americas-dev 目录下运行。本脚本先切到该目录再执行，
# 这样无论你在仓库的哪一层调用都不会找不到文件。
#
# 用法（在任意位置调用，路径写相对 jzp-americas-dev 的即可）：
#   ./run.sh 发送层自检.py
#   ./run.sh 扫描回复.py --days 14
#   ./run.sh scripts/构建跟进队列.py --build
# ---------------------------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$HERE/projects/jzp-americas-dev"

if [ ! -d "$TARGET" ]; then
  echo "找不到项目目录：$TARGET" >&2
  exit 1
fi

cd "$TARGET" || exit 1

PY="$(command -v python3)"
if [ -z "$PY" ]; then
  echo "系统里没有 python3" >&2
  exit 1
fi

exec "$PY" "$@"
