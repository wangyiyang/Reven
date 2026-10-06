# PRD: 搜索扩展到画像字段（#201 P4）

## 目的

CRM 客户搜索与 talents `q` 搜索扩展到画像字段：能通过联系人职务、人才能力/标签/喜好/联系方式/履历/院校等画像信息检索到记录。这是 issue #201 的最后一期。

## 背景

- #201 P1-P3 已完成（PR #207、#214）：talents 有 experiences/educations 子表与 tags/preferences/capability 等画像字段；CRM 有 contacts 子表。
- 但搜索覆盖面仍很窄：talents `q` 只匹配 name/organization；CRM `query` 匹配 name/source/notes + 联系人 name/phone/email/wechat，且 CRM 侧不转义 LIKE 通配符（既有缺陷）。
- 调研产物：`.trellis/tasks/10-06-search-profile-fields/research/touchpoints.md`（全部触点与字段行号证据）。

## 范围

### CRM（`crm/repository.py` `_customer_search`）

1. 联系人 EXISTS 的 `or_` 块增 `Contact.role`、`Contact.notes` 两个字段
2. 修复通配符转义缺陷：与 talents 对齐 `ilike(pattern, escape="\\")`

### talents（`talents/repository.py` `_filtered`，REST/MCP 共用一处）

3. 主表 `or_` 增：`notes`、`capability`、`phone`、`email`、`wechat`
4. JSONB 模糊匹配：`tags`、`preferences` 用 `cast(String).ilike`
5. 新建两个 EXISTS 子查询：`experiences.company/title/description`、`educations.school/degree/major`

### 文案同步

6. MCP 工具描述 ×2（`tools_crm_customers.py`、`tools_talents_talents.py`）、web 搜索框 placeholder ×2、spec 契约句 ×2

## 验收标准

- R1：CRM 搜索命中联系人 role/notes；一个客户多个联系人命中时不重复返回（EXISTS 语义保持）
- R2：CRM 搜索词含 `%`/`_`/`\` 按字面匹配，行为与 talents 一致
- R3：talents `q` 命中 notes/capability/phone/email/wechat/tags/preferences（模糊）/experiences 三字段/educations 三字段；既有 `tag` 精确筛参数行为不变
- R4：REST 与 MCP 两端同步生效；MCP 工具描述与 web placeholder 写明新覆盖面
- R5：spec 契约句同步（crm-contract.md 搜索覆盖面句、talents-contract.md `q` 覆盖面句）
- R6：门禁全绿——server pytest（覆盖率 ≥80%）+ migrations 测试 + ruff + mypy；web vitest + lint + tsc

## 非目标

- FollowUp.summary/next_action 全文检索（显著扩大命中面与扫描成本，需单独评审）
- engagement_terms/availability 纳入搜索（控制命中面）
- query/q 参数名统一（另一个话题）
- pg_trgm/GIN 索引（数据量级数百至低千行，seq scan 可接受，留作后续性能兜底）
- web UI 结构改动（仅 placeholder 文案）
