# jiezou-kb 客户开发知识库

纯文本、git 版本化的客户开发知识库：markdown 存内容，JSON 存索引，Python 脚本负责建条目 / 建索引 / 检索。不用数据库，任何 AI 工具（n8n、Claude Code 等）都可以直接读 `index/index.json` + `entries/` 作为知识来源。

## 目录结构

```
jiezou-kb/
├── schema/        # 每种实体类型的字段定义（JSON），新增类型在这里加一份
├── templates/     # 对应的 markdown 模板
├── entries/       # 实际内容，按类型分子文件夹
├── index/
│   └── index.json # 自动生成的全量索引，不要手动编辑
├── data/          # 线索流水线的工作数据层（配置进库，抓取数据忽略）
├── training/      # 生成物：资料索引 + 未导入清单
├── leads/         # 生成物：线索总表 + 打分明细
├── scripts/
│   ├── kblib.py                   # 公共工具（frontmatter 解析/外科手术式编辑、索引扫描、id 分配）
│   ├── new_entry.py               # 交互式创建新条目
│   ├── build_index.py             # 扫描 entries/ 重建 index.json
│   ├── search.py                  # 按关键词/类型/标签检索
│   ├── officedoc.py               # 标准库优先的文档文本提取（docx/pptx/xlsx/doc/pdf）
│   ├── import_owned_orders.py     # 自有成交记录 → 条目
│   ├── import_training.py         # 通用资料导入器（可重跑、幂等）
│   ├── customs_normalize.py       # 公司名/国别/HS 码归一化 + 两张种子表
│   ├── customs_adapters.py        # 海关数据适配器（canada_cid / local_csv / paid_portal）
│   ├── customs_data_fetch.py      # 取数 CLI
│   ├── lead_scoring.py            # 线索打分
│   ├── fix_frontmatter_quoting.py # 修正非法 YAML 值
│   └── selftest_pipeline.py       # 全离线端到端自测
└── README.md
```

## 快速上手

```bash
# 1. 遇到一条新信息（比如发现一家竞对公司）
python3 scripts/new_entry.py 竞争对手 "XX电气"
#    按提示填写专属字段，回车可跳过；完成后自动刷新索引

# 2. 需要查资料时
python3 scripts/search.py "东南亚" --type 竞争对手
python3 scripts/search.py "变压器" --tag 高压
python3 scripts/search.py "认证"            # 不加过滤条件则全库搜索

# 3. 手动改过 markdown 后，重建索引
python3 scripts/build_index.py

# 4. 每次积累后提交，保留历史
git add -A && git commit -m "新增竞对：XX电气"
```

## Frontmatter 说明

所有条目共用通用字段：

| 字段 | 说明 |
|------|------|
| `id` | 唯一标识，脚本自动生成：类型拼音缩写-序号，如 `jzd-001` |
| `type` | 实体类型 |
| `name` | 名称 |
| `created` / `updated` | 创建 / 最后更新日期 |
| `tags` | 自由标签，如 `["东南亚", "高压变压器"]` |
| `related` | 关联的其他条目 id，形成轻量知识图谱 |
| `source` | 信息来源，如 "招标网站" / "客户口述" / "展会" |

各类型的专属字段定义在 `schema/<类型>.json`。frontmatter 负责结构化检索，正文完全自由书写。

## 信息源规范（2026-09-08 起）

**规则：任何条目中出现的联系人信息（人名、职务、电话、邮箱、微信等）必须同时注明信息来源，不允许裸写。**

- frontmatter 的 `联系人` 字段只放一行摘要，不塞来源
- 正文里的联系人一律用带**信息来源列**的表格：

```markdown
| 姓名/主体 | 职务/联系方式 | 信息来源 |
|---|---|---|
| 张三 | 采购经理 · +86-138xxxx | LinkedIn 公司页 |
| 采购邮箱 | sales@example.com | Trademo 提单 MEDUOI556699 |
```

- 来源要具体到能复查：网址、平台+条目名（如 Trademo 公司页、ImportYeti 提单号、报道标题）、文档名
- 查不到公开来源的信息（如客户口述）：写 `来源：未证实（YYYY-MM-DD 某某口述）`，宁可标明不确定，也不裸写
- 新建条目时 `new_entry.py` 的提示语和各模板中已内置此规范的提醒

## 当前支持的实体类型

| 类型 | id 前缀 | 专属字段 |
|------|---------|----------|
| 竞争对手 | jzd | 主营产品、价格带、优势市场、已知劣势、关键联系人 |
| 案例 | al | 项目名称、客户名、结果、关键原因、涉及金额或容量 |
| 合作伙伴 | hhb | 合作类型、合作起始时间、联系人 |
| 客户 | kh | 所在行业、采购品类、历史订单、跟进状态、联系人 |
| 产品知识 | cpzs | 型号、参数范围、适用认证、常见配套需求 |
| 自有成交记录 | cjjl | 客户名、国家地区、成交时间、产品与容量、项目名称 |
| 培训资料 | pxzl | 主题、原始文件、文件类型、核心要点、适用场景 |

## 新增一种实体类型（不改任何代码）

1. `schema/行业展会.json`：定义 `type`、`prefix`（id 前缀）和 `fields`（字段名 + 提示语）
2. `templates/行业展会.md`：复制任一模板，frontmatter 里加上专属字段
3. `mkdir entries/行业展会`（其实不建也行，new_entry 会自动创建）

完成。`new_entry.py` / `build_index.py` / `search.py` 无需改动。

## 海关数据线索挖掘流水线

从海关数据/名录里找出「有真实采购需求但不容易搜到」的买家，打分排序后写成线索。
**只做发现和筛选**——不做群发邮件、不做自动加好友，联系和跟进仍然人工。

### 四步流程

```bash
# 1) 看有哪些数据源适配器
python3 scripts/customs_data_fetch.py --list-adapters

# 2) 零风险：只打印可点的查询链接，不抓取任何东西
python3 scripts/customs_data_fetch.py --print-urls --hs 8504.21,8504.22,8504.33

# 3) 取数 → 归一化（结果只落 data/，永不写 entries/）
python3 scripts/customs_data_fetch.py --adapter canada_cid \
    --hs 8504.21,8504.22,8504.23,8504.33,8504.34 --country CA
python3 scripts/customs_data_fetch.py --adapter local_csv \
    --file "/path/to/名录或导出文件.csv" --profile cantonfair \
    --country 美国,加拿大 --limit 20000

# 4) 打分 → 生成线索
python3 scripts/lead_scoring.py --latest --dry-run     # 先看结果
python3 scripts/lead_scoring.py --latest --apply       # 写 leads/ 并为 A/B 级建客户条目
```

### 数据源适配器

| 适配器 | 性质 | 说明 |
|---|---|---|
| `canada_cid` | 联网 · 免费官方 | 加拿大 ISED「进口商数据库」，开放数据（OGL-Canada）。只公布主要进口商名称 + HS6 + 城市/省份，**没有票数、金额、日期、供应商**。 |
| `local_csv` | 离线 | 本地 CSV/TSV/XLSX。内置 `cantonfair` / `importyeti` / `52wmb` / `trademo` / `manual` 列名预设，可用 `--map` 覆盖。严格流式，百万行也不爆内存。 |
| `paid_portal` | 占位 | **不做凭据登录、不抓取**。正确姿势：你登录自己的付费平台导出 CSV/XLSX，再用 `local_csv` 解析。 |

首次接入一个新来源时，先 `--inspect` 看它的真实列名，再用 `--map` 对齐。

### 打分规则

24 条加权信号，每条加减分都写进 `leads/leads.csv` 和条目正文的「评分明细」，可逐条追溯。
核心几条：

| 信号 | 分值 | 为什么 |
|---|---|---|
| 流失老客户（买过我们、后来走了） | **+35** | 转化概率最高——已经认可过我们，只是被撬走了 |
| 亚威买家（竞对已证明需求） | **+30** | 免费数据里信号最强的一条：竞对的提单证明这家有真实重复需求 |
| 美加主攻市场 | +25 | 物流/认证/交期只支持这两地 |
| 产品强匹配（液浸变压器 8504.21/22/23） | +20 | JIEZOU 主力产品线 |
| 纯贸易中间商 | −12 | 压价、无忠诚度、易被替换 |
| 非目标市场 | −15 | 避免把已搁置的市场又翻出来 |

分级：**A ≥80（立即跟进）· B ≥50（优先）· C ≥25（观察池）· D <25（暂不跟进）**。
阈值可用 `--tier-a/--tier-b/--tier-c` 调整。

### 怎么让「流失老客户」信号触发（+35，最高价值的一条）

这条信号需要「知识库确认这家买过我们」+「海关数据显示现在由竞对供货」两个条件同时成立。
「买过我们」有三个来源，满足任一即可：

1. 这家在 `entries/自有成交记录/` 里（从 `公司成单客户` 导入的 17 家）
2. 这家在 `entries/合作伙伴/` 里
3. **客户条目上打了 `杰走前客户` / `Jiezou老客户` / `流失老客户` 标签**

第 3 条是为那种「不是从成交记录里发现、而是从别的调研路径发现的老客户」准备的
（例如 `kh-001 Soltech Power`——它是从海关数据反查出来的，不在成交记录里，
所以靠标签表达）。**如果你知道某家以前买过、但成交记录里没有，就给它打上
`杰走前客户` 标签**，打分时就会把它认成老客户。

### 导出文件格式

从付费平台导出后，用 `--profile` 指定列名预设，`--inspect` 可以先看真实列名：

| profile | 适用 | 认得的列名（部分） |
|---|---|---|
| `importyeti` | ImportYeti 导出 | Consignee / Consignee Country / Product Description / HS Code / Supplier / Shipments / Quantity / Value / First Shipment / Last Shipment |
| `trademo` | Trademo 导出 | Buyer / Country / Product / HS / Exporter / Shipments / Value (USD) / Last Shipment |
| `52wmb` | 52wmb 导出 | Buyer / Buyer Country / Product / HS Code / Supplier / Deals / Weight / Date |
| `cantonfair` | 广交会名录 | 公司名称 / 来自国家 / 采购产品类别 / 联系人 / 电子邮箱 / 联系电话 / 联系地址 |
| `manual` | 手工整理的名单 | company / country / region / product / hs / email / phone / contact |

列名对不上就用 `--map buyer_name=你的列名,hs_code=你的列名` 覆盖。
CSV / TSV / XLSX 都支持，且是流式读取——百万行名录内存也不会涨。

> **注意数据完整度。** 免费来源拿不到票数/金额/日期/供应商，算不出来的信号就不算分，
> 并在每行输出 `coverage`。完整度 <40% 时报告会明确警告——
> **低完整度的 35 分不能和提单口径的 170 分直接比较**。
> 想解锁全部信号，最有价值的一份输入是**美国提单导出**
>（ImportYeti / ImportGenius / Trademo，含 Consignee/Supplier/HS/Shipments/Quantity/日期）。

### 打分是幂等的

按公司名归一化键匹配已有条目：命中就外科手术式更新（只改 `updated`/`历史订单`，
仅在状态为空或仍是「新线索」时才动 `跟进状态`，追加一条 `跟进记录`），未命中才新建。
**永不删除、永不重复**；同一家公司已经作为「合作伙伴」或「自有成交记录」存在的，
不会再建一个「客户」条目。

### 输出

| 路径 | 内容 |
|---|---|
| `leads/index.md` | 分级总表 + 流失客户专报（生成物，勿手改） |
| `leads/leads.csv` | 完整列表，含每一个信号的加减分（可审计） |
| `leads/<公司名>.md` | A/B 级线索落成的真实「客户」条目 |
| `data/cache/` `data/raw/` `data/normalized/` | 抓取缓存与中间数据，**已 gitignore** |

### 两张可编辑的种子表

- `data/watchlist_suppliers.csv` —— 供应商 → 角色（`self`/`competitor`/`partner`/`other`）。
  往这里加一行，打分立刻把该供应商的买家当高价值线索。**这是「竞对买家」信号可配置而非写死的关键。**
- `data/company_aliases.csv` —— 公司名别名。跨来源拼写不一致（如
  `Domino Highvoltage` vs `Domino Highvoltage Supply Inc`）在这里归一，
  否则同一家公司会被当成两家、重复建条目。

---

## 资料导入（培训 / 产品资料）

```bash
# 先看计划，不写任何东西
python3 scripts/import_training.py --source "<目录>" --source "<目录>"

# 确认后执行
python3 scripts/import_training.py --source "<目录>" --apply --report
```

- **通用**：`--source` 可重复，目录递归；以后新增素材再跑一次即可
- **幂等**：以源文件 sha256 前 12 位作「内容指纹」，并按「类型+标题」兜底匹配。
  改名能认出来、内容变了原地更新、同一份文档的多个副本只记一条（其他副本路径写在
  「来源与提取说明」里）、新文件才新建
- **不猜**：提取不到文本就生成 stub 条目并记入 `training/未导入清单.md`，说明原因
- **合规**：默认硬拒绝「不可发/内部」类路径；原文里的第三方联系方式只留在「原文存档」，
  绝不写进 `联系人` 字段

文件类型处理：`.md` / `.docx` / `.pptx` / `.xlsx` / `.doc` 用标准库或 macOS 自带 `textutil`；
`.pdf` 优先用隔离 venv 里的 `pypdf`（见下）。老式 `.ppt` 无法解析，只会生成 stub。

```bash
# 让 PDF 能被提取（可选，装到隔离环境，不污染系统）
python3 \
  -m venv /Users/eric/.workbuddy-ai/binaries/python/envs/default
/Users/eric/.workbuddy-ai/binaries/python/envs/default/bin/pip install pypdf
```

输出：`training/index.md`（按主题分组的人工索引）、`training/未导入清单.md`。

---

## 自测

```bash
python3 scripts/selftest_pipeline.py
```

全程离线，验证 26 组不变量（流式读取、归一化、自有成交记录、竞对交叉引用、
打分与基线一致、抓取不写 entries/、打分幂等、禁入名单）。
结束时会把 `entries/` 与 `leads/` 完整还原。

`data/fixtures/` 里是自测用的固定样本：

| 文件 | 用途 |
|---|---|
| `customs_sample.csv` | 15 条归一化记录，覆盖竞对买家/流失老客户/中间商/非目标市场等场景 |
| `expected_scores.csv` | **打分基线**。改动 `WEIGHTS` 权重后如果分数变了，自测会报出是哪一条不一致 |
| `sample_importyeti_export.csv` / `sample_trademo_export.csv` / `sample_52wmb_export.csv` / `sample_manual_list.csv` | 各平台导出格式的样例，用来验证列名预设 |
| `sample_export.xlsx` | 验证 xlsx 输入分支 |

改了打分权重之后，确认新结果合理，再用
`python3 scripts/selftest_pipeline.py` 里的 `parse_score_lines` 逻辑重新生成基线。

## 依赖与升级路径

- Python 3 标准库即可运行；装了 pyyaml 会自动优先使用，没装则用内置解析器，无需 `pip install`
- 检索目前是关键词匹配。数据量大了以后可给正文生成 embedding 存到 `index/embeddings.json`，给 `search.py` 加 `--semantic` 参数走语义检索——核心数据始终是纯 markdown + index.json，这一步是纯增量
