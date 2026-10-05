# 技术设计：talents 页面拆分

## 现状（调研结论）

- `web/src/features/talents/talents-page.tsx`（117 行）：`useResourceList` 驱动，`TalentEditorCard` 常驻表单 + `TalentListCard` + `ConfirmDialog` 一屏堆叠；`tagSuggestions` 由列表数据聚合（`useMemo`）。
- `talent-detail-page.tsx`（85 行）：只读，`DetailHeading` + `TalentSummary` + `InteractionsSection`。
- `TalentForm`（`talent-form.tsx`）完全受控（`values` + `onChange` 整对象回传）；校验/转换在 `talent-form-model.ts`（`validateTalentForm` / `talentFormToInput` / `talentToForm` / `EMPTY_TALENT_FORM`）；标签建议用原生 `<datalist>`。
- `useResourceList`（`web/src/lib/use-resource-list.ts`）：create/update/delete 三 mutation + 表单/编辑/删除态，`onSaved(entity)` 回调注释即「供关闭抽屉等扩展」（finance `EntryFormDrawer` 就是这么接的）；talents 是唯一传 `updateMethod: "PATCH"` 的调用方；`detailKeyOf` 用于更新后写详情缓存。
- 可复用 UI：`web/src/components/ui/drawer.tsx`（`Drawer`，右侧滑出，Radix Dialog 封装，props 含 open/title/onClose + footer）；`dialog.tsx` 仅导出 `ConfirmDialog`；无独立 AlertDialog。
- 路由：`web/src/routes.tsx`，`/talents` 与 `/talents/:talentId` 已注册，本方案**不新增路由**。
- 参照先例：finance `web/src/features/finance/entry-form-drawer.tsx`（Drawer 包表单）；crm `contacts-section.tsx`（本地 `useState` + `useMutation` + `ConfirmDialog` 三件套）。

## 已定决策（与用户两轮确认）

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | 新建承载形式 | **Drawer 抽屉**（对齐 finance；复用 `onSaved`；不加路由；不用 Dialog） |
| 2 | 详情页编辑形态 | **页内编辑切换**（档案卡片只读 ⇄ 表单态；不用抽屉/子路由） |
| 3 | 删除范围 | 仅列表页，详情页不加删除 |
| 4 | 状态管理 | 列表页整留 `useResourceList`；详情页编辑用本地 `useState` + `useMutation`（contacts-section 先例），复用 `talent-form-model` 的校验/转换；**不拆 hook** |
| 5 | 列表行「编辑」 | 跳 `/talents/:id?edit=1`，详情页读 search param 自动进编辑态 |
| 6 | 新建成功后 | 关抽屉 + toast「人才已添加」+ 列表刷新，停留列表页 |

## 改动清单（文件级）

1. **`web/src/features/talents/talent-form-drawer.tsx`（新增）**：仿 `entry-form-drawer.tsx`，`Drawer` 包 `TalentForm`；props 约 `{ open, form, tagSuggestions, busy, onChange, onSubmit, onClose }`。
2. **`talents-page.tsx`**：移除 `TalentEditorCard`；`PageHeading` 区加「新建人才」按钮开抽屉；`useResourceList` 保留（列表/筛选/删除/新建表单态），`onSaved` 关闭抽屉；编辑相关入口从列表页移除。
3. **`talent-list.tsx`**：行内「编辑」action 改为 `navigate(`/talents/${id}?edit=1`)`；删除不变；姓名 `Link` 不变。
4. **`talent-detail-page.tsx`**：`TalentSummary` 卡片加「编辑」按钮切换表单态（`useState<boolean>` + 表单 `useState<TalentFormValues>`，进入编辑时 `talentToForm(talent)` 初始化）；`useSearchParams` 读 `edit=1` 自动进编辑态（进入后替换掉 param 或不处理均可，实现从简）；保存走 `useMutation`（PATCH，与 `talents-api` 一致），`validateTalentForm` 前置校验失败 `toast.error` 不发请求；成功后失效/更新 `talentsKeys` 列表 + 详情缓存，toast「人才已更新」，回只读态。
5. **标签建议**：抽屉直接复用列表页已聚合的 `tagSuggestions`；详情页编辑态补一个列表查询（React Query 同 key，列表页过来时命中缓存）聚合 tags，保证不回归。

## 数据流 / 缓存契约

- 新建：`useResourceList.submit`（create mutation）→ 失效列表缓存 → `onSaved` 关抽屉。
- 编辑：详情页 mutation `onSuccess` → 更新 `talentsKeys.talent(id)` 详情缓存 + 失效列表缓存 → toast → 退出编辑态。
- PATCH 语义与列表页原编辑一致（`updateMethod: "PATCH"`），后端零改动。

## 测试方案

- `talents-page.test.tsx`：创建用例改为「点新建人才 → 抽屉内填写 → 提交」（断言提交体不变）；**移除**列表页编辑相关断言；删除/筛选/空态/重试用例不动。
- `talent-detail-page.test.tsx`：新增「点编辑进表单态 → 保存成功回只读」「校验失败保留表单 + toast」「`?edit=1` 进入自动进编辑态」用例；现有档案/跟进/404 用例不动。
- `use-resource-list.test.tsx` 不动。

## 不做什么（YAGNI 边界）

- 不加 `/talents/new`、`/talents/:id/edit` 路由；不加居中 Dialog；详情页不加删除按钮；不抽 `useResourceForm`；不加「保存并查看详情」。
