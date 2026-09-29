# 自托管与首次使用

本指南在独立的 Linux AMD64 主机上运行 PostgreSQL 17、Reven 与 Caddy，提供**源码构建（默认）**与**公开镜像**两种镜像来源，以及公网 HTTPS、仅本机 HTTP 两种入口。首次目标是登录后将一条 RSS 候选采纳并保存到 Reven 本地素材库。

以下命令使用 Bash，均从仓库根目录执行。部署数据使用独立的 `reven-self-host` Compose project；不要复用维护者生产目录或数据库。

## 1. 准备环境

- Linux AMD64、Docker Engine、Docker Compose **2.24.4 或更新版本**、Git、OpenSSL、curl。
- 容器构建需要访问上游镜像与依赖下载源。应用运行上限为 2 CPU / 2 GiB；还需为 PostgreSQL、Caddy、构建和数据预留资源。
- 公网部署准备一个域名，将 DNS 指向该主机，并放行 TCP 80、443；两个端口须未被其他服务占用。若配置了 AAAA 记录，IPv6 也应可达。

```bash
docker info --format '{{.OSType}}/{{.Architecture}}'
docker compose version
git clone https://github.com/wangyiyang/Reven.git
cd Reven
git rev-parse HEAD
```

选择已审阅的版本或提交，并保存提交号。ARM64 和 Docker Desktop 的运行结果不能替代 Linux AMD64 验收。

## 2. 生成并保存配置

仅在首次安装、文件尚不存在时执行：

```bash
umask 077
cp infra/self-host/.env.example infra/self-host/.env
chmod 600 infra/self-host/.env
```

分别运行下面的命令，将每次输出填写到 `.env` 对应项，并保存在自己的密码管理器中。不要上传终端输出或 `.env`。

| 配置项 | 生成命令或填写方式 | 用途 |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `openssl rand -hex 32` | 数据库密码；使用十六进制避免连接串转义问题 |
| `REVEN_ADMIN_PASSWORD` | `openssl rand -hex 24` | 首次及后续登录使用的管理员密码 |
| `REVEN_MASTER_KEY` | `openssl rand -base64 32` | 加密集成凭据，必须长期保留 |
| `REVEN_PUBLIC_BASE_URL` | 如 `https://reven.example.com`，替换为自己的域名 | 浏览器实际访问的 origin，无路径、查询或片段 |

公网指南使用标准 HTTPS 443 端口。域名填写 ASCII 形式；国际化域名使用其 Punycode 地址（例如 `https://xn--fa-hia.de`），不要直接填写 Unicode 域名。示例域名不能用于申请真实证书。数据库用户名与数据库名均为 `reven`，应用只通过容器网络连接 PostgreSQL。

**主密钥丢失后，数据库中已保存的集成凭据无法解密。** 重启或升级不要重新生成它。已初始化数据库的密码也不会因为修改 `.env` 自动改变，轮换时需同时修改数据库角色密码。

## 3. 选择入口并启动

先在当前 Bash 会话初始化 Compose 文件列表：

```bash
reven_compose_files=(-f infra/self-host/docker-compose.yml)
```

接着从镜像来源与入口中选择一种组合，再执行本节最后的启动命令。

### 镜像来源一：源码构建（默认）

本机构建 Reven 镜像，无需任何镜像仓库账号；构建需要访问上游镜像与依赖下载源。首次使用默认选择此来源。

### 镜像来源二：公开镜像

不想在主机上构建时，可改用发布到 GitHub Container Registry 的镜像。它是与维护者生产发布相同的产物，经过相同的 Trivy 门禁扫描；公开镜像在仓库公开后可匿名拉取，私有期间请使用源码构建。

1. 在 `.env` 增加 `REVEN_IMAGE`，固定为发布说明中的 digest（不要用 `:latest`）：

```bash
REVEN_IMAGE=ghcr.io/wangyiyang/reven@sha256:<64-hex>
```

2. 在文件列表追加镜像覆盖文件：

```bash
reven_compose_files+=(-f infra/self-host/compose.image.yml)
```

该覆盖文件会移除源码 build 段，启动时按 digest 拉取。拉取后可在宿主机直接核对（无需 `dc exec` 进入容器）：执行 `docker inspect --format '{{.RepoDigests}}' "$(docker compose -p reven-self-host ps -q reven)"`，确认输出与 `.env` 中的 digest 一致。此来源可与下面的"仅本机 HTTP 体验"入口叠加。

### 公网 HTTPS

保留刚才的文件列表，确认 `.env` 的 `REVEN_PUBLIC_BASE_URL` 为自己的 HTTPS 域名。Caddy 会自动申请、续签域名证书。

### 仅本机 HTTP 体验

没有公网域名时，在文件列表追加本机配置：

```bash
reven_compose_files+=(-f infra/self-host/compose.local.yml)
```

该覆盖文件将应用与 Caddy 的 origin 固定为 `http://localhost:8080`，端口仅绑定 `127.0.0.1`。它依赖 Compose 2.24.4 的 `!override` 支持。浏览器必须使用 `http://localhost:8080`，不要改用 `http://127.0.0.1:8080`，两者 origin 不同。远程主机可通过 SSH 转发到本机访问：

```bash
ssh -N -L 8080:127.0.0.1:8080 YOUR_USER@YOUR_HOST
```

此路径的 HTTP 只用于本机或安全隧道；公网部署使用 HTTPS 入口。

### 构建与启动

完成上面的文件与入口选择后定义 `dc`；两种来源、两种入口共用这些命令（使用公开镜像来源时跳过 `dc build reven`）：

```bash
dc() {
  docker compose -p reven-self-host \
    --env-file infra/self-host/.env \
    "${reven_compose_files[@]}" "$@"
}
dc config --quiet
dc build reven
dc up -d --wait
dc ps
```

Reven 等待数据库健康后自动执行迁移；迁移失败会停止启动。Caddy 在应用健康后提供静态页面与 `/api/*`。数据库 5432、应用 8000 和内部 MCP 端点不向宿主发布。

后续升级、备份、恢复和新终端会话都必须恢复所选的文件列表及 `dc` 定义，保留所选入口覆盖文件。

## 4. 验证健康与登录

公网模式将下面地址改为自己的域名；本机模式改为 `http://localhost:8080`：

```bash
reven_url=https://reven.example.com
curl --fail "$reven_url/api/health"
curl -s -o /dev/null -w '%{http_code}\n' "$reven_url/api/rss/candidates"
```

预期健康响应为 `{"service":"reven","status":"ok"}`，未登录业务请求为 `401`。浏览器打开同一地址，使用 `REVEN_ADMIN_PASSWORD` 登录；没有注册或默认密码流程。

HTTPS 登录后的 `reven_session` Cookie 应包含 `Secure`、`HttpOnly`、`SameSite=Lax`。本机 HTTP 不设置 `Secure`。不要把 Cookie 值复制到截图或 Issue。

启动失败时查看 `dc ps`、`dc logs --tail=100 postgres reven caddy`。不要用完整 `docker compose config` 或 `docker inspect` 输出作为公开日志，它们可能展开秘密。迁移失败需先查原因，不能靠删除数据卷恢复“正常”。

## 5. 配置 RSS 并等待发现

1. 打开 **RSS → RSS 源**，添加公开、可访问的 HTTPS Feed URL 并保持启用。先在浏览器核对 Feed 中确实有条目。
2. 打开 **RSS → RSS 关键词**，添加一个确实出现在该 Feed 标题或摘要中的正向关键词；首次验证可先不设反向关键词。空关键词不能保证产生候选。
3. 保持服务运行，等待每天 **06:00 Asia/Shanghai** 的发现任务。若服务在当天 06:00 之后首次启动，会检查当天是否已执行；没有订阅源的空跑也可能结束当天任务。
4. 当天任务已结束后再添加源，需要等**次日 06:00**。刷新页面或重启容器都不会强制重抓；当前没有手动抓取 API。
5. 打开 **RSS → RSS 候选**，核对来源、标题、摘要、原文链接、关键词和入选依据。

未配置翻译与 Qwen 时，条目可能保留原文并记录翻译错误；缺少 Embedding 时按字面和 BM25 保守筛选，候选显示“语义降级”。模型复核可能跳过。这些状态允许人工筛选，不代表 AI 功能完整可用。

若次日仍没有候选，依次检查源是否启用、HTTPS Feed 是否可访问、正向关键词是否真的匹配，以及 **系统状态**和脱敏后的应用日志。没有候选不一定是调度故障，也可能全部被规则筛掉。

## 6. 人工采纳并验证保存

在 **RSS → RSS 候选** 的待审核列表点击一条候选的 **采纳并保存**。成功后切换到 **已保存素材**，核对标题、来源、原文链接、摘要、筛选依据及保存时间。采纳不生成稿件；不需要的候选可点击 **忽略**。

验收记录包含源码提交、Linux AMD64 与 Docker/Compose 版本、所选入口、日期、RSS 来源及脱敏候选 ID，并检查：

- 待审核列表移除该候选，已保存列表恰好出现一条对应记录。
- 刷新页面后记录仍存在；重复采纳返回同一条记录，保存时间不变。
- 执行 `dc up -d --force-recreate --wait` 重建容器后，登录、RSS 配置与已保存素材仍可读取。
- 全程没有配置 Notion、GitHub 或微信公众号凭据，也没有向这些平台写入。

容器 smoke 使用确定性的本地候选验证采纳、幂等与持久化；真实 Feed 的抓取、筛选和每日调度应另按上节观察。模拟候选不能替代完整真实 RSS 链路验收。

升级、备份、恢复与回滚见 [运维指南](self-hosting-operations.md)，其他能力见 [可选集成](integrations.md)。
