# Reven 深度 Dogfood 报告（2026-08-20）

> 触发：Boss 要求“暴力验证和测试”。范围：`https://dev.wangyiyang.cc` 当前 main（含 #54 UI polish）。  
> 方法：agent-browser 登录后造 `AITEST-` 数据，覆盖财务/项目/SOP 三个新模块的创建、展示、校验、删除与清理；同时检查 API 与 UI 能力是否一致。  
> 红线：未创建/重置凭证；未碰 Notion/GitHub/飞书外部写动作；所有 `AITEST-` 数据已清理，财务汇总已回到 0。

## 结论摘要

| 严重度 | 数量 | 核心问题 |
|---|---:|---|
| High | 3 | 财务录入后无法管理；删除无二次确认；校验缺口导致脏数据可入库 |
| Medium | 3 | 列表缺筛选/搜索/排序；链接字段不可点/不展示；只能增删不能改/看详情 |
| Low | 2 | 空日期输入对辅助技术暴露 0；财务默认类型/状态容易误录 |

最值得马上修：**财务记录无法删除/编辑**、**删除无确认**、**项目链接与 Playbook 内容校验**。

## 已验证正常的部分

- 造数后财务汇总能正确计算：收入 ¥16,300.50、花销 ¥2,799.00、净额 ¥13,501.50、应收 ¥3,500.00、应付 ¥800.00。
- 财务前端能拦截无效金额：输入 `-5` 后出现「请填写名称、有效金额和日期」，未入库。
- 项目/Playbook 列表能按创建时间倒序展示新数据；空状态已上线。
- 清理接口正常：`AITEST-` 财务 4 条、项目 2 条（另有 1 条已在 UI 删除）、Playbook 5 条全部 DELETE 204；最终剩余 0。
- 巡检过程中浏览器 console / errors 为空。

## 问题清单

### ISSUE-001 财务记录录入后无法管理（High / Functional）

- 页面：`/finance`
- 现象：UI 只有「添加记录」和只读表格；没有编辑、删除、筛选、搜索。后端却有 `PATCH/DELETE /api/finance/entries/{id}` 与 `kind/status` 查询能力。
- 证据：财务页 snapshot 中表格只有 日期/名称/类型/分类/状态/金额，无操作列；清理时只能用 API DELETE。
- 影响：录错一笔账，前端无法补救，违背 OPc「减少操作」原则。

### ISSUE-002 删除是单键即删，没有确认（High / UX Safety）

- 页面：`/projects`、`/playbooks`
- 现象：点击行内「删除」后立即删除，无 confirm、无 undo。已用 `AITEST-项目-暂停` 验证：点击后该行消失。
- 证据：`projects-delete-before.png` / `projects-delete-after.png`（临时证据目录 `/tmp/reven-dogfood-20260820/screenshots/`）。
- 影响：项目/SOP 这类知识资产，误触成本高。

### ISSUE-003 校验缺口会让脏数据入库（High / Data Quality）

- 页面/API：`/projects`、`/playbooks`
- 现象：
  - 项目 `github_repo="bad url"`、`notion_url="not a url"` 可创建成功（201）。
  - Playbook 只填标题、内容留空也可创建成功（`AITEST-空内容` 已入列表后再清理）。
- 影响：以后 AI 测试或自动化读这些字段时会拿到不可信数据；报表/跳转会踩雷。

### ISSUE-004 列表缺筛选/搜索/排序（Medium / UX Efficiency）

- 页面：`/finance`、`/projects`、`/playbooks`
- 现象： seeded 后只能看时间倒序列表；没有状态/类型/标签/分类筛选，没有搜索，没有排序。财务/Playbook API 已有部分过滤能力，UI 未接。
- 影响：数据量一上来，页面退化成“只能新增”的流水墙。

### ISSUE-005 链接字段收了但不好用（Medium / Functional UX）

- 页面：`/projects`
- 现象：表单收集了 `Notion URL`，列表却不展示；`GitHub` 只显示纯文本（例如 `wangyiyang/Reven`），不可点击；非法值也原样展示。
- 影响：项目台账无法一键跳到仓库/文档，等于少闭环。

### ISSUE-006 只能增删，不能改/看详情（Medium / Functional）

- 页面：`/finance`、`/projects`、`/playbooks`
- 现象：后端有 `PATCH`，前端没有编辑入口；Playbook 列表只 line-clamp 预览，无详情页/复制全文；财务连删除入口都没有。
- 影响：真实维护时会被迫回数据库/API，违背「Reven 是 system of record」。

### ISSUE-007 空日期输入对辅助技术暴露 0（Low / Accessibility）

- 页面：`/projects`
- 现象：空 date input 在 accessibility snapshot 中显示 年/月/日 spinbutton 值为 0；视觉上是占位，但读屏语义差。
- 影响：低，但 AI 测试快照会反复读到噪音。

### ISSUE-008 财务默认态容易误录（Low / UX）

- 页面：`/finance`
- 现象：新增表单默认「支出 / 已记录」。对一人公司高频记收入/应收时，默认支出容易造成错账；「已记录」语义也弱。
- 建议：默认状态按类型联动，或保留上次使用的类型/状态。

## 建议修复顺序

1. 先补安全与数据质量：删除确认 + Playbook 内容必填 + 项目链接格式校验。
2. 再补闭环：财务编辑/删除、项目/Playbook 编辑或详情抽屉。
3. 最后补效率：三模块统一列表工具条（搜索 + 状态/类型筛选 + 排序），链接字段全部可点。

## 清理确认

- 财务：剩余 `AITEST-` 0，summary 全 0。
- 项目：剩余 `AITEST-` 0。
- Playbook：剩余 `AITEST-` 0。
- 证据 JSON：`/tmp/reven-dogfood-20260820/cleanup.json`。
