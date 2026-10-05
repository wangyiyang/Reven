# HTTPS 与开源 Alpha 自托管契约

## 1. 范围与触发

修改应用 origin、会话/CSRF、`infra/self-host/`、镜像构建上下文或安装文档时遵守本契约。
来源：Issue #127；部署定位为单管理员、Linux AMD64 自托管 Alpha。#128 已将首次流程收敛为 RSS → 人工采纳 → 本地素材，不恢复已移除的外部稿件发布。

两条部署路径共用应用镜像，入口独立：

- `infra/self-host/`：使用者从源码构建，PostgreSQL 17 + Reven + Caddy，公网 HTTPS 或 loopback HTTP。
- `infra/compose/`、`infra/caddy/`、`scripts/deploy_reven.sh`：维护者既有 ACR digest / HTTP 3001 部署，保留兼容性。

不能为了本地构建放宽生产镜像来源校验，也不能把开源准备当成迁移现网的授权。

## 2. 调用签名

- `reven.security.origin.normalize_origin(value: str) -> str`：配置与 CSRF 共用的 origin 校验及规范化；无效输入抛 `ValueError`。
- `Settings.validate_public_base_url(value: str) -> str`：将无效配置转成明确的 Pydantic 配置错误。
- `POST /api/auth/login`，JSON `{"password": "..."}`：成功返回会话 Cookie。
- `POST /api/auth/logout`：删除数据库会话，返回 `204` 和过期 Cookie；旧 Cookie 再访问受保护接口必须为 `401`。
- `GET /api/health`：`{"service":"reven","status":"ok"}`；只证明进程可响应，不证明 RSS 抓取或外部集成可用。

从源码根目录运行（真实配置不进命令输出）：

```bash
reven_compose_files=(-f infra/self-host/docker-compose.yml)
# 按入口追加覆盖文件，见安装指南。
dc() {
  docker compose -p reven-self-host \
    --env-file infra/self-host/.env \
    "${reven_compose_files[@]}" "$@"
}
dc config --quiet
dc build reven
dc up -d --wait
```

本机模式追加 `-f infra/self-host/compose.local.yml`。后续升级、备份和恢复均保持同一组配置。
`!override` 要求 Compose >= 2.24.4。

## 3. 行为、请求与环境契约

### Origin 与浏览器认证

- `REVEN_PUBLIC_BASE_URL` 优先于兼容别名 `PUBLIC_BASE_URL`。默认 origin 为本机回环 `http://localhost:8080`；公网自托管必须显式配置自己的域名。
- 接受 HTTP/HTTPS、ASCII 域名（包括 Punycode）、IPv4/方括号 IPv6、合法端口；scheme/host 转小写、删除根斜杠和默认端口，IPv6 压缩为规范形式。
- 拒绝非 ASCII authority、空白/控制字符、用户信息、非根路径、query/fragment（含空 `?`/`#`）、百分号、反斜杠、非法 host、空端口、端口 0 或超出 65535。
- 不使用 Python 内置 IDNA 编码自动转换 Unicode 域名：其 IDNA2003 行为会将 `faß.de` 转成 `fass.de`，与浏览器不同。使用者必须配置 `xn--fa-hia.de` 形式。
- `POST/PUT/PATCH/DELETE` 同时要求规范化后同源的 `Origin` 和 `X-Reven-CSRF: 1`。不信任 `Host`、`X-Forwarded-Host`、`X-Forwarded-Proto` 来替代该校验。
- `REVEN_CSRF_ALLOWED_ORIGINS`（#120）：逗号分隔的额外 Origin 放行白名单，供浏览器 Origin 与 `REVEN_PUBLIC_BASE_URL` 不一致的前端部署（如 Vercel 托管）使用；逐项经 `normalize_origin` 校验，非法值启动期报错。`Origin` 规范化后精确命中 `public_base_url` 或白名单任一即通过；默认空，行为与仅校验 `public_base_url` 完全一致。无 Origin、缺 CSRF 头或无配置时仍一律 `403`（fail-closed）。
- `reven_session` 登录和注销均保持 `Path=/`、HttpOnly、SameSite=Lax、无 Domain。仅可信配置的 HTTPS origin 决定 Secure；代理到 Uvicorn 的内部 HTTP 不改变此结果。
- 内部 `/agent/mcp` 继续由 Bearer token 独立鉴权；新 Caddy 只反代 `/api/*`，`/agent/*` 明确返回 404。

### Compose 与运行数据

| 环境项 | 契约 |
| --- | --- |
| `POSTGRES_PASSWORD` | 必填；指南生成随机 hex，直接拼进内部 asyncpg URL；更改 `.env` 不会自动轮换已初始化数据库密码 |
| `REVEN_MASTER_KEY` | 必填；Base64 编码的 32 字节密钥，必须随备份保存；不可随重启/升级重新生成 |
| `REVEN_ADMIN_PASSWORD` | 必填；无默认登录密码 |
| `REVEN_PUBLIC_BASE_URL` | 必填；公网指南为 `https://自己的域名`，标准 443；本机 override 对应用/Caddy 同时固定为 `http://localhost:8080` |
| `DATABASE_URL` | Compose 根据数据库密码指向 `postgres:5432/reven`；不依赖维护者账号或 Supabase 专有能力 |
| `DSH_HOME` | `/data/dsh`，使用独立持久卷 |
| `SILICONFLOW_*`、`RSS_MODEL_REVIEW_ENABLED`、`COS_*` | Compose 逐项映射；未设置时保留应用默认/降级行为，不将整份秘密配置传给 Caddy/PostgreSQL |

- 三个服务均声明 `platform: linux/amd64`；PostgreSQL/Caddy 从官方镜像按固定 digest 获取，Reven 使用源码 build。
- Reven 等待 PostgreSQL healthy，Caddy 等待 Reven healthy；entrypoint 自动迁移失败必须停止启动，不切换新版静态资源。
- 数据库和应用端口不发布到宿主。公网只发布 Caddy 80/443；local override **替换**端口列表，只留下 `127.0.0.1:8080:8080`。
- 保留 Reven UID 10001、只读根文件系统、tmpfs、资源上限、`cap_drop: ALL`、`no-new-privileges` 和 Docker 默认安全策略。Caddy 保留镜像二进制所需的 `NET_BIND_SERVICE`。
- 六个 named volumes：`postgres-data`、`reven-data`、`dsh-data`、`reven-static`、`caddy-data`、`caddy-config`。新卷复制镜像目录属主；恢复归档必须保留 UID/GID，不将应用改成 root。
- Dockerfile 专属 ignore 覆盖任意层级 `.env`/`.env.*`（仅放行 `.env.example`）、密钥及运行数据；`.gitignore` 不能代替构建上下文保护。
- 镜像继续携带旧部署所需 `/opt/reven-release/infra/`，运行许可材料位于 `/opt/reven-licenses/`。不得引入整个开发工具树；许可采集不等同于已完成公开分发审查。

## 4. 验证与失败矩阵

| 条件 | 预期行为 |
| --- | --- |
| `HTTPS://REVEN.EXAMPLE:443/` | 规范化为 `https://reven.example`，登录与注销 Cookie 均 Secure |
| 配置 `https://faß.de` 或非法 origin | 配置验证失败；错误提示使用 HTTP/HTTPS 及 ASCII/Punycode |
| HTTPS 请求 origin 显式 `:443` | 与默认 HTTPS 端口等价 |
| Origin 跨站/跨协议/不同端口，或缺任一 CSRF 头 | `403`，`code=csrf_validation_failed` |
| 伪造转发头但 Origin 不匹配 | 仍为 `403` |
| local 模式以 `127.0.0.1` 地址访问并写入 | 与配置的 `localhost` 不同源；应按指南使用 localhost |
| 必填 Compose 环境变量缺失/空值 | `config` / 启动插值失败，不使用共享默认秘密 |
| 数据库迁移或卷权限失败 | 应用不健康，入口依赖不能当成启动成功；保留故障证据 |
| 更改 `.env` 仅执行 restart | 旧容器环境仍保留；使用 `up -d --force-recreate --wait` 重建相关服务 |

## 5. 正常、默认与错误场景

- 正常：独立 Linux AMD64 主机，空卷、生成自己的秘密、公网 DNS/80/443 可达，通过可信 HTTPS 登录，再验收 RSS 候选的本地采纳与素材保存。
- 默认：没有 AI/COS 配置仍可启动；RSS 翻译/语义筛选可能降级。RSS 本地采纳不需要外部集成，品牌素材可选 COS。
- 调度：RSS 在上海时间每日 06:00 后执行，当日已完成的空跑也会阻止新增来源立即重抓；无手动重跑契约。
- 错误：将 `compose config`、`/api/health`、ARM64/QEMU、本地确定性 RSS fixture 或关闭全局宿主安全策略的 CI 烟测当成完整 Linux AMD64 默认部署验收。
- 回滚：退回应用镜像不会降级数据库；迁移不兼容时须恢复兼容备份，并核对备份后的素材及集成配置变化。数据库备份不能替代主密钥或文件卷。

## 6. 必须覆盖的测试与证据

- `server/tests/test_config.py`：HTTP/HTTPS、别名优先级、大小写/默认端口规范化、Punycode/IPv6、非法输入与 Unicode 拒绝；`REVEN_CSRF_ALLOWED_ORIGINS` 逗号分隔解析、留空默认与非法值拒绝。
- `server/tests/security/test_csrf.py`：同源成功、默认端口等价、不同协议/端口/无效输入/缺头为 403、转发头无法绕过；白名单内 Origin 放行、白名单外（含子域后缀仿冒）仍为 403。
- `server/tests/security/test_auth.py`：HTTP/HTTPS Cookie 属性、内部代理 HTTP 的配置决定行为、注销及旧 Cookie 重放为 401。使用隔离数据库。
- `server/tests/e2e/test_self_host_deployment.py`：实际 Compose 渲染后无数据库/应用公开端口，local 无遗留 80/443，必填环境/可选透传、卷及安全选项保留；不分发已退役的沙箱 profile。
- `server/tests/security/test_deployment_automation.py` 与 `e2e/test_http_deployment.py`：旧 ACR/HTTP/回滚约束、镜像 infra 不回退，自托管文件单独变化会选择 backend 回归；脚本另跑 `scripts/test_deploy_reven.sh`。
- 修改 ignore 规则时用无敏感内容的嵌套假配置/密钥/运行数据验证真实 BuildKit 上下文，再检查最终镜像；仅文本模式检查不足以证明未打包秘密。#127 本地已执行八类假文件排除探针，不能据此省略将来的规则变更验证。
- 独立容器验收：记录真实 Linux AMD64、镜像 ID、源码提交和宿主安全策略；空卷启动、可信 TLS、Secure Cookie、CSRF、UID/可写卷、素材采纳、持久化与恢复均需运行证据。
- 首次流程验收：真实 RSS 调度发现候选、人工采纳及重复采纳幂等、本地 saved 素材持久化。独立容器烟测可直接写入确定性候选验证采纳 API，但不替代真实源抓取与调度证据。

普通 PR/main 不构建容器；完整容器验证的入口和无生产部署边界见 [CI 契约](ci-release-contract.md)。

## 7. 错误与正确写法

```python
# 错误：原始大小写与 Cookie 字符串判断不一致；内置 IDNA 也不等于浏览器域名解析。
secure = raw_public_url.startswith("https://")
host = parsed.hostname.encode("idna").decode("ascii")

# 正确：Settings 与 CSRF 统一调用受限的 origin 规范化，再判断 Cookie。
origin = normalize_origin(configured_public_url)
secure = origin.startswith("https://")
```

```yaml
# 错误：普通列表合并会保留基础配置的公网端口。
ports:
  - "127.0.0.1:8080:8080"

# 正确：本机 override 明确替换列表。
ports: !override
  - "127.0.0.1:8080:8080"
```
