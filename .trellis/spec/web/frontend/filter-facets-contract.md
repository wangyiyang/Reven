# Filter Facets Contract

## 1. Scope / Trigger

Use this contract whenever adding or changing a filter dropdown in `@reven/web`
whose option values come from data stored in the database (e.g. user-defined categories),
not from a closed enum.

## 2. Rule

Filter dropdown options for open-ended value domains **must** come from a
backend facets endpoint. Never hardcode option lists for values that users can
define outside the codebase.

Closed enums owned by the backend (e.g. RSS 视图 `candidate` / `saved`)
may stay hardcoded in the frontend.

## 3. Why

PR `fix/articles-status-filter` (2026-09): `article-filters.tsx` hardcoded seven
imagined pipeline statuses (待发布/等待中/处理中/阻塞/失败/已完成/已交付) while the
real data used notion_status ∈ {已发布, 撰写中, 选题池} and automation_status ∈
{未开始}. The intersection was empty, so every filter selection returned zero
articles and real statuses were unselectable.

该稿件模块及 `/api/articles/status-facets` 已于 2026-09 退役；本案例只保留为规则来源。

## 4. Contract

- 新增开放值域筛选时，由所属模块提供 facets API，返回去重且排序的选项，
  排除空字符串，并保留全局 `AuthMiddleware` 鉴权。
- 前端通过 React Query 加载 facets，使用所属模块的 query key，
  并在选项前添加“全部”。
- If the URL `status` value is absent from the current facets, append it to the
  options so the Radix `Select` trigger never renders blank.
- When the facets request fails, the dropdown degrades to only the sentinel
  option (plus the URL value); the list query must stay unaffected.
- Route ordering: static paths like `/status-facets` must be registered before
  `/{item_id}` in the FastAPI router.
