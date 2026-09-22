# Hook Guidelines

> How hooks are used in this project.

---

## Overview

<!--
Document your project's hook conventions here.

Questions to answer:
- What custom hooks do you have?
- How do you handle data fetching?
- What are the naming conventions?
- How do you share stateful logic?
-->

(To be filled by the team)

---

## Custom Hook Patterns

### Convention: CRUD 列表页一律走 `useResourceList` seam

**What**：列表型页面的查询 / filters / 增删改 / 乐观删除 / toast 归一化全部经 `web/src/lib/use-resource-list.ts`；页面只写字段渲染与 `toPayload`/`toForm` 映射。

**Why**：该逻辑曾在 projects/sops/talents/crm 存在 4 份漂移拷贝；乐观删除回滚的 cache-key 错位会静默失效（GH #136）。

```ts
const list = useResourceList<Project, ProjectForm, ProjectFilters>({
  key: "projects",            // 或元组 ["crm", "customers"]
  path: "/api/projects",
  initialForm, toPayload, toForm,
  updateMethod: "PATCH",      // 默认 PUT
  detailKeyOf: (p) => ["projects", "project", p.id], // update 时写详情缓存
  onSaved: () => setDrawerOpen(false),
  messages: { created: "已创建", /* … */ },
});
```

**Caller 禁止**：直接 `useQuery/useMutation` 操作同一资源、直接接触 `queryClient` 原语（用 `detailKeyOf`/`onSaved`/`onDeleted` 钩子）。

---

## Data Fetching

- React Query（`@tanstack/react-query`）+ `lib/api.ts` 的 `apiRequest`；query-key 纪律：`[key, filters]` 查询、`[key]` 前缀失效。
- **Common Mistake: 前缀下存在非列表缓存**。`setQueriesData({queryKey: [key]}, updater)` 会命中详情/子资源缓存（如 `["talents","interactions",id]`），updater 必须先 `Array.isArray(old)` 守卫——seam 已内置，手写 mutation 时同样适用。

---

## Naming Conventions

- Hook 以 `use` 开头；资源级 seam hook 放 `web/src/lib/`，feature 私有 hook 放 feature 目录内。

---

## Common Mistakes

<!-- Hook-related mistakes your team has made -->

(To be filled by the team)
