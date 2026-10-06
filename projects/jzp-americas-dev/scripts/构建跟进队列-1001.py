#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 10/01 跟进信队列（33 封）

排程口径：**收件人当地 09:00–10:00**（项目铁律）。
⚠️ ET 组因构建时刻已过窗口起点（北京 22:09 = 当地 10:09），
   经用户 2026-10-01 明确授权**当天发出**（当地约 10:15–10:45）。

约束：
  · 全局**任意两封不得落在同一分钟**（避免「同刻批量」的垃圾邮件特征）
  · 每组在自己窗口内均匀铺开
"""

import importlib.util
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(Path(__file__).resolve().parents[1])
QUEUE = ROOT / "发信队列-跟进1001.json"
BJ = timezone(timedelta(hours=8))
TZ_OFF = {"AT": -3, "ET": -4, "CT": -5, "MT": -6, "PT": -7, "AK": -8}
TZ_CN = {"AT": "大西洋", "ET": "美东", "CT": "美中", "MT": "美山", "PT": "美西", "AK": "阿拉斯加"}

# 各组窗口（北京时刻）。ET 为**用户授权的当天补发窗口**；其余为当地 09:00–10:00 对应值。
WINDOW = {
    "ET": ("2026-10-01 22:15", "2026-10-01 22:45"),   # 当地 10:15–10:45（授权破例）
    "CT": ("2026-10-01 22:12", "2026-10-01 22:58"),   # 当地 09:12–09:58
    "MT": ("2026-10-01 23:02", "2026-10-01 23:58"),   # 当地 09:02–09:58
    "PT": ("2026-10-02 00:02", "2026-10-02 00:58"),   # 当地 09:02–09:58
}

LETTERS = {  # # -> 信件文件名
    21: "开发信-{{COMPANY}}.md", 23: "开发信-{{COMPANY}}.md",
    24: "开发信-{{COMPANY}}.md", 25: "开发信-{{COMPANY}}.md",
    26: "开发信-{{COMPANY}}.md", 27: "开发信-{{COMPANY}}.md",
    28: "开发信-{{COMPANY}}.md", 29: "开发信-{{COMPANY}}.md",
    30: "开发信-{{COMPANY}}.md", 31: "开发信-{{COMPANY}}.md",
    32: "开发信-{{COMPANY}}.md", 45: "开发信-跟进-RA-Electrical.md",
    46: "开发信-{{COMPANY}}.md", 48: "开发信-{{COMPANY}}.md",
    49: "开发信-{{COMPANY}}.md", 50: "开发信-跟进-K2-Electric.md",
    51: "开发信-{{COMPANY}}.md", 52: "开发信-{{COMPANY}}.md",
    153: "开发信-{{COMPANY}}.md", 154: "开发信-{{COMPANY}}.md",
    155: "开发信-{{COMPANY}}.md", 156: "开发信-{{COMPANY}}.md",
    159: "开发信-{{COMPANY}}.md", 160: "开发信-{{COMPANY}}.md",
    161: "开发信-{{COMPANY}}.md", 165: "开发信-{{COMPANY}}.md",
    166: "开发信-{{COMPANY}}.md", 172: "开发信-{{COMPANY}}.md",
    176: "开发信-{{COMPANY}}.md", 180: "开发信-{{COMPANY}}.md",
    181: "开发信-{{COMPANY}}.md", 183: "开发信-{{COMPANY}}.md",
    186: "开发信-跟进-Access-Electrical.md",
}


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, ROOT / fname)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    sd = _load("sdq", "发送开发信.py")
    av = _load("avq", "地址验证.py")
    sc = _load("scq", "定时发送.py")
    sig = sd.load_signature()
    BL = sc.load_blacklist()
    now = datetime.now(BJ)

    work = json.loads((ROOT / ".workbuddy-ai/今日工作单.json").read_text(encoding="utf-8"))
    tzof = {x["num"]: x["tz"] for x in work}
    groups = defaultdict(list)
    for num in LETTERS:
        groups[tzof.get(num, "?")].append(num)

    used = set()
    items, problems = [], []
    for tz in ("ET", "CT", "MT", "PT"):
        nums = sorted(groups.get(tz, []))
        if not nums:
            continue
        w0, w1 = (datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=BJ) for s in WINDOW[tz])
        span = (w1 - w0).total_seconds() / 60.0
        step = span / max(len(nums) - 1, 1)
        for i, num in enumerate(nums):
            letter = LETTERS[num]
            f = ROOT / "开发信项目/clients" / letter
            subs, body, notes = sd.parse_letter(f)
            body = sd.trim_signature_tail(body)
            to, cc = sd.recipients_of(notes), sd.cc_of(notes)
            wc = len(body.split())
            errs = []
            if not subs: errs.append("无主题")
            if not to: errs.append("无收件人")
            if not (20 <= wc <= 110): errs.append(f"词数 {wc}")
            try:
                sd.compliance_check(body, sig, followup=True)
            except SystemExit as e:
                errs.append(f"红线：{e}")
            for a in to + cc:
                # 🔴 2026-10-05：跟进信走**零退信**口径（strict_followup=True）
                b, why = sc.is_blocked(a, now, BL, strict_followup=True)
                if b: errs.append(f"闸门：{a} {why}")
                v = av.verify(a, do_probe=False, polite_delay=0)
                if v["verdict"].startswith("⛔"): errs.append(f"MX：{a} {v['notes']}")
            if errs:
                problems.append(f"#{num} {letter}: {'; '.join(errs)}")
                continue
            when = w0 + timedelta(minutes=round(step * i))
            while when.strftime("%Y-%m-%d %H:%M") in used:      # 全局同刻去重
                when += timedelta(minutes=1)
            used.add(when.strftime("%Y-%m-%d %H:%M"))
            local = when.astimezone(timezone(timedelta(hours=TZ_OFF[tz])))
            items.append(dict(letter=letter, to=to, cc=cc, subject=subs[0], tz=tz,
                              local_label=TZ_CN[tz],
                              scheduled_at_bj=when.strftime("%Y-%m-%d %H:%M"),
                              scheduled_at_local=local.strftime("%Y-%m-%d %H:%M"),
                              window_start_bj=w0.strftime("%Y-%m-%d %H:%M"),
                              window_end_bj=w1.strftime("%Y-%m-%d %H:%M"),
                              status="pending", blocked_reason="",
                              queued_at=now.strftime("%Y-%m-%d %H:%M"), sent_at=None))

    items.sort(key=lambda x: x["scheduled_at_bj"])
    print(f"入队 {len(items)}/{len(LETTERS)} 封\n")
    for x in items:
        print(f"  北京 {x['scheduled_at_bj']} → {x['local_label']} "
              f"{x['scheduled_at_local'][5:]}  {x['to'][0]}")
    if problems:
        print("\n⛔ 未入队：")
        for p in problems:
            print("  " + p)
        return 1
    dup = len(items) - len({x["scheduled_at_bj"] for x in items})
    print(f"\n同刻冲突：{dup}（应为 0）")
    QUEUE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已写 {QUEUE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
