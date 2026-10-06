# Talents Aggregate Contract

## 1. Scope / Trigger

Use this contract whenever changing the one-person-company talent pool across
PostgreSQL, FastAPI, or the React client. The aggregate contains talents, their
profile (contact channels, preferences, work experiences, educations), and
their interaction history. It intentionally does not include a `domain`
category (tags replace it), a reminder/notification module, engagement
(gig) records, pagination, multi-tenant ownership, resume file attachments
（简历=结构化履历数据，见 `talent_experiences`/`talent_educations`）, or any
Notion coupling — the product goal is to replace Notion, not sync with it.

## 2. Signatures

API prefix: `/api/talents`.

| Method | Path | Result |
|---|---|---|
| `GET` | `/talents` | `Talent[]` filtered by `status`, `due`, `q`, and `tag` |
| `POST` | `/talents` | Create a talent |
| `GET/PATCH/DELETE` | `/talents/{talent_id}` | Read, update, or delete one talent |
| `GET/POST` | `/talents/{talent_id}/interactions` | List or create interactions |
| `PATCH/DELETE` | `/talents/interactions/{interaction_id}` | Update or delete one interaction by ID |
| `GET/POST` | `/talents/{talent_id}/experiences` | List or create work experiences |
| `PUT/DELETE` | `/talents/{talent_id}/experiences/{experience_id}` | Update or delete an owned experience |
| `GET/POST` | `/talents/{talent_id}/educations` | List or create educations |
| `PUT/DELETE` | `/talents/{talent_id}/educations/{education_id}` | Update or delete an owned education |

**两种子表路由形状并存是刻意的，不要误判为笔误**：interactions 是扁平
`PATCH /talents/interactions/{id}`（按 ID 定位，0026 之前的既有形状，不在
本次重构范围）；experiences/educations 是嵌套 `PUT
/talents/{talent_id}/.../{child_id}`（双条件 scoped 查询，越父访问 404 不
泄露存在性，对齐 CRM contacts/follow-ups 范式）。新增子资源一律走嵌套。

Database tables（0015 起均有 RLS；0026 起含画像）:

- `talents(id UUID PK, name, organization, tags JSONB, preferences JSONB,
  phone, email, wechat, capability, engagement_terms, availability,
  rate_amount, rate_unit, rating, status, notes, timestamps)`
- `talent_interactions(id UUID PK, talent_id FK CASCADE, occurred_on,
  channel, summary, next_action, next_due_on, created_at)`
- `talent_experiences(id UUID PK, talent_id FK CASCADE, company, title,
  description, start_on, end_on NULL=至今, timestamps)`
- `talent_educations(id UUID PK, talent_id FK CASCADE, school, degree,
  major, start_on, end_on NULL=至今, timestamps)`

## 3. Contracts

Talent statuses are exactly `候选`, `接洽中`, `已合作`, and `搁置`. There is
no state machine: status only changes via explicit `PATCH`, and an
`已合作` talent may be patched back to `接洽中`. Interaction channels are
exactly `电话`, `面谈`, `微信`, `邮件`, and `其他`（0027 起 `电话语音` 并入
`电话` 并补 `其他`，与 CRM 跟进方式统一为同一五值集合）. `rate_unit` is exactly
`按小时`, `按天`, or `按项目`.

`due` accepts `overdue`, `today`, `upcoming`, or `none`; it compares the
**latest** interaction's `next_due_on`（`occurred_on desc, created_at desc,
id desc limit 1`，`TalentsRepository._latest_due_subquery`，0026 起）against
the Asia/Shanghai calendar date. 最新一条无日期时旧日期不再冒泡（`none`）——
与 CRM 派生语义一致；仓库内不得再出现 `min(next_due_on)` 口径。As in the
CRM contract, "today" must come from `reven.scheduling.SHANGHAI` in both
route and test code; `date.today()` follows the runner's local timezone and
flakes in CI when UTC and Shanghai straddle midnight. `q` matches
name/organization with ilike (`\`, `%`, `_` escaped). `tag` is an exact
single-tag match against the JSONB array; tags are free-form strings with no
backend normalization — consistency is a frontend autocomplete concern only.

`tags`（能力/行业）与 `preferences`（喜好/个人）语义不混用：均为 JSONB
字符串数组（`jsonb_typeof = 'array'` check），元素 trim、去空、保序去重；
preferences 不提供全库建议源（避免把他人喜好当候选），tags 的建议源来自
列表数据。

`rate_amount` is serialized as a JSON string (pydantic v2 `Decimal`), e.g.
`"500.00"`; the browser parses and submits it as a string.
`rate_amount` and `rate_unit` must be both null or both set. `rating` is an
integer in [1, 5] or null.

联系方式 `phone/email/wechat` 可空、trim、空串归 null，email 正则与 CRM
Contact 同规则。履历/院校的 `start_on` 必填、`end_on` 可空（null=至今）且
`end_on >= start_on`（DB check 为最终守卫）；列表排序为「`end_on` NULL
（至今）最前 → `start_on` desc → `created_at` desc」。

**月精度约定（0026 新增）**：履历/院校日期只精确到月。API/DB 只接受完整
`YYYY-MM-DD`（日恒为 01）；`YYYY-MM → YYYY-MM-01` 的补全只允许发生在
`web/src/features/talents/talents-api.ts`（`withMonthPrecision`），服务端与
数据库不做二次猜测；展示格式 `YYYY-MM`，`end_on=null` 展示「至今」。

`organization` 是用户手动维护的当前单位快照，不从履历派生（最新履历 ≠
用户认知的当前单位）；改履历不影响 `organization`，反之亦然。

Creating or deleting an interaction refreshes the talent's `updated_at`
(the list sorts by recent activity); it never changes `status`. 履历/院校
的增删改**不**刷新 `talent.updated_at`（履历修订 ≠ 接洽活跃）。Deleting a
talent cascades to its interactions, experiences, and educations.

## 4. Validation & Error Matrix

| Condition | Expected behavior |
|---|---|
| Unknown request field | FastAPI/Pydantic `422` |
| Empty required name / company / title / school / start_on | `422` |
| Invalid status, channel, rate_unit, rating outside 1–5 | `422` |
| Invalid email format, phone/email/wechat over length | `422` |
| `preferences` not an array or non-string element | `422` |
| `end_on < start_on`（experience / education） | `422 / TALENT_DATE_RANGE_INVALID`; DB check constraint is the final guard |
| Only one of `rate_amount` / `rate_unit` provided | `422 / TALENT_RATE_PAIR_INCOMPLETE`; DB check constraint is the final guard |
| Explicit `null` on any NOT NULL field in PATCH (including `tags` and `preferences`) | `422` |
| Missing talent | `404 / TALENT_NOT_FOUND` |
| Missing interaction | `404 / TALENT_INTERACTION_NOT_FOUND` |
| Experience / education outside the route talent | `404 / TALENT_EXPERIENCE_NOT_FOUND` / `TALENT_EDUCATION_NOT_FOUND` |

Lesson learned (2026-08-26): the PATCH explicit-null rejection list must
enumerate **every** NOT NULL column, including JSONB columns like `tags` and
`preferences` — a missing entry lets `null` reach the database and surface
as a 500 IntegrityError instead of a 422.

Talent payloads (rates, engagement terms, contact channels) must never be
written to application logs. Existing authentication and CSRF middleware
protect every talents route.

## 5. Good / Base / Bad Cases

- Good: create a talent with tags, preferences, contact channels, and rate
  pair; add experiences (latest with `end_on=null` first); log an interaction
  with `next_due_on`; the talent rises to the top of the list and matches
  `due` filters.
- Base: create a talent with only a name and at least one tag; defaults to
  `候选`, `preferences=[]`, no experiences/educations.
- Bad: PATCH `{"tags": null}` or `{"preferences": null}`; return `422`,
  never a 500.
- Bad: log a newer interaction without `next_due_on`; the older due date must
  NOT resurface — the talent moves to `none` (latest-record semantics).
- Bad: update an experience via another talent's path; return the scoped
  `404` without revealing it exists elsewhere.
- Bad: delete a talent; its interactions, experiences, and educations must
  disappear via FK cascade.

## 6. Tests Required

- Migration（0026）: upgrade/downgrade/upgrade; assert new columns, both new
  tables' check constraints (`ck_*_date_range`, `ck_talents_preferences_array`),
  indexes, and RLS; violating inserts (bad date range, non-array preferences)
  are rejected; `FINAL_REVISION` single-head assertion updated.
- API: talent CRUD; all four statuses; all due filters with **latest-record**
  semantics (older due date must not resurface when the latest interaction
  has none); `q` escaping; `tag` exact match; rate pair validation; rating
  boundary; explicit-null rejection (incl. `preferences`); interaction
  ordering; profile round-trip (trim, empty→null, preferences dedup);
  experience/education nested CRUD — ordering (`end_on` NULL first),
  scoped 404, date-range 422, required-field 422, no `updated_at` bump,
  cascade deletion.
- Frontend: typed request payloads (rate as string); contact fields and
  preferences chips in the talent form (no suggestion source for
  preferences); profile display; experience/education timeline sections —
  `YYYY-MM` display, `至今` for null `end_on`, month-precision serialization
  (`-01`) in request bodies, create/edit/delete confirmation.
