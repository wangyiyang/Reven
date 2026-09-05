# Implement: 将 Playbooks 模块统一更名为 SOP（无兼容）

执行顺序按依赖排列：迁移与后端先行（测试 fixtures 依赖表名），前端随后，文档收尾，最后全量验证。

## 清单

### 1. 数据库迁移改写
- [ ] `git mv server/migrations/versions/0012_playbooks.py server/migrations/versions/0012_sops.py`
- [ ] 改写内容：`revision = "0012_sops"`、表名 `sops`、RLS 语句、docstring
- [ ] 验证：`cd server && uv run alembic downgrade 0011_projects && uv run alembic upgrade head`（或 drop 库重建）确认迁移链从空库到 head 通过

### 2. 后端重命名
- [ ] `git mv server/src/reven/playbooks server/src/reven/sops`，`models.py`：`Playbook` → `Sop`、`__tablename__ = "sops"`、kind 默认 `"procedure"`
- [ ] `repository.py`：`PlaybookRepository` → `SopRepository`，方法内变量同步
- [ ] `git mv` routes/schemas 两个 `playbooks.py` → `sops.py`：API 前缀 `/api/sops`、tags `["sops"]`、`SopKind`（`Literal["procedure", "checklist", "script", "method"]`，默认 `"procedure"`）、`SopCreate/SopResponse/SopUpdate`、404 文案「SOP 不存在」
- [ ] `server/src/reven/app.py`：import 与 `include_router` 同步
- [ ] 验证：`cd server && uv run pytest tests/api/test_sops.py -x`

### 3. 后端测试更新
- [ ] `git mv server/tests/api/test_playbooks.py server/tests/api/test_sops.py`，内容全量替换（URL、fixture 名、kind 值、断言文案）
- [ ] `server/tests/conftest.py:52`、`server/tests/api/conftest.py:93`：TRUNCATE 清单 `playbooks` → `sops`
- [ ] `test_integration_latency_migration.py:44`、`test_merge_heads_migration.py:61`：`downgrade(config, "0012_playbooks")` → `"0012_sops"`
- [ ] 验证：`cd server && uv run pytest` 全绿

### 4. 前端重命名
- [ ] `git mv web/src/features/playbooks web/src/features/sops`，`playbooks-page.tsx` → `sops-page.tsx`
- [ ] 类型与组件：`Playbook` → `Sop`、`PlaybookForm` → `SopForm`、`PlaybooksPage` → `SopsPage`、API 路径 `/sops`、queryKey `["sops"]`
- [ ] kindLabels：`procedure: "程序"`，删除 `sop` 键；表单/筛选项同步
- [ ] 全部用户侧文案按 PRD 映射表替换
- [ ] `web/src/app.tsx`：`path="/sops"`，删除 `/playbooks` 路由
- [ ] `web/src/components/app-shell.tsx`：`{ to: "/sops", label: "SOP（标准作业流程）" }`
- [ ] 验证：`cd web && pnpm vitest run src/features/sops src/components/app-shell.test.tsx`

### 5. 前端测试更新
- [ ] `playbooks-page.test.tsx` → `sops-page.test.tsx`：mock 路径、断言文案全量同步
- [ ] `app-shell.test.tsx`：导航断言同步
- [ ] 验证：`cd web && pnpm vitest run` 全绿 + `pnpm tsc --noEmit`（如项目有此脚本则跑对应 typecheck）

### 6. 文档与 Issue 同步
- [ ] `docs/ai-test-map.md`、`.trellis/spec/reven-server/backend/crm-contract.md` 中 playbook 现行描述改为 sops
- [ ] `gh issue edit 107 --repo wangyiyang/Reven`：验收标准替换为 PRD 修订版，注明「无历史数据，取消兼容要求」

### 7. 全量验证（质量门）
- [ ] `grep -ri playbook server/src server/tests server/migrations web/src` 无命中（docs/ai-test-reports 豁免）
- [ ] `cd server && uv run pytest` 全绿
- [ ] `cd web && pnpm vitest run` 全绿
- [ ] 手动：启动前后端，访问 `/sops` 完成创建/筛选/编辑/删除全流程；确认 `/playbooks` 404

## 回滚点

- 每步验证失败时 `git checkout -- <file>` 回滚该步；迁移改写若已应用到本地库，`alembic downgrade 0011_projects` 后恢复文件再 `upgrade head`
- 全部改动未提交前，`git checkout -- .` 整体回滚

## 提交策略（Conventional Commits，原子提交）

1. `refactor(server): rename playbooks module to sops`（迁移 + 后端 + 后端测试）
2. `refactor(web): rename playbooks feature to sops`（前端 + 前端测试）
3. `docs: update sop naming in test map and crm contract`（文档）
