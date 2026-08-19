# 应用内登录替换 Caddy basic_auth

## 背景

当前整个站点靠 Caddy `basic_auth`（`infra/caddy/Caddyfile`）保护：浏览器原生弹窗、共享账号密码、无法登出。FastAPI 自身没有任何认证，只有 `CsrfOriginMiddleware`。目标是把认证收进应用内，提供正常登录页。

以下决策均来自 2026-08-19 grilling 访谈，已与用户确认。

## 需求与决策

| 决策点 | 结论 |
|---|---|
| 账号模型 | 单账号，不建用户表 |
| 登录页 | 仅密码输入框（无用户名字段） |
| 密码配置 | `REVEN_ADMIN_PASSWORD` 明文环境变量，登录时用 `hmac.compare_digest` 常量时间比较 |
| 未配密码 | 服务拒绝启动（fail-closed）；测试需显式设置测试密码 |
| 会话 | 数据库 `auth_sessions` 表；随机 token 放 HttpOnly/Secure/SameSite=Lax Cookie；库中存 token 的 SHA-256 哈希而非明文 |
| 有效期 | 7 天 + 滑动续期（活跃请求自动延长，闲置 7 天过期） |
| 登出 | 删除会话行，立即失效；前端加登出按钮 |
| 保护范围 | 全部业务 API；只放行 `/api/health` 和 `/api/auth/login`；前端静态资源公开（无数据） |
| 防爆破 | 内存限流：同一 IP 连续失败 5 次锁 15 分钟（重启清零可接受） |
| CSRF | 复用现有 `CsrfOriginMiddleware`（写请求要求 `x-reven-csrf: 1` + Origin 匹配） |
| Caddy | 同批改动删除 `basic_auth` 块 |
| 其他客户端 | 无（bot 不调 API，renderer 内部调用不经 Caddy） |

## 实现路径

### 服务端（server/）

- 全局认证中间件（fail-closed）：白名单放行 `/api/health`、`/api/auth/login`，其余 `/api/*` 请求校验会话 Cookie，无效返回 401
- 新增 `auth_sessions` 表 + Alembic 迁移：`id`(uuid)、`token_hash`、`created_at`、`expires_at`、`last_seen_at`
- 端点：`POST /api/auth/login`（校验密码+限流+签会话）、`POST /api/auth/logout`（删会话）、`GET /api/auth/me`（会话状态探测）
- 配置：`REVEN_ADMIN_PASSWORD` 必填，缺失时启动失败
- 登录限流：内存字典按 IP 计数，5 次失败锁 15 分钟

### 前端（web/）

- 新增 `/login` 路由：仅密码框 + 登录按钮
- fetch 封装遇 401 跳转 `/login?next=<原路径>`，登录成功后回跳
- 页面头部加登出按钮
- 启动时通过 `/api/auth/me` 判断会话状态

### 运维（infra/）

- `infra/caddy/Caddyfile` 删除 `basic_auth` 块
- `.env.example` / compose 文档补充 `REVEN_ADMIN_PASSWORD`

## 验收标准

1. 未登录访问任何业务 API 返回 401；`/api/health` 与 `/api/auth/login` 匿名可访问
2. 正确密码登录成功，Cookie 落盘；错误密码返回 401 且不泄露密码对错之外的信息
3. 连续 5 次失败后同 IP 被锁 15 分钟
4. 登出后原 Cookie 立即失效（401）
5. 滑动续期生效：活跃时会话 expires_at 顺延
6. 未设 `REVEN_ADMIN_PASSWORD` 时服务启动失败并报清晰错误
7. 前端 401 自动跳登录页，登录后回跳原页面；登出按钮可用
8. Caddyfile 中 basic_auth 已移除
9. 服务端与前端既有测试全部通过（测试环境显式配置测试密码）
