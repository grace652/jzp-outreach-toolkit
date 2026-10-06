# 行业数据信息库

> JZP 北美开发信项目 · 独立模块 ｜ 建立：2026-10-03
> **本模块不修改项目任何现有文件**，尤其不碰写信 agent 的规范与脚本（见 §六）

---

## 一、这是什么

一个**储存 + 自动获取行业数据**的独立模块，覆盖四类内容：

| 类别 | 说明 |
|---|---|
| `market_supply` | 市场与供应链行情（交期、需求、电网投资、数据中心用电）|
| `standards_cert` | 标准与认证动态（DOE / UL / CSA / IEEE / 联邦公报）|
| `customer_activity` | 客户业务动态（扩张、中标、重大合同）|
| `competitor` | 竞品与同行动态 |

**两个用途**：① 给人看（`出口/行业数据索引.md`）② 未来供写信 agent 写跟进信时引用「新信息点」

---

## 二、目录结构

```
行业数据/
├── README.md                    本文件
├── 抓取/
│   ├── 抓取行业数据.py           唯一脚本（纯 stdlib，零依赖）
│   ├── 来源清单.json             源注册表（可增删改）
│   ├── state.json               增量状态（自动生成，勿手改）
│   └── .lock                    运行时锁（自动生成/删除）
├── 数据/
│   └── industry_news.json       主数据（唯一真源，脚本写）
├── 出口/
│   └── 行业数据索引.md           人读索引（自动生成，勿手改）
└── _归档/                       历史版本备份
```

---

## 三、怎么用

**依赖**（已装入隔离环境 `/Users/eric/.workbuddy-ai/binaries/python/envs/default`，无需再装）：

| 库 | 版本 | 用途 |
|---|---|---|
| feedparser | 6.0.14 | RSS / Atom 解析（事实标准）|
| requests | 2.34.2 | HTTP 客户端 |
| beautifulsoup4 | 4.15.0 | HTML 解析 |
| lxml | 6.1.3 | bs4 的高速后端 |
| python-dateutil | 2.9.0 | 日期解析 |
| trafilatura | 2.3.0 | 正文提取（`--verify` 用）|

解释器：
```bash
PY=python3
cd "~/jzp-outreach-toolkit/projects/jzp-americas-dev/行业数据"
```

| 命令 | 作用 |
|---|---|
| `$PY 抓取/抓取行业数据.py` | **全量抓取并入库**（默认手动触发）|
| `$PY 抓取/抓取行业数据.py --dry-run` | 只看会写什么，**不落盘** |
| `$PY 抓取/抓取行业数据.py --list-sources` | 列出所有源及状态 |
| `$PY 抓取/抓取行业数据.py --source utilitydive` | 只抓指定源 |
| `$PY 抓取/抓取行业数据.py --category competitor` | 只抓某类别 |
| `$PY 抓取/抓取行业数据.py --render-only` | 只重渲 md 索引（不联网）|
| `$PY 抓取/抓取行业数据.py --pick --geo US --product distribution` | **查询候选「新信息点」** |
| `$PY 抓取/抓取行业数据.py --verify --limit 5` | **打开原文提取正文**（引用前核实）|
| `$PY 抓取/抓取行业数据.py -v` | 详细日志 |

**定时**：脚本已支持定时，但**当前只手动触发**。要改成每天自动跑，配一个 WorkBuddy automation 即可（建议 08:30，早于每日 09:00 的回复扫描）。

---

## 四、数据模型（`数据/industry_news.json`）

每条记录的关键字段：

| 字段 | 说明 |
|---|---|
| `id` | `sha1(source_id + canonical_url)`，去重主键 |
| `category` | 四类之一 |
| `title` / `summary_zh` / `summary_raw` | 标题、中文摘要（待补）、原文摘要 |
| `source_name` / `source_url` | **必填**，可追溯 |
| `published_at` / `fetched_at` | 发布日期 / 抓取日期 |
| `credibility` | `A` 一手（监管/官方 API）｜`B` 行业媒体｜`C` 聚合 |
| `quote_ready_en` | **预审过的英文句**，可直接引用 |
| `tags` | 自动推断（lead_time / UL / DOE / data_center …）|
| `audience_slice` | `{geo, buyer_type, product_line}` 自动推断 |
| `usable_in` | `["self","followup"]` 或 `["self"]`（后者=仅内部背景）|
| `do_not_say_flags` | 红线提示 |
| `status` / `used_in` | `new` / 已用于哪些客户 |

---

## 五、数据源与已知坑

| 源 | 实测状态 | 备注 |
|---|---|---|
| Utility Dive | ✅ | 全站 feed，需相关性过滤 |
| Data Center Dynamics | ⛔ 禁用 | 内容以 IT / GPU / 数据中心基建为主，与变压器设备相关性低 |
| EIA Today in Energy | ✅ | 响应慢（~11s），timeout 已放宽 |
| pv magazine USA | ⛔ 禁用 | 内容全为光伏，严格过滤后产出 0 条；且本机代理需 `insecure_ssl` |
| Federal Register API | ✅ | 官方 JSON；query 需用短语，否则返回大量无关文件 |
| SEC EDGAR 全文检索 | ✅ | 官方 JSON；⚠️ **只接受简单查询**，多词短语会 SSL 断开；⚠️ 需声明身份 UA |
| Google News RSS | ✅ | **需跟随 302 重定向**；C 级源，引用前必须核实原文 |
| T&D World | ⛔ 禁用 | 实测连接失败（curl 000）|

### 🔴 已知限制：原文核实（`--verify`）

trafilatura 只能核实**无反爬的文章页**。实测结论：

| 站点类型 | 能否自动核实 | 原因 |
|---|---|---|
| 政府站点（Federal Register、SEC）| ✅ | 无反爬（FedReg 实测提取 10 万字符）|
| Utility Dive / Data Center Dynamics | ❌ | Cloudflare 403 |
| Google News 聚合链接 | ❌ | 跳转靠 JS，HTTP 层拿不到真实 URL |

脚本已内置 `NO_VERIFY_DOMAINS` 跳过这些域，避免做无用请求。
**这类条目引用前请人工点开链接确认。**

### 过滤机制（两级）

- **宽规则**（`relevance_filter: true`）：标题须含变压器/电力行业词
- **严规则**（`relevance_level: "strict"`）：只认变压器核心词（transformer / substation / kVA / 电网设备）
- **时效闸门**（`max_age_days`）：太旧的条目不进库
- **每查询上限**（`per_query_limit`）：控制单源产出量

> 调整过滤强度 → 改 `抓取/来源清单.json` 里对应源的字段，重跑即可。

---

## 六、🔴 红线（依据 `开发信项目/04_do_not_say.md`）

脚本已内置 lint，违规条目自动降级为「仅内部背景」：

| 拦截项 | 处理 |
|---|---|
| `CSA Certified` / `SASO` / `SONCAP` | 命中即降级 |
| `YAWEI`（同行品牌）| 命中即降级 |
| spam 词（free / discount / best price / guarantee / 100% / !!!）| 命中即降级 |
| **含交期/价格语义** | 自动标记「不可用于跟进信正文，仅作背景」|

**竞品类条目（`competitor`）仅供内部参考** —— 04 号文件明令信中不得与竞品对比、不得点名对方独家品牌。

**引用要求**：任何引用必须能追溯到该条目的 `source_url` + `published_at`。
Google News 来源的条目，引用前须**打开原链接、标注真实媒体名**，不得以 google.com 为出处。

---

## 七、未来对接写信 agent（**本期未实施**）

数据是只读 JSON，写信 agent 将来可通过查询接口取用：

```bash
$PY 抓取/抓取行业数据.py --pick --geo CA --buyer EPC --product distribution --limit 3
```

返回 1–3 条候选「新信息点」，每条含：标题、来源（名称+链接）、发布日期、可直接引用的英文句。

**筛选逻辑**：`status == "new"` 且 `usable_in` 含 `followup` 且 `credibility ∈ {A,B}` 且 lint 通过。

> ⚠️ **具体怎么接线由用户决定。** 本模块未修改、也不会修改以下文件：
> `开发信项目/01_skill_email_writing.md`、`05_input_contract_from_project2.md`、
> `00_custom_instructions.md`、`04_do_not_say.md`、`scripts/生成跟进信-*.py`、
> `scripts/构建跟进队列-*.py`、`拆分跟进信.py`、`开发信项目/clients/**`、
> `开发信项目/工作区/开发信跟进表.*`

---

## 八、维护

- **增删数据源** → 编辑 `抓取/来源清单.json`，先跑 `--dry-run` 验证
- **写入安全** → 脚本用排他锁 + `os.replace` 原子替换 + 时间戳备份
  （项目历史发生过「并发写同一文件互相覆盖」事故，故此处更严格）
- **重复跑** → 幂等，已入库条目不会重复（实测第二次跑「新增 0 条」）
- **数据异常** → 直接删掉 `数据/industry_news.json` 重抓即可（源清单不动）

### 当前状态（2026-10-03，成熟库版）

| 项 | 值 |
|---|---|
| 条目总数 | **45** |
| 启用源 | **7**（禁用 3：T&D World 不可达、pv magazine 与 DCD 相关性不足）|
| 缺出处条目 | **0** |
| 可直接引用句（`quote_ready_en`）| 23 条（A 16 / B 4 / C 3）|
| 需人工改写 | 22 条 —— Google News 摘要退化为「标题+媒体名」，不是句子 |
| 幂等验证 | 连跑两次「新增 0 条」✓ |

> **关于 `quote_ready_en`**：该字段只保留**真正的句子**。若某条目的摘要实质是
> 「标题 + 媒体名」的拼接（Google News 常见），脚本会置空并打上
> 「仅有标题、无可用摘要 —— 引用前须人工撰写完整句」的标记，`--pick` 会自动跳过这类条目。
> **人看索引时仍能看到全部 45 条，但写信 agent 只会拿到可直接用的 23 条。**

### 版本

| 版本 | 说明 |
|---|---|
| v1（stdlib）| 纯 `urllib` + `xml.etree`，零依赖。已归档至 `_归档/抓取行业数据-stdlib版-20261003.py` |
| **v2（当前）** | feedparser + requests + bs4 + trafilatura。解析更健壮，新增 `--verify` 原文核实 |

### 待办

- [x] ~~补中文摘要~~ —— 用户明确不需要（读英文无障碍）
- [ ] 若需要，配 automation 实现每日自动抓取
- [ ] 客户动态类可升级为「按客户名逐个查询」（当前是通用关键词）
- [ ] 可选：给 Cloudflare 站点接 Playwright，实现自动核实（当前需人工）
