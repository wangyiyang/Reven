# API 现状调查：Dashboard 数据源盘点

> 调查时间 2026-10-05，结论：后端无任何聚合端点；财务、RSS、CRM 底层件齐备可复用；COS 无配置状态接口。

## 总览

- 后端 grep `dashboard|aggregate|overview` 零命中；前端无首页，`*` 重定向 `/rss/candidates`（`web/src/routes.tsx`）
- 路由统一挂载 `server/src/reven/app.py:355-366`，前缀 `/api/<module>`

## 财务（/api/finance）

- `GET /api/finance/summary?month=YYYY-MM`（`api/routes/finance.py:96`）→ `{income_cents, expense_cents, net_cents, receivable_cents, payable_cents}`；汇总 SQL 在 `finance/repository.py:73-96`
- `GET /api/finance/entries?status=应收&kind=income` 返回完整数组（无分页/total）；状态机：`已记录/应收/应付/已收/已付`
- `FinanceEntry`（`finance/models.py:13`）：`kind / amount_cents / status / occurred_on / due_on`；**有 due_on 但无任何逾期计算逻辑**
- 缺口：待收款笔数、逾期应收（需在聚合端点用 SQL count/sum 实现，不拉全量数组）

## CRM（/api/crm）

- `Customer`：`status / next_action / next_follow_up_on`（Date 带索引）；`CustomerStatus`：潜在客户/跟进中/合作客户/暂停跟进/已流失（`crm/models.py:14,30-41`）
- `GET /api/crm/customers?due=overdue|today|upcoming|none`（`api/routes/crm.py:55`）现成支持待跟进过滤（`crm/repository.py:40-49`，Asia/Shanghai）
- **`CrmRepository.list_due_follow_ups(today, limit)`（`crm/repository.py:72`）已存在**：到期+逾期合并、最逾期在前，仅被飞书每日提醒 `crm/follow_up_reminder.py` 使用——Dashboard Top N 直接复用
- 缺口：无 count 接口、无 HTTP 路由暴露 list_due_follow_ups

## RSS（/api/rss）

- `RssItem.status`：`pending → candidate / filtered → saved / ignored`；`saved` 即素材库（`rss/review_service.py:38`）
- `GET /api/rss/candidates?status=candidate&page=1&page_size=30`（`api/routes/rss.py:46`）：唯一带 `{items,total,page,page_size}` 的接口；`status=saved` 同接口拿素材计数
- `GET /api/rss/runs/latest`（`api/routes/rss.py:38`）：最近抓取运行 `status / candidate_count / failure_count / notification_error / started_at / finished_at`

## 项目（/api/projects）

- `Project`：`name / goal / status`（自由字符串，默认"进行中"）`/ department / due_on / github_repo / notes`
- `GET /api/projects?status=…` 返回全量数组，无分页/total；逾期需按 `due_on` 自行计算

## 集成（/api/integrations）

- `GET /api/integrations`（`api/routes/integrations.py:154`）只返回 DB 已存在行：`{provider, public_config, secret_configured, secret_hint, connection_status, last_tested_at, last_error, ...}`
- 受支持 provider 固定 5 个：`feishu_bot / translate_baidu / translate_aliyun / embedding / agent-llm`（`integrations/providers.py:16`）；前端 `web/src/features/integrations/types.ts:66` 有静态清单，"缺哪个 = 哪个未配置"
- **COS 不在 integrations API 内**：走环境变量（`integrations/tencent_cos/configuration.py:26-38` 的 `Settings.cos_*`），无任何接口暴露配置状态——聚合端点需自行读 Settings
- `/api/system/status` 只回 `{database.available, rss_discovery 心跳}`

## 前端调用约定

- `web/src/lib/api.ts:17` `apiRequest<T>(path, init)`：fetch 封装，自动 CSRF 头、401 跳登录、`ApiError{status,code,message}`，路径不含 `/api`
- 数据获取一律 TanStack Query（`web/src/lib/query-client.ts`，staleTime 15s）
- 各 feature 自带 `<module>-api.ts`；Dashboard 沿用 `features/dashboard/dashboard-api.ts` + `useQuery`
- 无统一分页类型，仅 RSS 有 `{items,total,...}`
