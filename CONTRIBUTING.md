# 贡献指南

欢迎通过 Issue 讨论问题并提交 PR。请先说明要解决的问题、预期行为与验证方式；安全问题按 [SECURITY.md](SECURITY.md) 私密反馈。

## 开发环境

- Python 3.12、uv（CI 使用 0.12.1）。
- Node.js 22.22.2 或更新的兼容版本、pnpm 10.13.1。
- PostgreSQL 17；建议用 Docker 创建独立开发数据库与测试数据库。
- 完整自托管验收需要 Linux AMD64 与容器依赖；其他平台的语言层检查不能替代该验收。

在仓库根目录安装锁定依赖：

```bash
uv python install 3.12
uv sync --frozen --all-packages --python 3.12
pnpm install --frozen-lockfile
```

不要把生产 `.env` 或集成凭据复制到开发目录。以下 Bash 命令创建只监听 loopback 的独立数据库；若容器名或端口已占用，换用自己的专用名称与端口，不要删除他人的容器：

```bash
export REVEN_DEV_DB_PASSWORD="$(openssl rand -hex 24)"
docker run -d --name reven-dev-postgres \
  -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=reven -e POSTGRES_DB=reven_dev \
  -e POSTGRES_PASSWORD="$REVEN_DEV_DB_PASSWORD" \
  postgres:17-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193
docker exec reven-dev-postgres pg_isready -U reven -d reven_dev
```

等 `pg_isready` 返回 accepting connections 后创建专用测试数据库，并配置当前终端：

```bash
docker exec reven-dev-postgres createdb -U reven reven_test
export DATABASE_URL="postgresql+asyncpg://reven:$REVEN_DEV_DB_PASSWORD@127.0.0.1:55432/reven_dev"
export TEST_DATABASE_URL="postgresql+asyncpg://reven:$REVEN_DEV_DB_PASSWORD@127.0.0.1:55432/reven_test"
export REVEN_MASTER_KEY="$(openssl rand -base64 32)"
export REVEN_ADMIN_PASSWORD="$(openssl rand -hex 24)"
export REVEN_PUBLIC_BASE_URL=http://localhost:5173
export DSH_HOME="$PWD/.dsh-runtime"
uv run alembic -c server/migrations/alembic.ini upgrade head
uv run uvicorn reven.app:app --host 127.0.0.1 --port 8000 --reload
```

在另一终端从仓库根目录执行 `pnpm --filter @reven/web exec vite --host localhost --port 5173 --strictPort`，浏览器访问 `http://localhost:5173`；Vite 将 `/api` 代理到后端。登录密码为后端终端中生成的 `REVEN_ADMIN_PASSWORD`，只在自己的终端或密码管理器中查看和保存。

本段随机配置适合一次性开发环境。要保留已保存的集成，需将同一主密钥和密码安全保存，后续启动继续使用；重新生成主密钥会使旧凭据无法解密。容器运行环境另由完整 CI 验证。

## 验证变更

先跑受影响功能的测试，再跑对应层的完整检查。后端测试会清空测试库多张表，**`TEST_DATABASE_URL` 必须指向可丢弃的独立测试库**；未配置导致跳过不算通过。迁移测试会创建临时数据库，测试角色需要 CREATEDB 权限。

```bash
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
DATABASE_URL="$TEST_DATABASE_URL" uv run alembic -c server/migrations/alembic.ini upgrade head
DATABASE_URL="$TEST_DATABASE_URL" uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80
pnpm --filter @reven/web lint
pnpm --filter @reven/web test --run
pnpm build
git diff --check
```

部署脚本变更还需运行 `sh scripts/test_deploy_reven.sh`；shell 逻辑用 shellcheck，workflow 用 actionlint 检查。验证命令不能连接生产数据库、发送真实群消息或修改真实业务资料。

普通 PR / main CI 按路径运行语言层检查，**不构建容器**；版本 tag 发版执行完整容器及供应链检查。维护者可以在 Actions 的 **CI** 工作流中选择待验证分支，手动设 `full=true` 运行完整检查；该入口不发布镜像或部署生产环境。

自托管烟测使用独立 project、临时随机凭据、空卷及显式信任的测试 CA，验证 HTTPS、认证、数据持久化、素材采纳和默认 Compose 安全设置。它不替代公网 ACME 签发或真实 Feed 的完整发现验收。不要推送版本 tag 来试跑检查，它会进入生产发布流程。容器相关 PR 应附独立环境验证证据。

## 提交与评审

1. 从最新 `main` 创建功能或修复分支；外部贡献者可先 fork。通过 PR 合并，不直接向 `main` 提交或强推。
2. 先读 [项目规范](.trellis/spec/)，遵循周边风格、DRY / KISS / SOLID / YAGNI。保持变更聚焦，避免顺手重构；单函数超过 50 行、单文件超过 500 行时评估拆分。
3. Bug 修复附能复现问题的回归测试；行为变更同步配置示例和用户文档。修改 vendored 内容时保留来源、许可和可重复应用的修改流程。
4. 使用 Conventional Commits，例如 `fix: 修复 HTTPS 会话 Cookie`。每个提交只解决一个关注点。
5. PR 先写问题与结果，再说明必要的改动、风险及验证结果；关联 Issue。未完成真实外部验收时如实标记，不能用模拟测试替代。

讨论、Issue 和 PR 说明使用简体中文。日志、截图与测试 fixture 应脱敏，不提交密钥、Cookie、数据库备份、私人稿件或环境文件。

原创贡献按项目 [Apache-2.0](LICENSE) 提交；第三方代码与工具按各自许可，详见 [第三方声明](THIRD_PARTY_NOTICES.md)。请确认自己有权提交，保留引入组件的许可和版权，不把整个仓库标为单一许可证。
