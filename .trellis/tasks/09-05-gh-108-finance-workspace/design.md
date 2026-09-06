# 技术设计：财务工作区（Issue #108）

## 1. 架构与边界

### 1.1 路由与导航

| URL | 页面 | 说明 |
|---|---|---|
| `/finance` | — | `<Navigate replace to="/finance/overview" />`，原入口继续有效（AC1） |
| `/finance/overview` | 财务概览 | 默认落地页 |
| `/finance/ledger` | 收支流水 | 仅已收/已付 |
| `/finance/pending?tab=&group=` | 待收待付 | tab=receivable\|payable；group=overdue\|upcoming\|later\|unscheduled（供概览跳入，AC3） |

- 三个子页面共享 `FinanceLayout`：标题、「记收入/记支出/新增待收/新增待付」四个动作按钮（桌面平铺、移动端 2×2 grid）、页内 tab 导航（NavLink，样式参照 app-shell 的 nav-link）。
- 侧边栏不动：`NavLink to="/finance"` 前缀匹配，子页面下保持 active。
- 流水页筛选（月份/类型/分类/搜索）放组件 state，不进 URL（无外部跳转需求，YAGNI）；pending 页 tab/group 进 URL search params（AC3 要求可直达筛选结果）。

### 1.2 前端文件结构（参照 crm feature 多文件模式）

```
web/src/features/finance/
  finance-api.ts              # 类型定义 + API 调用（参考 crm-api.ts）
  finance-utils.ts            # formatMoney、today()/本月（Asia/Shanghai）、待收付分组
  finance-layout.tsx          # 标题 + 动作按钮组 + tab 导航 + <Outlet/>
  finance-overview-page.tsx   # 概览
  finance-ledger-page.tsx     # 流水
  finance-pending-page.tsx    # 待收待付
  entry-form-drawer.tsx       # 新增/编辑抽屉（四个 variant 共用）
  confirm-settle-dialog.tsx   # 确认收付对话框
  *.test.tsx                  # 每页/每组件一个测试文件
web/src/components/ui/drawer.tsx  # 新增：基于 @radix-ui/react-dialog 的右侧滑入面板
```

- Drawer 复用已有依赖 `@radix-ui/react-dialog`（ConfirmDialog 同款），仅改 Content 定位：`fixed right-0 top-0 z-50 h-full w-full sm:max-w-md`，移动端全屏、桌面右侧抽屉；overlay/ESC/焦点管理由 radix 提供。
- 列表沿用现有双形态：桌面 `<Table>`（lg:block）+ 移动端卡片（lg:hidden）。

### 1.3 后端边界

改动集中在既有三层，无新模块、无新表、无迁移：

- `server/src/reven/api/routes/finance.py`：扩展 list 筛选参数、summary 增加 month、新增 confirm 路由（状态机校验在路由层，复用 repository.get/update）。
- `server/src/reven/api/schemas/finance.py`：新增 `FinanceEntryConfirm { occurred_on: date }`。
- `server/src/reven/finance/repository.py`：list 增加 statuses/month/category 条件；summary 增加可选月份范围。

## 2. 数据流与契约

### 2.1 状态机（业务动作 → kind/status 固定映射）

| 入口 | kind | status | occurred_on | due_on | source |
|---|---|---|---|---|---|
| 记收入 | income | 已收 | 表单：实际收付日期 | — | — |
| 记支出 | expense | 已付 | 表单：实际收付日期 | — | — |
| 新增待收 | income | 应收 | 创建当天（Asia/Shanghai） | 表单：预计收付日期 | 收付款对象 |
| 新增待付 | expense | 应付 | 创建当天（Asia/Shanghai） | 表单：预计收付日期 | 收付款对象 |
| 确认收款 | — | 应收→已收 | 覆盖为实际到账日期 | 保留（业务痕迹） | 保留 |
| 确认付款 | — | 应付→已付 | 覆盖为实际付款日期 | 保留 | 保留 |

- 待收付创建时 `occurred_on=创建当天`：pending 记录不展示 occurred_on、不进现金汇总，confirm 时覆盖；语义诚实且无副作用。
- 「已记录」：POST/PUT schema 保持兼容不收紧；新 UI 任何列表均不查询该状态（流水查 已收/已付，待收待付查 应收/应付），现金汇总口径不变（D1）。

### 2.2 API 变更（全部向后兼容）

**a) `GET /api/finance/entries` 新增可选参数**

| 参数 | 说明 |
|---|---|
| `status` | 精确匹配，逗号分隔多值（如 `已收,已付`），repository 转 IN 查询 |
| `month` | `YYYY-MM`，按 occurred_on 做 date 范围过滤（Date 列无时区，纯范围比较） |
| `category` | 精确匹配 |

排序不变（occurred_on desc, created_at desc）。

**b) `GET /api/finance/summary?month=YYYY-MM`（可选）**

- 不传：保持现有全时段五字段行为（现有测试不破）。
- 传：`income_cents/expense_cents/net_cents` 只统计该月；`receivable_cents/payable_cents` 仍为全时段存量（待收付是"当前欠多少"，无月份维度），响应 schema 不变。

**c) `POST /api/finance/entries/{id}/confirm`**（新增）

- body：`{occurred_on: date}`（pydantic 保证 422）。
- 404 `FINANCE_ENTRY_NOT_FOUND`；409 `FINANCE_ENTRY_ALREADY_SETTLED`（status 不在 {应收,应付}，含已收/已付/已记录）→ AC8：重复确认返回 409，数据不变。
- 成功：应收→已收 / 应付→已付，occurred_on 覆盖为实际日期，commit，返回 entry。
- 幂等性来源：确认只是单行 update，不产生新行；汇总由行状态计算，天然不会重复记账。双击/重试第二次得 409，前端 toast 提示。

### 2.3 前端数据获取

- 概览页：并行 `GET /summary?month=<本月>`（三卡）+ `GET /entries?status=应收,应付`（前端分组算逾期/近期到期摘要）。数据量为一人公司台账级，无需专用聚合 endpoint（KISS）。
- 流水页：`GET /entries?status=已收,已付&month=<选中月>[&kind][&category][&query]`。
- 待收待付页：`GET /entries?status=应收` 或 `应付`（按 tab），前端分组。
- 分组逻辑收在 `finance-utils.ts`，概览与 pending 页共用（DRY）：
  - 逾期 overdue：due_on < today；近期到期 upcoming：today ≤ due_on ≤ today+7；以后到期 later：due_on > today+7；日期未定 unscheduled：due_on 为空。
  - today 统一按 Asia/Shanghai 计算（`Intl.DateTimeFormat` timeZone）。
  - 组内排序：逾期/近期/以后按 due_on 升序；日期未定按 created_at 降序。
- `?group=` 存在时 pending 页只显示对应分组 + 顶部可清除的筛选提示；无则全分组展示。

### 2.4 表单与对话框

- `EntryFormDrawer` 四个 variant（income-settled / expense-settled / receivable / payable），字段按 §2.1 映射渲染；编辑模式按 entry 的 kind+status 推导 variant，提交 PUT。
- 分类沿用自由文本（可选）；收付款对象写入现有 `source` 字段，UI label 为「收付款对象」。
- `ConfirmSettleDialog`：展示名称+金额，日期输入默认 today，确认 → POST confirm；409 → toast「该款项已确认，请刷新查看」；其他失败 → toast 且原状态不变（R3.4）。
- 删除沿用现有 ConfirmDialog + DELETE。

## 3. 兼容性与迁移

- 无 DB 迁移、无 schema 变更；API 只加可选参数与新 endpoint，旧前端/旧调用不受影响。
- `/finance` 旧 URL 301 到概览；现有侧边栏入口无需修改。
- 现有后端测试 `test_finance_summary_uses_strict_cash_statuses` 等全部保持通过（口径回归）。
- 上线前核查（AC9）：`SELECT count(*) FROM finance_entries WHERE status='已记录'`；非 0 则人工处理后再发布。

## 4. 关键取舍

| 决策 | 选择 | 放弃的备选 |
|---|---|---|
| 导航形态 | 页内 tab + 独立 URL | 侧边栏二级菜单（RSS 模式）——三项高频平级，tab 更直接 |
| Drawer 实现 | 包装已有 radix-dialog | 引入新库——零新依赖 |
| 逾期/近期摘要 | 前端从 pending 列表分组计算 | 后端聚合 endpoint——数据量小，避免新增契约 |
| 已记录入口 | 不做（D1） | 待确认第三视图——数据前提不存在 |
| 状态机校验位置 | confirm 路由层 | domain 服务层——单行状态迁移，KISS |
| 流水筛选 URL 化 | 不做，组件 state | 全量 URL 同步——AC 无直达要求，YAGNI |

## 5. 回滚

- 后端先行合入也兼容旧前端（新参数可选、新 endpoint 独立）。
- 整体回滚 = revert 单个 PR，`/finance` 单页即刻恢复；无数据迁移需要回退。
