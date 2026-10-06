# 03 · 范本集（真实信件，可对照学习）

> 从 `clients/` 里 78 封信中选出 **6 个**，覆盖最难写的场景：
> ① design-build 承包商（钩子=报审资料）② 分销商条件切入（钩子=缺口）
> ③ 变电站级 EPC（钩子=测试数据）④ 展会来源转交（骨架 C）
> ⑤ **常规跟进信（新信息点压缩）** ⑥ **热转交（对方回信指人）**
>
> **学习重点看「中文批注」** —— 那里写了"为什么这么选"和"刻意没用什么"。
> 原件在 `clients/` 下，可随时调取。
> 更多同类型客户的旧信 → 查 `clients/INDEX.md`（按买家类型/骨架/钩子检索）。

---

## 范本一 · {{COMPANY}}（design-build 承包商）

**为什么选它**：钩子选得最准的一封 —— 对方有**独立选型权**，
所以钩子落在"让他的下次画图直接能用"，而不是"我们质量好"。

**信文件**：`clients/开发信-{{COMPANY}}.md`

```
【Subject 备选】
1. UL-certified pad-mount and pole-mount transformers
2. Transformers for your design-build submittals
3. Pad-mount and pole-mount transformer supply
```

```
Hi Brian,

Noticed your project list — Leatherman, Starbucks, four medical
facilities — and that you've added utility infrastructure rewiring and
EV charging. Those last two put a transformer on the drawing.

We're JZPE Power Transformer, a manufacturer in Suzhou, China. We build
pad-mount, pole-mount and three-phase liquid-filled distribution
transformers for 60 Hz systems — UL certified (E541626 / E541627),
tested to IEEE C57.12 and ANSI standards.

Since you run design-build, you're the one specifying these. Would it
help to have our UL certificates, product data sheets and factory test
reports ready for your submittals?

Reply "SPECS" and I'll send them over.

Best regards,
{{SENDER_NAME}}
```

### 这封信的关键决策（批注精华）

- **骨架 A**（官网全站 + 州务卿 + 行业名录）
- **开场用对方官网 Projects 页的 15 个实名项目**（Leatherman / Starbucks / 四家医疗机构）
  → 一句话证明"我真看过你的项目页，不是群发"
- **落点用对方自己的语言**：`put a transformer on the drawing`（drawing = 图纸）
- **核心逻辑**：`Since you run design-build, you're the one specifying these.`
  → **"选型权在你手上，所以我把资料给你，你下次画图时直接能用。"**
- **钩子 = submittals（报审资料）** —— 美国商业工程里分包商必须提交的**产品资料与证书报审**
  那是**他每天真正要交的东西**
- ⚠️ **同批 Williams 用的是 `for your bids`（投标）** ——
  两家都是"文档"类钩子，但**用词按其业务性质区分**，不重复

### 🔴 刻意未用的内容（这部分最值得学）

| 未用 | 原因 |
|---|---|
| **"30 年历史"** | 原文 "over 30 years in the electrical industry **Brian Alexander founded Alco Electric in 2020**" —— **30 年指个人从业年限，公司只有 5 年**。名录把个人资历写成公司历史，那是错的 |
| **华盛顿州 $37.30M 电车补贴** | 交接单称"最强钩子"，但**不是新信息**（他是从业者）**且不指向我方产品** → 降级为第 2 轮谈资 |
| **"12 人公司"** | 营收无公开数据 → 改用"业务扩张"叙事而非人数 |
| **俄勒冈责任险 2026-10-19 到期** | 提这个显得窥探合规状态 |
| **480V / 13.8kV 等具体电压** | 官网未明示 → **不编造** |
| **500kV / 480MVA** | 对方是商业承包商，**提这个属超纲** |
| **干式变** | 商业室内工程通常用干变，但我方**干变没有 UL** → **主动提等于自曝短板** |
| **union / prevailing wage 合规** | 首次触达谈劳动合规易被误解为暗示他成本高 |

⚠️ **两条地名红线**：这是**美国华盛顿州 Vancouver**，不是加拿大温哥华（时区/认证/法规全不同）。

---

## 范本二 · GenPac（分销商条件切入）

**为什么选它**：**"接不住的钩子就是自曝"的最佳演示** ——
对方主品类被 ERMCO 深度绑定，钩子只能落在**缺口**上。

**信文件**：`clients/开发信-GenPac.md`

```
【Subject 备选】
1. Transformer supply outside current brands?
2. Padmount distribution transformers — UL, volume tiers
3. Second transformer source for co-op stock
```

```
Hello,

Could you please forward this to Steven Breeden or George in the transformer group?

General Pacific supplies co-ops across the Northwest — Howard and ERMCO lines on
EWEB bids, a transformer group behind the counter, and contractor sales out of
Fairview and Anchorage. Distribution transformers outside those lines are what
we'd like to discuss.

We're JZPE Power Transformer, a manufacturer in Suzhou, China: liquid-filled
padmount and pole-mount distribution transformers, UL certified
(E541627 / E541626), built to IEEE C57.12, tested at 60 Hz, with factory test
reports per unit.

One question first: outside your current brands, is there room for a complementary
transformer source by rating or spec? If yes, I'll send our UL certificates,
spec sheets and test reports.

Best regards,
{{SENDER_NAME}}
```

### 这封信的关键决策

- **第一句就请求转交并点名具体人**（Steven Breeden / George）—— 提高转发率
- **开场用对方自己的业务版图**（Howard + ERMCO 线上 EWEB 投标、柜台后的变压器组、
  Fairview 与 Anchorage 的承包商销售）
- **钩子 = `outside your current brands / outside those lines`** ——
  **不碰 ERMCO 占住的品类**，只探缺口
- 🔴 **"ERMCO 只作背景理解，信中不点名、不评价"** —— 同 TEMZ / AECI 同纪律
- **落点**：`distribution transformers outside those lines`
  —— 我方**真有的那一样**（UL 双号的液浸美变/柱上变）

> **同类对照**（同一钩子，措辞各异，避免模板感）：
> - GenPac：`outside your current brands`
> - UUS：`outside your exclusive lines`
> - AECI：`Power and substation transformers for that grid`（换切片而非换钩子）

---

## 范本三 · {{COMPANY}} 转交（变电站级 EPC + 超 UL 区间划线）

**为什么选它**：**"UL 区间与公司能力分开表述"的教科书示范**，
也是**热转交**（对方回信指人）的标准写法。

**信文件**：`clients/跟进信-Iconic-20260923-WillMyers.md`

```
主题：Substation transformers — Jeremy Thompson pointed me to you
```

```
Hi Will,

Jeremy Thompson's reply pointed me to you — picking up the thread.

Iconic builds 500 kV AIS and GIS substations end to end — engineering, earthworks,
distribution and commissioning — including the Chestermere substation, with
renewables and BESS work alongside. Substation transformers and their test data
are what we manufacture and document.

We're JZPE Power Transformer, a manufacturer in Suzhou, China: liquid-filled
substation transformers, 750 kVA to 110 MVA on our UL certificate (E541626,
IEEE C57.12), with factory test reports per unit. For ratings above our UL band,
we work to project specs — happy to start with your vendor requirements.

If Iconic sources transformers for substation or renewables work, I'll send our
UL certificate, spec sheets and test reports.

Reply "SPECS" and I'll send them over.

Best regards,
{{SENDER_NAME}}
```

### 这封信的关键决策

- **第一句点明转交来源**（Jeremy 回信指过来）——
  **热转交不是冷信，必写**
- **开场用对方的变电站能力**（500 kV AIS/GIS、端到端、Chestermere 变电站、renewables + BESS）
- 🔴 **超 UL 区间划线的句式（关键）**：
  `For ratings above our UL band, we work to project specs — happy to start with your vendor requirements.`
  → **主动说明 UL 覆盖上限之外怎么办**，而不是含糊其辞
- **落点**：`Substation transformers and their test data` ——
  用对方业务里的"test data"（他每天要审的资料）
- **jthompson@ 作废**，后续禁用

### 引用官方条件的纪律

> ⚠️ **引用官网项目前先看措辞主语**：官网若写
> "Projects We Have **Been Involved In**"（参与过）≠ "我承包的"，
> 写成"你们的项目"有风险 → 改用**服务清单 / 电压范围**开场。

---

## 范本四 · {{COMPANY}}（展会来源 + 分销商）

**为什么选它**：**骨架 C（展会）** + **分销商话术**，
且是**非北美市场（阿联酋 50 Hz）**的处理方式。

**信文件**：`clients/开发信-{{COMPANY}}.md`（另附 WhatsApp 版）

### 关键决策

- **🔥 本家不是冷启动** —— 用户在迪拜展会上已与对方建立联系（拿到 WhatsApp）
  → 邮件开头带一句展会（增加可信度与转交依据），**WhatsApp 以展会开场**（最暖的触达状态）
- **分销商 ≠ 承包商**：
  - ❌ 不说"贵司是承包商"
  - ❌ 不提"小批量试单"（对方是 900 人、$1.5 亿营收的分销商）
  - ✅ 谈**批量与年度框架**、谈**成为你们的供应商/区域代理**
- **技术钩子**：**阿联酋 50 Hz，与中国标准一致，无需频率转换**
- **钩子落点在缺口**：`transformers aren't among your listed agencies,
  and that's the only line I'd like to be considered for.`
  → 承认对方代理体系（西门子 45 年独家），**只申请那一条没有的线**
- **交付方式**：邮件 + **WhatsApp 双轨**（展会后跟进）
- ⚠️ **邮箱域名是 `.ae` 不是 `.com`**（`{{COMPANY_DOMAIN}}`）
- ⚠️ **避开周五**（阿联酋周末 = 周五+周六），**周日至周四发**

---

## 五、跟进信范本（2026-09-23 新增）

> ⚠️ 此前 4 个范本里 3 个是首封。跟进信**规则层面**已补（见 `01` §十），
> 这里给两个**真实成品**作对照。
> **规则是骨架，范本是手感** —— 两个都要看。

---

### 范本五 · 常规第 N 轮跟进（{{COMPANY}}）

**为什么选它**：**"把开放问题压成两个单词"** 的教科书示范 ——
跟进信最难的是一句话讲清"为什么值得你再花 1 分钟"。

**信文件**：`clients/跟进信-第1轮-20260923.md`（② {{COMPANY}}）

```
主题：Re: Padmount transformers for commercial and tower-site work

Hi Anthony,

Short follow-up with an easy out: if those transformers come from the
utility — on tower sites or commercial jobs — reply "utility" and I'll
close the loop, no pitch. If you buy any directly, reply "self" and
I'll send specs.

Best regards,
{{SENDER_NAME}}
```

#### 关键决策（对照 `01` §十 跟进信规则）

| 规则 | 这封怎么做 |
|---|---|
| **必须带新信息点** | 首封是**开放问题**（自购还是电力公司供）→ 这封**压成两个单词选项**（`utility` / `self`）|
| **比首封更短** | **50 词**（首封更长）—— 匹配窄的客户要更短 |
| **同线程回复** | ✅ `Re:` 原主题 |
| **不再重复个性化开场** | ✅ 直接进正题，没有再说一遍 Tower-site 观察 |
| **称呼沿用** | ✅ `Hi Anthony,`（与首封同）|
| **给低成本回复路径** | ✅ **两个词就够**，不用他动脑 |
| **退订承诺** | ✅ `with an easy out` + `no pitch`（自然语，非群发式）|

> 🔴 **`I'll close the loop` 之后的动作**（易漏）：
> 客户真回了 `utility` → **这不是"继续跟进"的信号，是"关闭对话"的信号**。
> 按 `00` §六之二：**不要**把它当拒联（那是正常回答）；
> 应该礼貌收尾、标记状态、**停止推销**（但保留长期关系）。
> ⚠️ **若客户回的是明确的 `don't contact me` → 才走拒联流程**（登记不再联系名单）。

---

### 范本六 · 热转交（{{COMPANY}} → {{CONTACT_NAME}}）

**为什么选它**：**热转交不是冷信** —— 对方回信指了人，这是**最暖的跟进场景**，
但也最容易写坏（写成第二封冷信）。

**信文件**：`clients/跟进信-Iconic-20260923-WillMyers.md`
（完整正文见范本三，此处看规则要点）

#### 热转交的四要素

| # | 要素 | 这封怎么写 |
|---|---|---|
| 1 | **第一句点明转交来源** | `Jeremy Thompson's reply pointed me to you — picking up the thread.` |
| 2 | **重新交代上下文**（新人对前情不知情）| 用一句说清 Iconic 做什么 + 我们供什么 |
| 3 | **可稍长**（但仍 ≤120 词）| 比常规跟进长，因为要重建上下文 |
| 4 | **落点接住新人的关注点** | 新人管技术 → 落点改 `Substation transformers and their test data`（他每天要审的东西）|

> ⚠️ **热转交的字数例外**：常规跟进 ≤100 词，热转交可到 **≤120 词**
> —— 因为要重述上下文。**但仍必须比首封短**（首封 60–150 词，热转交 100–120 词）。

---

## 六、从范本提炼的通用检查清单

写完后逐条过：

**首封：**

- [ ] **开场是否引用了一个"只有看过资料才知道"的具体事实**？（项目名/业务单元/电压范围）
- [ ] **钩子是否只落在自己真有的产品上**？（对照 `02_product_positioning.md` §五）
- [ ] **有没有出现"接不住的钩子"**？（对方主品类被我方无认证产品覆盖时，主动回避）
- [ ] **UL 编号与公司能力是否分开表述**？
- [ ] **是否有编造的数字/电压/年份/客户名**？（含"对方信息"见 `04` §九）
- [ ] **称呼与转交策略是否正确**？（点名 + 请求转交；B 档邮箱必走此分支）
- [ ] **是否踩了地名陷阱**？（WA Vancouver vs BC Vancouver；同名公司带城市）
- [ ] **克制的"未用清单"是否写进批注**？（这是质量自证，也是下次的弹药库）
- [ ] **60–150 词、无 spam 词、只有一个钩子**？
- [ ] **含退订承诺句**？
- [ ] **语气是否按客户所在地区调整**？（见 `01` §十四）
- [ ] **附了建议发送时间（北京时间）+ 避开发送日**？

**跟进信（另加）：**

- [ ] **带来新信息点**了吗？（对照 `01` §十 的 5 种合法类型）
- [ ] **比首封更短**？
- [ ] **同线程 `Re:`**？
- [ ] **没有 "just following up"** 类零信息量表述？
