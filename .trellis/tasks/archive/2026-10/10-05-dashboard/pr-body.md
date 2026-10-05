# 工作台 Dashboard 首页

## 目的

新增"工作台"首页（路由 `/`，导航第一项），聚合需要判断和处理的经营事项，回答"我现在该干什么"；取代 `/rss/candidates` 成为默认落地页。

## 背景

产品定位即"聚合需要判断和处理的经营事项"，但此前没有首页：通配符路由直接重定向到 `/rss/candidates`，等于默认"每天第一件事是审 RSS"。需求经 grilling 访谈三轮达成共识（定位：行动中枢为主、经营概览为辅；MVP 只读聚合卡片 + 跳转，不做图表/快捷操作/布局自定义），规划产物见 `.trellis/tasks/10-05-dashboard/`。

## 改动点

**后端：聚合端点 `GET /api/dashboard/summary`**

- 新增 `reven/dashboard/` 包（service 只做只读查询 + SQL 计数，8 条扁平查询无 N+1）+ 路由/Schema 薄层
- 财务：待收款总额/笔数，按 `due_on < 今日（Asia/Shanghai）` 计算逾期
- RSS：待审核候选数、已保存素材数、最近一次抓取运行状态
- CRM：逾期/今日待跟进数 + Top 5 清单，**复用 `CrmRepository.list_due_follow_ups`**（与飞书每日提醒同源）
- 项目：进行中计数 + Top 5（`due_on` 升序、NULL 排后）
- 集成：5 个 DB provider 差集（含 `secret_configured=false`）+ COS 环境变量齐备性检查

**前端：`web/src/features/dashboard/`**

- 集成缺失横幅（可关闭，关闭状态记 localStorage，新缺失项出现时复弹）
- 四张卡片：财务待收款、RSS 待审核（数字卡）；CRM 待跟进 Top 5、进行中项目 Top 5（清单卡）；逾期项 `--danger` 红显；整卡/清单项可跳转
- `/` 注册为导航第一项"工作台"，`*` 重定向改 `/`；登录回退与 logo 链接同步指向 `/`
- 移动端单列堆叠（财务 → RSS → CRM → 项目）

**规范沉淀**

- `formatMoney` 复用约定写入组件规范（金额格式化唯一真相源 `@/features/finance/finance-utils`）

## 影响与风险

- 纯新增：不新增表、不改任何现有接口行为；触碰的现有文件仅 `app.py` 路由注册、`routes.tsx`、登录回退、logo 链接及对应测试
- 行为变化：默认落地页、登录后回退、logo 链接三处从 `/rss/candidates` 改为 `/`
- 回滚 = 删路由注册 + 删新文件，无迁移零残留

## 验证

- `ruff check/format`、`mypy`：全绿
- 后端 pytest：**861 passed**（新增 9 个 dashboard 用例：空库、逾期口径、missing 差集、COS 检查、`latest_run=null` 等）
- 前端：**243 passed**（新增 7 个组件用例：四卡渲染、逾期红显、横幅关闭/复现、跳转链接）、`pnpm build` 成功
- uvicorn 真机冒烟：登录后 `GET /api/dashboard/summary` 返回完整契约 JSON
- 待人工验收：浏览器并排核对数字与移动端宽度
