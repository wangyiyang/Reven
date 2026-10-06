# Design: 搜索扩展到画像字段（#201 P4）

调研证据见 `research/touchpoints.md`，以下行号均出自该文档对应的源码位置。决策一旦锁定不再重开。

## D1 子表搜索一律 EXISTS，不 JOIN+DISTINCT

契约已定调：`crm-contract.md:89-91`「EXISTS subquery so one customer is never duplicated」、`:68-69` 禁止 join 直数。talents 新加的 experiences/educations 两个 EXISTS 复制 CRM contacts EXISTS 的既有写法（`crm/repository.py:90-100`）：

```python
exists(
    select(TalentExperience.id).where(
        TalentExperience.talent_id == Talent.id,
        or_(TalentExperience.company.ilike(pattern, escape="\\"), ...),
    )
)
```

子表外键条件走既有索引前导列（experiences/educations 的 `(talent_id, start_on)`），无需新 migration。

## D2 JSONB 模糊匹配用 cast(String).ilike

tags/preferences 是 JSONB（`talents/models.py:43,47`），代码库无 `jsonb_array_elements_text` 先例。选简易方案：

```python
Talent.tags.cast(String).ilike(pattern, escape="\\")
```

`["设计","插画"]` 整体当文本匹配；JSON 引号/括号噪声对 `%词%` 包含匹配无害。既有 `tag` 精确筛参数（`repository.py:129` `Talent.tags.contains([tag])`）保留不动，与 q 模糊互补。

## D3 escape_like 提升到 reven/db.py 两域共用

- 把 `talents/repository.py:23-24` 的 `_escape_like` 移为 `reven/db.py` 的公开函数 `escape_like`（转义 `\`、`%`、`_`）
- `talents/repository.py` 改 import；`crm/repository.py` `_customer_search` 应用同一转义并补 `escape="\\"`（修复 CRM 不转义的既有缺陷）
- 不新建工具模块、不放 domain.py（db.py 是数据库层工具的家）

## D4 字段清单（最终锁定）

**CRM `_customer_search`**：客户 name/source/notes（已有）+ 联系人 EXISTS name/phone/email/wechat（已有）**+ role + notes（新增）**。

**talents `_filtered` q**：
- 主表 `or_`：name/organization（已有）**+ notes/capability/phone/email/wechat**
- JSONB cast：**tags/preferences**
- EXISTS ①：experiences.company/title/description
- EXISTS ②：educations.school/degree/major

排除项（写入契约避免回潮）：FollowUp 全文、engagement_terms/availability、rate_amount/rating/rate_unit（数值枚举无 ILIKE 语义）、contact_name_snapshot（冗余）。

## D5 文案同步点（R4/R5 验收依据）

| 位置 | 现状 | 改动 |
|---|---|---|
| `agent/tools_crm_customers.py:36-39` query 描述 | 「匹配客户名称/来源/备注，以及联系人的姓名/电话/邮箱/微信」 | 补「职务/备注」 |
| `agent/tools_talents_talents.py:45` query 描述（及 :50 docstring） | 「匹配人才姓名/当前单位」 | 写明新覆盖面（能力/标签/喜好/联系方式/履历/院校） |
| `web/src/features/crm/customer-list.tsx:79` placeholder | 「客户名称、联系人或联系方式」 | 补「职务」 |
| `web/src/features/talents/talent-list.tsx:93` placeholder | 「姓名或机构」 | 改为覆盖画像的简述（如「姓名、机构、能力、履历或院校」） |
| `crm-contract.md:89-91` 搜索覆盖面句 | 现字段清单 | 更新 |
| `talents-contract.md:64-67` q 覆盖面句 | 现字段清单 | 更新（含 JSONB cast 写法与排除项） |

spec 两处由主代理在实施验收后更新（同 P3 模式），实施代理不动 `.trellis/spec/`。

## D6 测试落点

- REST：`server/tests/api/test_crm.py:57` 家族（补 source/notes/role/联系人 notes 逐字段断言 + 多联系人命中不重复断言）、`server/tests/api/test_talents.py:48` 家族（逐画像字段断言）
- CRM 转义回归：参照 `test_talents.py:131-138` 为 CRM 补一条（`query="%"` 只命中字面 `%`）
- MCP：`server/tests/agent/test_tools_crm.py:68` 家族、`server/tests/agent/test_tools_talents.py:108-146` 家族各补一条画像字段命中
- web：placeholder 改动若被现有断言引用则同步（`crm-page.test.tsx:59-78`、`talents-page.test.tsx:72-91` 的参数序列化断言预期不受影响）

## D7 性能与兼容

- 无分页全量返回、单业主数百至低千行量级，多 OR + EXISTS seq scan 可接受；pg_trgm GIN 留作后续兜底
- RLS：EXISTS 子查询自动继承子表 RLS 策略，无额外动作
- REST/MCP 行为仅「命中面扩大」，无破坏性变更；既有测试（含转义、tag 精确筛）须零改动通过
