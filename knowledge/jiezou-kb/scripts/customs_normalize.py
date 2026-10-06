#!/usr/bin/env python3
"""海关/线索数据的基础归一化工具：公司名、国家、HS 码、供应商角色、行业关键词。

不联网、不读写知识库条目，纯函数 + 两张可编辑的种子表：
    data/company_aliases.csv      别名 → 规范名
    data/watchlist_suppliers.csv  供应商 → 角色（self / competitor / partner / other）

被 customs_adapters.py 与 lead_scoring.py 共用。
"""
import csv
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ALIAS_PATH = DATA_DIR / "company_aliases.csv"
WATCHLIST_PATH = DATA_DIR / "watchlist_suppliers.csv"

# ---------------------------------------------------------------- 公司名归一化

# 循环剥离的尾部法律后缀（英文名才有意义；中文名后缀有实义，跳过）
LEGAL_SUFFIXES = [
    "INCORPORATED", "INC", "LLC", "L.L.C", "LTD", "LIMITED", "CORPORATION", "CORP",
    "COMPANY", "CO", "GMBH", "S.A", "SA", "BV", "B.V", "NV", "N.V", "PTY", "PLC",
    "SRL", "S.R.L", "SPA", "AG", "AS", "OY", "AB", "KK", "PTE", "ULC", "LP", "LLP",
    "PLLC", "PC", "DBA", "USA", "US",
]
_LEGAL_SET = set(LEGAL_SUFFIXES)

_PUNCT_RE = re.compile(r"[.,'\"\-/\\()\[\]#:;*&+]")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def normalize_company(name):
    """把公司名压成可比较的规范形式（大写、去标点、去法律后缀）。

    含中日韩字符时跳过「去前导 THE」与「剥离法律后缀」两步——
    「有限公司」这类后缀在中文里是有实义的。
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name))
    # 去变音符
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.upper()
    s = s.replace("&", " AND ").replace("+", " AND ")
    s = _PUNCT_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()

    if _CJK_RE.search(s):
        return s

    if s.startswith("THE "):
        s = s[4:]

    # 循环剥离尾部后缀，例如 "ACME SUPPLY CO LTD" -> "ACME SUPPLY"
    changed = True
    while changed:
        changed = False
        for suf in LEGAL_SUFFIXES:
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                changed = True
                break
    return s


# 内置别名种子（CSV 可覆盖/追加）。都是真实出现过的拼写错位。
DEFAULT_ALIASES = {
    "DOMINO HIGHVOLTAGE": "DOMINO HIGHVOLTAGE SUPPLY",
    "JIANGSU JIEZOU INTERNATIONAL TRADING": "JIEZOU",
    "SUZHOU JIEZOU POWER": "JIEZOU",
    "JIEZOU POWER TRANSFORMER": "JIEZOU",
    "JIANGSU YAWEI TRANSFORMER": "YAWEI TRANSFORMER",
    "JIANGSU YAWEI TRANSFORMER CO": "YAWEI TRANSFORMER",
    "YAWEI": "YAWEI TRANSFORMER",
}


def load_aliases(path=None):
    """读取别名表；文件不存在时用内置种子。"""
    aliases = dict(DEFAULT_ALIASES)
    path = Path(path) if path else ALIAS_PATH
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                key = normalize_company(row.get("alias_key") or row.get("alias") or "")
                val = normalize_company(row.get("canonical_key") or row.get("canonical") or "")
                if key and val:
                    aliases[key] = val
    return aliases


def company_key(name, aliases=None):
    """归一化 + 查别名，得到跨来源一致的比对键。"""
    norm = normalize_company(name)
    if not norm:
        return ""
    if aliases is None:
        aliases = load_aliases()
    return aliases.get(norm, norm)


# ---------------------------------------------------------------- 供应商角色

DEFAULT_WATCHLIST = {
    "JIEZOU": ("结奏/杰走（我方）", "self"),
    "YAWEI TRANSFORMER": ("江苏亚威变压器", "competitor"),
    "CHINT ELECTRIC INTERNATIONAL": ("正泰", "competitor"),
    "TBEA": ("特变电工", "competitor"),
    "XINXIANG WEIYING MACHINERY": ("新乡威影机械", "other"),
    "LINKWELL ELECTRIC": ("联威电气", "other"),
}


def load_watchlist(path=None):
    """读取供应商名单，返回 {归一化键: (label, role)}。"""
    watch = {k: v for k, v in DEFAULT_WATCHLIST.items()}
    path = Path(path) if path else WATCHLIST_PATH
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                key = normalize_company(row.get("supplier_key") or "")
                role = (row.get("role") or "").strip().lower()
                if key and role:
                    watch[key] = (row.get("label") or key, role)
    return watch


def supplier_role(name, watchlist=None):
    """返回 (role, label)。role ∈ self/competitor/partner/other/""。"""
    norm = normalize_company(name)
    if not norm:
        return "", ""
    if watchlist is None:
        watchlist = load_watchlist()
    if norm in watchlist:
        return watchlist[norm][1], watchlist[norm][0]
    # 名称里出现已知关键词也算命中（如 "JIANGSU YAWEI TRANSFORMER CO., LTD."）
    for key, (label, role) in watchlist.items():
        if key and key in norm:
            return role, label
    return "", ""


# ---------------------------------------------------------------- 国家 / 地区

COUNTRY2 = {
    "USA": "US", "UNITED STATES": "US", "U.S.A": "US", "U.S": "US", "AMERICA": "US",
    "CANADA": "CA", "MEXICO": "MX", "CHINA": "CN", "ANGUILLA": "AI",
    "PUERTO RICO": "PR", "DOMINICAN REPUBLIC": "DO", "TRINIDAD AND TOBAGO": "TT",
    "JAMAICA": "JM", "BAHAMAS": "BS", "BARBADOS": "BB", "BELIZE": "BZ",
    "GUATEMALA": "GT", "HONDURAS": "HN", "PANAMA": "PA", "COSTA RICA": "CR",
    "UNITED KINGDOM": "GB", "GERMANY": "DE", "INDIA": "IN", "VIETNAM": "VN",
    "UZBEKISTAN": "UZ", "PHILIPPINES": "PH", "ECUADOR": "EC", "TANZANIA": "TZ",
    "KENYA": "KE", "AUSTRALIA": "AU", "UNITED ARAB EMIRATES": "AE",
}

# 国家名 → 2 位码的别名（含常见缩写）
COUNTRY_ALIASES = {
    "US": "US", "U.S.": "US", "U.S.A.": "US", "UNITED STATES OF AMERICA": "US",
    "CA": "CA", "CAN": "CA", "CAN.": "CA", "MEX": "MX", "CN": "CN", "CHN": "CN",
    "UK": "GB", "GB": "GB", "UAE": "AE",
}

US_STATES = set("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS
MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR""".split())

CA_PROVINCES = set("AB BC MB NB NL NS NT NU ON PE QC SK YT".split())

REGION_NAMES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "ALBERTA": "AB", "BRITISH COLUMBIA": "BC", "MANITOBA": "MB",
    "NEW BRUNSWICK": "NB", "NEWFOUNDLAND AND LABRADOR": "NL", "NOVA SCOTIA": "NS",
    "ONTARIO": "ON", "PRINCE EDWARD ISLAND": "PE", "QUEBEC": "QC",
    "SASKATCHEWAN": "SK",
}


# 省/州码 → 可读名称（用于条目里展示）
REGION_LABEL = {code: name.title() for name, code in REGION_NAMES.items()}


# 中文国家/地区名 → 2 位码。广交会名录等中文来源用这个。
CJK_COUNTRY = {
    "美国": "US", "加拿大": "CA", "墨西哥": "MX", "中国": "CN",
    "中国香港": "HK", "香港": "HK", "中国台湾": "TW", "中国澳门": "MO",
    "安圭拉": "AI", "波多黎各": "PR", "多米尼加": "DO",
    "特立尼达和多巴哥": "TT", "牙买加": "JM", "巴哈马": "BS", "巴巴多斯": "BB",
    "伯利兹": "BZ", "危地马拉": "GT", "洪都拉斯": "HN", "巴拿马": "PA",
    "哥斯达黎加": "CR", "古巴": "CU", "海地": "HT",
    "巴西": "BR", "智利": "CL", "秘鲁": "PE", "哥伦比亚": "CO", "阿根廷": "AR",
    "委内瑞拉": "VE", "厄瓜多尔": "EC", "玻利维亚": "BO", "巴拉圭": "PY", "乌拉圭": "UY",
    "英国": "GB", "法国": "FR", "德国": "DE", "意大利": "IT", "西班牙": "ES",
    "葡萄牙": "PT", "荷兰": "NL", "比利时": "BE", "爱尔兰": "IE", "希腊": "GR",
    "瑞典": "SE", "挪威": "NO", "丹麦": "DK", "芬兰": "FI", "瑞士": "CH",
    "奥地利": "AT", "波兰": "PL", "捷克": "CZ", "匈牙利": "HU", "罗马尼亚": "RO",
    "俄罗斯": "RU", "乌克兰": "UA", "土耳其": "TR", "以色列": "IL",
    "日本": "JP", "韩国": "KR", "印度": "IN", "巴基斯坦": "PK", "孟加拉国": "BD",
    "斯里兰卡": "LK", "泰国": "TH", "越南": "VN", "马来西亚": "MY",
    "新加坡": "SG", "印度尼西亚": "ID", "菲律宾": "PH",
    "澳大利亚": "AU", "新西兰": "NZ",
    "阿联酋": "AE", "沙特阿拉伯": "SA", "伊朗": "IR", "伊拉克": "IQ",
    "科威特": "KW", "卡塔尔": "QA", "阿曼": "OM", "约旦": "JO", "黎巴嫩": "LB",
    "南非": "ZA", "埃及": "EG", "尼日利亚": "NG", "摩洛哥": "MA", "阿尔及利亚": "DZ",
    "突尼斯": "TN", "埃塞俄比亚": "ET", "肯尼亚": "KE", "坦桑尼亚": "TZ",
    "乌干达": "UG", "加纳": "GH", "津巴布韦": "ZW", "赞比亚": "ZM",
    "莫桑比克": "MZ", "安哥拉": "AO", "乌兹别克斯坦": "UZ", "哈萨克斯坦": "KZ",
}

# 从文本里找国家名时，长的优先（避免「中国香港」被「中国」抢先匹配）
_CJK_COUNTRY_SORTED = sorted(CJK_COUNTRY.items(), key=lambda kv: -len(kv[0]))
_EN_COUNTRY_SORTED = sorted(
    set(list(COUNTRY2) + list(COUNTRY_ALIASES)), key=len, reverse=True)


def country2_of(*texts):
    """从若干文本片段里推断 2 位国家码，推断不出返回 ""。

    同时支持英文名（United States / USA）与中文名（美国），并且容忍
    来源里常见的脏数据，例如「美        国.」这种夹空格带句点的写法。
    """
    raw = " ".join(str(t or "") for t in texts).upper()
    # 保留 CJK 与常用标点，其余转空格
    blob = re.sub(r"[^A-Z0-9\u4e00-\u9fff .,'\-]", " ", raw)
    # 紧凑版：去掉所有空白与句点，专治「美        国.」
    compact = re.sub(r"[\s.·]+", "", blob)

    # 1) 中文国家名（在紧凑版上匹配，长的优先）
    for name, code in _CJK_COUNTRY_SORTED:
        if name in compact:
            return code

    # 2) 英文国家名/别名
    for name in _EN_COUNTRY_SORTED:
        if re.search(rf"(?<![A-Z]){re.escape(name)}(?![A-Z])", blob):
            return COUNTRY2.get(name) or COUNTRY_ALIASES.get(name) or ""

    # 3) 州/省名全称
    for name, code in sorted(REGION_NAMES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![A-Z]){re.escape(name)}(?![A-Z])", blob):
            return "CA" if code in CA_PROVINCES else "US"

    # 4) 两字母州/省码
    for tok in re.findall(r"(?<![A-Z])([A-Z]{2})(?![A-Z])", blob):
        if tok in CA_PROVINCES:
            return "CA"
        if tok in US_STATES:
            return "US"
    return ""


def region_of(*texts):
    """从文本里找州/省码，找不到返回 ""。"""
    blob = " ".join(str(t or "") for t in texts).upper()
    for name, code in sorted(REGION_NAMES.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"(?<![A-Z]){re.escape(name)}(?![A-Z])", blob):
            return code
    for tok in re.findall(r"(?<![A-Z])([A-Z]{2})(?![A-Z])", blob):
        if tok in US_STATES or tok in CA_PROVINCES:
            return tok
    return ""


TARGET_MARKETS = {"US", "CA"}
SECONDARY_MARKETS = {"MX", "PR", "DO", "TT", "JM", "BS", "BB", "BZ", "GT", "HN", "PA", "CR"}


# ---------------------------------------------------------------- HS 码

HS_STRONG = {"850421", "850422", "850423"}          # 液浸变压器（我方主力）
HS_OTHER_XFMR = {"850431", "850432", "850433", "850434"}   # 其他变压器
HS_PARTS = {"850490"}


def hs_digits(code):
    """抽出 HS 码里的数字部分。"""
    return re.sub(r"\D", "", str(code or ""))


def hs6(code):
    d = hs_digits(code)
    return d[:6] if len(d) >= 6 else ""


def hs4(code):
    d = hs_digits(code)
    return d[:4] if len(d) >= 4 else ""


def is_transformer_hs(code):
    return hs4(code) == "8504"


# ---------------------------------------------------------------- 行业 / 贸易商关键词

INDUSTRY_KEYWORDS = [
    "ELECTRIC", "ELECTRICAL", "POWER", "ENERGY", "UTILITY", "UTILITIES", "TRANSFORMER",
    "SUBSTATION", "GRID", "SOLAR", "WIND", "BATTERY", "BESS", "GENERATOR", "ENGINEERING",
    "CONTRACTOR", "CONTRACTING", "CONSTRUCTION", "INFRASTRUCTURE", "RENEWABLE",
    "TRANSMISSION", "DISTRIBUTION", "SWITCHGEAR", "LIGHTING", "MECHANICAL", "INDUSTRIAL",
    "ELECTRICITY", "ELECTRIFICATION", "MICROGRID", "DATACENTER", "DATA CENTER",
    "FOODS", "MINING", "MINERALS", "CEMENT", "PULP", "PAPER", "STEEL", "CHEMICAL",
]

# 与变压器采购**强相关**的行业词。判定「是不是终端买家」时用这一份——
# 用宽泛的 INDUSTRY_KEYWORDS 会把化学品、食品公司也算成买家，噪音太大。
STRONG_INDUSTRY_KEYWORDS = [
    "ELECTRIC", "ELECTRICAL", "ELECTRICITY", "ELECTRIFICATION", "POWER", "ENERGY",
    "UTILITY", "UTILITIES", "TRANSFORMER", "SUBSTATION", "SWITCHGEAR", "SWITCHBOARD",
    "GRID", "MICROGRID", "TRANSMISSION", "DISTRIBUTION", "GENERATOR", "GENERATION",
    "SOLAR", "WIND", "BATTERY", "BESS", "RENEWABLE", "HYDRO", "NUCLEAR",
    "CONTRACTOR", "CONTRACTING", "ENGINEERING", "ELECTRO", "VOLT", "KVA",
]

TRADER_KEYWORDS = [
    "TRADING", "IMPORT", "IMPORTS", "EXPORT", "EXPORTS", "ENTERPRISE", "ENTERPRISES",
    "MARKETING", "COMMODITIES", "RESOURCES", "HOLDINGS", "HOLDING", "INVESTMENT",
    "INVESTMENTS", "LOGISTICS", "FREIGHT", "FORWARDER", "SUPPLY CHAIN", "SOURCING",
    "GENERAL TRADING", "MERCHANDISE", "MERCHANTS",
]

FREEMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "aol.com", "outlook.com", "live.com",
    "qq.com", "163.com", "126.com", "sina.com", "foxmail.com", "icloud.com",
    "mail.com", "gmx.com", "yandex.com", "protonmail.com",
}

# 知名变压器 OEM / 同业厂商。它们出现在进口商名单里通常是因为承接项目自供，
# 而不是「来买变压器的终端客户」。**不扣分**，只打标签，
# 让你在 leads/index.md 里能一眼区分「同业」和「真买家」。
KNOWN_TRANSFORMER_OEM = [
    "SIEMENS", "HITACHI", "ABB", "GE ", "GENERAL ELECTRIC", "PROLEC", "WEG ",
    "SCHNEIDER", "EATON", "HYUNDAI", "MITSUBISHI", "TOSHIBA", "CG POWER",
    "HYOSUNG", "TBEA", "CHINT", "MADDox", "HAMMOND POWER", "VIRGINIA TRANSFORMER",
    "NIAGARA TRANSFORMER", "PIONEER TRANSFORMER", "OLTC", "REXEL", "SONEPAR",
    "WESCO", "GRAINGER", "POWELL INDUSTRIES",
]


def is_known_oem(name):
    up = f" {str(name or '').upper()} "
    return [k.strip() for k in KNOWN_TRANSFORMER_OEM if k in up]


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-.]?)?(?:\(\d{2,4}\)[\s\-.]?)?\d{3,4}[\s\-.]?\d{3,4}[\s\-.]?\d{0,4}")


def looks_like_trader(name, emails=(), product_desc=""):
    """贸易中间商启发式，返回 (是否命中, 命中的证据列表)。"""
    evidence = []
    upper = str(name or "").upper()
    if any(kw in upper for kw in TRADER_KEYWORDS):
        evidence.append("名称含贸易类词")
    if not any(kw in upper for kw in INDUSTRY_KEYWORDS):
        evidence.append("名称无行业词")
    for e in emails or ():
        domain = str(e).split("@")[-1].lower().strip()
        if domain in FREEMAIL_DOMAINS:
            evidence.append(f"仅免费邮箱域名（{domain}）")
            break
    if product_desc:
        chapters = {hs6(x)[:2] for x in re.findall(r"\b\d{6,10}\b", str(product_desc))}
        chapters.discard("")
        if len(chapters) >= 3:
            evidence.append(f"产品描述跨 {len(chapters)} 个 HS 章")
    return len(evidence) >= 2, evidence
