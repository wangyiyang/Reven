# Implement · CRM 第一阶段 MVP

按顺序执行；每步先补能失败的测试，再写满足需求的最小实现。

## Step 0 · 隔离工作区与基线

- [x] 获取最新远端引用，确认 `origin/main` 与当前迁移 head。
- [x] 从 `origin/main` 创建隔离的 `codex/crm-mvp` 分支/工作树，不切换或清理当前脏工作区。
- [x] 把本任务的 `prd.md`、`design.md`、`implement.md` 带入功能分支。
- [x] 通过最终全量测试确认 `origin/main` 基线能力未被破坏；实施前未单独重复跑一次基线。
- 验证：`git status --short --branch` 显示功能分支，且原工作区内容未变化。

## Step 1 · 后端契约测试与迁移

- [x] 新增 CRM API 测试，先覆盖客户 CRUD、搜索/状态/到期筛选、资源不存在和输入校验。
- [x] 扩展测试覆盖联系人主要标记切换、跨客户资源拒绝、联系人删除保留历史、客户删除级联。
- [x] 扩展测试覆盖跟进 CRUD、倒序和 `set_as_current` 的事务语义。
- [x] 新增 `0013_crm` 迁移：三张表、外键、索引、partial unique index 与 RLS；更新迁移模型导入。
- 验证：迁移可从空库升级至 head；新增 API 测试先按预期失败，迁移结构检查通过。

## Step 2 · 后端领域与 API

- [x] 创建 `reven/crm/models.py`，集中定义 ORM 与状态/跟进方式枚举。
- [x] 创建 `reven/crm/repository.py`，实现列表筛选、`EXISTS` 搜索、归属查询和排序。
- [x] 创建必要的 service 事务函数，处理主要联系人切换与跟进同步当前行动。
- [x] 创建 `api/schemas/crm.py`，实现 trim、长度、枚举、邮箱和跨字段校验。
- [x] 创建 `api/routes/crm.py` 并在 `app.py` 注册，统一稳定错误码。
- [x] 保证所有写操作的 commit/rollback 边界明确，失败不留下部分数据。
- 验证：`uv run pytest server/tests/api/test_crm.py`。

## Step 3 · 前端路由、类型与 API

- [x] 新增 CRM 类型和 `crm-api.ts`，页面不得散落原始路径或重复声明 payload。
- [x] 在 `app.tsx` 注册 `/crm` 与 `/crm/customers/:customerId`。
- [x] 在 `app-shell.tsx` 新增 CRM 导航并更新导航测试。
- [x] 复用共享 MSW server，并在 CRM 页面测试中覆盖成功与失败契约。
- 验证：CRM 路由和导航测试通过，TypeScript 编译通过。

## Step 4 · 客户列表闭环

- [x] 实现客户创建/编辑表单、客户列表、搜索、状态筛选和到期筛选。
- [x] 实现桌面表格、移动卡片、日期语义、加载/空态/错误态和重试。
- [x] 实现客户删除确认及成功/失败反馈。
- [x] 添加前端测试：展示、创建、编辑、删除、筛选、搜索、校验、失败不假成功、移动卡片。
- 验证：`pnpm --filter @reven/web test --run crm-page`。

## Step 5 · 客户详情、联系人和跟进

- [x] 实现客户详情摘要与返回列表导航。
- [x] 实现联系人列表及创建、编辑、主要联系人切换、确认删除。
- [x] 实现跟进时间线及创建、编辑、确认删除；新增时明确控制是否同步当前行动。
- [x] 同步成功后失效客户详情、联系人/跟进及客户列表 Query，确保跨页面一致。
- [x] 添加详情页测试：联系人、主要标记、跟进排序、同步当前行动、历史编辑语义、404/错误态。
- 验证：`pnpm --filter @reven/web test --run customer-detail-page`。

## Step 6 · 全量质量门禁

- [x] 后端：`uv run ruff check server`。
- [x] 后端：`uv run ruff format --check server`。
- [x] 后端：`uv run mypy server/src`。
- [x] 数据库：`uv run alembic -c server/migrations/alembic.ini upgrade head`。
- [x] 后端：`uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80`。
- [x] 前端：`pnpm --filter @reven/web lint`。
- [x] 前端：`pnpm --filter @reven/web test --run`。
- [x] 前端：`pnpm --filter @reven/web build`。
- [x] 检查新增文件均小于 500 行、函数小于 50 行，扫描 CRM 联系方式未进入日志。

## Step 7 · 运行态验收

- [x] 在真实迁移后的本地环境创建客户、两个联系人和两条跟进。
- [x] 验证设置主要联系人会替换旧标记；删除联系人后时间线仍保留姓名快照。
- [x] 验证同步下一步、逾期/今日/未来筛选、刷新持久化和级联删除。
- [x] 走查桌面与移动布局、浅色与深色模式、键盘操作和删除确认。
- [x] 对照 PRD 的 AC1–AC9 逐项签收，再进入 Trellis check/finish 流程。

## Rollback Points

- 数据库与后端、前端列表、前端详情分别保持原子提交；任一步失败可独立回退。
- 迁移上线后如需应用回滚，先移除 CRM 路由/导航；确认无数据保留需求后才执行 downgrade。
- 禁止通过清理或重置当前主工作区解决分支冲突。
