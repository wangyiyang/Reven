# Research: 搜索扩展到画像字段 — 触点调研（#201 P4）

- Query: GitHub issue #201 P4 — CRM 客户搜索与 talents q 搜索扩展到画像字段
- Scope: internal
- Date: 2026-10-06

## 1. CRM 搜索现状

**匹配字段与运算符**：`server/src/reven/crm/repository.py:87-106` `_customer_search(query)`：

- 模式：`pattern = f"%{query}%"`（:89），`or_` 组合，**运算符为 ILIKE**（大小写不敏感的包含匹配）；
- **未做 LIKE 通配符转义**（用户输入的 `%`/`_` 会被当作通配符——与 talents 行为不一致，见 §2）；
- 客户字段：`Customer.name.ilike`（:102）、`Customer.source.ilike`（:103）、`Customer.notes.ilike`（:104）；
- 联系子表：相关 **EXISTS 子查询**（:90-100）匹配 `Contact.name / phone / email / wechat`（:94-97）；
- 由 `list_customers` 在 :63-64 应用（`statement.where(self._customer_search(query))`）。

**调用方**（`CrmRepository.list_customers` 的全部调用方，grep 确认无遗漏）：

| 调用方 | 位置 | 说明 |
|---|---|---|
| REST list 端点 | `server/src/reven/api/routes/crm.py:71-84`（`GET /api/crm/customers`，`query` 参数定义在 :76，`Query(default=None, min_length=1, max_length=200)`） | web 列表页数据源 |
| MCP `crm_customer_list` | `server/src/reven/agent/tools_crm_customers.py:34-60`（注册于 `tools_crm.py:16`） | query 参数描述 :36-39 |
| MCP `crm_lead_funnel` | `tools_crm_customers.py:151` | 固定 `query=None`，不受影响 |
| MCP `crm_due_follow_ups` | `tools_crm_customers.py:170-171` | 固定 `query=None`，不受影响 |

dashboard / 提醒不走 `list_customers`（`dashboard/service.py:156-157` 用 `count_due_follow_ups` + `list_due_follow_ups`；`crm/follow_up_reminder.py:24` 用 `list_due_follow_ups`）。

**测试断言位置**：

- REST：`server/tests/api/test_crm.py:57` `test_customer_crud_search_and_filters`；搜索断言在 :83-84（`query="可搜索"` 命中**联系人姓名**，属当前最深的覆盖面断言；source/notes 的搜索无独立断言）。
- MCP：`server/tests/agent/test_tools_crm.py:68` `test_customer_list_supports_query_status_and_due_filters`（按名称 :90、按联系人 :93、空结果 :102）；MCP-over-HTTP 契约 :489（`crm_customer_list` `{"query": "协议"}`）。

## 2. talents q 现状

**匹配字段与运算符**：`server/src/reven/talents/repository.py:107-130` `_filtered`：

- q 过滤在 :120-127：`pattern = f"%{_escape_like(query)}%"`，`or_(Talent.name.ilike(pattern, escape="\\"), Talent.organization.ilike(pattern, escape="\\"))`；
- `_escape_like`（:23-24）转义 `\`、`%`、`_`，`ilike(..., escape="\\")`——**即只匹配 name / organization 两个字段，ILIKE 包含匹配且转义正确**；
- tag 过滤在 :128-129：`Talent.tags.contains([tag])`（JSONB `@>` 包含，单标签精确匹配，非模糊）。

**REST 与 MCP 是否共用过滤路径**：是。REST `list_talents`（`server/src/reven/api/routes/talents.py:76-90`，`q` 参数 :81 `Query(min_length=1, max_length=200)`，`tag` :82）→ `TalentsRepository.list_talents`（repository.py:61-71）；MCP `talent_list`（`server/src/reven/agent/tools_talents_talents.py:43-68`，注册于 `tools_talents.py:18`）→ `TalentsRepository.list_talent_plans`（repository.py:73-92）；两者都走 `_filtered`（:70、:83-90），仅 SELECT 列不同（MCP 版随行带派生计划）。**扩 q 只需改 `_filtered` 一处，REST/MCP 同时生效。**

**测试断言位置**：

- REST：`server/tests/api/test_talents.py:48-68`（q 按姓名 :63-64、按单位 :65-66、tag :67-68）；通配符转义 :131-138 `test_talent_query_escapes_like_wildcards`（`q="%"` 只命中字面 `%`）。
- MCP：`server/tests/agent/test_tools_talents.py:108-146`（query 按姓名 :129、按单位 :132、tag :141-142、空结果 :144）；MCP-over-HTTP :586（`talent_list` `{"query": "协议"}`）、:603。

## 3. 可扩展字段清单（模型定义位置）

### CRM（`server/src/reven/crm/models.py`）

| 字段 | 行号 | 列类型 | 现状 |
|---|---|---|---|
| `Customer.name` | :34 | `String(200)` | 已搜 |
| `Customer.source` | :36 | `String(100)` nullable | 已搜 |
| `Customer.notes` | :37 | `Text` nullable | 已搜 |
| `Contact.name` | :58 | `String(200)` | 已搜（EXISTS） |
| `Contact.role` | :59 | `String(100)` nullable | **未搜** |
| `Contact.phone` / `email` / `wechat` | :60-62 | `String(50/320/100)` nullable | 已搜（EXISTS） |
| `Contact.notes` | :64 | `Text` nullable | **未搜** |
| `FollowUp.summary` | :84 | `Text` 必填 | **未搜**（历史跟进正文） |
| `FollowUp.next_action` | :85 | `Text` nullable | **未搜** |
| `FollowUp.contact_name_snapshot` | :81 | `String(200)` nullable | **未搜**（快照，联系人有 name 已覆盖，冗余度高） |

Customer 无 tags/画像数组字段；CRM 画像扩展空间主要在 contacts 的 role/notes，以及（范围更大的）follow_ups 全文。

### talents（`server/src/reven/talents/models.py`）

| 字段 | 行号 | 列类型 | 现状 |
|---|---|---|---|
| `Talent.name` | :41 | `Text` | 已搜 |
| `Talent.organization` | :42 | `Text` nullable | 已搜 |
| `Talent.tags` | :43 | **JSONB** `list[str]`（`server_default '[]'::jsonb`） | 未入 q（仅 tag 参数精确筛，repository.py:129） |
| `Talent.phone` / `email` / `wechat` | :44-46 | `String(50/320/100)` nullable | **未搜** |
| `Talent.preferences` | :47 | **JSONB** `list[str]` | **未搜** |
| `Talent.capability` | :48 | `Text` nullable | **未搜** |
| `Talent.engagement_terms` | :49 | `Text` nullable | **未搜** |
| `Talent.availability` | :50 | `Text` nullable | **未搜** |
| `Talent.rate_amount` / `rate_unit` / `rating` | :51-53 | `Numeric(12,2)` / `String(16)` / `SmallInteger` | 数值/枚举，不适合 ILIKE |
| `Talent.notes` | :55 | `Text` nullable | **未搜** |
| `TalentExperience.company` | :83 | `Text` | **未搜** |
| `TalentExperience.title` | :84 | `Text` | **未搜** |
| `TalentExperience.description` | :85 | `Text` nullable | **未搜** |
| `TalentEducation.school` | :98 | `Text` | **未搜** |
| `TalentEducation.degree` / `major` | :99-100 | `Text` nullable | **未搜** |

JSONB 数组 check 约束（`jsonb_typeof = 'array'`）在 migration `server/migrations/versions/0026_talent_profile.py:45`；inputs 层元素约束 `Tag = str[1..50]`、每字段最多 20 元素（`server/src/reven/talents/inputs.py:14, 73, 77`）。

## 4. 搜索参数链路

### CRM REST

`web` 搜索框（`web/src/features/crm/customer-list.tsx:75-81`，`id="crm-customer-search"`，placeholder「客户名称、联系人或联系方式」:79）→ `CustomerFilters.query`（`web/src/features/crm/types.ts:30-34`；`crm-page.tsx:20` `EMPTY_FILTERS = { query, status, due }`）→ `useResourceList` 把 filters 非空项直出为 URL 查询参数（`web/src/lib/use-resource-list.ts:57-67`，键名即参数名）→ `GET /api/crm/customers?query=...` → `api/routes/crm.py:71-84`（FastAPI `Query` 校验 min/max length，**列表查询参数不经 inputs/schemas**；`api/schemas/crm.py` 只重导出 mutation 输入类 :8-13）→ `CrmRepository.list_customers` → `_customer_search`。

### talents REST

`web` 搜索框（`web/src/features/talents/talent-list.tsx:89-95`，`id="talents-search"`，placeholder「姓名或机构」:93）→ `TalentFilters.q`（`web/src/features/talents/types.ts:50-56`，:51 注释「后端约定为 q」；`talents-page.tsx:20`）→ 同一 `useResourceList` 序列化 → `GET /api/talents?q=...&tag=...` → `api/routes/talents.py:76-90` → `TalentsRepository.list_talents` → `_filtered`。

### MCP 工具参数定义

- CRM：`server/src/reven/agent/tools_crm_customers.py:36-39` `query: Annotated[str | None, Field(description="模糊检索词：匹配客户名称/来源/备注，以及联系人的姓名/电话/邮箱/微信")]`；共享参数别名在 `server/src/reven/agent/crm_tool_support.py`。
- talents：`server/src/reven/agent/tools_talents_talents.py:45` `query`（描述「匹配人才姓名/当前单位」）、:48 `tag`（描述「按单个能力/行业标签精确筛选」）；共享别名 `server/src/reven/agent/talents_tool_support.py:23-45`（`TalentIdParam`/`DueFilterParam` 等）。
- **扩字段后这两处 `Field(description=...)` 与 web 两处 placeholder 是文案同步点**（工具描述即模型可见的搜索覆盖面契约）。

### web 测试 / fixture

- MSW server：`web/src/test/server.ts`（`setupServer`）；setup `web/src/test/setup.ts`。
- CRM：`web/src/features/crm/crm-page.test.tsx:59-78`「把搜索、状态和跟进计划转换为查询参数」（输入「搜索」框 → 断言 `searchParams.get("query")`）。
- talents：`web/src/features/talents/talents-page.test.tsx:72-91`「把搜索、状态、到期和标签转换为查询参数」（:81 输入「搜索」→ :88-91 断言 `q/status/due/tag`）。
- 详情页测试 `customer-detail-page.test.tsx` / `talent-detail-page.test.tsx` 与列表搜索无关。

## 5. 子表搜索的技术方案约束

**EXISTS 是既定模式，且被 spec 固化**：

- CRM 联系人搜索已用相关 EXISTS（`crm/repository.py:90-100`）；契约原文 `crm-contract.md:89-91`：「Search covers customer name/source/notes and contact name/phone/email/WeChat through an `EXISTS` subquery so one customer is never duplicated by multiple matching contacts」。
- 重复计数的反面教材也写在契约里：`crm-contract.md:68-69`「禁止 join `FollowUp` 直数（一个客户多条历史会重复计数）」、:193-197 Wrong 示例；正确模式 `crm/repository.py:131-142` `count_due_follow_ups`（`func.count().filter(...)` over Customer，无 join）。
- 相关子查询写法先例：`_latest_action_subquery / _latest_due_subquery`（`crm/repository.py:23-42`、`talents/repository.py:27-54`）：`.where(child.parent_id == Parent.id).order_by(...).limit(1).correlate(Parent).scalar_subquery()`。

**结论：子表（contacts/experiences/educations）搜索用 `exists(select(child.id).where(child.parent_id == Parent.id, or_(...ilike...)))`，不要 JOIN+DISTINCT**——列表查询带 `order_by` 派生子查询（`crm/repository.py:65-70`）与 `tag` 过滤，JOIN 会同时污染行数与排序语义。

**分页 / count**：当前**列表端点无分页**（routes 无 limit/offset；talents 契约 :10 明确 no pagination），全量返回；因此「count 重复计数」风险主要存在于未来新增计数场景，EXISTS 已天然免疫。

**ILIKE 对中文**：Postgres ILIKE 对 UTF-8 中文子串可直接匹配（无分词需求，大小写折叠对中文无影响），现有测试全部用中文关键词通过（test_crm.py:83、test_talents.py:63 等）。

**JSONB 数组字段（tags/preferences）匹配方式**：

- 列类型是 **JSONB 不是 PG ARRAY**（`talents/models.py:43, 47`），`.contains([tag])`（`@>`）只能做精确元素包含，不能做模糊；
- 代码库中**没有** `jsonb_array_elements_text` 或 JSONB cast+ilike 的既有先例（grep 全 src 为空），两种写法任选：
  - 简易：`Talent.tags.cast(String).ilike(pattern)` / `preferences.cast(String).ilike(pattern)`——把 `["设计","插画"]` 整体当文本匹配；子串语义足够，但会连 JSON 引号/括号一起匹配（对 `%词%` 实际无害）；
  - 精确：元素级 `exists(select(func.jsonb_array_elements_text(Talent.tags).column_valued...).where(...ilike(pattern)))`——只匹配元素文本，无标点噪声，SQL 更复杂。

**转义不一致（扩搜时顺带处理的既有缺陷）**：CRM `_customer_search` 不转义 `%`/`_`/`\\`（`crm/repository.py:88-106`），talents 有 `_escape_like`（`talents/repository.py:23-24` 且 `ilike(..., escape="\\")` :124-125）。CRM 输入 `%` 会意外全匹配；扩字段时建议把 `_escape_like` 方案推广到 CRM（或抽到共享处）。

## 6. spec 契约行（精确位置）

**`.trellis/spec/reven-server/backend/crm-contract.md`**：

- :21 `| `GET` | `/customers` | `Customer[]` filtered by `query`, `status`, and `due` |`
- :59 `list_customers(*, status, due, query, today) -> list[CustomerPlan]`（派生读入口签名块内）
- **:89-91（核心覆盖面句）**：「Search covers customer name/source/notes and contact name/phone/email/WeChat through an `EXISTS` subquery so one customer is never duplicated by multiple matching contacts.」
- :160 Tests Required：「API: customer CRUD; all five statuses; search; all due filters on derived values; ...」

**`.trellis/spec/reven-server/backend/talents-contract.md`**：

- :20 `| `GET` | `/talents` | `Talent[]` filtered by `status`, `due`, `q`, and `tag` |`
- **:64-67（核心覆盖面句）**：「`q` matches name/organization with ilike (`\`, `%`, `_` escaped). `tag` is an exact single-tag match against the JSONB array; tags are free-form strings with no backend normalization — consistency is a frontend autocomplete concern only.」
- :145-152 Tests Required：「... `q` escaping; `tag` exact match; ...」（:147-148）

**web spec**：`.trellis/spec/web/frontend/` 下**无搜索契约**；`filter-facets-contract.md` 是下拉选项 facets 规则（:11-13），与关键词搜索无关。

## 7. 性能

**现有索引**（migration 与 models.py 双重确认）：

- `crm_customers`：`ix_crm_customers_status`（`0013_crm.py:44`；`crm/models.py:35` `index=True`）。0025 删计划列时其索引同删（`0025_crm_plan_derive.py:23-24`）。**name/source/notes 无索引**。
- `crm_contacts`：`ix_crm_contacts_customer_id`（`0013_crm.py:66`；`crm/models.py:54-57`）+ 部分唯一索引 `uq_crm_contacts_primary_per_customer`（`crm/models.py:44-51`）。
- `crm_follow_ups`：`customer_id`（`0013_crm.py:103`）、`occurred_on`（:104；`crm/models.py:83`）。
- `talents`：`ix_talents_status`（`0015_talents.py:51`；`talents/models.py:54`）。**name/organization/notes 无索引**。
- `talent_interactions`：`(talent_id, occurred_on)` + `next_due_on`（`0015_talents.py:73-78`；`talents/models.py:62-65`）。
- `talent_experiences`：`(talent_id, start_on)`（`0026_talent_profile.py:68`；`talents/models.py:79`）——**EXISTS 子查询的 `talent_id =` 条件可走该复合索引前导列**。
- `talent_educations`：`(talent_id, start_on)`（`0026_talent_profile.py:95`；`talents/models.py:94`）——同上。
- **全库无 pg_trgm / GIN 索引**（migrations grep 无 gin/trgm）；`%词%` ILIKE 恒为 seq scan，JSONB cast ILIKE 同样全扫。

**数据量级假设**：单业主产品——crm-contract.md:5-6「single-owner B2B CRM」、talents-contract.md:5-6「one-person-company talent pool」，列表无分页全量返回，量纲为数百至低千行；扩字段后的多 OR + EXISTS seq scan 在该量级可接受。若未来变慢，优化路径是新 migration 加 `pg_trgm` GIN（文本列）与 GIN（JSONB），本期非必需。

**其他约束**：CRM/talents 各表均启 RLS（`0013_crm.py:46,74` 等；talents-contract.md:36「0015 起均有 RLS」），新增 EXISTS 子查询自动继承子表 RLS 策略，无额外动作。

## 推荐扩展字段清单

### CRM 侧（`_customer_search` 扩展）

| 推荐 | 字段 | 理由 | 实现注意点 |
|---|---|---|---|
| ✅ | `Contact.role`（models.py:59） | 「找某公司的 CTO/对接人」是高频检索意图；零成本 | 加入现有 contacts EXISTS 的 `or_` 块（repository.py:93-98） |
| ✅ | `Contact.notes`（models.py:64） | 联系人级备注（Text），与 Customer.notes 已搜对齐 | 同上 |
| ⚠️ 可选 | `FollowUp.summary` / `next_action`（models.py:84-85） | 跟进正文全文检索（「谁说过要做官网」）价值高，但显著扩大命中面与扫描成本 | 需第三个 EXISTS（follow_ups.customer_id 有索引）；建议本期不做或单独评审；若做，契约 :89-91 句子同步改写 |
| ❌ | `FollowUp.contact_name_snapshot`（models.py:81） | 与 Contact.name 搜索冗余 | — |

### talents 侧（`_filtered` q 扩展，REST/MCP 一处生效）

| 推荐 | 字段 | 理由 | 实现注意点 |
|---|---|---|---|
| ✅ | `Talent.notes`（:55） | 备注文本，CRM notes 已搜的对称补全 | 主表 `or_` 直接加 |
| ✅ | `Talent.capability`（:48） | 能力描述是画像检索核心诉求（「会品牌视觉的人」） | 主表 `or_` |
| ✅ | `Talent.tags` / `Talent.preferences`（:43, :47） | 「按能力模糊找人」（tag 精确筛覆盖不了「插」匹配「插画」） | JSONB 非 ARRAY；推荐 `cast(String).ilike(pattern)`（简单）或 `jsonb_array_elements_text` 元素级 EXISTS（精确）；与既有 `tag` 精确参数（repository.py:129）互补保留 |
| ✅ | `Talent.phone` / `email` / `wechat`（:44-46） | 与 CRM 联系人渠道搜索对齐 | 主表 `or_` |
| ✅ | `TalentExperience.company` / `title` / `description`（:83-85） | 履历检索是「画像字段搜索」的题眼（「在阿里干过的人」） | 新 EXISTS 子查询，复制 CRM contacts 模式（repository.py:90-100）；`talent_id` 条件走 `(talent_id, start_on)` 索引前导列 |
| ✅ | `TalentEducation.school` / `degree` / `major`（:98-100） | 院校检索（「清华的」「学设计的」） | 同上，第二个 EXISTS |
| ⚠️ 可选 | `engagement_terms` / `availability`（:49-50） | 合作条件/可用时间文本，价值中 | 主表 `or_`，成本低，纳入与否取决于覆盖面控制 |
| ❌ | `rate_amount` / `rating` / `rate_unit`（:51-53） | 数值/枚举，ILIKE 无语义 | — |

### 跨域实现注意点

1. **统一转义**：把 talents `_escape_like`（repository.py:23-24）推广到 CRM `_customer_search`（当前不转义，`%` 输入会全匹配），两域 `ilike(pattern, escape="\\")` 对齐。
2. **子表一律 EXISTS**，不 JOIN+DISTINCT：契约已定调（crm-contract.md:89-91、:68-69 禁止 join 直数），且列表查询带相关标量排序子查询，JOIN 会破坏行数/排序。
3. **文案同步点**：MCP 工具描述 `tools_crm_customers.py:36-39`、`tools_talents_talents.py:45`（:50 docstring 同步）；web placeholder `customer-list.tsx:79`、`talent-list.tsx:93`；spec 句 `crm-contract.md:89-91` + `talents-contract.md:64-67`（以及 :21/:59、:20 表格行如措辞变化）。
4. **参数名不一致保持现状**：CRM 用 `query`（routes/crm.py:76），talents 用 `q`（routes/talents.py:81）；P4 只扩覆盖面，统一参数名属另一个话题。
5. **测试落点**：REST 行为断言加在 `server/tests/api/test_crm.py:57` / `test_talents.py:48` 家族；MCP 断言加在 `server/tests/agent/test_tools_crm.py:68` / `test_tools_talents.py:108`；转义回归参照 `test_talents.py:131-138` 为 CRM 补一条；web 仅需更新 placeholder 相关断言（crm-page.test.tsx / talents-page.test.tsx 现有参数序列化断言不受影响）。
6. **RLS / 索引**：EXISTS 子查询自动继承子表 RLS；子表外键均有索引（contacts.customer_id 独立索引；experiences/educations 复合索引前导列），无需新 migration；pg_trgm GIN 留作后续性能兜底。

## Caveats / Not Found

- CRM 侧 source/notes 字段搜索**无独立测试断言**（现有断言只覆盖 name 与联系人 name）；扩展时建议补齐逐字段断言。
- JSONB 模糊匹配在代码库无先例（`jsonb_array_elements_text` / cast+ilike 均未出现），选型需实现期定夺并在契约中写明。
- 「数据量级」无硬数据支撑，仅依据契约的 single-owner 定位与无分页设计推断为数百至低千行。
- `.trellis/spec/web/` 下无搜索相关契约，web 侧无需契约更新（仅组件文案）。
