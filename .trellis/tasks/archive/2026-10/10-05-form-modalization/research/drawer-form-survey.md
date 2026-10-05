# 表单弹窗化改造调研（#189）

> 来源：explore 子代理全量调研，2026-10-05。为 design.md 提供事实基础。

## 总体结论

- Drawer 基建就绪：`web/src/components/ui/drawer.tsx`，基于 **Radix Dialog ^1.1.15**（非 vaul），右侧滑出，API：`{ open, title, children, footer?, onClose }`。
- 已合并先例 finance `EntryFormDrawer`（自包含模式）与 talents #186 草稿（受控模式）**模式不同**；推荐以 talents 草稿为基准推广到 useResourceList 系页面。
- `useResourceList`（`web/src/lib/use-resource-list.ts:46`）已内建 `onSaved` / `startEdit` / `cancelEdit` / `detailKeyOf`，对 Drawer 化开箱即用。
- RSS 两页独立：`useRssSettingsController.execute(action): Promise<boolean>`，靠返回值驱动关闭/刷新。

## 页面现状

| 页面 | 路由文件 | 表单现状 | 编辑入口 | 状态 hook | 详情页 |
|---|---|---|---|---|---|
| CRM | `features/crm/crm-page.tsx` | `CustomerEditorCard` 内联卡片（包 `CustomerForm` 受控组件） | 行「编辑」→ `list.startEdit`，卡片原地变编辑 | `useResourceList`（key=`crmKeys.customers`，有 `detailKeyOf`） | **有** `/crm/customers/:customerId`，但详情页无客户主档案编辑（仅联系人/跟进内联编辑） |
| 项目 | `features/projects/projects-page.tsx` | 页内内联 `<form>`（无独立表单组件，model 在页内 :24-78） | 行「编辑」→ `list.startEdit` | `useResourceList`（key=`"projects"`） | 无 |
| SOP | `features/sops/sops-page.tsx` | 页内内联 `<form>`；另有只读查看弹窗（手写 Radix Dialog :263-293） | 行「编辑」→ `list.startEdit` | `useResourceList`（key=`"sops"`） | 无 |
| RSS sources | `features/rss/rss-sources-page.tsx` | `SourceForm` Card 顶部内联横条（:154），`useEffect` 监听 editing 回填 | 行「编辑」→ `setEditing(source)` | `useRssSettingsController` | 无 |
| RSS keywords | `features/rss/rss-keywords-page.tsx` | `KeywordForm` 内联（:79），模式同上 | chip 行「编辑」→ `setEditing(keyword)` | `useRssSettingsController` | 无 |
| talents | `features/talents/talents-page.tsx` | **#186 草稿已移除常驻表单**：「新建人才」→ `drawerOpen` state → `TalentFormDrawer` | 行「编辑」跳详情页 `/talents/:id?edit=1` | `useResourceList`（`onSaved: () => setDrawerOpen(false)`） | 有，`TalentDetailPage` 支持 `?edit=1` 内联编辑 |

## talents 抽屉草稿模式（推荐基准）

- `talent-form-drawer.tsx`：纯受控 `{ open, form, tagSuggestions, busy, onChange, onSubmit, onClose }`，`if (!open) return null`，内部 `<Drawer title="新建人才">` + 复用 `TalentForm`（`editing={false}`）。
- 局限：标题硬编码「新建人才」、`editing` 恒 false——**只覆盖新建**；编辑走详情页。
- 测试 `talents-page.test.tsx:102-167` 已按抽屉模式改写（断言 `role="dialog"`）。

## finance EntryFormDrawer 模式（RSS 可参照）

- 自包含：表单 state 在 Drawer 内部，自带 `useMutation`（create/update 分支）、校验、payload 构造；props 极薄 `{ open, variant, entry?, onClose }`；成功后 `invalidateQueries + onClose()`。

## 测试现状

所有目标页面均有 `*.test.tsx`；改造需同步改断言（`role="dialog"` 内操作表单）。`use-resource-list.test.tsx` 已覆盖 onSaved 行为。

## 关键文件行号速查

- Drawer 组件：`web/src/components/ui/drawer.tsx:7-15`（单组件，Portal + 右侧 `sm:max-w-md` 面板 + footer 插槽）
- `useResourceList`：`web/src/lib/use-resource-list.ts:46`
- talents 抽屉：`web/src/features/talents/talent-form-drawer.tsx:17`
- CRM 列表配置：`web/src/features/crm/crm-page.tsx:20-37,56,92`
- RSS controller：`web/src/features/rss/use-rss-settings-controller.ts:12`
