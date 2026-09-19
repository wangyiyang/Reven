# Filter Facets Contract

## 1. Scope / Trigger

Use this contract whenever adding or changing a filter dropdown in `@reven/web`
whose option values come from data stored in the database (e.g. article status),
not from a closed enum.

## 2. Rule

Filter dropdown options for open-ended value domains **must** come from a
backend facets endpoint. Never hardcode option lists for values that users can
define outside the codebase (e.g. Notion status names).

Closed enums owned by the backend (e.g. `TargetChannel`: 个人博客 / 微信公众号)
may stay hardcoded in the frontend.

## 3. Why

PR `fix/articles-status-filter` (2026-09): `article-filters.tsx` hardcoded seven
imagined pipeline statuses (待发布/等待中/处理中/阻塞/失败/已完成/已交付) while the
real data used notion_status ∈ {已发布, 撰写中, 选题池} and automation_status ∈
{未开始}. The intersection was empty, so every filter selection returned zero
articles and real statuses were unselectable.

## 4. Contract

- `GET /api/articles/status-facets` → `{"statuses": string[]}`: distinct union
  of `articles.notion_status` and `articles.automation_status`, Python-side
  `sorted()` (collation-independent), empty strings excluded. Auth via the
  global `AuthMiddleware`.
- Frontend fetches facets via React Query (`queryKey: ["article-status-facets"]`,
  `staleTime: 60_000`) and prepends the "全部" sentinel option.
- If the URL `status` value is absent from the current facets, append it to the
  options so the Radix `Select` trigger never renders blank.
- When the facets request fails, the dropdown degrades to only the sentinel
  option (plus the URL value); the list query must stay unaffected.
- Route ordering: static paths like `/status-facets` must be registered before
  `/{article_id}` in the FastAPI router.
