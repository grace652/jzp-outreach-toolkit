---
name: market-entry-playbook
description: 为一个新市场（或新区域）产出一套可落地的客户开发作战资产：调研市场与准入条件 → 写作战手册（PDF+Word）→ 建目标客户清单 → 打现有线索流水线补丁 → 出多语邮件弹药库 → 做交互式作战台。当用户说「帮我做 XX 市场的开发方案」「XX 市场怎么打」「开拓 XX 市场」「做一个新市场项目」「南美/中东/东南亚/非洲市场怎么做」时使用。基于 JIEZOU/JZP 变压器外贸业务的实战沉淀，但流程可迁移到其他品类。
agent_created: true
---

# 新市场客户开发作战系统

## 一、这个 skill 解决什么

把「开拓一个新市场」从模糊的想法，变成一套**有来源、可执行、能接上现有流水线**的资产包。

产出物固定为 5 件（不是 5 篇泛泛的报告）：

| # | 产出 | 为什么必须有 |
|---|---|---|
| 1 | 作战手册（HTML → PDF + DOCX） | 结论与依据。每条判断附可复查来源 |
| 2 | 目标客户 CSV | 能直接进现有线索流水线的格式 |
| 3 | 渠道清单 CSV | 数据源/名录/招标/展会，带可点击 URL |
| 4 | 流水线补丁 | **不修流水线，新市场线索会被自己的模型筛掉** |
| 5 | 多语邮件弹药库 | 按语言分线，不能共用文案 |

可选加一件：交互式作战台（HTML 单文件）。

## 二、铁律（违反任何一条，产出就是废的）

1. **先读现有知识库，再动笔。** 不知道客户的产品线、认证、现有市场、客户结构，做出来的东西一定对不上。至少读：`README.md`、`entries/产品知识/`、`entries/自有成交记录/`、`entries/客户/`、`scripts/lead_scoring.py` 的 `WEIGHTS`、`scripts/customs_normalize.py` 的市场常量。

2. **区分事实与推断，标注来源。** 每条关键结论后附可复查 URL。查不到就写「未查到公开信息」，**不要用模糊措辞掩盖不确定**。最后必须有一节「待核实清单」，把不确定项集中列出并标优先级。

3. **绝不编造联系方式。** 目标客户清单只列可核实的机构与公开采购入口。邮箱电话查不到就留空。这条在 `jiezou-kb` 的「信息源规范」里有明文要求。

4. **补丁必须在副本上实测。** 不要直接改用户的生产仓库。`cp -R` 到 /tmp → 改 → 跑 `selftest_pipeline.py` → 验证效果 → 生成 patch 文件 → 原仓库保持干净。

5. **改权重会打破自测基线。** 优先用**标签分层**代替改权重：加标签零风险，改权重需要重生成 `data/fixtures/expected_scores.csv`。

## 三、工作流

### Step 1 · 摸底（并行读）

```
jiezou-kb/README.md                              # 流水线怎么用、打分规则
jiezou-kb/scripts/lead_scoring.py                # WEIGHTS 表 + 打分分支
jiezou-kb/scripts/customs_normalize.py           # TARGET_MARKETS / SECONDARY_MARKETS / COUNTRY2 / CJK_COUNTRY
jiezou-kb/entries/产品知识/                       # 产品线、认证、技术参数
jiezou-kb/entries/自有成交记录/                    # 现有业绩（做背书用）
jiezou-kb/data/watchlist_suppliers.csv           # 竞对名单
~/.workbuddy-ai/skills/foreign-trade-email-dev/SKILL.md   # 邮件方法论与规范
```

### Step 2 · 调研（并行派 3 个 agent）

用 Agent 工具一次派 3 个 general-purpose agent，各带明确 brief，**要求每条结论附来源 URL、区分事实与不确定、字数上限**：

| Agent | 任务 |
|---|---|
| A | 目标区域的市场态势与贸易壁垒（需求驱动、规模、交期、关税、政策禁入区、能效法规） |
| B | 目标区域的国别优先级评估（市场规模、本地制造、关税、强制认证、频率/标准体系、付款与外汇风险）+ 采购平台 + 展会 |
| C | 线索渠道（海关数据平台对比、官方免费源、买家名录、招标公告、展会名录）+ 竞争格局（中国同行 + 当地制造商） |

**关键技巧**：在 brief 里明确写「今天是 YYYY-MM-DD，请查证最近 12 个月的最新情况，不要用过期信息」。关税政策变化极快，一年前的结论常常已经失效。

调研完如果目标客户清单还不够具体，**再派一个 agent 专门建客户清单**（要求：真实机构名 + 官网 URL + 采购入口 + 声明「未查到公开信息」而不是编造联系方式）。

### Step 3 · 写作战手册

HTML 单文件 → Chrome 转 PDF → html4docx 转 DOCX。**转换命令见下方「技术要点」**，两条都有坑。

固定章节结构：

```
封面（主体/产品/资质/编制日期）
本手册的三条前提（结论先行 / 区分事实与推断 / 不编造联系方式）
目录
0  执行摘要：三条结论          ← 一页能看完，最重要
1  市场态势
2  政策与关税地图              ← 最容易出错、最影响报价的一章
3  认证准入矩阵
4  买家地图与目标清单
5  线索获取渠道
6  竞争格局与我方定位
7  开发执行系统（语言线 / 触达节奏 / 报价策略 / 授权 / 售后）
8  90 天行动计划（分周 + 验收标准）
A  来源清单
B  待核实清单
```

**写作要求**：
- 表格优先于段落。用 `<table>`，`th` 深色底白字
- 关键判断用 `.verdict` 框（带标题的结论条）或 `.callout`（普通/警告/成功/注意四色）
- 每个结论都要回答「所以呢」——不要只陈述事实
- 主动写出**对我不利的结论**（如「这个产品线在这个市场已被政策封路」），这比只讲机会可信得多

### Step 4 · 建线索资产

**目标客户 CSV 的列名必须对齐流水线的 `manual` profile**：

```
company,country,region,product,hs,source,email,phone,contact
```

- `country` 字段**写中文国名**（`巴西`、`秘鲁`、`哥伦比亚`…），因为 `CJK_COUNTRY` 表覆盖这些；英文国名在 `COUNTRY2` 里可能缺失（见 Step 5）
- `region` 字段**写地区全称**（`São Paulo`、`Minas Gerais`），不要写州码——巴西州码与美国的撞车（PA/MA/MT/MS/AL/SC/PR），`region_of()` 会误判
- `email`/`phone` 只填**确实在公开页面上看到的**，其余留空
- 含逗号的字段用双引号包裹

### Step 5 · 打流水线补丁（这一步最容易被跳过，但最关键）

**先验证，再改。** 把目标客户 CSV 导入流水线跑一次 dry-run：

```bash
cd <kb>
python3 scripts/customs_data_fetch.py --adapter local_csv --file "<csv>" --profile manual --inspect
python3 scripts/customs_data_fetch.py --adapter local_csv --file "<csv>" --profile manual
python3 scripts/lead_scoring.py --latest --dry-run --top 30
```

**大概率会发现新市场的机构全被打成 C/D 级**。原因是两处（缺一不可）：

1. **国别解析表缺新市场国家**。`COUNTRY2`（英文名→码）和 `COUNTRY_ALIASES`（缩写→码）里没有新市场国家。英文来源 → 解析返回 `""` → 走「国别未识别，按非目标市场处理」−15 分。中文来源若能解析出码 → 走「非目标市场」−15 分。**两条路径都扣 15 分，只是标签不同。**

2. **市场分层集合未覆盖**。`SECONDARY_MARKETS` 只有加勒比与中美洲。

**补丁写法**（见 `references/补丁模板.md`）：
- **补丁 A**：`COUNTRY2` 加新市场英文全名 + `SECONDARY_MARKETS` 纳入新市场 → 自测基线**不受影响**
- **补丁 B**：新增分层集合 + 在 `lead_scoring.py` 的 `elif c2 in cn.SECONDARY_MARKETS:` 分支里 `tags.add(...)` → **只加标签不动权重**，基线仍不受影响
- **补丁 C（慎用）**：真正调权重 → 会打破 `expected_scores.csv` 基线，需按 README 说明重生成

⚠️ **绝对不要给 `COUNTRY_ALIASES` 加 2 字母码。** `country2_of()` 匹配的是 `buyer_country + buyer_address + buyer_region` 三段自由文本，用宽松正则。地址里的 `"ABC ELECTRIC CO., LTD"` 会命中 `CO` → 判定为哥伦比亚。南美国家用全名匹配（`BRAZIL` 不会误伤）已经足够。

**实测流程**：
```bash
rm -rf /tmp/kbtest && cp -R <kb> /tmp/kbtest && cd /tmp/kbtest && rm -rf .git
# 改文件
python3 scripts/selftest_pipeline.py          # 必须 26/26 全绿
# 验证效果
python3 scripts/customs_data_fetch.py --adapter local_csv --file "<csv>" --profile manual
python3 scripts/lead_scoring.py --latest --dry-run --top 30
# 生成 patch（改 header 路径）
diff -u <kb>/scripts/X.py scripts/X.py | sed '1s|.*|--- a/scripts/X.py|; 2s|.*|+++ b/scripts/X.py|' > 补丁.patch
# 校验 patch 可应用
patch -p1 --dry-run < 补丁.patch
# 清理
rm -rf /tmp/kbtest
```

**必须向用户说清楚的一点**：打完补丁后分数**可能仍然很低**。因为目录型名单的数据完整度通常只有 ~20%（没有票数/金额/日期/供应商），而打分模型权重最高的信号正是这些。**分数低 ≠ 线索质量差**——这份名单的用途是定向外呼，不是打分排序。想要打分有意义，必须补提单级数据。

### Step 6 · 出邮件弹药库

按语言分线，**每条线单独一个文件**。复用 `foreign-trade-email-dev` skill 的 Mail Group 骨架与规范（首封 ≤150 词、跟进 ≤120 词、Subject 3–6 词、无 spam 触发词、半角标点、一次只给一个主推版本）。

每条线的**主诉求必须按市场特性定，不能照搬**。判断方法：看这个市场的**本地交期 vs 进口交期**、**价格敏感度**、**认证门槛**、**售后期望**。

例（变压器，2026 年）：
| 市场 | 主诉求 | 必须避免 |
|---|---|---|
| 美国 | 交期（本土 26–40 周） | 回避「中国产」；含糊处理关税 |
| 加拿大 | CSA 合规 + 交期（本土 100+ 周） | 忽略魁北克法语要求 |
| 墨西哥 | 价格 + 认证规格 | **打交期牌**——本地 8–16 周比进口快 |
| 巴西 | 价格 + 认证成本优势 | **用西语替代葡语** |

**每个文件末尾都要有「序列使用说明」表**（节奏、语言、优先客群、招标监控关键词、skill 能力缺口提示）。

**引用客户业绩前必须取得书面授权**——附一份 `Reference-Authorization-模板.md`（三档授权：全名可提 / 仅技术描述不可署名 / 不可提）。没有书面授权，一律脱敏表述。

### Step 7 · 作战台（可选）

HTML 单文件，5 个页签：市场优先级（可排序表）/ 产品线×市场合规检查器 / 落地成本试算 / 认证缺口清单 / 90 天计划看板。

**设计原则**：
- 税率做成**可编辑输入项**，不要写死——用户有报关行的权威数字，让他替换
- 勾选进度用 `localStorage`，不上传
- 显式标注哪些数字是「估算值」哪些是「未核实」
- 无外部依赖（不引 CDN），离线可用

## 四、技术要点（都有坑，都实测过）

### HTML → PDF（Chrome headless）

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --no-pdf-header-footer --virtual-time-budget=8000 \
  --print-to-pdf="out.pdf" "file://<绝对路径>.html"
```

- **`--no-sandbox` 不可省。** 不加会报 `sandbox initialization failed: Operation not permitted` → `GPU process isn't usable. Goodbye.` → **PDF 完全不生成，但退出码仍是 0**。必须 `ls -la *.pdf` 确认文件真的存在。
- CSS 必须写 `@page { size: A4; margin: 18mm 16mm 20mm 16mm; }`，否则默认 Letter。
- 中文文件名与路径可用。

### HTML → DOCX（html4docx）

```python
# 解释器：/Users/eric/.venv-html-to-docx/bin/python
from html4docx import HtmlToDocx
h = HtmlToDocx()
doc = h.parse_html_string(html_string)   # 返回 docx.Document
doc.save("out.docx")
```

- **不是 `python -m html_to_docx`**——该模块名不存在，会报 `No module named html_to_docx`。
- **不能直接调 `run_process()`**——会报 `'HtmlToDocx' object has no attribute 'bs'`。必须走 `parse_html_string()` / `parse_html_file()`。
- 会读 `<style>` 里的 CSS，但 CSS 变量 / flexbox / 多列布局支持有限；**表格、标题、列表能正确转换**。
- **定位**：PDF 作保真版，DOCX 作可编辑版。不要期待视觉一致，也不要在交付说明里承诺一致。

### 验证交付物（别只信退出码）

```python
from docx import Document
d = Document("out.docx")
print("段落数:", len(d.paragraphs), "表格数:", len(d.tables))
```

## 五、交付前自检

- [ ] 原仓库 `git status --short` 为空（没动用户的文件）
- [ ] 补丁在副本上跑过 `selftest_pipeline.py`，全绿
- [ ] patch 文件通过 `patch -p1 --dry-run`
- [ ] 目标客户 CSV 实测能进流水线（`--inspect` 显示正确列映射与国别码）
- [ ] 手册 PDF 文件真实存在且体积合理（>500KB 说明样式渲染了）
- [ ] DOCX 段落数/表格数合理
- [ ] 手册含「待核实清单」且标了优先级
- [ ] 目标客户 CSV 无编造的联系方式
- [ ] 邮件弹药库每条线的主诉求符合该市场特性（不是照搬）
- [ ] 作战台的 JS 通过 `node --check`

## 六、参考文件

- `references/补丁模板.md` —— 流水线补丁的精确写法与实测对比表模板
- `references/作战手册骨架.md` —— 手册的章节骨架与 CSS 要点
- `references/关键人邮箱挖掘.md` —— **找具名决策人邮箱的渠道与证据分级**（拉美靠公开登记库、美加靠州政府采购门户；含发信前必做的域名信誉保护）
- `references/邮件通道接入.md` —— **让 agent 能读写用户邮箱**（先查 MX 定位服务商；企业微信走 `wecom-cli` CLI 而非 MCP；授权与能力权限是两层，必须实调确认；发冷邮件前必做的 DMARC / 子域名 / 节奏控制）
- `references/开发信发送链路.md` —— **定时发送（协议层做不到，只能本机队列）、时区窗口算法、发信前合规闸门、接入外部项目的纪律**

## 六之二、当用户要「找 N 家客户 + 关键人邮箱」时

这是本 skill 的高频变体需求。三条纪律必须先说清（否则做出来就是废的）：

1. **不要承诺成交率。** 用户可能说「要成功率 80% 以上的」。明确拒绝这个数字并解释原因（成交取决于报价/交期/账期/MOQ，不取决于名单；冷邮件真实基准：回复率 5–15%、整体成交率 1–3%），改为给每家打 **1–5 匹配度分**。
2. **关键人个人邮箱在美加拿不到 100%。** 实测 50 家拿到 48% 具名个人邮箱、20% 采购口部门邮箱。**必须给分级统计**，并说明这是行业上限。
3. **绝不编造邮箱。** 没找到写「未找到」。第三方数据商的格式推断标「未证实」，不算 A 级。

产出物固定为 3 件：
- `<N>家目标名单.csv` —— 一行一家，含关键人/职务/邮箱/邮箱等级/来源 URL/匹配度
- `可直接发送邮箱清单.csv` —— **一行一个邮箱**（一家公司多个联系人就多行），方便导入邮件工具。必须校验：零 `info@` 类通用邮箱混入、邮箱格式全部合规、无重复
- `名单使用说明.md` —— 含：现实检验、分级统计、立刻可发清单、需验证清单、另找路径清单、**情报更正（人员离职/公司被收购/域名错误）**、发信前必做

**校验脚本**（每次必跑）：
```python
import csv, re, collections
r = list(csv.DictReader(open('可直接发送邮箱清单.csv', encoding='utf-8')))
bad = [x for x in r if not re.match(r'^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$', x['邮箱'].strip())]
gen = [x['邮箱'] for x in r if re.match(r'^(info|ventas|contato|contacto|sales|contact|comercial|service)@', x['邮箱'], re.I)]
print('格式异常:', bad or '无')
print('通用邮箱混入:', gen or '无')
print('唯一邮箱:', len({x['邮箱'].lower() for x in r}), '/ 行数', len(r))
```

## 七、相关 skill

- `jiezou-kb-pipeline` —— 知识库本身的维护与线索挖掘流水线（本 skill 的下游）
- `foreign-trade-email-dev` —— 邮件写作规范与方法论（本 skill 第 6 步的上游）
