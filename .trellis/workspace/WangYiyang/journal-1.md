# Journal - WangYiyang (Part 1)

> AI development session journal
> Started: 2026-08-19

---



## Session 1: 应用内登录替换 Caddy basic_auth

**Date**: 2026-08-19
**Task**: 应用内登录替换 Caddy basic_auth
**Package**: web
**Branch**: `main`

### Summary

grilling 访谈收敛需求后经 Trellis 任务 08-19-app-login 实现：单账号密码登录（login/logout/me + 会话表 + 7 天滑动续期 + 5 次失败锁 15 分钟 + fail-closed 中间件），前端 /login 页与 401 回跳、登出按钮，移除 Caddy basic_auth 并同步 smoke/runbook/CI。验证：服务端 560 passed、前端 67 passed、tsc/build/ruff 通过。同轮提交纳入 Trellis 脚手架。

### Git Commits

| Hash | Message |
|------|---------|
| `1e50372` | (see git log) |
| `38c6fbb` | (see git log) |

### Status

[OK] **Completed**
