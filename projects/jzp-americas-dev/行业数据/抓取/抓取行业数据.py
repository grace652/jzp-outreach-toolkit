#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业数据抓取器 —— 成熟库版

依赖（已装入隔离环境 /Users/eric/.workbuddy-ai/binaries/python/envs/default）
    feedparser 6.0.14 | requests 2.34.2 | beautifulsoup4 4.15.0
    lxml 6.1.3 | python-dateutil 2.9.0 | trafilatura 2.3.0（--verify 用）

设计要点
--------
1. 写入安全：排他锁 + os.replace 原子替换 + 时间戳备份
2. 每条数据必须有出处：缺 source_url 或 published_at 的条目直接丢弃
3. 遵守 04_do_not_say.md：quote_ready_en 必须通过禁语 lint
4. 交期/价格类条目自动降级为「不可用于跟进信」

用法
----
  python3 抓取行业数据.py                      # 全量抓取
  python3 抓取行业数据.py --dry-run             # 只看会写什么，不落盘
  python3 抓取行业数据.py --source utilitydive  # 只抓指定源
  python3 抓取行业数据.py --render-only         # 只重渲 md 索引
  python3 抓取行业数据.py --list-sources
  python3 抓取行业数据.py --pick --geo CA --buyer EPC --product distribution
  python3 抓取行业数据.py --verify --limit 5    # 打开原文核实
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

ROOT = Path(__file__).resolve().parent.parent
SRC_FILE = ROOT / "抓取" / "来源清单.json"
STATE_FILE = ROOT / "抓取" / "state.json"
LOCK_FILE = ROOT / "抓取" / ".lock"
STORE_FILE = ROOT / "数据" / "industry_news.json"
INDEX_FILE = ROOT / "出口" / "行业数据索引.md"

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
BOT_UA = "jzp-industry-data/1.0 (+contact: {{SENDER_EMAIL}})"
# 这些站点要求请求方声明身份，用浏览器 UA 会被 403（SEC 实测）
FORCE_BOT_UA_DOMAINS = ("sec.gov",)
BJ = timezone(timedelta(hours=8))

CATEGORY_LABEL = {
    "market_supply": "市场与供应链行情",
    "standards_cert": "标准与认证动态",
    "customer_activity": "客户业务动态",
    "competitor": "竞品与同行动态",
}
CRED_LABEL = {"A": "一手", "B": "行业媒体", "C": "聚合"}

# 已知无法自动核实的域（2026-10-03 实测）：
#   utilitydive.com / datacenterdynamics.com  → Cloudflare 403
#   news.google.com                           → 跳转需 JS，HTTP 层拿不到真实 URL
NO_VERIFY_DOMAINS = ("utilitydive.com", "datacenterdynamics.com",
                     "pv-magazine-usa.com", "news.google.com")

SESSION = requests.Session()

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


def lint_quote(text):
    issues = [msg for rx, msg in BANNED_RE if rx.search(text)]
    return (not issues), issues


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

RELEVANCE_STRICT_RE = re.compile(
    r"transformer|substation|switchgear|\bkVA\b|\bMVA\b|\bkV\b|"
    r"insulation|bushing|recloser|voltage regulator|capacitor bank|"
    r"high[- ]voltage (equipment|insulation|apparatus|asset)|"
    r"grid (equipment|hardware|infrastructure|constraint|bottleneck|"
    r"capacity|connection|interconnect|upgrade)|"
    r"power (equipment|hardware|supply chain|distribution)|"
    r"interconnect(ion)? (queue|delay|wait|study)|"
    r"electrical (equipment|infrastructure)",
    re.I)


def relevance_ok(source, title):
    if not source.get("relevance_filter"):
        return True
    rx = RELEVANCE_STRICT_RE if source.get("relevance_level") == "strict" else RELEVANCE_RE
    return bool(rx.search(title))


def now_bj():
    return datetime.now(BJ)


def today_str():
    return now_bj().strftime("%Y-%m-%d")


def clean_html(raw):
    if not raw:
        return ""
    soup = BeautifulSoup(str(raw), "lxml")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def parse_date_any(s):
    if not s:
        return None
    s = str(s).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # dateutil 对 EST/PST 等时区缩写会告警
        try:
            return dateparser.parse(s, fuzzy=True).strftime("%Y-%m-%d")
        except Exception:
            return None


def canonical_url(u):
    if not u:
        return ""
    try:
        p = urllib.parse.urlsplit(u.strip())
        q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
             if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
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
    ("EPC", re.compile(r"\bEPC\b|engineering,? procurement|design-build", re.I)),
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
    ("regulation", re.compile(r"regulation|rulemaking|final rule|proposed rule", re.I)),
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
    """用 requests 抓取，自动跟随重定向。返回 (bytes, headers)。

    SSL 失败会自动降级重试一次（本机代理链证书可能不被信任）。
    """
    ua = BROWSER_UA if opts.get("browser_ua") else BOT_UA
    if any(d in url for d in FORCE_BOT_UA_DOMAINS):
        ua = BOT_UA
    headers = {
        "User-Agent": ua,
        "Accept": ("application/rss+xml, application/atom+xml, application/xml, "
                   "application/json, text/xml, text/html, */*"),
        "Accept-Language": "en-US,en;q=0.9",
    }
    if extra_headers:
        headers.update(extra_headers)

    kwargs = {"headers": headers, "timeout": opts.get("timeout", 20),
              "allow_redirects": True}

    def _do(v):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return SESSION.get(url, verify=v, **kwargs)

    verify = not opts.get("insecure_ssl")
    try:
        r = _do(verify)
    except requests.exceptions.SSLError:
        if verify:
            r = _do(False)
        else:
            raise
    r.raise_for_status()
    return r.content, dict(r.headers)


def fetch_with_retry(url, opts, extra_headers=None, retries=1):
    last = None
    for attempt in range(retries + 1):
        try:
            return fetch(url, opts, extra_headers)
        except requests.RequestException as e:
            last = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last


# ---------------------------------------------------------------- 解析器

def parse_rss(body, source, limit=30):
    """标准 RSS 2.0 / Atom —— 交给 feedparser 处理各种格式变体。"""
    fp = feedparser.parse(body)
    out = []
    for e in fp.entries[:limit]:
        out.append({
            "title": (e.get("title") or "").strip(),
            "url": (e.get("link") or "").strip(),
            "date": e.get("published") or e.get("updated") or "",
            "summary": clean_html(e.get("summary") or e.get("description") or ""),
        })
    return out


def parse_google_news(body, source, limit=25):
    """Google News RSS —— feedparser 会把 <source url> 解析进 e.source。"""
    fp = feedparser.parse(body)
    out = []
    for e in fp.entries[:limit]:
        title = (e.get("title") or "").strip()
        src = e.get("source") or {}
        real_name = (src.get("title") or "").strip() if isinstance(src, dict) else ""
        real_url = (src.get("href") or "").strip() if isinstance(src, dict) else ""
        if real_name and title.endswith(" - " + real_name):
            title = title[: -(len(real_name) + 3)].strip()
        out.append({
            "title": title,
            "url": (e.get("link") or "").strip(),
            "date": e.get("published") or e.get("updated") or "",
            "summary": clean_html(e.get("summary") or e.get("description") or ""),
            "publisher_name": real_name,
            "publisher_url": real_url,
        })
    return out


def parse_federal_register(payload, source, limit=25):
    out = []
    for r in (payload.get("results") or [])[:limit]:
        abstract = r.get("abstract") or ""
        agencies = ", ".join(a.get("name", "") for a in (r.get("agencies") or [])
                             if a.get("name"))
        out.append({
            "title": r.get("title") or "",
            "url": r.get("html_url") or "",
            "date": r.get("publication_date") or "",
            "summary": (f"[{r.get('type','')}{' · ' + agencies if agencies else ''}] "
                        f"{abstract}").strip(),
        })
    return out


def parse_edgar(payload, source, limit=25):
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
    "rss": parse_rss,
    "rss_google_news": parse_google_news,
    "json_federal_register": lambda b, s, lim: parse_federal_register(json.loads(b), s, lim),
    "json_edgar": lambda b, s, lim: parse_edgar(json.loads(b), s, lim),
}


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
                  "dateRange": "custom", "startdt": start, "enddt": today_str()}
        return base + "?" + urllib.parse.urlencode(params)
    if source["parser"] == "rss_google_news":
        params = {"q": query or "transformer", "hl": "en-US", "gl": "US", "ceid": "US:en"}
        return base + "?" + urllib.parse.urlencode(params)
    return base


# ---------------------------------------------------------------- 归一化

def normalize(raw, source, query=None):
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    pub = parse_date_any(raw.get("date"))
    if not title or not url or not pub:
        return None                      # 缺出处 → 丢弃

    # 相关性闸门：只认标题（实测摘要里的泛词会放进大量无关新闻）
    if not relevance_ok(source, title):
        return None

    publisher = raw.get("publisher_name") or ""
    src_name = source["name"]
    notes = []
    if publisher:
        src_name = publisher
        notes.append("Google News 聚合源；引用前须打开原链接核实，标注真实媒体名")

    summary = (raw.get("summary") or "").strip()

    # 可引用句：优先取摘要首句。Google News 的摘要常为 HTML 链接列表，
    # clean_html 后可能为空 —— 此时不拿标题充数（标题不是完整句），改为标记待人工改写。
    quote_en = summary.strip()
    if quote_en:
        first = re.split(r"(?<=[.!?])\s+", quote_en)[0].strip()
        if len(first) >= 30:
            quote_en = first
        if len(quote_en) > 240:
            quote_en = quote_en[:237].rsplit(" ", 1)[0] + "..."

    # Google News 的摘要常退化成「标题 + 媒体名」的拼接 —— 那不是句子，不能当引用句
    if quote_en:
        residue = quote_en
        for part in (title, publisher):
            if part:
                residue = residue.replace(part, "")
        if len(re.sub(r"\s+", "", residue)) < 25:
            quote_en = ""
    needs_rewrite = not quote_en

    ok, issues = lint_quote(quote_en)
    if needs_rewrite:
        ok = False
    flags = list(issues)
    usable = ["self", "followup"]

    if needs_rewrite:
        flags.append("仅有标题、无可用摘要 —— 引用前须人工撰写完整句")
    if LEADTIME_PRICE_RE.search(quote_en):
        usable = ["self"]
        flags.append("含交期/价格语义 —— 不可用于跟进信正文，仅作背景")
    if not ok and not needs_rewrite:
        usable = ["self"]

    return {
        "id": entry_id(source["id"], url),
        "category": source["category"],
        "source_id": source["id"],
        "title": title,
        "summary_zh": "",
        "summary_raw": summary[:500],
        "source_name": src_name,
        "source_url": url,
        "published_at": pub,
        "fetched_at": today_str(),
        "credibility": source["credibility"],
        "query": query or "",
        "quote_ready_en": quote_en,
        "quote_lint_ok": ok,
        "tags": infer_tags(f"{title} {summary}"),
        "audience_slice": infer_slice(f"{title} {summary}"),
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
        time.sleep(1)

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
                    print("⚠️  发现僵尸锁（PID 已不存在），接管。")
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
    w("- **原文核实**：`抓取行业数据.py --verify --limit N` 用 trafilatura 打开原文提取正文")
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


def cmd_pick(entries, geo, buyer, product, limit, include_c=False):
    """查询候选「新信息点」。

    硬过滤：A/B 级（--include-c 时含 C）、含 followup、lint 通过、设备级相关。
    软排序：与 geo/buyer/product 的**匹配度**（geo 权重 2，其余各 1）。
      —— 刻意不做硬过滤：行业信息常跨地域适用（如「全球变压器交期紧张」对美加都成立），
         硬过滤会把可用信息直接滤光（实测 --geo CA 曾返回 0 条）。
    """
    out = []
    creds = ("A", "B", "C") if include_c else ("A", "B")
    for e in entries:
        if e.get("status") != "new":
            continue
        if "followup" not in e.get("usable_in", []):
            continue
        if e.get("credibility") not in creds:
            continue
        if not e.get("quote_lint_ok", True):
            continue
        # 二次过滤：必须是「设备/产品」级相关，而非泛监管或泛行业新闻。
        # 库本身保留宽过滤（供人阅读），但 --pick 的产出要直接进信，必须严。
        # 匹配范围**含摘要** —— 标题常是「FERC 批准某标准」这类监管表述，
        # 真正的设备信息（transformer / substation …）在摘要里。
        blob = f"{e.get('title', '')} {e.get('summary_raw', '')}"
        if not RELEVANCE_STRICT_RE.search(blob):
            continue
        sl = e.get("audience_slice", {})
        score = 0
        if geo:
            score += 2 if geo in sl.get("geo", []) else 0
        if buyer:
            score += 1 if buyer in sl.get("buyer_type", []) else 0
        if product:
            score += 1 if product in sl.get("product_line", []) else 0
        out.append((score, e))

    # 匹配度优先，同分按发布日期倒序
    out.sort(key=lambda t: (-t[0], t[1]["published_at"]))
    out = out[:limit]

    print(f"# 候选「新信息点」({len(out)} 条)")
    print(f"> 筛选：geo={geo or '不限'} buyer={buyer or '不限'} product={product or '不限'} "
          f"可信度={'A/B/C' if include_c else 'A/B'}")
    print("> 排序：按客户画像匹配度（geo 权重 2，buyer / product 各 1）")
    print()
    for i, (score, e) in enumerate(out, 1):
        tag = " ✅ 匹配画像" if score else " ⚠️ 未匹配画像（参考项 —— 行业信息常跨地域适用）"
        print(f"## {i}. {e['title']}{tag}")
        print(f"- 来源：{e['source_name']}（{e['credibility']}）{e['source_url']}")
        print(f"- 发布：{e['published_at']}")
        if e["credibility"] == "C":
            print("- ⚠️ 聚合源：引用前须打开原链接核实、标注真实媒体名")
        print(f"- 可用英文句：{e['quote_ready_en']}")
        print()
    return 0


def cmd_verify(entries, limit):
    """用 trafilatura 打开原文链接，提取正文 —— 用于引用前核实。"""
    if not HAS_TRAFILATURA:
        print("⛔ 未安装 trafilatura，无法核实。")
        return 1
    pool = [e for e in entries if e.get("source_url")]
    if not pool:
        print("（库里没有可核实的条目）")
        return 0
    skipped = [e for e in pool
               if any(d in e["source_url"] for d in NO_VERIFY_DOMAINS)]
    pool = [e for e in pool
            if not any(d in e["source_url"] for d in NO_VERIFY_DOMAINS)]
    pool.sort(key=lambda e: e["published_at"], reverse=True)
    pool = pool[:limit]
    if skipped:
        print(f"（跳过 {len(skipped)} 条已知无法自动核实的源：Cloudflare 反爬 / 聚合跳转）\n")
    if not pool:
        print("⚠️ 库内没有可自动核实的条目 —— 剩下的都需人工点开。")
        return 0

    print(f"核实 {len(pool)} 条（打开原文提取正文）\n")
    ok = fail = 0
    for e in pool:
        print(f"── {e['title'][:70]}")
        print(f"   {e['source_name']}（{e['credibility']}）")
        print(f"   链接：{e['source_url'][:88]}")
        try:
            body, _ = fetch(e["source_url"], {"browser_ua": True, "timeout": 25})
            text = trafilatura.extract(body.decode("utf-8", "replace"),
                                       include_comments=False, include_tables=False)
            if text and len(text) > 200:
                first = text.split("\n")[0][:170]
                print(f"   ✅ 正文 {len(text)} 字符")
                print(f"   首段：{first}")
                ok += 1
            else:
                print(f"   ⚠️ 未提取到有效正文（可能被反爬拦截，需人工点开）")
                fail += 1
        except Exception as ex:
            print(f"   ❌ {type(ex).__name__}: {str(ex)[:70]}")
            fail += 1
        print()
        time.sleep(1)

    print(f"核实结果：成功 {ok} ｜ 需人工 {fail}")
    print("\n> 提示：Cloudflare 等强反爬站点（如 Utility Dive）无法自动核实，")
    print("> 这类条目引用前请人工打开链接确认。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="行业数据抓取器（feedparser + requests 版）")
    ap.add_argument("--source", default="all", help="all 或来源 id")
    ap.add_argument("--category", help="按类别筛选")
    ap.add_argument("--since-days", type=int, default=0, help="只保留 N 天内发布的条目")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不落盘")
    ap.add_argument("--no-network", action="store_true", help="不联网，只用已有数据渲染")
    ap.add_argument("--render-only", action="store_true", help="只重渲 md 索引")
    ap.add_argument("--list-sources", action="store_true", help="列出所有源")
    ap.add_argument("--pick", action="store_true", help="查询候选新信息点")
    ap.add_argument("--include-c", action="store_true",
                    help="--pick 时纳入 C 级聚合源（引用前需人工核实）")
    ap.add_argument("--verify", action="store_true", help="打开原文核实聚合源条目")
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

    if args.verify:
        entries = load_json(STORE_FILE, [])
        return cmd_verify(entries, args.limit)

    if args.pick:
        entries = load_json(STORE_FILE, [])
        return cmd_pick(entries, args.geo, args.buyer, args.product, args.limit,
                        include_c=args.include_c)

    if args.render_only:
        entries = load_json(STORE_FILE, [])
        if not entries:
            print("⛔ 数据文件为空，先跑一次抓取")
            return 1
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(INDEX_FILE, render_index(entries))
        print(f"✅ 已重渲索引：{INDEX_FILE}（{len(entries)} 条）")
        return 0

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




