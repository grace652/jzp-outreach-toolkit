# 客户案例引用授权模板（Reference Authorization）

> **为什么需要这个**：南美买家对「你有没有在北美卖过」高度敏感。KB 里 `entries/自有成交记录/` 的 17 家成交客户（AC Tesla、Wilson High Voltage、Black & McDonald、Domino Highvoltage 等）是可以合法引用的北美业绩——**但引用客户名称与项目细节属于对外披露，必须先取得书面同意。**
>
> **未取得授权的，一律按脱敏方式表述**（如「北美某省级配电运营商，1000kVA 变电站变压器」）。
>
> **用法**：把下面的英文邮件发给已成交客户，取得回复即可。中文版供你自己理解条款，不需要发出去。

---

## 一、邮件模板（发给客户，英文）

**Subject**: Quick permission request - project reference

```
Dear [Contact Name],

I hope you are doing well.

We are preparing technical documentation and proposals for new customers
in Canada, the United States and Latin America. Prospective customers
often ask whether we have supplied utilities and contractors in North
America.

I would like to ask your permission to reference our project together,
in one of the following levels. Please just reply with the number that
you are comfortable with:

1. Full reference - we may name your company and describe the project
   (product type, kVA rating, voltage class, delivery year), and we may
   offer your team as a reference contact for a short call.

2. Partial reference - we may describe the project technically
   (product type, kVA rating, voltage class, delivery year) but not
   name your company.

3. No reference - we will not mention the project externally.

If you choose 1 or 2, please also confirm the scope you are comfortable
with, for example:

- [ ] Product type and kVA rating
- [ ] Voltage class
- [ ] Delivery year
- [ ] Province / State
- [ ] Company name
- [ ] Reference call availability

If you would prefer we not use the project at all, that is completely
fine and will not affect our relationship or your warranty in any way.

Thank you for your time.

Best regards,
[Your Name]
[Title] | JZP Power Transformer Inc.
[Email] | [Phone]
```

---

## 二、中文说明（自己看，不必发出）

### 为什么用「三档授权」而不是简单的「同意/不同意」

直接问「能不能引用你们的项目」会让客户为难——**因为「同意」看起来是无限授权，客户不知道会被怎么用**。给三个明确档位，客户只需回一个数字，回复率会高很多。

### 建议的沟通顺序

| 顺序 | 对象 | 说明 |
|---|---|---|
| 1 | **最近的成交客户** | 关系最新鲜，回复率最高。优先 AC Tesla（2024-05）、Wilson High Voltage、Black & McDonald |
| 2 | 长期合作客户 | 关系稳，但可能已换联系人，需要先确认对接人 |
| 3 | 已流失客户 | **不要在这轮找**。流失客户对引用请求通常敏感，且容易引发不必要的联想 |

### 授权范围建议

- **优先争取档位 1（Full reference）**，因为南美买家最看重「能不能打个电话问问」。
- 客户不愿意给 reference call 但同意署名，**也有价值**——署名本身就是背书。
- **档位 2（Partial reference）是保底选项**，多数客户能接受，因为它不暴露身份。
- **档位 3 也要礼貌接受**，并在邮件里明确说明「不影响合作关系与质保」，避免客户担心拒绝会有后果。

### 合规红线

1. **没有书面授权，绝不提客户名。** 口头同意不算——邮件回复留痕才算。
2. **授权有范围。** 客户只同意披露「kVA 与交付年份」，就不要额外说省份。
3. **授权有时效。** 建议在授权邮件里注明「unless you tell us otherwise」，并在 KB 里记录授权日期，便于日后复查。
4. **不要把授权记录写进对外文件。** 授权邮件是内部凭证，放在 `entries/客户/` 或 `entries/自有成交记录/` 条目的正文里，**按 KB 的信息源规范注明来源**（见 README「信息源规范」一节）。

### 记录方式建议

在对应客户的 KB 条目正文里追加一行：

```markdown
## 案例引用授权

| 授权档位 | 授权范围 | 授权日期 | 信息来源 |
|---|---|---|---|
| 档位 1（Full reference） | 产品类型、kVA、电压等级、交付年份、省份、公司名、可提供 reference call | 2026-10-XX | 客户 [姓名] 邮件回复，2026-10-XX |
```

> 按 KB 的「信息源规范」：**任何联系人信息必须注明来源，不允许裸写。** 授权记录同理。

---

## 三、待授权清单（来自 KB `entries/自有成交记录/`）

以下是 KB 里已记录的成交客户，建议按此顺序联系授权。**标注「已取得授权」的才能在对内文件之外引用。**

| 客户 | 国家/地区 | 成交时间 | 产品与容量 | 授权状态 |
|---|---|---|---|---|
| AC Tesla | 加拿大 Ontario | 2024-05 | 1000KVA Substation Transformer / 25kVA 单相美变 | 待申请 |
| Wilson High Voltage Inc | 待补 | 待补 | 待补 | 待申请 |
| {{COMPANY}} | 加拿大 | 待补 | 待补 | 待申请 |
| Domino Highvoltage Supply Inc | 待补 | 待补 | 待补 | 待申请（同时是 KB 里的「合作伙伴」） |
| Pro 1 Electric, Inc | 美国 | 待补 | 待补 | 待申请（同时是 KB 里的「合作伙伴」） |
| Electric South | 待补 | 待补 | 待补 | 待申请 |
| POWER ELECTRONICS | 待补 | 待补 | 待补 | 待申请 |
| SGE | 待补 | 待补 | 待补 | 待申请 |
| Intellogic Engineering Inc | 待补 | 待补 | 待补 | 待申请 |
| Drunken Moose Enterprises Inc | 待补 | 待补 | 待补 | 待申请 |
| ATD Power Solutions | 待补 | 待补 | 待补 | 待申请 |
| Boundary Electric | 待补 | 待补 | 待补 | 待申请 |
| JS Energy LTD | 待补 | 待补 | 待补 | 待申请 |
| Bibico Electric Inc | 待补 | 待补 | 待补 | 待申请 |
| Jungbunzlauer Canada Inc | 加拿大 | 待补 | 待补 | 待申请 |
| iSpice Foods | 待补 | 待补 | 待补 | 待申请 |
| Anguilla Electricity Company Limited | 安圭拉 | 待补 | 待补 | 待申请 |

> **「待补」项需从 KB 条目正文的「成交明细」补齐。** 本表只列出客户名，未擅自填写容量或时间——**编造项目细节用于对外引用是严重的合规问题。**
