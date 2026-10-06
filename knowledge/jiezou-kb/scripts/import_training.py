#!/usr/bin/env python3
"""通用、可重跑、幂等的资料导入器。

把散落在各处的培训资料 / 产品资料导入知识库：
    - 毅冰外贸方法论（客户背调、开发信、LinkedIn、展会、SOP……）
    - JIEZOU 自家产品资料（规格表、证书、产品目录、配件、双语产品文章）

设计要点
1. **通用**：--source 可重复，目录递归；以后新增素材直接再跑一次即可。
2. **幂等**：以源文件 sha256 前 12 位作为「内容指纹」。改名能认出来，
   内容变了原地更新，新文件才新建；不需要状态文件（状态从条目本身推导）。
3. **不猜**：文件类型决定提取方式；提取不到文本就生成 stub 条目并记入
   training/未导入清单.md，说明原因——绝不编造内容。
4. **合规**：默认硬拒绝「不可发/内部」类路径（内部供货记录不得入库）；
   导入器**绝不**把原文里的第三方联系方式写进 `联系人` 字段。

用法：
    # 先看计划（不写任何东西）
    python3 scripts/import_training.py --source <目录> [--source <目录>...]

    # 确认后执行
    python3 scripts/import_training.py --source <目录> --apply --report
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import build_index
import kblib
import officedoc

# 默认硬拒绝路径关键词（内部/机密资料不得入库）
DEFAULT_DENY = ["不可发", "供货记录-内部", "内部资料-", "机密", "confidential"]

# 递归时直接跳过的目录名（虚拟环境、版本库、缓存等，避免扫进上万无关文件）
EXCLUDE_DIRS = {".venv", "venv", ".git", "node_modules", "__pycache__", ".obsidian",
                ".idea", ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache",
                "site-packages", ".cache"}

# 支持的文件类型
SUPPORTED_EXT = {".md", ".txt", ".docx", ".doc", ".pptx", ".xlsx", ".xlsm", ".pdf"}
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".svg",
             ".zip", ".rar", ".7z", ".mp4", ".mov", ".mp3", ".dwg"}

# 主题分类规则：首匹配生效。作用于「路径 + 标题 + 前 3000 字」
TOPIC_RULES = [
    ("客户背调", ["背调", "背景调查", "调研", "investigating", "13步", "工商", "sunbiz", "whois",
                  "尽职调查", "客户分析"]),
    ("开发信与邮件", ["开发信", "mail group", "邮件", "email", "函电", "话术", "跟进信", "cold mail",
                      "回信", "报价信"]),
    ("LinkedIn", ["linkedin", "领英", "社媒", "私信", "加好友", "人脉", "社交"]),
    ("展会", ["展会", "canton", "广交会", "展位", "exhibition", "trade show", "摊位"]),
    ("报价与谈判", ["报价", "谈判", "quotation", "议价", "成交技巧", "价格谈判", "付款方式"]),
    ("订单与出货SOP", ["sop", "出货", "样品单", "报关", "信用证", "单证", "验货", "接待",
                       "客户来访", "标准流程", "跟单"]),
    ("海关数据", ["海关", "提单", "b/l", "hs code", "进口商", "trademo", "importyeti", "52wmb",
                  "关单", "清关数据"]),
    ("市场与选品", ["选品", "市场调研", "目标市场", "行业大客户", "竞品", "市场信息"]),
    ("英语与函电", ["英语", "口语", "词汇", "地道", "口语表达", "english"]),
    ("产品知识", ["变压器", "transformer", "箱变", "干变", "油变", "套管", "bushing", "熔断器",
                  "fuse", "oltc", "bil", "铁芯", "core", "冷却", "cooling", "ifd", "elsp",
                  "法兰", "flange", "pad mount", "美变", "储能"]),
]
DEFAULT_TOPIC = "其他"

# 按路径判断实体类型：命中即归为「产品知识」，否则「培训资料」
PRODUCT_PATH_HINTS = ["产品知识细分", "技术参数", "specs", "证书", "certificat", "产品目录",
                      "培训资料", "变压器配件", "变压器bil", "产品图片", "产品目录"]

# 路径命中上面这些目录时，只允许这些主题——避免产品文档被误判成方法论
PRODUCT_ONLY_TOPICS = ["产品知识", "英语与函电"]

# 明显是「脚本生成的索引/清单」，导入进来毫无意义且会自引用
SKIP_STEMS = {"index", "00-index", "_index", "未导入清单", "知识地图"}

# 超过这个长度就把全文外置到 training/sources/，条目里只留指针
MAX_INLINE_CHARS = 60000

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-.]?)?(?:\(\d{2,4}\)[\s\-.]?)?\d{3,4}[\s\-.]?\d{3,4}[\s\-.]?\d{0,4}")

CONTACT_BANNER = ("> 以下原文含第三方联系方式，仅作培训素材存档，**非客户线索**，"
                  "不得据此直接外联；来源：原文文件。")


def normalize_title(title):
    """标题归一化，用于识别「同一份文档的不同副本」。"""
    s = re.sub(r"[\s　]+", "", str(title or ""))
    s = re.sub(r"[（(【\[].*?[)）】\]]", "", s)
    return s.lower()


def is_product_path(path):
    return any(h in str(path).lower() for h in PRODUCT_PATH_HINTS)


def classify_topic(path, title, text, overrides=None):
    # 归一化 blob：把 "+" "&" "_" "-" 视作分隔符，否则「Mail+Group」匹配不到「mail group」
    blob = f"{path} {title} {text[:3000]}".lower()
    blob = re.sub(r"[+&_\-/]", " ", blob)
    if overrides:
        for key, topic in overrides.items():
            if re.sub(r"[+&_\-/]", " ", key.lower()) in blob:
                return topic
    # 产品资料目录下的文档，只允许产品/术语类主题；
    # 否则「出货」「报价」这类词会把产品说明书误判成 SOP
    allowed = PRODUCT_ONLY_TOPICS if is_product_path(path) else None
    for topic, keywords in TOPIC_RULES:
        if allowed is not None and topic not in allowed:
            continue
        if any(kw in blob for kw in keywords):
            return topic
    return DEFAULT_TOPIC if allowed is None else allowed[0]


def classify_type(path):
    return "产品知识" if is_product_path(path) else "培训资料"


def fingerprint(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def extract(path, pdf_mode="auto"):
    """返回 (text, method, note, ok)。"""
    ext = path.suffix.lower()
    if ext in (".md", ".txt"):
        try:
            return path.read_text(encoding="utf-8", errors="replace"), "直接读取（UTF-8）", "", True
        except OSError as exc:
            return "", "读取失败", str(exc), False

    if ext == ".pdf" and pdf_mode == "skip":
        return "", "已跳过（--pdf skip）", "按参数跳过 PDF", False

    res = officedoc.extract(path)
    return res["text"], res["method"], res["note"], res["ok"]


def title_of(path, text):
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if m:
        t = kblib.get_frontmatter_field(text, "title")
        if t:
            return t
    for line in text.split("\n")[:60]:
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def summarize(text, topic, max_chars=220):
    """取正文里信息密度最高的一段作为摘要（跳过标题行与空行）。"""
    for para in re.split(r"\n\s*\n", text):
        p = " ".join(para.split())
        if len(p) < 40 or p.startswith("#") or p.startswith("---"):
            continue
        return p[:max_chars] + ("…" if len(p) > max_chars else "")
    # 兜底：PDF 常见「每行一句、无空行分段」的排版，把前若干非空行拼起来
    joined = " ".join(
        l.strip() for l in text.split("\n")
        if l.strip() and not l.strip().startswith(("#", "---", "<!--"))
    )
    if len(joined) >= 20:
        return joined[:max_chars] + ("…" if len(joined) > max_chars else "")
    return f"（{topic}）原文未提取到可读正文。"


def key_points(text, limit=8):
    """抓取看起来像要点/小标题的行。"""
    points = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if re.match(r"^#{2,4}\s+", s):
            points.append(re.sub(r"^#+\s*", "", s))
        elif re.match(r"^[-*•]\s+\S", s) and 8 <= len(s) <= 120:
            points.append(re.sub(r"^[-*•]\s*", "", s))
        elif re.match(r"^\d+[.、)]\s+\S", s) and 8 <= len(s) <= 120:
            points.append(s)
        if len(points) >= limit:
            break
    return points


def build_body(text, path, method, note, fp, topic, is_stub):
    lines = []
    lines.append("## 摘要")
    lines.append("")
    lines.append(summarize(text, topic) if not is_stub else f"（未提取到正文：{note}）")
    lines.append("")
    lines.append("## 核心要点")
    lines.append("")
    pts = key_points(text) if not is_stub else []
    if pts:
        lines += [f"- {p}" for p in pts]
    else:
        lines.append("- （待补全）")
    lines.append("")
    lines.append("## 适用场景")
    lines.append("")
    lines.append(f"- 主题：{topic}")
    lines.append(f"- 源文件：{path}")
    lines.append("")
    lines.append("## 原文存档")
    lines.append("")
    has_contacts = bool(EMAIL_RE.search(text) or PHONE_RE.search(text))
    if has_contacts:
        lines.append(CONTACT_BANNER)
        lines.append("")
    if not text.strip():
        lines.append(f"（空）{note}")
    elif len(text) <= MAX_INLINE_CHARS:
        lines.append(text.strip())
    else:
        lines.append(f"（全文 {len(text)} 字符，超过内联上限，已外置到 `training/sources/`）")
    lines.append("")
    lines.append("## 来源与提取说明")
    lines.append("")
    lines.append(f"- 源文件：`{path}`")
    lines.append(f"- 内容指纹：`sha256:{fp}`（源文件内容变化时会自动更新本条目）")
    lines.append(f"- 提取方式：{method}")
    if note:
        lines.append(f"- 备注：{note}")
    lines.append("")
    return "\n".join(lines), has_contacts


def split_body_sections(body):
    """把生成的正文拆成 [(小节名, 内容), ...]，便于按小节做外科手术式替换。"""
    out, current, buf = [], None, []
    for line in body.split("\n"):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current is not None:
                out.append((current, "\n".join(buf).strip("\n")))
            current, buf = m.group(1), []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        out.append((current, "\n".join(buf).strip("\n")))
    return out


def scan_sources(sources, deny, only_ext, limit):
    """遍历源，产出 (path, skipped_reason or None)。"""
    seen = set()
    out = []
    for src in sources:
        p = Path(src)
        if not p.exists():
            out.append((p, "源不存在"))
            continue
        files = [p] if p.is_file() else sorted(
            q for q in p.rglob("*") if q.is_file() and not (set(q.parts) & EXCLUDE_DIRS))
        for f in files:
            rp = str(f.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            low = str(f).lower()
            if set(f.parts) & EXCLUDE_DIRS:
                continue
            if any(d.lower() in low for d in deny):
                out.append((f, "命中禁入名单（内部/不可发）"))
                continue
            if only_ext and f.suffix.lower().lstrip(".") not in only_ext:
                out.append((f, f"扩展名不在 --only-ext 内（{f.suffix}）"))
                continue
            if f.suffix.lower() in MEDIA_EXT:
                out.append((f, f"媒体/压缩包，不做文本提取（{f.suffix}）"))
                continue
            if f.suffix.lower() not in SUPPORTED_EXT:
                out.append((f, f"不支持的格式（{f.suffix}）"))
                continue
            if f.stem.lower() in SKIP_STEMS:
                out.append((f, "脚本生成的索引/清单，无需导入"))
                continue
            if f.name.startswith(".") or f.name == ".DS_Store":
                out.append((f, "隐藏文件"))
                continue
            out.append((f, None))
            if limit and len([1 for _, r in out if r is None]) >= limit:
                return out
    return out


def main():
    ap = argparse.ArgumentParser(description="通用资料导入器（可重跑、幂等）")
    ap.add_argument("--source", action="append", required=True, help="源文件或目录（可重复）")
    ap.add_argument("--deny", action="append", default=[], help="额外禁入关键词（可重复）")
    ap.add_argument("--type", default="auto", choices=["auto", "培训资料", "产品知识"])
    ap.add_argument("--only-ext", default="", help="只处理这些扩展名，逗号分隔，如 docx,pdf")
    ap.add_argument("--pdf", default="auto", choices=["auto", "skip"], help="PDF 处理策略")
    ap.add_argument("--topic-override", action="append", default=[],
                    help="强制主题，形如 关键词=主题（可重复）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少个文件")
    ap.add_argument("--refresh", action="store_true", help="忽略内容指纹，全部重新提取")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="只打印计划（默认）")
    g.add_argument("--apply", action="store_true", help="实际写入")
    ap.add_argument("--report", action="store_true", help="生成 training/index.md 与未导入清单.md")
    args = ap.parse_args()

    deny = DEFAULT_DENY + list(args.deny)
    only_ext = {e.strip().lower() for e in args.only_ext.split(",") if e.strip()}
    overrides = {}
    for item in args.topic_override:
        if "=" in item:
            k, v = item.split("=", 1)
            overrides[k.strip()] = v.strip()

    scanned = scan_sources(args.source, deny, only_ext, args.limit)

    records = kblib.load_index()
    by_fp, by_src, by_title = {}, {}, {}
    for r in records:
        if r.get("type") not in ("培训资料", "产品知识"):
            continue
        text = (kblib.ROOT / r["path"]).read_text(encoding="utf-8")
        fp = kblib.get_frontmatter_field(text, "内容指纹")
        src = kblib.get_frontmatter_field(text, "原始文件")
        if fp:
            by_fp[fp] = r
        if src:
            by_src[src] = r
        # 同一份资料常同时存在于多个目录（如 毅冰课蒸馏/MD素材 与 毅冰-kb），
        # 内容可能有微小差异导致指纹不同。按「类型+标题」再兜一层，
        # 否则同一份文档会生成两条重名条目。
        by_title.setdefault((r["type"], normalize_title(r["name"])), r)

    today = date.today().isoformat()
    sources_dir = kblib.ROOT / "training" / "sources"
    stats = {"new": 0, "updated": 0, "unchanged": 0, "skipped": 0, "stub": 0}
    skipped_log, created_log = [], []

    for path, reason in scanned:
        if reason:
            stats["skipped"] += 1
            skipped_log.append((str(path), reason))
            continue

        try:
            fp = fingerprint(path)
        except OSError as exc:
            stats["skipped"] += 1
            skipped_log.append((str(path), f"读取失败：{exc}"))
            continue

        abs_path = str(path.resolve())
        entity_type = args.type if args.type != "auto" else classify_type(path)
        existing = (by_fp.get(fp) or by_src.get(abs_path)
                    or by_title.get((entity_type, normalize_title(path.stem))))
        if existing and not args.refresh and by_fp.get(fp):
            stats["unchanged"] += 1
            continue

        text, method, note, ok = extract(path, args.pdf)
        is_stub = not ok
        title = title_of(path, text) if text else path.stem
        topic = classify_topic(path, title, text, overrides)
        body, has_contacts = build_body(text, abs_path, method, note, fp, topic, is_stub)

        if is_stub:
            stats["stub"] += 1
        if existing:
            stats["updated"] += 1
            action = "UPDATE"
            entry_id = existing["id"]
            target = kblib.ROOT / existing["path"]
        else:
            stats["new"] += 1
            action = "CREATE"
            entry_id = kblib.next_id(records, kblib.load_schema(entity_type)["prefix"])
            records.append({"id": entry_id, "type": entity_type, "name": title,
                            "tags": [], "updated": today, "path": ""})
            name = kblib.safe_filename(title)[:80] or "未命名"
            target = kblib.ENTRIES_DIR / entity_type / f"{name}.md"
            if target.exists():
                target = kblib.ENTRIES_DIR / entity_type / f"{name}-{fp[:6]}.md"

        tags = [topic]
        if entity_type == "产品知识":
            tags.append("产品资料")
        if has_contacts:
            tags.append("含联系方式")
        if is_stub:
            tags.append("待补全")

        print(f"  {action:6} [{entity_type}] {topic:10} {title[:46]:46} → {entry_id}")
        if is_stub:
            print(f"         ↳ stub：{note}")
        created_log.append((entry_id, entity_type, topic, title, str(path), method, is_stub))

        # 把新条目登记进查找表。否则同一次运行里遇到同一份文档的第二个副本
        # （例如 毅冰课蒸馏/MD素材 与 毅冰-kb 各存一份）时找不到它，会重复建条目。
        stub_rec = {
            "id": entry_id, "type": entity_type, "name": title,
            "tags": tags, "updated": today,
            "path": target.relative_to(kblib.ROOT).as_posix() if target.is_absolute()
                    else str(target),
        }
        by_fp[fp] = stub_rec
        by_src[abs_path] = stub_rec
        by_title[(entity_type, normalize_title(title))] = stub_rec

        if not args.apply:
            continue

        if existing:
            cur = target.read_text(encoding="utf-8")
            prev_src = kblib.get_frontmatter_field(cur, "原始文件")
            updates = {
                "updated": today, "主题": topic,
                "文件类型": path.suffix.lower().lstrip("."), "内容指纹": fp,
                "核心要点": summarize(text, topic) if not is_stub else note,
            }
            if not prev_src:
                updates["原始文件"] = abs_path
            cur = kblib.upsert_frontmatter_fields(cur, updates)
            # 同一份资料的其他副本：只记一笔，不另建条目
            if prev_src and prev_src != abs_path:
                note_line = f"- 同一份资料的其他副本：`{abs_path}`"
                if note_line not in cur:
                    cur = kblib.append_under_heading(cur, "来源与提取说明", note_line)
            # 标签取并集，保留用户自己加过的
            old_tags = []
            m_fm = re.match(r"\A---\s*\n(.*?)\n---", cur, re.DOTALL)
            if m_fm:
                for line in m_fm.group(1).split("\n"):
                    if line.startswith("tags:"):
                        try:
                            old_tags = json.loads(line.split(":", 1)[1].strip() or "[]")
                        except ValueError:
                            old_tags = []
                        break
            merged = list(dict.fromkeys([t for t in old_tags if t] + tags))
            cur = kblib.set_frontmatter_raw(cur, "tags", json.dumps(merged, ensure_ascii=False))
            # 只替换「生成型」小节，保留用户自己写的内容
            for heading, content in split_body_sections(body):
                cur = kblib.replace_section(cur, heading, content)
            target.write_text(cur, encoding="utf-8")
        else:
            fm = {
                "id": entry_id, "type": entity_type, "name": title,
                "created": today, "updated": today, "tags": tags, "related": [],
                "source": f"{abs_path}（sha256:{fp}，{today} 导入）",
                "主题": topic, "原始文件": abs_path,
                "文件类型": path.suffix.lower().lstrip("."),
                "核心要点": summarize(text, topic) if not is_stub else note,
                "适用场景": f"主题「{topic}」下的参考资料；原文见本条目「原文存档」。",
                "内容指纹": fp,
            }
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(kblib.dump_frontmatter(fm, body), encoding="utf-8")

            if len(text) > MAX_INLINE_CHARS:
                sources_dir.mkdir(parents=True, exist_ok=True)
                (sources_dir / f"{kblib.safe_filename(title)[:60]}-{fp}.md").write_text(
                    text, encoding="utf-8")

    print(f"\n{'已写入' if args.apply else '计划（未写入）'}："
          f"新增 {stats['new']}，更新 {stats['updated']}，"
          f"未变化 {stats['unchanged']}，跳过 {stats['skipped']}，其中 stub {stats['stub']}")

    if not args.apply:
        print("确认无误后加 --apply 执行。")
        return 0

    # 必须先重建索引，报告才有数据可读
    build_index.main()
    if args.report:
        write_reports(created_log, skipped_log, stats)
        print("报告：training/index.md、training/未导入清单.md")
    return 0


def write_reports(created_log, skipped_log, stats):
    """生成 training/index.md（按主题分组）与 training/未导入清单.md。"""
    training_dir = kblib.ROOT / "training"
    training_dir.mkdir(parents=True, exist_ok=True)

    records = kblib.load_index()
    groups = {}
    for r in records:
        if r.get("type") not in ("培训资料", "产品知识"):
            continue
        text = (kblib.ROOT / r["path"]).read_text(encoding="utf-8")
        topic = kblib.get_frontmatter_field(text, "主题") or DEFAULT_TOPIC
        groups.setdefault(topic, []).append((r, text))

    lines = [
        "# 培训与产品资料索引",
        "",
        "> 本文件由 `scripts/import_training.py --report` 生成，请勿手改。",
        f"> 生成日期：{date.today().isoformat()} · 共 {sum(len(v) for v in groups.values())} 条",
        "> 真源是 `entries/培训资料/` 与 `entries/产品知识/`；本文件只是人看的视图。",
        "",
    ]
    for topic in sorted(groups):
        items = sorted(groups[topic], key=lambda x: x[0]["name"])
        lines.append(f"## {topic}（{len(items)}）")
        lines.append("")
        for r, text in items:
            core = kblib.get_frontmatter_field(text, "核心要点") or ""
            stub = "（待补全）" if "待补全" in (r.get("tags") or []) else ""
            lines.append(f"- **{r['name']}** `{r['id']}`{stub} — {core[:110]}")
        lines.append("")
    (training_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")

    if skipped_log:
        out = ["# 未导入清单", "",
               "> 由 `scripts/import_training.py --report` 生成。列出每个没进知识库的文件及原因。", ""]
        reasons = {}
        for path, reason in skipped_log:
            reasons.setdefault(reason, []).append(path)
        for reason in sorted(reasons):
            out.append(f"## {reason}（{len(reasons[reason])}）")
            out.append("")
            for p in sorted(reasons[reason]):
                out.append(f"- `{p}`")
            out.append("")
        (training_dir / "未导入清单.md").write_text("\n".join(out), encoding="utf-8")
    else:
        (training_dir / "未导入清单.md").write_text(
            "# 未导入清单\n\n> 本次运行没有文件被跳过。\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
