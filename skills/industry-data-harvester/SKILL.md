---
name: industry-data-harvester
description: 为一个业务项目搭建「行业数据信息库」—— 用纯 stdlib 定时抓取公开源（RSS / 官方 JSON API / 新闻聚合），去重入库并渲染人读索引。当用户说「建一个行业数据库」「自动获取行业数据」「抓行业新闻」「做个市场情报库」「自动收集竞品动态」「把行业数据存起来给写作 agent 用」时使用。也适用于给冷邮件/内容营销提供「新信息点」素材的场景。
agent_created: true
---

# 行业数据抓取库搭建

在目标项目里新建一个**完全独立**的数据模块，抓取公开行业信息，供人阅读 + 供写作 agent 引用。

## 〇、先确认四件事（不要跳过）

1. **目标项目路径**与是否允许新建目录（**默认零侵入**：只新增独立目录，不改任何现有文件）
2. **数据范围**：市场行情 / 标准法规 / 客户动态 / 竞品动态 —— 哪几类
3. **触发方式**：手动跑 / 定时跑（定时用 `automation_update`，别用 launchd/cron）
4. **使用边界**：数据能否直接进对外内容？**有没有禁语清单文件**必须遵守？

## 一、环境探测（决定技术方案）

```bash
PY=<项目的 python 解释器>
for m in requests feedparser bs4 lxml httpx pandas yaml openpyxl; do
  printf "%-12s " "$m"; $PY -c "import $m; print('OK')" 2>&1 | tail -1; done
```

**关键**：如果 `requests/feedparser/bs4` 缺失，就走**纯 stdlib**（`urllib.request` + `xml.etree.ElementTree`），
**不要为了抓 RSS 去装依赖** —— stdlib 完全够用，且不污染环境。

## 二、数据源连通性必须逐个实测

```bash
curl -sL -o /dev/null -w "%{http_code} %{size_download}B\n" --max-time 15 \
  -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" "<url>"
```

**实测踩过的坑（通用，务必先看）**
| 现象 | 原因 | 对策 |
|---|---|---|
| `403` | 站点挡默认 UA | 换浏览器 UA |
| `403` on `sec.gov` | **SEC 要求声明身份**，浏览器 UA 会被拒 | 这些域强制用自述 UA，如 `toolname/1.0 (+contact: {{CONTACT_EMAIL}})` |
| `302` + 0B | 需跟随重定向 | `curl -L` / requests 默认跟随 |
| `000` | 连接失败/被墙 | 换源，不要硬磕 |
| `405` | 该 API 需 POST | 换 GET 接口或放弃 |
| **多词查询 SSL 断开** | 某些官方 API（如 SEC EDGAR）只吃简单查询 | 用单词/短语 + 日期过滤 |
| **curl 能过但 requests 报 SSLError** | 本机代理链证书不被信任 | 捕获 SSLError 后降级 `verify=False` 重试一次；按源开关 |
| **dateutil 时区告警刷屏** | `EST`/`PST` 等缩写不被识别 | `warnings.catch_warnings()` 静默 |

### 依赖选择（先探测再决定）

```bash
for m in feedparser requests bs4 lxml dateutil trafilatura; do
  printf "%-12s " "$m"; $PY -c "import $m; print($m.__version__)" 2>&1 | tail -1; done
```

- **有 `feedparser` + `requests`** → 优先用它们（RSS 变体容错、重定向、编码都省心）
- **都没有** → 走纯 stdlib（`urllib` + `xml.etree`），别为了抓 RSS 装依赖
- **要「打开原文核实」** → `trafilatura`（正文提取最成熟）

### 🔴 原文核实的能力边界（先想清楚再承诺）

| 站点类型 | 能否自动核实 | 原因 |
|---|---|---|
| 政府/监管站点（Federal Register、SEC）| ✅ | 无反爬 |
| Cloudflare 保护站点（多数行业媒体）| ❌ | 403，需 Playwright 才行 |
| Google News 聚合链接 | ❌ | `/rss/articles/` 靠 JS 跳转，HTTP 层拿不到真实 URL |

**做法**：维护一份 `NO_VERIFY_DOMAINS`，核实前跳过，避免做无用请求；对这些条目在输出里给出「用标题+媒体名手动搜索」的指引。

**高价值结构化源（JSON API，无需 key）**
- Federal Register（美国联邦公报）`federalregister.gov/api/v1/documents.json`
- SEC EDGAR 全文检索 `efts.sec.gov/LATEST/search-index`（**只接受简单查询**）
- EIA / 各国统计机构 RSS
- Google News RSS `news.google.com/rss/search?q=...`（C 级源，item 内 `<source url>` 给真实媒体名）

## 三、目录结构（模板）

```
<项目>/行业数据/
├── README.md                  用法 + 数据模型 + 已知坑 + 对接说明
├── 抓取/
│   ├── 抓取行业数据.py          唯一脚本
│   ├── 来源清单.json            源注册表（可增删改）
│   ├── state.json             增量状态
│   └── .lock                  运行时锁
├── 数据/industry_news.json     主数据（唯一真源）
├── 出口/行业数据索引.md          人读索引（自动生成，勿手改）
└── _归档/                      历史版本
```

## 四、🔴 写入安全（必做，别省）

目标项目如果历史上出现过「并发写同一文件互相覆盖」，这里必须更严格：

1. **排他锁**：`os.open(path, O_CREAT|O_EXCL|O_WRONLY)` 写 PID；
   启动时读 PID 并 `os.kill(pid, 0)` 探活；僵尸锁则接管
2. **原子替换**：写 `.tmp` 再 `os.replace(tmp, target)` —— **绝不原地写**
3. **替换前备份**：`name.bak-YYYYMMDD-HHMM`
4. 读-改-写全程持锁

## 五、🔴 相关性过滤（不做的话数据会废掉）

**全站类 feed（行业媒体首页）必须过滤**。实测教训：某次 286 条里过半与业务无关。

**两条铁律**
1. **只认标题，不要看摘要** —— 摘要里的泛词（grid / utility / capacity）会放进大量无关新闻
2. **垂直媒体要用更严的规则** —— 如数据中心媒体的标题几乎都含 "data center"，
   宽规则形同虚设 → 需要 `relevance_level: "strict"` 只认业务核心词

**三级闸门**
| 闸门 | 配置字段 | 作用 |
|---|---|---|
| 相关性 | `relevance_filter` + `relevance_level` | 宽/严两套正则 |
| 时效 | `max_age_days` | 太旧的不入库 |
| 产量 | `per_query_limit` | 控制单源产出 |

## 六、内容红线（若目标项目有禁语清单）

**必须有 lint，且违规条目自动降级而非直接丢弃**（保留可追溯性）：

- 从项目的禁语文件（如 `04_do_not_say.md`）提取正则
- 命中 → `quote_lint_ok: false`，`usable_in` 降为 `["self"]`（仅内部背景）
- **含交期/价格语义**的条目单独标记（很多行业规定「首次触达不报交期/价格」）

## 七、每条数据必须有出处

缺 `source_url` 或 `published_at` 的条目**直接丢弃**，不入库。
聚合源（Google News）要额外记 `notes`：引用前须打开原链接、标注真实媒体名。

## 七之二、🔴 「不是句子就不是引用句」

如果模块要给写作 agent 提供**可直接粘贴的句子**（如 `quote_ready_en`），必须做这个检测：

**聚合源（Google News）的摘要常退化为「标题 + 媒体名」的拼接**，例如
`Hammond Power Adds to Transformer Manufacturing Capacity Advanced Manufacturing` ——
**这不是句子，粘进信里会露馅。**

检测方法：把 `title` 与 `publisher` 从候选句里剔除，剩余字符数 < 25 即判定无效，
**置空该字段**并标记「须人工撰写完整句」。

### 分级原则（重要）

| 层 | 过滤强度 | 理由 |
|---|---|---|
| **数据库** | 宽 | 给人看，人可自行判断 |
| **查询接口（给 agent）** | **严** | 产出直接进对外内容，不能有噪音 |

`--pick` 这类接口除了宽过滤，还要加**二次相关性过滤**（用最严的正则），
否则泛监管新闻（电价分摊、诉讼、并购）会混进来 —— 它们命中宽规则但不含任何产品信息。

### 🔴 查询接口：地域/受众用**软排序**，不要用硬过滤

**实测教训**：某模块把 `geo` 做成硬过滤，结果 `--geo CA` 返回 **0 条** ——
但「全球变压器交期紧张」这类行业信息对美加**都成立**，硬过滤把可用信息直接滤光了。

**正确做法** —— 地域/受众/产品线只作**排序权重**，不匹配的标注「参考项」仍返回：

| 维度 | 权重 |
|---|---|
| `geo` | 2 |
| `buyer_type` | 1 |
| `product_line` | 1 |

**仍然硬过滤的只有**：可信度等级、lint 结果、`status`、业务相关性。
**输出里必须标注**该条是「✅ 匹配画像」还是「⚠️ 未匹配画像（参考项）」，让人自己判断。

## 八、验收清单

1. `--dry-run` 跑通，输出计划写入条目
2. 真实跑一次，主 JSON 有数据
3. 缺出处条目数 = **0**
4. **连跑两次，第二次「新增 0 条」**（去重生效）
5. lint 命中的条目已降级
6. 索引 md 人可读
7. **禁改清单里的文件时间戳全部未变**（零侵入验证）

## 九、交付后

- 把「已知坑」写进模块 README（下次改源不用重新踩）
- 把「实测可用的源 + 特殊要求」写进 `来源清单.json` 的 `notes`
- 若用户要定时：用 `automation_update`（`scheduleType=recurring`），
  prompt 里写明工作目录、解释器绝对路径、脚本命令、报告格式
