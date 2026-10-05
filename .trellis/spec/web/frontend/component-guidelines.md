# Component Guidelines

> How components are built in this project.

---

## Overview

<!--
Document your project's component conventions here.

Questions to answer:
- What component patterns do you use?
- How are props defined?
- How do you handle composition?
- What accessibility standards apply?
-->

(To be filled by the team)

---

## Component Structure

### Convention: 列表页双视口渲染一律走 `ResponsiveList`

**What**：同一实体的移动卡片（`lg:hidden`）+ 桌面 Table（`hidden lg:block`）由 `web/src/components/responsive-list.tsx` 独占渲染；页面只提供 `columns` / `card` / `actions` 描述。

**Why**：双渲染曾散在 6 个页面各 60-100 行平行 JSX，空态/action/aria-label 需平行维护两遍（GH #136）。

```tsx
<ResponsiveList
  items={list.itemsQuery.data} keyOf={(p) => p.id}
  emptyText="暂无项目，先添加一个。" cardLabel={(p) => `${p.name} 移动摘要`}
  columns={[{ header: "名称", cell: (p) => p.name }/* … */]}
  card={(p) => ({ title: p.name, meta: /* … */ })}
  actions={[{ label: "编辑", ariaLabel: (p) => `编辑 ${p.name}`, onClick: list.startEdit }/* … */]}
/>
```

**约束**：action 定义一组、双视口各渲染一遍，aria-label 对等由 seam 保证；页面不再手写 `lg:hidden`/`hidden lg:block` 列表容器。

### Convention: 共享 UI 落 `components/ui`

通用展示件（如 `ErrorPanel`）放 `web/src/components/ui/`；feature 私有件留在 feature 目录（先例：`rss-shared.tsx` 的 `StatusBadge` 仅 rss 使用，不提升）。

### Convention: 列表页去表单化拆分——新建走 `Drawer`，编辑收进详情页

**What**：列表页不常驻新建/编辑表单。新建 → `Drawer`（`web/src/components/ui/drawer.tsx`）包受控表单，`useResourceList` 的 `onSaved` 回调负责关抽屉（该回调的注释即「供关闭抽屉等扩展」，抽屉是其设计内用法）；编辑 → 收进详情页页内切换（只读卡片 ⇄ 表单态），列表行「编辑」跳 `/:id?edit=1`，详情页用 `useState(() => searchParams.get("edit") === "1")` 懒初始化进编辑态。先例：finance `entry-form-drawer.tsx`、talents `talent-form-drawer.tsx` + `talent-detail-page.tsx`（GH #186）。

**Why**：一屏堆叠「常驻表单 + 列表」让首屏被表单占据（GH #186 前的 talents-page；crm-page 仍是旧结构，后续拆分应照此对齐）。统一做法避免各模块各自发明弹窗/子路由。

**约束**：
- 详情页编辑不实例化 `useResourceList`（会白拉列表、闲置删除流程）；用 contacts-section 式本地 `useState` + `useMutation`，校验/转换复用本模块 `*-form-model.ts`。
- 标签建议等由列表聚合的数据，详情页编辑态用同 key 的列表查询聚合，并加 `enabled` 门控（如 `enabled: editing`），避免只读浏览时多打全量请求。
- 同页出现多个同名按钮（如详情页档案卡与跟进卡各有「编辑」）时加区分性 aria-label（如 `编辑人才档案`），否则 `getByRole` 与读屏歧义。
- 不为拆分新增 `/new`、`/:id/edit` 路由，也不为此拆 `useResourceList`。

### Convention: Drawer/Dialog 受控开合，禁止提前卸载

**What**：浮层调用方始终渲染组件、以 `open` prop 受控，禁止 `if (!open) return null`。`Drawer`（`web/src/components/ui/drawer.tsx`）经 Radix `data-[state=open/closed]` 触发 `index.css` 的 `drawer-fade/slide-in/out` keyframes，Radix Presence 等 `animationend` 后才卸载 children——提前 return null 会让退出动画永远播不了。

**Why**：7 个抽屉曾全部 `if (!open) return null`，开关瞬现瞬隐（GH 前 #186 时代遗留）。自含状态的表单组件放进 Drawer children 还有第二个收益：Presence 关闭后才卸载，下次打开重新挂载，表单自然重置，语义与旧卸载模式一致、无需 reset effect。

**约束**：
- 父级在关闭时立即清空数据源的场景（如 finance `entry` 置空、sops `viewing` 置空），用 ref 快照最后一次打开的会话数据渲染，避免 240ms 退出动画期间内容闪变/结构消失。
- 仅标题一词之差（「编辑 X」→「新建 X」）属可接受 cosmetic，不值得加快照。
- 浮层只用共享组件：`Drawer`（侧滑）/ `ConfirmDialog`（居中确认，深遮罩 `bg-black/55` 为既有设计，勿"统一"成浅遮罩）。禁止页面内联手写 `Dialog.Overlay/Content`（先例：sops 查看弹窗、confirm-settle-dialog 已收敛）。
- `Drawer` 必渲染 sr-only `Dialog.Description`（缺省复用 title），消除 Radix a11y 警告。

---

## Props Conventions

- **窄 interface**：一个 module 的 props 应显著小于其内部实现；发现 props 钻给 3+ 个内部子组件且各自 props 近乎雷同时，收拢为一个 module（先例：`IntegrationCard` 10 props → `{definition, controller}`，GH #137）。
- **禁止字符串编码状态**：跨 module 的状态用结构化类型（如 `busy: IntegrationActionKind | null`），不要让 caller 用 `startsWith` 反解析 `"provider:action"` 这类编码。

---

## Styling Patterns

Tailwind 实用类；组件级样式变体经可选 props（如 `column.className`、`action.variant`）暴露，不开放任意 className 透传。

---

## Accessibility

- 交互元素必须有 aria-label；列表 action 的移动/桌面两实例标签对等（`ResponsiveList` 负责）。
- 对话框关闭后的焦点恢复是行为契约，删除/确认类操作必须保留（先例：IntegrationCard 删除成功焦点落「保存配置」）。

---

## Common Mistakes

- **平行 JSX 树漂移**：同一数据渲染两遍时改动只改一处——用 `ResponsiveList` 杜绝。
- **复刻共享格式化函数**：金额格式化的唯一真相源是 `@/features/finance/finance-utils`（`formatMoney`），新 feature 一律导入复用，不在自己的 `*-api.ts` 里重写（先例：10-05 dashboard 复刻后被 check 收敛）。
- **浅 partition**：把一张卡片拆成 5 个 props 雷同的子组件不会带来复用，只是更宽的 interface；先过删除测试：删掉它复杂度是集中还是只是搬家。
