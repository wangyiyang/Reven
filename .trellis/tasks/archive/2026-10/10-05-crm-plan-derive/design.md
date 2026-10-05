# 技术设计：CRM 历史与计划派生化

## 核心原则

**计划的唯一权威来源是最新跟进记录。** 客户表不再持有计划状态；一切「当前计划」读路径从跟进历史派生。写路径因此从双写降为单写，不一致问题在结构上消失。

## 1. 数据模型与 migration

- `crm_customers`：drop 列 `next_action`、`next_follow_up_on`，以及「日期必须有行动」的 check 约束（0013_crm 中创建，具体名以 research/touchpoints.md 为准）。`next_follow_up_on` 上的索引随列删除。
- `crm_follow_ups`：`next_follow_up_on` rename 为 `next_due_on`；该表的配对 check 约束保留（列名同步）。
- 无存量数据，downgrade 仍按 alembic 约定补齐（rename 回退 + 重建列与约束）。
- 命名沿用 `next_due_on`，与 `talent_interactions.next_due_on` 对齐。

## 2. 派生读模型

统一定义「客户的当前计划」：

```
latest_follow_up(customer) = FollowUp where customer_id = customer
  order by occurred_on desc, created_at desc, id desc
  limit 1
current plan = (latest.next_action, latest.next_due_on)  -- 无跟进时为 (None, None)
```

实现位置：`CrmRepository` 内部的相关标量子查询（correlated scalar subquery），供列表排序、`due` 过滤、详情、待跟进、提醒共用。**禁止**在调用方各自拼子查询。

注意与 talents 现状的区别：talents 用 `min(next_due_on)`（会永久冒泡旧计划），本设计用「最新一条」语义（记新跟进即刷新状态）。talents 域改为同一语义是后续阶段的 Non-Goal（见 prd.md）。

- 列表排序：派生 `next_due_on` 升序、NULL 最后，再 `updated_at` 倒序（保持现状的视觉稳定性：有日期的在前，越近越前）。
- `due` 过滤：overdue = 派生日期 < today；today = 等于；upcoming = 大于；none = 派生日期 IS NULL。today 取自 `reven.scheduling.SHANGHAI`，规则不变。

## 3. 写路径变化

- `CustomerCreate` / `CustomerUpdate`：删除 `next_action`、`next_follow_up_on` 及配套 validator（`require_action_for_date` 仍被 FollowUp 复用，函数保留）。`update_customer` 的 MCP adapter 删除 `clear_next_follow_up_on` 参数。
- `FollowUpCreate`：删除 `set_as_current` 字段与 validator；`CrmService.create_follow_up` 删除客户回写，返回值简化为只提交跟进记录本身（保留返回 customer 供 MCP 展示名称）。
- `FollowUpUpdate`：字段改名 `next_due_on`；`clear_next_follow_up_on` → `clear_next_due_on`；行动/日期合并校验（`_validate_plan`）逻辑不变。
- `_plan_text`、错误类型 `InvalidActionPairError` 保留复用。

## 4. API 契约变化（REST + MCP 一致）

- 请求：`POST/PUT /customers` 不再接受计划字段（extra=forbid → 422）。
- 响应：`CustomerResponse` 移除 `next_follow_up_on`；`next_action` 保留但语义变为只读派生；新增 `next_due_on` 只读派生（`date | None`）。即响应字段 = `next_action / next_due_on`，全部来自最新跟进。web 与 MCP 展示文案不需要发明新字段名。
- 序列化规则不变：null 而非空串、ISO 日期、UUID 字符串。
- MCP 工具：
  - `crm_customer_create` / `crm_customer_update` 删除计划参数；`create` 的返回话术与工具描述补「创建后可用 crm_follow_up_create 记录第一次跟进并定下计划」引导。
  - `crm_follow_up_create` 删除 `set_as_current`；描述改为「next_due_on 即该客户的当前计划（自动生效，无需额外同步）」。
  - `crm_follow_up_update` 参数改名。
  - `crm_list_due_follow_ups`、列表/详情的 `_customer_line` 等输出改用派生值。

## 5. Web 变化

- `customer-form.tsx` / `customer-form-model.ts`：删除「下一步行动 / 下次跟进日期」字段与提交逻辑；新建/编辑表单只剩名称/状态/来源/备注。
- `types.ts`：`CustomerInput` 删计划字段；`Customer` 响应类型的 `next_action / next_due_on` 标注为派生只读；`FollowUp*` 字段改名。
- 列表/详情（`customer-list.tsx`、`customer-detail-page.tsx`）：展示派生计划；无计划且零跟进时显示「记第一条跟进」引导（详情页空态按钮，跳转/唤起跟进表单）。
- `follow-ups-section.tsx`：字段改名；创建表单不再出现「同步为当前计划」勾选。
- dashboard `crm-due-card.tsx` + `dashboard-api.ts`：适配派生语义（逾期标记、天数计算改用响应中的派生 `next_due_on`）。

## 6. 服务端适配点

- `follow_up_reminder.py`：到期集合 = 派生日期 <= today 的客户（每客户最新跟进），提醒文案中的行动/日期取自派生值。
- `crm_tool_support._collect_updates` 的 `date_key` 调用点同步改名。
- 测试：`tests/agent/test_tools_crm*.py`、crm api 测试、`tests/migrations/` 按新契约重写断言（删 set_as_current 用例，新增「删除最新跟进后计划回退」用例）。

## 7. 兼容与回滚

- 破坏性变更，无存量数据；前端与后端同 PR 发布，无新旧协议并存期。
- 回滚 = revert PR + alembic downgrade（rename 回退 + 重建列；计划数据本就可由跟进记录重建，无数据损失）。

## 8. 风险与对策

- 派生子查询在列表页的 N 倍开销：客户量级为个人 CRM（百级），标量子查询可接受；不预优化。
- 「最新跟进没定日期 → 旧计划静默失效」是已知取舍（issue #201 Q13）：靠列表排序让无计划客户不沉底（updated_at 倒序）缓解。
- spec 漂移：`crm-contract.md` 必须与本 PR 同批更新（Phase 3.3）。
