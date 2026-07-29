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

## 5. 配置微信出口 IP 白名单

完成 HTTPS 与 Basic Auth 后，访问：

```text
https://dev.wangyiyang.cc/api/system/egress-ip
```

把响应中的固定公网 `ip` 加入微信公众号平台 IP 白名单。若云服务器出口 IP
变化，必须先更新白名单，再恢复微信发布。

## 6. 在服务器部署

使用既有免密 SSH 用户登录，并在独立目录操作：

```bash
ssh kk@dev.wangyiyang.cc
mkdir -p /opt/reven
cd /opt/reven
```

检出待部署的已审核 Git Tag，在 `/opt/reven/.env` 填写 `.env.example`
列出的全部变量，并限制权限：

```bash
chmod 600 .env
docker compose --env-file .env -f infra/compose/docker-compose.yml config
docker compose --env-file .env -f infra/compose/docker-compose.yml build --pull
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d
docker compose --env-file .env -f infra/compose/docker-compose.yml ps
```

运行容器使用单个 Uvicorn worker。启动时先执行幂等 Alembic 迁移，再原子切换
前端静态文件。API 的 8000 端口不映射到宿主机，只允许 Caddy 容器访问。

## 7. 确认 3000 端口未变化

部署前后分别记录并比较：

```bash
docker ps --format '{{.Names}}\t{{.Ports}}'
ss -lntp | grep ':3000 '
```

Reven Compose 不声明 3000 端口。若既有服务的容器、进程或监听地址发生变化，
立即停止 Reven 部署并调查，不要覆盖或重启该服务。

## 8. 验证 HTTPS、认证与健康状态

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

## 9. 按镜像 Tag 回滚

生产环境只部署不可变镜像 Tag。回滚时把 `.env` 中 `REVEN_IMAGE` 改为上一已验证
Tag，然后执行：

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml pull reven
docker compose --env-file .env -f infra/compose/docker-compose.yml up -d --no-deps reven
docker compose --env-file .env -f infra/compose/docker-compose.yml ps
```

数据库迁移必须保持向后兼容：先扩展、再迁移数据、最后在后续版本收缩。应用回滚
不会自动回滚数据库；若某次迁移不兼容上一镜像，禁止发布该版本。回滚后重复第 8
步，并确认所有时间展示仍为上海时间。
