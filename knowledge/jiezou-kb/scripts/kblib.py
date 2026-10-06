#!/usr/bin/env python3
"""知识库公共工具：路径定位、frontmatter 解析/生成、条目扫描与 id 分配。

被 new_entry.py / build_index.py / search.py 共用，不单独运行。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES_DIR = ROOT / "entries"
SCHEMA_DIR = ROOT / "schema"
INDEX_PATH = ROOT / "index" / "index.json"

# 所有类型共享的通用字段（schema/*.json 只需再定义专属字段）
COMMON_FIELDS = ["id", "type", "name", "created", "updated", "tags", "related", "source"]


# ---------- YAML：优先用 pyyaml，未安装时回退到内置极简解析器 ----------

def load_yaml(text):
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        return _parse_simple_yaml(text)


def dump_yaml(data):
    try:
        import yaml
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    except ImportError:
        return _dump_simple_yaml(data)


def _scalar(s):
    """去掉包裹的引号，并把引号里的转义还原。

    双引号值按 JSON 字符串解析（JSON 转义是 YAML 双引号转义的子集）；
    单引号值按 YAML 规则把 '' 还原成 '。
    不做还原的话，「读出来再写回去」会把反斜杠越转义越多。
    """
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        try:
            return json.loads(s)
        except ValueError:
            return s[1:-1]
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


def _parse_simple_yaml(text):
    """极简 YAML 解析：只覆盖本知识库用到的形态（扁平 key: value、[]、flow 列表、块列表）。"""
    data = {}
    current_list_key = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_list_key is not None:
                data[current_list_key].append(_scalar(stripped[1:]))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        current_list_key = None
        if value in ("", "[]"):
            # 空值先按空列表处理；若后续出现 "- item" 行会填充进去
            data[key] = []
            if value == "":
                current_list_key = key
            continue
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                data[key] = []
            else:
                try:
                    data[key] = json.loads(value)
                except ValueError:
                    data[key] = [_scalar(p) for p in inner.split(",")]
            continue
        data[key] = _scalar(value)
    return data


def _dump_simple_yaml(data):
    lines = []
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}" if value else f"{key}: []")
        elif value is None or value == "":
            lines.append(f'{key}: ""')
        else:
            lines.append(f"{key}: {quote_scalar(value)}")
    return "\n".join(lines) + "\n"


# ---------- frontmatter ----------

def parse_frontmatter(text):
    """返回 (frontmatter_dict, body)。没有合法 frontmatter 时返回 ({}, 原文)。"""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not m:
        return {}, text
    return load_yaml(m.group(1)), text[m.end():]


def dump_frontmatter(data, body):
    return f"---\n{dump_yaml(data)}---\n\n{body.lstrip(chr(10))}"


# ---------- 严格 YAML 标量 & 外科手术式 frontmatter 编辑 ----------
#
# 背景：本库有 7 个条目的 frontmatter 值里含未加引号的 ": "（如「（B/L: XXX）」），
# 内置宽松解析器能容忍，但严格 YAML（pyyaml）会直接报错。
# 因此：
#   1) 新写入的值一律经 quote_scalar() 转义；
#   2) 修改已有条目一律走 set_frontmatter_field()（只换那一行），
#      绝不调用 dump_frontmatter() 整体重写——内置 dumper 只支持扁平结构，
#      整体重写会破坏手工写的内容。

_YAML_SPECIAL_START = "-?:,[]{}#&*!|>'\"%@`"
_YAML_RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "none", "~"}
# 控制字符（保留换行与制表）会让 YAML 直接报 "special characters are not allowed"
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _looks_numeric(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def quote_scalar(value):
    """把标量转成严格 YAML 合法的字符串表示（需要时加双引号）。"""
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if s == "":
        return '""'

    need_quote = (
        s != s.strip()                      # 首尾空白
        or "\n" in s or "\r" in s or "\t" in s
        or _CONTROL_RE.search(s)            # 控制字符：必须转义
        or ": " in s                        # 值里再出现 ": " 会破坏解析
        or s.endswith(":")
        or " #" in s                        # 行内注释起始
        or s[0] in _YAML_SPECIAL_START
        or s.lower() in _YAML_RESERVED
        or _looks_numeric(s)                # 想当字符串就别被读成数字
    )
    if not need_quote:
        return s
    # JSON 字符串是 YAML 双引号标量的子集，转义规则完全兼容
    return json.dumps(s, ensure_ascii=False)


def _frontmatter_block(lines):
    """返回 (开分隔符下标, 闭分隔符下标)；没有合法 frontmatter 时返回 None。"""
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return 0, i
    return None


def get_frontmatter_field(text, key):
    """读取 frontmatter 中 key 的原始值（自动去引号）；不存在返回 ""。"""
    lines = text.split("\n")
    block = _frontmatter_block(lines)
    if not block:
        return ""
    for line in lines[block[0] + 1:block[1]]:
        k, sep, v = line.partition(":")
        if sep and k.strip() == key:
            return _scalar(v)
    return ""


def set_frontmatter_field(text, key, value):
    """替换 frontmatter 中 key 那一行；不存在则插在闭分隔符之前。

    除该行外，其余字节（包括正文、注释、空行、原有缩进）原样保留。
    """
    return _set_frontmatter_line(text, key, f"{key}: {quote_scalar(value)}")


def set_frontmatter_raw(text, key, raw_value):
    """同 set_frontmatter_field，但值原样写入（用于列表等已序列化好的值）。"""
    return _set_frontmatter_line(text, key, f"{key}: {raw_value}")


def _set_frontmatter_line(text, key, new_line):
    lines = text.split("\n")
    block = _frontmatter_block(lines)
    if not block:
        raise ValueError("文本没有合法的 frontmatter 块（首行须为 ---）")
    open_idx, close_idx = block
    for i in range(open_idx + 1, close_idx):
        k, sep, _ = lines[i].partition(":")
        if sep and k.strip() == key:
            lines[i] = new_line
            return "\n".join(lines)
    lines.insert(close_idx, new_line)
    return "\n".join(lines)


def upsert_frontmatter_fields(text, updates):
    """按 dict 顺序对多个字段执行 set_frontmatter_field。"""
    for key, value in updates.items():
        text = set_frontmatter_field(text, key, value)
    return text


def append_under_heading(text, heading, line):
    """在 `## <heading>` 小节末尾追加一行；该小节不存在则在文末新建。"""
    lines = text.split("\n")
    target = f"## {heading}".strip()

    start = None
    for i, l in enumerate(lines):
        if l.strip() == target:
            start = i
            break

    if start is None:
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines.extend(["", target, "", line, ""])
        return "\n".join(lines)

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break

    ins = end
    while ins - 1 > start and lines[ins - 1].strip() == "":
        ins -= 1
    lines.insert(ins, line)
    return "\n".join(lines)


def safe_filename(name):
    """去掉文件名里不允许的字符。"""
    for ch in '/\\:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip() or "未命名"


def replace_section(text, heading, new_body):
    """把 `## <heading>` 小节的正文整体替换为 new_body；小节不存在则在文末新建。

    用于刷新「生成型」条目（如培训资料）的正文段落，同时不动 frontmatter
    和用户自己加的其他小节。
    """
    lines = text.split("\n")
    target = f"## {heading}".strip()
    new_lines = new_body.split("\n") if isinstance(new_body, str) else list(new_body)
    while new_lines and new_lines[-1].strip() == "":
        new_lines.pop()

    start = None
    for i, l in enumerate(lines):
        if l.strip() == target:
            start = i
            break

    if start is None:
        while lines and lines[-1].strip() == "":
            lines.pop()
        lines.extend([""] + [target, ""] + new_lines + [""])
        return "\n".join(lines)

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break

    lines[start:end] = [target, ""] + new_lines + [""]
    return "\n".join(lines)


# ---------- 索引与条目 ----------

def scan_entries():
    """扫描 entries/ 下全部 .md，解析 frontmatter，生成索引记录列表。"""
    records = []
    if not ENTRIES_DIR.exists():
        return records
    for md in sorted(ENTRIES_DIR.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"[警告] 无法读取 {md.name}：{exc}", file=sys.stderr)
            continue
        fm, _ = parse_frontmatter(text)
        if not fm.get("id"):
            print(f"[警告] 跳过缺少 frontmatter 或 id 的文件：{md.relative_to(ROOT).as_posix()}", file=sys.stderr)
            continue
        records.append({
            "id": str(fm.get("id", "")),
            "type": str(fm.get("type", "")),
            "name": str(fm.get("name", "")),
            "tags": list(fm.get("tags") or []),
            "updated": str(fm.get("updated", "")),
            "path": md.relative_to(ROOT).as_posix(),
        })
    return records


def load_index():
    """优先读 index/index.json；不存在时现场扫描。"""
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return scan_entries()


def next_id(records, prefix):
    """基于同前缀 id 的最大序号 +1，生成形如 jzd-001 的新 id。"""
    pattern = re.compile(rf"\A{re.escape(prefix)}-(\d+)\Z")
    nums = [int(m.group(1)) for r in records if (m := pattern.match(str(r.get("id", ""))))]
    return f"{prefix}-{max(nums, default=0) + 1:03d}"


def load_schema(entity_type):
    """读取 schema/<类型>.json；不存在返回 None。"""
    path = SCHEMA_DIR / f"{entity_type}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def available_types():
    return sorted(p.stem for p in SCHEMA_DIR.glob("*.json"))
