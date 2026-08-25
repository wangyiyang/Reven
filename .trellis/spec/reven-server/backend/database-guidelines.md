# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

<!--
Document your project's database conventions here.

Questions to answer:
- What ORM/query library do you use?
- How are migrations managed?
- What are the naming conventions for tables/columns?
- How do you handle transactions?
-->

(To be filled by the team)

---

## Query Patterns

<!-- How should queries be written? Batch operations? -->

(To be filled by the team)

---

## Migrations

### Scenario: Merge concurrent Alembic heads

#### 1. Scope / Trigger

- Trigger: two branches add migrations from the same released revision, or `alembic heads` reports more than one head.
- Released migration files are append-only. Never change their `revision`, `down_revision`, `upgrade`, or `downgrade` behavior to repair the graph.

#### 2. Signatures

```python
revision: str = "<next_revision>"
down_revision: str | tuple[str, ...] = ("<left_head>", "<right_head>")
```

Required commands:

```bash
uv run alembic -c server/migrations/alembic.ini heads
uv run alembic -c server/migrations/alembic.ini upgrade head
```

#### 3. Contracts

- Every revision ID is unique and immutable after release.
- Before merge and deployment, `alembic heads` must return exactly one revision.
- Resolve concurrent heads with a new no-op merge revision whose `down_revision` tuple contains every current head.
- `upgrade head` must work from a fresh database and from a database stamped at any merged sibling head.
- A merge revision has no request, response, or environment contract beyond the existing required `DATABASE_URL`.

#### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| `alembic heads` returns multiple rows | Fail validation; add a merge revision before deployment |
| Database is at one sibling head | `upgrade head` applies the missing sibling and then stamps the merge revision |
| A released revision would need editing | Reject the edit; append a corrective or merge revision |
| `DATABASE_URL` is missing or unreachable | Migration exits non-zero and deployment must not continue |

#### 5. Good / Base / Bad Cases

- Good: two sibling `0013` revisions are joined by a new `0014` merge revision and both upgrade paths are tested.
- Base: one linear migration points to the previous single head.
- Bad: renaming or rebasing an `0013` revision after a database has already recorded it.

#### 6. Tests Required

- Assert `ScriptDirectory.get_heads()` returns exactly the expected single head.
- Starting from each sibling revision, run `upgrade head` and assert `alembic_version` contains only the merge revision.
- Assert the schema changes from every sibling exist after the upgrade.
- Run the normal fresh-database `alembic upgrade head` CI step.

#### 7. Wrong vs Correct

Wrong — rewrite a released sibling to create a linear history:

```python
down_revision = "other_released_sibling"
```

Correct — preserve both released revisions and append a merge node:

```python
revision = "0014_merge_crm_and_integration"
down_revision = ("0013_crm", "0013_integration_last_latency_ms")


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```


---

## Naming Conventions

<!-- Table names, column names, index names -->

(To be filled by the team)

---

## Common Mistakes

<!-- Database-related mistakes your team has made -->

(To be filled by the team)
