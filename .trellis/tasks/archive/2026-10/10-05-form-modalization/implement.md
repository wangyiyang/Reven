# 执行计划：表单 Drawer 化（#189）

> 开发目录：`/Users/wangyiyang/Documents/Github/worktrees/Reven/issue/gh-189-feat-web`（分支 `issue/gh-189-feat-web`）
> 验证命令（web 包）：`cd web && pnpm test -- <file>`、`pnpm tsc --noEmit`、`pnpm lint`、（需要时）`pnpm build`

## 阶段 0：环境

- [x] worktree 内 `cp`/软链主仓库 `.env`（跑后端联调时需要；纯前端单测不需要）
- [x] worktree 内 `pnpm install`（确认 node_modules 就绪）

## 阶段 1：项目页（模式最简单，先打通）

- [x] 抽出 `features/projects/project-form-model.ts` + 受控 `ProjectForm`（从 projects-page.tsx:24-78,117-169 迁移）
- [x] 页面去表单化：「新建项目」按钮 + `ProjectFormDrawer`；`useResourceList` 传 `onSaved` 关抽屉
- [x] 行「编辑」→ Drawer 内编辑态（`list.editing` 派生打开）
- [x] 更新 `projects-page.test.tsx`（dialog 内断言）
- [x] 验证：`pnpm test -- projects-page`、`tsc --noEmit`

## 阶段 2：SOP 页（同模式复用）

- [x] 抽 `SopForm` + form model；「新建 SOP」按钮 + Drawer；编辑进 Drawer
- [x] 查看弹窗不动
- [x] 更新 `sops-page.test.tsx`
- [x] 验证：单测 + tsc

## 阶段 3：RSS 两页（自包含模式）

- [x] sources：「新建 RSS 源」按钮 + Drawer（`SourceForm` 挪入，editing 回填逻辑挪进 Drawer）
- [x] keywords：同上（`KeywordForm`）
- [x] 保存成功（execute 返回 true）关闭 Drawer
- [x] 更新 `rss-sources-page.test.tsx` / `rss-keywords-page.test.tsx`
- [x] 验证：单测 + tsc

## 阶段 4：CRM（最大改动：详情页编辑态）

- [x] `crm-page.tsx` 去 `CustomerEditorCard`；「新建客户」按钮 + `customer-form-drawer.tsx`（复用 `CustomerForm`）
- [x] 行「编辑」改跳 `/crm/customers/:id?edit=1`
- [x] `customer-detail-page.tsx` 补主档案编辑态（参照 `talent-detail-page.tsx`：懒初始化 edit state、本地 mutation、setQueryData + invalidate；「编辑」aria-label `编辑客户档案`）
- [x] 更新 `crm-page.test.tsx` + `customer-detail-page.test.tsx`
- [x] 验证：单测 + tsc

## 阶段 5：全站核对与收尾

- [x] talents 页与 #186 草稿模式核对（本分支不动 talents 代码）
- [x] 全量验证：`pnpm test`、`tsc --noEmit`、`pnpm lint`、（提交前）`pnpm build`
- [x] 人工走查：各页打开/提交/取消/关闭抽屉，提交后列表刷新
- [x] `trellis-check` 质量检查

## 回滚点

- 每个阶段独立提交，单个页面出问题 revert 该阶段 commit 即可，无跨页面耦合。

## 提交计划（Conventional Commits，原子提交）

1. `feat(web): projects 页面表单抽屉化（#189）`
2. `feat(web): sops 页面表单抽屉化（#189）`
3. `feat(web): rss 源与关键词表单抽屉化（#189）`
4. `feat(web): crm 页面表单抽屉化，客户档案编辑收进详情页（#189）`

## PR

- 分支 `issue/gh-189-feat-web` → `main`，描述关联 closes #189
