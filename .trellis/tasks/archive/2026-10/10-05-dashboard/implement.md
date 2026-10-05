# 执行计划：工作台 Dashboard

## 顺序

1. **后端聚合端点**
   - [ ] `server/src/reven/api/schemas/dashboard.py`：响应模型
   - [ ] `server/src/reven/dashboard/__init__.py` + `service.py`：`DashboardService.build_summary()`，复用 Finance/Rss/Crm/Project Repository 与 Settings
   - [ ] `server/src/reven/api/routes/dashboard.py`：`GET /api/dashboard/summary`
   - [ ] `server/src/reven/app.py`：注册路由
   - [ ] `server/tests/`：聚合端点测试（空库、各模块有数据、逾期计算、missing providers 差集、COS 检查、无 RSS run 时 latest_run=null）
   - 验证：`uv run ruff check server && uv run ruff format --check server && uv run mypy server/src && TEST_DATABASE_URL=... uv run pytest server/tests -k dashboard`

2. **前端页面**
   - [ ] `web/src/features/dashboard/dashboard-api.ts`：类型 + 请求 + localStorage 常量
   - [ ] `dashboard-page.tsx` + 卡片组件（横幅、财务、RSS、CRM、项目）
   - [ ] `web/src/routes.tsx`：`/` 注册 + 导航首位 + `*` 重定向改 `/`
   - [ ] `dashboard-page.test.tsx`：渲染四卡、逾期红显、横幅关闭/复现、跳转链接
   - 验证：`pnpm test && pnpm build`

3. **端到端核对**
   - [ ] 本地起服务，打开 `/` 核对数字与各模块页一致、跳转可用、移动端宽度正常

## 验证命令汇总

```bash
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
TEST_DATABASE_URL=<TEST_DATABASE_URL> uv run pytest server/tests
pnpm test
pnpm build
```

## 回滚点

- 后端：删 `dashboard/` 包 + 路由/Schema + `app.py` 注册行
- 前端：删 `features/dashboard/` + 还原 `routes.tsx`
- 无迁移、无现有接口变更，回滚零残留

## Review Gates

- 2.1 完成后跑 trellis-check 全量检查（spec 合规 + 验收标准逐条核对）
