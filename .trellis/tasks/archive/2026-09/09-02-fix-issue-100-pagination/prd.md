# PRD · #100 稿件分页越界

## Goal

让所有非法或过期页码链接自动恢复到有效稿件页，避免误导性空态和无返回入口。

## Confirmed Facts

- `readFilters` 已把非整数、0、负数归一为查询第 1 页，但不会同步改写地址栏。
- 大于最后一页的正整数会请求空列表；当前仅在有 items 时渲染分页，因此用户会陷入普通空态。

## Requirements

- 非整数、0、负数规范化为 `page=1`。
- `total > 0` 且请求页大于末页时，使用 `replace` 规范化为最后一页，避免污染浏览历史。
- 真正无匹配结果时继续显示现有空态。
- 保留已有 status/channel/query 筛选参数。

## Acceptance Criteria

- [x] `page=abc`、`page=0`、`page=-5` 展示第 1 页且 URL 为 `page=1`。
- [x] `page=99` 在三页数据时展示第 3 页且 URL 为 `page=3`。
- [x] 规范化时不丢筛选参数，不产生循环请求。
- [x] 增加组件回归测试并通过。

## Verification

- `pnpm -C web exec vitest run src/features/articles/articles-page.test.tsx`：15 项通过。
- `pnpm --filter @reven/web lint`：通过。
- `pnpm --filter @reven/web build`：TypeScript 与 Vite 构建通过，仅有既有 chunk size 警告。
- 独立 `trellis-check` 复核了 replace 导航、筛选保留、请求次数、循环风险、空态屏蔽及测试有效性，无遗留发现。

## Out of Scope

- 改变服务端分页 API 契约或增加跳页控件。
