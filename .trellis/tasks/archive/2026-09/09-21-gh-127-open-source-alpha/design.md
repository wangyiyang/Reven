# #127 开源 Alpha 技术设计

> 合并范围更新：`main` 的 `7edafd7`（#128）已移除 Notion、稿件发布、renderer、Doocs 与 Ruby/bubblewrap 运行依赖。用户要求本分支解决与 main 的冲突，因此当前实施保留该产品决策，首次流程改为 RSS → 人工审核 → Reven 本地素材库；以下早期设计与验收记录中涉及退役能力的内容仅保留为历史依据。当前合并验证见 `research/merge-main-validation.md`。

## 结论与范围

以最小兼容改动交付首个可独立部署的 Alpha：原创部分采用 Apache-2.0，第三方工具与组件维持各自许可；新增独立的通用自托管入口，复用现有应用、镜像、迁移与数据库模型。现有生产 ACR/HTTP 部署继续可用。

用户决策和验收定义以 `prd.md` 为准。实施前由最终规划摘要确认本设计。

## 1. 部署边界

| 路径 | 用途 | 本次策略 |
| --- | --- | --- |
| `infra/compose/`、`infra/caddy/`、`scripts/deploy_reven.sh` | 维护者现有生产部署 | 保留兼容；不改变正在使用的端口、镜像仓库、HTTP 和回滚约束 |
| `infra/self-host/` | 外部使用者安装 | 新增 Compose、Caddy 配置及通用环境变量示例，支持源码构建 |
| `infra/docker/Dockerfile` | 同一应用镜像 | 复用构建过程；仅补分发许可、必要卷权限与构建上下文排除 |
| 后端 Settings 与认证 | 两条部署路径共用 | 增加标准 HTTPS origin 能力，同时保留合法 HTTP 配置 |

首版提供源码构建路径即可满足外部独立运行，不将公开镜像发布作为安装前提，也不引入新的云平台、数据库抽象或对象存储适配。

## 2. HTTPS、Origin 与认证

- `PUBLIC_BASE_URL` 接受规范 HTTP/HTTPS origin，拒绝用户信息、非根路径、query、fragment、非法 host/port 及其他协议。
- 规范化 scheme、host 与尾部根斜杠，避免 URL 解析结果与 Cookie 的字符串判断不一致；保留原有 `REVEN_PUBLIC_BASE_URL` alias。
- Cookie 的 Secure 行为取决于已验证的外部 origin：HTTPS 必须为 Secure，既有 HTTP 兼容行为保持。
- 保留 HttpOnly、SameSite、会话认证与 CSRF 双条件，不允许通过反向代理伪造客户端 Origin 来放行请求。
- 不将全局 HSTS 强加给既有同域名多端口 HTTP 服务；旧生产入口不做 TLS 迁移。
- 新 Caddy 路径复用安全响应头、静态资产缓存和 SPA fallback，只反代 `/api/*`；不公开 loopback MCP 端点或数据库端口。
- 针对大小写、空白、默认端口与非法端口等边界写行为测试；具体规范化方式保持 KISS，避免不必要的全局 URL 库重构。

## 3. 通用自托管 Compose

### 服务与数据

- PostgreSQL 17：独立数据卷、健康检查，仅容器网络访问。
- Reven：源码构建现有 Dockerfile，等待 PostgreSQL 健康，再复用入口的 Alembic 迁移与静态发布。
- Caddy：公网域名路径提供自动 HTTPS；本地初次体验明确限定在 loopback/可信网络 HTTP。公网路径文档要求域名和证书所需端口可达。
- 为应用数据、静态资产、Agent 数据、数据库及 Caddy 证书提供持久卷；核对非 root UID 的初始化权限，不靠给应用容器 root/privileged 权限绕过。
- 保留资源上限、只读根文件系统、cap_drop、no-new-privileges 和沙箱约束。

### 配置与镜像身份

- 自托管示例使用通用域名及空的外部集成配置，密码与主密钥必须由使用者生成。
- 数据库连接采用项目内服务地址，不要求 Supabase 账号；默认使用独立 PostgreSQL 容器。
- 源码构建的本地镜像在专用自托管入口运行；维护者生产脚本仍接受受限的 ACR 完整 digest。
- 不为自托管新增接受任意远端镜像的宽松入口；若未来需要公共镜像，再增加明确的来源与 digest 验证。
- Dockerfile 专属 ignore 文件必须覆盖嵌套 `.env`、密钥与运行态数据，同时正确保留构建所需的示例文件。`COPY infra/` 不得携带真实自托管配置。

## 4. 许可、版权与分发物

- 根 `LICENSE` 使用 Apache-2.0，原创版权署名 Wang Yiyang；包元数据和 README 保持一致。
- `THIRD_PARTY_NOTICES.md` 或同等清单明确各目录的许可证边界，并保存必要许可证原文与来源/版本。
- Doocs 保留原始 WTFPL v2 与固定提交信息；不得将其许可证替换为 Apache-2.0。
- Trellis 0.6.15 上游 LICENSE 已确认为 AGPL v3；已确认两个模板复制样本，查阅范围内未发现模板例外。按 `.template-hashes.json` 和来源对照建立文件清单，保留独立 LICENSE/COPYRIGHT 与修改声明；项目自身任务、规格及日志不一概归为第三方模板。上游 COPYRIGHT 与 CLI SPDX 的 v3-or-later/only 表述差异记录待核对，保留原文，不自行改授权。
- 对实际锁定的 JS、Python、Ruby、字体及镜像内组件建立清单；未知或特殊分发条款作为待处理项，不能仅凭顶层项目许可证判断整包可分发。
- 运行镜像中携带其所需的声明；开发工具若不属于运行时，不因写通知而扩大镜像内容。
- 现有 Dockerfile 定向 COPY 不包含 Trellis 工具；Node 可执行文件、打包后的 JS/字体和 Doocs 许可目前缺少显式交付路径，应补充版本对应的许可集合并检查最终镜像。许可集合不能放进已被 Dockerfile ignore 排除的目录。
- 不将 SBOM 等同于许可履约，分别核对许可证、版权声明及必要的源码/修改说明。

## 5. 第三方 Token 与公开资料清理

- 移除渲染所不需要的 Doocs 凭据配置及孤立导出；同步修改 vendoring 脚本和回归 fixture，避免下次导入恢复。
- 扫描范围覆盖拟公开的本地/远端分支、标签可达历史、当前工作树及会随公开暴露的仓库附属资料。
- 使用固定版本的专用扫描工具，开启完全脱敏；报告只保留规则、文件、行号、提交和处理结论，禁止密钥值、完整连接串或 Cookie。
- 明确区分当前树清理和历史风险处理：删除当前文件不代表历史已经安全。
- 已确认的模板占位值可用精确例外记录；禁止用整目录、整类 Token 的宽泛忽略掩盖命中。
- 真实自有凭据先轮换/撤销；第三方凭据不擅自验证或使用。确需历史重写时，先形成具体影响与恢复方案，按授权范围单独处理。
- 对 Trellis 工作日志、任务资料及文档进行隐私复核，保留有价值的工程知识；不无差别删除全部历史或工具目录。

## 6. 文档与首次体验

- README：单用户、自托管 Alpha 定位、核心链路、正式支持平台、安装入口和已知限制。
- Quick Start：安装前提 → 生成配置 → 构建启动 → 健康/登录验证 → 配置 RSS 与 Notion → 等待调度 → 人工确认 → 核对页面与幂等。
- 说明 Notion 配置当前需要稿件库与 Inbox 两个数据源及相应授权；字段初始化会修改这两个数据源。
- 翻译、Embedding、模型、通知、COS、博客和微信按流程列出必需/可选属性及降级表现。首次 RSS 路径不要求 COS，也不承诺完整稿件同步无需 COS。
- 清楚说明每天 06:00 Asia/Shanghai 调度、当日最多一次，以及当日空跑后新增源可能等待次日；本轮不新增手动重跑功能。
- 升级/备份文档同时覆盖 PostgreSQL、加密主密钥和持久卷；数据库恢复和应用回滚分别说明，不宣称回滚应用会自动回滚数据。
- CONTRIBUTING：开发依赖、验证命令、GitHub Flow 和贡献约定。
- SECURITY：明确私密报告方式；当前 GitHub private-vulnerability-reporting 查询返回 404，公开前必须确认入口可用，不能以公开 Issue 接收凭据或漏洞细节。

## 7. 验证与发布证据

| 层次 | 核心证据 | 不能替代的部分 |
| --- | --- | --- |
| 配置/API 回归 | HTTPS、HTTP 兼容、CSRF、Secure Cookie、无效 origin | 真实反向代理及证书链 |
| 供应链与资料 | 固定工具版本、扫描范围、脱敏 findings、许可清单 | 不能由一次简单正则扫描替代 |
| 隔离数据库集成 | 全量后端与 RSS 幂等测试、迁移 | 不访问生产数据库 |
| 真实 Compose | Linux AMD64、空卷安装、健康登录、持久化、沙箱、回滚 | ARM64 本机测试不等同于正式平台验证 |
| 首次核心流程 | 指定 RSS、Notion 测试空间，确认推送和重复确认 | Fake Notion 测试不等同于外部验收 |

当前 Docker daemon 为 Linux AArch64。实施中选择可用的 Linux AMD64 测试环境；如使用独立手动验证 workflow，应与生产 tag/release/deploy 解耦，不改变普通 PR 不构建容器的既有契约。

## 8. 兼容、风险与回滚

- 配置变更以扩大合法协议支持为主；现有显式 HTTP 配置仍通过，原生产 Caddy/端口不迁移。
- 通用部署使用不同 Compose project/卷，不复用生产目录和数据库。
- vendoring 变更必须通过离线 fixture 和真实 renderer 回归，确保删除的配置不影响渲染输出。
- 后端无预期数据库 schema 变更；若实施发现需要迁移，重新说明原因与向后兼容方案。
- 新自托管文件可独立撤回；现有生产发布脚本的 digest 校验及失败恢复用例保持通过。
- 工具许可、扫描命中和真实验收未完成时，只能标记“实现完成/待发布验收”，不能宣布 Alpha 已可公开发布或关闭未达标的验收项。
