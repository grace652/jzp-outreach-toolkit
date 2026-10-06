# 发件箱 · 接入契约

给「写作 agent」用的稳定接口。**写作 agent 只写正文，签名与图片由发送层自动附加。**

---

## 一、流程

```
写作 agent                发送层（发件箱.py）              企业邮箱
   │                              │                          │
   │  写正文 → 产出 JSON          │                          │
   ├─────────────►  发件箱/       │                          │
   │                              │ 附加签名 + 内嵌图片       │
   │                              ├─────────────────────────►│
   │                              │                          │
   │                              │ 成功 → _已发送/           │
   │                              │ 失败 → _失败/ + .error.txt│
```

**为什么这样分**：写作 agent 不需要懂 SMTP、不需要管签名和图片、不需要处理退信和重试。
它只专注一件事——把信写好。

---

## 二、目录约定

```
发件箱/
├── 001-company-a.json      ← 待发（写作 agent 产出）
├── 002-company-b.json
├── bodies/                 ← 正文文件（如果用 html_file 方式）
│   └── 001.html
├── files/                  ← 附件
│   └── certs.pdf
├── _已发送/                 ← 发送成功后自动移入
├── _失败/                   ← 失败后移入，并生成同名 .error.txt
└── 发送日志.csv             ← 逐封记录（时间/收件人/主题/结果/失败原因）
```

---

## 三、JSON 契约

### 必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `to` | string[] | 收件人邮箱，至少一个 |
| `subject` | string | 邮件主题，不可为空 |
| `html` **或** `html_file` | string | 正文。二选一，不能都给 |

### 可选字段

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `cc` / `bcc` | string[] | — | 抄送 / 密送 |
| `text` | string | 自动生成 | 纯文本兜底版本。**建议提供**，提升送达率 |
| `attach` | string[] | — | 附件路径（相对发件箱目录或绝对路径） |
| `wrap` | bool | `true` | 是否给正文套统一字体样式 |
| `force` | bool | `false` | 正文含 `【待填…】` 时是否仍强制发送 |
| `meta` | object | — | 自由元数据，仅用于日志与归档，不参与发送 |

### `meta` 建议字段（便于后续统计）

| 字段 | 说明 |
|---|---|
| `company` | 客户公司名（日志里会显示） |
| `country` | 国家 |
| `priority` | `A` / `B` / `C`（列表里会标出来） |
| `source` | 产出方，如 `writer-agent-v1` |
| `lead_time` | 本封承诺的交期周数（便于事后核对） |

---

## 四、示例

`发件箱/示例-001.json`：

```json
{
  "to": ["{{CONTACT_EMAIL}}"],
  "subject": "Pad-mount transformers, 24-week delivery",
  "html_file": "bodies/001.html",
  "text": "Dear C. Nelson,\n\n...",
  "attach": ["files/JZP-UL-Certificate.pdf"],
  "meta": {
    "company": "{{COMPANY}} Co. of Houston",
    "country": "US",
    "priority": "A",
    "lead_time": 24,
    "source": "writer-agent-v1"
  }
}
```

或者正文直接内联（适合短信）：

```json
{
  "to": ["buyer@example.com"],
  "subject": "Transformadores tipo pedestal",
  "html": "<p>Estimado/a Juan:</p><p>...</p>",
  "meta": {"company": "Alianza Eléctrica", "country": "MX", "priority": "A"}
}
```

---

## 五、发送层会自动做的事

写作 agent **不需要**处理这些：

1. **附加企业签名** —— 自动拼在正文后面（含 Logo、认证标识条、产品图、联系方式、社交图标）
   - 若正文里已含签名（检测 `jiezoupower` + `<table`），则不重复附加
2. **内嵌签名图片** —— 图片走 CID 内嵌，收件人**无需点「显示图片」**即可看到
3. **生成纯文本兜底** —— 未提供 `text` 时自动生成
4. **发送间隔** —— 默认每封间隔 90 秒，避免触发风控
5. **归档与日志** —— 成功移 `_已发送/`，失败移 `_失败/` 并写 `.error.txt`
6. **占位符拦截** —— 正文含 `【待填…】` 直接跳过（除非 `force: true`）

---

## 六、安全闸

| 闸门 | 行为 |
|---|---|
| 不加 `--send` | 只列出，绝不发送 |
| 加 `--send` 但不加 `--yes` | 需要输入 `yes` 二次确认 |
| **`--redirect-to <邮箱>`** | **测试专用：无论 JSON 里写的是谁，只发到这个地址** |
| 正文含 `【待填…】` | 跳过该封，记日志 |
| JSON 校验失败 | 跳过该封并打印具体错误，不影响其他封 |

**这些闸门是防止「写了一半的信被发出去」。写作 agent 应该总是产出完整内容。**

### ⚠️ 测试时的强制要求

**任何时候测试发送，都必须加 `--redirect-to`。**

```bash
python3 发件箱.py --send --yes --redirect-to 你的邮箱@example.com
```

**原因（真实事故）**：2026-09-27 测试时，发件箱里混进了一个「示例文件」，
但它的收件人写的是**真实客户邮箱**。执行 `--send` 时它被一并发出去了，
**一封带虚构交期数字的冷邮件发给了真实客户**。

**教训**：
1. 示例文件**绝不能放在发件箱根目录**——放 `发件箱/示例/`（发送层只扫根目录，不递归）
2. 示例文件里的收件人**一律用 `test@example.com`**，不要用真客户
3. **测试发送永远加 `--redirect-to`** —— 这是最后一道保险

---

## 七、常用命令

```bash
# 看发件箱里有什么
python3 发件箱.py

# 只校验格式，不发送
python3 发件箱.py --check

# 【测试】重定向到自己的邮箱，绝不发给真实客户
python3 发件箱.py --send --yes --redirect-to me@example.com

# 小批量试水（只发前 3 封）
python3 发件箱.py --send --limit 3

# 全量发送
python3 发件箱.py --send --yes

# 放慢节奏
python3 发件箱.py --send --yes --interval 180

# 发送后保留 JSON（便于重放）
python3 发件箱.py --send --yes --keep
```

---

## 八、给写作 agent 的实现建议

1. **一个客户一个 JSON 文件**，文件名建议 `<序号>-<公司slug>.json`，便于排序与排查
2. **正文用 HTML 片段**（`<p>` / `<ul>` / `<strong>` / `<a>`），不要写 `<html>` / `<body>` 外壳
3. **不要写签名** —— 发送层会加，重复了会被检测到但不美观
4. **`text` 字段建议提供** —— 纯文本版能显著降低被判垃圾邮件的概率
5. **`meta.lead_time` 一定要填** —— 事后核对交期承诺是否一致
6. **产出的文件先放 `发件箱/`，不要直接调 SMTP** —— 让发送层统一处理归档与日志
