# PRD · #102 人才库空态与标签状态

## Goal

统一人才库桌面空态结构，并保证客户端验证失败不会丢失用户已确认的标签。

## Confirmed Facts

- `TalentListState` 当前在 `<Table>` 之前渲染空态，同时空的桌面表格仍会渲染表头。
- 当前 `submitTalent` 在验证失败时直接 toast 并返回，代码未显式 reset；标签状态位于父组件 `form.tags`。标签丢失需用回归测试复核，不能臆测根因。

## Requirements

- 桌面空态在 `TableBody` 内使用 `colSpan=6`；移动端使用独立空态，不渲染无内容卡片。
- 添加标签后触发“费率金额与单位需同时填写”时，所有字段与标签保持原值。
- 若当前主干已满足标签状态要求，仅补充回归测试；若测试先失败，再做最小修复。

## Acceptance Criteria

- [x] 桌面空态位于表头下方且跨六列，不存在表格外重复空态。
- [x] 验证失败后“插画”标签、姓名、金额均仍可见/保留。
- [x] 成功提交后的既有 reset 行为不变。
- [x] 相关组件测试通过。

## Out of Scope

- 重构人才表单状态库或改变服务端校验契约。

## Verification

- `pnpm --filter @reven/web exec vitest run src/features/talents/talents-page.test.tsx`：7/7 通过。
- `pnpm --filter @reven/web lint`：通过。
- `pnpm --filter @reven/web build`：通过；仅有既存的大包体积提示。
- 回归断言覆盖桌面六列表头与 `colSpan=6` 空态、移动端独立空态、校验失败保留字段与标签，以及成功提交后的完整重置。
- `git diff --check`：通过。
