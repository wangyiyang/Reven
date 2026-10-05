# talents 页面拆分：列表去表单化，新建抽屉化，编辑收进详情页

来源：GitHub Issue #186（Boss 需求：/talents 按「列表页只留列表，新建/编辑独立化」拆分）。

## Goal

`/talents` 列表页移除常驻「添加/编辑人才」表单卡片（TalentEditorCard），首屏即列表；新建改为抽屉（Drawer），编辑统一收进详情页 `/talents/:id`。

## Requirements

- 列表页：只保留列表 + 筛选 + 删除确认；顶部提供「新建人才」按钮。
- 新建：抽屉内嵌 `TalentForm`（对齐 finance `EntryFormDrawer` 先例）；保存成功 → 关抽屉 + toast「人才已添加」+ 列表刷新，停留列表页。
- 编辑：详情页 `TalentSummary` 卡片支持「编辑」切换为表单态，保存/取消回到只读；`/talents/:id` 为唯一编辑入口。
- 列表行「编辑」：跳转 `/talents/:id?edit=1`，详情页自动进入编辑态。
- 删除：仅列表页，`ConfirmDialog` 流程不变。
- 字段、校验、标签建议（tag suggestions）在新建/编辑流程均不回归。

## 红线（约束）

- 不改后端 API。
- 不动 talents 模块以外的其他模块（不重构 `useResourceList`，不动 CRM/finance 等）。
- 中文提交，走 GitHub Flow（分支 `feat/186-talents-page-split` → PR 回 main）。

## Acceptance Criteria

- [ ] `/talents` 无常驻表单，首屏即列表
- [ ] 新建（抽屉）/编辑（详情页编辑态）流程完整可用，字段、校验、标签建议不回归
- [ ] 列表行「编辑」跳详情页并自动进编辑态
- [ ] `talents-page.test.tsx` / `talent-detail-page.test.tsx` 等测试更新后 `pnpm test -- run` 全绿
- [ ] `pnpm lint`、`pnpm build`（含 `tsc -b`）干净

## Notes

- 设计已定（grilling 两轮与用户确认），见 `design.md`；执行清单见 `implement.md`。
- Issue 描述中「参照 CRM 择一」不可照搬：CRM 列表页同样常驻表单、详情页只读，项目内真正先例是 finance 的 Drawer 方案——已与用户确认采用 Drawer。
