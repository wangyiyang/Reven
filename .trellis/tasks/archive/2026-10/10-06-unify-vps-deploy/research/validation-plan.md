# Research: VPS 统一发布的最小验证组合

- Query: 当前部署测试是否真实运行生产 Caddyfile；恢复 SPA 后如何证明路由、静态资源、只读卷及同源认证契约。
- Scope: mixed；只读检查仓库与官方文档，仅编写本研究文件，不运行部署、登录或产品测试。
- Date: 2026-10-06
- Repository: /Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven；主会话提供的 main 基线 6166389772d7ea61cd562f0546ad577cb81bf275。

## Findings

### 结论

现有 full CI **不运行生产路由的 HTTP 请求测试**：生产 Caddyfile 只做语法校验，真实烟测用独立 self-host 配置。最小补齐方案是恢复生产 SPA/只读挂载、调整现有结构测试和 CI 路径过滤，并在现有 self-host 烟测中增加导入生产 `site_common` 的隔离网关阶段；复用 Browser，不新增框架或 smoke 脚本。

### Files found / 现有证据边界

| 文件与行号 | 作用与边界 |
| --- | --- |
| `.github/workflows/ci.yml:49-58` | backend 路径过滤含 self-host 与 smoke，但缺 `infra/caddy/**`、`infra/compose/**`；仅改生产配置可能跳过 backend 回归。 |
| `.github/workflows/ci.yml:158-170` | container 只在 `inputs.full` 运行，原生 ubuntu-22.04 构建 `reven:test` 后执行已有 self-host 烟测。 |
| `.github/workflows/ci.yml:171-193` | 检查镜像嵌入 infra、fake Docker 部署同步、Compose 渲染和生产 Caddy `validate`；没有请求生产路由。 |
| `scripts/self_host_smoke.py:40-80` | 随机项目、临时凭据、self-host Compose + local override；`--no-build --pull never`，使用本地测试镜像。 |
| `scripts/self_host_smoke.py:185-215` | TLS 也读取 `infra/self-host/Caddyfile`，只为测试加 internal TLS、loopback 端口并信任导出的 CA。 |
| `scripts/self_host_smoke.py:218-243` | 原生 Linux AMD64 门禁、故障后项目清理与已有执行入口；不部署生产。 |
| `scripts/self_host_http_smoke.py:22-70` | 可复用 HTTP 客户端、CookieJar、可信 TLS、首页/health/me/MCP 拒绝与同源/缺头/异源 CSRF 检查。 |
| `scripts/self_host_http_smoke.py:107-118` | 注销、旧 Cookie 重放及 Secure/HttpOnly/SameSite/Path/无 Domain 验证。 |
| `server/tests/e2e/test_http_deployment.py:8-46` | 读取生产 Caddy 文本/YAML，不启动 Caddy；纯 API / 无静态卷的两个断言需按新契约替换。 |
| `server/tests/e2e/test_self_host_deployment.py:33-42,86-111` | 真实 Compose config 渲染或文本断言，目标仅 self-host；无 HTTP 容器请求。 |
| `server/tests/security/test_deployment_automation.py:7-159` | CI/release/部署脚本结构断言；可复用路径过滤回归和 full-only 容器门禁。 |
| `server/tests/security/test_self_host_smoke.py:18-81` | 烟测失败清理、项目隔离、原生架构、环境秘密隔离；增加阶段时补该阶段失败清理验证。 |
| `server/tests/security/test_auth.py:33-63,83-123,300-311` | TestClient + 隔离 PostgreSQL：Cookie/会话/代理 origin；不经过 Caddy。 |
| `server/tests/security/test_csrf.py:18-101,104-157` | TestClient：同源/缺头/异源/伪造转发头拒绝；HTTPS 中间件部分无需数据库。 |
| `server/tests/security/test_headers.py:18-65` | 仅应用中间件响应头，不能证明 Caddy 直出静态页响应头。 |
| `scripts/smoke.sh:9-24` | 只接受 HTTP，只检查 health；不能当作生产 HTTPS/SPA 验收工具。 |
| `scripts/test_deploy_reven.sh:44-107,117-215` | fake Docker 验证配置同步/恢复与镜像历史，不是真实网关或 HTTP 验收。 |
| `scripts/deploy_reven.sh:173-201` | 现有上线健康门禁仅应用容器内 `/api/health`；其成功不能证明 Caddy 静态资源可读。 |
| `infra/docker/entrypoint.sh:8-31` | 应用镜像生成并原子切换 `/srv/reven/current`，无需新增前端发布机制。 |
| `web/src/lib/api.ts:17-25` | 前端相对 `/api` 请求，写请求已带 CSRF 头；统一域名不需重写 API 客户端。 |

### Code patterns / 生产恢复边界

1. `infra/caddy/Caddyfile:17-24` 当前仅 `/api/*` reverse proxy + 非 API 404。恢复后保持 API 独立 handle，并将 `/assets/*` 与 SPA fallback 分为互斥 handle。
2. `infra/self-host/Caddyfile:14-29` 已有三段可复用规则：`/agent/*` 显式 404；assets 无 `try_files`、只 file_server + immutable；普通页面 `try_files {path} /index.html` + no-cache。
3. **必须保留 `/agent/*` 显式 404。** 若直接恢复全路径 SPA fallback，GET `/agent/mcp` 会变成 200 HTML，虽没有反代内部 MCP，仍破坏明确 404 契约。用 self-host 现有规则最小补齐。
4. **缺失 `/assets/...` 必须 404。** assets handle 不使用 `try_files`，不经 SPA fallback；避免返回 index.html 导致 MIME 错误与假成功。
5. `infra/compose/docker-compose.yml:19-23,61-76,78-83` 应用静态卷仍存在，Caddy 缺该卷；只需恢复 `reven-static:/srv/reven:ro`，保留其它安全设置。
6. 最小 CI 修复：backend filters 加 `infra/caddy/**`、`infra/compose/**`，在 `test_deployment_automation.py:143-159` 的实际 fnmatch 回归中加两条生产路径；**不改变 container 的 full-only 条件**。

### 建议的最小验证矩阵

| 层级 | 最小验证 | 能证明 / 限制 |
| --- | --- | --- |
| 本地结构与回归 | 生产 Caddy/Compose 测试、CI 路径过滤与清理回归、部署 fake Docker 烟测、actionlint、前端 build | 配置与触发规则正确；不是 HTTP 行为或线上运行证明。 |
| 原生 Linux AMD64 full CI | 现有 full CI，扩展现有 smoke 的 production gateway 阶段 | 运行生产路由 snippet，真实镜像静态产物、TLS、Cookie/CSRF、只读卷；不是公网 ACME 或生产 Compose 全栈验收。 |
| 线上切换后只读 | 可信 HTTPS GET 首页/深链接/实际 index 引用 assets/health/匿名 me/agent/缺失 assets | 线上入口实际可用与静态缓存正确；不做错误密码、登录或业务写入，不声称已验证线上写操作。 |

full smoke 的生产网关阶段建议：复用现有隔离 PostgreSQL/Reven/卷、随机项目和清理，临时 Caddyfile 从 **生产文件导入原样 `site_common`**，只将顶层站点改成 loopback 测试站点并用 internal TLS；不得复制路由到另一份测试模板，以免测试旧副本。测试覆盖如下：

- `/api/health` 为 200 JSON 且内容 `service=reven,status=ok`；匿名 `/api/auth/me` 为 401 JSON，不得落到 SPA。未知 API 若验证 404，应在隔离成功登录后发 GET，避免应用认证中间件先返回 401。
- `/`、`/login` 和 `/crm/customers/smoke-customer` 为 200 HTML、内容相同的构建 index，`Cache-Control: no-cache`；后两者为真实前端路由（`web/src/routes.tsx:45-48`）。
- 从 index 提取实际 script/link 引用的 JS、CSS，确保引用非空且都可取；JS 为 JavaScript MIME（允许 text/javascript 或 application/javascript）、CSS 为 text/css，均非 HTML、非空且含 immutable/max-age=31536000。
- `/assets/__reven_smoke_missing__.js` 为 404，不是 index；GET 与 POST `/agent/mcp` 均为 404。
- 首页与 assets 有现有 nosniff/CSP 等安全头；API 既有安全头无重复。不要新增 HSTS，仍保留 HTTP 过渡入口。
- 通过 `docker inspect` 对 Caddy/Reven 的 `/srv/reven` Mounts 验证 Source/Name 相同、Caddy `RW=false`、Reven `RW=true`，并检查生产 Compose 声明确实为同一共享卷 + `:ro`。只检查容器根目录 readonly 不足以证明挂载 readonly（现有 assert_runtime 仅检查 Reven HostConfig，`self_host_smoke.py:82-90`）。
- 核对 `/srv/reven/current/.release` 与 `/app/web-dist/.release`、HTTP index 与本镜像 index 一致，证明静态产物来自同一镜像。
- 复用 Browser.login/logout 的隔离凭据验证同源 CSRF、缺头/异源拒绝、HTTPS Secure Cookie 与登录后 GET；不删除原有 allowlist 安全回归。HTTPS 阶段全程使用显式信任的测试 CA，不能 `-k`。

### 建议命令（仅规划，未运行）

本地先运行不依赖真实数据库的聚焦检查：

```bash
uv run pytest server/tests/e2e/test_http_deployment.py server/tests/security/test_deployment_automation.py server/tests/security/test_self_host_smoke.py
sh scripts/test_deploy_reven.sh
actionlint .github/workflows/ci.yml
pnpm --filter @reven/web build
```

改动 smoke Python 时同时使用现有 ruff 规则检查对应脚本和测试。应用 Cookie/CSRF/headers 回归只在已迁移的**专用隔离 PostgreSQL** 下运行：

```bash
uv run pytest server/tests/security/test_auth.py server/tests/security/test_csrf.py server/tests/security/test_headers.py
```

该命令需已有 `TEST_DATABASE_URL`；未设置时 DB fixture 会 skip（`test_auth.py:35-37`），skip 不计认证验收成功；不能指向生产或共享业务数据库，fixture 会 TRUNCATE（`test_auth.py:49-53`、`server/tests/conftest.py:25-43`）。

合并前选功能分支手动 full CI，复用现有入口，无部署：

```bash
gh workflow run ci.yml --ref <功能分支名> -f full=true
```

若原生 Linux AMD64 本地已按照 CI 构建 `reven:test`、拉取两项固定 digest 依赖，直接使用 `python3 scripts/self_host_smoke.py`；不将 Mac/ARM 仿真结果算作正式 full 证据。

线上只读核查示例（其它 JS/CSS URL 从当次 index 中获取）：

```bash
curl --fail --silent --show-error -D - -o /dev/null https://dev.wangyiyang.cc/
curl --fail --silent --show-error -D - -o /dev/null https://dev.wangyiyang.cc/login
curl --fail --silent --show-error https://dev.wangyiyang.cc/api/health
curl --silent --show-error -o /dev/null -w '%{http_code}\n' https://dev.wangyiyang.cc/assets/__reven_smoke_missing__.js
curl --silent --show-error -o /dev/null -w '%{http_code}\n' https://dev.wangyiyang.cc/agent/mcp
```

### External references / versions

- 项目固定 Caddy **2.10.0-alpine** digest，见 `infra/compose/docker-compose.yml:45`；验证使用同一镜像，不顺带升级。
- [Caddy handle 官方文档](https://caddyserver.com/docs/caddyfile/directives/handle)：同级 handle 互斥，无 matcher 的 handle 为 fallback。
- [Caddy file_server 官方文档](https://caddyserver.com/docs/caddyfile/directives/file_server)：缺失文件产生 404；静态 root 与 URI 组合定位文件。
- [Caddy try_files 官方文档](https://caddyserver.com/docs/caddyfile/directives/try_files)：重写到首个存在文件，说明为何 SPA fallback 必须限制在普通页面分支。
- 以上官方网页于 2026-10-06 检查，文档不是版本固定快照，最终行为以项目固定 Caddy 镜像的隔离请求证据为准。

### Related specs

- `.trellis/spec/reven-server/backend/ci-release-contract.md:18-24,47-58,74-84`：普通 PR 不构建容器、full gate/原生 AMD64、隔离 fixture、可信 CA 与故障清理；规划需补生产 gateway 阶段与 backend 路径覆盖。
- `.trellis/spec/reven-server/backend/open-source-self-host-contract.md` 的“Origin 与浏览器认证”“必须覆盖的测试与证据”：CSRF 精确同源/白名单、Secure Cookie、内部 `/agent/*` 404、独立数据库与验证证据边界。统一 VPS 不要求删除 CSRF 白名单能力。

## Caveats / Not Found

- 本研究没有运行容器、测试、线上请求或真实部署；以上为代码/文档核查与待实施验收建议。
- 未发现已有深链接、实际 assets MIME/缓存、缺失 assets 404 的真实 HTTP 断言，也未发现生产 Caddy 路由的真实容器烟测。
- 复用 self-host 应用栈并运行生产 snippet，可覆盖路由行为；生产 Compose 的平台、外部 Supabase、ACME、真实数据卷仍依赖配置检查与切换后的只读验收，不能混称整个生产栈已做隔离验证。
- 部署脚本当前只探应用内 health；如果本任务不扩展部署脚本，必须将 Caddy/SPA 只读验收列为明确发布后验收步骤。fake Docker smoke 不能补这个证据缺口。
