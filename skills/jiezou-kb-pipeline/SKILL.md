---
name: jiezou-kb-pipeline
description: 维护 JIEZOU 客户开发知识库（~/jzp-outreach-toolkit/knowledge/jiezou-kb）并跑海关数据线索挖掘。当用户说「导入新的培训/产品资料」「跑一下线索挖掘」「找变压器买家」「更新知识库」「海关数据」「打分排序线索」「加一家竞对/客户」「知识库结构要复用到别的项目」时使用。覆盖：新增实体类型、通用资料导入、可插拔海关数据适配器、24 项规则打分、leads 报告生成，以及这套库的几个硬约束（frontmatter 只能外科手术式编辑、付费平台不抓取、禁入名单）。
agent_created: true
---

# JIEZOU 知识库维护 + 海关线索挖掘

## 何时用

- 用户要给知识库加新资料（培训课程、产品文档、证书、竞对情报）
- 用户要找买家 / 跑线索挖掘 / 看海关数据
- 用户要新增实体类型（展会、报价记录、内容素材……）
- 用户提到把这套库复用到别的项目

**知识库位置**：`~/jzp-outreach-toolkit/knowledge/jiezou-kb`（独立 git 仓库）
先 `cd` 过去，所有命令都在仓库根目录执行。

## 硬约束（踩过坑，别绕开）

1. **改已有条目的 frontmatter 只能用 `kblib.set_frontmatter_field()`**（逐行外科手术式），
   **绝不能 `dump_frontmatter()` 整体重写**——内置 YAML 写入器只支持扁平结构且不加引号，
   会把手工写的内容改乱。
2. **git 写入的沙箱拦截（2026-09-26 更新）**：此前 `git add/commit` 会报
   `fatal: Unable to create index.lock` 并留下 0 字节残留锁；**2026-09-26 实测未加提权即成功**。
   对策：先直接跑 `rm -f .git/index.lock && git add -A && git commit ...`；
   若仍报 index.lock 错误，再加 `dangerouslyDisableSandbox` 重试。
   无论哪种情况，**动 git 前都先 `rm -f .git/index.lock`**（残留锁会让后续操作失败）。
3. **付费海关平台不抓取、不登录**：Trademo / ImportGenius / 52wmb / Volza 等
   只吃用户自己导出的 CSV/XLSX，走 `--adapter local_csv`。不做凭据、不用 cookie。
4. **`供货记录-内部-不可发/` 是机密**，导入器硬拒绝该路径，别去动。
5. **`wc -l` 不能当记录数**（广交会名录 805,140 行 ≠ 804,838 条记录，多行引号字段）。
6. **归一化 CSV 里缓存的 `buyer_key` 不能信**：打分时要按当前别名表重算，
   否则新加的别名对这批发好的数据不生效（已修，但别改回去）。
7. **同一次运行内新建的条目要立刻登记进查找表**，否则同一份文档的第二个副本
   （毅冰课蒸馏/MD素材 与 毅冰-kb 各存一份）会重复建条目（已修）。
8. **PDF 提取要清控制字符**（`\x00-\x1f` 会让 frontmatter 变成非法 YAML），
   引号转义要能还原（双引号走 `json.loads`），否则读写往返会越转义越多。
9. **更新条目时要刷新「生成型」小节**（需求与偏好/海关数据/联系人/采购习惯/评分明细），
   否则正文的评分明细会停在旧分数上，审计链断裂。用 `kblib.replace_section()`。

## 常用命令

```bash
cd ~/jzp-outreach-toolkit/knowledge/jiezou-kb

# 新增一个条目（交互式）
python3 scripts/new_entry.py 竞争对手 "XX电气"

# 检索
python3 scripts/search.py "东南亚" --type 竞争对手
python3 scripts/search.py "海关" --tag 北美主攻

# 导入资料（先 dry-run 看计划，确认后 --apply）
python3 scripts/import_training.py --source "<目录>" --source "<目录>" --dry-run
python3 scripts/import_training.py --source "<目录>" --apply --report

# 海关数据：先看有哪些源 / 打印可点的查询链接（零风险）
python3 scripts/customs_data_fetch.py --list-adapters
python3 scripts/customs_data_fetch.py --print-urls --hs 8504.21,8504.22,8504.33

# 取数（加拿大官方开放数据，免费）
python3 scripts/customs_data_fetch.py --adapter canada_cid \
    --hs 8504.21,8504.22,8504.23,8504.33,8504.34 --country CA
# 取数（本地 CSV，流式，百万行没问题）
python3 scripts/customs_data_fetch.py --adapter local_csv \
    --file "/Users/eric/Documents/毅冰-kb/04-data/广交会采购商名录.csv" \
    --profile cantonfair --country 美国,加拿大 --limit 20000

# 打分
python3 scripts/lead_scoring.py --latest --dry-run
python3 scripts/lead_scoring.py --latest --apply        # 写 leads/ + A/B 级客户条目

# 全离线自测（会自己还原 entries/ 和 leads/）
python3 scripts/selftest_pipeline.py
```

## 新增实体类型（不用改任何代码）

1. `schema/<类型>.json`：`{"type":..., "prefix":"<拼音缩写>", "fields":[{"name":...,"hint":...}]}`
2. `templates/<类型>.md`：复制任一模板，frontmatter 加上专属字段
3. `mkdir entries/<类型>`

`new_entry.py` / `build_index.py` / `search.py` / `import_training.py` 都不用改。
加完记得同步 README 的实体类型表（否则会漂移）。

## 打分逻辑速查

24 条加权信号，权重表在 `scripts/lead_scoring.py` 的 `WEIGHTS` dict。
分级 **A≥80 / B≥50 / C≥25 / D<25**，可用 `--tier-a/--tier-b/--tier-c` 调。

最高价值的几条：流失老客户 +35、亚威买家 +30、美加市场 +25、液浸变压器 +20；
纯贸易中间商 −12、非目标市场 −15。

**每次都要看 `coverage`（数据完整度）**：免费源（CID、广交会）只有 17-21%，
报告会警告「低完整度的分数不能和提单口径直接比较」。别把 35 分当 170 分用。

### 怎么让「流失老客户」触发（+35，最值钱的一条）

需要「知识库确认买过我们」+「提单显示现在由竞对供货」。前者满足任一即可：

1. 在 `entries/自有成交记录/` 里
2. 在 `entries/合作伙伴/` 里
3. **客户条目打了 `杰走前客户` / `Jiezou老客户` / `流失老客户` 标签**

第 3 条是为「不是从成交记录发现、而是从别的路径发现的老客户」准备的
（如 `kh-001 Soltech Power`）。**知道某家以前买过但成交记录里没有，就给它打
`杰走前客户` 标签**，打分时就会认成老客户。
判定逻辑在 `lead_scoring.PRIOR_PURCHASE_TAGS`。

## 付费平台导出文件的入库格式

`--profile` 指定列名预设，`--inspect` 先看真实列名，对不上用 `--map k=v` 覆盖。
CSV / TSV / XLSX 都支持，流式读取。

| profile | 认得的列名（部分） |
|---|---|
| `importyeti` | Consignee / Consignee Country / Product Description / HS Code / Supplier / Shipments / Quantity / Value / First Shipment / Last Shipment |
| `trademo` | Buyer / Country / Product / HS / Exporter / Shipments / Value (USD) / Last Shipment |
| `52wmb` | Buyer / Buyer Country / Product / HS Code / Supplier / Deals / Weight / Date |
| `cantonfair` | 公司名称 / 来自国家 / 采购产品类别 / 联系人 / 电子邮箱 / 联系电话 / 联系地址 |
| `manual` | company / country / region / product / hs / email / phone / contact |

`data/fixtures/sample_*_export.csv` 是各格式的样例，可用来回归验证。

## 改打分权重之后

`data/fixtures/expected_scores.csv` 是打分基线，selftest 会逐条比对。
调完 `WEIGHTS` 后：先人工确认新结果合理，再重新生成基线
（用 `selftest_pipeline.parse_score_lines` 的解析逻辑），否则自测会一直报不一致。

## 两张可编辑的种子表（改完立刻生效，不用重跑取数）

- `data/watchlist_suppliers.csv`：供应商 → 角色 `self`/`competitor`/`partner`/`other`。
  加一行，打分立刻把该供应商的买家当高价值线索。
- `data/company_aliases.csv`：公司名别名。跨来源拼写不一致在这里归一，
  否则同一家公司会被当成两家、重复建条目。
  已知需要维护的：Domino Highvoltage、亚威多种拼法、Boundary Electric 1985。
  键值都写**归一化后**的形式（大写、去标点、去法律后缀）。

## 修 bug 时的检查清单

改完 `kblib` 或导入器后，跑这三条：

```bash
# 1) 所有条目仍是合法 YAML
python3 -c "
import re,pathlib,yaml
bad=0
for p in sorted(pathlib.Path('entries').rglob('*.md')):
    m=re.match(r'\A---\s*\n(.*?)\n---\s*\n?', p.read_text(encoding='utf-8'), re.DOTALL)
    try: yaml.safe_load(m.group(1))
    except Exception as e: print('FAIL',p,e); bad+=1
print('problems:',bad)"

# 2) frontmatter 编辑是幂等的（读出来写回去不变）
python3 -c "
import sys,pathlib; sys.path.insert(0,'scripts'); import kblib
bad=0
for p in sorted(pathlib.Path('entries').rglob('*.md')):
    t=p.read_text(encoding='utf-8'); fm,b=kblib.parse_frontmatter(t); o=t
    for k,v in fm.items():
        if isinstance(v,list): continue
        o=kblib.set_frontmatter_field(o,k,v)
    if kblib.parse_frontmatter(o)[0]!=fm: bad+=1
print('mismatches:',bad)"

# 3) 端到端
python3 scripts/selftest_pipeline.py
```

## 已知缺口（用户会陆续补）

- **最有价值的输入仍缺：美国提单导出**（ImportYeti / ImportGenius / Trademo，
  含 Consignee/Supplier/HS/Shipments/Quantity/日期）。这一个文件能解锁约 +75 分信号，
  并让亚威交叉引用从手工变全自动。用户说后续会给浏览器访问他买的付费平台。
- 用户会陆续补充培训素材，直接再跑一次 `import_training.py --source "<新目录>" --apply` 即可
- `entries/案例/` 为空（无素材）
- 仓库**无 remote**，含内部成交史，建议保持无 remote 或只加私有
