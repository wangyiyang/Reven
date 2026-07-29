# Reven 单机部署运行手册

Reven 以 Docker Compose 部署在 `dev.wangyiyang.cc`，时区统一使用
`Asia/Shanghai`。Compose 只运行 Reven 与 Caddy；PostgreSQL 使用
Supabase，宿主机现有 3000 端口服务不属于 Reven。

## 1. 配置 Supabase Session Pooler

在 Supabase 控制台复制支持 IPv4 的 Session Pooler 连接串，不使用
Transaction Pooler。将驱动改为 `postgresql+asyncpg`，并明确启用 SSL：

```dotenv
DATABASE_URL=postgresql+asyncpg://<DB_USER>:<DB_PASSWORD>@<SESSION_POOLER_HOST>:5432/postgres?ssl=require
```

先从服务器验证 DNS、IPv4 和 TLS 可达性。连接串仅写入服务器部署目录的
`.env`，不得提交到 Git 或写入镜像。

## 2. 生成主密钥

生成 32 字节随机密钥的 Base64 表示：

```bash
openssl rand -base64 32
```

将结果写入服务器 `.env`：

```dotenv
REVEN_MASTER_KEY=<BASE64_32_BYTE_MASTER_KEY>
```

丢失该密钥将无法解密已保存的集成 Secret。备份应进入独立的密码管理器，
不得进入日志、镜像或仓库。

## 3. 配置独立的 Caddy Basic Auth

Basic Auth 密码必须与 SSH、Supabase、Notion 等密码不同。生成哈希：

```bash
docker run --rm caddy:2.10.0-alpine caddy hash-password --plaintext '<BASIC_AUTH_PASSWORD>'
```

只把用户名和生成的哈希写入 `.env`：

```dotenv
REVEN_BASIC_AUTH_USER=<BASIC_AUTH_USER>
CADDY_BASIC_AUTH_HASH=<CADDY_BCRYPT_HASH>
```

不要把明文密码写入 `.env`。Caddy 为 `dev.wangyiyang.cc` 自动申请并续期
HTTPS 证书，因此域名 A/AAAA 记录必须指向服务器，公网 80/443 端口必须可达。
Caddy 容器只接收这两个认证变量，不接收 Reven 的数据库或集成 Secret。

## 4. 安装博客 required check

通过博客仓库的独立 PR，把本仓库 `infra/blog/verify.yml` 安装为
`.github/workflows/reven-jekyll.yml`。PR 合并后，在博客仓库默认分支保护中将
`Jekyll build` 设为 required check。完成前不要启用 Reven 博客自动发布。

Reven 容器中的博客构建运行在无网络、受限文件系统的 OS 沙箱中；若宿主机
禁用非特权用户命名空间，沙箱自检会失败，发布会 fail-closed。不得通过移除
沙箱或给容器增加特权来绕过，应先修复宿主机用户命名空间能力。Compose 为此
使用基于 Docker 默认 allowlist 的最小 seccomp 扩展，只额外允许 bwrap 所需的
`mount`、`pivot_root`、`umount2` 与 `unshare`，并仅允许带
`CLONE_NEWUSER` 的额外 `clone`；同时保持 `cap_drop: ALL`、
`no-new-privileges`、只读根文件系统。bwrap 子进程使用独立 PID/网络命名空间，
并把 `/proc` 覆盖为空目录。

博客 Ruby 依赖来自镜像内 `/opt/reven-blog` 的受信 `Gemfile.lock`，运行时只
执行 `bundle check`，不会解析博客仓库自己的 Gemfile，也不会联网安装
Gem。博客依赖变化必须先更新 `infra/blog/runtime/Gemfile.lock`、重新构建并通过
实际博客 fixture，再发布新镜像；禁止在生产容器内执行 `bundle update`。

## 5. 配置微信出口 IP 白名单

完成 HTTPS 与 Basic Auth 后，访问：

```text
https://dev.wangyiyang.cc/api/system/egress-ip
```

把响应中的固定公网 `ip` 加入微信公众号平台 IP 白名单。若云服务器出口 IP
变化，必须先更新白名单，再恢复微信发布。

## 6. 配置服务器 GHCR 只读凭据

本项目镜像包按私有 GHCR Package 管理。为服务器的专用部署用户 `kk` 创建独立、
可撤销的只读凭据；不要复用个人日常 Token。优先使用仅授予该仓库 Package
读取权限的 fine-grained 凭据（组织策略支持时），否则使用仅含 `read:packages`
scope 的 classic PAT。两者都不得授予 `write:packages`、`delete:packages` 或仓库
写权限。

在服务器上建立该用户专用的 Docker 配置目录，然后交互式读取 Token。下面命令
不会把 Token 放进命令参数或 shell history：

```bash
install -d -m 700 /opt/reven/.docker
read -r -s -p 'GHCR read token: ' GHCR_TOKEN
printf '\n'
printf '%s' "$GHCR_TOKEN" | \
  docker --config /opt/reven/.docker login ghcr.io \
    --username '<GHCR_USERNAME>' --password-stdin
unset GHCR_TOKEN
chmod 600 /opt/reven/.docker/config.json
```

凭据应定期轮换；人员、服务器或仓库权限变化时立即撤销。撤销或更换前可执行
`docker --config /opt/reven/.docker logout ghcr.io` 清除本地凭据。所有部署命令
都显式使用此 `--config`，避免误用其他项目共享的 Docker 登录状态。

## 7. 在服务器部署

使用既有免密 SSH 用户登录，并在独立目录操作：

```bash
ssh kk@dev.wangyiyang.cc
mkdir -p /opt/reven
cd /opt/reven
```

Git Tag 触发 `.github/workflows/release.yml` 后，先核对完整质量门禁、SBOM、漏洞
扫描和 `image-digest.txt`。Tag 只是便于识别的发布标签，不具备技术上的不可变
保证；部署只接受证据中已审核的 digest：

```bash
REVEN_IMAGE=ghcr.io/<OWNER>/<REPOSITORY>@sha256:<AUDITED_DIGEST>
export REVEN_IMAGE
./scripts/validate_reven_image.sh
docker --config /opt/reven/.docker pull "$REVEN_IMAGE"
test "$(docker image inspect "$REVEN_IMAGE" --format '{{index .RepoDigests 0}}')" = "$REVEN_IMAGE"
chmod 600 .env
docker compose --env-file .env -f infra/compose/docker-compose.yml config
docker --config /opt/reven/.docker compose --env-file .env \
  -f infra/compose/docker-compose.yml pull reven
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d
docker compose --env-file .env -f infra/compose/docker-compose.yml ps
```

把同一个 `ghcr.io/...@sha256:...` 值写入 `.env` 的 `REVEN_IMAGE`，不得使用 Tag、
`latest` 或本地构建名称。

服务器不构建生产镜像。发布 workflow 只构建并推送 GHCR 镜像，不执行 SSH 或自动
部署；升级仍由用户审核 release 证据后手工执行。workflow 会在推送前拒绝已存在
的同名 Tag，但生产部署的身份依据始终是 digest。

运行容器使用单个 Uvicorn worker。启动时先执行幂等 Alembic 迁移，再原子切换
前端静态文件。迁移和静态切换共享排他锁；迁移失败时旧 `current` 保持不变。
API 的 8000 端口不映射到宿主机，只允许 Caddy 容器访问。

Reven 容器上限为 2 CPU、2 GiB 内存和 128 PID。Jekyll 子进程另有限制：
240 CPU 秒、1.5 GiB 地址空间、64 进程、256 文件描述符和 64 MiB 文件大小；
renderer 使用 384 MiB V8 old-space，并限制 CPU、进程、文件描述符和文件大小。
不要通过提高容器权限绕过限制；确有正常文章超限时，应先复现和缩小资源需求。

## 8. 确认 3000 端口未变化

部署前后分别记录并比较：

```bash
docker ps --format '{{.Names}}\t{{.Ports}}'
ss -lntp | grep ':3000 '
```

Reven Compose 不声明 3000 端口。若既有服务的容器、进程或监听地址发生变化，
立即停止 Reven 部署并调查，不要覆盖或重启该服务。

## 9. 验证 HTTPS、认证与健康状态

依次验证 HTTP 自动跳转 HTTPS、未认证请求被拒绝、认证后健康检查成功：

```bash
curl -I http://dev.wangyiyang.cc
curl -I https://dev.wangyiyang.cc
curl --fail --user '<BASIC_AUTH_USER>:<BASIC_AUTH_PASSWORD>' \
  https://dev.wangyiyang.cc/api/health
```

预期分别为 HTTPS 重定向、`401`、以及
`{"service":"reven","status":"ok"}`。随后检查容器状态与脱敏日志：

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml ps
docker compose --env-file .env -f infra/compose/docker-compose.yml logs --tail=200 reven caddy
```

日志中不得出现数据库密码、主密钥、GitHub Token、微信 Secret 或 Notion Token。

## 10. 按镜像 digest 回滚

回滚时把 `.env` 中 `REVEN_IMAGE` 改为上一已验证的完整 digest，然后执行：

```bash
docker --config /opt/reven/.docker compose --env-file .env \
  -f infra/compose/docker-compose.yml pull reven
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d --no-deps reven
docker compose --env-file .env -f infra/compose/docker-compose.yml ps
```

数据库迁移必须保持向后兼容：先扩展、再迁移数据、最后在后续版本收缩。应用回滚
不会自动回滚数据库；若某次迁移不兼容上一镜像，禁止发布该版本。回滚后重复第 9
步，并确认所有时间展示仍为上海时间。

## 11. 真实发布验收（执行前必须取得用户确认）

以下步骤会写入真实 Notion、GitHub、微信草稿箱和飞书。默认状态为
**未执行**；必须由用户指定专用测试稿并逐项确认后，才可开始。不得使用生产稿件，
不得调用微信公众号公开发布接口。

1. 配置并分别测试 Notion、GitHub、微信公众号、飞书四个集成。
2. 对专用测试稿显式初始化全部 Notion 字段，并记录页面 ID。
3. 清空封面后设为待发布，确认 Reven 阻塞全部渠道且飞书收到阻塞通知。
4. 补充封面，确认下一轮同步自动恢复，且没有产生重复任务。
5. 设置未来日期和时间，确认到期前不发布；仅日期时确认使用上海时间 08:01。
6. 确认博客只创建一个 PR、`Jekyll build` required check 通过、自动合并且线上标题一致。
7. 再次取得用户明确确认后，只创建一篇微信测试草稿。
8. 核对最终 HTML、正文图片、封面和草稿 `media_id`，不得执行公开发布。
9. 确认 Notion 状态为“已交付”（不是“已发布”），两渠道结果均已落库。
10. 人工触发一次重试与容器重启，确认 PR、博客文章和微信草稿均未重复创建。

每一步都记录执行人、上海时间、稿件/任务 ID、脱敏截图或 URL、预期与实际结果。
不得记录 Token、Secret、Cookie 或完整数据库连接串。出现跨稿件写入、重复发布、
公开发布、3000 端口变化、认证绕过或敏感信息泄露时，立即停止验收，按第 10 节回滚，
保留脱敏日志并将任务标记为阻塞。全部证据复核通过前，不得宣布 MVP 真实验收完成。

## 受控依赖更新与已知供应链风险

Dockerfile 三个基础镜像、Caddy、CI PostgreSQL 和安全扫描器都使用
`tag@sha256`。更新时只允许在独立 PR 中同时修改可读 Tag 与 digest，并执行
`docker build --pull --no-cache`、全量测试、实际沙箱 fixture、Trivy 门禁和
Caddy 验证。CI 保存 CycloneDX SBOM 供审计，并阻止存在已有修复方案的
Critical 漏洞。

`apt` 软件包仍来自构建时 Debian 仓库快照状态，Ruby Gem 虽由 lockfile 固定，
下载源本身也不由本仓库镜像保存，因此当前构建不是字节级完全可复现。不得宣称
完全可复现；SBOM、digest、冻结 lockfile 和漏洞门禁是当前单人 MVP 的补偿控制。
