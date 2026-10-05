# 设计：工作台 Dashboard

## 架构决策

**新增聚合端点而非前端并行拉取**：财务/CRM/项目的现有列表接口返回全量数组、无 count，前端为拿计数拉全量既是浪费又把逾期计算散到客户端。一个 `GET /api/dashboard/summary` 把计数收进 SQL，后续加卡片只改一处。

**CRM 清单复用 `CrmRepository.list_due_follow_ups`**：飞书每日提醒已在用同一方法，Dashboard 新写一套查询会导致两处口径漂移。

## 后端

### 模块落位

遵循现有模块结构，新建 `server/src/reven/dashboard/` 包：

- `dashboard/service.py` — `DashboardService`：编排各模块 Repository，组装聚合结果；`today` 统一按 Asia/Shanghai 取（与 `crm/repository.py` 的 `due` 过滤口径一致）
- `api/routes/dashboard.py` — 路由薄层，`GET /api/dashboard/summary`，挂进 `app.py` 路由注册区
- `api/schemas/dashboard.py` — 响应模型

聚合层只做"读 + 计数"，直接复用各模块 Repository/Model 查询，不新增表、不改任何现有接口。

### 响应契约

```json
{
  "finance": {
    "receivable_cents": 120000,
    "receivable_count": 3,
    "overdue_receivable_cents": 50000,
    "overdue_receivable_count": 1
  },
  "rss": {
    "candidate_count": 12,
    "saved_count": 34,
    "latest_run": {
      "status": "success",
      "failure_count": 0,
      "finished_at": "2026-10-05T06:00:00+00:00"
    }
  },
  "crm": {
    "overdue_count": 2,
    "today_count": 1,
    "due_items": [
      {
        "customer_id": "…",
        "name": "张三",
        "next_action": "…",
        "next_follow_up_on": "2026-10-02",
        "overdue_days": 3
      }
    ]
  },
  "projects": {
    "active_count": 4,
    "items": [
      { "id": "…", "name": "…", "due_on": "2026-10-20", "overdue": false }
    ]
  },
  "integrations": {
    "missing_providers": ["translate_baidu", "embedding"],
    "cos_configured": false
  }
}
```

字段规则：

- `finance`：`status='应收'` 且 `kind='income'` 的 sum/count；逾期 = 同一集合中 `due_on < today`
- `rss.latest_run`：无运行记录时为 `null`
- `crm.due_items`：Top 5，`list_due_follow_ups` 顺序（最逾期在前）；`overdue_days = (today - next_follow_up_on).days`，未到期为 0 或负数由前端按 `< 0` 判断与否均可——**约定后端直接给整数值，前端 `> 0` 即逾期红显**
- `projects.items`：`status='进行中'`，按 `due_on` 升序（NULL 排后），Top 5；`overdue = due_on < today`
- `integrations.missing_providers`：固定 5 provider 清单与 DB 行做差集；DB 行存在但 `secret_configured=false` 也算 missing；`cos_configured` 读 `Settings.cos_*` 四个值是否齐全

### 金额单位

沿用全站惯例：分（cents），前端格式化。

## 前端

### 落位

- `web/src/features/dashboard/`：`dashboard-api.ts`（类型 + `fetchDashboardSummary`）、`dashboard-page.tsx`（页面编排）、卡片组件（同目录拆分，单文件不超规范行数）、`dashboard-page.test.tsx`
- `web/src/routes.tsx`：`{ path: "/", label: "工作台", icon: LayoutDashboard, element: <DashboardPage /> }` 放导航数组首位；`*` 改为 `<Navigate replace to="/" />`

### 组件结构

```
DashboardPage
├── IntegrationMissingBanner   (missing_providers + cos_configured；可关闭)
├── FinanceReceivableCard      (数字卡 → /finance/pending)
├── RssCandidateCard           (数字卡 → /rss/candidates)
├── CrmDueCard                 (清单卡 → /crm；清单项 → /crm/customers/:id)
└── ActiveProjectCard          (清单卡 → /projects)
```

- 数据：单个 `useQuery(['dashboard','summary'])`；沿用 `apiRequest` + TanStack Query 约定
- 栅格：桌面 `md:grid-cols-2` 两行（数字卡行 + 清单卡行），移动单列；逾期数字用 `text-destructive`
- 横幅关闭：`localStorage["dashboard.missing-integrations.dismissed"] = JSON.stringify(缺失 key 数组)`；当前缺失集合 ⊄ 已关闭集合时重新显示
- 加载/失败：卡片骨架或 `--`，遵循现有页面惯例（参考 finance-overview-page）

### 样式约束

遵循 `.trellis/spec/web/frontend/component-guidelines.md` 与现有卡片用法（shadcn/ui Card），不引入新依赖。

## 兼容与回滚

- 纯新增：新路由、新前端页面、新后端包；仅 `app.py` 注册一行与 `routes.tsx` 两处改动触碰现有文件
- 回滚 = 删路由注册 + 删新文件；无数据库迁移

## 风险

| 风险 | 缓解 |
|---|---|
| 项目 `status` 是自由字符串，"进行中"口径靠约定 | 聚合端点按字面值过滤，与前端表单默认值一致；契约文档化 |
| 横幅 localStorage 键值漂移 | key 与格式写在 dashboard-api.ts 常量，测试覆盖 |
