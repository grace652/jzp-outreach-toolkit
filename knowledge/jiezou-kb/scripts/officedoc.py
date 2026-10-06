#!/usr/bin/env python3
"""标准库优先的文档文本提取：docx / pptx / xlsx / doc / pdf。

设计原则：脚本本身零依赖即可运行。
- docx / pptx / xlsx：纯标准库（zipfile + xml.etree）
- doc（老式 OLE）：调用 macOS 自带的 textutil
- pdf：优先进程内 import pypdf；没有就试隔离 venv 的解释器；都没有则只报页数
  （可用环境变量 JIEZOU_KB_PYTHON 指定带 pypdf 的解释器）

用法：
    python3 scripts/officedoc.py <文件或目录> [...]     # 提取并预览
    python3 scripts/officedoc.py --selftest             # 对内置样本自测
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# 带 pypdf 的候选解释器（用于 PDF 提取的子进程回退）
VENV_PYTHONS = [
    os.environ.get("JIEZOU_KB_PYTHON", ""),
    "/Users/eric/.workbuddy-ai/binaries/python/envs/default/bin/python",
]

PDF_HELPER = r'''
import sys
try:
    from pypdf import PdfReader
except ImportError:
    sys.exit(3)
reader = PdfReader(sys.argv[1])
parts = []
for i, page in enumerate(reader.pages, 1):
    try:
        t = page.extract_text() or ""
    except Exception:
        t = ""
    if t.strip():
        parts.append("--- 第 %d 页 ---\n%s" % (i, t))
sys.stdout.write("\n\n".join(parts))
'''


def _local(tag):
    """去掉 XML 命名空间，只留本地名。"""
    return tag.rsplit("}", 1)[-1]


# ---------- docx ----------

def read_docx(path):
    """提取 word/document.xml 的段落文本。"""
    with zipfile.ZipFile(path) as z:
        if "word/document.xml" not in z.namelist():
            raise ValueError("不是有效的 docx（缺 word/document.xml）")
        root = ET.fromstring(z.read("word/document.xml"))

    parents = {child: parent for parent in root.iter() for child in parent}
    out = []
    for para in root.iter():
        if _local(para.tag) != "p":
            continue
        # 跳过嵌套在别的 w:p 里的段落（文本框），避免重复输出
        anc, nested = parents.get(para), False
        while anc is not None:
            if _local(anc.tag) == "p":
                nested = True
                break
            anc = parents.get(anc)
        if nested:
            continue
        buf = []
        for node in para.iter():
            ln = _local(node.tag)
            if ln == "t":
                buf.append(node.text or "")
            elif ln == "tab":
                buf.append("\t")
            elif ln in ("br", "cr"):
                buf.append("\n")
        out.append("".join(buf))
    return "\n".join(out)


# ---------- pptx ----------

def read_pptx(path):
    """提取每页幻灯片文本，返回 (文本, 页数)。纯图片页会得到空文本。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        slides = [n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        if not slides:
            raise ValueError("不是有效的 pptx（找不到 ppt/slides/*.xml）")
        slides.sort(key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
        parts = []
        for i, name in enumerate(slides, 1):
            root = ET.fromstring(z.read(name))
            texts = [(n.text or "") for n in root.iter() if _local(n.tag) == "t"]
            body = " ".join(t.strip() for t in texts if t.strip())
            if body:
                parts.append(f"--- 第 {i} 页 ---\n{body}")
        return "\n\n".join(parts), len(slides)


# ---------- xlsx ----------

def _col_index(ref):
    m = re.match(r"([A-Z]+)", (ref or "").upper())
    if not m:
        return 0
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _cell_text(cell, shared):
    ctype = cell.get("t")
    if ctype == "s":
        v = next((x.text for x in cell if _local(x.tag) == "v"), None)
        try:
            return shared[int(v)]
        except (TypeError, ValueError, IndexError):
            return ""
    if ctype == "inlineStr":
        return "".join(x.text or "" for x in cell.iter() if _local(x.tag) == "t")
    v = next((x.text for x in cell if _local(x.tag) == "v"), None)
    return v or ""


def read_xlsx_rows(path, max_rows=0):
    """读取全部工作表，返回 {表名: [[单元格, ...], ...]}。max_rows>0 时每表截断。"""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())

        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.iter():
                if _local(si.tag) == "si":
                    shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))

        # 表名与顺序
        sheet_meta = []
        if "xl/workbook.xml" in names:
            rels = {}
            if "xl/_rels/workbook.xml.rels" in names:
                rr = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
                for r in rr:
                    rels[r.get("Id")] = r.get("Target", "")
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            for sh in wb.iter():
                if _local(sh.tag) != "sheet":
                    continue
                rid = next((v for k, v in sh.attrib.items() if _local(k) == "id"), None)
                target = rels.get(rid, "")
                target = target.lstrip("/")
                if target and not target.startswith("xl/"):
                    target = "xl/" + target
                sheet_meta.append((sh.get("name") or "", target))

        if not sheet_meta:
            found = sorted(
                (n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)),
            )
            sheet_meta = [(f"Sheet{i}", n) for i, n in enumerate(found, 1)]

        result = {}
        for name, target in sheet_meta:
            if target not in names:
                continue
            root = ET.fromstring(z.read(target))
            rows = []
            for row in root.iter():
                if _local(row.tag) != "row":
                    continue
                cells = {}
                for cell in row:
                    if _local(cell.tag) != "c":
                        continue
                    cells[_col_index(cell.get("r"))] = _cell_text(cell, shared)
                width = (max(cells) + 1) if cells else 0
                rows.append([cells.get(i, "") for i in range(width)])
                if max_rows and len(rows) >= max_rows:
                    break
            result[name] = rows
        return result


# ---------- doc（老式 OLE） ----------

def read_doc(path):
    """用 macOS 自带 textutil 转换老式 .doc。"""
    if not shutil.which("textutil"):
        return "", "textutil 不可用（非 macOS？）"
    try:
        proc = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", f"textutil 调用失败：{exc}"
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()[:200]
        return "", f"textutil 返回 {proc.returncode}：{err}"
    return proc.stdout.decode("utf-8", "replace"), "textutil -convert txt"


# ---------- pdf ----------

def _pdf_page_count(path):
    """只用标准库粗数 /Type /Page 出现次数，用于判断是否扫描件。"""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return 0
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


# ---------- PDF 文本清理 ----------
# 不少中文 PDF 用逐字定位排版，抽出来会变成「注 册 领 英 第 一 步」这种。
# 下面是两个安全的修补：中文字符之间的空格一定可以去掉；
# 而拉丁文只有在整篇明显被逐字拆开时才动手，避免误伤正常英文。

_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff"
_CJK_SPACE_RE = re.compile(rf"(?<=[{_CJK}])[ \t]+(?=[{_CJK}])")
_CJK_PUNCT_SPACE_RE = re.compile(rf"(?<=[{_CJK}])[ \t]+(?=[，。、；：？！（）《》「」【】…—])")
_SINGLE_CHAR_SPACE_RE = re.compile(r"(?<=\b\w) (?=\w\b)")
# 控制字符（保留换行与制表）：PDF 提取偶尔会带出 \x00-\x1f 里的杂字符，
# 它们会让 frontmatter 变成非法 YAML。
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _looks_letter_spaced(text):
    tokens = text.split()
    if len(tokens) < 60:
        return False
    singles = sum(1 for t in tokens if len(t) == 1)
    return singles / len(tokens) > 0.35


def clean_pdf_text(text):
    """修补 PDF 逐字排版造成的异常空格，并去掉控制字符。"""
    if not text:
        return text
    out = _CONTROL_RE.sub("", text)
    out = _CJK_SPACE_RE.sub("", out)
    out = _CJK_PUNCT_SPACE_RE.sub("", out)
    if _looks_letter_spaced(out):
        out = _SINGLE_CHAR_SPACE_RE.sub("", out)
    return re.sub(r"[ \t]{3,}", "  ", out)


def read_pdf(path):
    """返回 (文本, 方法说明)。优先进程内 pypdf，其次隔离 venv 子进程。"""
    try:
        import pypdf  # noqa: F401

        from pypdf import PdfReader
        reader = PdfReader(str(path))
        parts = []
        for i, page in enumerate(reader.pages, 1):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t.strip():
                parts.append(f"--- 第 {i} 页 ---\n{t}")
        return clean_pdf_text("\n\n".join(parts)), f"pypdf {getattr(pypdf, '__version__', '')}（进程内）"
    except ImportError:
        pass

    for py in VENV_PYTHONS:
        if py and Path(py).exists():
            try:
                proc = subprocess.run(
                    [py, "-c", PDF_HELPER, str(path)],
                    capture_output=True, timeout=600,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if proc.returncode == 0:
                return clean_pdf_text(proc.stdout.decode("utf-8", "replace")), f"pypdf（{py}）"
            if proc.returncode == 3:
                break  # 该解释器也没有 pypdf

    pages = _pdf_page_count(path)
    return "", f"无 pypdf 可用；标准库探测到约 {pages} 页"


# ---------- 统一入口 ----------

def extract(path):
    """返回 dict：ok / kind / text / method / note / slides / sheets。"""
    path = Path(path)
    ext = path.suffix.lower()
    res = {"ok": False, "kind": ext.lstrip("."), "text": "", "method": "", "note": ""}

    try:
        if ext == ".docx":
            res["text"] = read_docx(path)
            res["method"] = "stdlib zipfile → word/document.xml"
        elif ext == ".pptx":
            text, n = read_pptx(path)
            res["text"], res["slides"] = text, n
            res["method"] = f"stdlib zipfile → ppt/slides/*.xml（{n} 页）"
        elif ext == ".xlsx":
            sheets = read_xlsx_rows(path)
            res["sheets"] = sheets
            res["method"] = "stdlib zipfile → xl/worksheets/*.xml"
            res["text"] = "\n".join(
                f"### {name}\n" + "\n".join(" | ".join(c for c in row) for row in rows)
                for name, rows in sheets.items()
            )
        elif ext == ".doc":
            res["text"], note = read_doc(path)
            res["method"] = "textutil -convert txt"
            if not res["text"]:
                res["note"] = note
        elif ext == ".pdf":
            res["text"], note = read_pdf(path)
            res["method"] = note
        else:
            res["note"] = f"不支持的扩展名 {ext}"
            return res
    except (zipfile.BadZipFile, ET.ParseError, ValueError, OSError) as exc:
        res["note"] = f"解析失败：{type(exc).__name__}: {exc}"
        return res

    res["ok"] = bool(res["text"].strip())
    if not res["ok"] and not res["note"]:
        res["note"] = "提取到 0 个字符（可能是纯图片/扫描件）"
    return res


# ---------- 自测 ----------

SELFTEST_DIRS = [
    Path("/Users/eric/Downloads/资料/产品知识细分"),
    Path("/Users/eric/Downloads/资料/技术参数 Specs"),
    Path("/Users/eric/Documents/毅冰课蒸馏/P1方法论库-上传包未完成"),
]


def selftest():
    targets = []
    for d in SELFTEST_DIRS:
        if d.is_dir():
            targets += [p for p in sorted(d.rglob("*")) if p.suffix.lower() in
                        (".docx", ".xlsx", ".pptx", ".doc", ".pdf")]
    if not targets:
        print("找不到自测样本目录")
        return 1

    by_kind = {}
    ok = 0
    for p in targets:
        r = extract(p)
        by_kind.setdefault(r["kind"], [0, 0])
        by_kind[r["kind"]][1] += 1
        if r["ok"]:
            by_kind[r["kind"]][0] += 1
            ok += 1
        flag = "ok  " if r["ok"] else "MISS"
        extra = ""
        if r["kind"] == "pptx":
            extra = f" slides={r.get('slides')}"
        if r["kind"] == "xlsx":
            extra = f" sheets={list((r.get('sheets') or {}).keys())}"
        print(f"  {flag} [{r['kind']:4}] {len(r['text']):>8} 字符{extra}  {p.name}")
        if not r["ok"]:
            print(f"        note: {r['note']}")

    print(f"\n按类型统计：")
    for kind, (good, total) in sorted(by_kind.items()):
        print(f"  {kind:5} {good}/{total} 提取到文本")
    print(f"合计 {ok}/{len(targets)} 个文件提取成功")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="标准库优先的文档文本提取")
    ap.add_argument("paths", nargs="*", help="文件或目录")
    ap.add_argument("--selftest", action="store_true", help="对内置样本目录自测")
    ap.add_argument("--chars", type=int, default=300, help="每个文件预览多少字符")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    targets = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            targets += [q for q in sorted(p.rglob("*")) if q.is_file()]
        elif p.exists():
            targets.append(p)
        else:
            print(f"[跳过] 不存在：{p}", file=sys.stderr)

    for p in targets:
        r = extract(p)
        print(f"\n=== {p.name} ===")
        print(f"  类型={r['kind']} ok={r['ok']} 长度={len(r['text'])} 方法={r['method']}")
        if r["note"]:
            print(f"  备注={r['note']}")
        if r["text"]:
            print("  ---")
            print("  " + r["text"][: args.chars].replace("\n", "\n  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
