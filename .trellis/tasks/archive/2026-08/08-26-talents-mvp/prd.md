# 人才库（Talents）模块：对齐 CRM 风格的后端 + Web 前端

## Goal

为一人公司提供"人才库"功能：管理潜在合作者/外包人选档案与跟进记录，替代 Notion 的人脉管理职能。交付 server API + 数据库迁移 + Web 列表页/详情页，全面对齐已合并的 CRM MVP（#84）的技术形态。

## Background

- 本地曾有一套未提交的 talents 实现（备份在 `~/Reven-local-backup-20260826/`），与 CRM #84 冲突后未入库；本任务吸收其产品设计，按新 CRM 代码风格重新实现。
- 设计经 grilling 会话逐分支确认（2026-08-26），结论见 Key Decisions。
- CRM #84 模式（代码证据）：中文 StrEnum 枚举存文本列 + 迁移 CheckConstraint 双保险；Repository/Service 分层；统一 `_error(status, code, message)` 返回 `{"code", "message"}`；子资源嵌套路由；无分页；迁移开 RLS；`workbench` 测试 fixture，TRUNCATE 清单维护在 `server/tests/conftest.py:50` 与 `server/tests/api/conftest.py:90`。

## Requirements

### R1 人才档案（`talents` 表）

- 字段：`name`（必填）、`organization`、`tags`（JSONB 数组，自由输入）、`capability`、`engagement_terms`、`availability`、`rate_amount`（Numeric，可空）、`rate_unit`（可空，枚举：按小时/按天/按项目）、`rating`（整数 1–5，可空，人才总体评分）、`status`、`notes`、`created_at`、`updated_at`
- 无 `domain` 字段（粗分类由 tags 取代）、无任何 Notion 字段
- 软删除不做；删除人才级联删除其跟进记录

### R2 状态机与枚举

- `status` 四值：候选 / 接洽中 / 已合作 / 搁置；无自动流转，仅 PATCH 直接修改；"不合适"并入搁置 + notes；已合作可 PATCH 回接洽中
- 跟进形式 `channel` 四值：面谈 / 电话语音 / 微信 / 邮件
- 枚举存中文文本值，应用层（pydantic）校验 + 迁移 CheckConstraint 钉死，对齐 CRM

### R3 跟进记录（`talent_interactions` 表）

- 字段：`talent_id`（FK CASCADE）、`occurred_on`（Date，必填）、`channel`（必填）、`summary`、`next_action`、`next_due_on`（Date，可空）、`created_at`
- 追加跟进仅刷新人才 `updated_at`（列表按最近活跃排序），不触发状态流转

### R4 后端 API（`/api/talents`）

- 人才 CRUD：`GET /api/talents`（过滤：`status`、`due`、`q`、`tag`）、`POST`、`GET/PATCH/DELETE /api/talents/{id}`
- 跟进嵌套路由：`GET/POST /api/talents/{id}/interactions`、`PATCH/DELETE /api/talents/interactions/{interaction_id}`（嵌套查询双重匹配防跨属，对齐 CRM）
- `due` 过滤值：overdue/today/upcoming/none，基于该人才所有跟进的最早 `next_due_on`；"今天"按上海时区
- `q` 搜索 name/organization（ilike 转义）；`tag` 为单标签精确匹配
- 统一错误格式 `{"code", "message"}`；404 用 `TALENT_NOT_FOUND` / `TALENT_INTERACTION_NOT_FOUND`，校验失败 422
- 写路径走 Service，读路径路由可直用 Repository；Service 负责事务提交

### R5 迁移

- `server/migrations/versions/0015_talents.py`，`down_revision="0014_merge_crm_and_integration"`（当前唯一 head）
- 纯 create_table + CheckConstraint + `ENABLE ROW LEVEL SECURITY`；`env.py` 注册新 models
- 两处 conftest 的 TRUNCATE 清单按子表→父表顺序加入 `talent_interactions, talents`

### R6 Web 前端（`web/src/features/talents/`）

- 文件同构 CRM：types.ts、talents-api.ts、talents-page.tsx（列表）、talent-detail-page.tsx（详情：摘要 + 跟进记录区）、talent-form.tsx / talent-form-model.ts、use-talent-mutations.ts、talent-list.tsx、interactions-section.tsx
- 标签输入：自由输入 + 从已有人才标签中去重补全（前端从列表数据提取，不加后端接口）
- 列表页：status/due/tag 过滤 + q 搜索 + 删除 ConfirmDialog + 逾期/今天徽标；详情页：人才摘要 + 跟进记录 CRUD
- 路由 `/talents`、`/talents/:talentId` 注册进 `web/src/app.tsx`；导航项"人才库"加入 `web/src/components/app-shell.tsx` 并同步 app-shell 测试

### R7 测试

- `server/tests/api/test_talents.py`：CRUD + 过滤（status/due/q/tag）、枚举参数化、嵌套归属、级联删除、PATCH 显式 null 拒绝，风格对齐 `test_crm.py`
- Web：`talents-page.test.tsx`、`talent-detail-page.test.tsx`、app-shell 导航 label 更新

## Acceptance Criteria

- [ ] AC1: 通过 API 可创建/读取/更新/删除人才，必填校验与枚举校验返回 422，不存在返回带稳定 code 的 404
- [ ] AC2: 人才列表支持 status/due/q/tag 过滤；due=overdue 返回最早 next_due_on 早于今天（上海时区）的人才
- [ ] AC3: 跟进记录嵌套 CRUD 可用；删除人才后其跟进记录级联删除；跨人才访问他人跟进返回 404
- [ ] AC4: tags/rate_amount/rate_unit/rating 结构化字段端到端可用（API 读写 + 前端录入展示）；rating 越界（非 1–5）被 422 拒绝
- [ ] AC5: `alembic upgrade head` 干净通过，新表启用 RLS；`alembic downgrade` 可回退
- [ ] AC6: Web 端导航出现"人才库"，列表页与详情页可完成建人、打标签、填费率/评分、记跟进、看到期徽标的完整闭环
- [ ] AC7: `uv run pytest server/tests`、`ruff check/format --check`、`mypy server/src`、`pnpm test`、`pnpm build` 全部通过

## Out of Scope

- 提醒模块（应用内聚合页 / 站外通知）——到期仅靠 due 过滤 + 前端徽标；将来单独立项，应做成跨模块基础设施
- Notion 同步、`notion_page_id` 字段、Notion 数据迁移脚本——目标是替代 Notion，零耦合
- `domain` 粗分类字段（被 tags 取代）
- "合作记录"（engagements）第三实体——评分挂人才总体，合作频次起来后再议
- 分页、多租户、标签管理页/受控词表

## Key Decisions（2026-08-26 grilling 确认）

- 参照系：自由职业者对接平台（B 类）为骨架 + 个人 CRM（C 类）的跟进机制；不采用 ATS 管道和 VMS 合规结算
- 技能标签、费率、评分均结构化；费率 = `rate_amount` + `rate_unit`（币种默认人民币，不建模）；评分 = 人才总体 1–5，不挂跟进、不建合作实体
- 砍 `domain`，纯标签体系；标签自由输入 + 前端自动补全已有标签
- 状态机四值不加"黑名单"等负面状态；状态无流转规则（状态是标签不是流程锁）
- 人才库与 CRM 客户库相互独立，同一人可两边存在，不做关联

## Delivery Constraint

- 基线 `origin/main`（6b8b845 之后）；实现遵循 `.trellis/spec/reven-server/backend/` 的 database-guidelines 与 crm-contract 两篇 Active 规范
