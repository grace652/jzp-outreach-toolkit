#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业数据抓取器 —— 纯 stdlib 实现

设计要点
--------
1. 零外部依赖：本机 Python 环境只有 yaml + openpyxl，故只用 urllib + xml.etree
2. 写入安全：排他锁 + os.replace 原子替换 + 时间戳备份
   （项目历史发生过「并发写同一文件互相覆盖」事故）
3. 每条数据必须有出处：缺 source_url 或 published_at 的条目直接丢弃
4. 遵守 04_do_not_say.md：quote_ready_en 必须通过禁语 lint
5. 交期/价格类条目自动降级为「不可用于跟进信」

用法
----
  python3 抓取行业数据.py                      # 全量抓取
  python3 抓取行业数据.py --dry-run             # 只看会写什么，不落盘
  python3 抓取行业数据.py --source utilitydive  # 只抓指定源
  python3 抓取行业数据.py --category market_supply
  python3 抓取行业数据.py --render-only         # 只重渲 md 索引
  python3 抓取行业数据.py --no-network          # 离线，只用缓存渲染
  python3 抓取行业数据.py --list-sources
  python3 抓取行业数据.py --pick --geo CA --buyer EPC --product distribution
"""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # 行业数据/
SRC_FILE = ROOT / "抓取" / "来源清单.json"
STATE_FILE = ROOT / "抓取" / "state.json"
LOCK_FILE = ROOT / "抓取" / ".lock"
STORE_FILE = ROOT / "数据" / "industry_news.json"
INDEX_FILE = ROOT / "出口" / "行业数据索引.md"

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BOT_UA = "jzp-industry-data/1.0 (+contact: {{SENDER_EMAIL}})"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml, application/json, text/xml, */*"
BJ = timezone(timedelta(hours=8))

CATEGORY_LABEL = {
    "market_supply": "市场与供应链行情",
    "standards_cert": "标准与认证动态",
    "customer_activity": "客户业务动态",
    "competitor": "竞品与同行动态",
}
CRED_LABEL = {"A": "一手", "B": "行业媒体", "C": "聚合"}

# ---------------------------------------------------------------- 禁语 lint

BANNED_PATTERNS = [
    (r"\bCSA\s+Certified\b", "禁：CSA Certified（我方无此证书）"),
    (r"\bSASO\s+Certified\b", "禁：SASO Certified（未持有）"),
    (r"\bSONCAP\s+Certified\b", "禁：SONCAP Certified（未持有）"),
    (r"\bYAWEI\b", "禁：YAWEI（同行品牌，全篇禁用）"),
    (r"\bfree\b", "spam 词：free"),
    (r"\bdiscount\b", "spam 词：discount"),
    (r"\bbest price\b", "spam 词：best price"),
    (r"\blimited time\b", "spam 词：limited time"),
    (r"\bguarantee\b", "spam 词：guarantee"),
    (r"100\s*%", "spam 词：100%"),
    (r"!!!", "spam 词：!!!"),
]
BANNED_RE = [(re.compile(p, re.I), msg) for p, msg in BANNED_PATTERNS]

LEADTIME_PRICE_RE = re.compile(
    r"lead\s*time|delivery\s+(time|window)|backlog|\bweeks?\b|\bmonths?\b|"
    r"\bprice|\bpricing|\bcost|\bquote[sd]?\b|\bUSD\b|\b\$", re.I)

# 全站类 feed（Utility Dive / DCD / EIA 等）必须过相关性闸门，
# 否则会带进大量与变压器业务无关的新闻（实测：286 条里过半无关）
RELEVANCE_RE = re.compile(
    r"transformer|substation|switchgear|breaker|"
    r"\bgrid\b|\bgrids\b|transmission|"
    r"utility|utilities|co-?op|interconnect|"
    r"electric(al)? (grid|infrastructure|equipment|utility|system)|"
    r"power (grid|transmission|distribution|delivery|supply)|"
    r"\bkVA\b|\bMVA\b|\bkV\b|volt|"
    r"capacit(y|ies) (market|constraint|shortage)|load growth|"
    r"data cent(er|re)|hyperscal|"
    r"energy conservation standard|efficiency standard|"
    r"FERC|NERC|PJM|MISO|ERCOT|ISO-?NE|"
    r"DOE\b|Department of Energy",
    re.I)

# 严过滤：用于专业垂直媒体（如 Data Center Dynamics）——
# 这类源几乎所有标题都含 "data center"，宽规则形同虚设
RELEVANCE_STRICT_RE = re.compile(
    r"transformer|substation|switchgear|\bkVA\b|\bMVA\b|\bkV\b|"
    r"grid (equipment|hardware|infrastructure|constraint|bottleneck|"
    r"capacity|connection|interconnect|upgrade)|"
    r"power (equipment|hardware|supply chain|distribution)|"
    r"interconnect(ion)? (queue|delay|wait|study)|"
    r"electrical (equipment|infrastructure)",
    re.I)


def relevance_ok(source, title):
    """按源配置的严格程度判断标题相关性。"""
    if not source.get("relevance_filter"):
        return True
    rx = RELEVANCE_STRICT_RE if source.get("relevance_level") == "strict" else RELEVANCE_RE
    return bool(rx.search(title))


def lint_quote(text):
    """返回 (ok, issues)。仅用于 quote_ready_en。"""
    issues = [msg for rx, msg in BANNED_RE if rx.search(text)]
    return (not issues), issues


# ---------------------------------------------------------------- 工具

def now_bj():
    return datetime.now(BJ)


def today_str():
    return now_bj().strftime("%Y-%m-%d")


def clean_html(raw):
    if not raw:
        return ""
    txt = re.sub(r"<[^>]+>", " ", str(raw))
    txt = html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def parse_date_any(s):
    """尽最大努力解析日期，返回 YYYY-MM-DD 或 None。"""
    if not s:
        return None
    s = str(s).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", s):
        return s[:10]
    try:
        return parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        pass
    for fmt in ("%Y/%m/%d", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def canonical_url(u):
    if not u:
        return ""
    try:
        p = urllib.parse.urlsplit(u.strip())
        q = urllib.parse.parse_qsl(p.query)
        q = [(k, v) for k, v in q if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
        return urllib.parse.urlunsplit(
            (p.scheme, p.netloc.lower(), p.path.rstrip("/"), urllib.parse.urlencode(q), ""))
    except Exception:
        return u.strip()


def entry_id(source_id, url):
    return hashlib.sha1(f"{source_id}|{canonical_url(url)}".encode("utf-8")).hexdigest()[:16]


def norm_title(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


# ---------------------------------------------------------------- 切片/标签推断

GEO_US = re.compile(r"\bU\.?S\.?\b|United States|American|\bEIA\b|\bDOE\b|FERC|"
                    r"Texas|California|New York|PJM|MISO|ERCOT", re.I)
GEO_CA = re.compile(r"Canada|Canadian|Ontario|Alberta|Quebec|British Columbia|"
                    r"Hydro One|BC Hydro|IESO", re.I)
BUYER_MAP = [
    ("utility", re.compile(r"utilit(y|ies)|co-?op|municipal(ly)? owned|investor-owned", re.I)),
    ("EPC", re.compile(r"\bEPC\b|engineering,? procurement|design-build|substation (builder|contractor)", re.I)),
    ("distributor", re.compile(r"distributor|supply house|wholesale|electrical supply", re.I)),
    ("datacenter", re.compile(r"data cent(er|re)|hyperscal", re.I)),
]
PRODUCT_MAP = [
    ("distribution", re.compile(r"distribution transformer|pad-?mount|pole-?mount|"
                                r"service transformer|kVA\b", re.I)),
    ("power", re.compile(r"power transformer|substation transformer|\bMVA\b|"
                         r"high[- ]voltage|transmission", re.I)),
]
TAG_MAP = [
    ("lead_time", re.compile(r"lead\s*time|delivery|backlog|shortage|constraint", re.I)),
    ("grid_investment", re.compile(r"grid (investment|upgrade|expansion)|transmission (line|project)", re.I)),
    ("data_center", re.compile(r"data cent(er|re)|hyperscal", re.I)),
    ("standards", re.compile(r"\bIEEE\b|ANSI|NEMA|standard", re.I)),
    ("UL", re.compile(r"\bUL\b|Underwriters", re.I)),
    ("CSA", re.compile(r"\bCSA\b|Canadian Standards", re.I)),
    ("DOE", re.compile(r"\bDOE\b|Department of Energy|energy conservation standard", re.I)),
    ("regulation", re.compile(r"regulation|rule|rulemaking|final rule|proposed rule", re.I)),
    ("contract_award", re.compile(r"contract|award|win|order|deal", re.I)),
    ("capacity", re.compile(r"capacity|expansion|plant|factory|manufactur", re.I)),
]


def infer_slice(text):
    geo = []
    if GEO_US.search(text):
        geo.append("US")
    if GEO_CA.search(text):
        geo.append("CA")
    if not geo:
        geo = ["US", "CA"]
    buyer = [k for k, rx in BUYER_MAP if rx.search(text)] or ["utility", "EPC", "distributor"]
    product = [k for k, rx in PRODUCT_MAP if rx.search(text)] or ["distribution", "power"]
    return {"geo": geo, "buyer_type": buyer, "product_line": product}


def infer_tags(text):
    return [k for k, rx in TAG_MAP if rx.search(text)]


# ---------------------------------------------------------------- 抓取

def fetch(url, opts, extra_headers=None):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", BROWSER_UA if opts.get("browser_ua") else BOT_UA)
    req.add_header("Accept", ACCEPT)
    req.add_header("Accept-Language", "en-US,en;q=0.9")
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    timeout = opts.get("timeout", 20)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), dict(resp.headers)


def fetch_with_retry(url, opts, extra_headers=None, retries=1):
    last = None
    for attempt in range(retries + 1):
        try:
            return fetch(url, opts, extra_headers)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last


# ---------------------------------------------------------------- 解析器

def _find_text(node, names):
    for n in names:
        el = node.find(n)
        if el is not None and (el.text or "").strip():
            return el.text.strip()
    return ""


def parse_rss(xml_bytes, limit=30):
    """标准 RSS 2.0 / Atom。"""
    root = ET.fromstring(xml_bytes)
    out = []
    items = root.findall(".//item")
    if items:
        for it in items[:limit]:
            out.append({
                "title": _find_text(it, ["title"]),
                "url": _find_text(it, ["link"]),
                "date": _find_text(it, ["pubDate", "date"]),
                "summary": clean_html(_find_text(it, ["description", "summary"])),
            })
        return out
    # Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for it in root.findall(".//a:entry", ns)[:limit]:
        link = ""
        for ln in it.findall("a:link", ns):
            if ln.get("rel") in (None, "alternate"):
                link = ln.get("href", "")
                break
        out.append({
            "title": _find_text(it, ["a:title"], ) if False else (it.findtext("a:title", default="", namespaces=ns) or "").strip(),
            "url": link,
            "date": (it.findtext("a:published", default="", namespaces=ns)
                     or it.findtext("a:updated", default="", namespaces=ns) or "").strip(),
            "summary": clean_html(it.findtext("a:summary", default="", namespaces=ns)
                                  or it.findtext("a:content", default="", namespaces=ns)),
        })
    return out


def parse_google_news(xml_bytes, limit=25):
    """Google News RSS —— 带 <source url> 真实媒体名。"""
    root = ET.fromstring(xml_bytes)
    out = []
    for it in root.findall(".//item")[:limit]:
        title = _find_text(it, ["title"])
        real_name, real_url = "", ""
        src_el = it.find("source")
        if src_el is not None:
            real_name = (src_el.text or "").strip()
            real_url = src_el.get("url", "")
        # Google News 标题形如 "标题 - 媒体名"，去掉后缀
        if real_name and title.endswith(" - " + real_name):
            title = title[: -(len(real_name) + 3)].strip()
        out.append({
            "title": title,
            "url": _find_text(it, ["link"]),
            "date": _find_text(it, ["pubDate"]),
            "summary": clean_html(_find_text(it, ["description"])),
            "publisher_name": real_name,
            "publisher_url": real_url,
        })
    return out


def parse_federal_register(payload, limit=25):
    out = []
    for r in (payload.get("results") or [])[:limit]:
        title = r.get("title") or ""
        abstract = r.get("abstract") or ""
        agencies = ", ".join(a.get("name", "") for a in (r.get("agencies") or []) if a.get("name"))
        out.append({
            "title": title,
            "url": r.get("html_url") or "",
            "date": r.get("publication_date") or "",
            "summary": (f"[{r.get('type','')}{' · ' + agencies if agencies else ''}] {abstract}").strip(),
        })
    return out


def parse_edgar(payload, limit=25):
    out = []
    hits = ((payload.get("hits") or {}).get("hits") or [])[:limit]
    for h in hits:
        s = h.get("_source") or {}
        names = s.get("display_names") or []
        who = names[0] if names else "(unknown filer)"
        cik = (s.get("ciks") or [""])[0]
        form = s.get("root_forms") or ([s.get("form")] if s.get("form") else [])
        hid = h.get("_id") or ""
        url = ""
        if ":" in hid and cik:
            acc, fname = hid.split(":", 1)
            url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                   f"{acc.replace('-', '')}/{fname}")
        out.append({
            "title": f"{who} — {form[0] if form else 'filing'}",
            "url": url or f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            "date": s.get("file_date") or "",
            "summary": (f"{who} filed {form[0] if form else 'a filing'} "
                        f"({s.get('file_type','')})."),
        })
    return out


PARSERS = {
    "rss": lambda b, s, lim: parse_rss(b, lim),
    "rss_google_news": lambda b, s, lim: parse_google_news(b, lim),
    "json_federal_register": lambda b, s, lim: parse_federal_register(json.loads(b), lim),
    "json_edgar": lambda b, s, lim: parse_edgar(json.loads(b), lim),
}


# ---------------------------------------------------------------- 单源处理

def build_url(source, query=None):
    base = source["url"]
    if source["parser"] == "json_federal_register":
        params = {"conditions[term]": query or "transformer",
                  "per_page": "25", "order": "newest"}
        return base + "?" + urllib.parse.urlencode(params)
    if source["parser"] == "json_edgar":
        start = (now_bj() - timedelta(days=45)).strftime("%Y-%m-%d")
        # ⚠️ EDGAR 只接受简单查询 —— 多词短语会触发 SSL UNEXPECTED_EOF（实测）
        params = {"q": query or "transformer",
                  "dateRange": "custom", "startdt": start,
                  "enddt": today_str()}
        return base + "?" + urllib.parse.urlencode(params)
    if source["parser"] == "rss_google_news":
        params = {"q": query or "transformer", "hl": "en-US", "gl": "US", "ceid": "US:en"}
        return base + "?" + urllib.parse.urlencode(params)
    return base


def normalize(raw, source, query=None):
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    pub = parse_date_any(raw.get("date"))
    if not title or not url or not pub:
        return None                      # 缺出处 → 丢弃

    publisher = raw.get("publisher_name") or ""
    src_name = source["name"]
    notes = []
    if publisher:
        src_name = publisher
        notes.append("Google News 聚合源；引用前须打开原链接核实，标注真实媒体名")

    summary = (raw.get("summary") or "").strip()
    blob = f"{title} {summary}"

    # 相关性闸门：只认标题（实测摘要里的泛词会放进大量无关新闻）
    if not relevance_ok(source, title):
        return None

    # 取摘要首句作为可引用句（邮件场景下不宜过长）
    quote_en = (summary or title).strip()
    if quote_en:
        first = re.split(r"(?<=[.!?])\s+", quote_en)[0].strip()
        if len(first) >= 30:
            quote_en = first
    if len(quote_en) > 240:
        quote_en = quote_en[:237].rsplit(" ", 1)[0] + "..."

    ok, issues = lint_quote(quote_en)
    flags = list(issues)
    usable = ["self", "followup"]

    if LEADTIME_PRICE_RE.search(quote_en):
        usable = ["self"]
        flags.append("含交期/价格语义 —— 不可用于跟进信正文，仅作背景")

    if not ok:
        usable = ["self"]

    return {
        "id": entry_id(source["id"], url),
        "category": source["category"],
        "source_id": source["id"],
        "title": title,
        "summary_zh": "",                 # 由 agent 后续补写
        "summary_raw": summary[:500],
        "source_name": src_name,
        "source_url": url,
        "published_at": pub,
        "fetched_at": today_str(),
        "credibility": source["credibility"],
        "query": query or "",
        "quote_ready_en": quote_en,
        "quote_lint_ok": ok,
        "tags": infer_tags(blob),
        "audience_slice": infer_slice(blob),
        "usable_in": usable,
        "do_not_say_flags": flags,
        "status": "new",
        "used_in": [],
        "notes": notes,
    }


def fetch_source(source, verbose=False):
    """返回 (entries, status, detail)"""
    parser = PARSERS.get(source["parser"])
    if parser is None:
        return [], "failed", f"未知解析器 {source['parser']}"

    queries = source.get("queries") or [None]
    entries, errors = [], []
    per_q = source.get("per_query_limit", 25)
    for q in queries:
        url = build_url(source, q)
        try:
            body, _ = fetch_with_retry(url, source.get("options") or {})
            raws = parser(body, source, per_q)
        except Exception as e:
            errors.append(f"{q or '-'}: {type(e).__name__} {e}")
            continue
        for r in raws:
            e = normalize(r, source, q)
            if e:
                entries.append(e)
        if verbose:
            print(f"      query={q!r:52s} → {len(raws)} 条")
        time.sleep(1)                    # 礼貌限速

    # 时效闸门：太旧的条目不进库
    max_age = source.get("max_age_days")
    if max_age:
        cut = (now_bj() - timedelta(days=max_age)).strftime("%Y-%m-%d")
        before = len(entries)
        entries = [e for e in entries if e["published_at"] >= cut]
        if verbose and before != len(entries):
            print(f"      时效过滤 {max_age} 天：{before} → {len(entries)}")

    if not entries and errors:
        return [], "failed", "; ".join(errors[:2])
    if errors:
        return entries, "degraded", "; ".join(errors[:2])
    return entries, "ok", ""


# ---------------------------------------------------------------- 存储

class FileLock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        for _ in range(3):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                stale = False
                try:
                    pid = int(self.path.read_text().strip() or "0")
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        stale = True
                    except PermissionError:
                        stale = False
                    else:
                        print(f"⛔ 另一个抓取进程正在运行（PID {pid}），本次退出。"
                              f"若确认无进程，删除 {self.path} 后重试。")
                        sys.exit(2)
                except (ValueError, OSError):
                    stale = True
                if stale:
                    print(f"⚠️  发现僵尸锁（PID 已不存在），接管。")
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
        sys.exit(2)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass
        return False


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  {path.name} 读取失败（{e}），按空处理")
        return default


def backup_file(path):
    if path.exists():
        stamp = now_bj().strftime("%Y%m%d-%H%M")
        dst = path.with_name(f"{path.name}.bak-{stamp}")
        shutil.copy2(path, dst)
        return dst
    return None


def atomic_write_text(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path, data):
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=1))


def dedupe(entries):
    """按 id 去重；再按归一化标题去重（消除转载）。保留先出现的。"""
    seen_id, seen_title, out = set(), set(), []
    for e in entries:
        if e["id"] in seen_id:
            continue
        nt = norm_title(e["title"])
        if nt and nt in seen_title:
            continue
        seen_id.add(e["id"])
        if nt:
            seen_title.add(nt)
        out.append(e)
    return out


# ---------------------------------------------------------------- 渲染

def render_index(entries):
    entries = sorted(entries, key=lambda e: (e["published_at"], e["fetched_at"]), reverse=True)
    week_ago = (now_bj() - timedelta(days=7)).strftime("%Y-%m-%d")
    fresh = [e for e in entries if e["fetched_at"] >= week_ago]
    usable = [e for e in entries if "followup" in e["usable_in"] and e["quote_lint_ok"]]

    L = []
    w = L.append
    w("# 行业数据索引")
    w("")
    w(f"> 自动生成 · {now_bj().strftime('%Y-%m-%d %H:%M')}（北京）｜ 共 **{len(entries)}** 条")
    w(f"> 其中可进跟进信正文的 **{len(usable)}** 条 ｜ 本周新增 **{len(fresh)}** 条")
    w("")
    w("> ⚠️ 本索引由 `抓取/抓取行业数据.py` 自动生成，**请勿手工编辑**（会被覆盖）。")
    w("")
    w("---")
    w("")
    w("## 本周新增")
    w("")
    if fresh:
        w("| 日期 | 类别 | 标题 | 来源 | 可信度 | 可用于 |")
        w("|---|---|---|---|---|---|")
        for e in fresh[:40]:
            use = "跟进信" if "followup" in e["usable_in"] else "仅背景"
            title = e["title"].replace("|", "/")[:56]
            w(f"| {e['published_at']} | {CATEGORY_LABEL.get(e['category'], e['category'])} "
              f"| {title} | {e['source_name'][:22]} "
              f"| {CRED_LABEL.get(e['credibility'], '?')} | {use} |")
    else:
        w("_本周暂无新增。_")
    w("")
    w("---")
    w("")

    for cat, label in CATEGORY_LABEL.items():
        group = [e for e in entries if e["category"] == cat]
        w(f"## {label}（{len(group)} 条）")
        w("")
        if not group:
            w("_暂无数据。_")
            w("")
            continue
        for e in group[:60]:
            cred = CRED_LABEL.get(e["credibility"], "?")
            use = "✅ 可用于跟进信" if "followup" in e["usable_in"] else "⛔ 仅内部背景"
            w(f"### {e['published_at']} · {e['title']}")
            w("")
            w(f"- **来源**：[{e['source_name']}]({e['source_url']})（{cred}）")
            if e.get("query"):
                w(f"- **检索词**：`{e['query']}`")
            if e["tags"]:
                w(f"- **标签**：{'、'.join(e['tags'])}")
            sl = e["audience_slice"]
            w(f"- **受众切片**：地域 {'/'.join(sl['geo'])} ｜ 买家 {'/'.join(sl['buyer_type'])} "
              f"｜ 产品线 {'/'.join(sl['product_line'])}")
            w(f"- **可用性**：{use}")
            if e["do_not_say_flags"]:
                w(f"- ⚠️ **红线提示**：{'；'.join(e['do_not_say_flags'])}")
            if e.get("summary_zh"):
                w(f"- **中文摘要**：{e['summary_zh']}")
            if e.get("summary_raw"):
                w(f"- **原文摘要**：{e['summary_raw'][:300]}")
            w("")
            w("```text")
            w(e["quote_ready_en"][:400])
            w("```")
            w("")
        w("---")
        w("")

    w("## 说明")
    w("")
    w("- **可信度**：一手（监管/官方 API）｜ 行业媒体 ｜ 聚合（Google News）")
    w("- **可用性**：`✅ 可用于跟进信` 表示可作为「新信息点」引用；")
    w("  `⛔ 仅内部背景` 表示含交期/价格语义或命中禁语，**不得写进信里**")
    w("- **红线依据**：`开发信项目/04_do_not_say.md`")
    w("- **引用要求**：任何引用必须能追溯到本条目的 `source_url` + `published_at`")
    w("")
    return "\n".join(L)


# ---------------------------------------------------------------- 命令

def cmd_list_sources(sources):
    print(f"{'ID':<18}{'类别':<20}{'解析器':<24}{'可信':<6}{'状态':<6}名称")
    print("-" * 96)
    for s in sources:
        st = "启用" if s.get("enabled") else "禁用"
        print(f"{s['id']:<18}{s['category']:<20}{s['parser']:<24}"
              f"{s['credibility']:<6}{st:<6}{s['name']}")
    return 0


def cmd_pick(entries, geo, buyer, product, limit):
    out = []
    for e in entries:
        if e.get("status") != "new":
            continue
        if "followup" not in e.get("usable_in", []):
            continue
        if e.get("credibility") not in ("A", "B"):
            continue
        if not e.get("quote_lint_ok", True):
            continue
        sl = e.get("audience_slice", {})
        if geo and geo not in sl.get("geo", []):
            continue
        if buyer and buyer not in sl.get("buyer_type", []):
            continue
        if product and product not in sl.get("product_line", []):
            continue
        out.append(e)
    out.sort(key=lambda x: x["published_at"], reverse=True)
    out = out[:limit]

    print(f"# 候选「新信息点」({len(out)} 条)")
    print(f"> 筛选：geo={geo or '不限'} buyer={buyer or '不限'} product={product or '不限'}")
    print()
    for i, e in enumerate(out, 1):
        print(f"## {i}. {e['title']}")
        print(f"- 来源：{e['source_name']}（{e['credibility']}）{e['source_url']}")
        print(f"- 发布：{e['published_at']}")
        print(f"- 可用英文句：{e['quote_ready_en']}")
        print()
    return 0


def main():
    ap = argparse.ArgumentParser(description="行业数据抓取器（纯 stdlib）")
    ap.add_argument("--source", default="all", help="all 或来源 id")
    ap.add_argument("--category", help="按类别筛选")
    ap.add_argument("--since-days", type=int, default=0, help="只保留 N 天内发布的条目")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    ap.add_argument("--no-network", action="store_true", help="不联网，只用已有数据渲染")
    ap.add_argument("--render-only", action="store_true", help="只重渲 md 索引")
    ap.add_argument("--list-sources", action="store_true", help="列出所有源")
    ap.add_argument("--pick", action="store_true", help="查询候选新信息点")
    ap.add_argument("--geo", help="US / CA")
    ap.add_argument("--buyer", help="utility / EPC / distributor / datacenter")
    ap.add_argument("--product", help="distribution / power")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    reg = load_json(SRC_FILE, None)
    if not reg:
        print(f"⛔ 读不到来源清单：{SRC_FILE}")
        return 1
    sources = reg.get("sources", [])

    if args.list_sources:
        return cmd_list_sources(sources)

    if args.pick:
        entries = load_json(STORE_FILE, [])
        return cmd_pick(entries, args.geo, args.buyer, args.product, args.limit)

    if args.render_only:
        entries = load_json(STORE_FILE, [])
        if not entries:
            print("⛔ 数据文件为空，先跑一次抓取")
            return 1
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(INDEX_FILE, render_index(entries))
        print(f"✅ 已重渲索引：{INDEX_FILE}（{len(entries)} 条）")
        return 0

    # ---------- 抓取 ----------
    with FileLock(LOCK_FILE):
        state = load_json(STATE_FILE, {"sources": {}})
        store = load_json(STORE_FILE, [])
        existing_ids = {e["id"] for e in store}
        existing_titles = {norm_title(e["title"]) for e in store}

        targets = [s for s in sources if s.get("enabled")]
        if args.source != "all":
            targets = [s for s in targets if s["id"] == args.source]
        if args.category:
            targets = [s for s in targets if s["category"] == args.category]
        if not targets:
            print("⛔ 没有匹配的来源")
            return 1

        print(f"开始抓取 {len(targets)} 个源（现有库内 {len(store)} 条）\n")
        report, new_entries = [], []

        if args.no_network:
            print("（--no-network：跳过抓取）")
        else:
            for s in targets:
                if args.verbose:
                    print(f"→ {s['id']} ({s['name']})")
                entries, status, detail = fetch_source(s, args.verbose)
                report.append((s["id"], status, len(entries), detail))
                icon = {"ok": "✅", "degraded": "⚠️", "failed": "❌"}[status]
                print(f"  {icon} {s['id']:<18} {status:<9} {len(entries):>3} 条"
                      + (f"  {detail[:70]}" if detail else ""))
                st = state.setdefault("sources", {}).setdefault(s["id"], {})
                st["last_fetched"] = now_bj().strftime("%Y-%m-%d %H:%M")
                st["last_status"] = status
                if status != "failed":
                    new_entries.extend(entries)

        # ---------- 合并去重 ----------
        fresh = []
        for e in new_entries:
            if e["id"] in existing_ids:
                continue
            if norm_title(e["title"]) in existing_titles:
                continue
            existing_ids.add(e["id"])
            existing_titles.add(norm_title(e["title"]))
            fresh.append(e)

        if args.since_days:
            cut = (now_bj() - timedelta(days=args.since_days)).strftime("%Y-%m-%d")
            fresh = [e for e in fresh if e["published_at"] >= cut]

        merged = dedupe(store + fresh)

        print(f"\n新增 {len(fresh)} 条 ｜ 库内合计 {len(merged)} 条")

        if args.dry_run:
            print("\n[--dry-run] 以下为将写入的前 15 条：")
            for e in fresh[:15]:
                print(f"  [{e['published_at']}] ({e['category']}/{e['credibility']}) "
                      f"{e['title'][:62]}")
            print("\n[--dry-run] 未写入任何文件。")
            return 0

        # ---------- 落盘 ----------
        bak = backup_file(STORE_FILE)
        if bak:
            print(f"  备份 → {bak.name}")
        atomic_write_json(STORE_FILE, merged)
        atomic_write_json(STATE_FILE, state)
        atomic_write_text(INDEX_FILE, render_index(merged))
        print(f"✅ 已写 {STORE_FILE.name}（{len(merged)} 条）")
        print(f"✅ 已写 {INDEX_FILE.name}")
        print(f"✅ 已更新 {STATE_FILE.name}")

        ok = sum(1 for _, s, _, _ in report if s == "ok")
        deg = sum(1 for _, s, _, _ in report if s == "degraded")
        bad = sum(1 for _, s, _, _ in report if s == "failed")
        print(f"\n运行报告：正常 {ok} ｜ 降级 {deg} ｜ 失败 {bad}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
