# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

### Don't: 请求中途 / tick 中途调用 `get_settings()`

**Problem**：lru_cache 全局 settings 曾在 11 个 module 被拉取，迫使 `app.py` 造出第二个真相源，测试要付 `cache_clear()` + env 清洗 fixture 的税（GH #135）。

**Instead**：`Settings` 只在 `create_app` 组合根解析一次（`get_settings()` 在 src 的唯一调用点）；routes 用 `SettingsDep`、中间件收构造参数、后台组件构造注入；测试显式 `Settings(..., _env_file=None)` 注入，禁止 monkeypatch env + `cache_clear`。

### Don't: module import 副作用改变行为

**Problem**：`register_*_adapter()` 在 routes import 时填充全局 dict，interface 在任何签名里不可见，测试互相污染全局态（GH #134）。

**Instead**：装配关系在组合根以显式字面量/构造参数表达；新增 provider 只改一处 dict。

---

## Required Patterns

<!-- Patterns that must always be used -->

(To be filled by the team)

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)
