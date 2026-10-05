# Research: CRM 计划派生化触点清单（next_action / next_follow_up_on / set_as_current）

- Query: issue #201 P1「CRM 历史与计划派生化」全链路触点调研
- Scope: internal
- Date: 2026-10-05

说明：talents 域的 `next_action` / `next_due_on` 命中（models.py:67、schemas/talents.py、web talents/*）属于对比参考，本任务不改动。

## server 写路径

- `server/src/reven/crm/models.py:38` — `Customer.next_action` ORM 列（Text，可空）。
- `server/src/reven/crm/models.py:39` — `Customer.next_follow_up_on` ORM 列（Date，可空，`index=True`）。
- `server/src/reven/crm/models.py:87-88` — `FollowUp.next_action / next_follow_up_on` ORM 列（R3 改名 `next_due_on` 的目标）。
- `server/src/reven/crm/inputs.py:37-39` — `require_action_for_date()` 配对校验：有日期无行动抛 `InvalidActionPairError`（FollowUp 侧保留复用）。
- `server/src/reven/crm/inputs.py:49-50,52,54-57` — `CustomerCreate` 计划字段 + 空串归一 validator + model_validator 配对校验（R1 删除）。
- `server/src/reven/crm/inputs.py:67-68,70` — `CustomerUpdate` 计划字段（合并校验在 service._validate_plan）。
- `server/src/reven/crm/inputs.py:120-122,124,126-131` — `FollowUpCreate.next_action / next_follow_up_on / set_as_current`；双 validator：配对校验 + `set_as_current=True` 必须有 next_action（R2/R3）。
- `server/src/reven/crm/inputs.py:141-142,144` — `FollowUpUpdate` 计划字段（改名）。
- `server/src/reven/crm/service.py:31-36` — `update_customer`：`_validate_plan` + `_assign` 将计划字段落库（R1 后整段简化）。
- `server/src/reven/crm/service.py:66-76` — `create_follow_up`：`model_dump(exclude={"set_as_current"})`；**双写核心** `if payload.set_as_current: customer.next_action = ...; customer.next_follow_up_on = ...`（service.py:72-74，R2 删除）。
- `server/src/reven/crm/service.py:123-126` — `_validate_plan`：合并 payload 与当前值后跑 `require_action_for_date`（逻辑保留，字段名改）。
- `server/src/reven/crm/errors.py:16-17` — `InvalidActionPairError` 定义（保留）。
- `server/src/reven/agent/tools_crm_customers.py:91-92,102-103` — MCP `crm_customer_create` 计划参数及 Field description（LLM 可见契约，R1/R5 删除+引导话术）。
- `server/src/reven/agent/tools_crm_customers.py:118-120,127-130` — `crm_customer_update` 计划参数 + `clear_next_follow_up_on` 开关，走 `_collect_updates(date_key="next_follow_up_on")`。
- `server/src/reven/agent/tools_crm_follow_ups.py:57-62,65-76` — `crm_follow_up_create` 参数含 `set_as_current` 及其 description「同步为客户的当前跟进计划」。
- `server/src/reven/agent/tools_crm_follow_ups.py:82-83` — 返回文案「已同步为当前跟进计划：…」（随 set_as_current 删除）。
- `server/src/reven/agent/tools_crm_follow_ups.py:95-97,100-105` — `crm_follow_up_update` 参数 + `clear_next_follow_up_on`，`_collect_updates` 调用。
- `server/src/reven/agent/crm_tool_support.py:42-43,52` — `_FIELD_LABELS`：`next_action→下一步行动`、`next_follow_up_on→下次跟进日期`、`set_as_current`（校验报错文案用）。
- `server/src/reven/agent/crm_tool_support.py:61-76` — `_collect_updates`：`date_key: str = "next_follow_up_on"` 默认值 + 日期/clear 冲突 ToolError（两处调用点传了显式 date_key，默认值可随改名单列）。
- `server/src/reven/agent/crm_tool_support.py:123-124` — `_action_pair_error()` 文案「设置下次跟进日期时必须提供下一步行动（next_action）」。
- `server/src/reven/api/routes/crm.py:45` — REST 422 映射 `CRM_NEXT_ACTION_REQUIRED`「设置跟进日期时必须提供下一步行动」。
- `server/src/reven/api/routes/crm.py:70-98` — POST/PUT `/customers` 直接把 `CustomerCreate/CustomerUpdate` 传给 `CrmService`（extra=forbid，字段删除后旧入参自动 422）。

## server 读路径

- `server/src/reven/crm/repository.py:31-36` — `list_customers` 排序：`next_follow_up_on IS NULL` 最后、日期升序、`updated_at` 倒序、小写名。
- `server/src/reven/crm/repository.py:40-49` — `_filter_due`：overdue/today/upcoming/none 四档直接查 `Customer.next_follow_up_on` 列（R4 改派生子查询的核心点）。
- `server/src/reven/crm/repository.py:72-80` — `list_due_follow_ups`：`next_follow_up_on <= today` 升序 + limit；返回 `Customer` 行，调用方直读 ORM 属性。
- `server/src/reven/dashboard/service.py:53-59` — `CrmDueItemAggregate` dataclass 字段 `next_action / next_follow_up_on / overdue_days`。
- `server/src/reven/dashboard/service.py:155-173` — `_crm_summary`：复用 `list_due_follow_ups`，`(today - due_on).days` 算逾期天数。
- `server/src/reven/dashboard/service.py:175-178` — `_count_follow_ups`：**绕过 repository 直接查 `Customer.next_follow_up_on`** 计 overdue/today 数（派生化时易漏，且不能简单 join FollowUp，会重复计数）。
- `server/src/reven/api/routes/dashboard.py:43-55` — DashboardCrmSummary 序列化透传 due_items。
- `server/src/reven/api/schemas/dashboard.py:36-47` — `DashboardCrmDueItem` schema；docstring 写明 `overdue_days = (今日 - next_follow_up_on).days` 语义。
- `server/src/reven/api/schemas/crm.py:25-26` — `CustomerResponse.next_action / next_follow_up_on`（`from_attributes` 直接序列化 ORM；派生后路由层不能再裸返 ORM，见风险点 4）。
- `server/src/reven/api/schemas/crm.py:57-58` — `FollowUpResponse` 计划字段（改名 next_due_on）。
- `server/src/reven/api/routes/crm.py:29,55-67` — `DueFilter = Literal["overdue","today","upcoming","none"]` 经 `GET /api/crm/customers?due=` 暴露；today 取 `datetime.now(SHANGHAI).date()`。
- `server/src/reven/agent/tools_crm_customers.py:169-193` — MCP `list_due_follow_ups`：overdue+today 两组查询合并排序，文案「已逾期 N 天（原定 …）/ 今天到期 / 下一步：…」。
- `server/src/reven/agent/tools_crm_customers.py:196-202` — `_customer_line`：列表行「下次跟进：`_plan_text(...)`」。
- `server/src/reven/agent/tools_crm_customers.py:205-214` — `_customer_detail`：「当前跟进计划：…」文案。
- `server/src/reven/agent/tools_crm_follow_ups.py:136-142` — `_follow_up_line`：历史条目「下一步：…」文案。
- `server/src/reven/agent/crm_tool_support.py:97-100` — `_plan_text(next_action, next_follow_up_on)`：日期+行动拼接（保留，签名改名）。
- `server/src/reven/crm/follow_up_reminder.py` 完整行为（详见下方专节）。

## follow_up_reminder.py 行为

- 类 `CrmFollowUpReminder`（`server/src/reven/crm/follow_up_reminder.py:17`），`biz_key="crm:follow-up-daily"`、标题「CRM 待跟进提醒」，是 `DailyPushScene` 首个挂载场景。
- 挂载点：`server/src/reven/background.py:13,85` — `(CrmFollowUpReminder(),)` 注入 DailyPushScheduler；输出经 `reven.notify`（飞书 proactive notifier）推送，见 `server/tests/notify/test_scheduler_delivery.py`。
- `render(session, today)`（follow_up_reminder.py:24-41）：调 `CrmRepository.list_due_follow_ups(today, limit=21)`；空则返回 `None`（默认不骚扰）；超限截断为 20 条并追加「……更多请进 CRM 查看。」；头部「M月D日 · 共 N[+] 位客户待跟进（逾期 X 位）」。
- 逾期计数（follow_up_reminder.py:30-32）：`customer.next_follow_up_on < today` 的条数（直接读 Customer 列）。
- 单行渲染（follow_up_reminder.py:43-51）：`（未填跟进事项）` 兜底空 action；`逾期 N 天` / `今日到期` 徽标；格式 `{name} — {action}（{badge}）`。

## migration

- 写法约定（读自 0013/0020/0021）：
  - 手写 alembic（非 autogenerate）；文件头 docstring 含中文说明；`revision`/`down_revision` 为 `"NNNN_slug"` 字符串；`branch_labels = None`、`depends_on = None` 固定样板。
  - `upgrade()`/`downgrade()` 成对实现（0020 加列/drop 列镜像）；不可逆迁移 downgrade 直接 `raise RuntimeError` 并注明恢复方式（0021）。
  - 建表惯例：`op.create_table` + `sa.CheckConstraint`（中文枚举值约束）+ `op.create_index` + `op.execute("ALTER TABLE ... ENABLE ROW LEVEL SECURITY")`（0013、0015）。
- `server/migrations/versions/0013_crm.py:30-31` — `crm_customers.next_action / next_follow_up_on` 列创建处。
- `server/migrations/versions/0013_crm.py:38-41` — check 约束 `ck_crm_customers_follow_up_action`（`next_follow_up_on IS NULL OR (next_action IS NOT NULL AND btrim(next_action) <> '')`，R1 需 drop）。
- `server/migrations/versions/0013_crm.py:45` — 索引 `ix_crm_customers_next_follow_up_on`（随列删除）。
- `server/migrations/versions/0013_crm.py:87-88,95-98` — `crm_follow_ups` 计划列 + `ck_crm_follow_ups_follow_up_action`（R3 rename 后保留约束；PG rename column 会自动更新约束/索引表达式引用，约束名不变）。
- merge migration 约定：`0014_merge_crm_and_integration.py`、`0016_merge_talents_tencent.py` 均为 `down_revision = (tuple)` 的空 upgrade/downgrade。
- 当前 head 链：`0013_crm+0013_integration → 0014 merge → 0015_talents+0015_remove_tencent → 0016 merge → 0017 → … → 0021 → 0022 → 0023 → 0024_rss_resilience`（单一 head；编号 0009 缺号不影响链）。**下一个 migration 应为 `0025_<slug>`，`down_revision = "0024_rss_resilience"`**。
- 迁移测试（`server/tests/migrations/`）：
  - `conftest.py:24-38` — autouse fixture 每个用例独立建库 `reven_migration_<uuid>`；`TEST_DATABASE_URL` 未设置则跳过。
  - `test_rss_item_review_pushed_at_migration.py:34-50` — 典型模式：`command.upgrade` 到目标 → information_schema 断言 → `downgrade` 一版 → 断言消失 → 再 upgrade 恢复（finally 保证升到目标版）。
  - `test_metadata_contract.py:13-25` — 子进程跑 `alembic upgrade head` + `alembic check`，校验 ORM 元数据与库结构一致（改 ORM 不加 migration 会挂）。
  - `test_merge_heads_migration.py:18,45-49` — **硬编码 `FINAL_REVISION = "0024_rss_resilience"` 断言单 head**；新增 0025 后必须同步改此常量。

## web

- `web/src/features/crm/types.ts:15-16` — `Customer` 响应类型计划字段。
- `web/src/features/crm/types.ts:26-27` — `CustomerInput`（create/update 共用）计划字段。
- `web/src/features/crm/types.ts:68-69` — `FollowUp` 类型计划字段。
- `web/src/features/crm/types.ts:79-81` — `FollowUpInput` 含 `set_as_current?: boolean`。
- `web/src/features/crm/customer-form-model.ts:9-10,18-19,28-29,39-40,46` — 表单值类型/初始空串/编辑回填/提交序列化（emptyToNull）/前端配对校验「设置跟进日期时请填写下一步行动」。
- `web/src/features/crm/customer-form.tsx:76-99` — `CustomerActionFields`：新建/编辑客户表单中的「下一步行动 + 下次跟进日期」两个 Input（R5 整块删除）。
- `web/src/features/crm/customer-list.tsx:42-43` — 卡片视图展示 `next_action ?? "尚未安排下一步"` + `FollowUpState`。
- `web/src/features/crm/customer-list.tsx:58-60` — 表格视图「下一步行动」「跟进日期」两列。
- `web/src/features/crm/customer-list.tsx:109-117` — due 筛选下拉（已逾期/今天到期/未来/无计划），值进 `?due=` 查询参数。
- `web/src/features/crm/customer-list.tsx:140-146` — `FollowUpState({ dueOn })`：无计划/逾期（红）/今天/计划于；与 `todayInShanghai()` 字符串比较。
- `web/src/features/crm/customer-detail-page.tsx:102-103` — 详情页「下一步行动 / 下次跟进」两个展示块（R5 空态引导挂载点）。
- `web/src/features/crm/follow-ups-section.tsx:23-29` — 跟进草稿类型含 `set_as_current: boolean`，**新建默认 `set_as_current: true`**。
- `web/src/features/crm/follow-ups-section.tsx:106-107` — 跟进表单「约定的下一步」「下次跟进日期」字段。
- `web/src/features/crm/follow-ups-section.tsx:113` — checkbox「同步为客户当前下一步行动」（R2 删除）。
- `web/src/features/crm/follow-ups-section.tsx:130` — 历史条目展示「下一步：action · date」。
- `web/src/features/crm/follow-ups-section.tsx:158,162` — 编辑回填（`set_as_current: false`）与提交序列化。
- `web/src/features/crm/follow-ups-section.tsx:167-168` — 前端校验：有日期必须有行动；set_as_current 必须有行动。
- `web/src/features/crm/crm-api.ts:54-59,69-78` — `updateFollowUp` 经 `historicalFollowUpInput()` **剥离 `set_as_current`** 后 PUT（编辑历史不同步计划）。
- `web/src/features/dashboard/dashboard-api.ts:22-28` — `DashboardCrmDueItem` 类型含 `next_action / next_follow_up_on / overdue_days`。
- `web/src/features/dashboard/crm-due-card.tsx:43-58` — `DueItemRow`：`overdue_days > 0` 红显「逾期 N 天 · 」+ `item.next_follow_up_on`（55 行）。
- 对比参考（本任务不改）：`web/src/features/talents/interactions-section.tsx:25-30,90,112,175-184`、`web/src/features/talents/types.ts:56,65` — talents 侧 `next_action / next_due_on` 命名与表单/校验写法，是 CRM 改名后的对齐模板。

## 测试

server（pytest；MCP 测试断言返回中文文案，API 测试断言 JSON 字段）：

- `server/tests/api/test_crm.py:20-21,50-52` — 创建客户/跟进 payload 带计划字段 + `set_as_current`。
- `server/tests/api/test_crm.py:66-68,95,104-110` — due 过滤列表、422 配对校验（`{"name": ..., "next_follow_up_on": ...}` 无行动被拒）。
- `server/tests/api/test_crm.py:155-177` — set_as_current=True/False 与「更新历史不覆盖客户计划」行为断言（R2 后整组改写为派生语义）。
- `server/tests/api/test_crm.py:240` — `PUT {"next_action": null}` 用例。
- `server/tests/crm/test_service.py:119-133` — `update_customer` 计划字段合并/清空校验。
- `server/tests/crm/test_service.py:143-161` — `update_follow_up` 不回填客户的断言（派生化后转为「派生值随最新跟进变化」断言的正面用例）。
- `server/tests/crm/test_service.py:168-199` — `set_as_current=True/False` 行为（删除，换「删除最新跟进后计划回退」用例，design.md §6）。
- `server/tests/crm/test_follow_up_reminder.py:13-15,19-37,40-44,47-63` — reminder 三用例；fixture 直插 `Customer.next_action/next_follow_up_on`（派生化后改为创建 FollowUp）。
- `server/tests/agent/test_tools_crm.py:27-28,63-64,93,97` — MCP create/update customer 计划参数与 422 文案断言。
- `server/tests/agent/test_tools_crm.py:153-188` — follow_up CRUD + `set_as_current=True`，断言「已同步为当前跟进计划」出现在返回文本。
- `server/tests/agent/test_tools_crm.py:233-234` — `next_follow_up_on 与清除开关不能同时使用` ToolError 文案。
- `server/tests/agent/test_tools_crm.py:328-360` — `list_due_follow_ups` 文案断言：「共 2 个客户」「已逾期 2 天」「今天到期」、逾期排在今日前。
- `server/tests/api/test_dashboard.py:130-132,172-173,226-237` — dashboard due_items 字段断言 +「Top 5 复用 list_due_follow_ups：最逾期在前」语义。
- `server/tests/notify/test_scheduler_delivery.py:45` — 调度交付测试直插 `Customer(name=..., next_action=..., next_follow_up_on=today)`。
- `server/tests/agent/test_tools_crm.py` 断言风格：`pytest.raises(ToolError, match=...)` + 返回字符串 `in` 断言；fixture 直接调工具类方法。
- `server/tests/api/test_talents.py:39` — talents 侧 `next_action` 用法参考（不改）。

web（msw 拦截 `/api/...` + Testing Library + userEvent；捕获 request body 到局部变量后断言）：

- `web/src/features/crm/crm-page.test.tsx:28-29,87,109-110` — Customer fixture 带计划字段；61-76 断言 `searchParams.get("due") === "today"`。
- `web/src/features/crm/customer-detail-page.test.tsx:29-30,55-56` — customer/followUp fixture 计划字段。
- `web/src/features/crm/customer-detail-page.test.tsx:173-178` — 创建跟进断言 body `toMatchObject({ ..., set_as_current: true })`。
- `web/src/features/crm/customer-detail-page.test.tsx:190` — 更新跟进断言 `expect(updatedBody).not.toHaveProperty("set_as_current")`。
- `web/src/features/dashboard/dashboard-page.test.tsx:30-45` — dashboard fixture due_items 两条（逾期/今日）。
- 断言方式总结：`server.use(http.get/post/put(...))` 捕获 body → `toMatchObject` / `toHaveProperty` / `not.toHaveProperty`；UI 侧 `findByLabelText` / `getByRole` + `userEvent`，toast 用 `waitFor(() => expect(toast.success).toHaveBeenCalledWith(...))`（toast 已 mock）。

## talents 域到期语义参考（本任务不改）

- `server/src/reven/talents/repository.py:16-22` — `_earliest_due_subquery()`：`func.min(TalentInteraction.next_due_on)` 相关标量子查询（min 语义：旧计划永久冒泡，与 CRM 目标「最新一条」语义相反）。
- `server/src/reven/talents/repository.py:56-66` — `_filter_due`：overdue/today/upcoming/none 均基于 `earliest_due` 与 today 比较，none 时 `IS NULL`。
- `server/src/reven/talents/repository.py:77-87` — `list_interactions` 排序 `occurred_on desc, created_at desc, id desc` —— 正是 CRM 派生「最新一条」应采用的排序模板（design.md §2）。
- API 暴露：`server/src/reven/api/routes/talents.py:25,43-57` — `DueFilter` Literal + `GET /api/talents?due=` → `TalentsRepository.list_talents(due=..., today=datetime.now(SHANGHAI).date())`；CRM 路由（api/routes/crm.py:55-67）结构完全平行。
- 字段命名目标：`server/src/reven/api/schemas/talents.py:112,124,143` 与 `server/migrations/versions/0015_talents.py:64,78` 均用 `next_due_on`（CRM rename 对齐对象）。

## 风险点

1. **check 约束迁移细节**：`ck_crm_customers_follow_up_action` 随 drop column 需显式 `drop_constraint` 再 drop 列（或依赖 PG 级联，但显式更清晰）；`crm_follow_ups` rename 列时 PG 会自动更新 `ck_crm_follow_ups_follow_up_action` 表达式中的列引用、约束保留，downgrade 反向 rename 即可。
2. **dashboard 计数绕过 repository**：`dashboard/service.py:175-178` 直接查 `Customer.next_follow_up_on`；派生化后计数语义=「最新跟进到期日 < /= today 的客户数」，不能用 join FollowUp 直数（一个客户多条历史会重复计数），需基于派生子查询或 `list_due_follow_ups` 同源逻辑。
3. **`list_due_follow_ups` 返回形状**：现返回 `Customer` ORM 且三个调用方（dashboard/service.py:158、follow_up_reminder.py:25、MCP 经 list_customers 自组）都直读 `customer.next_*` 属性；派生后需返回携带派生计划的结构（如 tuple/DTO），三处同步改。
4. **CustomerResponse 裸返 ORM**：`api/routes/crm.py` 的 list/get/create/update 直接 `return Customer`，依赖 `from_attributes`；派生字段不在 ORM 上，需在响应组装层注入派生 `next_action / next_due_on`（或服务层返回 DTO），否则字段恒 null/缺省。
5. **MCP 参数描述即 LLM 契约**：`Field(description=...)`（tools_crm_customers.py:91-92、tools_crm_follow_ups.py:57-62）和工具 docstring 需同步 R5 引导话术「创建后可用 crm_follow_up_create 记录第一次跟进」。
6. **迁移测试常量硬编码**：`tests/migrations/test_merge_heads_migration.py:18` 的 `FINAL_REVISION = "0024_rss_resilience"` 在新增 0025 后必须更新，否则单 head 断言失败；另可仿照补一个 0025 的 upgrade/downgrade 回归测试。
7. **提醒/交付测试 fixture 直插 Customer 计划列**：`test_follow_up_reminder.py:14`、`test_scheduler_delivery.py:45` 派生化后必须改为「先建客户再建跟进」的两步 fixture。
8. **min vs 最新语义并存**：CRM 改「最新一条」后与 talents `_earliest_due_subquery`（min）语义分叉，两套 `_filter_due` 并存是已知 Non-Goal，但代码评审时易被误指为不一致——design.md §2 已记录取舍。
9. **web 同类型复用**：`CustomerInput` 同时服务 create/update；删除计划字段后 `customer-form-model.ts` 的校验函数只剩 notes 等，`validate` 返回值结构需检查调用点。`FollowUpState` 组件只依赖响应字段名，改名后跟随 types.ts 即可。
10. **无存量数据但仍需可 downgrade**：prd.md AC 要求 downgrade 可回退（rename 回退 + 重建列与约束），0025 不能照搬 0021 的 `raise RuntimeError` 模式。

## 实施建议顺序

1. **Migration 0025 + ORM**：新增 `server/migrations/versions/0025_crm_plan_derive.py`（drop `crm_customers.next_action/next_follow_up_on` + 约束 `ck_crm_customers_follow_up_action` + 索引；rename `crm_follow_ups.next_follow_up_on → next_due_on`），同步 `crm/models.py`；更新 `test_merge_heads_migration.py` 的 `FINAL_REVISION`，新增 0025 迁移回归测试（仿 0020 用例 + information_schema 断言约束/索引）。
2. **派生读模型进 `CrmRepository`**：新增「最新跟进」相关标量子查询（occurred_on desc, created_at desc, id desc，模板见 talents/repository.py:81-85），改造 `list_customers` 排序、`_filter_due`、`list_due_follow_ups` 返回形状；同步 `dashboard/service.py`（含 `_count_follow_ups`）与 `follow_up_reminder.py`。
3. **server 写路径**：`inputs.py` 删 Customer* 计划字段、删 `set_as_current`、FollowUp* 改名（`require_action_for_date` 保留）；`service.py` 删双写回写；`errors.py` 不动。
4. **API + MCP 适配**：`api/schemas/crm.py`（CustomerResponse 派生只读字段、FollowUpResponse 改名）、`api/routes/crm.py` 响应组装；`agent/tools_crm_*.py` + `crm_tool_support.py` 参数/文案/标签改名与 R5 引导话术。
5. **web 适配**：`types.ts` → `crm-api.ts`（删 historicalFollowUpInput 剥离逻辑）→ `customer-form*`（删计划字段）→ `customer-list/detail`（派生展示 + 空态引导）→ `follow-ups-section.tsx`（删 checkbox、改名）→ `dashboard-api.ts`/`crm-due-card.tsx`。
6. **测试重写**：server（api/agent/crm/notify/migrations，重点新增「删除最新跟进后计划回退」「记跟进后各读路径立即呈现」用例）→ web（fixture 与 body 断言同步，`not.toHaveProperty("set_as_current")` 可扩展为对 create 也断言）。
7. **spec 同步**：`.trellis/spec/reven-server/backend/crm-contract.md` 按新契约更新（主代理在 Phase 3.3 用 update-spec skill；该文件现有 151 行，§Signatures 与共享写入口清单都需改写）。

## Caveats / Not Found

- `server/src/reven/api/routes/` 中除 crm.py / dashboard.py 外无其他文件引用目标字段（已全量 grep 确认）。
- talents 侧 due 卡/提醒（如有）不在本任务范围，未深入。
- PG rename column 对 check 约束表达式的自动跟随行为为 PostgreSQL 既定语义，建议 0025 迁移回归测试里显式断言约束仍存在且配对校验生效（插入违例行应失败）。
