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

<!-- How to create and run migrations -->

- 运行方式：`cd server/migrations && DATABASE_URL=... uv run alembic upgrade head`（`alembic.ini` 在 `server/migrations/` 下，不在 `server/`）。
- **改写历史迁移文件（改 revision id / 表名）时必须同步的牵连点**（2026-09 playbook→sop 重命名实证）：
  1. 所有后续迁移的 `down_revision` 与 docstring 中的 `Revises:` 注释（断裂会导致迁移链无法解析）；
  2. `server/migrations/env.py` 中对应模型的 import（autogenerate 依赖）；
  3. `server/tests/migrations/` 中引用该 revision 的 `command.downgrade(config, "<revision>")`；
  4. `server/tests/conftest.py` 与 `server/tests/api/conftest.py` 的 TRUNCATE 表名清单。
- 验证标准：空库 `upgrade head` 到顶端 + `pytest tests/migrations/` 全绿。

---

## Naming Conventions

<!-- Table names, column names, index names -->

(To be filled by the team)

---

## Common Mistakes

<!-- Database-related mistakes your team has made -->

(To be filled by the team)
