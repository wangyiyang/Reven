# 执行计划：Talent 画像扩展（#201 P2）

按序执行；每步完成跑对应验证。设计契约见 design.md，触点与范式细节见 research/touchpoints.md（实施前必读，尤其 §4 JSONB 路径、§5 范式对比、§6 牵连点清单、§9 风险点）。

## 已锁定的补充决策（review 确认）

- 子表（experience/education）写操作**不** bump `talent.updated_at`（履历修订 ≠ 接洽活跃，与 CRM 不 bump 一致）。
- `preferences` 输入**不提供** datalist 建议源（避免把全库他人喜好当候选，语义混用）。
- 月精度录入用 `<input type="date">`（`type="month"` 测试兼容性差）；序列化在 `talents-api.ts` 强制 `-01`；展示 `YYYY-MM`，`end_on=null` 展示「至今」。

## 环境

- `export TEST_DATABASE_URL=postgresql+asyncpg://reven_test:reven_test@127.0.0.1:55432/reven_test`
- server：`uv run pytest server/tests`、`uv run mypy server/src`、`uv run ruff check server`、`uv run ruff format server`
- web：`pnpm --filter @reven/web exec vitest run`、`pnpm --filter @reven/web lint`、`pnpm --filter @reven/web exec tsc -b`

## Step 1 — Migration 0026

- [ ] 新增 `server/migrations/versions/0026_talent_profile.py`（`down_revision = "0025_crm_plan_derive"`）：talents 加 4 列（phone/email/wechat 可空 String；preferences JSONB NOT NULL server_default `'[]'::jsonb` + `ck_talents_preferences_array` check）；建 `talent_experiences` / `talent_educations`（FK CASCADE、`ck_*_date_range`（`end_on IS NULL OR end_on >= start_on`）、`ix_*_(talent_id, start_on)`、`ENABLE ROW LEVEL SECURITY`）；downgrade 反序完整镜像。
- [ ] 牵连点（漏一个就红）：`server/migrations/env.py:19` 追加新模型 import；`server/tests/conftest.py:36` 与 `server/tests/api/conftest.py:82` TRUNCATE 列表加两表；`tests/migrations/test_merge_heads_migration.py:18` FINAL_REVISION → `"0026_talent_profile"`。
- [ ] `talents/models.py`：Talent 加 4 列（preferences 照抄 tags 行）；新增 `TalentExperience` / `TalentEducation`（含 created_at/updated_at，无 relationship，靠 repository）。
- [ ] 新增 `server/tests/migrations/test_talent_profile_migration.py`（照 0025 模板：information_schema 断言列/约束/RLS、违 date_range 与 preferences 非数组插入被拒、upgrade→downgrade→upgrade）。
- [ ] 验证：`uv run pytest server/tests/migrations -x`

## Step 2 — schemas 校验层

- [ ] `api/schemas/talents.py`：加 `OptionalPhone/OptionalEmail/OptionalWechat` 别名与 email 正则（规则同 CRM）；Talent create/update/response 加联系方式 + `preferences`（`list[Tag]` 形态，create 默认空数组）；**`TalentUpdate.keep_required_fields` 的 `_reject_explicit_null` 列表必须加 `"preferences"`**。
- [ ] 新增 `TalentExperienceCreate/Update/Response`、`TalentEducationCreate/Update/Response`（extra=forbid、必填与 date_range 校验、Update 支持部分字段 + 显式清空 end_on）。
- [ ] 验证：`uv run mypy server/src`

## Step 3 — repository + service + routes

- [ ] `talents/repository.py`：子表 scoped 查询（`get_experience(talent_id, experience_id)` 双条件，范式 crm/repository.py:161-164）；`list_*` 排序「`end_on` NULL 最前 → `start_on` desc → `created_at` desc」。
- [ ] `talents/service.py`：子表写入口（create/update/delete），不 bump `talent.updated_at`。
- [ ] `api/routes/talents.py`：嵌套端点 8 个（`GET/POST /{talent_id}/experiences|educations`、`PUT/DELETE .../{id}`），沿用 routes `_error` 模式；新错误码 `TALENT_EXPERIENCE_NOT_FOUND` / `TALENT_EDUCATION_NOT_FOUND`；越父 404。
- [ ] `TalentResponse` 扩字段（from_attributes 直返即可）。
- [ ] 验证：`uv run ruff check server && uv run mypy server/src`

## Step 4 — R7 到期语义对齐

- [ ] `talents/repository.py`：`_earliest_due_subquery` → `_latest_due_subquery`（照抄 `crm/repository.py:34-41`：occurred_on desc, created_at desc, id desc limit 1 取 `next_due_on`）；`_filter_due` 四档比较不变。
- [ ] 重写 `tests/api/test_talents.py::test_talent_due_filters_use_earliest_next_due` → 「最新无日期 → 旧日期不冒泡；最新有日期 → 按最新分档」。
- [ ] 验证：`uv run pytest server/tests/api/test_talents.py -x`

## Step 5 — server API 测试

- [ ] 照 `test_interactions_nested_scoped_and_cascade` 模板参数化覆盖两子表：排序（至今最前）、越父 404、date_range 422、必填 422、PATCH null 拒绝（preferences）、级联删除；联系方式 email/长度校验并入既有 422 矩阵用例。
- [ ] 验证：`uv run pytest server/tests/api/test_talents.py server/tests/crm -x`（CRM 回归）

## Step 6 — web

- [ ] `types.ts` / `talents-api.ts`：Talent 类型与输入加新字段；新增 Experience/Education 类型与嵌套 CRUD 函数；日期序列化在此层强制 `-01`。
- [ ] `talent-form-model.ts`：`TalentFormValues` 加字段、双向序列化、校验；复用 `appendTag/removeTag` 于 preferences。
- [ ] `talent-form.tsx`：联系方式 3 字段（进 Identity 或 Profile 区）；喜好字段照抄 `TalentTagsField` 变体（无 datalist）。
- [ ] 详情页：画像卡（联系方式 + 喜好，可并入 `TalentSummary` 或独立卡，参照 contacts-section 卡片网格）；新增 `experiences-section.tsx` / `educations-section.tsx`（照 interactions-section 模板：常驻内联表单 + Card 列表 + ConfirmDialog；date 输入 + `YYYY-MM` 展示）。
- [ ] 测试：`talent-detail-page.test.tsx` 扩 msw 用例（画像编辑 PATCH body、子表增删改 body 与列表渲染、`-01` 序列化断言）；`talents-page.test.tsx` 同步 fixture。
- [ ] 验证：`pnpm --filter @reven/web exec tsc -b && pnpm --filter @reven/web lint && pnpm --filter @reven/web exec vitest run`

## Step 7 — 全量门禁（先红后绿，全绿才交付）

- [ ] `uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80`
- [ ] `uv run pytest server/tests/migrations`
- [ ] `uv run ruff check server && uv run ruff format --check server && uv run mypy server/src`
- [ ] `pnpm --filter @reven/web exec vitest run && pnpm --filter @reven/web lint && pnpm --filter @reven/web exec tsc -b`

## Step 8 — spec 同步（交还主代理 Phase 3.3）

- [ ] `.trellis/spec/reven-server/backend/talents-contract.md` 更新（主代理用 trellis-update-spec；要点见 touchpoints.md §7：§2 加端点行与新表、§3 due 改最新记录语义并写明两种子表路由形状适用范围、§4 加新错误行与 preferences null 拒绝、§6 补测试清单）。implement 代理不改 spec。

## 回滚点

- Step 1 失败：删 0026 文件即可。
- 全量回滚：revert + `alembic downgrade 0025_crm_plan_derive`。

## Review gates

- Step 1 迁移双通后再做 Step 2。
- Step 7 全绿前不得交付；覆盖率门禁 80% 不得豁免。
- 越界检查：CRM 域文件（server/src/reven/crm/、web/src/features/crm/）与 talents interactions 路由形状不得改动。
