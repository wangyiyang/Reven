# 执行计划：CRM 历史与计划派生化

按序执行；每步完成跑对应验证。设计契约见 design.md，触点明细见 research/touchpoints.md。

## 环境

- 测试库（本机 docker 已运行）：`TEST_DATABASE_URL=postgresql+asyncpg://reven_test:reven_test@127.0.0.1:55432/reven_test`
- server 命令在仓库根执行：`uv run pytest server/tests`、`uv run mypy server/src`、`uv run ruff check server`、`uv run ruff format server`
- web：`pnpm --filter @reven/web exec vitest run`、`pnpm --filter @reven/web lint`、`pnpm --filter @reven/web exec tsc -b`

## Step 1 — Migration 0025 + ORM

- [ ] 新增 `server/migrations/versions/0025_crm_plan_derive.py`（`down_revision = "0024_rss_resilience"`）：drop 约束 `ck_crm_customers_follow_up_action` → drop 列 `crm_customers.next_action / next_follow_up_on`（索引 `ix_crm_customers_next_follow_up_on` 随列）；rename `crm_follow_ups.next_follow_up_on → next_due_on`（约束 `ck_crm_follow_ups_follow_up_action` 保留，PG 自动跟随）。downgrade 完整镜像（不得用 raise RuntimeError 模式）。
- [ ] `crm/models.py`：删 Customer 两列，FollowUp 列改名。
- [ ] `tests/migrations/test_merge_heads_migration.py:18` `FINAL_REVISION` 改 `"0025_crm_plan_derive"`；新增 0025 迁移回归测试（information_schema 断言列/约束 + 违配对阵列插入被拒，仿 test_rss_item_review_pushed_at_migration.py）。
- [ ] 验证：`TEST_DATABASE_URL=... uv run pytest server/tests/migrations -x`

## Step 2 — 派生读模型进 CrmRepository

- [ ] 统一「最新跟进」相关标量子查询（occurred_on desc, created_at desc, id desc limit 1，模板 talents/repository.py:81-85），同时派生 `next_action` 与 `next_due_on`。
- [ ] `list_customers`：排序改派生 `next_due_on` 升序 NULL 最后 + updated_at desc；`_filter_due` 改派生比较；返回结构携带派生计划（tuple/DTO，勿裸返 ORM 让调用方读已删属性）。
- [ ] `list_due_follow_ups`：派生日期 <= today，返回携带派生计划的结构；三个调用方同步改：`dashboard/service.py`（含 175-178 `_count_follow_ups`，不得 join FollowUp 直数）、`follow_up_reminder.py`（逾期计数与单行渲染改派生值）、MCP 侧。
- [ ] 验证：`uv run mypy server/src`

## Step 3 — server 写路径

- [ ] `inputs.py`：Customer* 删计划字段与配对 validator；FollowUp* 删 `set_as_current`、改名 `next_due_on`（`require_action_for_date` 保留）；`clear_next_follow_up_on` → `clear_next_due_on`。
- [ ] `service.py`：`create_follow_up` 删客户回写（service.py:72-74）；`update_customer` 简化；`_validate_plan` 逻辑保留字段名改。
- [ ] 验证：`uv run pytest server/tests/crm -x`（此步可先红，Step 6 修齐）

## Step 4 — API + MCP 适配

- [ ] `api/schemas/crm.py`：CustomerResponse 删 `next_follow_up_on`，`next_action` 改只读派生 + 新增 `next_due_on`；FollowUpResponse 改名。
- [ ] `api/routes/crm.py`：list/get/create/update 响应组装注入派生计划（from_attributes 不再够用）。
- [ ] `agent/tools_crm_customers.py`：create/update 删计划参数与 clear 开关；描述补「创建后可用 crm_follow_up_create 记录第一次跟进并定下计划」；`_customer_line/_customer_detail/list_due_follow_ups` 用派生值。
- [ ] `agent/tools_crm_follow_ups.py`：删 `set_as_current` 参数与「已同步」文案；参数改名；描述改「next_due_on 即当前计划，自动生效」。
- [ ] `agent/crm_tool_support.py`：`_FIELD_LABELS` 删 set_as_current、改字段标签；`_collect_updates` date_key 默认值改 `next_due_on`；`_plan_text` 签名改名。
- [ ] 验证：`uv run mypy server/src && uv run ruff check server`

## Step 5 — web 适配

- [ ] `types.ts`：CustomerInput 删计划字段；Customer 响应 `next_action / next_due_on` 派生只读；FollowUp* 改名、删 `set_as_current`。
- [ ] `crm-api.ts`：删 `historicalFollowUpInput` 剥离逻辑。
- [ ] `customer-form.tsx` + `customer-form-model.ts`：删 `CustomerActionFields` 整块与配对校验。
- [ ] `customer-list.tsx` / `customer-detail-page.tsx`：展示派生计划；详情页零跟进空态加「记第一条跟进」引导按钮。
- [ ] `follow-ups-section.tsx`：删同步 checkbox 与草稿字段、改名、校验只留「有日期必须有行动」。
- [ ] `dashboard-api.ts` / `crm-due-card.tsx`：字段改名。
- [ ] 验证：`pnpm --filter @reven/web exec tsc -b && pnpm --filter @reven/web lint`

## Step 6 — 测试重写（先红后绿）

- [ ] server：`tests/api/test_crm.py`（删 set_as_current 组，新增「记跟进后列表/详情立即呈现计划」「删除最新跟进后计划回退次新/null」）、`tests/crm/test_service.py`、`tests/crm/test_follow_up_reminder.py`（fixture 改两步：建客户→建跟进）、`tests/notify/test_scheduler_delivery.py:45` 同上、`tests/agent/test_tools_crm.py`（删参断言、改文案断言）、`tests/api/test_dashboard.py`。
- [ ] web：`crm-page.test.tsx` / `customer-detail-page.test.tsx` / `dashboard-page.test.tsx` fixture 与 body 断言同步（create follow-up body 也不含 set_as_current）。
- [ ] 验证（全绿门槛）：
  - `TEST_DATABASE_URL=... uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80`
  - `TEST_DATABASE_URL=... uv run pytest server/tests/migrations`
  - `uv run ruff check server && uv run ruff format --check server && uv run mypy server/src`
  - `pnpm --filter @reven/web exec vitest run && pnpm --filter @reven/web lint && pnpm --filter @reven/web exec tsc -b`

## Step 7 — spec 同步（交还主代理 Phase 3.3）

- [ ] `.trellis/spec/reven-server/backend/crm-contract.md` 按新契约更新（由主代理用 trellis-update-spec 完成，implement 代理不改 spec）。

## 回滚点

- Step 1 失败：删 0025 文件即可，无其他改动。
- Step 2-5 失败：git checkout 回滚对应层，migration 已可 downgrade。
- 全量回滚：revert 全部改动 + `uv run alembic -c server/migrations/alembic.ini downgrade 0024_rss_resilience`。

## Review gates

- Step 1 后：确认 migration upgrade/downgrade 双通再做 Step 2。
- Step 6 全绿前不得交付；覆盖门禁 80% 不得豁免。
