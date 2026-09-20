# 自托管与首次使用

本指南从源码构建，在独立的 Linux AMD64 主机上运行 PostgreSQL 17、Reven 与 Caddy。首次目标是登录后将一条 RSS 候选人工推送到自己的 Notion Inbox。

以下命令使用 Bash，均从仓库根目录执行。部署数据使用独立的 `reven-self-host` Compose project；不要复用维护者生产目录或数据库。

## 1. 准备环境

- Linux AMD64、Docker Engine、Docker Compose **2.24.4 或更新版本**、Git、OpenSSL、curl。
- 容器构建需要访问上游镜像与依赖下载源。应用运行上限为 2 CPU / 2 GiB；还需为 PostgreSQL、Caddy、构建和数据预留资源。
- 公网部署准备一个域名，将 DNS 指向该主机，并放行 TCP 80、443；两个端口须未被其他服务占用。若配置了 AAAA 记录，IPv6 也应可达。
- 博客与渲染需要宿主允许非特权用户命名空间及 bubblewrap 沙箱。启用 AppArmor 的 Docker 主机还需下文的命名 profile；验证基线为 Ubuntu 22.04 原生 AMD64，其他发行版的安全策略需单独验证。不要用 `privileged`、`apparmor=unconfined`、删除 seccomp 或关闭全局安全策略来绕过失败。

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

先在当前 Bash 会话初始化 Compose 文件列表，并检查 Docker 是否启用 AppArmor：

```bash
reven_compose_files=(-f infra/self-host/docker-compose.yml)
docker info --format '{{json .SecurityOptions}}'
```

如果输出含 `apparmor`，必须先安装随附的命名 profile，再加入覆盖文件。默认 `docker-default` 禁止沙箱所需的 mount；此 profile 只作用于 Reven，保留 `/proc`、`/sys` 等限制。详细来源与范围见 [AppArmor 配置](../infra/self-host/apparmor/README.md)。未启用 AppArmor 的宿主跳过以下代码块。

```bash
sudo install -m 0644 infra/self-host/apparmor/reven-self-host /etc/apparmor.d/reven-self-host
sudo apparmor_parser -r /etc/apparmor.d/reven-self-host
reven_compose_files+=(-f infra/self-host/compose.apparmor.yml)
```

接着从以下两种入口中选择一种，再执行本节最后的启动命令。

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

完成上面的文件选择后定义 `dc`；两种入口均执行这些命令：

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

后续升级、备份、恢复和新终端会话都必须恢复所选的文件列表及 `dc` 定义，保留 AppArmor 和入口覆盖文件。

## 4. 验证健康与登录

公网模式将下面地址改为自己的域名；本机模式改为 `http://localhost:8080`：

```bash
reven_url=https://reven.example.com
curl --fail "$reven_url/api/health"
curl -s -o /dev/null -w '%{http_code}\n' "$reven_url/api/articles"
```

预期健康响应为 `{"service":"reven","status":"ok"}`，未登录业务请求为 `401`。浏览器打开同一地址，使用 `REVEN_ADMIN_PASSWORD` 登录；没有注册或默认密码流程。

HTTPS 登录后的 `reven_session` Cookie 应包含 `Secure`、`HttpOnly`、`SameSite=Lax`。本机 HTTP 不设置 `Secure`。不要把 Cookie 值复制到截图或 Issue。

启动失败时查看 `dc ps`、`dc logs --tail=100 postgres reven caddy`。不要用完整 `docker compose config` 或 `docker inspect` 输出作为公开日志，它们可能展开秘密。迁移失败需先查原因，不能靠删除数据卷恢复“正常”。

## 5. 准备 Notion 稿件库与 Inbox

先使用专用测试空间，避免首次初始化修改已有业务资料。

1. 创建自己的 Notion 内部集成，允许读取、插入和更新内容。向它授权两个独立数据库：**稿件库**和 **Inbox**。可从连接的 Content access 配置授权，也可在各数据库页面的连接菜单添加集成；新建集成默认没有页面访问权。[Notion 授权说明](https://developers.notion.com/guides/get-started/internal-connections)
2. 在稿件库将标题列命名为 **标题**，手动添加名为 **状态** 的 Status 类型字段（不是 Select）。先保持稿件库为空，不创建“待发布”测试稿。
3. 在 Inbox 将唯一的标题列重命名为 **名称**。这些初始字段要求不能由 Reven 自动补齐。
4. 获取稿件库 Database ID、稿件库 Data Source ID、Inbox Data Source ID。Database ID 是数据库链接中的标识；Data Source ID 可在数据库“Manage data sources”菜单复制。两种 ID 不能互换。[Notion ID 说明](https://developers.notion.com/guides/get-started/upgrade-guide-2025-09-03#step-1-add-a-discovery-step-to-fetch-and-store-the-data-source-id)
5. 在 Reven **集成设置 → Notion** 填入三个 ID 和 Token，保存后点击 **测试连接**。虽然 Inbox 在表单中标为可选，本次 RSS 推送必须填写；稿件库 Data Source ID 同样必填。
6. 点击 **初始化字段**。这会修改两个数据源：补齐稿件库的封面、自动化状态、失败原因及状态选项；补齐 Inbox 的 Reven ID、来源、原文链接、发布时间、摘要，并建立“关联稿件 ↔ 关联素材”双向关系。

连接测试只读取稿件库，不能证明 Inbox 授权正确。以字段初始化成功及后续实际推送为准。同名字段类型冲突时，按页面错误先在 Notion 修正，再重试；应用不会静默覆盖错误类型。

首次 RSS 推送不需要 COS、博客或微信公众号配置。完整稿件同步需要 COS，见 [后续集成](integrations.md)。

## 6. 配置 RSS 并等待发现

1. 打开 **RSS → RSS 源**，添加公开、可访问的 HTTPS Feed URL 并保持启用。先在浏览器核对 Feed 中确实有条目。
2. 打开 **RSS → RSS 关键词**，添加一个确实出现在该 Feed 标题或摘要中的正向关键词；首次验证可先不设反向关键词。空关键词不能保证产生候选。
3. 保持服务运行，等待每天 **06:00 Asia/Shanghai** 的发现任务。若服务在当天 06:00 之后首次启动，会检查当天是否已执行；没有订阅源的空跑也可能结束当天任务。
4. 当天任务已结束后再添加源，需要等**次日 06:00**。刷新页面或重启容器都不会强制重抓；当前没有手动抓取 API。
5. 打开 **RSS → RSS 候选**，核对来源、标题、摘要、原文链接、关键词和入选依据。

未配置翻译与 Qwen 时，条目可能保留原文并记录翻译错误；缺少 Embedding 时按字面和 BM25 保守筛选，候选显示“语义降级”。模型复核可能跳过。这些状态允许人工筛选，不代表 AI 功能完整可用。

若次日仍没有候选，依次检查源是否启用、HTTPS Feed 是否可访问、正向关键词是否真的匹配，以及 **系统状态**和脱敏后的应用日志。没有候选不一定是调度故障，也可能全部被规则筛掉。

## 7. 人工确认与首次验收

点击一条专用测试候选的 **推送到 Notion**，通过成功提示的“打开页面”核对 Inbox 页面：标题、来源、原文链接、发布时间、摘要与 Reven ID 应对应这条素材。确认后候选从待审列表消失；不需要的素材可点击“忽略”。

验收记录应包含源码提交、Linux AMD64 与 Docker/Compose 版本、所选入口、日期、RSS 来源、脱敏后的候选 ID/Notion 页面 URL，以及下面的结果：

- 空卷安装、健康检查、未登录 401 与首次登录通过；公网模式还需验证证书与 HTTPS Cookie。
- 两个数据源授权和字段初始化成功；等待一次真实调度后出现测试候选。
- 人工确认后只创建一个对应的 Inbox 页面。
- 在同一登录浏览器的开发者工具中，对刚才的 `/api/rss/candidates/{id}/confirm` 请求重放一次；返回相同页面，Inbox 中同一 Reven ID 仍只有一条。不要导出请求头或 Cookie。
- 执行 `dc restart reven` 后，集成与 RSS 数据仍在，已推送条目没有回到待审队列。

这些操作会写入你指定的 Notion 测试空间。自动化里的 Fake Notion 测试不能替代真实验收；没有外部测试目标时，应记录“待验收”，不能标记通过。

下一步阅读 [备份、恢复与升级](self-hosting-operations.md)，再按需开启 [其他集成](integrations.md)。维护者原有 ACR/HTTP 部署继续按 [原运行手册](runbook.md) 操作，两条路径不共用部署脚本。
