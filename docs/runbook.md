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

## 2.1 配置腾讯云对象存储

COS Bucket 必须专用于 Reven 的公开内容资产。上传凭据使用独立子账号，最小权限只
包含目标 Bucket 的 `cos:HeadBucket`、`cos:HeadObject` 和 `cos:PutObject`；禁止复用
主账号长期密钥。将凭据备份至 1Password，并只通过服务器 `.env` 注入：

```dotenv
COS_BUCKET=reven-1251081768
COS_REGION=ap-beijing
COS_SECRET_ID=<TENCENT_CLOUD_SECRET_ID>
COS_SECRET_KEY=<TENCENT_CLOUD_SECRET_KEY>
COS_PUBLIC_BASE_URL=https://reven-1251081768.cos.ap-beijing.myqcloud.com
COS_ASSET_PREFIX=assets/sha256
```

服务器 `.env` 必须保持 `600` 权限。COS SDK 根据 `COS_REGION` 生成官方 API 地址，
不要用自定义域名发送写请求。自定义公开域名只配置在 `COS_PUBLIC_BASE_URL`。

对象按 SHA-256 内容寻址并携带不可变缓存头；相同内容复用同一对象，应用不会自动
删除或覆盖已验证的历史资产。品牌素材上传前，应为专用 Bucket 配置自定义
公开域名、流量告警和防盗链，并将权限限制为“公有读、私有写”；禁止设置“公有读写”。

## 3. 配置管理员登录密码

站点认证由应用内登录页负责（不再使用 Caddy Basic Auth）。管理员密码必须与
SSH、数据库等密码不同，只把明文密码写入服务器 `.env`（文件本身保持
`600` 权限，不进入仓库）：

```dotenv
REVEN_ADMIN_PASSWORD=<ADMIN_PASSWORD>
```

未配置该变量时服务拒绝启动（fail-closed）。登录后签发 HttpOnly 会话 Cookie，
有效期 7 天并随活跃自动续期；同一 IP 连续 5 次密码错误锁定 15 分钟。
Caddy 仅通过 3001 端口提供 HTTP，不监听 443，也不申请 TLS 证书；域名 A/AAAA
记录必须指向服务器，公网 3001 端口必须可达。Caddy 容器不接收任何认证变量，
只负责反向代理与静态资源。

HTTP 不会加密管理员密码、会话 Cookie 或业务数据，只能在可信网络或已有安全隧道的
环境中使用；服务直接暴露到公网时，链路上的第三方可能窃听或篡改这些内容。
旧版本已经下发过 HSTS；浏览器若仍缓存该策略，会继续把 HTTP 强制升级为 HTTPS。
HTTP 响应无法清除已缓存的 HSTS，切换后需要在受影响客户端手动清除该域名的 HSTS 记录。

## 4. 当前运行边界

当前版本提供 RSS 素材发现与采纳、飞书审核通知、品牌及经营模块。
稿件、博客发布、微信公众号草稿和 Notion 集成已移除，镜像不再包含
Ruby/Jekyll、微信渲染器或发布沙箱。容器使用 Docker 默认 seccomp，
保留只读根文件系统、cap_drop: ALL 和 no-new-privileges。

## 5. 退役迁移 0021

0021_retire_publishing 删除稿件、内容快照、发布任务、Notion 导入记录、
旧 RSS 推送记录以及 Notion/GitHub/微信配置和加密凭据。
历史内容不迁移，采纳的新素材保存到 Reven 的 RSS 记录。
该迁移不可降级；部署此版本后若要恢复旧稿件功能，需要恢复升级前数据库，
仅执行镜像 rollback 不兼容。生产升级按明确接受历史数据丢弃的范围执行。

## 6. 配置阿里云 ACR 凭据

本项目镜像存放在阿里云容器镜像服务个人版的私有仓库
`registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven`。当前项目只有一名开发者，明确
选择不引入 RAM 用户：GitHub Actions 发布和服务器拉取共用主账号的 Registry
登录凭据。这样维护成本最低，但任一环境泄露都需要同时轮换 CI 与服务器凭据。

在 GitHub 仓库的 Actions Secrets 中配置：

- `ALIYUN_ACR_USERNAME`：Registry 登录用户名；
- `ALIYUN_ACR_PASSWORD`：访问凭证页面设置的 Registry 登录密码。
- `REVEN_DEPLOY_SSH_HOST`：生产服务器主机名，不包含用户或端口；
- `REVEN_DEPLOY_SSH_PRIVATE_KEY`：仅允许 `kk` 用户部署 Reven 的私钥；
- `REVEN_DEPLOY_KNOWN_HOSTS`：服务器的完整 SSH host key，使用 `ssh-keyscan` 后经人工核对指纹写入；
- `FEISHU_DEPLOY_WEBHOOK`：部署状态通知机器人 Webhook；未配置时跳过通知。

`REVEN_DEPLOY_SSH_PRIVATE_KEY` 只应允许 `kk` 在 `/opt/reven` 下执行部署所需的
Docker 操作。不要关闭 SSH host key 校验，也不要用 `StrictHostKeyChecking=no` 代替
`REVEN_DEPLOY_KNOWN_HOSTS`。

同时在 GitHub 的 `main` 分支保护中将 CI 的 `backend`、`migration`、`frontend` 设为日常 required checks；仅有 workflow 文件不能阻止未通过检查的 PR
被合并。`container` 只在发版完整 CI 中运行，普通 PR 和 `main` push 均跳过。
若现有分支保护仍要求 `container`，job 条件导致的跳过不会阻止合并，无需为本次调整
修改远端分支保护。若 required checks 仍包含 renderer，应移除该已退役检查。

不要把密码写进仓库、工作流参数或命令历史。在服务器建立项目专用 Docker 配置，
再交互式读取密码：

```bash
install -d -m 700 /opt/reven/.docker
read -r -s -p 'ACR registry password: ' ACR_PASSWORD
printf '\n'
printf '%s' "$ACR_PASSWORD" | \
  docker --config /opt/reven/.docker login registry.cn-hangzhou.aliyuncs.com \
    --username 'wangyiyang_kk' --password-stdin
unset ACR_PASSWORD
chmod 600 /opt/reven/.docker/config.json
```

Docker 会提示该文件内的凭据未加密；这是无桌面凭据助手的 Linux 服务器上的预期
行为，因此目录必须为 `700`、文件必须为 `600`。所有部署命令都显式使用此
`--config`，避免误用用户级登录状态。轮换密码后，必须同步更新两个 GitHub Secret
并重新执行服务器登录；旧配置可用
`docker --config /opt/reven/.docker logout registry.cn-hangzhou.aliyuncs.com` 清除。

## 7. 自动部署与手动回滚

使用既有免密 SSH 用户登录，并在独立目录操作：

```bash
ssh kk@dev.wangyiyang.cc
mkdir -p /opt/reven
cd /opt/reven
```

首次部署前，服务器只需准备宿主机专属的 `.env` 和 `.docker` 凭据目录，无需预置仓库
中的 `infra/`；服务器不得执行 Docker 镜像构建。生产镜像把与该 digest 严格对应的发布
基础设施保存在稳定路径 `/opt/reven-release/infra`。后续由 workflow 上传唯一的受限部署
脚本；部署和回滚都会先从目标镜像导出并校验该目录，再精确同步到 `/opt/reven/infra`。
同步会删除新镜像中已移除的基础设施文件，但不会改动 `infra/` 之外的 `.env`、`.docker`、
镜像历史文件或部署脚本。

推送形如 `v1.2.3` 的版本 Tag 后，`.github/workflows/release.yml` 会先执行完整 CI，
通过 `full: true` 启用容器测试镜像构建、运行验证、漏洞扫描和 SBOM；全部通过后才
构建 ACR 正式镜像并推送 `<版本 Tag>` 与 `latest`。触发事件是版本 Tag push，单独
发布 GitHub Release 不触发此工作流。普通 PR 和 `main` push 按路径运行后端、迁移、
前端检查，不构建容器镜像，也不部署；容器打包、运行环境及镜像
漏洞问题会延后到发版阶段发现。生产部署只接收解析后的完整 digest，不使用任意 Tag。
workflow 使用 GitHub `production` Environment 和全局并发锁，避免并发升级。
成功部署会记录当前与上一健康镜像，并发送一条飞书通知。若 Caddyfile 内容发生变化，
脚本会在 Reven 健康检查通过后对正在运行的 Caddy 执行 reload；内容未变时不会 reload。

发布若涉及入口端口或协议变化，触发部署前必须先在服务器完成两项前置动作：
`ss -lntp | grep ':3001 '` 确认入口端口未被其他进程占用，并确认防火墙/安全组已放行
3001；同时先把 `.env` 的 `PUBLIC_BASE_URL` 同步为新入口地址（当前为
`http://dev.wangyiyang.cc:3001`）。若 `.env` 与新镜像的配置约束不一致，新容器会拒绝
启动，Reven 不健康时 Caddy 因 `depends_on` 不会启动，站点整体不可用（2026-08-31
事故）。入口无变化的日常部署无需改动 `.env`。

通过 Actions 的 `workflow_dispatch` 可选择：

- `deploy`：输入已发布镜像的版本 Tag（如 `v1.2.3`）；留空时部署 `latest`；
- `rollback`：切换到服务器记录的上一健康镜像，并同步该镜像内的配套基础设施；不会执行
  数据库降级。

手动部署和回滚均复用已有镜像，不运行完整 CI，也不重新构建镜像。

部署失败时 workflow 明确失败并发送失败通知；脚本会原位恢复 `.env` 中原有的
`REVEN_IMAGE` 和部署前的完整 `infra/`，必要时重新载入恢复后的 Caddyfile——Caddy
仍在运行时执行 reload；若失败发生在 Reven 健康检查阶段、Caddy 因 `depends_on` 从未
启动，则以恢复后的 Caddyfile 直接拉起 Caddy（`--no-deps`），尽力恢复静态页访问。
它不会伪造健康状态，也不会自动启动旧 Reven 镜像，因为失败镜像可能已经执行数据库迁移。

若需要在故障处置时人工部署，仍只接受完整 digest，并调用服务器上的同一受限脚本，
以确保镜像与基础设施保持同步：

```bash
REVEN_IMAGE=registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven@sha256:<AUDITED_DIGEST>
DEPLOY_OPERATION=deploy REVEN_IMAGE="$REVEN_IMAGE" /opt/reven/scripts/deploy_reven.sh
```

直接调用写接口的受控运维客户端必须同时发送
`Origin: <PUBLIC_BASE_URL>` 与 `X-Reven-CSRF: 1`。浏览器和脚本缺少任一请求头时，
服务会拒绝 POST、PUT、PATCH、DELETE；不要通过 Caddy 伪造或覆盖客户端的 `Origin`。

把同一个 ACR 完整 digest 写入 `.env` 的 `REVEN_IMAGE`，不得使用 Tag、`latest`
或本地构建名称。

服务器不构建生产镜像。workflow 会拒绝覆盖已有的版本镜像标签（如 `v1.2.3`），
生产部署的身份依据始终是 digest。

运行容器使用单个 Uvicorn worker。启动时先执行幂等 Alembic 迁移，再原子切换
前端静态文件。迁移和静态切换共享排他锁；迁移失败时旧 `current` 保持不变。
API 的 8000 端口不映射到宿主机，只允许 Caddy 容器访问。

Reven 容器上限为 2 CPU、2 GiB 内存和 128 PID。

Caddy 容器保留 `cap_add: NET_BIND_SERVICE` 不是特权端口需求：官方镜像的
`/usr/bin/caddy` 带 `cap_net_bind_service=ep` filecap，bounding set 缺该 cap 时
execve 直接 EPERM、容器无法启动（2026-09-01 实证）。调整容器 capability 前，
先用 `getcap` 检查二进制是否声明了 filecap。

## 8. 确认 3000 端口未变化

部署前后分别记录并比较：

```bash
docker ps --format '{{.Names}}\t{{.Ports}}'
ss -lntp | grep ':3000 '
```

Reven Compose 不声明 3000 端口。若既有服务的容器、进程或监听地址发生变化，
立即停止 Reven 部署并调查，不要覆盖或重启该服务。

## 9. 验证 HTTP、认证与健康状态

依次验证 HTTP 静态入口、未认证业务请求、公开健康检查，并确认服务未监听 HTTPS、
80 端口也不再提供服务：

```bash
curl -I http://dev.wangyiyang.cc:3001
curl -i http://dev.wangyiyang.cc:3001/api/rss/candidates
curl --fail http://dev.wangyiyang.cc:3001/api/health
! curl --fail --connect-timeout 3 https://dev.wangyiyang.cc
! curl --fail --connect-timeout 3 http://dev.wangyiyang.cc
```

预期依次为 HTTP 入口可访问、`401`、`{"service":"reven","status":"ok"}`，以及
HTTPS 与 80 端口连接失败。随后用浏览器打开 `http://dev.wangyiyang.cc:3001`，确认
跳转到登录页，并用 `.env` 中的
`REVEN_ADMIN_PASSWORD` 登录成功。最后检查容器状态与脱敏日志：

```bash
docker compose --env-file .env -f infra/compose/docker-compose.yml ps
docker compose --env-file .env -f infra/compose/docker-compose.yml logs --tail=200 reven caddy
```

日志中不得出现数据库密码、主密钥、Agent API Key 或飞书 Secret。

## 10. 按镜像 digest 回滚

回滚通过受限部署脚本读取 `.previous-healthy-image`，并从该镜像同步配套基础设施后再启动：

```bash
DEPLOY_OPERATION=rollback /opt/reven/scripts/deploy_reven.sh
```

应用回滚不会自动回滚数据库。退役迁移 0021 明确不兼容旧稿件版本，
不得直接回滚到该迁移之前的镜像；需要恢复旧功能时先恢复对应数据库备份。
同一新数据模型内的镜像回滚后重复第 9 步验证。

回滚到入口迁移（3001）之前的镜像时，Caddy 按该镜像配套 infra 重新监听 80，而
`.env` 的 `PUBLIC_BASE_URL` 仍带 3001：服务可用，但飞书通知链接的端口与入口不一致。
这是可接受的降级态；恢复后应尽快重新部署 3001 版本，或临时把 `PUBLIC_BASE_URL`
改回 `http://dev.wangyiyang.cc` 并重建 Reven 容器。

## 11. RSS 内容发现与素材保存

RSS 任务每天 `06:00 Asia/Shanghai` 执行，同一自然日只创建一个运行记录并只发送一条
飞书汇总。SiliconFlow 密钥仅写入服务器 `.env`，不得进入集成公共配置、日志或仓库：

```dotenv
SILICONFLOW_API_KEY=<SILICONFLOW_API_KEY>
SILICONFLOW_CHAT_MODEL=Qwen/Qwen3-8B
RSS_MODEL_REVIEW_ENABLED=true
```

在“集成设置”配置翻译、Embedding 与飞书。飞书应用审核需要配置应用凭据及
允许操作的用户；普通飞书机器人负责每日汇总。无需稿件平台配置。

在“RSS 配置”中录入 HTTPS Feed、正向关键词和反向关键词。需要主动重建关键词向量时，
先在浏览器登录获取会话，再在同一浏览器会话中调用；或用受控客户端走登录接口：

```bash
curl --fail -c /tmp/reven-cookie.jar \
  -H 'Content-Type: application/json' \
  -H 'Origin: http://dev.wangyiyang.cc:3001' \
  -H 'X-Reven-CSRF: 1' \
  -d '{"password": "<ADMIN_PASSWORD>"}' \
  -X POST http://dev.wangyiyang.cc:3001/api/auth/login
curl --fail -b /tmp/reven-cookie.jar \
  -H 'Origin: http://dev.wangyiyang.cc:3001' \
  -H 'X-Reven-CSRF: 1' \
  -X POST http://dev.wangyiyang.cc:3001/api/rss/embeddings/rebuild
rm -f /tmp/reven-cookie.jar
```

本地或专用测试环境按以下顺序验收：

1. 添加 Feed 与关键词，执行抓取，检查重复 item 不新增、异常源不阻断其他源。
2. 在网页采纳候选，切到“已保存素材”确认标题、摘要、原文链接和筛选依据。
3. 对同一素材重复采纳，确认返回同一记录且保存时间不变；已忽略条目不能采纳。
4. 用专用飞书测试应用验证授权用户采纳、忽略、重复点击及未授权拒绝。
5. 检查 RSS 运行记录和每日汇总，服务重启后已保存素材仍可查阅。

/api/system/status 返回数据库与 RSS 后台运行状态，不再显示稿件同步或发布调度。
生产飞书发送会触达实际用户，测试使用专用应用和会话，避免写入生产聊天。

## 受控依赖更新与已知供应链风险

Dockerfile 三个基础镜像、Caddy、CI PostgreSQL 和安全扫描器都使用
`tag@sha256`。更新时只允许在独立 PR 中同时修改可读 Tag 与 digest。PR 和 `main`
CI 只执行对应路径的语言层检查；版本 Tag 发版的完整 CI 才执行
`docker build --pull --no-cache`、全量测试、运行验证、Trivy 门禁和
Caddy 验证，并保存 CycloneDX SBOM 供审计。完整 CI 通过后才能构建推送正式镜像，
正式镜像也会执行漏洞扫描并保存 SBOM；两处扫描均阻止存在已有修复方案的 Critical
漏洞。容器与供应链风险的自动检查因此发生在发版阶段。

apt 软件包仍来自构建时 Debian 仓库状态，下载源不由本仓库镜像保存，
因此当前构建不是字节级完全可复现。SBOM、digest、冻结 lockfile 和漏洞门禁
是当前单人项目的补偿控制。
