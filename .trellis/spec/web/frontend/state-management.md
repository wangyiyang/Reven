# State Management

> How state is managed in this project.

---

## Overview

<!--
Document your project's state management conventions here.

Questions to answer:
- What state management solution do you use?
- How is local vs global state decided?
- How do you handle server state?
- What are the patterns for derived state?
-->

(To be filled by the team)

---

## State Categories

<!-- Local state, global state, server state, URL state -->

(To be filled by the team)

---

## When to Use Global State

<!-- Criteria for promoting state to global -->

(To be filled by the team)

---

## Server State

- React Query 是唯一的 server-state 载体；不允许在 feature 内另起 fetch + useState 缓存同一资源。
- query-key 纪律：列表 `[key, filters]`、详情 `[key, singular, id]`；失效用 `[key]` 前缀；元组 key（如 `["crm","customers"]`）注意前缀不要误伤兄弟缓存（contacts/follow-ups）。
- 乐观更新只写在 seam（`useResourceList`）内；页面级 mutation 默认走 invalidate，不手写 `setQueriesData`。

### Convention: 路由与导航的唯一真相源是 `web/src/routes.tsx`

加页面 = `routes.tsx` 一处数组项；`App`（`<Routes>`）与 `AppShell`（导航）共同消费。导航折叠组开关状态为 `Record<groupId, boolean>`（groupId 取分组 path），localStorage 持久化键 `reven:nav:group-open:<path>`；禁止再出现硬编码单组开关（前 `rssOpen` 单例，GH #137）。

---

## Common Mistakes

- **手写第二份导航/路由登记**：`app.tsx` 加 Route 却忘改 shell 导航（或反之）——routes.tsx 收敛后禁止回退。
