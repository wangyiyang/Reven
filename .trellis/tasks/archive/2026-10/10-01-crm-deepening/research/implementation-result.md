# CRM 实施结果

## 结论

CRM 客户跟进变更已经按批准的设计完成：六个输入模型与固定领域错误归属于 CRM module，九个写操作通过 input + ID 完成范围查找、校验与提交。REST / MCP 写 adapter 不再预查 ORM，读查询保持原用途。仅关联或解除跟进联系人的更新缺口已复现并修复。

本实现没有修改飞书、会话模型、数据库迁移、依赖或 uv.lock，没有提交或推送。spec 与任务规划由父会话维护，不在本代理的产品修改清单内。

## 修改文件

| 文件 | 改动 | 当前行数 / 最长函数跨度 |
| --- | --- | --- |
| `server/src/reven/crm/inputs.py` | 六个输入模型、原字段约束/空串归一/必填 null 校验；创建与合并更新共用行动日期配对校验 | 155 / 5 |
| `server/src/reven/crm/errors.py` | 客户、联系人、跟进缺失与行动日期配对的固定错误 | 17 / 0 |
| `server/src/reven/crm/service.py` | input + ID 完整写操作；私有 session/repository；保留一次提交与 ORM 返回 | 126 / 11 |
| `server/src/reven/api/schemas/crm.py` | 保留 Response，显式重导出原六个输入名称 | 60 / 0 |
| `server/src/reven/api/routes/crm.py` | 写路由直接调用业务操作；集中固定 HTTP 错误转换 | 202 / 12 |
| `server/src/reven/agent/tools_crm.py` | 显式装配三个真实 adapter，保留 15 个工具注册名称 | 30 / 20 |
| `server/src/reven/agent/tools_crm_customers.py` | 完整客户工具与原列表/详情/漏斗/到期读查询、中文展示 | 209 / 27 |
| `server/src/reven/agent/tools_crm_contacts.py` | 完整联系人工具与展示 | 125 / 29 |
| `server/src/reven/agent/tools_crm_follow_ups.py` | 完整跟进工具与展示；全部字段收集完成后拒绝空更新 | 134 / 38 |
| `server/src/reven/agent/crm_tool_support.py` | 真实共用的 MCP 参数、输入转换、中文校验与固定领域错误映射 | 124 / 16 |
| `server/tests/crm/test_service.py` | 直接业务 interface 的 PostgreSQL 行为：缺失/跨客户、失败不提交、partial/null/空串、单次提交、历史/当前计划、主联系人/快照 | 248 / 35 |
| `server/tests/api/test_crm.py` | 保留现有行为，增补写操作 404 JSON 与合并状态 422 JSON 的契约矩阵 | 243 / 33 |
| `server/tests/agent/test_tools_crm.py` | 原断言迁到三个真实 adapter；contact-only 两例、clear 冲突/空更新、真实 MCP contact-only 调用 | 466 / 41 |

## Deletion 与 locality

- 删除两个写 adapter 的“取实体 → 判断缺失 → 传 ORM”接线，完整变更知识集中到已有 CRM module。
- 删除公开 `CrmService.session` / `.repository` 以及原 dict / ORM 写签名，不保留兼容 facade。
- 删除网页 schema 所拥有的输入校验副本，六个名称通过显式重导出保持兼容；MCP 直接导入领域输入。
- 删除原聚合 `CrmTools`；三个 adapter 各自拥有完整输入、业务调用、中文输出，注册点明确装配。现有测试直接使用这三个真实 adapter，没有复制业务规则或新增聚合替身。
- 删除独立 `_valid_action_pair`，由同一输入校验函数检查创建与合并后的更新状态。
- 原日期、客户筛选、读查询、工具参数形状、中文消息、REST JSON 与现有高价值 adapter 断言均保留。

## 复现与验证

所有数据库 pytest 都通过父会话提供的保护 runner 注入专用测试库，没有打印数据库 URL。该库已由父会话迁移至 head，本代理没有访问其他数据库。

### 修复前复现

```sh
.venv/bin/python /Users/wangyiyang/.tmp/reven-architecture-test-run.py uv run --frozen pytest server/tests/agent/test_tools_crm.py -k contact_only -q
```

结果：**2 failed**。关联与解除两个参数化用例都在旧 `_collect_updates` 尚未收集 contact 字段时抛出“没有需要修改的字段”。

### 修复后针对性测试

```sh
.venv/bin/python /Users/wangyiyang/.tmp/reven-architecture-test-run.py uv run --frozen pytest server/tests/crm server/tests/api/test_crm.py server/tests/agent/test_tools_crm.py
```

结果：**58 passed in 10.34s，0 skipped**。修复前的两例通过；另外经 FastMCP Client 调用注册后的跟进更新，验证只传 contact_id 会返回原中文结果与联系人。

共享业务测试使用 SQLAlchemy `after_commit` 事件观察真实事务提交次数，证明创建历史与同步当前计划一次提交、主联系人切换一次提交、缺失/跨客户/非法合并输入不提交。刷新数据库记录验证失败无副作用和删除联系人保留快照。

### 外部契约一致性

在产品修改前后，经真实内存 FastMCP Client 读取完整 15 个工具模型，并使用挂载 CRM router 的 FastAPI 应用生成 OpenAPI。两者与修改前基线严格比较相等，覆盖名称、参数 schema、默认值、描述及 REST 输入/输出 schema。

基线保存在仓库外：`/Users/wangyiyang/.tmp/crm-contract-before.json`。

### 后端质量检查

```sh
uv run --frozen ruff check server
uv run --frozen ruff format --check server
uv run --frozen mypy server/src
```

- ruff：All checks passed。
- format：251 files already formatted。
- strict mypy：Success: no issues found in 130 source files。
- AST 与文件行数核对：本次生产文件最大 209 行、最长函数 38 行；本次测试文件最大 466 行、最长函数 41 行；全部满足文件 <=500 / 函数 <=50。

## 遗留与后续

- 无本项已知失败或未完成实现；等待父会话的独立 trellis-check 验收。
- ORM 返回继续遵循既有 `expire_on_commit=False`，没有支持额外 session 配置变体。
- 本项无数据库迁移、无依赖变更；内部 Python interface 已有意迁移，仓库外若直接引用旧 CrmTools / service ORM 签名需同步。
- 后续飞书交付与会话模型任务按原顺序执行，最终完整 server 测试由父会话统一安排。
