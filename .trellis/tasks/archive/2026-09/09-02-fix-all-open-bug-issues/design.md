# Design · 处理全部开放 Bug Issues

## Architecture and Boundaries

本任务不引入新模块；以 7 个 Issue 的最小责任边界修复现有行为：

1. **发布边界（#83）**：复用已经合入的镜像内 release infra 与部署脚本，只做证据验证和 Issue 收口。
2. **稿件查询边界（#100）**：分页有效性由文章列表页依据 URL 与 API 返回的 `total/page_size` 规范化；不改变服务端响应契约。
3. **CRM/人才展示边界（#101/#102）**：仅调整组件布局、换行策略、空态 DOM 和回归测试，不改 API 或数据模型。
4. **财务一致性边界（#103）**：删除改为服务端确认后再更新查询缓存，取消客户端假成功；后端 DELETE 契约保持 204/404。
5. **财务汇总边界（#104）**：repository 负责现金口径计算，API 字段结构保持兼容；前端负责使用明确卡名表达语义。
6. **主题与可访问性边界（#105）**：继续使用 Notion 蓝灰主题，通过全局语义 token 和共享按钮组件消除系统性对比度问题，不逐节点堆叠颜色补丁。

## Detailed Design

### #100 URL 规范化

- 初始 URL 中非整数、0、负数与 `readFilters` 的规范页不一致时，通过 `setSearchParams(..., { replace: true })` 改为 `page=1`。
- 查询成功后计算 `lastPage = max(1, ceil(total / page_size))`；当 `total > 0 && requestedPage > lastPage` 时 replace 为末页。
- 规范化保留 status/channel/query；重定向期间不展示普通“没有匹配稿件”空态，避免错误文案闪烁。

### #101 响应式布局

- 客户详情双列断点从 `xl` 后移到有足够内容宽度的断点，1280px 下让两个复杂卡片纵向排列。
- 日期字段设置合理最小列宽；邮箱从 `break-all` 改为按单词优先、必要时 anywhere。
- 复选框标签与主要联系人 badge 使用 `whitespace-nowrap`，内容容器保留 `min-w-0`。

### #102 空态与表单状态

- loading/error 保持表格外状态；空结果由移动列表和桌面 `TableBody` 各自渲染符合其语义的空态。
- 先写“添加标签 → 触发费率跨字段验证失败”的测试。当前父级 form state 理论上已保持标签；测试若通过则不制造额外状态层。

### #103 删除一致性

- 删除 mutation 移除 `onMutate` 乐观缓存写和回滚快照。
- DELETE 成功后失效 entries 与 summary，再关闭对话框并提示成功；失败只提示错误，现有缓存不变。
- 连续删除测试以 3 条服务端数组为真相，逐条确认 DELETE 请求与最终列表。

### #104 现金汇总

- `income_cents = sum(kind=income && status=已收)`。
- `expense_cents = sum(kind=expense && status=已付)`。
- `net_cents = income_cents - expense_cents`。
- `receivable_cents` 与 `payable_cents` 继续按应收/应付独立求和；`已记录` 不进入任何已支付汇总。
- API JSON 字段名不变，避免结构迁移；这是字段语义收紧，需要同步测试与页面卡名。

### #105 可访问性色彩

- 浅色：`--signal: #0B65A3`、`--muted: #6B6A67`、`--danger: #B42318`、`--on-signal/--on-danger: #FFFFFF`。
- 深色：`--signal: #6EB6E8`、`--muted: #A7A7A4`、`--danger: #FF7B72`、`--on-signal/--on-danger: #191919`。
- 默认按钮和登录按钮使用 `--on-signal`；danger hover 使用 `--on-danger`。disabled 控件保持现状（WCAG 对不可用控件豁免）。
- 将财务收入 badge 的固定 emerald 色改为可访问语义 token，避免主题外硬编码。
- 修正过期 Brand VI spec，使其反映 PR #40 与本次用户确认的 Notion 蓝灰基线。

## Compatibility and Migration

- 不新增数据库迁移，不改变 HTTP 路径或 JSON shape。
- #104 会改变 `income_cents/expense_cents/net_cents` 的统计语义；这是修复目标，现有 `已记录` 数据不会被猜测或批量改写。
- #100 使用 history replace，不增加浏览器返回栈条目。
- CSS token 是内部契约；所有现有 token 消费者自动获得新对比度。

## Rollback

- 每个实际改动 Issue 保持一个原子 Conventional Commit，可独立 revert。
- #104 可通过回退 repository 条件与前端卡名恢复旧口径，无数据损失。
- #105 只改 token/前景引用与规范，可单独回退，不影响业务数据。

## Risks

- #102 标签丢失可能在当前主干不可复现；以先写回归测试为准，禁止为假设根因引入状态重构。
- #103 从乐观删除改为确认后删除会让高延迟环境下行停留更久，但换取服务端一致性；pending 状态必须清晰。
- #105 全局 token 影响所有页面，必须用浅/深主题浏览器审计与全量测试兜底。
