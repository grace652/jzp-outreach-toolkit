#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 2026-10-02 跟进信（31 封）

设计纪律（本轮特别注意）：
  🔴 **绝不把客户的电压套进证书区间，除非确实落在区间内。**
     本轮踩到的三处越界：Rogers 138kV、PFM 138kV、VoltCore 345kV ——
     E541626 的 HV 区间是 **72–121 kV**，这三家**都超上限**，只能**反问**不能声称覆盖。
  · 第 2 轮 = **换角度**（不重复首封与第 1 轮）
  · 第 1 轮 = **补新信息点**（首封只给了「有证书」，本轮给「是什么」）
  · 每封 ≤100 词、带退订句、必带收件人行、`Re:` 用**实测主题**
"""
import json
import re
from pathlib import Path

ROOT = Path(Path(__file__).resolve().parents[1])
TODAY = "2026-10-02"
OUT = ROOT / f".workbuddy-ai/今日工作单-{TODAY}.json"

REMINDER = f"""## ⛔⛔ 无法触达邮箱提醒（发前必看）

> 数据源：`退信黑名单.json`｜`扫描退信.py` 于 {TODAY} 扫描入库

- ✅ **本批 31 家已逐条实测退信闸门 —— 拦截 0 条。**
- ⛔ **整域封锁**（该域全部地址一律拦截）：`{{COMPANY_DOMAIN}}`、`{{COMPANY_DOMAIN}}`。
- ⛔ 本批**无抄送项**。
- ⚠️ **附件体积红线**：本批为**纯文本跟进信，不带附件**；若后续要发证书/规格书，
  **总量控制在 20 MB 内**（Catalog 用 Email Version），大文件走云盘链接。
"""

# num -> (称呼行, 正文, 设计说明)
L = {}

# ============ 第 2 轮（换角度）16 家 ============
L[36] = ("Hi Ken,", """A number worth having on file for data center scopes: our two listings split
the range cleanly — E541627 for distribution, 45 kVA to 5,000 kVA, and
E541626 for power units, 750 kVA to 110 MVA. Both are searchable on UL
Product iQ under JZPE.

Tell me which voltage class your data center packages run at and I will send
the sheets for that class rather than the whole set.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：数据中心页列 MV/HV 开关柜+变压器+UPS；第 1 轮：数据中心 submittal 三件套
- **本轮换角度**：从「submittal 要什么」转到「**区间怎么分**」—— 给出双证书的分工，并**反问电压等级**
- 🔴 **未套用**其数据中心电压（未知，不猜）""")

L[37] = ("Hi Jonathon,", """One thing I should have said earlier, since your work is in Ontario: both
certificates carry the Canadian listing as well as the US one. The power
listing is certified for Canada to CSA C88, and the distribution listing
covers 75 kVA to 3,000 kVA on the Canadian side.

If that matters for the retrofit and upgrade work, I will send the
certificates and the sheets for the band you use.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：480V 以上，变压器测试维护/保护继电器/改造；第 1 轮：有文档的替换机过审更快
- **本轮换角度**：**点明加拿大覆盖**（Sudbury = 安省）—— 前两轮只提 UL 编号，**漏了加拿大那一半**
- ✅ 对加拿大客户这是最该说、却一直没说的一条""")

L[38] = ("Hello,\n\nCould you please forward this to Ian Frailey in purchasing?", """Rather than guess at your substation voltages, one question: on the turnkey
scopes, which HV class do the units usually sit at? Our power listing runs
750 kVA to 110 MVA at 72–121 kV on E541626 (IEEE C57.12.00), and distribution
units run 45 kVA to 5,000 kVA on E541627 — tell me which side your scopes fall
on and I will send only the matching sheets.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：Philippi 138kV 50MVA 变电站 turnkey；第 1 轮：长周期项宜早审规格
- **本轮换角度**：**反问 HV 等级**，而不是拿其项目电压去套证书
- 🔴 **关键纪律**：其 **138 kV 超出 E541626 的 72–121 kV 上限** ——
  **绝不能声称覆盖**。故本封只给区间 + 反问，一个项目数字都不套""")

L[39] = ("Hello,\n\nCould you please forward this to Eric Moore?", """Last note from me on this one, since my first email asked a straight yes/no
and you have plenty on: if a commercial or civil job ever needs a service
transformer bought direct, our listing is E541627, 45 kVA to 5,000 kVA, and I
will send the certificate and sheets for it.

No reply needed if it is always utility-supplied — I will leave it there.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：1927 起商业/民用/高压照明，IBEW 466，**坦白「多数不是变压器」**，问自购还是电力公司供
- 第 1 轮：两词压缩（self / utility）
- **本轮换角度**：两轮无回应 + **匹配本窄** → 改为**礼貌收尾式**：给区间 + **明确「无需回复」**
- ✅ 对匹配窄的客户，第 2 轮不该再追问，该给台阶""")

L[40] = ("Hi Donna,", """One band I have not put in front of you yet, and it lines up with the EV work
on your page: the units behind a charging site are usually distribution class.
Ours run 45 kVA to 5,000 kVA on E541627, with a factory test report per unit.

If the EV upgrades are still moving, tell me the rating you are replacing and
I will send that sheet rather than the catalogue.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：HV 页列变压器维护/测试/整体更换 pad-mount 与架空 + **EV 充电变压器升级**
- 第 1 轮：更换时要匹配既有 bay 与阻抗
- **本轮换角度**：切到首封提过但两轮都没展开的 **EV 充电升级**""")

L[42] = ("Hello William,", """A different part of your scope this time: changeouts. On a replacement, the
unit has to sit against protection settings that are already in service, so
what usually decides the fit is the test data — ratio, impedance, losses —
rather than the rating alone. Every unit ships with its own report.

Tell me which voltage class your changeouts usually run at and I will send
the matching sheets.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：12.47–345kV 变电站新建/升级/改造 + 变压器安装与更换 + SEL/GE/ABB 保护
- 第 1 轮：345kV 语境，TTR 变比试验
- **本轮换角度**：切到 **changeout（更换）** —— 其保护整定已在线，配合靠试验数据
- 🔴 **未套用** 12.47–345kV（345 kV 远超证书 72–121 kV）""")

L[43] = ("Hi Gary,", """Adding something for the multi-state side: your work runs across Ohio, Kentucky
and West Virginia, and on industrial scopes the same rating often has to hold
across more than one site. Our documentation is per unit rather than per
shipment, so a spec can be matched site by site.

Our distribution listing is E541627, 45 kVA to 5,000 kVA. Tell me the rating
you specify most and I will send that sheet.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：工业规模配电 + FLSmidth Winfield 扩建；第 1 轮：FLSmidth 变压器早于机械包定
- **本轮换角度**：切到**跨州多现场**（其覆盖 OH/KY/WV）→ **逐台文档 = 逐现场匹配**""")

L[44] = ("Hello,\n\nCould you please forward this to Matthew Jackson or Greg Bedard?", """One thing that matters for a Canadian distributor and that I have not spelled
out: both listings carry the Canadian side as well as the US one. The power
listing is certified for Canada to CSA C88; the distribution listing covers
75 kVA to 3,000 kVA in Canada against 45 kVA to 5,000 kVA in the US.

If that clears the first question your product team would ask, I will send
the certificates and sheets through your vendor approval process.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：加拿大首要 MV/HV 分销商（三仓 + Trydor + NAIL）；第 1 轮：不替换现有线，第二工厂源，走 vendor approval
- **本轮换角度**：**加拿大覆盖**（Rexel Canada 是加拿大客户）—— 直接回答其产品组会问的第一个问题""")

L[47] = ("Hi Gary,", """One point of overlap worth clearing up: you build your own control transformers
from 240 to 995 V, so that band is already yours. The part we would sit in is
above it — power units from 750 kVA to 110 MVA on E541626, and distribution
from 45 kVA to 5,000 kVA on E541627.

If a line or substation job ever needs a unit in those bands, I will send the
certificates and sheets.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：设计建造配电至 138kV 输电线，**自产 240–995V 控制变**；第 1 轮：问常用品牌 + 给变电站档
- **本轮换角度**：**明确「不碰你自产的那一段」** —— 自产 240–995V，我们供 750 kVA 以上，无冲突
- ✅ 降低戒心：先划清边界，再谈互补""")

L[53] = ("Hello,\n\nCould you please forward this to Gus Cedeño or Derin Pitre?", """A different angle on the new-unit side: with 42 locations behind you, the
useful question is not which unit you would buy once, but which ratings are
worth having a factory source behind. Our distribution listing runs 45 kVA to
5,000 kVA (E541627) and power units 750 kVA to 110 MVA (E541626).

Tell me the ratings your network turns over most and I will send those sheets.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：全生命周期（新机/租赁/维修/回收）42 地；第 1 轮：新机 drawings to FAT 周期 + DOE 2024
- **本轮换角度**：从「新机能力」转到**其 42 地网络的常备额定** —— 新机作为翻新线**之外**的品类""")

L[55] = ("Hi Brian,", """One angle I have not used: the plant side. Six wastewater plants plus municipal
work means replacement units on a schedule that is not set by a project — they
fail when they fail. Our distribution listing is E541627, 45 kVA to 5,000 kVA,
with a test report per unit so the file is complete on each swap.

Tell me the rating you most often replace and I will send that sheet.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：MV 配电升级（Clarion University）+ 4000A 开关柜 + 500kW 发电机 + **6 座污水厂**；第 1 轮：问常用品牌
- **本轮换角度**：切到**污水厂/市政** —— 这类是**按故障换**而非按项目换，文件要随台齐""")

L[56] = ("Hi Matt,", """A band that maps onto the URD side of your work: underground residential
distribution usually lands in distribution class. Ours runs 45 kVA to 5,000 kVA
on E541627, with a factory test report per unit — which is what you would want
against the HiPot work you already run.

Tell me the rating you pull most on URD jobs and I will send that sheet.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：MV 变电站与变压器端到端 + **URD 终端** + HI POT 测试 + 电杆销售；第 1 轮：问电压
- **本轮换角度**：切到 **URD（地下配电）**，并接上其自有 HiPot 能力（逐台报告可对）""")

L[58] = ("Hi Jody,", """One thing worth stating plainly, since Thunder Bay puts this on the Canadian
side: both listings carry the Canadian certification as well as the US one.
The power listing is certified for Canada to CSA C88, and the distribution
listing covers 75 kVA to 3,000 kVA in Canada.

If that helps on the rebuild and retrofit scopes, I will send the certificates
and the sheets for the band you use.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：北安大略变电站新建/重建 4–25kV + 230kV 干冰清洗；第 1 轮：重建要与既有 bus/保护/净距匹配
- **本轮换角度**：**加拿大覆盖**（Thunder Bay = 加拿大）""")

L[59] = ("Hello,\n\nCould you please forward this to John Kirby or Anthony Cortazzo?", """One more for the blanket-order side, on the voltage question: the SCR work at
Conemaugh runs at 13.8 kV, which is distribution class rather than transmission.
Our distribution listing is E541627, 45 kVA to 5,000 kVA, and it covers that
class.

If a blanket order ever touches that band, tell me the rating and I will send
the matching sheet.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：全厂 blanket order，Conemaugh SCR **13.8 kV 开关柜**，Wheeling 钢铁；第 1 轮：多现场文档一致性
- **本轮换角度**：用其**自己项目里的 13.8 kV** 说明「这是配电级、落在 E541627」
- ✅ **这条映射是成立的**：13.8 kV 属配电级（E541627 覆盖 Over 600 V 配电），
  与 Rogers/PFM 的 138 kV 越界不同""")

L[61] = ("Hello,\n\nCould you please forward this to Will Mitchell or John Smith?", """One thing aimed at how you quote rather than what we make: with estimating
managers pricing each job, the slow part is usually getting documentation to
sit behind the number. Our certificates, capacity sheets and a sample factory
test report can be sent as one pack so your estimators have it on file.

Reply "PACK" and it goes out.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：1976 起 HV 变电站/杆线/工业配电，北阿拉巴马/南田纳西，**估算经理逐项报价**；第 1 轮：报价阶段买方先要证书与试验数据
- **本轮换角度**：切到**其估算经理的工作流** —— 把「资料」变成「报价时手上就有的一包」""")

L[62] = ("Hello,\n\nCould you please forward this to whoever handles transformer purchasing?", """A different part of your operation: with your own transformer repair shop behind
the counter, the parts side is consumed continuously rather than per project.
Bushings, fuses and transformer oil ship alongside our transformers and are
often what a repair is actually waiting on.

If a parts source would help the shop, reply "PARTS" and I will send what we
can supply.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：75 合作社/300 万会员，自有杆厂 + **EPA 变压器维修车间** + 变电站钢结构；第 1 轮：合作社联盟语境，找对人
- **本轮换角度**：切到**其自有维修车间的消耗件**（套管/熔断器/变压器油）—— 持续消耗，不是按项目""")

# ============ 第 1 轮（补新信息点）15 家 ============
L[148] = ("Hi Mario,", """One thing the first note did not spell out, and it matters in BC: both listings
carry the Canadian certification alongside the US one. The power listing is
certified for Canada to CSA C88; the distribution listing covers 75 kVA to
3,000 kVA on the Canadian side.

Given the 20/27 MVA and 35 MVA assembly work on your record, that band is the
one I would send first.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：Substations+Transformers 页列 padmount/变电站/接地/干式/自耦/封装；
  项目记录 **20/27 MVA、35 MVA 现场组装**；CTA 证书+容量表+试验报告
- **本轮补新信息点**：**加拿大覆盖**（Martech = BC）—— 首封只说「UL certified」，**漏了加拿大那一半**""")

L[149] = ("Hi Terry,", """One thing the first note left open: what the documents actually contain. It is
three items — our UL certificate for the range, capacity sheets by rating, and
a sample factory test report. Both listings are searchable on UL Product iQ
under JZPE, so the covered band can be confirmed before any meeting.

Tell me the voltage class your substation work runs at and I will send the
matching sheets.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：变压器安装 + 变电站建造 + 接地 + HV/MV 电缆；**新团队**；CTA 容量表+证书
- **本轮补新信息点**：把「容量表 + 证书」拆成**三件具体物** + 给**可自查路径**""")

L[158] = ("Hi Rajan,", """One thing worth settling before a FEED package, and it is on the Canadian side:
both listings carry the Canadian certification as well as the US one — the
power listing to CSA C88, the distribution listing covering 75 kVA to 3,000 kVA
in Canada.

Tell me which voltage class the substation equipment sits at and I will send
only the sheets that apply, rather than the full set.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：**FEED 分析 138 kV 变电站** + 电气设备采购；CTA 容量表+证书
- **本轮补新信息点**：**加拿大覆盖** + **反问电压等级**
- 🔴 **关键纪律**：其 **138 kV 超出 E541626 的 72–121 kV 上限** —— 只能反问，**不可声称覆盖**""")

L[204] = ("Hi Charlie,", """One thing the first note did not pin down: the band itself. Distribution runs
45 kVA to 5,000 kVA on E541627 and power units 750 kVA to 110 MVA on E541626,
both searchable on UL Product iQ under JZPE — so if a client ever asks you who
to source from, the covered range is checkable in one step.

If it would help to have that on file, say the word.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：变电站基础/开关站/输电线；**你在现场但机组可能别人买**；CTA 若需自购
- **本轮补新信息点**：给**具体区间 + 可核验路径** —— 让他在被客户问到时有据可查""")

L[205] = ("Hi Eddie,", """One thing the first note did not spell out: what arrives with each unit. Every
transformer ships with its own factory test report — routine tests, ratio,
impedance and losses — and the distribution listing runs 45 kVA to 5,000 kVA
on E541627.

If a project does call for the unit to be sourced, that is the pack I would
send first.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：变电站是第一应用，TX；问自购还是别人供；CTA
- **本轮补新信息点**：**逐台出厂试验报告**（首封只给了「有」）""")

L[206] = ("Hi Luis,", """One thing the first note did not put a number against: the replacement band.
When a repair turns into a swap, the units usually sit in distribution class —
45 kVA to 5,000 kVA on E541627 — with a test report per unit so the file closes
on each swap.

Tell me the rating you most often replace and I will send that sheet.

If this isn't useful, reply "stop" and I won't write again.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：变电站安装 → 变压器维修/升级/**LTC**；大量时间在换机；CTA 容量表+证书
- **本轮补新信息点**：给**换机最常落的区间** + 逐台报告（首封只说「有容量表」）""")

L[207] = ("Hi John,", """One thing the first note left open: the range behind the certificates. Power
units run 750 kVA to 110 MVA on E541626 (IEEE C57.12.00) and distribution runs
45 kVA to 5,000 kVA on E541627 — both searchable on UL Product iQ under JZPE.

Given your role on the sourcing side, tell me which band your turnkey scopes
fall in and I will send only that sheet.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：输电与变电站 turnkey + 电力变压器服务线；**你在采购侧**；CTA
- **本轮补新信息点**：给**双证书区间 + 可核验路径** + 反问其 turnkey 落在哪一段""")

L[208] = ("Hi Frank,", """One thing that matters when you are writing the spec rather than buying against
it: the standard the unit is tested to. Our power listing is built to
IEEE C57.12.00 (E541626) and carries a Canadian certification to CSA C88 as
well — so the compliance line in a spec can be checked against the certificate
rather than taken on trust.

If it would help to have the certificate and the standard list on file, I will
send them.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：电力公司变电站与输电**设计** → **变压器规格在你手上**；CTA
- **本轮补新信息点**：**标准符合性**（IEEE C57.12.00 + 加拿大依 CSA C88）——
  设计方最关心的是**规格书里怎么引用标准**，不是价格""")

L[210] = ("Hi Glen,", """One thing the first note did not put a number against: the range. Distribution
runs 45 kVA to 5,000 kVA on E541627 and power units 750 kVA to 110 MVA on
E541626, with a factory test report per unit — which matters on the testing
side of your service list.

Tell me the class your substation work runs at and I will send that sheet.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：12kV–500kV 变电站建造 + **移动变压器安装 + 变压器测试**；CTA
- **本轮补新信息点**：给**区间 + 逐台试验报告**，并挂在其**测试业务**上
- 🔴 未套用其 500 kV（远超证书 72–121 kV）""")

L[218] = ("Hi John,", """One thing the first note did not spell out, and it is the question a Canadian
buyer asks first: both listings carry the Canadian certification as well as the
US one — the power listing to CSA C88, the distribution listing covering 75 kVA
to 3,000 kVA in Canada against 45 kVA to 5,000 kVA in the US.

If that clears the first hurdle, tell me which ratings are hardest to keep on
the shelf and I will send those sheets.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：四个变压器品牌线 + 安省分店网络 → **正经营这个品类**；问第二货源；CTA
- **本轮补新信息点**：**加拿大覆盖** + 反问「最难常备的额定」—— 直接对上其**分店库存**痛点""")

L[222] = ("Hi Gary,", """One thing the first note did not spell out, and it is the first question a
Canadian buyer asks: both listings carry the Canadian certification alongside
the US one — the power listing to CSA C88, the distribution listing covering
75 kVA to 3,000 kVA in Canada.

If that clears the hurdle for your industrial division, I will send the
certificates and sheets.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：纽芬兰/新斯科舍/PEI 独立**工业部门**；CTA 证书+容量表给供应商评审人
- **本轮补新信息点**：**加拿大覆盖**（大西洋省份客户）""")

L[223] = ("Hi Donna,", """One thing the first note left open, and it is on the Canadian side: both
listings carry the Canadian certification as well as the US one — the power
listing to CSA C88, the distribution listing covering 75 kVA to 3,000 kVA in
Canada against 45 kVA to 5,000 kVA in the US.

If adding a supplier is part of your process, that is the first thing your
review would ask, so I would rather put it in front of you now.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：全国供应链 + 分支运营，电气是垂直之一；CTA
- **本轮补新信息点**：**加拿大覆盖** —— 直接预答其评审流程的第一个问题""")

L[225] = ("Bonjour Patrick,", """One thing the first note did not spell out, and it is the first question a
Canadian buyer asks: both listings carry the Canadian certification as well as
the US one — the power listing to CSA C88, the distribution listing covering
75 kVA to 3,000 kVA in Canada.

If that clears the hurdle for the electrical division, I will send the
certificates and capacity sheets.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：集中采购跨部门 → 变压器线落在你手上；CTA
- **本轮补新信息点**：**加拿大覆盖**（QC 客户）""")

L[235] = ("Hi Austin,", """One thing the first note did not put a number against: the band. Distribution
runs 45 kVA to 5,000 kVA on E541627 and power units 750 kVA to 110 MVA on
E541626, both searchable on UL Product iQ under JZPE — so the covered range can
be confirmed before you take it to a category review.

If it is useful to have on file, say the word and I will send the certificate
and the sheets.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：**采购与定价一体** → 加品类落在你桌上；CTA
- **本轮补新信息点**：**区间 + 可核验路径**（他做品类评审时要能自证）""")

L[237] = ("Hi Randy,", """One thing the first note did not spell out: what arrives with each unit. Every
transformer ships with its own factory test report, and our distribution
listing runs 45 kVA to 5,000 kVA on E541627 — enough for a gear counter to
file against each order rather than each shipment.

If the gear build-out reaches transformers, I will send the certificate and
the sheets for that band.

If this isn't relevant, just let me know and I won't follow up.

Best regards,
{{SENDER_NAME}}""",
"""- 首封：正在招 **gear/工业方向**的人 → 品类在扩张；CTA
- **本轮补新信息点**：**逐台出厂试验报告**（按单归档，对上柜台作业方式）""")

# ---------- 写文件 ----------
def slug(ft):
    return re.sub(r"^开发信-", "开发信-跟进-", ft)


def main():
    work = json.loads(OUT.read_text(encoding="utf-8"))
    md = (ROOT / "开发信项目/工作区/开发信跟进表.md").read_text(encoding="utf-8")
    written, skipped = [], []
    for x in work:
        n = x["num"]
        if n not in L:
            skipped.append(n)
            continue
        b = re.search(rf"^### {n}\.\s.*?(?=^### |\Z)", md, re.S | re.M)
        m = re.search(r"\*\*信文件\*\*：(.+)", b.group(0)) if b else None
        ft = re.sub(r"[（(].*", "", (m.group(1) if m else "")).strip().strip("`").replace("clients/", "")
        sal, body, design = L[n]
        text = (REMINDER + "\n---\n\n【Subject 备选】\n1. `" + x["last_subject"] + "`\n\n【正文】\n\n"
                + sal + "\n\n" + body + "\n\n【中文批注】\n\n"
                + f"- **收件人**：`{x['emails'][0]}`（{x['name']}）\n"
                + "- **抄送**：—\n"
                + f"- 轮次：**{x['round']}**\n"
                + f"- 时区：{x['tz']}｜公司：{x['name']}\n"
                + "- 说明：跟进信（同主题 Re: 回复原线程）\n\n"
                + "## 本封设计\n\n" + design + "\n")
        p = ROOT / "开发信项目/clients" / slug(ft)
        p.write_text(text, encoding="utf-8")
        written.append((n, slug(ft), len(body.split())))
    print(f"已写 {len(written)} 封")
    for n, f, wc in written:
        flag = "✅" if wc <= 100 else "⚠️超100词"
        print(f"  {flag} #{n:<5}词={wc:<4}{f}")
    if skipped:
        print("未覆盖:", skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
