# 实施计划：财务工作区（Issue #108）

验证命令（仓库根目录）：
- 后端：`uv run pytest server/tests/api/test_finance.py -v`、`uv run ruff check server/src`、`uv run mypy server/src`
- 前端：`cd web && pnpm test`、`pnpm lint`、`pnpm build`
- 全量回归（收尾）：`uv run pytest server/tests --cov=reven --cov-fail-under=80 -q`

## Phase A：后端 API（可独立合并，向后兼容）

- [ ] A1 扩展 `FinanceRepository.list`：`statuses`（IN 查询）、`month`（occurred_on 范围）、`category` 参数；`routes/finance.py` 解析 `status` 逗号分隔、`month`/`category` query 参数
  - 验证：新增测试「status 多值 / month / category 筛选」通过
- [ ] A2 `GET /summary` 增加可选 `month=YYYY-MM`：前三个现金字段按月过滤，待收付两字段保持全时段
  - 验证：新增测试「跨月数据只计入对应月份；不传 month 行为不变」通过；既有 `test_finance_summary_uses_strict_cash_statuses` 不破
- [ ] A3 新增 `POST /entries/{id}/confirm`：`FinanceEntryConfirm{occurred_on}`；404/409（`FINANCE_ENTRY_ALREADY_SETTLED`）/200 三分支；应收→已收、应付→已付、occurred_on 覆盖
  - 验证：新增测试「确认后状态与日期变更且计入对应月份汇总、重复确认 409、已收/已付/已记录 confirm 409、不存在 404」通过
- [ ] A4 `uv run pytest server/tests/api/test_finance.py -v` 全绿 + `ruff`/`mypy` 无新增告警
  - 回滚点：Phase A 单独 revert 不影响旧前端

## Phase B：前端基础设施

- [ ] B1 `web/src/components/ui/drawer.tsx`：包装 `@radix-ui/react-dialog`，右侧滑入面板（移动端全屏），overlay/ESC/焦点管理
- [ ] B2 `finance-api.ts`：Entry/Summary 类型、list（新参数）、confirm 调用；`finance-utils.ts`：formatMoney、Asia/Shanghai today/当月、pending 分组函数
  - 验证：`cd web && pnpm build`（tsc）通过

## Phase C：前端页面

- [ ] C1 `finance-layout.tsx` + `app.tsx` 路由：`/finance` → `/finance/overview` 重定向，三子路由挂 layout
- [ ] C2 `entry-form-drawer.tsx`：四 variant 字段映射、编辑模式、提交后 invalidate
- [ ] C3 `finance-overview-page.tsx`：本月三卡（标注周期）+ 逾期/近期到期摘要 + 跳 pending 对应 group
- [ ] C4 `finance-ledger-page.tsx`：月份/类型/分类/搜索筛选 + 双形态列表 + 编辑/删除
- [ ] C5 `finance-pending-page.tsx` + `confirm-settle-dialog.tsx`：方向切换、四分组、`?tab=&group=` URL 同步、确认收付全流程（409 提示）
  - 验证：`pnpm build` 通过；dev 服务器手工走查四流程（桌面 + 移动视口）

## Phase D：测试与收尾

- [ ] D1 前端测试：overview（卡片/周期/摘要/跳转）、ledger（筛选参数/列表口径）、pending（分组/确认流程/方向切换）、drawer（四入口字段与 payload 固定映射）；替换旧 `finance-page.test.tsx`
  - 验证：`pnpm test` 全绿
- [ ] D2 全量回归：`pnpm lint`、`uv run pytest server/tests --cov=reven --cov-fail-under=80 -q`
- [ ] D3 spec 更新（Phase 3.3）：`finance-summary-contract.md` 补 month 参数、confirm 状态机、新卡片 label 映射
- [ ] D4 发布前核查清单：线上 `SELECT count(*) FROM finance_entries WHERE status='已记录'`（AC9）；桌面+移动端四流程走查（AC10）

## 风险文件

- `web/src/app.tsx`（路由改动面小但影响全局导航）
- `server/src/reven/api/routes/finance.py` + `repository.py`（口径核心，改动必须配套口径回归测试）
- 旧 `finance-page.tsx`/`finance-page.test.tsx` 删除前确认无其他引用

## 实施顺序说明

A 先行（旧前端不受新参数影响）；B→C→D 顺序执行；每个 Phase 结束跑对应验证命令，全绿再进下一 Phase。
