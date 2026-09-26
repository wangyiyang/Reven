# Research: 开源 Alpha 的 HTTPS 与通用自托管部署设计

- Query: 在保持现有 HTTP/ACR 生产部署兼容的前提下，支持 HTTPS origin、正确 CSRF/Cookie，以及 Linux AMD64 上从源码构建的 Postgres 17 + Caddy + Reven 自托管方案。
- Scope: mixed；本地配置、认证、部署脚本、测试与官方容器文档。数据库能力采用 `bootstrap-facts.md` 的已知结论，不重复验证。
- Date: 2026-09-21
- 工作目录：`/Users/wangyiyang/Documents/Github/worktrees/Reven/codex/gh-127-open-source-alpha`。
- 研究边界：未读取真实 `.env` 或凭据，未执行 Git 操作、部署、数据库迁移或容器启动；仅写本文件。文中新增路径与命令属于实施建议，尚未存在或执行。

## Findings

### 结论与最小方案

建议新增独立的 `infra/self-host/` Compose、Caddyfile 和无真实凭据的配置示例，复用现有 Dockerfile 与 entrypoint。现有 `infra/compose/docker-compose.yml`、`infra/caddy/Caddyfile`、ACR 验证与自动部署脚本继续服务维护者生产环境。这样可以增加公开安装路径，同时保留已有 HTTP 行为与回滚契约。

应用层只需调整 public origin 校验及 Cookie 判断，并补足 HTTP/HTTPS 行为测试。不要仅将校验中的 `http` 改成 `{http, https}`：现有 Cookie 使用原始字符串前缀判断，存在大小写差异导致未设置 `Secure` 的隐患。

首次使用范围仍为 RSS → 人工筛选 → Notion；无需新增对象存储、调度机制、发布平台或多架构支持。

### 文件清单与代码模式

| 文件 | 职责与证据 |
| --- | --- |
| `server/src/reven/config.py:17` | public origin 默认值、两个环境变量别名；`:44` 当前仅允许 HTTP。 |
| `server/src/reven/security/csrf.py:24` | 写操作要求 Origin 与 `X-Reven-CSRF: 1`；`:49` 已解析 HTTP/HTTPS 和默认端口。 |
| `server/src/reven/api/routes/auth.py:67` | 登录 Cookie；`:72` 用字符串前缀决定 Secure；`:86` 注销删除 Cookie。 |
| `server/src/reven/app.py:219` | 应用可注入 CSRF origin；认证读取 Settings，与这个注入参数不是同一入口。 |
| `server/src/reven/rss/factory.py:126`、`:170` | 使用 public origin 生成候选列表通知链接。 |
| `server/src/reven/publishing/factory.py:120` | 将 Settings 的 public origin 传入交付状态存储。 |
| `server/src/reven/publishing/delivery_store.py:28` | 交付链接构造器另有旧 HTTP 默认值；实际工厂显式传参。 |
| `web/src/lib/api.ts:17` | 相对 `/api` 请求，写操作统一添加 CSRF 头；同源 HTTPS 无需新增前端 API 域名配置。 |
| `infra/compose/docker-compose.yml:1` | 旧 ACR digest 镜像、数据卷、非特权/只读/资源限制、HTTP 3001 Caddy。 |
| `infra/caddy/Caddyfile:1` | 固定旧 HTTP 地址；`:5` 安全头，`:12` API 代理，`:18` 指纹缓存，`:24` SPA 回退。 |
| `infra/docker/Dockerfile:45` | UID 10001 与预先 chown 的可写目录；`:63` 把整个 infra 打入发布镜像；`:69` 切换非 root。 |
| `infra/docker/Dockerfile.dockerignore:1` | 当前仅根目录形式的 `.env`、`.env.*` 忽略规则；嵌套配置需补规则。 |
| `infra/docker/entrypoint.sh:8` | 先锁定静态目录、迁移，再切换静态版本，最后启动单 worker Uvicorn。 |
| `scripts/validate_reven_image.sh:5` | 只接受维护者 ACR 仓库的 sha256 digest。 |
| `scripts/deploy_reven.sh:40` | 独立重复执行相同仓库/digest 校验；`:92` 拉取后核对 RepoDigest。 |
| `scripts/deploy_reven.sh:115` | 要求镜像导出的旧 infra 路径存在；`:247` 仅比较旧 Caddyfile 决定 reload。 |
| `scripts/test_deploy_reven.sh:139` | fake Docker 覆盖配置保护、基础设施同步、健康失败恢复与回滚。 |
| `server/tests/test_config.py:24` | HTTP 接受测试；`:36` 当前把 HTTPS 当非法输入。 |
| `server/tests/security/test_auth.py:77` | 只验证 HTTP Cookie 无 Secure；`:99` 注销使会话失效。 |
| `server/tests/security/test_csrf.py:65` | Origin、头缺失、跨站与协议不匹配的 fail-closed 测试。 |
| `server/tests/e2e/test_http_deployment.py:8` | 静态结构测试，硬性要求旧 Caddyfile HTTP、3001、无 HSTS；并非真实浏览器 E2E。 |
| `server/tests/security/test_deployment_automation.py:60` | 明确要求保留 ACR 限制、完整健康门禁、镜像内 infra、回滚方式。 |
| `.github/workflows/ci.yml:168` | 容器只在 full 模式构建；`:174`、`:209` 额外放宽 AppArmor；`:229` 验证迁移失败保留旧静态版本。 |
| `server/src/reven/publishing/sandbox.py:30` | bubblewrap 强制隔离、按需绑定路径、默认无网络与资源限制。 |
| `scripts/container_security_smoke.py:16` | 真实博客构建与恶意 fixture 沙箱行为验证。 |
| `docs/runbook.md:1` | 现有维护者专用运维手册；`:85` 明确不允许移除沙箱或赋予容器特权绕过宿主限制。 |

### Origin、CSRF 与 Cookie 实施契约

1. `REVEN_PUBLIC_BASE_URL` 优先于兼容别名 `PUBLIC_BASE_URL`，保留这个优先级。为最小兼容，暂时保留 Settings 旧默认值，但新的 self-host Compose 必须显式提供自己的 origin，不能隐式落回维护者域名。若主会话选择改成 localhost 默认，必须同时给旧 Compose 注入原默认值并验证遗漏环境变量的旧部署，不能仅替换全局默认。
2. 允许 HTTP 与 HTTPS origin，继续拒绝 userinfo、路径（根 `/` 可规范化去掉）、查询与片段。必须访问 `parsed.port` 以拒绝非数字或超范围端口；当前 Settings 未做这一步，错误直到 CSRF 请求才暴露。建议明确拒绝端口 0。
3. 使用解析后的 scheme 判断 Secure，或保证校验返回统一的小写 scheme；不要保留未经规范化的值再做 `startswith("https://")`。本轮对固定非敏感字符串的标准库探针确认：`urlsplit("HTTPS://example.com").scheme == "https"`，但原字符串的 `startswith("https://")` 为 False。空白/控制字符应拒绝，避免解析器宽松处理与配置文件解释不一致。
4. CSRF 已支持 scheme/host/有效端口精确比对，不需要新增 CORS、通配子域或依据请求 Host 自动信任来源。若提取共用 origin helper，位置应为独立小模块，避免让 config 导入当前依赖 config 的 csrf 而形成循环。不要扩展成通用 URL 框架。
5. `_origin` 当前用 `parsed.port or default`，会把 0 当成缺省端口；若处理端口 0，配置与请求端应一致。HTTPS 缺省端口与 `:443` 等价，HTTP 与 HTTPS、不同端口均不等价。
6. Cookie 保持 `HttpOnly`、`SameSite=Lax`、`Path=/`、无 Domain；HTTPS 添加 Secure，HTTP 保持当前行为。注销应在删除服务端会话后发出过期 Cookie，可与登录保持同一属性计算。Cookie 删除依赖 name/path/domain 匹配，不应把当前注销未带 Secure 误报成已证实的注销失败。
7. Cookie 安全性以受信配置中的外部 origin 决定，不能根据 Uvicorn 内部 HTTP 请求决定。Caddy 终止 TLS 后仍通过 `reven:8000` 转发是预期设计。现有同源 API/链接不需要为此扩大 `--forwarded-allow-ips` 信任范围。
8. 保留 `/agent/mcp` Bearer 豁免及默认 loopback 地址；Caddy 只代理 `/api/*`，不要顺带暴露这个内部机器端点。注意登录限流读取 `X-Forwarded-For`（`auth.py:30`）；Reven 的 8000 端口必须继续不发布到宿主，Caddy 是对外入口。
9. `cos_public_base_url`、COS configuration 的同名字段不是应用 origin；保持其 HTTPS 资源地址校验，不应通过全局搜索替换扩大修改范围。

Caddy 默认处理 `X-Forwarded-*` 并忽略不可信来路值；本次不增加 CDN/多层代理配置，若用户自行加 CDN，需要额外确定可信代理范围。[Caddy 反向代理头规则](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#defaults)

### 新增通用 Compose 的建议形态

建议新增路径：`infra/self-host/docker-compose.yml`、`infra/self-host/Caddyfile`、`infra/self-host/.env.example`，以及 `docs/self-hosting.md`。这组文件直接在源码 checkout 下运行，不使用 `scripts/deploy_reven.sh`。

| 服务 | 最小配置 |
| --- | --- |
| postgres | PostgreSQL 17，沿用 CI 已固定的镜像 digest；持久卷挂 `/var/lib/postgresql/data`；`pg_isready` 健康检查；不发布 5432。 |
| reven | `platform: linux/amd64`；`build.context: ../..` 与 `dockerfile: infra/docker/Dockerfile`；可省略 image 让 Compose 管理本地构建名；等待 postgres healthy；显式提供基础变量。 |
| caddy | 复用当前固定版本/digest；只接受非秘密的 public origin 环境变量；等待 reven healthy；公开 80/443 TCP（443 UDP 非首次验收必需）；保持证书数据与配置卷。 |

Postgres 当前固定引用可从 `.github/workflows/ci.yml:73` 复用，不需要调查其他托管数据库。新 PostgreSQL 卷初始化需保留官方镜像本身的权限/用户流程，不能机械复制 Reven 的非 root、只读与 cap_drop 设置。

Reven 保留现有 `/data`、`/data/dsh`、`/srv/reven` 卷及 `DSH_HOME=/data/dsh`、`read_only`、tmpfs、2 GiB/2 CPU/128 PID 限制、`cap_drop: ALL`、`no-new-privileges` 与相对 `../docker/seccomp-bwrap.json`。先不增设自定义网络、初始化服务或额外 root chown 容器。

配置必须区分 Compose 插值与容器环境：`--env-file` 只为 Compose 提供插值，不自动把所有变量传给容器。建议逐项映射 Reven 必需的数据库 URL、主密钥、管理员密码、public origin、DSH_HOME；可选集成变量按文档显式映射。禁止给 Caddy/Postgres 直接传整份 Reven 秘密配置。

若从 `POSTGRES_PASSWORD` 直接拼接 asyncpg URL，首次指南应使用随机 hex 密码，例如 `openssl rand -hex 32`；任意密码中的 `@`、`/`、`:`、`#` 等字符需要 URI 转义，不应承诺所有自选密码都能直接插值。基础数据库名与用户名固定为 `reven` 即可，不为 Alpha 增加无需求的可配置项。变更已初始化卷的 POSTGRES_PASSWORD 不会自动修改数据库内已有角色密码，升级文档必须保留原值或单独说明轮换。

新 Caddyfile 可用 `{$REVEN_PUBLIC_BASE_URL}` 作为站点地址，与后端使用同一个显式 origin。公开安装指南限定 `https://真实域名`、标准 443，要求 DNS 指向服务器且 80/443 可达；不承诺 IP 地址公信证书、子路径部署、已有负载均衡器或任意自定义端口的开箱即用。Caddy 自动续签与 HTTP 跳转依赖持久可写的证书数据目录。[Caddy 自动 HTTPS](https://caddyserver.com/docs/automatic-https)

新 Caddyfile 复制并维护现有 API 代理、SPA fallback、静态缓存与安全头语义即可。不要为减少约 30 行配置重复而把旧 Caddyfile 改成 import：当前部署脚本只比较主 Caddyfile 是否变化，新增共享片段会牵连 reload 与回滚检测。旧 HTTP 文件继续无 HSTS；若新 HTTPS 路径添加 HSTS，仅限该路径，不加 preload/includeSubDomains 之类未经需求确认的域级策略。

Caddy 站点变量必须使用 Caddyfile 的 `{$VAR}` 语法；它在解析前替换，可扩展为多个 token，因此应把环境配置当受信运维输入，并拒绝多地址/空白形式的 origin。[Caddyfile 地址与变量](https://caddyserver.com/docs/caddyfile/concepts#environment-variables)

### 镜像校验分界与凭据排除

- ACR 校验目前存在两处：独立 `validate_reven_image.sh` 和部署脚本自身 `validate_image_reference`。只改前者不会开放部署脚本，也不应为了本地构建把二者改成任意 tag。
- self-host 的本地 build 没有 registry RepoDigest 是正常情况；源码 commit/tag、锁文件、固定 base image，以及最终本地 image ID 是该路径的追溯证据。不要伪造 registry digest，也不要声称 apt/gem 安装过程因此已达到字节级可复现。
- 保留 `COPY infra/ /opt/reven-release/infra/` 与旧 infra 必需路径，使维护者发布镜像继续携带准确版本的部署配置；新增 self-host 文件被一并带入是兼容的。
- **新增嵌套 `.env` 的泄露风险必须处理。** 当前 Dockerfile-specific ignore 仅写 `.env`、`.env.*`，不覆盖任意层级。若指南让用户创建 `infra/self-host/.env`，`COPY infra/` 可能把它带入运行镜像。将规则改成 `**/.env`、`**/.env.*`，最后仅放行 `!**/.env.example`，并用无敏感内容的嵌套假文件验证最终镜像不含这些路径。
- 修改的是 `infra/docker/Dockerfile.dockerignore`：Dockerfile 专属 ignore 优先于根 `.dockerignore`，只补根文件没有效果。不要依赖 `.gitignore` 防止进入镜像。[Docker 构建上下文与 ignore 规则](https://docs.docker.com/build/concepts/context/#dockerignore-files)

### entrypoint 与空数据卷权限

`Dockerfile:45–47` 已将 `/data/jobs`、`/data/dsh`、`/srv/reven` 分配给 UID 10001。新建 Docker named volume 默认继承镜像挂载目录内容；保留这一模式，不换成宿主目录 bind mount，也不使用 `volume-nocopy`。[Docker volumes](https://docs.docker.com/engine/storage/volumes/#mounting-a-volume-over-existing-data)

要验证的实际行为是：UID 10001 能创建 `/srv/reven/releases` 与 `.startup.lock`、写入 job/dsh 目录；Caddy 能只读访问 `current/index.html`；重启后数据/主密钥关联仍正确。根目录只读不妨碍这些被单独挂载为可写的卷。

entrypoint 在 migration 之前打开静态锁，在迁移成功后才原子替换 current；因此权限不对会在迁移前失败，数据库不可用会阻止服务与新静态版本上线。加 postgres `service_healthy` 解决首次启动顺序，不取代 Alembic fail-fast；不用给 entrypoint 添加吞错等待循环。[Compose 健康依赖顺序](https://docs.docker.com/compose/how-tos/startup-order/)

已有非空卷的权限不会因重建镜像自动修正，恢复备份时要保留数值 UID/GID。Caddy 的 `NET_BIND_SERVICE` 必须继续保留：现有 Compose 与回归测试明确指出其镜像二进制 filecap 在缺少 bounding capability 时会 exec 失败，即使只用高端口也一样。

### bubblewrap 与平台限制

- 博客工厂 `publishing/blog/factory.py:74` 显式使用 `/usr/bin/bwrap`；微信实际 renderer 通过 bwrap 运行，不能用裸 `node cli.mjs` 冒烟代替沙箱验证。
- `sandbox.py` 默认 `--unshare-all`、`--cap-drop ALL`，仅指定目录可写、系统目录只读、空 `/proc`，资源 profile 配合容器限制。二进制缺失/命名空间失败应明确失败，不新增跳过沙箱配置。
- seccomp 文件已覆盖 x86_64 与 AArch64 架构映射，但它只能允许 syscall，不能消除宿主 AppArmor/user namespace 限制。不得因为 archMap 有 AArch64 就宣称 ARM64 支持。
- CI 在容器烟测前执行 `kernel.apparmor_restrict_unprivileged_userns=0`，且 docker run 另带 `apparmor=unconfined`；正式 Compose 没有这项。**因此现有 CI 通过不足以证明新用户按默认 Compose 就能运行博客/微信沙箱。**
- Alpha 可明确要求 Linux AMD64 宿主允许非特权 user namespaces；先让支持宿主通过与文档相同安全参数的真实测试。遇 AppArmor 阻断应使用宿主定向 profile/受控运维配置另行解决，不能把全局关闭 AppArmor 或 privileged/SYS_ADMIN 当默认 Quick Start。
- bubblewrap 是构造沙箱的工具，安全性取决于调用参数；本项目应继续以其既有参数与攻击 fixture 实测为准。[bubblewrap 官方说明](https://github.com/containers/bubblewrap/blob/main/README.md)
- 主会话补充：当前可用 Docker daemon 为 linux/aarch64。该环境只能提供有限静态/跨架构辅助检查，正式 Linux AMD64 和宿主沙箱证据仍需要独立 AMD64 runner；QEMU 运行成功不能替代宿主支持声明。

### 最小有意义的验证矩阵

| 层次 | 必须验证 | 现有位置/新增建议 |
| --- | --- | --- |
| 配置 | HTTP、HTTPS、别名优先级、规范化 scheme、根斜杠、合法自定义端口；拒绝非法 port/userinfo/path/query/fragment | 扩充 `test_config.py`；确保测试清除两个 origin 环境别名并使用 `_env_file=None`。 |
| CSRF | HTTPS 同源写成功、`:443` 等价；HTTP→HTTPS 降级/跨站/不同端口/缺头拒绝；MCP 豁免保持 | 扩充 `test_csrf.py`；可用无 DB 的最小 middleware app 测纯 Origin 行为。 |
| 会话 | HTTPS 登录 Cookie Secure/HttpOnly/Lax/path、认证访问、注销后 401；HTTP 原行为 | 参数化 `test_auth.py` fixture，同时设置 Settings origin、create_app origin 与 TestClient HTTPS base_url，避免 Secure cookie 被 HTTP TestClient 丢弃。 |
| 旧部署兼容 | 旧 HTTP 3001/no HSTS、ACR digest only、镜像内 infra、健康失败恢复 | 既有 HTTP/automation 测试 + `scripts/test_deploy_reven.sh`。 |
| 新部署结构 | 源码 build 路径、固定公开依赖镜像、数据库健康依赖、无 5432/8000 宿主暴露、只给 Caddy origin、权限与资源限制 | 新增针对 self-host 配置的结构测试；不覆盖或改名冒充旧测试。 |
| 新部署运行 | 空卷启动、自动迁移、静态首页、健康与认证、重启后数据、失败迁移不切静态、镜像无嵌套配置 | 在独立 Linux AMD64 临时项目上执行；不能只 `compose config`。 |
| TLS 入口 | HTTP 跳 HTTPS、可信 HTTPS 握手、浏览器登录/注销与写操作；Cookie 属性可观察 | 单独 DNS/测试域名，或测试专用 Caddy CA 并给客户端正确安装信任；不要用 `curl -k` 当可信 TLS 证明。 |
| 沙箱 | 使用新 Compose 实际安全参数通过 renderer 与真实 blog fixture；宿主限制造成失败时明确报告 | 复用 container CI 与 `container_security_smoke.py`。 |

建议实施阶段按顺序执行（这里只列命令，未执行；数据库必须是隔离测试实例）：

```sh
uv sync --frozen --all-packages
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
uv run pytest server/tests/test_config.py server/tests/e2e/test_http_deployment.py server/tests/security/test_deployment_automation.py
sh scripts/test_deploy_reven.sh
```

认证行为测试前，使用现有 `infra/test/docker-compose.yml` 的临时 PostgreSQL，提供该测试库的 `DATABASE_URL`/`TEST_DATABASE_URL` 并执行迁移；这些 fixture 会 TRUNCATE 业务与认证表（`server/tests/conftest.py:67`、`test_auth.py:44`），绝不能指向现有用户数据。

```sh
uv run alembic -c server/migrations/alembic.ini upgrade head
uv run pytest server/tests/security/test_auth.py server/tests/security/test_csrf.py server/tests/security/test_headers.py server/tests/publishing/test_sandbox.py
```

新增 Compose 的后续验收命令形态如下，`REVEN_SELFHOST_ENV` 是实施时准备的测试配置文件路径，不是当前仓库真实配置：

```sh
docker compose -p reven-oss-check --env-file "$REVEN_SELFHOST_ENV" -f infra/self-host/docker-compose.yml config --quiet
docker compose -p reven-oss-check --env-file "$REVEN_SELFHOST_ENV" -f infra/self-host/docker-compose.yml build reven
docker compose -p reven-oss-check --env-file "$REVEN_SELFHOST_ENV" -f infra/self-host/docker-compose.yml up -d --wait
docker compose -p reven-oss-check --env-file "$REVEN_SELFHOST_ENV" -f infra/self-host/docker-compose.yml exec -T reven id -u
docker compose -p reven-oss-check --env-file "$REVEN_SELFHOST_ENV" -f infra/self-host/docker-compose.yml exec -T caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

`config --quiet` 避免输出插值后的秘密。Caddy validate 不证明证书签发成功；Reven `/api/health` 返回常量（`app.py:257`），不证明 RSS/Notion 或沙箱可用。后续必须按上表补实际请求验证。使用独立 project 名防止和维护者旧 Compose 卷/容器冲突。

CI 路由注意：普通 PR 不构建容器是现有明确契约，不通过放开 `container.if` 解决新部署验收。可在 full container 任务补 self-host 验证，首次 Alpha 另外留 AMD64 验收证据。新增结构测试若希望未来 infra-only PR 自动运行，应把相关 `infra/self-host/**`/Dockerfile-ignore 路径加入 backend 路径过滤；当前 backend 只识别 server、pyproject、uv.lock、ci.yml（`:43`），否则 infra-only 变更可能跳过这些测试。

### 升级、备份与回滚边界

最小文档必须说明备份数据库、`/data`（包括 dsh）、配置中的主密钥与密码，以及需要保留的 Caddy 证书数据；数据库备份不能代替主密钥。self-host 源码升级应记录源版本与本地 image ID，先备份再重建。

entrypoint 每次自动迁移，新镜像迁移失败或后续启动失败都不意味着旧镜像能直接回滚数据库。现有 `deploy_reven.sh:218` 已明确禁止失败后自动重启旧 Reven 镜像，因为目标版本可能已迁移。self-host 文档必须同样区分“退回应用版本”和“恢复兼容数据库备份”，不能承诺一条 `git checkout`/重建命令实现安全数据库回滚。

### Related specs

- `.trellis/workflow.md`：规划先于实现、研究持久化、复杂任务设计与实施清单分离；本轮仅研究。
- `.trellis/spec/reven-server/backend/ci-release-contract.md`：普通 CI 不构建容器，full 容器/沙箱/SBOM/漏洞检查保留；不触发现网部署。
- `.trellis/spec/reven-server/backend/agent-dsh-contract.md`：DSH_HOME 卷、MCP loopback/Bearer、配置变更重启与 Agent 降级语义。
- `.trellis/spec/reven-server/backend/brand-publishing-contract.md`：无配置时保留 legacy 行为、COS/Notion 缺配置显式反馈；不将本次部署工作扩展为发布流程改造。
- `.trellis/spec/reven-server/backend/quality-guidelines.md` 当前仍为占位模板，实际质量命令以根 pyproject 与 CI 为准。
- 实施后建议增加 self-host/HTTPS 专用契约，明确两条部署路径与支持平台；研究代理不修改 spec。

### External references / versions

- Caddy 镜像当前仓库固定为 `2.10.0-alpine` + digest；官网为当前文档，本文只采用该版本已存在的自动 HTTPS、环境变量、反向代理头语义，不要求升级到文档提及的 2.11 新功能。
- PostgreSQL 17 镜像采用当前 CI 固定版本；未自行升级大版本。
- Docker Compose V2 的 build、platform、health dependency 与 named volumes：[构建规范](https://docs.docker.com/reference/compose-file/build/)、[启动顺序](https://docs.docker.com/compose/how-tos/startup-order/)、[数据卷](https://docs.docker.com/engine/storage/volumes/)。正式最低 Compose 版本应按实际验收记录，不凭当前机器版本推断。
- Python 应用目标 `>=3.12`、容器为 Python 3.12，配置用 `pydantic-settings>=2.10,<3`，Web 为 FastAPI/Starlette；实际锁定依赖见 `uv.lock`，本轮未升级依赖。

## Caveats / Not Found

- 本文件提供可实施的方案与检查点，不构成 HTTPS、空卷权限、AMD64 构建或真实第三方链路已经通过的验收报告。
- 目前未找到通过真实 HTTPS 入口的浏览器测试，也未找到原生产 Compose 安全参数在未经 AppArmor 放宽的干净 AMD64 宿主上的沙箱验收证据。
- 新用户使用真实 Notion 仍需要自己的集成权限与指定测试目标；真实写入由主会话授权范围决定。本轮没有调用任何外部账号。
- 主会话补充并决定保留：RSS 按上海时间每天 06:00 调度；空来源的当日 run 也可能最终化，之后添加来源当天不能重跑，首次体验可能等到次日 06:00。本部署方案不新增手动重跑或 UI，文档和最终摘要必须明确，不能宣传“安装后立即看到候选”。
- 本轮未读取部署凭据，因此不知道现网是否显式配置 public origin；这是保留旧默认和旧 Compose 行为的兼容理由，不能把未读取当作已验证配置完整。
