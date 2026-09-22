# 架构深化批次：集成凭证 seam、注册表拆除、Settings 组合根、Web CRUD/路由收拢（GH #133-#137）

## Goal

落地 2026-09-21 架构评审产出的 5 个 GitHub Issue（#133-#137），把 server 与 web 侧的浅 module 集群深化为 deep module。每个 Issue 一个独立 feature 分支 + PR，逐批合并，测试全绿。

## Requirements

按依赖排序：R3 最小先行 → R1 是地基 → R2 依赖 R1；R4/R5 为 web 线，与 server 线互不依赖。

### R1 · server：IntegrationCredentials + ProviderClients（GH #133）

- 新增 `IntegrationCredentials` module：SecretBox 构造仅一处、`_secret_hint` 剥离、per-provider typed credentials、统一 log-and-degrade 策略
- interface 收敛为 `resolve(provider) -> TypedCredentials | None`；`agent/config.py` 的 `resolve_agent_config` 改为普通调用方
- 其上建 `ProviderClients`（lifespan 构建）：统一超时 / 错误映射 / httpx client 复用
- 删除 3 个 `Configured*` adapter（`rss/factory.py:80,195`、`notifications.py:27`）
- 语义保持：未配置 / 解密失败时优雅降级，错误码不变

### R2 · server：Settings 组合根（GH #135）

- `get_settings()` 仅在 `create_app` 调用一次；`app.state.settings` + `SettingsDep` + 构造函数注入
- 叶子模块（csrf 等）收标量构造参数
- 删除 `cache_clear()` ×3 与 autouse `_scrub_agent_env` fixture

### R3 · server：删除 connection-test 全局注册表（GH #134）

- `IntegrationService` 构造时显式传入 `{provider: adapter}` 映射，route 模块构建一次
- 删除：全局 `_CONNECTION_TEST_ADAPTERS` dict、全部 `register_*_adapter()`、`tests/api/conftest.py` 的 autouse 修复 fixture
- 新增 provider 只需在 dict 里加一行

### R4 · web：useResourceList + ResponsiveList（GH #136）

- `useResourceList<TEntity, TForm>`：入参 `{key, path, toPayload, toForm, filters}`，出参 `{itemsQuery, editing, deleting, form, submit, remove}`；seam 内拥有 query-key 纪律、乐观删除+回滚、toast 归一化、编辑表单态
- `ResponsiveList`：入参 `columns + card 投影`；seam 内拥有 `lg:hidden` / `hidden lg:block` 切分、空态、action 渲染、aria-label 对等
- 转换 projects / sops / talents / crm（+finance）页面；`rss-shared.tsx` 的 `ErrorPanel` 提升为公共组件
- 页面行为无回归

### R5 · web：routes.tsx + IntegrationCard 收拢（GH #137）

- `routes.tsx` 导出 `[{path, label, icon, element, children?}]`，App 与 AppShell 共同消费；折叠组开关按 group id keyed（终结 RSS 单例）
- IntegrationCard 从 10 props 收拢为 `{definition, controller}`；删除 `busyAction` 的 `${provider}:${action}` 字符串编码

## Constraints

- 每个 Issue 一个 feature 分支 + 一个 PR：GitHub Flow、原子提交、Conventional Commits
- 词汇与原则遵循 codebase-design：module / interface / seam / adapter / depth / leverage / locality；删除测试；一个 adapter 是假想 seam，两个才是真 seam
- 测试策略 replace-don't-layer：新测试打在深化后 module 的 interface 上，浅 module 旧测试删除，不做双层重复覆盖
- 语义保持：优雅降级、错误码、页面行为、API 契约不变
- 门禁：server = pytest 全绿 + ruff + mypy(strict)；web = vitest 全绿 + eslint + `tsc -b && vite build`

## Acceptance Criteria

- [ ] R3 / R1 / R2 / R4 / R5 各自 PR 合并，GH #133-#137 全部关闭
- [ ] `SecretBox.from_base64` 全仓仅 1 处构造；无 `register_*_adapter` 全局注册；`get_settings()` 仅组合根调用
- [ ] web：乐观删除回滚逻辑仅一份；`toast.error(error instanceof Error …)` 归一化仅在 seam 内；加页面 = 一处数组项；IntegrationCard 2 props
- [ ] server 与 web 全套质量门禁通过

## Notes

- 评审报告：本机 `/Users/wangyiyang/.tmp/architecture-review-20260921-214152.html`
- 证据数据已按 #128（移除 Notion/发布）后的代码树校准；S4（preparation_state）已随删除消解，S6 由 09-21-feishu-app-only 任务覆盖，W4 因 articles 删除按 YAGNI 不立项
- 与在途 `09-21-feishu-app-only` 相邻的代码（feishu_bot 凭证）实施前先对齐 main
