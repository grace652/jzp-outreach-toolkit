#!/usr/bin/env python3
"""海关数据适配器层：统一接口 + 可插拔数据源。

设计边界（重要）：
- 适配器**只产出归一化记录，绝不写入 entries/**。是否把某个买家变成知识库条目，
  由 lead_scoring.py 决定——抓取是探索性的、可重跑；建条目是判断，只做一次。
- 付费平台（Trademo / ImportGenius / 52wmb / Volza 等）**不走凭据登录、不抓取**。
  正确路径是：你自己登录导出 CSV/XLSX → 用 local_csv 适配器解析。
  这样做既合规，也不会因为页面改版而失效。

已实现的适配器：
    canada_cid   加拿大 ISED 官方进口商数据库（开放数据，免费，无条款风险）
    local_csv    本地 CSV/TSV/XLSX（广交会名录、各平台导出文件、自有成交记录）
    paid_portal  占位：文档化付费平台的正确接入方式
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import customs_normalize as cn
import officedoc

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"

UA = "jiezou-kb-customs/1.0 (local research; contact: local user)"

# 归一化记录结构：所有适配器都产出这套字段
NORMALIZED_FIELDS = [
    # 身份
    "record_id", "source", "source_ref", "retrieved_at",
    # 买家
    "buyer_name", "buyer_name_norm", "buyer_key", "buyer_country", "buyer_country2",
    "buyer_region", "buyer_city", "buyer_postal", "buyer_address",
    # 产品
    "hs_code", "hs_code6", "product_desc",
    # 供应侧
    "supplier_name", "supplier_name_norm", "supplier_role",
    # 量（未知一律 0/空，绝不猜）
    "shipment_count", "quantity_kg", "value_usd",
    "first_shipment_date", "last_shipment_date", "distinct_suppliers", "top_supplier_share",
    # 联系方式（仅当来源本身提供）
    "contact_name", "contact_email", "contact_phone",
    # 溯源
    "raw",
]


def blank_record(source, source_ref):
    rec = {k: "" for k in NORMALIZED_FIELDS}
    rec.update({
        "source": source, "source_ref": source_ref,
        "retrieved_at": date.today().isoformat(),
        "shipment_count": 0, "quantity_kg": 0.0, "value_usd": 0.0,
        "distinct_suppliers": 0, "top_supplier_share": 0.0,
        "raw": {},
    })
    return rec


def finalize_record(rec, aliases=None, watchlist=None):
    """补全派生字段：归一化名、比对键、国家码、供应商角色、record_id。"""
    name = rec.get("buyer_name") or ""
    rec["buyer_name_norm"] = cn.normalize_company(name)
    key = cn.company_key(name, aliases)
    c2 = rec.get("buyer_country2") or cn.country2_of(
        rec.get("buyer_country"), rec.get("buyer_address"), rec.get("buyer_region"), rec.get("buyer_city")
    )
    rec["buyer_country2"] = c2
    rec["buyer_key"] = f"{key}@{c2 or '??'}" if key else ""

    if not rec.get("buyer_region"):
        rec["buyer_region"] = cn.region_of(rec.get("buyer_address"), rec.get("buyer_city"))

    sup = rec.get("supplier_name") or ""
    rec["supplier_name_norm"] = cn.normalize_company(sup)
    if sup and not rec.get("supplier_role"):
        role, _ = cn.supplier_role(sup, watchlist)
        rec["supplier_role"] = role

    rec["hs_code6"] = cn.hs6(rec.get("hs_code"))

    if not rec.get("record_id"):
        parts = [rec.get(k, "") for k in
                 ("source", "source_ref", "buyer_name_norm", "hs_code6", "product_desc", "last_shipment_date")]
        rec["record_id"] = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]
    return rec


# ---------------------------------------------------------------- 查询与缓存

@dataclass
class Query:
    hs_codes: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
    country: str = ""
    categories: list = field(default_factory=list)
    limit: int = 0
    refresh: bool = False
    offline: bool = False

    def hs6_list(self):
        return sorted({h for h in (cn.hs6(c) for c in self.hs_codes) if h})

    def country_list(self):
        """把 --country 的输入统一成 2 位码。

        允许「美国」「Canada」「US」等写法——否则筛选会拿原始字符串
        去比对归一化后的 2 位码，永远匹配不上。
        """
        out = []
        for item in str(self.country or "").split(","):
            item = item.strip()
            if not item:
                continue
            out.append(cn.country2_of(item) or item.upper())
        return out


class OfflineError(RuntimeError):
    """离线且无缓存。"""


class Cache:
    """带 TTL、最小请求间隔与元数据的本地缓存。"""

    def __init__(self, root=None, ttl_days=30, min_interval=3.0, offline=False, timeout=60):
        self.root = Path(root) if root else CACHE_DIR
        self.ttl_days = ttl_days
        self.min_interval = min_interval
        self.offline = offline
        self.timeout = timeout
        self._last_request = {}

    def _key(self, url):
        return hashlib.sha1(url.encode("utf-8")).hexdigest()

    @staticmethod
    def _host(url):
        return re.sub(r"^https?://([^/]+).*$", r"\1", url)

    def path_for(self, url):
        # 按主机名分目录，缓存目录自己就说明数据来自哪里
        return self.root / self._host(url) / self._key(url)

    def meta_for(self, url):
        return self.root / self._host(url) / f"{self._key(url)}.meta.json"

    def is_fresh(self, url):
        p = self.path_for(url)
        if not p.exists() or p.stat().st_size == 0:
            return False
        age = time.time() - p.stat().st_mtime
        return age < self.ttl_days * 86400

    def get(self, url, refresh=False, label=""):
        """返回本地缓存路径；必要时下载。离线且无缓存时抛 OfflineError。"""
        if not refresh and self.is_fresh(url):
            return self.path_for(url)
        if self.offline:
            if self.path_for(url).exists() and self.path_for(url).stat().st_size:
                return self.path_for(url)
            raise OfflineError(f"离线且无缓存：{label or url}")

        self._throttle(url)
        self.root.mkdir(parents=True, exist_ok=True)
        dest = self.path_for(url)
        tmp = dest.with_suffix(".part")

        last_err = None
        for attempt, backoff in enumerate((0, 1, 4)):
            if backoff:
                time.sleep(backoff)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp, open(tmp, "wb") as out:
                    etag = resp.headers.get("ETag", "")
                    last_mod = resp.headers.get("Last-Modified", "")
                    total = 0
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        total += len(chunk)
                if total == 0:
                    raise OSError("服务端返回 0 字节（该资源可能未发布）")
                tmp.replace(dest)
                self.meta_for(url).write_text(json.dumps({
                    "url": url, "label": label, "bytes": total,
                    "etag": etag, "last_modified": last_mod,
                    "retrieved_at": date.today().isoformat(),
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                return dest
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_err = exc
        raise OfflineError(f"下载失败（已重试 3 次）：{label or url} → {last_err}")

    def _throttle(self, url):
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.time()


# ---------------------------------------------------------------- 适配器基类

class CustomsAdapter:
    name = ""
    requires_network = False
    description = ""

    def available(self, cache=None):
        """返回 (可用?, 人话原因)。"""
        return True, ""

    def fetch(self, query, cache):
        """产出归一化记录 dict；绝不写入 entries/。"""
        raise NotImplementedError

    def print_manual_urls(self, query):
        """零风险交付：给人直接点开的查询链接。"""
        return []


REGISTRY = {}


def register(cls):
    REGISTRY[cls.name] = cls()
    return cls


def get_adapter(name):
    if name not in REGISTRY:
        raise KeyError(f"未知适配器 {name!r}；可用：{', '.join(sorted(REGISTRY))}")
    return REGISTRY[name]


def list_adapters():
    return [REGISTRY[k] for k in sorted(REGISTRY)]


# ---------------------------------------------------------------- 加拿大 ISED CID

@register
class CanadaCIDAdapter(CustomsAdapter):
    """加拿大创新科学与经济发展部「加拿大进口商数据库」(CID)。

    官方开放数据，Open Government Licence – Canada，免费、无需登录、无爬虫条款风险。
    覆盖范围：**只公布主要进口商名称 + HS6 + 城市/省份**，
    没有票数、金额、日期、供应商——所以这些字段一律留空，不假装有。
    这一点会在打分时的 coverage（数据完整度）里如实体现。

    正好匹配「北美主攻」策略里的加拿大一侧。
    """

    name = "canada_cid"
    requires_network = True
    description = "加拿大 ISED 官方进口商数据库（开放数据，免费）"

    CKAN_API = ("https://open.canada.ca/data/api/3/action/package_show"
                "?id=873cfcb0-1c9b-4a48-a366-076697069bb9")
    BASE = "https://ised-isde.canada.ca/site/ised/sites/default/files/documents/"

    # 已核实的资源（2026-09-18 实测：bycountry 在服务端为 0 字节，已剔除）
    RESOURCES = {
        "importers_by_hs6": "cid-bdic-majorimportersbyhs62023.xlsx",
        "hs6_description": "cid-bdic-hs6description2023_0.xlsx",
    }

    # 列名同义词。CID 的实际表头是「英文-法文」双语形式，实测确认：
    #   HS6-SH6 / COMPANY-ENTREPRISE / CITY-VILLE / PROVINCE_ENG / PROVINCE_FRA
    #   / POSTAL_CODE-CODE_POSTAL / DATA_YEAR-ANNÉE_DES_DONNÉES
    COLUMN_SYNONYMS = {
        "buyer_name": ["COMPANY-ENTREPRISE", "COMPANY", "ENTREPRISE", "IMPORTER",
                       "IMPORTER_NAME", "COMPANY_NAME", "NAME", "IMPORTATEUR", "NOM"],
        "hs_code": ["HS6-SH6", "HS6", "HS_CODE", "HSCODE", "SH6", "CODE"],
        "city": ["CITY-VILLE", "CITY", "VILLE", "MUNICIPALITY"],
        "province": ["PROVINCE_ENG", "PROVINCE", "PROV", "PROVINCE_CODE", "REGION"],
        "postal": ["POSTAL_CODE-CODE_POSTAL", "POSTAL", "POSTAL_CODE", "CODE_POSTAL"],
        "country": ["COUNTRY", "COUNTRY_OF_ORIGIN", "ORIGIN", "PAYS"],
        "year": ["DATA_YEAR-ANNÉE_DES_DONNÉES", "DATA_YEAR", "YEAR", "ANNEE"],
    }

    def available(self, cache=None):
        if cache is not None and cache.offline:
            url = self.BASE + self.RESOURCES["importers_by_hs6"]
            if cache.path_for(url).exists() and cache.path_for(url).stat().st_size:
                return True, "离线（使用本地缓存）"
            return False, "离线且无缓存"
        return True, ""

    def _resource_url(self, key):
        return self.BASE + self.RESOURCES[key]

    def discover(self, cache):
        """通过 Open Canada CKAN API 列出真实资源清单（用于核对是否新增了年度版本）。"""
        try:
            path = cache.get(self.CKAN_API, refresh=True, label="Open Canada CKAN 元数据")
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OfflineError, ValueError):
            return []
        out = []
        for r in (data.get("result") or {}).get("resources", []):
            out.append({"name": r.get("name"), "format": r.get("format"), "url": r.get("url")})
        return out

    def _detect_columns(self, header, override=None):
        """把表头映射成内部字段名；override 形如 {'buyer_name': 'IMPORTER NAME'}。"""
        override = override or {}
        norm = {re.sub(r"[^A-Z0-9]", "", str(h or "").upper()): h for h in header}
        mapping = {}
        for internal, syns in self.COLUMN_SYNONYMS.items():
            want = override.get(internal)
            if want:
                mapping[internal] = want
                continue
            for syn in syns:
                k = re.sub(r"[^A-Z0-9]", "", syn.upper())
                if k in norm:
                    mapping[internal] = norm[k]
                    break
        return mapping

    def inspect(self, cache, limit=8):
        """打印表头与前几行，用于首次运行时确认列名。"""
        url = self._resource_url("importers_by_hs6")
        path = cache.get(url, refresh=True, label="CID 主要进口商表")
        sheets = officedoc.read_xlsx_rows(path, max_rows=limit + 1)
        report = []
        for sheet, rows in sheets.items():
            header = rows[0] if rows else []
            report.append({
                "sheet": sheet,
                "columns": header,
                "detected": self._detect_columns(header),
                "sample_rows": rows[1:limit + 1],
            })
        return report

    def fetch(self, query, cache, column_map=None):
        aliases = cn.load_aliases()
        watchlist = cn.load_watchlist()
        url = self._resource_url("importers_by_hs6")
        path = cache.get(url, refresh=query.refresh, label="CID 主要进口商表")

        # HS6 描述表（可选，用于补 product_desc）
        desc = {}
        try:
            dpath = cache.get(self._resource_url("hs6_description"),
                              refresh=query.refresh, label="CID HS6 描述表")
            for rows in officedoc.read_xlsx_rows(dpath).values():
                for row in rows[1:]:
                    if len(row) >= 2 and row[0]:
                        desc[str(row[0]).strip()] = row[1]
        except (OfflineError, OSError, ValueError):
            pass

        wanted_hs6 = set(query.hs6_list())
        wanted_country = set(query.country_list())
        keywords = [k.lower() for k in (query.keywords or [])]
        emitted = 0

        for sheet, rows in officedoc.read_xlsx_rows(path).items():
            if not rows:
                continue
            mapping = self._detect_columns(rows[0], column_map)
            name_col = mapping.get("buyer_name")
            if not name_col:
                continue
            hs_col = mapping.get("hs_code")
            for i, row in enumerate(rows[1:], start=2):
                cells = {}
                for internal, col in mapping.items():
                    try:
                        cells[internal] = row[rows[0].index(col)]
                    except (ValueError, IndexError):
                        cells[internal] = ""
                name = (cells.get("buyer_name") or "").strip()
                if not name:
                    continue

                hs = cn.hs6(cells.get("hs_code"))
                if wanted_hs6 and hs and hs not in wanted_hs6:
                    continue
                if wanted_hs6 and not hs:
                    continue
                if keywords:
                    blob = f"{name} {desc.get(hs, '')}".lower()
                    if not any(k in blob for k in keywords):
                        continue

                rec = blank_record("canada_cid", f"{url}#{sheet}!{i}")
                rec["buyer_name"] = name
                rec["buyer_country"] = "Canada"
                rec["buyer_country2"] = "CA"
                rec["buyer_city"] = (cells.get("city") or "").strip()
                rec["buyer_region"] = (cells.get("province") or "").strip()
                rec["buyer_postal"] = (cells.get("postal") or "").strip()
                rec["hs_code"] = hs or (cells.get("hs_code") or "")
                rec["product_desc"] = desc.get(hs, "")
                rec["raw"] = {"sheet": sheet, "row": i, "cells": cells}

                if wanted_country and "CA" not in wanted_country:
                    continue

                finalize_record(rec, aliases, watchlist)
                yield rec
                emitted += 1
                if query.limit and emitted >= query.limit:
                    return

    def print_manual_urls(self, query):
        hs6s = query.hs6_list() or ["850421", "850422", "850433"]
        urls = []
        for h in hs6s:
            urls.append("https://ised-isde.canada.ca/app/ixb/cid-bdic/"
                        f"searchProduct.html?lang=eng&hsCode={h}")
            urls.append("https://ised-isde.canada.ca/app/ixb/cid-bdic/"
                        f"listByCountry.html?lang=eng&hsCode={h}&countryCode=553")  # 553 = China
        urls.append("https://ised-isde.canada.ca/site/ised/en/research-and-business-intelligence/"
                    "canadian-importers-database")
        return urls


# ---------------------------------------------------------------- 本地文件

# 各平台导出文件的列名预设
PROFILES = {
    "cantonfair": {
        "buyer_name": ["公司名称"],
        "buyer_country": ["来自国家"],
        "product_desc": ["采购产品类别"],
        "contact_name": ["联系人"],
        "contact_email": ["电子邮箱"],
        "contact_phone": ["联系电话"],
        "buyer_address": ["联系地址"],
        "source_ref_col": ["来源文件"],
        "extra": ["届"],
    },
    "importyeti": {
        "buyer_name": ["Consignee", "Consignee Name", "Buyer", "Importer"],
        "buyer_country": ["Consignee Country", "Country"],
        "product_desc": ["Product Description", "Product", "Description"],
        "hs_code": ["HS Code", "HTS", "HS"],
        "supplier_name": ["Supplier", "Shipper", "Manufacturer"],
        "shipment_count": ["Shipments", "Shipment Count", "Total Shipments"],
        "quantity_kg": ["Quantity", "Weight", "Total Weight (kg)"],
        "value_usd": ["Value", "Total Value (USD)"],
        "first_shipment_date": ["First Shipment", "First Shipment Date"],
        "last_shipment_date": ["Last Shipment", "Last Shipment Date"],
    },
    "52wmb": {
        "buyer_name": ["Buyer", "买家", "Importer"],
        "buyer_country": ["Buyer Country", "Country", "国家"],
        "product_desc": ["Product", "Description", "产品描述"],
        "hs_code": ["HS Code", "HS"],
        "supplier_name": ["Supplier", "供应商"],
        "shipment_count": ["Deals", "Transactions", "交易次数"],
        "quantity_kg": ["Weight", "Quantity", "重量"],
        "last_shipment_date": ["Date", "Last Date", "日期"],
    },
    "trademo": {
        "buyer_name": ["Buyer", "Importer", "Consignee"],
        "buyer_country": ["Country", "Buyer Country"],
        "product_desc": ["Product", "Product Description"],
        "hs_code": ["HS", "HS Code", "HSN"],
        "supplier_name": ["Supplier", "Exporter", "Shipper"],
        "shipment_count": ["Shipments", "Count"],
        "value_usd": ["Value", "Value (USD)", "Amount"],
        "last_shipment_date": ["Date", "Last Shipment"],
    },
    "manual": {
        "buyer_name": ["company", "name", "公司"],
        "buyer_country": ["country", "国家"],
        "buyer_region": ["region", "state", "province", "省"],
        "product_desc": ["product", "产品"],
        "hs_code": ["hs", "hs_code"],
        "source_ref_col": ["source", "url", "来源"],
        "contact_email": ["email", "邮箱"],
        "contact_phone": ["phone", "电话"],
        "contact_name": ["contact", "联系人"],
    },
}

# 数值/日期字段，便于统一转型
NUMERIC_FIELDS = {"shipment_count": int, "quantity_kg": float, "value_usd": float}


def _to_number(value, caster):
    if value in (None, "", "NA", "N/A", "-", "null"):
        return 0 if caster is int else 0.0
    s = re.sub(r"[^\d.\-]", "", str(value))
    if not s or s in ("-", "."):
        return 0 if caster is int else 0.0
    try:
        return caster(float(s))
    except ValueError:
        return 0 if caster is int else 0.0


def _norm_date(value):
    """把各种日期写法压成 YYYY-MM-DD；认不出就返回空（不猜）。"""
    s = str(value or "").strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.match(r"^([A-Za-z]{3,9})[-\s](\d{4})$", s)
    if m:
        months = {name: i for i, name in enumerate(
            ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
        mon = months.get(m.group(1)[:3].lower())
        if mon:
            return f"{m.group(2)}-{mon:02d}-01"
    return ""


# 自有成交记录的块解析（公司成单客户 那种自由文本格式）
_OWNED_CUST_RE = re.compile(r"^\s*Customer\s*:\s*(?P<rest>.+)$", re.I)
_OWNED_ADD_RE = re.compile(r"^\s*ADD\s*:\s*(?P<rest>.+)$", re.I)
_OWNED_PROJ_RE = re.compile(r"^\s*Project\s*:\s*(?P<rest>.+)$", re.I)
_OWNED_DATE_RE = re.compile(r"Date\s*:\s*(?P<d>[A-Za-z]{3,9}[-\s]\d{4})", re.I)
_DOMAIN_RE = re.compile(r"\b([A-Za-z0-9\-]+\.(?:ca|com|net|org|cn|us|biz|info))\b", re.I)
_OWNED_PROJ_INLINE_RE = re.compile(r"Project\s*:", re.I)


def _split_inline_project(text):
    """把挤在同一行里的「...地址... Project: 产品」拆开，返回 (地址部分, 产品或 None)。"""
    if not text or not _OWNED_PROJ_INLINE_RE.search(text):
        return text, None
    parts = _OWNED_PROJ_INLINE_RE.split(text, maxsplit=1)
    addr = parts[0].rstrip().rstrip(".").strip()
    proj = parts[1].strip() if len(parts) > 1 else ""
    return addr, (proj or None)


def parse_owned_orders(path):
    """解析「Customer: ... ADD: ... Project: ... Date: ...」块格式的成交记录。

    返回 [{name, website, address, projects: [...], date, block_no}]。
    这是 /Users/eric/Downloads/公司成单客户 的格式。
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    blocks, current = [], []
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    orders = []
    for idx, block in enumerate(blocks, 1):
        name = address = ""
        projects = []
        raw_date = ""
        in_project = False

        for line in block:
            m_date = _OWNED_DATE_RE.search(line)
            if m_date:
                raw_date = raw_date or m_date.group("d")
                line = line[: m_date.start()].rstrip()

            m_cust = _OWNED_CUST_RE.match(line)
            if m_cust:
                rest = m_cust.group("rest").strip()
                # 名称与地址可能挤在一行："ACME Ltd. ADD: 123 Main St"
                for pattern in (r"\.\s*ADD\s*:", r"\s+ADD\s*:"):
                    split = re.split(pattern, rest, maxsplit=1, flags=re.I)
                    if len(split) == 2:
                        name, address = split[0], split[1]
                        break
                else:
                    name = rest
                # 地址后面还可能挤着 "Project: xxx"（源文件里 JS Energy 就是这样）
                address, inline_proj = _split_inline_project(address)
                if inline_proj:
                    projects.append(inline_proj)
                    in_project = True
                else:
                    in_project = False
                continue

            m_add = _OWNED_ADD_RE.match(line)
            if m_add:
                rest = m_add.group("rest").strip()
                addr_part, inline_proj = _split_inline_project(rest)
                address = (address + " " + addr_part).strip() if address else addr_part
                if inline_proj:
                    projects.append(inline_proj)
                    in_project = True
                else:
                    in_project = False
                continue

            m_proj = _OWNED_PROJ_RE.match(line)
            if m_proj:
                in_project = True
                rest = m_proj.group("rest").strip()
                # "ADD: ... Canada. Project: xxx" 挤在同一行的情况
                if ". Project:" in rest or re.search(r"Project\s*:", rest, re.I):
                    parts = re.split(r"Project\s*:", rest, maxsplit=1, flags=re.I)
                    if parts[0].strip():
                        address = (address + " " + parts[0].strip()).strip()
                    rest = parts[1].strip() if len(parts) > 1 else ""
                if rest:
                    projects.append(rest)
                continue

            if in_project and line.strip():
                projects.append(line.strip())

        if not name:
            continue

        name = name.strip().rstrip(".").strip()
        website = ""
        m_dom = _DOMAIN_RE.search(name)
        if m_dom:
            website = m_dom.group(1)
            name = (name[: m_dom.start()] + name[m_dom.end():]).strip().strip(".,").strip()

        orders.append({
            "name": name,
            "website": website,
            "address": re.sub(r"\s+", " ", address).strip().rstrip("."),
            "projects": [p for p in projects if p],
            "date": _norm_date(raw_date),
            "block_no": idx,
        })
    return orders


@register
class LocalCSVAdapter(CustomsAdapter):
    """本地文件适配器：CSV / TSV / XLSX。

    这是离线主力，也是**未来付费平台的入库通道**——
    你自己登录导出文件，交给它解析即可，不需要任何凭据。
    严格流式读取，可处理百万行级名录而内存平稳。
    """

    name = "local_csv"
    requires_network = False
    description = "本地 CSV/TSV/XLSX（平台导出文件、广交会名录、自有成交记录）"

    def __init__(self):
        self.file = None
        self.profile = "manual"
        self.column_map = None

    def configure(self, file=None, profile="manual", column_map=None):
        self.file = file
        self.profile = profile
        self.column_map = column_map or {}
        return self

    # ---- 列映射

    def _resolve_map(self, header):
        preset = PROFILES.get(self.profile, {})
        norm = {re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(h or "").lower()): h for h in header}
        mapping = {}
        for internal, candidates in preset.items():
            want = self.column_map.get(internal)
            if want:
                mapping[internal] = want
                continue
            for cand in candidates:
                k = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(cand).lower())
                if k in norm:
                    mapping[internal] = norm[k]
                    break
        for internal, want in self.column_map.items():
            if internal not in mapping and want:
                mapping[internal] = want
        return mapping

    # ---- 行迭代

    def _iter_rows(self, path):
        """产出 (行号, dict)。CSV/TSV 用流式；XLSX 用 officedoc。"""
        suffix = Path(path).suffix.lower()
        if suffix in (".xlsx", ".xlsm"):
            for sheet, rows in officedoc.read_xlsx_rows(path).items():
                if not rows:
                    continue
                header = rows[0]
                for i, row in enumerate(rows[1:], start=2):
                    yield f"{sheet}!{i}", dict(zip(header, row))
            return

        delim = "\t" if suffix in (".tsv", ".txt") else ","
        with open(path, encoding="utf-8-sig", newline="", errors="replace") as fh:
            reader = csv.DictReader(fh, delimiter=delim)
            for i, row in enumerate(reader, start=2):
                yield f"L{i}", row

    def fetch(self, query, cache=None):
        if not self.file:
            raise ValueError("local_csv 适配器需要 --file 指定文件")

        aliases = cn.load_aliases()
        watchlist = cn.load_watchlist()
        wanted_country = set(query.country_list())
        wanted_cats = [c.lower() for c in (query.categories or [])]
        keywords = [k.lower() for k in (query.keywords or [])]
        wanted_hs6 = set(query.hs6_list())
        emitted = 0
        mapping = None

        for ref, row in self._iter_rows(self.file):
            if mapping is None:
                mapping = self._resolve_map(list(row.keys()))

            def pick(internal):
                col = mapping.get(internal)
                return (row.get(col) or "").strip() if col else ""

            name = pick("buyer_name")
            if not name:
                continue

            # 类别过滤（广交会名录用「采购产品类别」）
            if wanted_cats:
                cat = pick("product_desc").lower()
                if not any(c in cat for c in wanted_cats):
                    continue

            rec = blank_record(self.profile, f"{self.file}#{ref}")
            rec["buyer_name"] = name
            rec["buyer_country"] = pick("buyer_country")
            rec["buyer_region"] = pick("buyer_region")
            rec["buyer_city"] = pick("buyer_city")
            rec["buyer_postal"] = pick("buyer_postal")
            rec["buyer_address"] = pick("buyer_address")
            rec["product_desc"] = pick("product_desc")
            rec["hs_code"] = pick("hs_code")
            rec["supplier_name"] = pick("supplier_name")
            rec["contact_name"] = pick("contact_name")
            rec["contact_email"] = pick("contact_email")
            rec["contact_phone"] = pick("contact_phone")
            rec["first_shipment_date"] = _norm_date(pick("first_shipment_date"))
            rec["last_shipment_date"] = _norm_date(pick("last_shipment_date"))
            for f_, caster in NUMERIC_FIELDS.items():
                rec[f_] = _to_number(pick(f_), caster)
            rec["raw"] = {k: v for k, v in row.items() if v not in (None, "")}

            # 来源列优先用文件里自带的来源字段
            extra_ref = pick("source_ref_col")
            if extra_ref:
                rec["source_ref"] = f"{self.file}#{ref}（{extra_ref}）"

            finalize_record(rec, aliases, watchlist)

            if wanted_country and rec["buyer_country2"] not in wanted_country:
                continue
            if wanted_hs6 and rec["hs_code6"] and rec["hs_code6"] not in wanted_hs6:
                continue
            if keywords:
                blob = f"{name} {rec['product_desc']} {rec['buyer_address']}".lower()
                if not any(k in blob for k in keywords):
                    continue

            yield rec
            emitted += 1
            if query.limit and emitted >= query.limit:
                return


# ---------------------------------------------------------------- 付费平台（占位）

@register
class PaidPortalAdapter(CustomsAdapter):
    """占位适配器：说明付费海关平台的**正确**接入方式。

    明确不做的事：不做凭据登录、不复用浏览器 cookie/session、不抓取页面。
    原因：付费平台的授权条款通常禁止自动化抓取，而且页面改版就会失效；
    更重要的是，你的账号凭据不应该落到脚本里。

    正确流程：
        1. 你在浏览器里登录自己的海关数据平台
        2. 导出 CSV / XLSX
        3. python3 scripts/customs_data_fetch.py --adapter local_csv --file <导出文件> --profile <预设>

    需要的列（有哪列算哪列，缺的会按「未知」处理，不会瞎猜）：
    """

    name = "paid_portal"
    requires_network = False
    description = "付费平台（占位）：请导出文件后用 local_csv 解析"

    REQUIRED_COLUMNS = ["Buyer", "Buyer Country", "Supplier", "Product", "HS Code",
                        "Shipments", "Quantity", "First Shipment", "Last Shipment", "Value"]

    def available(self, cache=None):
        return False, ("未接入。请登录你的付费海关平台 → 导出 CSV/XLSX → "
                       "python3 scripts/customs_data_fetch.py --adapter local_csv "
                       "--file <导出文件> --profile importyeti|trademo|52wmb")

    def fetch(self, query, cache=None):
        raise NotImplementedError(
            "付费平台不通过本适配器联网抓取。请导出文件后改用："
            " --adapter local_csv --file <导出文件> --profile <预设>")

    def print_manual_urls(self, query):
        return [
            "https://www.importyeti.com/",
            "https://www.trademo.com/",
            "https://www.importgenius.com/",
            "https://www.52wmb.com/",
        ]
