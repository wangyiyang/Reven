# Talents MVP 执行计划

实现顺序：迁移/模型 → service/repository → API → 后端测试 → web feature → 导航/路由 → 前端测试。每步完成后跑对应校验。

## Checklist

- [ ] 1. 读规范：`.trellis/spec/reven-server/backend/database-guidelines.md`、`crm-contract.md`；通读 `server/src/reven/crm/{models,repository,service}.py` 与 `server/src/reven/api/{routes,schemas}/crm.py` 作为模板
- [ ] 2. `server/src/reven/talents/`：`models.py`（枚举 StrEnum 中文值 + 两表）、`repository.py`、`service.py`、`__init__.py`（仅 docstring）
- [ ] 3. `server/migrations/versions/0015_talents.py`（down_revision=`0014_merge_crm_and_integration`，CheckConstraint + RLS）+ `server/migrations/env.py` 注册 models
- [ ] 4. `server/src/reven/api/schemas/talents.py` + `server/src/reven/api/routes/talents.py` + `server/src/reven/app.py` 挂载 talents_router
- [ ] 5. 两处 conftest TRUNCATE 清单加表（`server/tests/conftest.py:50`、`server/tests/api/conftest.py:90`，子表→父表）
- [ ] 6. `server/tests/api/test_talents.py`：覆盖 AC1–AC4（CRUD、过滤、枚举参数化、嵌套归属、级联、PATCH null 拒绝、rating 越界、rate 同填同清）
- [ ] 7. `web/src/features/talents/` 全部文件（先查 `features/crm/date-utils.ts` 复用性）
- [ ] 8. `web/src/app.tsx` 路由 + `web/src/components/app-shell.tsx` 导航 + `app-shell.test.tsx` label
- [ ] 9. `talents-page.test.tsx`、`talent-detail-page.test.tsx`

## Validation Commands

```bash
# 后端（需 TEST_DATABASE_URL，CI 同口径）
uv run alembic -c server/migrations/alembic.ini upgrade head
uv run pytest server/tests -q
uv run ruff check server && uv run ruff format --check server
uv run mypy server/src

# 前端
pnpm test
pnpm build
```

## Risky Files / Rollback Points

- `server/migrations/env.py`、两处 `conftest.py`、`server/src/reven/app.py`、`web/src/app.tsx`、`web/src/components/app-shell.tsx` 是共享文件，改动最小化，只加不删
- 回滚点：步骤 3 之后（迁移可独立 downgrade）；步骤 6 之后（后端完整可独立交付）
- 若 `crm-contract.md` 与 design.md 冲突：以规范为准，回写 design.md 后继续

## Pre-start Follow-ups

- `alembic heads` 确认 0014 仍是唯一 head（若 main 前进则调整 down_revision）
