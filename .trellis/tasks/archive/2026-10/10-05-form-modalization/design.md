# 技术设计：各资源页面表单 Drawer 化（#189）

## 结论

复用现有 `web/src/components/ui/drawer.tsx`，按两类落地：

1. **useResourceList 系页面**（CRM / 项目 / SOP）：以 talents #186 草稿的「受控 Drawer」模式为基准——表单状态留在 `useResourceList`，Drawer 只做壳，`onSaved` 负责关抽屉。
2. **RSS 两页**（无 `useResourceList`，controller 返回 Promise）：参照 finance `EntryFormDrawer` 的自包含模式。

## 编辑路径（与 issue 原文的取舍）

issue 写「编辑入口也统一进窗口」，但已合并的 spec convention（源自 #186 验证过的决策）规定：**有详情页的实体编辑收进详情页页内切换，无详情页的实体编辑走 Drawer**。issue 本身也要求「参照 #186 的模式落地」。故：

| 实体 | 新建 | 编辑 | 理由 |
|---|---|---|---|
| CRM 客户 | Drawer | 详情页 `?edit=1` 页内编辑（需给详情页补主档案编辑态） | 有详情页，spec convention |
| 项目 | Drawer | 同一 Drawer | 无详情页 |
| SOP | Drawer | 同一 Drawer | 无详情页（查看弹窗维持现状，不在本任务范围） |
| RSS 源/关键词 | Drawer | 同一 Drawer | 无详情页 |
| talents | — | — | #186 负责，本任务不重复 |

## 各类页面改造要点

### CRM（`features/crm/`）

- `crm-page.tsx`：删除 `CustomerEditorCard` 顶部常驻卡片；顶部改「新建客户」按钮 → 本地 `drawerOpen` state → 新增 `customer-form-drawer.tsx`（纯受控壳，复用现有 `CustomerForm`）。
- `useResourceList` 传 `onSaved: () => setDrawerOpen(false)`。
- 列表行「编辑」action 从 `list.startEdit` 改为跳 `/crm/customers/:id?edit=1`。
- `customer-detail-page.tsx`：补客户主档案编辑态（参照 `talent-detail-page.tsx` 模式：本地 `useState` 懒初始化 `searchParams.get("edit") === "1"`，不实例化 `useResourceList`，校验/转换复用本模块 form model，PATCH 成功 `setQueryData` + invalidate 列表）。
- 注意：详情页已有联系人/跟进 section 的内联编辑，新增主档案编辑时「编辑」按钮加区分性 aria-label（如 `编辑客户档案`）。

### 项目（`features/projects/`）

- 页内内联 `<form>` 抽成受控 `ProjectForm` 组件（model/toPayload/toForm 从页内 :24-78 移到 `project-form-model.ts`）。
- 页面顶部改「新建项目」按钮 + `ProjectFormDrawer`；`onSaved` 关抽屉。
- 行「编辑」维持 `list.startEdit`（编辑态由 hook 管），但表单渲染挪进 Drawer：Drawer 内 `editing` 由 `list.editing` 派生，编辑态打开 Drawer，取消/保存成功关闭。

### SOP（`features/sops/`）

- 同 projects：内联 `<form>` 抽 `SopForm` + form model；「新建 SOP」按钮 + Drawer；行「编辑」进 Drawer。
- 只读「查看」弹窗（:263-293 手写 Dialog）维持现状，不在本任务改动。

### RSS sources / keywords（`features/rss/`）

- 两页表单从 Card 顶部内联横条挪进 Drawer。
- 模式：页面本地 `drawerOpen`/`editing` state（替代现在的 `editing` 原地切换）；保存成功 `execute()` 返回 true 后关闭 Drawer 并清 editing；`useEffect` 回填逻辑挪进 Drawer 内部（editing 变化时重置局部表单 state）。
- 表单组件 `SourceForm`/`KeywordForm` 保持局部 state 自包含，仅改为 Drawer 内渲染。

## 统一约束

- 抽屉统一用 `components/ui/drawer.tsx`，**不引入 vaul/新组件**；sops 查看弹窗等既有 Dialog 不动。
- 不新增 `/new`、`/:id/edit` 路由。
- 每个页面同步更新 `*.test.tsx`：断言表单在 `role="dialog"` 内、打开/提交/取消/关闭交互、提交后列表刷新（参照 talents-page.test.tsx:102-167 草稿断言）。
- 同页多个同名按钮加区分性 aria-label。
- 对话框关闭后焦点恢复由 Drawer（Radix Dialog）保证，删除类操作不破坏该契约。

## 兼容与回滚

- 纯前端交互改造，无 API/数据层变更；回滚 = revert 单个 PR。
- talents 草稿（#186）在 main 工作区未提交，本分支不携带；两任务改不同页面（除 talents 外），冲突面小。若 #186 先合入，本分支 rebase 后 talents 部分自动一致。

## 不做的事（YAGNI）

- 不做 Modal 方案、不做路由级编辑页、不抽象通用 `ResourceFormDrawer`（各 Drawer 薄壳重复成本低于过早抽象；若第 3 个页面写完发现壳代码雷同再提取）。
- 不改 sops 查看弹窗、finance 既有实现。
