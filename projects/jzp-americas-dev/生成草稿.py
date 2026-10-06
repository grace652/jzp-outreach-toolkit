#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发信草稿生成器 v3（HTML + 企业签名 + 输入闸门）
=================================================
🔴 v3 核心变更 —— 「信息不够就不发」（用户 2026-09-27 立规）：

  v2 的问题：只从 CSV 读「公司名 / 收件人 / 邮箱」三列就套模板，
             产出的 52 封本质是 mail-merge 群发件，不符合本项目红线。
             根因是没有任何环节判断「输入够不够写一封个性化开发信」。

  v3 对策：脚本**拒绝为信息不足的客户生成草稿**。每行必须先通过闸门检查
           （见 GATE_REQUIRED），缺关键信息的客户进 "被拦截" 清单，
           不发信、不改模板凑数。想发就先补交接单。

  闸门依据：技能 `jzp-buyer-handover`（项目2 产出标准）§三 合格线闸门

产出：
  发信草稿/_正文/<序号>_<国家>_<公司slug>.html   ← 直接喂 wecom-cli mail send 的 file_path
  发信草稿/_预览/<序号>_<国家>_<公司slug>.md     ← 纯文本预览（人工快速审阅用）
  发信草稿/草稿总览.md
  发信草稿/发送清单.csv
  发信草稿/被拦截清单.md                          ← 🔴 信息不足、必须补交接单的客户

用法：
  python3 生成草稿.py              # 生成（只生成过闸门的）
  python3 生成草稿.py --check      # 只检查配置是否填全
  python3 生成草稿.py --gate-only  # 只跑闸门检查，报告谁被拦截，不生成任何文件
"""

import csv
import html as html_mod
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_typography():
    """加载**唯一**的正文排版模块（字体 Arial / 11pt / 强调加粗）。

    🔴 2026-09-28：字体与加粗规则收敛到 `邮件排版.py` 一处定义，
    本文件不再硬编码 font-family / font-size。
    """
    spec = importlib.util.spec_from_file_location("typo", ROOT / "邮件排版.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["typo"] = mod
    spec.loader.exec_module(mod)
    return mod
# 🔴 2026-09-28 输入清单已被用户删除（上一批 50 家不符合要求，整批撤销）。
# 本脚本**不再自己找客户**——找客户是「找客户 agent」的活，写信是「写开发信 agent」的活。
# 本脚本只在拿到**合格的交接单**之后才生成草稿（分工见 项目流程-邮件开发.md）。
# 保留此常量仅为兼容旧调用；新链路应通过 `--list <清单.csv>` 显式传入。
LIST_CSV = ROOT / "线索资产" / "可直接发送邮箱清单.csv"
# 优先用「内嵌版」签名（图片走 cid，收件人无需点「显示图片」）；
# 没有则退回远程引用版。
_SIG_INLINE = ROOT / "签名_内嵌版.html"
_SIG_REMOTE = ROOT / "签名.html"
SIG_FILE = _SIG_INLINE if _SIG_INLINE.exists() else _SIG_REMOTE
OUT_DIR = ROOT / "发信草稿"
BODY_DIR = OUT_DIR / "_正文"
PREVIEW_DIR = OUT_DIR / "_预览"

# ============================================================
# 配置区
# 前六项已从用户的企业签名中提取；LEAD_TIME 是唯一待填项。
# ============================================================
CONFIG = {
    "SENDER_NAME":   "{{SENDER_NAME}}",
    "SENDER_TITLE":  "Sales Manager",
    "COMPANY_SHORT": "JIEZOU POWER",
    "SENDER_EMAIL":  "{{SENDER_EMAIL}}",
    "SENDER_PHONE":  "{{SENDER_PHONE}}",
    "WEBSITE":       "www.jiezoupower.com",
}

# ============================================================
# 🔴 交期口径（2026-09-27 用户确认：6-8 周）
# ============================================================
# 来源：~/Documents/毅冰-kb/company-profile.md（占位符实参源）
# 历史合同佐证：225KVA 三相美变「确认图纸后 5 周」；1500/3000KVA 美变「6 周」。
# 口径：**自确认图纸起算**（不含发运 35–40 天）。
#
# ⚠️⚠️ 用在哪里——别用错地方（这是本项目最易踩的坑）：
#
#   ❌ 首封（第 1 轮触达）**绝对不报交期**。
#      依据：开发信项目/04_do_not_say.md 第 17 条「不在首封报交期/价格」；
#            开发信项目/02_product_positioning.md §六「首封不报交期/价格 ——
#            钩子是"资料/规格/认证"时，报 8 周会分散焦点。交期留给第 3 轮或对方问价时」。
#            发送开发信.py 的 LEAD_RE 会**直接拦截**含 `\d+ weeks` 的正文。
#
#   ✅ 交期是**第 3 轮及以后**的谈资（对方问了价 / 问了货期才给）。
#      例外：急修/运维类客户（Premier / Oregon / {{COMPANY}}）——
#          02 号文档 §五 允许「卖交期不卖价格」，但那也**不是首封**。
#
#   所以：首封模板里**不出现 LEAD_TIME 变量**。交期只在跟进信模板/人工写第 3 轮时使用。
LEAD_TIME = "6-8"          # 仅供跟进信与人工撰写引用，首封模板不得插入


SUBJECTS = {
    # 首封主题必须落在我方真有的「资料 / 规格 / 认证」钩子上，不落交期价格。
    "en": "UL-listed pad-mount transformers, 25-167 kVA",
    "es": "Transformadores tipo pedestal con certificacion UL",
    "pt": "Transformadores tipo pedestal com certificacao UL",
}

# ============================================================
# 🔴 输入闸门（v3 核心）—— 「信息不够就不发」
# ============================================================
#
# 用户立规（2026-09-27）：不要群发策略，信息不够就不发。
#
# 本闸门判断「这家客户的信息够不够写一封个性化开发信」。
# 判断依据不是 CSV 里有没有这一列，而是**该列内容是否真的能撑起开场句**。
#
# 每个检查项返回 (是否通过, 原因)。任一不通过 → 该客户被拦截，不生成草稿。

# 「规模与备注」至少要多长，才算提供了可用的个性化素材。
# 实测：CSV 里最长的备注是 54 字，最短只有 10 来字。
# 一句话能撑起开场观察的，起码要 25 字以上。
MIN_NOTE_CHARS = 25

# 备注里出现这些词，说明它只是给筛选人看的判断，不是给写信人用的观察素材
JUDGEMENT_ONLY_HINTS = [
    "谨慎使用", "身份未核实", "待核实", "可能上移", "偏大备选", "压线",
]

# 备注里出现这些词，说明它确实含"我为什么找他"型的观察
OBSERVATION_HINTS = [
    "家族", "独立", "批发商", "分销商", "承包商", "服务线", "代理",
    "门店", "连锁", "仓库", "设", "主营", "专做", "覆盖", "网点",
]


def gate_report(row: dict) -> tuple:
    """检查一行名单能否写出一封个性化开发信。

    返回 (ok: bool, reasons: list[str], info: dict)
    """
    reasons = []
    company = (row.get("公司") or "").strip()
    person = (row.get("收件人") or "").strip()
    email = (row.get("邮箱") or "").strip()
    level = (row.get("邮箱等级") or "").strip()
    note = (row.get("备注") or "").strip()

    # ── 1. 邮箱必须存在且不是 D 级 ───────────────────────────
    if not email or "未找到" in email or "未" in email:
        reasons.append("邮箱缺失或未找到（无法发送）")
    elif level.startswith("D"):
        reasons.append(f"邮箱等级 D（未找到有效地址）")

    # ── 2. 收件人必须可称呼（或有明确转交策略）───────────────
    if not person or "未" in person:
        reasons.append("收件人姓名缺失（无法写称呼，需转交策略）")

    # ── 3. 备注必须够长，且不是纯判断语 ──────────────────────
    if len(note) < MIN_NOTE_CHARS:
        reasons.append(
            f"备注仅 {len(note)} 字（<{MIN_NOTE_CHARS}）：不足以支撑开场观察，"
            f"写出来必是群发"
        )
    elif (any(h in note for h in JUDGEMENT_ONLY_HINTS)
          and not any(h in note for h in OBSERVATION_HINTS)):
        reasons.append("备注是筛选人判断语（如「谨慎使用」），非写信素材")

    # ── 4. C 级邮箱需先电话确认 ─────────────────────────────
    if level.startswith("C"):
        reasons.append("邮箱等级 C（免费/通用）：需先电话确认，不能直接发")

    return (not reasons), reasons, {"公司": company, "收件人": person, "邮箱": email,
                                    "邮箱等级": level, "备注": note}

# ---------------- 正文模板（不含签名，签名由 build_html 统一附加） ----------------

T_EN = """Dear {name},

I'm {sender} at {company}, a Chinese manufacturer of liquid-immersed
distribution transformers.

Most distributors here are comparing overseas supply right now, and the
first question is always the same: will the units actually clear UL
inspection.

Ours do. Product lines relevant to you:

- Single-phase pad-mounted, 25-167 kVA
- Three-phase pad-mounted, 75-2,500 kVA
- Substation transformers, up to 500 kV / 480 MVA

We hold UL (E541626, E541627) and build to IEEE C57.12.00/.28/.34/.90.

Would the UL certificates and a spec sheet be useful? Tell me the kVA
rating and voltage class you handle most, and I will send the matching
documents.

If this isn't relevant to you, just say so and I won't write again.

Best regards,"""

T_ES = """Estimado/a {name}:

Mi nombre es {sender} y represento a {company}, fabricante chino de
transformadores de distribucion sumergidos en aceite.

Nuestra linea principal:

- Monofasicos tipo pedestal (pad-mounted), 25 a 167 kVA
- Trifasicos tipo pedestal, 75 a 2.500 kVA
- Transformadores de subestacion, hasta 500 kV / 480 MVA

Contamos con certificacion UL (E541626, E541627) y fabricamos conforme a
las normas IEEE C57.12.00/.28/.34/.90. Tambien trabajamos con clientes
que requieren certificacion local.

Le interesaria recibir los certificados UL y una ficha tecnica? Indiqueme
las capacidades y niveles de tension que manejan habitualmente y le envio
los documentos que correspondan.

Si este mensaje no es de su interes, indiquemelo y no volvere a escribir.

Saludos cordiales,"""

T_PT = """Prezado(a) {name},

Meu nome e {sender} e represento a {company}, fabricante chines de
transformadores de distribuicao imersos em oleo.

Nossa linha principal:

- Monofasicos tipo pedestal (pad-mounted), 25 a 167 kVA
- Trifasicos tipo pedestal, 75 a 2.500 kVA
- Transformadores de subestacao, ate 500 kV / 480 MVA

Possuimos certificacao UL (E541626, E541627) e fabricamos conforme as
normas IEEE C57.12.00/.28/.34/.90.

Um ponto relevante para o Brasil: nossos relatorios UL e CSA sao
emitidos dentro do sistema ILAC, o que permite reaproveitamento na
avaliacao de um OCP brasileiro para a certificacao INMETRO. Isso reduz
bastante o custo e o prazo de certificacao.

Gostaria de receber os certificados UL e uma ficha tecnica? Indique as
potencias e niveis de tensao que voces trabalham com mais frequencia e eu
envio os documentos correspondentes.

Se esta mensagem nao for do seu interesse, basta me avisar que nao
voltarei a escrever.

Atenciosamente,"""

LANG_BY_COUNTRY = {
    "美国": "en", "加拿大": "en",
    "墨西哥": "es", "秘鲁": "es", "哥伦比亚": "es", "智利": "es",
    "巴西": "pt",
}
TPL = {"en": T_EN, "es": T_ES, "pt": T_PT}
FALLBACK_NAME = {"en": "Sir or Madam", "es": "senores", "pt": "senhores"}

NOTE_BY_COUNTRY = {
    # ⚠️ 注意：以下「牌」是**整体市场打法**（跨轮次），不是首封该说的内容。
    #    首封一律只打「资料 / 规格 / 认证」钩子。交期与价格留到第 3 轮。
    "美国": "整体打法：交期 + UL 认证（本土 26–40 周）。首封只给 UL 证书与规格表。⚠️ 不回避中国制造商身份，主动说明边界更可信。",
    "加拿大": "整体打法：CSA/IEEE 标准合规 + 交期（本土 100+ 周）。首封只给认证与规格表。⚠️ Lumen 是魁北克公司，建议改用法语版本。",
    "墨西哥": "整体打法：认证 + 价格。首封只给 UL 证书与规格表。⚠️ 绝不打交期牌——墨西哥本土交期 8–16 周，比进口快。",
    "秘鲁": "整体打法：认证 + 售后响应。首封只给 UL 证书与规格表。矿业客户渠道。",
    "哥伦比亚": "整体打法：认证 + 售后响应。首封只给 UL 证书与规格表。RETIE 认证是主要成本项。",
    "智利": "50Hz 市场，需确认客户是否接受 60Hz 机型或要求定制。首封只给认证与规格表。",
    "巴西": "整体打法：INMETRO 认证成本优势（ILAC 报告可复用）+ 价格。首封只给 UL 证书与规格表。⚠️ 必须葡语。",
}

# 🔴 2026-09-28 统一：字体 / 字号 / 加粗规范**唯一出处**是 `邮件排版.py`。
# 保留 BODY_STYLE 这个名字只为兼容旧引用；值改从该模块取（Arial / 11pt）。
BODY_STYLE = load_typography().BODY_STYLE


def md_to_html(md: str) -> str:
    """把简单 Markdown 片段转成 HTML 片段。

    只处理本生成器实际产出的内容：段落 + 无序列表。

    🔴 2026-09-28 修复：原实现对**段落内所有行**合并为空格，导致结尾块
        Best regards,
        {{SENDER_NAME}}
    被并成一行 `Best regards, {{SENDER_NAME}}`（两行间只有 `\\n`，非 `\\n\\n`），
    违反《正文格式规范.md》§六「固定两行」。

    现规则（与 发送开发信.py: body_to_html 保持一致）：
      · 含 `Best regards` 的块 → **逐行保留换行**（`<br />`）
      · 其余段落 → 仍合并软换行（模板里的换行只是排版折行）
    """
    # 🔴 2026-09-28 统一：实现已收敛到 `邮件排版.py`
    #    （字体 Arial / 11pt / 强调加粗 / 支持 `- ` 列表 / 结尾块逐行保留）。
    #    本函数仅作兼容入口，逻辑不再在此维护。
    return load_typography().text_to_html(md, lists=True)


def build_html(body_md: str, signature: str) -> str:
    """正文 + 签名 → 完整 HTML。

    字体（Arial）、字号（11pt）、强调加粗规则见 `邮件排版.py` —— 唯一出处。
    """
    T = load_typography()
    return T.wrap(T.text_to_html(body_md, lists=True), signature)


def slugify(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s[:48] or "company"


def display_name(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw or "未" in raw or "（" in raw:
        return ""
    return raw


def unfilled() -> list:
    return [k for k, v in CONFIG.items() if "待填" in str(v)]


def main() -> int:
    check_only = "--check" in sys.argv
    gate_only = "--gate-only" in sys.argv
    missing = unfilled()

    if check_only:
        if missing:
            print("未填写的配置项：")
            for k in missing:
                print(f"  - {k}: {CONFIG[k]}")
        else:
            print("配置已填全，可以生成。")
        return 0 if not missing else 1

    if not SIG_FILE.exists() and not gate_only:
        print(f"找不到签名文件：{SIG_FILE}")
        return 1
    signature = SIG_FILE.read_text(encoding="utf-8").strip() if SIG_FILE.exists() else ""

    if not LIST_CSV.exists():
        print(f"⛔ 找不到输入清单：{LIST_CSV}")
        print()
        print("   上一批 50 家名单已由用户撤销删除（2026-09-28）。")
        print("   本脚本**不负责找客户** —— 找客户是「找客户 agent」的职责。")
        print("   正确链路：找客户 agent 产出交接单 → 本脚本据此生成草稿。")
        print("   拿到新的合格名单后再跑。")
        return 1

    rows = list(csv.DictReader(LIST_CSV.open(encoding="utf-8-sig")))

    # ── 跑闸门：分流「可生成」与「被拦截」 ───────────────────
    passed, blocked = [], []
    for r in rows:
        ok, reasons, info = gate_report(r)
        (passed if ok else blocked).append((r, reasons, info))

    # ── --gate-only：只报告，不生成任何文件 ──────────────────
    if gate_only:
        print(f"闸门检查：共 {len(rows)} 行 → 通过 {len(passed)}，拦截 {len(blocked)}\n")
        if blocked:
            print("⛔ 被拦截（信息不足，需先补交接单）：")
            for r, reasons, info in blocked:
                print(f"  · {info['公司']}（{r['国家']}）")
                for why in reasons:
                    print(f"      - {why}")
        if passed:
            print("\n✅ 通过闸门：")
            for r, _, info in passed:
                print(f"  · {info['公司']}（{r['国家']}）")
        return 0

    if not passed:
        print("⛔ 没有任何客户通过闸门 —— 按「信息不够就不发」原则，不生成任何草稿。")
        print(f"   共 {len(blocked)} 家被拦截，见 发信草稿/被拦截清单.md")
        _write_blocked(blocked)
        return 0

    BODY_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    # 🔴 清掉上一轮的产物 —— 否则被拦截客户的旧草稿会残留，
    # 发送脚本仍可能捡走，闸门就形同虚设。
    removed = 0
    for d in (BODY_DIR, PREVIEW_DIR):
        for old in d.glob("*"):
            if old.is_file() and not old.name.startswith("_"):
                old.unlink()
                removed += 1
    if removed:
        print(f"已清理上一轮 {removed} 个旧文件（含被拦截客户的历史草稿）\n")

    manifest, overview = [], []

    for r, _, _info in passed:
        idx = r["序号"].zfill(2)
        country, company = r["国家"], r["公司"]
        person, email = r["收件人"], r["邮箱"].strip()
        prio, note = r["优先级"], r.get("备注", "")

        lang = LANG_BY_COUNTRY.get(country, "en")
        nm = display_name(person) or FALLBACK_NAME[lang]

        # 🔴 首封模板**不含** lead —— 「不在首封报交期/价格」是硬红线
        # （04_do_not_say.md 第 17 条）。交期只在跟进信/第 3 轮用，见文件头 LEAD_TIME 注释。
        body = TPL[lang].format(
            name=nm,
            sender=CONFIG["SENDER_NAME"],
            company=CONFIG["COMPANY_SHORT"],
        )
        subject = SUBJECTS[lang]

        slug = slugify(company)
        (BODY_DIR / f"{idx}_{country}_{slug}.html").write_text(
            build_html(body, signature), encoding="utf-8")
        (PREVIEW_DIR / f"{idx}_{country}_{slug}.md").write_text(
            body, encoding="utf-8")

        manifest.append({
            "序号": idx, "国家": country, "公司": company,
            "收件人": person, "邮箱": email, "优先级": prio,
            "语言": lang, "主题": subject,
            "正文文件": str(BODY_DIR / f"{idx}_{country}_{slug}.html"),
        })
        overview.append((idx, country, company, person, email, prio, lang, subject, note))

    with (OUT_DIR / "发送清单.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0].keys()))
        w.writeheader()
        w.writerows(manifest)

    L = ["# 开发信草稿总览（v3 · HTML + 企业签名 + 输入闸门）", ""]
    L.append(f"- **通过闸门并生成**：{len(manifest)} 封")
    L.append(f"- **被拦截**：{len(blocked)} 封（信息不足，需先补交接单）")
    L.append("- 语言分布：" + "、".join(
        f"{k} {sum(1 for m in manifest if m['语言'] == k)} 封" for k in ["en", "es", "pt"]))
    L.append("- 优先级分布：" + "、".join(
        f"{p} {sum(1 for m in manifest if m['优先级'] == p)} 封" for p in ["A", "B", "C"]))
    L.append("- 正文格式：**HTML**（`content_type=html`），已附加企业签名")
    L.append("")

    if blocked:
        L.append(f"## ⛔ 被拦截 {len(blocked)} 家（信息不够就不发）")
        L.append("")
        L.append("这些客户**没有生成草稿**。想发就必须先补交接单（见技能 `jzp-buyer-handover`）。")
        L.append("")
        L.append("| 公司 | 国家 | 拦截原因 |")
        L.append("|---|---|---|")
        for r, reasons, info in blocked:
            L.append(f"| {info['公司']} | {r['国家']} | {'；'.join(reasons)} |")
        L.append("")

    if missing:
        L.append("## ⚠️ 未填写的配置项（正文里以【待填：…】标出）")
        L.append("")
        for k in missing:
            L.append(f"- `{k}` → {CONFIG[k]}")
        L.append("")
        L.append("**替换后才能发送。** 编辑本脚本顶部 CONFIG 后重跑。")
        L.append("")
    else:
        L.append("## ✅ 配置已填全")
        L.append("")

    L += ["## 发信前必做", "",
          "1. **补 DMARC**：`jiezougroup.com` 与 `jiezoupower.com` 目前都缺 DMARC 记录",
          "2. **不要用主域名发**：建议子域名或第三域名",
          "3. **先发 A 级 + 匹配度 5 分**的十几封，看退信率，再放量",
          "4. **逐封人工过一遍**：模板只保证合规底线，个性化开场仍需按交接单重写",
          "", "---", ""]

    for (idx, country, company, person, email, prio, lang, subject, note) in overview:
        L.append(f"### {idx}. {company}　`{prio}`　`{lang}`")
        L.append("")
        L.append(f"- **收件人**：{person}（{email}）")
        L.append(f"- **国家**：{country}")
        L.append(f"- **主题**：{subject}")
        L.append(f"- **市场策略**：{NOTE_BY_COUNTRY.get(country, '')}")
        if note:
            L.append(f"- **名单备注**：{note}")
        L.append("")

    (OUT_DIR / "草稿总览.md").write_text("\n".join(L), encoding="utf-8")
    _write_blocked(blocked)

    print(f"✅ 已生成 {len(manifest)} 封草稿（HTML + 签名）")
    print(f"  HTML 正文：{BODY_DIR}")
    print(f"  文本预览：{PREVIEW_DIR}")
    print(f"  审阅总览：{OUT_DIR / '草稿总览.md'}")
    print(f"  发送清单：{OUT_DIR / '发送清单.csv'}")
    if blocked:
        print(f"\n⛔ 拦截 {len(blocked)} 家（信息不足，未生成）：")
        for r, reasons, info in blocked:
            print(f"    · {info['公司']}：{reasons[0]}")
        print(f"  详见：{OUT_DIR / '被拦截清单.md'}")
    if missing:
        print(f"\n⚠️  仍有 {len(missing)} 项未填：{'、'.join(missing)}")
    return 0


def _write_blocked(blocked: list) -> None:
    """写被拦截清单 —— 这些客户要补交接单才能进入写信环节。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    L = ["# 被拦截清单 · 信息不够就不发", "",
         f"> 生成时间：自动 | 共 **{len(blocked)}** 家客户因信息不足被拦截。", "",
         "**处理原则（用户 2026-09-27 立规）：不要群发策略，信息不够就不发。**", "",
         "这些客户**没有生成任何草稿**。想发必须先补交接单 ——",
         "见技能 `jzp-buyer-handover`（项目2 产出标准）。", "",
         "| 公司 | 国家 | 收件人 | 邮箱等级 | 拦截原因 |",
         "|---|---|---|---|---|"]
    for r, reasons, info in blocked:
        L.append(f"| {info['公司']} | {r['国家']} | {info['收件人']} | "
                 f"{info['邮箱等级']} | {'；'.join(reasons)} |")
    L.append("")
    L.append("## 补交接单后怎么回到发信流程")
    L.append("")
    L.append("1. 按 `jzp-buyer-handover` 产出一份 `买家N_公司名_开发信交接单.md`")
    L.append("2. 过完 §三 八条合格线闸门")
    L.append("3. 把该客户从 `可直接发送邮箱清单.csv` 移除，改走交接单 → 写开发信流程")
    L.append("")
    (OUT_DIR / "被拦截清单.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
