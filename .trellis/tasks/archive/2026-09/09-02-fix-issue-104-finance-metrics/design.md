# Design · #104 财务现金口径

## Contract

保持 `/api/finance/summary` 的 JSON shape 不变，收紧字段语义：

- `income_cents`：仅 `kind=income,status=已收`。
- `expense_cents`：仅 `kind=expense,status=已付`。
- `net_cents`：上述两项之差。
- `receivable_cents`：`kind=income,status=应收`。
- `payable_cents`：`kind=expense,status=应付`。

`已记录` 不推断现金状态，不进入五项汇总。前端以“已收收入 / 已付花销 / 现金净额”显式表达前三项；页面副标题删除“跑道”。不迁移数据。

## Risk and Rollback

现有消费者若把 `income_cents` 当应计收入会观察到数值下降；仓库内唯一消费者为 finance 页面并会同步改名。回滚无需数据操作，只需恢复查询条件与卡名。
