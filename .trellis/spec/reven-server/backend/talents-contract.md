# Talents Aggregate Contract

## 1. Scope / Trigger

Use this contract whenever changing the one-person-company talent pool across
PostgreSQL, FastAPI, or the React client. The aggregate contains talents and
their interaction history. It intentionally does not include a `domain`
category (tags replace it), a reminder/notification module, engagement
(gig) records, pagination, multi-tenant ownership, or any Notion coupling —
the product goal is to replace Notion, not sync with it.

## 2. Signatures

API prefix: `/api/talents`.

| Method | Path | Result |
|---|---|---|
| `GET` | `/talents` | `Talent[]` filtered by `status`, `due`, `q`, and `tag` |
| `POST` | `/talents` | Create a talent |
| `GET/PATCH/DELETE` | `/talents/{talent_id}` | Read, update, or delete one talent |
| `GET/POST` | `/talents/{talent_id}/interactions` | List or create interactions |
| `PATCH/DELETE` | `/talents/interactions/{interaction_id}` | Update or delete one interaction by ID |

Database tables (migration `0015_talents`, both with RLS enabled):

- `talents(id UUID PK, name, organization, tags JSONB, capability,
  engagement_terms, availability, rate_amount, rate_unit, rating, status,
  notes, timestamps)`
- `talent_interactions(id UUID PK, talent_id FK CASCADE, occurred_on,
  channel, summary, next_action, next_due_on, created_at)`

## 3. Contracts

Talent statuses are exactly `候选`, `接洽中`, `已合作`, and `搁置`. There is
no state machine: status only changes via explicit `PATCH`, and an
`已合作` talent may be patched back to `接洽中`. Interaction channels are
exactly `面谈`, `电话语音`, `微信`, and `邮件`. `rate_unit` is exactly
`按小时`, `按天`, or `按项目`.

`due` accepts `overdue`, `today`, `upcoming`, or `none`; it compares the
talent's earliest `next_due_on` across all interactions against the
Asia/Shanghai calendar date. As in the CRM contract, "today" must come from
`reven.scheduling.SHANGHAI` in both route and test code; `date.today()`
follows the runner's local timezone and flakes in CI when UTC and Shanghai
straddle midnight. `q` matches name/organization with ilike
(`\`, `%`, `_` escaped). `tag` is an exact single-tag match against the
JSONB array; tags are free-form strings with no backend normalization —
consistency is a frontend autocomplete concern only.

`rate_amount` is serialized as a JSON string (pydantic v2 `Decimal`), e.g.
`"500.00"`; the browser parses and submits it as a string.
`rate_amount` and `rate_unit` must be both null or both set. `rating` is an
integer in [1, 5] or null.

Creating or deleting an interaction refreshes the talent's `updated_at`
(the list sorts by recent activity); it never changes `status`. Deleting a
talent cascades to its interactions.

## 4. Validation & Error Matrix

| Condition | Expected behavior |
|---|---|
| Unknown request field | FastAPI/Pydantic `422` |
| Empty required name | `422` |
| Invalid status, channel, rate_unit, rating outside 1–5 | `422` |
| Only one of `rate_amount` / `rate_unit` provided | `422 / TALENT_RATE_PAIR_INCOMPLETE`; DB check constraint is the final guard |
| Explicit `null` on any NOT NULL field in PATCH (including `tags`) | `422` |
| Missing talent | `404 / TALENT_NOT_FOUND` |
| Missing interaction | `404 / TALENT_INTERACTION_NOT_FOUND` |

Lesson learned (2026-08-26): the PATCH explicit-null rejection list must
enumerate **every** NOT NULL column, including JSONB columns like `tags` —
a missing entry lets `null` reach the database and surface as a 500
IntegrityError instead of a 422.

Talent payloads (rates, engagement terms) must never be written to
application logs. Existing authentication and CSRF middleware protect every
talents route.

## 5. Good / Base / Bad Cases

- Good: create a talent with tags, rate pair, and rating; then log an
  interaction with `next_due_on`; the talent rises to the top of the list
  and matches `due` filters.
- Base: create a talent with only a name and at least one tag; defaults to
  `候选`.
- Bad: PATCH `{"tags": null}`; return `422`, never a 500.
- Bad: delete a talent; its interactions must disappear via FK cascade.

## 6. Tests Required

- Migration: upgrade from `0014_merge_crm_and_integration`, downgrade back,
  upgrade to head; assert check constraints and RLS on both tables.
- API: talent CRUD; all four statuses; all due filters with earliest-due
  semantics; `q` escaping; `tag` exact match; rate pair validation; rating
  boundary (0/6 rejected); explicit-null rejection; interaction ordering;
  talent cascade deletion.
- Frontend: typed request payloads (rate as string); tag input with
  autocomplete from existing tags; list filters; overdue/today badges;
  create/edit/delete confirmation; interaction CRUD on the detail page.
