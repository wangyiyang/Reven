# 执行计划：talents agent 工具全套与方式枚举统一（#201 P3）

按序执行；每步完成跑对应验证。契约见 design.md，触点/范式细节见 research/touchpoints.md（实施前必读）。

## 已锁定的补充决策

- 枚举成员名语义化：CRM `FollowUpKind.MEETING = "会议"` → `IN_PERSON = "面谈"`（同步全部引用）；talents `CALL = "电话"`（成员名不动）+ 增 `OTHER = "其他"`。
- MCP 的 interaction/experience/education 更新与删除均要求 `talent_id + 子项 id` 双参归属校验（对齐 CRM 防串户；repository 已有 scoped 查询），与 REST 的扁平形状刻意不同。
- `talent_import_profile` 的 `experiences/educations` 嵌套参数**先 spike**：验证 fastmcp 对 `list[pydantic 模型]` 的 schema 生成与调用链；不通则 fallback 为 `list[dict]` 后逐条 `_validate`。
- talents 错误类顺手移到 `server/src/reven/talents/errors.py`（对齐 CRM 结构）。

## 环境

- `export TEST_DATABASE_URL=postgresql+asyncpg://reven_test:reven_test@127.0.0.1:55432/reven_test`
- server：`uv run pytest server/tests`、`uv run mypy server/src`、`uv run ruff check server`、`uv run ruff format server`
- web：`pnpm --filter @reven/web exec vitest run`、`pnpm --filter @reven/web lint`、`pnpm --filter @reven/web exec tsc -b`

## Step 1 — 枚举合并（阻塞后续文案）

- [ ] `crm/models.py` FollowUpKind → `电话(IN_PERSON? 按现成员名调整)/面谈/微信/邮件/其他`：`MEETING="会议"` → `IN_PERSON="面谈"`；`talents/models.py`：`CALL="电话"`、增 `OTHER="其他"`。同步 crm/inputs.py 等全部引用。
- [ ] migration `0027_unify_follow_up_channel.py`（`down_revision = "0026_talent_profile"`）：drop+add `ck_crm_follow_ups_kind` 与 `ck_talent_interactions_channel`（新集合字面量，写法见 touchpoints §3 代码块）；downgrade 恢复旧字面量；docstring 注明「假设无旧值数据」。
- [ ] 字面量触点全改（touchpoints §3 表）：`crm_tool_support.py:27`、`tools_crm_follow_ups.py:60`、server 测试（test_tools_crm*.py、test_service.py、test_crm.py、test_talents.py:parametrize）、web `types.ts`×2、`follow-ups-section.tsx:28` 默认值、web 测试 fixture。
- [ ] `tests/migrations/test_merge_heads_migration.py` FINAL_REVISION → 0027；新增 0027 迁移回归（旧值「会议」插入被拒、新值「面谈」通过、双向）。
- [ ] 验证：`uv run pytest server/tests/migrations -x && uv run pytest server/tests/api -x`

## Step 2 — 校验层抽离（纯重构，行为零变化）

- [ ] 新建 `server/src/reven/talents/inputs.py`：8 个 Create/Update 模型 + 辅助函数原样平移（touchpoints §4 清单）；`api/schemas/talents.py` 改重导出 + 保留 Response（对齐 `api/schemas/crm.py:8-13`）。
- [ ] `talents/errors.py` 新建，`InvalidRatePairError/InvalidDateRangeError` 迁入，service/routes 改 import。
- [ ] 验证：`uv run pytest server/tests/api/test_talents.py -x`（不改测试应全绿）+ `uv run mypy server/src`

## Step 3 — MCP 工具面

- [ ] `server/src/reven/agent/talents_tool_support.py`：复刻 crm_tool_support——Annotated 别名（TalentIdParam、TalentStatusParam、InteractionChannelParam、ConfirmTalentNameParam）、`_validate` + talents 版 `_FIELD_LABELS`（覆盖 rate/start_on/end_on/experiences 等）、`_collect_updates`、`_mutation_errors`（映射 NotFound 自查与 InvalidRatePair/InvalidDateRange）、`_confirm_talent_name`。
- [ ] 四个工具类文件 + 聚合：`tools_talents_talents.py`（list/get/create/update/delete）、`tools_talents_interactions.py`、`tools_talents_experiences.py`、`tools_talents_educations.py`、`tools_talents.py`（register_talents_tools）；`mcp_server.py:55` 后挂载。
- [ ] 话术对齐 R4（next_due_on 自动生效、tags vs preferences、月精度补 01、delete 级联提示）；not-found 文案带下一步工具名。
- [ ] 验证：`uv run mypy server/src && uv run ruff check server`

## Step 4 — talent_import_profile

- [ ] spike 嵌套参数（见上决策）；`TalentsService.import_profile(...)`：全部 pydantic 校验（逐条带序号错误文案）→ 连续 add（flush）→ 单 commit；同名人才精确匹配（0→创建、1→更新画像+追加子表、≥2→ToolError 改用 talent_update）。
- [ ] 返回文案计数风格（touchpoints §5）+ 引导语。
- [ ] 验证：`uv run pytest server/tests/agent -x -k import`

## Step 5 — 测试

- [ ] `server/tests/talents_tools_support.py`（TRUNCATE talents CASCADE、上海时钟、快捷建实体、_extract_id）；`server/tests/agent/test_tools_talents.py`：四实体 CRUD roundtrip、筛选、校验文案、not-found、confirm_talent_name 三段式（可拆 delete_confirmation 文件）、协议面断言 18 个工具名全集 + delete 工具 confirm 参数 required、批量导入（全成功计数 + 第 K 条失败全回滚后列表为空）。
- [ ] 验证：全量门禁（Step 6）。

## Step 6 — 全量门禁

- [ ] `uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80`
- [ ] `uv run pytest server/tests/migrations`
- [ ] `uv run ruff check server && uv run ruff format --check server && uv run mypy server/src`
- [ ] `pnpm --filter @reven/web exec vitest run && pnpm --filter @reven/web lint && pnpm --filter @reven/web exec tsc -b`

## Step 7 — spec 同步（交还主代理 Phase 3.3）

- [ ] `crm-contract.md:80` 与 `talents-contract.md` 枚举字面量行更新；`agent-dsh-contract.md` 模块契约补 `agent/tools_talents*.py` 一行。implement 代理不改 spec。

## 回滚点

- Step 1 失败：删 0027 即可。全量回滚：revert + downgrade 0026。

## Review gates

- Step 1 全绿后再做工具面（文案依赖新枚举）。
- Step 2 纯重构不得改变任何 API 行为（测试不改为绿）。
- 越界禁令：不重构 interactions REST 扁平路由；不改 RSS 工具；不填 tool-contracts 模板（主代理决定）。
