#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮件正文排版规范 —— 全项目唯一实现点
=========================================

用户 2026-09-28 明确要求（对**之后所有**发出的邮件生效）：
  ① 字体  **Arial**
  ② 字号  **11pt**
  ③ 强调的部分 **加粗**

为什么要有这个模块
------------------
此前 `发送开发信.py` / `生成草稿.py` / `发件箱.py` **各自硬编码**了一份
`<div style="font-family: ...; font-size: 10pt; ...">`——
三处口径一致纯属巧合，任何一处改动都会造成「同一封信、不同链路、渲染不同」。

本模块把**字体 / 字号 / 加粗**收敛到**一处定义**，三条链路统一从这里取，
并由 `verify()` 提供机器自检，防止再次漂移。

改动历史
--------
2026-09-28  建立。字号 **10pt → 11pt**；新增**加粗**支持（此前完全没有）。

加粗规则（三条，按优先级）
--------------------------
1. **写信方显式标记**：正文里写 `**要加粗的字**` → 渲染为 `<strong>`。
   （写信环节掌握"哪里算强调"的判断权，发送环节只负责渲染。）
2. **CTA 行动句自动加粗**：段落含 `reply "XXX"` 的句子自动整句加粗。
3. **合规句永不加粗**：含 `won't write again` / `just let me know` 等
   退订承诺语的行**强制不加粗**——合规声明做成营销腔会适得其反。

> ⚠️ 规则 1 优先：若某段已含显式 `**` 标记，则不再对其套用规则 2。
"""

import re

# ---------------------------------------------------------------- 字体规范（唯一出处）
FONT_FAMILY = "Arial, Helvetica, sans-serif"
FONT_SIZE_PT = 11
FONT_SIZE = f"{FONT_SIZE_PT}pt"
COLOR = "#3f3f3f"
LINE_HEIGHT = "1.65"

#: 正文容器样式 —— 三条链路统一引用这一条
BODY_STYLE = (f"font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}; "
              f"color: {COLOR}; line-height: {LINE_HEIGHT};")

P_STYLE = "margin:0 0 14px 0;"
UL_STYLE = "margin:0 0 14px 0; padding-left:22px;"

#: 正文与签名图片之间的间隔块
SIGNATURE_GAP = ('<div style="height:16px; line-height:16px; font-size:0;">'
                 '&nbsp;</div>')

# ---------------------------------------------------------------- 加粗规则
BOLD_MARK_RE = re.compile(r"\*\*(.+?)\*\*", re.S)          # 规则 1：显式标记
CTA_RE = re.compile(r'\breply\s*["“]', re.I)               # 规则 2：CTA 句
NO_BOLD_RE = re.compile(                                    # 规则 3：合规句豁免
    r"won't write again|won't follow up|close the loop|"
    r"isn't useful|isn't relevant|just let me know|"
    r"no chasing|I won't write", re.I)


def esc(s: str) -> str:
    """HTML 转义（& < >）—— 与项目原有实现保持一致。"""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def inline(text: str) -> str:
    """行内渲染：转义 → `**bold**` → `<strong>`。"""
    text = esc(text)
    text = BOLD_MARK_RE.sub(r"<strong>\1</strong>", text)
    # 还原被误转义的实体（与旧实现一致：&amp;quot; → &quot;）
    text = re.sub(r"&amp;(quot|#\d+);", r"&\1;", text)
    return text


def _auto_bold_cta(html_text: str) -> str:
    """规则 2/3：CTA 句自动加粗；合规句豁免；已有显式加粗则不重复。"""
    if "<strong>" in html_text:
        return html_text
    if NO_BOLD_RE.search(html_text):
        return html_text
    if CTA_RE.search(html_text):
        return f"<strong>{html_text}</strong>"
    return html_text


def text_to_html(text: str, auto_bold_cta: bool = True,
                 lists: bool = False) -> str:
    """纯文本正文 → HTML 段落。

    规则（与项目《正文格式规范》一致）：
      · 结尾块（含 `Best regards,`）→ **逐行保留换行**（`<br />`）
      · 其余段落 → 合并软换行（信件是手工折行的）
      · `lists=True` 时把 `- ` 开头的块渲染为 `<ul>`
      · 加粗按 BOLD_MARK_RE / CTA_RE / NO_BOLD_RE 三条规则
    """
    out, in_ul = [], False
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = [l.strip() for l in block.split("\n") if l.strip()]

        if lists and lines and all(l.startswith("- ") for l in lines):
            if not in_ul:
                out.append(f'<ul style="{UL_STYLE}">')
                in_ul = True
            for l in lines:
                out.append(f"<li>{inline(l[2:])}</li>")
            continue

        if in_ul:
            out.append("</ul>")
            in_ul = False

        if any(l.startswith("Best regards") for l in lines):
            body = "<br />".join(inline(l) for l in lines)
        else:
            body = inline(" ".join(lines))
            if auto_bold_cta:
                body = _auto_bold_cta(body)
        out.append(f'<p style="{P_STYLE}">{body}</p>')

    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


def wrap(body_html: str, signature: str = "") -> str:
    """给正文套统一字体样式，再接签名（输出结构与旧 build_html 一致）。"""
    doc = f'<div style="{BODY_STYLE}">\n{body_html}\n</div>'
    if not signature:
        return doc
    return f"{doc}\n{SIGNATURE_GAP}\n{signature}\n"


def verify(html: str) -> list:
    """自检：返回不符合规范的问题列表（空 = 通过）。"""
    problems = []
    if "font-family" not in html or "Arial" not in html:
        problems.append("缺 Arial 字体声明")
    if re.search(r"font-size:\s*10pt", html):
        problems.append("仍存在 10pt 字号（应为 11pt）")
    if f"font-size: {FONT_SIZE}" not in html:
        problems.append(f"未声明字号 {FONT_SIZE}")
    return problems


if __name__ == "__main__":
    demo = ("Hi Bert,\n\n"
            "A follow-up: our UL certificate (E541626) is ready.\n\n"
            "Reply \"SEND\" and I'll send it over.\n\n"
            "If this isn't useful, reply \"stop\" and I won't write again.\n\n"
            "Best regards,\n{{SENDER_NAME}}")
    html = wrap(text_to_html(demo), "<div>SIG</div>")
    print(html)
    print("\n--- verify ---")
    print(verify(html) or "✅ 通过")
