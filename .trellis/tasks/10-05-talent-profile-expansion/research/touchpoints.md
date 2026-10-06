# Research: Talent 画像扩展触点（#201 P2）

- Query: talents 域 server/web/测试全链路现状、JSONB 与子表范式、migration 0026 落点、talents-contract spec 结构
- Scope: internal
- Date: 2026-10-05
- 前置文档：`.trellis/tasks/10-05-talent-profile-expansion/prd.md`（R1–R8）、`design.md`（已锁定嵌套端点 + scoped 404 + 月精度序列化归 web）

---

## 1. Server 现状

### models — `server/src/reven/talents/models.py`

- `TalentStatus / InteractionChannel / RateUnit` 三个 StrEnum（models.py:16-33），枚举值即中文字面量，直接落 `String(16)` 列。
- `Talent`（models.py:36-52）：`tags: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))`（models.py:42）——preferences 照抄此行。
- `TalentInteraction`（models.py:55-69）：FK `ForeignKey("talents.id", ondelete="CASCADE")`（models.py:63），复合索引走 `__table_args__`（models.py:57-60），**无 `relationship()` ORM 关系**，全靠 repository 查询；无 `updated_at`。
- 对比 `crm/models.py`：Contact/FollowUp 的 FK 列带 `index=True`（crm/models.py:54-57, 73-76）且有 `updated_at`；P2 新子表按 design.md 带 `created_at/updated_at`。

### repository — `server/src/reven/talents/repository.py`

- `TalentsRepository(session)` 构造注入（repository.py:26-27）；全部方法 async，返回 ORM 实例。
- `list_talents`（repository.py:29-53）：status/due/q/tag 过滤，`Talent.tags.contains([tag])` 做 JSONB 数组过滤（repository.py:51），`updated_at desc, id` 排序。
- `_earliest_due_subquery`（repository.py:16-22）：`func.min(TalentInteraction.next_due_on)` 相关子查询——**R7 要改的就是这里**。
- CRM 的「最新一条」范式已存在：`crm/repository.py:34-41 _latest_due_subquery()`（`order_by(occurred_on desc, created_at desc, id desc).limit(1).correlate().scalar_subquery()`），R7 直接同构照抄；`_filter_due` 四档比较（repository.py:56-66）逻辑不变。
- 子查询/写方法模式：`get_talent` = `session.get`（repository.py:68-69）；`add_*` 接收 `dict[str, object]` 展开 + `flush()`（repository.py:71-75, 94-98）；`list_interactions` 按 `occurred_on desc, created_at desc, id desc`（repository.py:77-87）——履历/院校排序（end_on NULL 在前 + start_on desc）在此层实现。
- 注意：talents 的 `get_interaction` 只按 id 查（repository.py:89-92，**不 scoped**）；CRM 的 `get_contact(customer_id, contact_id)` 双条件 scoped（crm/repository.py:161-164）——P2 新子表按 design.md 走 CRM scoped 范式。

### service — `server/src/reven/talents/service.py`

- `InvalidRatePairError(ValueError)` 定义在 service 模块（service.py:10-11），routes 捕获映射 422——talents 没有 `errors.py`（CRM 有 `crm/errors.py`，异常继承 `LookupError/ValueError`）。
- 写入口签名全是 `(实体, values: dict[str, object])`：`create_talent(values)`（service.py:19）、`update_talent(talent, values)`（service.py:24）、`create_interaction(talent, values)`（service.py:37）、`update_interaction(interaction, values)`（service.py:43）。
- 业务不变量在 service 二次校验（rate 配对，service.py:25-28），因为 PATCH 合并语义（未提交字段取现值）只能在 service 判。
- `_assign` 循环 setattr（service.py:64-66）；`_commit_and_refresh` 统一 commit+refresh（service.py:59-61）。
- `create_interaction` / `delete_interaction` 会 bump `talent.updated_at`（service.py:39, 53-55）——**新子表是否 bump 父级 updated_at 需决策**（design.md 未写；不 bump 则履历变更不影响列表排序，与 R6「画像不参与活跃度」语义一致）。

### routes — `server/src/reven/api/routes/talents.py`

8 个端点（routes/talents.py:43-141）：

| 行 | 端点 | 说明 |
|---|---|---|
| :43 | `GET /api/talents` | Query: status(TalentStatus)/due(Literal)/q/tag，SHANGHAI 取 today（:56） |
| :60 | `POST /api/talents` | 201，`payload.model_dump()` 直传 service |
| :65/:70/:85 | `GET/PATCH/DELETE /{talent_id}` | PATCH 用 `model_dump(exclude_unset=True)`（:80），捕获 `InvalidRatePairError` → 422 |
| :94/:103 | `GET/POST /{talent_id}/interactions` | 嵌套 list/create |
| :119/:131 | `PATCH/DELETE /interactions/{interaction_id}` | **扁平**（非嵌套），404 code `TALENT_INTERACTION_NOT_FOUND` |

- 错误处理：模块级 `_error(status_code, code, message)` 返回 `JSONResponse`（routes/talents.py:28-29）；`_talent()` loader 返回 `Talent | JSONResponse` 联合，调用方 `isinstance` 收窄（:36-40, 76-78）——这是 talents 的错误模式，与 CRM 的「service 抛领域异常 → `_mutation_error` 映射」不同（crm/routes.py:145-149）。
- 现有错误码：`TALENT_NOT_FOUND`、`TALENT_INTERACTION_NOT_FOUND`、`TALENT_RATE_PAIR_INCOMPLETE`。新子表需新增 `TALENT_EXPERIENCE_NOT_FOUND` / `TALENT_EDUCATION_NOT_FOUND`。

### schemas — `server/src/reven/api/schemas/talents.py`（关键结论）

- **talents 没有 `inputs.py` 校验层，全部校验就在本文件**（Pydantic 模型即校验）。CRM 的 `crm/inputs.py` 是域层校验、`api/schemas/crm.py:8-13` 显式重导出六个输入类（为 MCP 复用解耦）；talents 目前无 MCP 工具（grep `server/src/reven/agent` 无 talent 引用，P3 才做），所以 P2 校验继续落在 `api/schemas/talents.py`，**不要机械搬 inputs.py**（design.md §2 也以此文件结论为准）。
- 校验原语（schemas/talents.py:12-35）：
  - 类型别名：`RequiredName` / `OptionalText`(strip, ≤2000) / `Tag`(strip, 1–50) / `RateAmount`(Decimal) / `Rating`(1–5)；
  - `_empty_to_none`：空串归 null，用 `field_validator(..., mode="before")` 批量挂 `_TEXT_FIELDS`（:21-24, 53）；
  - `_reject_explicit_null`：PATCH 拒绝显式 null 的 NOT NULL 字段（:32-35），`TalentUpdate.keep_required_fields` 枚举 `"name", "status", "tags"`（:80）——**preferences 加列后必须进此列表**（spec 教训：漏枚举 JSONB 列会让 null 穿透成 500，talents-contract.md:71-74）；
  - `_require_rate_pair`：create 时 model_validator 全量校验（:55-58），update 时仅当两字段都提交才校（:81-82，单边由 service 合并校验兜底）。
- 全部模型 `extra="forbid"`（:39, 62, 106, 118）。
- 联系方式校验规则可直接对齐 CRM：`OptionalPhone`(≤50)/`OptionalEmail`(≤320)/`OptionalWechat`(≤100) + `_EMAIL_PATTERN` 正则（crm/inputs.py:16-18, 22, 31-34）——把同样规则写进 talents schemas（是否抽共享模块是 implement 决策，现状两域各自定义、无共享）。
- 响应模型 `TalentResponse` `from_attributes`（schemas/talents.py:86-102），直接返回 ORM。

---

## 2. Web 现状 — `web/src/features/talents/`

| 文件 | 职责 |
|---|---|
| `types.ts` (67 行) | 枚举常量 + `Talent`/`TalentInput`/`TalentFilters`/`TalentInteraction`/`TalentInteractionInput`；`rate_amount: string \| null`（Decimal 字符串化，types.ts:19） |
| `talents-api.ts` (33 行) | `talentsKeys`（:5-9，talents/talent/interactions 三级 key）+ talent 详情与 interactions CRUD；**talent 的 create/update/delete 不在这里**——列表页走 `useResourceList` seam、详情页 PATCH 内联 |
| `talent-form-model.ts` (85 行) | `TalentFormValues`（全 string 形态）、`EMPTY_TALENT_FORM`、`talentToForm`/`talentFormToInput` 双向序列化、`validateTalentForm` 返回 `string \| null`、`appendTag`/`removeTag` 纯函数（:77-85）——preferences 的 append/remove 直接复用这两个函数 |
| `talent-form.tsx` (223 行) | 受控表单：`TalentIdentityFields`/`TalentTagsField`/`TalentProfileFields`/`TalentRateFields` + notes + 按钮行；`singleColumn` prop 适配抽屉（:19）；联系方式 3 字段加进 Identity 或新 Profile 行、喜好照抄 `TalentTagsField` |
| `talent-form-drawer.tsx` (31 行) | Drawer 壳，复用 `TalentForm`（新建场景） |
| `talents-page.tsx` (103 行) | 列表页：`useResourceList<Talent, TalentFormValues, TalentFilters>`（:24-43，`updateMethod: "PATCH"`，toPayload/toForm/validate 注入 form-model 函数）；tag 建议从列表数据派生（:44-47） |
| `talent-list.tsx` | 表格 + 过滤栏；`TagBadges`（:164-166）展示 tags；新字段不进列表（列表契约不变） |
| `talent-detail-page.tsx` (149 行) | 详情页骨架：`DetailHeading` + `TalentSummary`（档案卡，只读/编辑两态）+ `InteractionsSection` 竖排（:34-38）；`?edit=1` 深链（:71） |
| `interactions-section.tsx` (188 行) | 子表分区范式（见下） |

### 详情页分区组织（新画像区挂载点）

`TalentDetail`（talent-detail-page.tsx:27-40）按 `<main class="space-y-6">` 竖排三张卡：heading → `TalentSummary`（人才档案 Card，内含编辑态）→ `InteractionsSection`。P2 建议：画像卡（联系方式+喜好）插在 `TalentSummary` 之后，履历/院校两个新 section 文件插在 `InteractionsSection` 之前/之后均可；或把联系方式并入 `TalentSummary` 卡（编辑态已复用 `TalentForm`，加字段即双向打通）。`TalentSummary` 的编辑态用 `useSearchParams` 初始化 + 内联 PATCH + `setQueryData` 乐观写缓存（:83-93）。

### interactions-section 增删改模式（子表 section 模板，照抄对象）

- 状态：`form`（当前编辑值）+ `editing`（编辑目标实体|null）+ `deleting`（确认框目标|null）（interactions-section.tsx:34-36）。
- 查询/变更：`useQuery(talentsKeys.interactions(talentId))`；`useCreate/Update/Delete` 三个 hook（:126-166），成功回调里 `invalidateQueries` 相关 key + `toast.success` + reset 表单；create 还额外 invalidate talent 详情与列表（因为 bump updated_at，:131-135）。
- 表单：顶部常驻内联表单（非抽屉），`InteractionFormValues` 全 string；提交前 `validateInteraction`（:182-186）→ toast.error 短路；`interactionFormToInput` 用 `emptyToNull`（**跨 feature 从 `../crm/crm-api` 导入**，interactions-section.tsx:15，crm-api.ts:69-72）序列化空串→null。
- 列表：`InteractionList` 三态（loading/failed/empty）+ `InteractionCard`（`article` + aria-label 便于测试定位，:109）；删除走 `ConfirmDialog`（components/ui/dialog）。
- 日期输入：`<Input type="date">`（:86, 91），默认 `todayInShanghai()`（`../crm/date-utils`，:16, 30）——**项目无"只到月"先例**，所有日期控件都是 `type="date"`，存储 PG `date`，序列化 ISO `YYYY-MM-DD`。月精度是 P2 新引入的约定（design.md §4：web 层补 `-01`，API 只收完整日期）。
- CRM `contacts-section.tsx` 是同一模板的另一实例（嵌套端点版本：`updateContact(customerId, contactId, input)`，contacts-section.tsx:155），卡片网格布局 `md:grid-cols-2`（:134）可参考用于画像卡。

### `useResourceList` seam — `web/src/lib/use-resource-list.ts`

列表页通用 CRUD hook（:46）：注入 `toPayload/toForm/validate/messages`，默认 PUT、talents 显式传 PATCH（talents-page.tsx:27）。Talent 加字段只需改 form-model 三函数 + types，seam 不动。

---

## 3. 测试现状

### Server — `server/tests/api/test_talents.py`（243 行，唯一 talents API 测试）

- fixture：`workbench`（`tests/api/conftest.py:70-90`）= `(TestClient, async_sessionmaker)`，`TEST_DATABASE_URL` 缺失即 skip，每用例 TRUNCATE 重置；真实 PostgreSQL。
- **⚠️ TRUNCATE 表清单是硬编码枚举**，两处：`tests/conftest.py:36` 和 `tests/api/conftest.py:82`——新子表 `talent_experiences / talent_educations` 必须同时加进这两处，否则用例间数据污染。
- 辅助：`_today()` 用 SHANGHAI 时钟（test_talents.py:8-11，注释解释了 UTC 16:00–24:00 窗口 flake）；`_create_talent` / `_create_interaction` payload 工厂（:14-45）先断言 201 再返回 json。
- 断言风格：状态码 + `response.json()["code"]` 错误码（:85, 183, 225）；列表断言用 id 数组等值（:60, 103-106）；422 校验矩阵集中在一个用例连发（`test_talent_validation_is_explicit`，:119-136）；枚举全值 `pytest.mark.parametrize`（:139, 150）；级联删除端到端验证（:239-243）。
- 子表嵌套用例 `test_interactions_nested_scoped_and_cascade`（:195-243）是 P2 新子表测试的直接模板：排序断言、越父 404（:223-233）、PATCH null 拒绝（:220-221）、级联（:240-243）。
- R7 影响：`test_talent_due_filters_use_earliest_next_due`（:88-106）断言的是 min 语义（同一人两条记录，earliest 决定分档）——改「最新记录」语义后此用例需重写（最新无日期→旧日期不冒泡；最新有日期→按最新分档）。

### Migration 测试

- `tests/migrations/test_merge_heads_migration.py:18`：`FINAL_REVISION = "0025_crm_plan_derive"`——0026 落地后改 `"0026_<slug>"`，`test_migration_graph_has_one_head`（:45-49）即自动覆盖单 head 断言。
- `tests/migrations/test_crm_plan_derive_migration.py`（120 行）是单迁移回归模板：information_schema 查列/check 约束名（:23-49）、违例插入断言被拒（`_plan_pair_is_rejected`，:52-81）、upgrade→downgrade→upgrade 三段（:91-118）、finally upgrade head（:119-120）。0026 照此新增（约束：`end_on >= start_on` 违例插入被拒 + preferences 的 `jsonb_typeof = 'array'` check）。
- `database-guidelines.md:36-41`：迁移链牵连点=后续 `down_revision` + `env.py` import + tests/migrations 引用；验证标准=空库 upgrade head + `pytest tests/migrations/` 全绿。
- `server/migrations/env.py:19` import 了 `Talent, TalentInteraction`——新 ORM 模型要追加到该行（autogenerate 依赖）。

### Web 测试

- `talent-detail-page.test.tsx`（232 行）：msw `server.use(http.get/patch/delete(...))` 打 `/api/...` 前缀（:67-72）；`QueryClient({ queries: { retry: false } })` + `MemoryRouter`/`Routes` 包渲染（:50-62）；`vi.mock("sonner")` 断言 toast（:15-20）；`userEvent.type/click` 驱动；断言 request body 形状（:108-113, 138）与缓存失效后的 UI 更新；表单控件一律按 `getByLabelText` 取（Label htmlFor 配套）。P2 新 section 的测试照此文件扩。
- `talents-page.test.tsx`：列表页同款 msw 模式（过滤参数转换 :68-90、空态 :92、抽屉新建 :102、客户端校验短路 :148、删除确认 :171、错误重试 :194）。

---

## 4. JSONB（tags）先例 → preferences 最短路径

| 层 | tags 写法 | 位置 |
|---|---|---|
| migration | `JSONB(astext_type=sa.Text())` + `server_default "'[]'::jsonb"` + NOT NULL + `CheckConstraint("jsonb_typeof(tags) = 'array'", name="ck_talents_tags_array")` | 0015_talents.py:28-33, 44 |
| ORM | `Mapped[list[str]] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))` | models.py:42 |
| schemas | `Tag` 别名（strip 1–50）；create `list[Tag] = Field(default_factory=list, max_length=20)`；update `list[Tag] \| None` + `_reject_explicit_null(..., "tags")` | schemas/talents.py:14, 43, 66, 80 |
| repository | 列表过滤 `Talent.tags.contains([tag])`（preferences 无过滤需求，不需要） | repository.py:51 |
| web 序列化 | 表单值 `string[]` 原样往返（`talentToForm`/`talentFormToInput` 直通，form-model.ts:37, 53） | form-model.ts |
| web 控件 | 输入框 + `datalist` 建议 + 回车/按钮添加 + Badge  Chips × 移除（`TalentTagsField`，talent-form.tsx:92-145）；纯函数 `appendTag`(trim、去重)/`removeTag`（form-model.ts:77-85）可直接复用于 preferences | talent-form.tsx |
| 建议数据 | 从列表查询结果 flatMap 去重排序（talents-page.tsx:44-47；详情页编辑态用同 key 列表查询命中缓存，talent-detail-page.tsx:74-82）——preferences 语义=个人喜好，**是否也要建议源需决策**（tags 建议来自全库 talents，preferences 若同样取全库会泄露他人喜好语义，建议不提供 datalist 或仅从自身取） | — |

preferences 增量 = migration 加列（含 `ck_talents_preferences_array` check）→ ORM 一行 → schemas 三处（create/update/response + update 的 null 拒绝列表）→ form-model 三函数各加一行 → 表单抄一个 `TalentTagsField` 变体。无 repository/service/routes 改动（随 Talent 主实体读写）。

---

## 5. 子表先例与 P2 范式选择

项目存在两种 1—N 子表范式：

| 维度 | talents interactions（扁平） | CRM contacts/follow-ups（嵌套） |
|---|---|---|
| 更新/删除路由 | `/talents/interactions/{id}`（routes/talents.py:119, 131） | `/customers/{cid}/contacts/{cid2}`（routes/crm.py:152, 165） |
| 更新动词 | PATCH（`exclude_unset`） | **PUT**（完整替换语义，schema 仍允许部分字段） |
| 子行查询 | `get_interaction(id)` 不 scoped（repository.py:89-92） | `get_contact(customer_id, id)` scoped（crm/repository.py:161-164），越父访问 404 不泄露存在性 |
| 错误 | routes `_error` JSONResponse + isinstance 收窄 | 域异常（crm/errors.py）→ `_mutation_error` 映射 |
| 校验层 | api/schemas | crm/inputs.py（域层，API 重导出） |
| 父级联动 | create/delete bump `talent.updated_at`（service.py:39, 53-55） | 无 bump（客户活跃度靠派生查询） |
| web section | interactions-section（扁平函数 `updateInteraction(id, input)`） | contacts-section（嵌套函数 `updateContact(customerId, id, input)`） |

**P2 已锁定跟 CRM 嵌套范式**（prd R5 + design.md §3：`/talents/{id}/experiences|educations` + `PUT/DELETE /talents/{id}/experiences/{eid}`，scoped 404）。落位时保留 talents 自身风格的部分：校验继续写 `api/schemas/talents.py`（不建 inputs.py）、错误继续用 routes `_error` 模式（不建 errors.py）；只有「路由形状 + scoped 查询 + PUT 动词」对齐 CRM。排序：`list_experiences` 在 repository 实现 `end_on IS NULL 最前, start_on desc, created_at desc`（PG 写法 `(TalentExperience.end_on.is_(None)).desc()` 或 `nulls_first`）。

---

## 6. Migration 0026 落点

- 编号/链头：下一个 = `0026`，`down_revision = "0025_crm_plan_derive"`（0025_crm_plan_derive.py:15-16 确认是当前唯一 head；merge-heads 测试 FINAL_REVISION 同步改）。
- 0015 建表惯例（0015_talents.py）：
  - check 约束命名 `ck_<table>_<purpose>`（:44-48），枚举值 check 直接写字面量 IN 列表；
  - 索引 `ix_<table>_<cols>`，FK 复合索引 `(talent_id, occurred_on)`（:73-77）；
  - 每表末尾 `op.execute("ALTER TABLE ... ENABLE ROW LEVEL SECURITY")`（:52, 79）——**新两表必须带**（无 RLS 策略=默认拒绝，与现有一致，service 用超级用户/owner 连接不受影响）；
  - FK `sa.ForeignKeyConstraint(["talent_id"], ["talents.id"], ondelete="CASCADE")`（:70）；
  - downgrade 反序 drop index → drop table（:82-87）。
- 0026 内容（对齐 design.md §1）：talents `add_column` × 4（phone/email/wechat 可空 String + preferences JSONB NOT NULL server_default '[]' + `ck_talents_preferences_array` check）；建 `talent_experiences` / `talent_educations` 两表（`ck_*_date_range`: `end_on IS NULL OR end_on >= start_on`；`ix_*_(talent_id, start_on)`；RLS）。
- 牵连点清单：① `server/migrations/env.py:19` 追加新模型 import；② `tests/conftest.py:36` + `tests/api/conftest.py:82` TRUNCATE 列表加两表；③ `test_merge_heads_migration.py:18` FINAL_REVISION；④ 新增 `tests/migrations/test_0026_*_migration.py`（照 0025 模板）。

---

## 7. Spec 现状与更新映射

`.trellis/spec/reven-server/backend/talents-contract.md`（100 行）结构：

1. **Scope / Trigger**（:3-10）：聚合边界 + 明确排除项（无 reminder、无 gig、无分页、无 Notion 耦合）。
2. **Signatures**（:12-30）：API 端点表 + 数据库表字段表（标注 migration 编号与 RLS）。
3. **Contracts**（:32-57）：枚举全集、due 四档语义（含 SHANGHAI 时区强制条款 :40-44）、q/tag 过滤语义、Decimal 字符串化、rate 配对、rating 区间、interaction 写操作 bump updated_at、级联删除。
4. **Validation & Error Matrix**（:59-78）：条件→行为表 + 「教训」段（PATCH null 拒绝必须枚举 JSONB 列）+ 日志/中间件条款。
5. **Good / Base / Bad Cases**（:80-88）。
6. **Tests Required**（:90-100）：migration/API/frontend 三层清单。

与 `crm-contract.md`「派生读入口」小节的对应关系：crm-contract 在 Signatures 内嵌了 `### 派生读入口（CrmRepository）`（crm-contract.md:50-63，含 `CustomerPlan` dataclass 代码块与四个派生读签名），并在 Contracts 加「计划派生契约」条目组（:97-109）、文末附 Incorrect/Correct 代码对照（:190-205）。talents-contract 目前没有对应小节——**P2 更新时**：R7 到期语义改写进 §3 Contracts（due 段，现 :40-44 描述的还是"earliest"，要改成"最新一条 interaction 的 next_due_on"，与 crm-contract.md:83-87 措辞对齐）；是否新增「派生读入口」式小节取决于 talents repository 是否也暴露独立派生读签名——现状 `_latest_due_subquery` 只是 list 过滤的内部实现，建议只在 §3 写明语义、不另起小节（talents 列表排序按 updated_at，无 CustomerPlan 那样的派生读模型）。§2 表加两个新端点行 + 两张新表；§4 矩阵加 `end_on < start_on` 422、email 格式 422、新 404 错误码行；§6 补迁移/API/前端新用例。

---

## 8. 实施建议顺序

1. **migration 0026**（加列 + 两表 + RLS + check）→ `env.py` import → 两处 TRUNCATE 列表 → `FINAL_REVISION` → 新增 0026 迁移回归测试（先跑通 `pytest tests/migrations/`）。
2. **ORM + schemas**（models.py 加列加两模型；schemas/talents.py 加联系方式校验别名、preferences、两个子表的 Create/Update/Response，update 的 `_reject_explicit_null` 列表补 `preferences`）。
3. **repository + service + routes**：子表 scoped 查询/写方法（排序：至今最前 + start_on desc）；嵌套端点 8 个（GET/POST 列表创建 + PUT/DELETE 单条），新 404 错误码；`TalentResponse` 扩字段。
4. **R7 到期语义**：`_earliest_due_subquery` → `_latest_due_subquery`（照抄 crm/repository.py:34-41），重写 `test_talent_due_filters_*` 用例。
5. **API 测试**：照 `test_interactions_nested_scoped_and_cascade` 模板参数化覆盖两子表（排序、越父 404、date_range 422、级联）；联系方式/preferences 校验矩阵并入既有 422 用例。
6. **web**：types/talents-api → form-model + talent-form（联系方式 + 喜好）→ 详情页画像卡 → `experiences-section.tsx` / `educations-section.tsx`（照 interactions-section 模板，月份录入 + YYYY-MM 展示）→ 详情页/列表页测试扩 msw 用例。
7. **spec 更新**（Phase 3.3，用 update-spec skill）+ 全量门禁（pytest、vitest、lint、typecheck、覆盖率）。

## 9. 风险点

- **TRUNCATE 硬编码清单两处**（tests/conftest.py:36、tests/api/conftest.py:82）：漏加新表 → 用例间污染且报错隐晦；最易遗漏的牵连点。
- **PATCH 显式 null 拒绝列表**：`TalentUpdate.keep_required_fields` 必须加 `"preferences"`，否则 `{"preferences": null}` 穿透成 500（talents-contract.md:71-74 已记录该教训的 tags 版本）。
- **R7 语义反转**：`test_talent_due_filters_use_earliest_next_due` 整个用例的断言基于 min 语义，改最新语义后不是微调而是重写；同时 dashboard/agent 若有复用 talents due 过滤的入口需排查（本次 grep 未发现 talents 被 dashboard 引用——列表过滤是 talents 域内部实现）。
- **范式混用**：talents 现存扁平子表路由（interactions）与 P2 新嵌套路由（experiences/educations）将并存，且 PUT（新）与 PATCH（旧）动词不一致——这是已锁定决策（design.md §3），spec 更新时写明两种形状各自的适用范围，避免后人误判为笔误。interactions 不重构成嵌套（非本任务范围）。
- **月精度是新约定**：项目无先例；必须只在 web 序列化层补 `-01`（talents-api.ts），API/DB 不做二次猜测（design.md §4）；`<input type="month">` 的浏览器兼容与测试可用性（userEvent.type 对 month 输入支持差）可能要求改用 date 输入 + 截取序列化，implement 时先在组件测试里验证。
- **preferences 建议源**：照抄 tags 的 datalist 建议会把全库他人喜好当候选，语义混用（风险 design.md §8 已列）；建议 preferences 不提供建议源或仅自身值。
- **子表写操作是否 bump `talent.updated_at`**：interactions 会 bump（影响列表排序），design.md 未明确新子表行为；不 bump 更合理（履历修订≠接洽活跃），implement 前需在 review 中确认并在 spec 写明。
- **RLS 必带**：新两表漏 `ENABLE ROW LEVEL SECURITY` 会打破 0013/0015 以来的安全惯例，迁移回归测试可断言。
