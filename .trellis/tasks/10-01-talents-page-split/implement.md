# 执行计划：talents 页面拆分

全部改动锁在 `web/src/features/talents/`；命令均在 `web/` 下执行（pnpm）。

## 执行清单（按序）

1. [ ] 新增 `talent-form-drawer.tsx`（仿 `web/src/features/finance/entry-form-drawer.tsx`）
2. [ ] 改 `talents-page.tsx`：移除 `TalentEditorCard`、加「新建人才」按钮 + Drawer 接线（`onSaved` 关抽屉）
3. [ ] 改 `talent-list.tsx`：行内「编辑」→ `navigate(`/talents/${id}?edit=1`)`
4. [ ] 改 `talent-detail-page.tsx`：编辑态切换 + `?edit=1` + PATCH mutation + 缓存失效 + 标签建议
5. [ ] 改 `talents-page.test.tsx`：创建用例走抽屉，移除列表页编辑断言
6. [ ] 改 `talent-detail-page.test.tsx`：补编辑态三个用例

## 验证点

- 每步后：`pnpm test -- run`（相关测试文件）
- 收尾全量：`pnpm test -- run`、`pnpm lint`、`pnpm build`（含 `tsc -b`）

## 回滚点

- 每步一个可独立还原的文件改动；整体回滚 = `git checkout -- web/src/features/talents/`（分支内无其他改动）

## 审查门禁

- 实现完成后由 trellis-check 对照 prd.md / design.md / 本清单全量复核，并跑三条验证命令。
