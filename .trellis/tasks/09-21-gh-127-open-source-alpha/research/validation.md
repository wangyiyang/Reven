# #127 实施验收记录

## 当前结论

源码授权材料、自托管入口、HTTPS 认证支持及对外指南已实施。语言层检查通过，首次完整镜像构建发现的 Ruby 许可采集加载顺序错误已修复并通过增量构建。
真实 Notion、历史敏感材料处置、私密报告入口和二进制分发许可核验仍有未完成项，Issue #127 不应自动关闭。

## 已执行检查

| 范围 | 环境与结果 |
| --- | --- |
| Python 依赖 | `uv sync --frozen --all-packages --python 3.12`；Python 3.12.13，未修改锁文件 |
| 前端依赖 | pnpm 10.13.1，`pnpm install --frozen-lockfile` 通过 |
| 数据库 | 本任务单独 PostgreSQL 17 容器，随机 loopback 端口、专用测试账号/库；Alembic 升至 `0020_rss_item_review_pushed_at` |
| 后端全量 | `pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80`：949 passed，覆盖率 87.06%；未使用生产数据库 |
| 静态质量 | Ruff、格式检查、mypy 190 源文件通过；后续审查新增边界定向复测见 review 报告 |
| Web | 测试、ESLint、生产构建通过；现有 MSW、Node 实验性 API 和 Vite chunk 大小警告仍保留 |
| Renderer | 39 项测试通过，生产构建通过 |
| Vendoring | 防回灌与错误恢复 fixture 通过，ShellCheck 0.11.0 通过 |
| 原部署 | `scripts/test_deploy_reven.sh` 通过；未修改生产凭据、入口或实际部署 |
| 自托管配置 | Compose 渲染与 !override 端口边界、可选环境变量透传通过；固定 Caddy 镜像校验公网/本地配置通过 |
| 构建上下文 | 使用实际 Dockerfile 专属 ignore 和 BuildKit 假文件 fixture，8 类敏感文件排除、3 类必要输入保留 |
| CI | actionlint 1.7.12 通过；手动 `full=true` 入口不调用生产发布，普通 PR/main 不构建容器 |
| 许可采集 | 4 项 collector 回归通过；原创 wheel 元数据、原始 LICENSE、补充证据哈希通过 |
| 完整镜像 | 本地 Linux AMD64 目标构建通过；宿主为 ARM64 OrbStack，因此仅为跨架构辅助证据 |
| 秘密扫描 | 详见 `security-audit.md`：当前树 2 条人工确认假值/示例，历史 30 条第三方 Token 材料未处置 |

ShellCheck 官方 v0.11.0 macOS ARM64 归档 SHA-256：`339b930feb1ea764467013cc1f72d09cd6b869ebf1013296ba9055ab2ffbd26f`。
actionlint 官方 v1.7.12 macOS ARM64 归档 SHA-256：`aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f`。

## 实际容器与远端验证

本地 AMD64 模拟镜像 `sha256:6366dea0c175911e6374ffb1985e9379704d80f92b5e0a90b067b6de6cdbef95` 已通过：空卷启动、健康、首次登录、未登录 401、CSRF 拒绝、MCP 不外露、UID 10001、只读根文件系统、资源/能力约束、会话及 RSS 数据与三个应用卷重建后保留、可信测试 CA 的 HTTPS 登录/退出及 Secure Cookie。

renderer bubblewrap 执行通过；博客 smoke 在 git 初始化的资源限制子进程报 `init mmap: Out of memory`，因此整体 smoke 返回失败并清理了其专用项目和卷。该运行依赖 ARM64 宿主的 AMD64 仿真，尚不能断言是正式平台问题；保留原有资源和安全限制，交由原生 CI 判定。

本机 Docker classic image store 无法让同一 PostgreSQL manifest index 同时映射两个架构，辅助测试临时引用其固定 AMD64 子 digest `sha256:af194ccf3e2d7fe367012c7b88ce8b816c5c889b18a5b316799a1f0d7eac746a`；产品 Compose 保持官方 index digest，未删除其他任务的镜像或容器。
原生 Linux AMD64 的正式证据须来自手动完整 CI，不能用 ARM64 宿主上的模拟运行替代。
测试 HTTPS 使用显式受信的本地 CA；即使通过，也不能宣称已验证真实域名的 ACME 申请。

## 剩余发布门槛

1. 按 `security-audit.md` 决定公开快照/历史处置方式，并复核实际拟公开内容与附属材料。
2. 真实 RSS → 人工确认 → Notion 验收需要明确指定测试空间、集成与两个数据源；不得借用生产凭据。
3. 实际公网域名的 DNS、ACME 与外部可达性尚未验证。
4. GitHub 私密漏洞报告入口尚不可验证；公开前需启用并实测。
5. `licenses/REVIEW.md` 中的缺失原文、内嵌运行时及对应源码义务须在重新分发相关二进制/镜像前核验；新增根许可证不等于整个分发物已通过。

当前没有对外发布镜像、改变仓库可见性、重写主分支历史、迁移生产或写入真实 Notion。
