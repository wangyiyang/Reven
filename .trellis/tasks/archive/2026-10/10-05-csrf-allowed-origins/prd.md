# fix: CSRF Origin 白名单支持 Vercel 前端域

## Goal

web 部署 Vercel 后浏览器 Origin 为 Vercel 域，被 CsrfOriginMiddleware 拒绝（403 csrf_validation_failed）导致无法登录。新增 REVEN_CSRF_ALLOWED_ORIGINS 配置扩展放行 Origin，向后兼容。

关联：issue #120 第一期 PR #200 的实机验证暴露的问题；本任务在同一分支修复后并入该 PR。

## 背景与根因

- `server/src/reven/security/csrf.py:34`：写请求要求 `Origin == settings.public_base_url`（归一化后比较），唯一放行源。
- 前端部署到 `https://reven-web-nine.vercel.app` 后，浏览器 POST 携带该域 Origin，与 `public_base_url=https://dev.wangyiyang.cc` 不匹配 → 403。
- 实机验证：`Origin: https://reven-web-nine.vercel.app` → 403；`Origin: https://dev.wangyiyang.cc` → 401（CSRF 通过）。
- Cookie 无问题：`set_cookie` 无 `Domain` 属性 + `SameSite=Lax`（`server/src/reven/api/routes/auth.py:64-72`），经 Vercel 同源代理可正常种植。

## Requirements

- `Settings`（`server/src/reven/config.py`）新增 `csrf_allowed_origins` 配置：
  - 环境变量 `REVEN_CSRF_ALLOWED_ORIGINS`，逗号分隔多个 origin；
  - 每个值用 `normalize_origin` 校验（与 `public_base_url` 一致），非法值 fail-closed 报错；
  - 默认空列表，行为与现状完全一致（向后兼容）。
- `CsrfOriginMiddleware` 支持额外放行 origins：`Origin` 命中 `public_base_url` 或 `csrf_allowed_origins` 任一即通过。
- `app.py` 装配处把新配置传入中间件。
- 更新 `docs/vercel-deploy.md`：说明 server 需设置 `REVEN_CSRF_ALLOWED_ORIGINS=https://<vercel 域>` 并重启。
- `.env.example` 补充该变量示例。

## Acceptance Criteria

- [ ] 默认配置下现有 CSRF 行为不变（现有 `server/tests/security/test_csrf.py` 全绿）。
- [ ] 新增测试覆盖：白名单内 Origin 放行、白名单外 Origin 仍 403、非法配置值报错。
- [ ] server 测试与 lint/type-check 不回归。
- [ ] 文档与环境变量示例同步更新。

## Notes

- fail-closed 原则保持：无配置、无 Origin、无 CSRF 头时仍一律拒绝。
- server 侧生效需在 VPS 设置环境变量并重启容器（运维动作，文档说明）。
