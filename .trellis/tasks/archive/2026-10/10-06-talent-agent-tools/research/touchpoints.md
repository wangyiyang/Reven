# Research: P3 MCP 工具面 + 枚举合并触点

- Query: issue #201 P3 — talents 域 MCP agent 工具全套（≈15 + talent_import_profile 批量）与两域方式枚举合并（电话/面谈/微信/邮件/其他）的全部代码触点与可照抄范式
- Scope: internal
- Date: 2026-10-06

## Findings

## 1. 注册与组装

| File Path | Description |
|---|---|
| `server/src/reven/agent/mcp_server.py:45-56` | `create_agent_mcp_server(session_factory, token, …)` 构建 `FastMCP("reven", auth=StaticTokenVerifier)`，依次调 `register_rss_tools` / `register_crm_tools`（:54-55）——新 `register_talents_tools` 挂这里 |
| `server/src/reven/agent/tools_crm.py:11-29` | 聚合层：`register_crm_tools(mcp, session_factory)` 实例化三个工具类并逐个 `mcp.tool(method, name="crm_*")` 显式命名注册（15 个工具） |
| `server/src/reven/agent/tools_crm_customers.py:30-32` | 工具类惯例：`__init__(self, session_factory)` 存工厂，方法内 `async with self._session_factory() as session` |
| `server/src/reven/app.py:91-101` | 装配：`_mount_agent_mcp` → `create_agent_mcp_app(factory, token, embedding_refresher=…)`；session_factory 来自 `_resolve_factory`（app.py:81-88） |
| `server/src/reven/agent/dsh.patch.yml:5-14` | dsh 侧只配 MCP server 通道（streamable-http + Bearer），**无工具白名单**——新工具经 MCP list_tools 自动对模型可见 |
| `server/src/reven/agent/dsh.patch.yml:38-44` | personaSuffix 目前只对 rss_keyword 工具写行为约束（CRM 工具 #169 上线时未加 prompt），P3 可选追加 talents 话术 |
| `.trellis/spec/reven-server/backend/agent-dsh-contract.md:10` | 模型侧工具名 = `mcp__<serverName>__<tool>`，即 `mcp__reven__talent_*` |

命名惯例（照 CRM）：聚合文件 `tools_talents.py`（`register_talents_tools`）+ 每实体一个 `tools_talents_<entity>.py`（`TalentsTalentTools`/`TalentsInteractionTools`/`TalentsExperienceTools`/`TalentsEducationTools`，或把 talent 本体 CRUD+import 放进聚合文件——CRM 是 customers 也有独立文件，建议保持一致用独立文件）。工具名建议 `talent_list/talent_get/talent_create/talent_update/talent_delete`、`talent_interaction_*`、`talent_experience_*`、`talent_education_*`、`talent_import_profile`（对齐 issue 给的名字）。

## 2. CRM 工具范式（P3 照抄对象）

全部集中在 `server/src/reven/agent/crm_tool_support.py` + 三个 `tools_crm_*.py`：

- **session 注入**：工具类构造收 `async_sessionmaker[AsyncSession]`，每个方法 `async with self._session_factory() as session` 自开自关（tools_crm_customers.py:49）。
- **参数 Annotated 别名**（crm_tool_support.py:18-36）：`CustomerIdParam = Annotated[UUID, Field(description="客户 ID（由 crm_customer_list / crm_customer_get 返回）")]`；枚举参数 `CustomerStatusParam = Annotated[CustomerStatus, Field(description="客户状态：潜在客户 / 跟进中 / …")]`（:21-24）、`FollowUpKindParam`（:25-28，文案含「会议（即拜访、面谈）」——枚举合并时要改）；筛选用 `DueFilterParam = Annotated[Literal["overdue","today","upcoming","none"], …]`（:29-32）；删除确认 `ConfirmCustomerNameParam`（:33-36）。
- **`_validate`**（crm_tool_support.py:78-93）：空 dict → `ToolError("没有需要修改的字段：请至少传入一个要更新的字段")`；`model_type.model_validate(values)` 的 `ValidationError` 逐条映射——`_FIELD_LABELS`（:37-52）把字段名翻成中文 label、剥掉 `"Value error, "` 前缀，`"；"`连接后抛 `ToolError("参数校验未通过——…")`。talents 版需自己的 `_FIELD_LABELS`（费率/院校/履历字段）。
- **`_collect_updates`**（crm_tool_support.py:60-75）：None=不修改；日期字段单独走 `date_value` + `clear_date` 开关（同时为真抛 ToolError），空串清理由 schema `_empty_to_none` 归一。
- **`_mutation_errors`**（crm_tool_support.py:126-137）：contextmanager，把域层 `CustomerNotFoundError/ContactNotFoundError/FollowUpNotFoundError/InvalidActionPairError` 映射为中文 ToolError。talents 对应物是 `TalentsService` 的 `InvalidRatePairError/InvalidDateRangeError`（talents/service.py:14-19）+ 仓库 get 返回 None 的自查（见 §4）。
- **delete 确认模式**：`_confirm_customer_name(session, customer_id, confirm)`（crm_tool_support.py:106-111）先查客户（不存在抛 not-found），`confirm != customer.name` 逐字不等抛 `ToolError("删除未执行：confirm_customer_name 与客户名称不完全一致，请先用 crm_customer_get 核对后重试")`；三个 delete 工具都先调它（tools_crm_customers.py:141-146、tools_crm_follow_ups.py:130-135、tools_crm_contacts.py 同构）。协议层 `confirm_customer_name` 为必填（test_tools_crm.py:473-479 断言 input_schema required）。talents 版应对齐为 `confirm_talent_name` 逐字确认人才名称。
- **日期参数**：`occurred_on: Annotated[date, Field(description="跟进发生日期，格式 YYYY-MM-DD")]`（tools_crm_follow_ups.py:51）；可空日期 `date | None = None`。
- **读写分层**：读路径直接用 `CrmRepository`（list/get），写路径走 `CrmService`（收 pydantic inputs，tools_crm_customers.py:107、tools_crm_follow_ups.py:77）。
- **中文文案风格**：列表 `"共 {n} 个客户："` + 编号行 `"1. 「名」（id=…，状态：…）｜来源：…"`（tools_crm_customers.py:58-60、193-200）；空列表给下一步引导（:57）；创建 `"已创建客户：…。可用 crm_follow_up_create …"`（:109）；删除 `"已删除客户「X」（id=…），其名下联系人与跟进记录已一并删除。"`（:146）；统计 `"线索漏斗（共 N 个客户）：潜在客户 1｜跟进中 2｜…"`（:163）。
- **not found 形状**：`ToolError(f"客户不存在（id={customer_id}），请先调用 crm_customer_list 确认可用的客户 ID")`（crm_tool_support.py:102-103）——错误文案里带下一步该调哪个工具。
- **时区**：`_today()` 用上海时区（crm_tool_support.py:55-57，注释指明 CI UTC 窗口防串天）。

## 3. 枚举合并触点（目标集合：电话/面谈/微信/邮件/其他）

### Server 定义与约束

| File Path | 现状 | 改法 |
|---|---|---|
| `server/src/reven/crm/models.py:22-27` | `FollowUpKind.MEETING = "会议"` | 值改 `"面谈"`（成员名是否改 MEETING→IN_PERSON 是风格决策，改成员名需同步全部引用） |
| `server/src/reven/talents/models.py:23-27` | `CALL = "电话语音"`，无 OTHER | `CALL = "电话"` + 增 `OTHER = "其他"` |
| `server/migrations/versions/0013_crm.py:91-94` | check `kind IN ('电话','会议','微信','邮件','其他')`，名 **`ck_crm_follow_ups_kind`**（表 `crm_follow_ups`） | 0027 改写（见下） |
| `server/migrations/versions/0015_talents.py:66-68` | check `channel IN ('面谈','电话语音','微信','邮件')`，名 **`ck_talent_interactions_channel`**（表 `talent_interactions`） | 0027 改写（见下） |
| `server/src/reven/agent/crm_tool_support.py:27` | FollowUpKindParam description 含「会议（即拜访、面谈）」 | 改「面谈」 |
| `server/src/reven/agent/tools_crm_follow_ups.py:60` | docstring「方式（会议=拜访/面谈）」 | 改「面谈」 |

**0027 migration 写法**（drop + add，先例：0025_crm_plan_derive.py:22 `op.drop_constraint(..., type_="check")`、0026_talent_profile.py:108；新链 `down_revision = "0026_talent_profile"`）：

```python
def upgrade() -> None:
    op.drop_constraint("ck_crm_follow_ups_kind", "crm_follow_ups", type_="check")
    op.create_check_constraint(
        "ck_crm_follow_ups_kind", "crm_follow_ups",
        "kind IN ('电话', '面谈', '微信', '邮件', '其他')",
    )
    op.drop_constraint("ck_talent_interactions_channel", "talent_interactions", type_="check")
    op.create_check_constraint(
        "ck_talent_interactions_channel", "talent_interactions",
        "channel IN ('电话', '面谈', '微信', '邮件', '其他')",
    )
# downgrade 反向各来一遍（恢复旧字面量）
```

模型列宽无忧：crm `kind String(24)`（models.py:82）、talents `channel String(16)`（talents/models.py:69）。issue 明确无存量数据、不做数据迁移（但若有旧值行存在，ADD CONSTRAINT 会失败——见风险点）。

### Server 测试触点（`会议` / `电话语音` 字面量）

- `server/tests/agent/test_tools_crm.py:42,175,182,198,217,433`（`kind="会议"` 及 `"会议跟进"` 断言）
- `server/tests/agent/test_tools_crm_delete_confirmation.py:60`
- `server/tests/crm/test_service.py:48,172,216`
- `server/tests/api/test_crm.py:45`
- `server/tests/api/test_talents.py:185`（`@pytest.mark.parametrize("channel", ["面谈","电话语音","微信","邮件"])` → 改为新集合 5 值）

### Web 触点

- `web/src/features/crm/types.ts:2` `FOLLOW_UP_KINDS = ["电话","会议","微信","邮件","其他"]` → `"会议"` 改 `"面谈"`
- `web/src/features/crm/follow-ups-section.tsx:28` 表单默认值 `kind: "会议"`；:95 select 渲染 FOLLOW_UP_KINDS
- `web/src/features/crm/customer-detail-page.test.tsx:52,258`（`kind: "会议"`、aria-label `"2026-08-20 会议 跟进记录"`）
- `web/src/features/talents/types.ts:2` `INTERACTION_CHANNELS = ["面谈","电话语音","微信","邮件"]` → `["电话","面谈","微信","邮件","其他"]`
- `web/src/features/talents/interactions-section.tsx:85` select 渲染 INTERACTION_CHANNELS（无硬编码值）
- talents web 测试只用 `"微信"`（talent-detail-page.test.tsx:47,265,294），不受枚举合并影响

### Spec 触点

- `.trellis/spec/reven-server/backend/crm-contract.md:80`「Follow-up kinds are exactly `电话`, `会议`, `微信`, `邮件`, and `其他`」
- `.trellis/spec/reven-server/backend/talents-contract.md:52-53`「Interaction channels are exactly `面谈`, `电话语音`, `微信`, and `邮件`」（:102 的 422 行也提 channel）
- `.trellis/tasks/archive/**` 的旧 PRD/design 有出现但归档不改

## 4. talents 写路径与校验层落位

- **`TalentsService` 写入口全部吃 `values: dict[str, object]`**：`create_talent(values)`（talents/service.py:27）、`update_talent(talent, values)`（:32，内含 rate-pair 不变量 :33-36）、`delete_talent(talent)`（:41）、`create_interaction(talent, values)`（:45，bump talent.updated_at :47）、`update/delete_interaction`（:51-65）、`create/update/delete_experience`（:69-86）、`create/update/delete_education`（:88-105）；update_experience/education 在 service 判 PATCH 合并后的日期区间（:117-122 `_validate_date_range`）。**注意与 CRM 不同：talents 的 update/delete 收的是已加载的 model 实例而不是 id**——MCP 工具要先用 `TalentsRepository.get_talent/get_interaction/get_experience/get_education`（talents/repository.py:74,95,118,144）自查 not-found。
- **校验现状在 API 层**：`server/src/reven/api/schemas/talents.py`（TalentCreate:69-95 含 rate-pair model_validator；TalentUpdate:98-126；Interaction:152-178；Experience:194-227 含 `_require_date_range`；Education:244-277）；routes 用 `payload.model_dump()` / `model_dump(exclude_unset=True)` 喂 service（api/routes/talents.py:94,112,148,160,198,212,252,266），service 抛的 `InvalidRatePairError/InvalidDateRangeError` 在 routes 映射 422（:111-114,211-214,265-268）。
- **CRM 先例的依赖方向**：域层 `reven/crm/inputs.py` 持全部校验模型 → `api/schemas/crm.py:8-13` 原样重导出（`from reven.crm.inputs import CustomerCreate as CustomerCreate`）→ MCP 工具 `from reven.crm.inputs import …`（tools_crm_customers.py:23）。**agent 层对 api 层零依赖**：`server/src/reven/agent/` 下 grep `from reven.api` 无任何匹配。
- **建议**：P3 把 talents 的 8 个 Create/Update 模型 + 辅助函数（`_empty_to_none`、`_validate_email`、`_normalize_string_list`、`_require_rate_pair`、`_require_date_range`、`_reject_explicit_null`）抽到 `server/src/reven/talents/inputs.py`；`api/schemas/talents.py` 照 crm.py 改为重导出 + 保留 Response 模型；MCP 工具只 import `reven.talents.inputs`。不要让 agent 层 import api 层（打破既定分层，且 api/schemas 的 Response 模型对 MCP 无用）。
- 次要不一致：CRM 域错误集中在 `reven/crm/errors.py`（service 抛、support 捕），talents 的两个错误类直接定义在 `talents/service.py:14-19`；P3 可顺手移到 `talents/errors.py` 对齐 CRM，也可就地 import——非阻塞。

## 5. 批量导入工具设计输入（`talent_import_profile`）

- **入参形状**（镜像 P2 schema）：画像字段 = `TalentCreate` 全集（api/schemas/talents.py:69-95：name 必填 + organization/tags/phone/email/wechat/preferences/capability/engagement_terms/availability/rate_amount+rate_unit 配对/rating 1-5/status/notes）；`experiences` 列表项 = `TalentExperienceCreate`（:194-208：company/title 必填、description、start_on、end_on 可空=至今）；`educations` 列表项 = `TalentEducationCreate`（:244-258：school 必填、degree/major、start_on、end_on）。date 参数照 CRM 惯例 description 标 `YYYY-MM-DD`。
- **事务性**：`TalentsRepository.add_talent/add_experience/add_education` 只 `flush` 不 commit（talents/repository.py:77-81,126-130,152-156）；`TalentsService` 每个公开方法各自 commit（service.py:107-109 `_commit_and_refresh`）。**全回滚最稳做法**：单个 session 内先用 pydantic 把画像+全部条目校验完（逐条 `_validate`，失败文案带序号，如「第 2 条履历：结束日期不能早于开始日期」——此时零 DB 写入），再用 repository 连续 add（flush），最后一次 `session.commit()`；任何异常 → `async with` 退出时 session 关闭即回滚。建议新增 `TalentsService.import_profile(...)`（或同类方法）承载这个多步单 commit，而不是在 MCP 工具里拼 repository——与「写路径走 service」的 CRM 惯例一致。
- **updated_at 语义**：履历/院校写操作不 bump talent.updated_at（service.py:67 注释，与 CRM 一致）；批量导入时 talent 是新建，无此问题。
- **返回文案**（对齐 CRM 计数风格）：`"已导入人才「X」（id=…）：画像已创建，写入履历 N 条、院校 M 条。"`；tags/preferences 经 `_normalize_string_list` 保序去重（schemas/talents.py:38-50），若有去重可附注「preferences 去重后 K 项」；后续引导语（如「可用 talent_interaction_create 记录第一次接洽」）对齐 `create_customer` 的引导风格（tools_crm_customers.py:109）。

## 6. tool-contracts spec

- `.trellis/spec/tool-contracts/backend/` 是**未填充模板**：`index.md:17-21` 五个文件状态全标 "To fill"；`error-handling.md`、`directory-structure.md` 正文均为 "(To be filled by the team)" 占位。它是通用 backend 指南脚手架，**不是 MCP 工具层的实际 spec**，P3 无强制更新义务（可选填）。
- 实际承载 MCP/工具约定的是 `.trellis/spec/reven-server/backend/agent-dsh-contract.md`（模块契约 :20 mcp_server、:23 tools_rss 写路径约定）——P3 完成后若有新惯例（如批量工具事务模式）可在该文件「模块契约」节加一行 `agent/tools_talents.py`。
- **必须更新的 spec**：`crm-contract.md:80` 与 `talents-contract.md:52-53` 的枚举字面量列表（随枚举合并改动）。

## 7. 测试范式

- `server/tests/agent/test_tools_crm.py`（497 行）：绝大多数用例**直接调工具类方法**（不走协议），如 `await customers.create_customer(name=…)` 后用中文子串断言（:29-38）；错误用 `pytest.raises(ToolError, match="客户不存在")`（:63-64,111-119）；枚举参数直接传中文字符串 + `# type: ignore[arg-type]`（:42,175）；`@pytest.mark.anyio` 标记（:19）。
- **协议面单测**：`test_tools_are_callable_over_mcp_protocol`（test_tools_crm.py:448-497）——`create_agent_mcp_server(session_factory, token="test-token")` + `fastmcp.Client`，断言 `crm_*` 工具名集合精确相等、三个 delete 工具的 `confirm_customer_name` 在 input_schema required 里、`call_tool` 返回 `TextContent`。
- **共享 fixture**：`server/tests/crm_tools_support.py`——`session_factory` fixture 要求 `TEST_DATABASE_URL`（缺则 skip；conftest.py `pytest_sessionstart` 在 CI 强制要求），开工前 `TRUNCATE crm_follow_ups, crm_contacts, crm_customers RESTART IDENTITY CASCADE`（:27），`_today()` 与实现同一上海时钟（:15-17），`_create_customer` 快捷建实体（:33-37），`_extract_id` 从返回文案解析 `id=` 后 UUID（:40-46）。
- **删除确认单独成文**：`test_tools_crm_delete_confirmation.py`（#176）——逐字不等拒绝 + 记录仍在 + 正确名称成功的三段式（:14-28）。
- **新增 `test_tools_talents.py` 照抄要点**：① 新 `tests/talents_tools_support.py`（TRUNCATE `talents RESTART IDENTITY CASCADE` 即可级联清四个子表，或显式列出）；② 每实体一组 CRUD roundtrip + 筛选（talent list 的 status/due/query/tag 对齐 `TalentsRepository.list_talents` repository.py:35-59）；③ 校验错误文案断言（「费率金额与单位必须同时填写或同时留空」「结束日期不能早于开始日期」「参数校验未通过」）；④ not-found 断言（人才/跟进/履历/院校四类）；⑤ `confirm_talent_name` 三段式删除确认；⑥ 协议面断言 `talent_*` 工具名全集（18 个）+ import 工具 Smoke；⑦ 批量导入：全成功计数文案 + 第 K 条校验失败全回滚（导入后列表应为空）。

## 实施建议顺序

1. **枚举合并先行**（阻塞工具文案与 web）：改 `crm/models.py` + `talents/models.py` 枚举值 → migration 0027 drop+add 两个 check 约束 → server/web 全部字面量触点（§3 表格）→ 更新 crm-contract.md:80 / talents-contract.md:52-53。此步独立可验（现有测试改字面量后转绿）。
2. **校验层抽离**（纯重构）：新建 `reven/talents/inputs.py`，`api/schemas/talents.py` 改重导出；现有 API 测试不动应全绿。
3. **MCP 工具面**：`talents_tool_support.py`（复刻 crm_tool_support：Annotated 别名、`_validate`/`_collect_updates`/`_mutation_errors`/`confirm_talent_name`、talents 版 `_FIELD_LABELS`）→ 四个 `tools_talents_*.py` → `tools_talents.py` 聚合 → `mcp_server.py:55` 后挂 `register_talents_tools`。
4. **`talent_import_profile`**：`TalentsService` 加单事务批量方法 + 工具包装（设计见 §5）。
5. **测试**：`tests/talents_tools_support.py` + `test_tools_talents.py`（+ 可选 delete_confirmation 拆分文件），协议测试断言工具全集。
6. **spec 收尾**：agent-dsh-contract.md 模块契约补一行；可选填 tool-contracts 模板。

## 风险点

- **嵌套列表参数无先例**：CRM 工具全是扁平标量参数；`talent_import_profile` 的 `experiences: list[...]`/`educations: list[...]` 是首个嵌套参数，需先验证 fastmcp 对 `list[pydantic模型]` 的 JSON Schema 生成与模型侧传参表现，fallback 方案是收 JSON 字符串或 `list[dict]` 后 `_validate` 逐条校验。这是本 P3 最大设计不确定点，建议最先 spike。
- **旧值数据违反新约束**：issue 声明无存量数据故不做数据迁移；但若任何环境已有 `会议`/`电话语音` 行，0027 的 ADD CONSTRAINT 会直接失败——升级脚本假设空表/仅新值，部署前需确认目标库状态。
- **枚举成员名 vs 值**：只改值（`MEETING = "面谈"`）diff 最小但成员名误导；改成员名（如 `IN_PERSON`）需同步 crm/inputs.py、agent 工具、测试全部引用。建议成员名语义化，趁 P3 一并改。
- **`confirm_talent_name` 文案与参数名**：CRM 参数叫 `confirm_customer_name`（语义=所属客户名称）；talents 删除人才/跟进/履历/院校时应统一为人才名称确认，参数命名保持域内一致（`confirm_talent_name`），协议测试照 CRM 断言 required。
- ** talents update 语义差异**：`TalentsService.update_*` 收 model 实例而非 id，且 interaction 的 update/delete 路由本就不嵌套 talent_id（api/routes/talents.py:151,163，按 interaction_id 直查）；MCP 工具设计参数时要决定是否要求传 talent_id 做归属校验（CRM follow_up 工具要求 customer_id + follow_up_id 双参防串户——建议 talents 对齐 CRM 双参，用 `get_experience(talent_id, experience_id)` 这类带归属的查询，repository 已支持）。
- **`_FIELD_LABELS` 覆盖度**：talents 字段多（rate_amount/rate_unit/start_on/end_on/…），漏配 label 会把原始字段名泄给模型；测试应覆盖主要校验失败文案。
- **测试时钟**：due 筛选断言必须用上海时区 `_today()`（crm_tools_support.py:15-17 注释记录了 CI UTC 16:00-24:00 串天事故），talents support 文件直接复刻。

### Files Found（总表）

| File Path | Description |
|---|---|
| `server/src/reven/agent/mcp_server.py` | MCP server 构建与工具注册入口 |
| `server/src/reven/agent/tools_crm.py` | CRM 工具聚合注册层（照抄结构） |
| `server/src/reven/agent/crm_tool_support.py` | 参数别名/_validate/_collect_updates/_mutation_errors/删除确认（照抄实现） |
| `server/src/reven/agent/tools_crm_customers.py` / `tools_crm_contacts.py` / `tools_crm_follow_ups.py` | 三个实体工具类（照抄实现） |
| `server/src/reven/crm/inputs.py` | 域层校验模型先例（talents 应对齐抽离） |
| `server/src/reven/crm/service.py` / `crm/errors.py` | 域服务/错误模块先例 |
| `server/src/reven/talents/service.py` / `repository.py` / `models.py` | talents 写入口（values dict）、查询、枚举定义 |
| `server/src/reven/api/schemas/talents.py` / `api/schemas/crm.py` | talents 校验现址 / CRM 重导出先例 |
| `server/src/reven/api/routes/talents.py` | talents REST 路由（model_dump 喂 service 的形状） |
| `server/migrations/versions/0013_crm.py` / `0015_talents.py` / `0025_crm_plan_derive.py` / `0026_talent_profile.py` | 两处 check 约束字面量与 drop_constraint 先例 |
| `server/tests/agent/test_tools_crm.py` / `test_tools_crm_delete_confirmation.py` / `server/tests/crm_tools_support.py` | 测试范式与共享 fixture |
| `web/src/features/crm/types.ts` / `follow-ups-section.tsx` / `customer-detail-page.test.tsx` / `web/src/features/talents/types.ts` / `interactions-section.tsx` | web 枚举数组与表单触点 |
| `.trellis/spec/reven-server/backend/agent-dsh-contract.md` / `crm-contract.md` / `talents-contract.md` | 实际 spec（tool-contracts/ 目录为未填充模板） |
