#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发送层回归自检（防「已修 bug 复发」）
=====================================
本脚本把两条**用户实测发现过、已修复**的显示 bug 固化成自动检查。
每次改动发送层后跑一遍；也可以挂进 CI 或发信前的预检。

用法
----
    python3 发送层自检.py            # 跑全部检查
    python3 发送层自检.py -v         # 额外打印细节

背景（两条都是 2026-09-28 用户在自己邮箱实测发现）
--------------------------------------------------
Bug 1 · 结尾换行被合并
    现象：正文结尾显示成 `Best regards, {{SENDER_NAME}}`（一行）
    根因：body_to_html()/md_to_html() 对段落内所有行做 `" ".join()`
    修复：含 `Best regards` 的块逐行保留（<br />）
    涉及：发送开发信.py、生成草稿.py

Bug 2 · text/plain 段是中文占位符
    现象：手机通知栏显示「此邮件为 HTML 格式，请用支持 HTML 的客户端查看。」
    根因：build_message() 把该中文句塞进 multipart/alternative 的 text/plain 段
    修复：改为 html_to_text(html) 反推真实纯文本
    涉及：邮箱客户端.py（全局唯一 EmailMessage 构造点）

还有一条**尚未被用户遇到但已存在的隐患**，一并守住：
Bug 3 · 尾部署名行未裁
    现象：收件人看到职务与邮箱重复两次（正文 + 图片签名）
    根因：新格式信件正文块尾部有 `Sales Manager / JZPE POWER... / ian@...`
    修复：发送前调 trim_signature_tail()
    涉及：发送开发信.py、定时发送.py

另有一条**排版规范**（2026-09-28 用户立规，非 bug 而是硬要求）：
规范 4 · 字体 Arial / 字号 11pt / 强调加粗
    要求：之后发出的所有邮件统一 Arial 11pt，强调部分加粗
    实现：收敛到 `邮件排版.py` **唯一出处**；三条链路
          （发送开发信.py / 生成草稿.py / 发件箱.py）统一引用
    加粗规则：① 写信方 `**...**` 显式标记 ② CTA 句（含 `reply "X"`）自动加粗
              ③ 合规退订句**强制不加粗**
    本节 [7] 会拦住任何 10pt 回归与加粗失效
"""

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIENTS = ROOT / "开发信项目" / "clients"
VERBOSE = "-v" in sys.argv

FAILS = []
PASSES = []


def check(name, cond, detail=""):
    if cond:
        PASSES.append(name)
        print(f"  ✅ {name}")
    else:
        FAILS.append((name, detail))
        print(f"  ⛔ {name}")
        if detail:
            print(f"     {detail}")


def load(modname, filename):
    spec = importlib.util.spec_from_file_location(modname, ROOT / filename)
    m = importlib.util.module_from_spec(spec)
    sys.modules[modname] = m
    spec.loader.exec_module(m)
    return m


def main():
    print("=" * 70)
    print(" 发送层回归自检")
    print("=" * 70)

    sd = load("sd", "发送开发信.py")
    mailer = load("mailer", "邮箱客户端.py")

    # ---------- Bug 1：结尾换行 ----------
    print("\n[1] 结尾换行未被合并（Best regards, / {{SENDER_NAME}} 两行）")
    probe = "Regards test.\n\nBest regards,\n{{SENDER_NAME}}"
    h = sd.body_to_html(probe)
    check("发送开发信.body_to_html 保留硬换行",
          "<br />{{SENDER_NAME}}" in h or "<br>{{SENDER_NAME}}" in h,
          f"实际输出末段：{h[-90:]}")
    check("发送开发信.body_to_html 未合并成一行",
          "Best regards, {{SENDER_NAME}}" not in h,
          "出现了合并形式 `Best regards, {{SENDER_NAME}}`")
    # 普通段落仍应合并软换行（防修过头）
    probe2 = "line one\nline two continues.\n\nSecond para."
    h2 = sd.body_to_html(probe2)
    check("普通段落仍合并软换行（防修过头）",
          "line one line two continues." in h2,
          f"实际：{h2[:130]}")

    print("\n[2] 同类修复覆盖 生成草稿.py")
    try:
        gd = load("gd", "生成草稿.py")
        h3 = gd.md_to_html(probe)
        check("生成草稿.md_to_html 保留硬换行",
              "<br />{{SENDER_NAME}}" in h3 or "<br>{{SENDER_NAME}}" in h3,
              f"实际输出末段：{h3[-90:]}")
    except Exception as e:
        check("生成草稿.md_to_html 可加载", False, f"{type(e).__name__}: {e}")

    # ---------- Bug 2：text/plain 段 ----------
    print("\n[3] text/plain 段是真实正文，非中文占位符")
    cfg = mailer.load_config()
    real = None
    for f in sorted(CLIENTS.glob("开发信-*.md")):
        subs, body, notes = sd.parse_letter(f)
        if subs and body:
            real = (f, subs, body)
            break
    check("找到可用于测试的信件", real is not None, "clients/ 下没有可解析的信")
    if real:
        f, subs, body = real
        body = sd.trim_signature_tail(body)
        html = sd.build_html(body, sd.load_signature())
        msg = mailer.build_message(cfg, ["x@example.com"], subs[0],
                                   html=html, inline=True)
        plain = msg.get_body(("plain",)).get_content()
        check("无「此邮件为 HTML 格式」占位符",
              "此邮件为 HTML" not in plain,
              f"仍出现占位符：{plain[:80]!r}")
        check("纯文本段含真实正文（首段可见）",
              "Hi " in plain or "Hello" in plain or "Dear" in plain,
              f"实际开头：{plain[:100]!r}")
        check("纯文本段不含 cid: 残留",
              "cid:" not in plain,
              f"发现 cid: 残留：{plain[:200]!r}")
        check("纯文本段含署名",
              "{{SENDER_NAME}}" in plain, "纯文本段里找不到署名")
        if VERBOSE:
            print("\n     ── 纯文本段前 400 字 ──")
            print("     " + plain[:400].replace("\n", "\n     "))

    # ---------- Bug 3：尾部署名行必须被裁 ----------
    print("\n[4] 尾部「职务/公司/邮箱」行被裁掉")
    body_with_tail = ("Hi X,\n\nBody text here.\n\nBest regards,\n{{SENDER_NAME}}\n"
                      "Sales Manager\nJZPE POWER TRANSFORMER CO., LTD.\n"
                      "{{SENDER_EMAIL}}")
    trimmed = sd.trim_signature_tail(body_with_tail)
    check("trim_signature_tail 去掉尾部三行",
          trimmed.rstrip().endswith("{{SENDER_NAME}}"),
          f"实际末尾：{trimmed[-70:]!r}")
    check("trim_signature_tail 不动正文",
          "Body text here." in trimmed, "正文被误删")
    check("trim_signature_tail 对无尾行文本安全（幂等）",
          sd.trim_signature_tail("Hi X,\n\nBest regards,\n{{SENDER_NAME}}")
          == "Hi X,\n\nBest regards,\n{{SENDER_NAME}}",
          "对已裁剪文本产生了变化")

    print("\n[5] 定时发送.py 已接入尾部裁剪（隐患 Bug 3）")
    try:
        t = (ROOT / "定时发送.py").read_text(encoding="utf-8")
        check("定时发送.py 调用 trim_signature_tail",
              "trim_signature_tail" in t,
              "定时发送.py 未调 trim_signature_tail —— 会给客户发出重复署名")
    except Exception as e:
        check("定时发送.py 可读", False, f"{e}")

    # ---------- 全量扫描：所有信件的红线自检 ----------
    print("\n[6] 全量信件红线自检（抽查全部 clients/*.md）")
    files = sorted(CLIENTS.glob("开发信-*.md"))
    sig = sd.load_signature()
    ok_n = bad_n = 0
    bad_list = []
    for f in files:
        subs, body, notes = sd.parse_letter(f)
        if not body:
            continue          # 无法解析的跳过（非本检查职责）
        problems = sd.compliance_check(sd.trim_signature_tail(body), sig)
        if problems:
            bad_n += 1
            bad_list.append((f.name, problems))
        else:
            ok_n += 1
    print(f"     可解析 {ok_n + bad_n} 封：通过 {ok_n}，不通过 {bad_n}")
    if VERBOSE and bad_list:
        for n, ps in bad_list[:12]:
            print(f"       · {n}: {'; '.join(ps)}")

    # ---------- 排版规范：Arial / 11pt / 强调加粗 ----------
    print("\n[7] 排版规范：Arial / 11pt / 强调加粗（唯一出处 邮件排版.py）")
    try:
        typo = load("typo", "邮件排版.py")
        check("字号常量为 11pt", typo.FONT_SIZE == "11pt", f"实际 {typo.FONT_SIZE}")
        check("字体含 Arial", "Arial" in typo.FONT_FAMILY, f"实际 {typo.FONT_FAMILY}")

        probe = ("Hi X,\n\nOur **UL certificate** is ready.\n\n"
                 "Reply \"SPECS\" and I'll send it over.\n\n"
                 "If this isn't useful, reply \"stop\" and I won't write again.\n\n"
                 "Best regards,\n{{SENDER_NAME}}")

        links = [("发送开发信", lambda: sd.build_html(probe, "<div>SIG</div>"))]
        try:
            gd2 = load("gd2", "生成草稿.py")
            links.append(("生成草稿", lambda: gd2.build_html(probe, "<div>SIG</div>")))
        except Exception as e:
            check("生成草稿.py 可加载", False, f"{type(e).__name__}: {e}")
        try:
            ox = load("ox", "发件箱.py")
            links.append(("发件箱", lambda: ox.build_html(probe, "<div>SIG</div>", True)))
        except Exception as e:
            check("发件箱.py 可加载", False, f"{type(e).__name__}: {e}")

        for label, fn in links:
            try:
                html = fn()
            except Exception as e:
                check(f"{label} 可渲染", False, f"{type(e).__name__}: {e}")
                continue
            check(f"{label} 字号 11pt", "font-size: 11pt" in html,
                  f"未声明 11pt；片段：{html[:120]}")
            check(f"{label} 字体 Arial", "Arial" in html, "缺 Arial 声明")
            check(f"{label} 无 10pt 残留", "font-size: 10pt" not in html,
                  "仍出现 10pt 字号")
            check(f"{label} 显式 **加粗** 生效",
                  "<strong>UL certificate</strong>" in html,
                  "写信方写的 **...** 未被渲染为 <strong>")
            check(f"{label} CTA 句自动加粗", "<strong>Reply" in html,
                  "含 reply \"X\" 的行动句未自动加粗")
            check(f"{label} 合规退订句不加粗",
                  "<strong>If this isn't useful" not in html,
                  "合规退订句被加粗（会显得像营销）")

        # 源码层：不得再硬编码 10pt（邮件排版.py 的 10pt 只允许出现在说明文字里）
        bad_src = []
        for name in ("发送开发信.py", "生成草稿.py", "发件箱.py", "邮件排版.py"):
            src = (ROOT / name).read_text(encoding="utf-8")
            for ln in src.splitlines():
                s = ln.strip()
                if "font-size: 10pt" in ln and not s.startswith(("#", "*", "`", "·", '"')):
                    bad_src.append(f"{name}: {s[:70]}")
        check("无源码硬编码 10pt 字号", not bad_src, "; ".join(bad_src))
    except Exception as e:
        check("邮件排版.py 可加载", False, f"{type(e).__name__}: {e}")

    # ---------- 结果 ----------
    print("\n" + "=" * 70)
    if FAILS:
        print(f" ⛔ 未通过 {len(FAILS)} 项：")
        for n, d in FAILS:
            print(f"    - {n}")
            if d:
                print(f"      {d}")
        return 1
    print(f" ✅ 全部通过（{len(PASSES)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
