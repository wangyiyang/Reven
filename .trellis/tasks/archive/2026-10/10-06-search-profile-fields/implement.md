# Implement: 搜索扩展到画像字段（#201 P4）

先读 `prd.md`、`design.md`（D1-D7 已锁定）、`research/touchpoints.md`（全部行号证据）。按 Step 顺序执行，每步跑受影响测试。Step 6（spec）由主代理负责，不要动 `.trellis/spec/` 与 `.trellis/tasks/`。

## Step 1 — escape_like 共享化

- `reven/db.py` 新增公开函数 `escape_like(value: str) -> str`（转义 `\`、`%`、`_`，逻辑从 `talents/repository.py:23-24` 平移）
- `talents/repository.py` 删除私有 `_escape_like`，改 `from reven.db import escape_like`（:121 调用点同步）
- `crm/repository.py` `_customer_search`（:87-106）：`pattern = f"%{escape_like(query)}%"`，所有 `ilike` 调用补 `escape="\\"`
- 验证：`pytest server/tests/api/test_talents.py server/tests/api/test_crm.py -q`（既有转义测试须零改动通过）

## Step 2 — CRM 联系人搜索扩字段

- `crm/repository.py:93-98` 联系人 EXISTS 的 `or_` 块加 `Contact.role.ilike(pattern, escape="\\")`、`Contact.notes.ilike(pattern, escape="\\")`
- 保持 EXISTS 结构不变（D1）

## Step 3 — talents q 扩字段

- `talents/repository.py` `_filtered`（:107-130）的 q 块扩展：
  - 主表 `or_` 追加：`notes`、`capability`、`phone`、`email`、`wechat`（均 `ilike(pattern, escape="\\")`）
  - JSONB：`Talent.tags.cast(String).ilike(pattern, escape="\\")`、`Talent.preferences.cast(String).ilike(pattern, escape="\\")`（D2）
  - 两个新 EXISTS：experiences.company/title/description、educations.school/degree/major（D1 写法）
- REST `list_talents` 与 MCP `list_talent_plans` 共用 `_filtered`，只改这一处

## Step 4 — server 测试

- `server/tests/api/test_crm.py:57` 家族：补 source/notes 逐字段断言（调研 Caveats 指出的缺口）、联系人 role/notes 命中断言、多联系人命中不重复返回断言、CRM 通配符转义回归（参照 `test_talents.py:131-138`，`query="%"` 只命中字面 `%`）
- `server/tests/api/test_talents.py:48` 家族：逐画像字段命中断言（notes/capability/phone/email/wechat/tags 模糊/preferences 模糊/experiences/educations），tag 精确筛行为不变
- `server/tests/agent/test_tools_crm.py:68` 家族、`server/tests/agent/test_tools_talents.py:108-146` 家族：各补一条画像字段命中（证明 MCP 端同步生效）

## Step 5 — 文案同步（MCP + web）

- `agent/tools_crm_customers.py:36-39` query 描述补「职务/备注」
- `agent/tools_talents_talents.py:45` query 描述与 :50 docstring 写明新覆盖面（能力/标签/喜好/联系方式/履历/院校）
- `web/src/features/crm/customer-list.tsx:79` placeholder 补「职务」；`web/src/features/talents/talent-list.tsx:93` placeholder 改为覆盖画像的简述
- web 测试若断言 placeholder 文案则同步；参数序列化断言预期不受影响

## Step 6 — spec 契约句更新（主代理执行，实施代理跳过）

- `crm-contract.md:89-91` 搜索覆盖面句、`talents-contract.md:64-67` q 覆盖面句（含 JSONB cast 写法与排除项）

## 交付门槛（全量实跑）

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://reven_test:reven_test@127.0.0.1:55432/reven_test
uv run pytest server/tests --cov=reven --cov-fail-under=80
uv run pytest server/tests/migrations
uv run ruff check server && uv run ruff format --check server
uv run mypy server/src
pnpm --filter @reven/web exec vitest run
pnpm --filter @reven/web lint
pnpm --filter @reven/web exec tsc -b
```

（web 依赖若缺先 `pnpm install`；测试库容器若没起 `docker start test-postgres-1`。）

禁止 git add/commit；禁止改 `.trellis/spec/`、`.trellis/tasks/`；禁止范围外重构（不统一 query/q 参数名、不加索引、不动 FollowUp 搜索）。
