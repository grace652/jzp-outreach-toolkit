#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发信发送器（信件 → 正文 + 图片签名 → 发送）
==============================================
把 `开发信项目/clients/开发信-*.md` 里的【正文】抽出来，
自动附加 `签名_内嵌版.html`（图片走 CID 内嵌），然后发送。

正文格式依据：`开发信项目/正文格式规范.md`
  - 正文止于 `{{SENDER_NAME}}`，不带职务/邮箱/电话行
  - 签名由本脚本自动追加

用法
----
  python3 发送开发信.py --list                    # 列出所有可用信件
  python3 发送开发信.py --dry-run Codale          # 预演（不发送）
  python3 发送开发信.py --send --to {{CONTACT_EMAIL}} Codale   # 【测试】重定向到自己
  python3 发送开发信.py --send Codale             # 真正发送（发给信里指定收件人）
  python3 发送开发信.py --send --subject-index 2 Codale

安全闸
------
  1. 不加 --send 绝不发送
  2. 加 --send 但不加 --yes 需输入 yes 确认
  3. `--to` 重定向：测试时强制发到指定地址，绝不发给真实客户
  4. 正文含【待填…】直接拒绝
  5. 发送前跑红线自检（禁用认证 / YAWEI / spam 词 / 交期 / 价格 / 退订句）
"""

import argparse
import html as html_mod
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENTS = ROOT / "开发信项目" / "clients"
FORMAT_SPEC = ROOT / "开发信项目" / "正文格式规范.md"

# 收件人从信件批注里读
#   旧格式：`主送 \`xxx@yyy\``
#   新格式：`- **收件人**：**{{CONTACT_NAME}} · President**（\`{{CONTACT_EMAIL}}\`）`
RECIPIENT_RE = re.compile(r"主送\s*`([^`]+@[^`]+)`")
RECIPIENT_NEW_RE = re.compile(r"\*\*收件人\*\*[：:].*?`([^`]+@[^`]+)`")
# 🔴 2026-09-28 新增（Format C / batch5「129plus」批注体）：正文批注里
# 邮箱写在「- **邮箱档位**：**A** — `mario@…`（说明）」这种**行内破折号**句式里，
# 既没有 `主送 \`…\`` 也没有 `**收件人**：`，故前两条正则全部落空 → 收件人 = []。
# 该式样只认「邮箱档位」行后的第一个反引号邮箱，避免误抓正文里的其它地址。
# 🔴 2026-09-29 放宽：原正则硬要求 `**邮箱档位**`（带粗体标记），
#    实测有信件写成 **不加粗** 的 `- 邮箱档位：**B（…）** → 收件 `xxx@yyy``，
#    导致收件人 = [] → 该信**永远排不进队列**（Graybar Canada / Amtek 两封实测）。
#    改为 `\*{0,2}`，兼容加粗与不加粗两种写法（只会**新增**命中，不改动原有行为）。
RECIPIENT_LINE_RE = re.compile(
    r"^[-*\s]*\*{0,2}邮箱档位\*{0,2}[^\n]*?`([^`]+@[^`]+)`", re.M)

# 正文 ``` 围栏块（部分格式把正文包在代码块里）
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)

# ---------------- 红线自检 ----------------
BAD_CERT = ["CSA Certified", "SASO", "SONCAP", "cUL and CSA"]
SPAM = ["free", "discount", "best price", "limited time", "click here",
        "guarantee", "100%", "!!!"]
UNSUB_MARKERS = ["won't write again", "close the loop", "won't follow up",
                 # 🔴 2026-09-28 新增：batch5 写信 agent 实际输出的是
                 # **will not / do not** 全拼形式（非缩写），且常带条件状语
                 # 「If this is not a fit, …」「If not relevant, …」。
                 # 原表只有缩写式，导致 129/130 两封**明明写了退订句却报「缺退订句」**。
                 "will not write again",       # 130 T&N 实际写法
                 "will not follow up",         # 129 Martech 实际写法
                 "do not follow up",
                 "will not write", "will not follow",
                 "do not write", "do not contact",
                 "won't contact", "will not contact",
                 "no further emails", "stop here",
                 # 本项目有西语/葡语模板，退订句是外文的，
                 # 只列英文短语会把所有非英语信件误判为「缺退订句」。
                 "no volvere a escribir",      # es
                 "nao voltarei a escrever",    # pt（无重音写法，模板实际用这个）
                 "não voltarei a escrever",    # pt（带重音，防日后改动）
                 "won't write", "no volvere", "nao voltarei"]
LEAD_RE = re.compile(r"\b\d+\s*(?:-|to|–)?\s*\d*\s*weeks?\b", re.I)
PRICE_RE = re.compile(r"\b(price|quote|quotation|FOB|USD|discount|MOQ)\b", re.I)
SIGN_LINE = "JZPE POWER TRANSFORMER CO., LTD."


def load_mailer():
    spec = importlib.util.spec_from_file_location("mailer", ROOT / "邮箱客户端.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mailer"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_typography():
    """加载**唯一**的正文排版模块（字体 Arial / 11pt / 强调加粗）。

    🔴 2026-09-28：字体与加粗规则收敛到 `邮件排版.py` **一处定义**，
    本文件不再硬编码 font-family / font-size，避免与其它发送链路漂移。
    """
    spec = importlib.util.spec_from_file_location("typo", ROOT / "邮件排版.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["typo"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_signature():
    f = ROOT / "签名_内嵌版.html"
    if not f.exists():
        f = ROOT / "签名.html"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def parse_letter(p: Path):
    """返回 (subjects: list, body: str, notes: str)
    支持三套标记（2026-09-28 扩展到三套）：
      A. 纯标记（正文格式规范.md §六 范例）：【Subject 备选】/【正文】/【中文批注】
      B. 新格式（batch5 起）：`## 一、主题行` / `## 二、正文` / `## 三、中文注解`
      C. Markdown 标题包裹的标记（买家 129/130 用）：
         `## 【Subject 备选】` / `## 【正文】（…）` / `## 【中文批注】`

    ⚠️ A 与 C 内容一样，差别只在**标记行是否带 `## ` 前缀与行尾说明**。
    原正则要求 `【正文】\n` 紧邻，故 C 会解析出空正文（词数 0）→ 静默不发送。
    现将标记行统一放宽为「行首可有 `#{1,6} `、行尾可有说明括号」。
    """
    t = p.read_text(encoding="utf-8")
    # 标记行放宽：可选 `## ` 前缀 + 可选行尾 `（…）` 说明
    def _mark(tag):
        return rf"^[#\s]*【{tag}】[^\n]*\n"
    m_sub = re.search(_mark("Subject 备选") + r"(.*?)(?=" + _mark("正文") + r")",
                      t, re.S | re.M)
    m_body = re.search(_mark("正文") + r"(.*?)(?=" + _mark("中文批注") + r")",
                       t, re.S | re.M)
    m_note = re.search(_mark("中文批注") + r"(.*)$", t, re.S | re.M)

    subjects = []
    if m_sub:
        seg = m_sub.group(1)
        # 兼容两种主题行写法：`1. 纯文本` 与 `1. \`带反引号\``
        for line in seg.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^\d+[.、)]\s*", "", line)
            mm = re.match(r"^`([^`]+)`$", line)
            subjects.append(mm.group(1).strip() if mm else line)

    body = m_body.group(1).strip() if m_body else ""
    notes = m_note.group(1).strip() if m_note else ""

    # 正文可能被 ``` 围栏包裹 → 拆掉围栏，并去掉可能的 `Subject:` 首行
    if body and "```" in body:
        fm = FENCE_RE.search(body)
        if fm:
            body = fm.group(1).strip()
        lines = body.split("\n")
        if lines and lines[0].strip().lower().startswith("subject:"):
            body = "\n".join(lines[1:]).strip()

    # ---- 新格式回退（## 一、主题行 / ## 二、正文 / ## 三、中文注解）----
    if not body:
        return _parse_letter_new_format(t)
    return subjects, body, notes


# 新格式：标题行 `## 一、主题行（3 选 1）` —— 括号里是可变说明，故只锚定前缀
NEW_SUBJ_RE = re.compile(r"^##\s*一、主题行[^\n]*\n(.*?)(?=^##\s|\Z)", re.S | re.M)
NEW_BODY_RE = re.compile(r"^##\s*二、正文[^\n]*\n(.*?)(?=^##\s|\Z)", re.S | re.M)
NEW_NOTE_RE = re.compile(r"^##\s*三、中文注解[^\n]*\n(.*?)(?=^##\s|\Z)", re.S | re.M)
# 主题行形如： 1. `Transformer supply — 150 to 1200 kVA`
NEW_SUBJ_LINE_RE = re.compile(r"^\s*\d+\.\s*`([^`]+)`\s*$", re.M)
# 正文代码块 ``` ... ```
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def _parse_letter_new_format(t: str):
    """解析 `## 一、主题行` / `## 二、正文` / `## 三、中文注解` 结构。"""
    subjects = []
    m = NEW_SUBJ_RE.search(t)
    if m:
        # 只取「N. `...`」形式的行；其后的 `> 选型说明` 引用块自动被忽略
        subjects = [s.strip() for s in NEW_SUBJ_LINE_RE.findall(m.group(1))]

    body = notes = ""
    m = NEW_BODY_RE.search(t)
    if m:
        seg = m.group(1)
        # 正文在 ``` 围栏内；取第一个围栏块，去掉可能存在的 `Subject:` 首行
        fm = FENCE_RE.search(seg)
        raw = (fm.group(1) if fm else seg)
        lines = raw.strip().split("\n")
        if lines and lines[0].strip().lower().startswith("subject:"):
            lines = lines[1:]
        body = "\n".join(lines).strip()

    m = NEW_NOTE_RE.search(t)
    if m:
        notes = m.group(1).strip()
    return subjects, body, notes


def trim_signature_tail(body: str) -> str:
    """裁掉正文尾部的「职务 / 公司 / 邮箱」行，只保留到 `{{SENDER_NAME}}`。

    依据 `正文格式规范.md` §一 与 §六（2026-09-27 用户定稿）：
        `{{SENDER_NAME}}` 与图片签名之间：**零内容**。
        职务、公司名、联系方式一律由第 ⑦ 段的图片签名承担。

    但 batch5 起的一批信件在正文块里仍写了旧式四行：
        Best regards, / {{SENDER_NAME}} / Sales Manager / JZPE POWER ... / ian@...
    本函数在**发送层**裁掉 `{{SENDER_NAME}}` 之后的非空行，**不改动信件文件**。

    只认 `{{SENDER_NAME}}`（署名主体），不误伤正文里出现的其他 `{{SENDER_NAME}}`：
    从**最后一个** `{{SENDER_NAME}}` 行往后切。
    """
    lines = body.rstrip().split("\n")
    last = None
    for i, l in enumerate(lines):
        if l.strip() == "{{SENDER_NAME}}":
            last = i
    if last is None:
        return body
    return "\n".join(lines[:last + 1]).rstrip()



def recipients_of(notes: str) -> list:
    """按优先级依次尝试三种批注体提取收件人邮箱。

    三种格式（按项目演化顺序）：
      ① 旧格式    `主送 \\`xxx@yyy\\``
      ② 新格式    `- **收件人**：**姓名 · 职务**（\\`xxx@yyy\\`）`
      ③ batch5 体  `- **邮箱档位**：**A** — \\`xxx@yyy\\`（验证说明）`
    """
    for rx in (RECIPIENT_RE, RECIPIENT_NEW_RE, RECIPIENT_LINE_RE):
        found = rx.findall(notes)
        if found:
            return [e.strip() for e in found]
    return []


# 抄送行：`- **抄送**：`{{CONTACT_EMAIL}}`、`{{CONTACT_EMAIL}}`` ／ 无抄送时写 `—`
CC_RE = re.compile(r"^[-*\s]*\*\*抄送\*\*[：:]\s*(.+)$", re.M)


def cc_of(notes: str) -> list:
    """从批注里提取**抄送**地址（2026-09-28 新增）。

    背景：此前链路**完全没有抄送能力**（队列无 cc 字段、发送不带 cc），
    导致 ALCO / ALB / GEC 等需要抄送 PM、办公室主管的信只能漏掉抄送。
    跟进信批次起补齐。

    兼容写法：`—` / `-` / `无` 一律视为无抄送。
    """
    m = CC_RE.search(notes)
    if not m:
        return []
    seg = m.group(1).strip()
    if seg in ("—", "-", "无", "None", ""):
        return []
    return [e.strip() for e in re.findall(r"`([^`]+@[^`]+)`", seg)]


def body_to_html(body: str) -> str:
    """把纯文本正文转 HTML：段落 + 软换行合并 + 强调加粗。

    🔴 2026-09-28 统一：实现已收敛到 `邮件排版.py`（字体 Arial / 11pt /
    强调加粗）。本函数保留为兼容入口，逻辑不再在此维护。

    历史（保留说明，避免重复踩坑）：
      · 原实现对**每个段落**内的所有行做 `" ".join(...)`，
        导致结尾块的 `Best regards,` 与 `{{SENDER_NAME}}` 被合并成一行
        （渲染为「Best regards, {{SENDER_NAME}}」），而《正文格式规范.md》§六 要求固定两行。
      · 现规则：结尾块（含 `Best regards,`）→ **逐行保留换行**（`<br />`）；
        其余段落 → 仍合并软换行（信件正文是手工折行的，必须合并）。
    """
    return load_typography().text_to_html(body)


def build_html(body: str, signature: str) -> str:
    """正文 + 签名 → 完整 HTML。

    字体（Arial）、字号（11pt）、强调加粗规则见 `邮件排版.py` —— 唯一出处。
    """
    T = load_typography()
    return T.wrap(T.text_to_html(body), signature)


def compliance_check(body: str, signature: str, followup: bool = False) -> list:
    """返回问题列表，空 = 通过。

    `followup=True` 时按**跟进信口径**校验（2026-09-28 新增）。

    🔴 为什么要分口径：本检查器原本只有一套规则，其中三条是**首次触达专属**纪律 ——
      · 「首封不报交期」（LEAD_RE）
      · 「首封不报价」（PRICE_RE）
      · 词数 60–150

    跟进信里出现 `price` / `quote` / `weeks` 往往是**在讨论流程**
    （如 `before the price is firm`、`rather than a one-off quote`），
    或复述首封已给的信息，**并非报价**；而跟进信刻意更短（46–66 词是 house style）。
    按首封规则硬卡 → 实测 **6/38 封合规的跟进信被误拦**、永远发不出去。

    ⚠️ 只跳过上面三条。**以下一律照旧强制执行**：
      认证红线（CSA Certified/SASO/SONCAP）、禁用品牌 YAWEI、spam 触发词、
      退订承诺句、旧式署名行、签名主体、【待填】占位符。

    注意：署名主体检查放在**签名**上，不在正文里——
    新格式下正文止于 `{{SENDER_NAME}}`，公司名由图片签名承担（见 正文格式规范 第 ⑥⑦ 段）。
    """
    problems = []
    # 🔴 2026-09-27 修复：调用方传进来的 body 可能来自 HTML 抽取，撇号会被转义成
    # `&#x27;` / `&#39;`（模板里写的是 `isn't` / `won't`）。不先解转义，
    # 退订句检测会**必然漏判**，把每一封合规的信都误判成「缺退订承诺句」。
    # 这里统一解一次，保证纯文本与 HTML 两条来源口径一致。
    body = html_mod.unescape(body)
    low = body.lower()
    # 🔴 2026-09-29 修复：**退订句检测必须先把换行归一化**
    #    原实现对 `low` 做纯子串匹配，而邮件正文**会自然折行** ——
    #    实测 `…and I won't\nwrite again.` 因 `won't` 与 `write again` 被换行拆开，
    #    明明写了退订句却报「缺退订承诺句」（误杀合规信）。
    #    修法：另存一份「空白折叠为单空格」的副本，专供多词短语匹配。
    low_flat = re.sub(r"\s+", " ", low)
    for b in BAD_CERT:
        if b.lower() in low:
            problems.append(f"出现禁用认证表述：{b}")
    if "yawei" in low or "亚威" in body:
        problems.append("出现禁用品牌 YAWEI")
    # ---- 以下三条为**首封专属**，跟进信跳过（见 docstring）----
    if not followup:
        if LEAD_RE.search(body):
            problems.append("首封出现交期数字（红线：首封不报交期）")
        if PRICE_RE.search(body):
            problems.append("首封出现价格词（红线：首封不报价）")
    for s in SPAM:
        if re.search(rf"\b{re.escape(s)}\b", body, re.I):
            problems.append(f"spam 触发词：{s}")
    if not any(u in low_flat for u in UNSUB_MARKERS):
        problems.append("缺退订承诺句（CASL/CAN-SPAM 合规必带）")
    # 正文不应再出现职务/公司/邮箱行（新格式）
    # 🔴 2026-09-28 收紧：旧正则只匹配「Sales Manager | JZPE」（带竖线），
    # 而新格式正文里职务是**独立成行**的（无竖线），会被静默放过。
    # 现改为：`{{SENDER_NAME}}` 之后若还跟着职务/公司/邮箱行，即报错。
    tail = body.split("{{SENDER_NAME}}")[-1] if "{{SENDER_NAME}}" in body else ""
    if re.search(r"Sales\s+Manager", tail) or "JZPE POWER" in tail:
        problems.append("正文里仍有旧式署名行（应只保留 `{{SENDER_NAME}}`，"
                        "职务/公司/邮箱由图片签名承担）")
    # 署名主体：查签名。
    # 注：文档里出现过 JZPE POWER / JIEZOU POWER / JZPE POWER TRANSFORMER CO., LTD.
    # 等写法，用户 2026-09-27 确认「都是同一家公司 JIEZOU POWER」，不作区分。
    if not any(x in signature for x in ("JZPE POWER", "JIEZOU POWER")):
        problems.append("签名里找不到署名主体（JIEZOU POWER）")
    if "待填" in body:
        problems.append("正文含【待填…】占位符")
    # ---- 词数：首封 60–150；跟进信放宽到 30–150（house style 46–66）----
    wc = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", body))
    lo = 30 if followup else 60
    if not (lo <= wc <= 150):
        problems.append(f"词数 {wc} 不在 {lo}–150 区间")
    return problems


def main():
    ap = argparse.ArgumentParser(description="开发信发送器")
    ap.add_argument("letter", nargs="?", help="信件关键字（文件名包含即可），如 Codale")
    ap.add_argument("--list", action="store_true", help="列出所有信件")
    ap.add_argument("--send", action="store_true", help="真正发送")
    ap.add_argument("--yes", action="store_true", help="跳过交互确认")
    ap.add_argument("--to", help="【测试】重定向收件人，绝不发给真实客户")
    ap.add_argument("--dry-run", action="store_true", help="预演，不发送")
    ap.add_argument("--subject-index", type=int, default=1,
                    help="用第几个 Subject 备选（默认 1）")
    args = ap.parse_args()

    files = sorted(CLIENTS.glob("开发信-*.md"))
    if args.list or not args.letter:
        print(f"可用信件（{len(files)} 封）：\n")
        for f in files:
            _, body, notes = parse_letter(f)
            wc = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", body))
            rc = recipients_of(notes)
            print(f"  {f.stem.replace('开发信-',''):<36} {wc:>4}词  → {rc or '（批注里未标主送）'}")
        return 0

    hit = [f for f in files if args.letter.lower() in f.name.lower()]
    if not hit:
        print(f"找不到匹配「{args.letter}」的信件。用 --list 看全部。")
        return 1
    if len(hit) > 1:
        print(f"匹配到 {len(hit)} 封，请更精确：")
        for f in hit:
            print("  ", f.name)
        return 1
    letter = hit[0]

    subjects, body, notes = parse_letter(letter)
    signature = load_signature()
    # 🔴 发送层裁掉正文尾部的「职务/公司/邮箱」行（正文格式规范 §一「零内容」）
    body_raw = body
    body = trim_signature_tail(body)
    trimmed = body_raw.rstrip() != body.rstrip()
    problems = compliance_check(body, signature)

    print(f"信件：{letter.name}")
    print(f"词数：{len(re.findall(r'[A-Za-z][A-Za-z_-]*', body))}")
    print(f"主题：{subjects[args.subject_index-1] if len(subjects) >= args.subject_index else '（无）'}")
    if trimmed:
        dropped = [l for l in body_raw[len(body):].split("\n") if l.strip()]
        print(f"✂️  已裁尾部 {len(dropped)} 行（按规定：`{{SENDER_NAME}}` 与签名间零内容）："
              f"{' / '.join(dropped)}")
    print()

    if problems:
        print("⛔ 红线自检未通过：")
        for p in problems:
            print("   -", p)
        return 2
    print("✅ 红线自检通过（无禁用认证 / 无 YAWEI / 无交期 / 无价格 / 无 spam / 含退订句 / 词数合规）")
    print()

    real_to = recipients_of(notes)
    if not real_to and not args.to:
        print("⚠️ 批注里没有标主送邮箱，且未提供 --to。无法发送。")
        return 1

    to = [args.to] if args.to else real_to
    if args.to and real_to:
        print(f"⚠️  重定向：原收件人 {real_to} → {args.to}（未发给真实客户）")
    print(f"收件人：{to}")

    html = build_html(body, signature)
    print(f"正文 HTML：{len(html)} 字符；签名图片引用：{html.count('cid:')} 个")
    print()

    if args.dry_run or not args.send:
        print("（未加 --send，仅预演。确认无误后加 --send 执行）")
        return 0

    if not args.yes:
        if input("确认发送请输入 yes：").strip().lower() != "yes":
            print("已取消。")
            return 1

    mailer = load_mailer()
    cfg = mailer.load_config()
    subject = subjects[args.subject_index-1] if len(subjects) >= args.subject_index else letter.stem
    msg = mailer.build_message(cfg, to, subject, html=html, inline=True)
    ok, err = mailer.smtp_send(cfg, msg, to)
    if ok:
        print("✅ 已发送")
        print(f"   收件人：{to}")
        print(f"   主题  ：{subject}")
        return 0
    print(f"❌ 发送失败：{err}")
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
