# PRD: 将 Playbooks 模块统一更名为 SOP（无兼容）

## 目的

将 Playbooks 模块统一更名为「SOP（标准作业流程）」，用户侧与代码库内不再使用 Playbooks 或「SOP / 话术库」作为名称。对应 GitHub Issue: wangyiyang/Reven#107。

## 背景

现有功能由 Issue #47 实现，当前存在 Playbooks、SOP、话术库等多种称呼，语义不一致。「话术库」会将模块范围限定为沟通文本，无法覆盖 checklist、method 等标准作业内容。

**范围变更（与原 Issue #107 的差异）**：项目无历史数据、无外部 API 调用方，因此**取消一切兼容要求**——不做旧路由跳转、不做 API 兼容层、不做数据迁移，`playbook` 命名从代码库中彻底清零。

## 决策记录（grilling 共识）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 重命名深度 | 全量重命名：目录、文件、类名、变量、API 路径、数据库表名、迁移文件 |
| 2 | `kind="sop"` 语义冲突 | kind 值 `sop` → `procedure`（中文标签「程序」）；`checklist`/`script`/`method` 三值及标签不动 |
| 3 | 数据库迁移 | 直接改写 `0012_playbooks.py` → `0012_sops.py`（revision id、表名、RLS、kind 默认值）；本地库重建验证，不新增迁移 |
| 4 | 类名风格 | 大驼峰 `Sop`（如 `SopRepository`、`SopsPage`），不保留全大写缩写 |
| 5 | 用户侧文案 | 分层用词：页面标题/导航「SOP（标准作业流程）」，toast/按钮/表单等操作文案「SOP」 |
| 6 | Issue 同步 | 完成后用 `gh issue edit` 更新 #107 验收标准，标注取消兼容的原因 |

## 改动范围

### 数据库
- `server/migrations/versions/0012_playbooks.py` → `0012_sops.py`：revision id、表名 `playbooks` → `sops`、RLS 语句、kind 默认值 `"sop"` → `"procedure"`

### 后端
- `server/src/reven/playbooks/` → `server/src/reven/sops/`（`models.py`：`Playbook` → `Sop`、`__tablename__ = "sops"`；`repository.py`：`SopRepository`）
- `server/src/reven/api/routes/playbooks.py` → `routes/sops.py`：前缀 `/api/sops`、tags、函数名、404 文案「SOP 不存在」
- `server/src/reven/api/schemas/playbooks.py` → `schemas/sops.py`：`PlaybookKind` → `SopKind`（值 `procedure`）、`SopCreate/SopResponse/SopUpdate`
- `server/src/reven/app.py`：路由注册同步
- 测试：`server/tests/api/test_playbooks.py` → `test_sops.py`；`server/tests/conftest.py:52` 与 `server/tests/api/conftest.py:93` 的 TRUNCATE 表名；`server/tests/migrations/test_integration_latency_migration.py:44`、`test_merge_heads_migration.py:61` 的 downgrade 目标 revision

### 前端
- `web/src/features/playbooks/` → `web/src/features/sops/`（`sops-page.tsx`：类型 `Sop`、组件 `SopsPage`、API 路径 `/sops`、queryKey `["sops"]`、全部用户侧文案）
- `web/src/app.tsx`：路由 `/playbooks` → `/sops`（旧路由删除，不保留跳转）
- `web/src/components/app-shell.tsx`：导航 `{ to: "/sops", label: "SOP（标准作业流程）" }`
- 测试：`sops-page.test.tsx`、`app-shell.test.tsx` 同步

### 用户侧文案映射
| 现状 | 目标 |
|---|---|
| 页面标题「SOP / 话术库」 | 「SOP（标准作业流程）」 |
| 导航「SOP/话术」 | 「SOP（标准作业流程）」 |
| 「添加 Playbook」「编辑 Playbook」「Playbook 列表」 | 「添加 SOP」「编辑 SOP」「SOP 列表」 |
| toast「Playbook 已添加/已更新/已删除」 | 「SOP 已添加/已更新/已删除」 |
| 空状态/筛选等其余 Playbook 字样 | 统一「SOP」 |
| kind 标签 `sop` → "SOP" | `procedure` → 「程序」 |

### 文档
- `docs/ai-test-map.md`、`.trellis/spec/reven-server/backend/crm-contract.md` 中的现行描述同步
- `docs/ai-test-reports/2026-08-20-*.md` 为历史快照，**不回改**
- GitHub Issue #107 验收标准修订（`gh issue edit`）

## 验收标准（修订版，将同步至 Issue #107）

1. 用户侧不再出现 Playbooks 或「SOP / 话术库」字样
2. 页面统一显示「SOP（标准作业流程）」
3. `/sops` 可正常访问；`/playbooks` 路由与 `/api/playbooks` 接口不再存在
4. 代码库中 `playbook` 命名清零（`grep -ri playbook server/src web/src server/tests web/src` 无命中）；数据库表更名为 `sops`，迁移链可从空库跑到 head
5. 相关现行文档与全部测试同步更新并通过

## 明确排除

- 旧路由 `/playbooks` → `/sops` 的跳转兼容
- `/api/playbooks` 的兼容层/别名
- 数据迁移脚本（无历史数据）
- `checklist`/`script`/`method` 的 kind 值与标签变更
- 历史测试报告（`docs/ai-test-reports/`）的回改
