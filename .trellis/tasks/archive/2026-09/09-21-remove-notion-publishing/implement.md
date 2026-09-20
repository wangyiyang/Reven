# 实施计划

1. 创建 worktree 与任务产物，固定已授权范围。
2. 按 Trellis auto 子代理流程并行实施（所有人仅写指定 worktree，不回退他人修改）：
   - 后端核心：装配、领域退役、共享网络/通知提取、集成/系统 API 及相应测试。
   - RSS：采纳事务、schema/API、飞书审核、RSS/Agent 测试。
   - Web：稿件退役、素材视图、集成/系统页面及测试。
   - 主 agent：品牌去耦、迁移、依赖/部署/构建、文档和集成。
3. 隔离本地数据库运行迁移与测试，前后端检查修复。
4. Trellis check agent 全范围审阅，修复并复验。
5. Conventional Commit 提交，归档并报告证据。

## 验证命令
uv sync --all-packages --group dev
uv run ruff check server
uv run mypy server/src/reven
TEST_DATABASE_URL=<isolated-local-db> uv run pytest
pnpm install --frozen-lockfile
pnpm --filter @reven/web test --run
pnpm build
Alembic upgrade head 与 ORM metadata 对照。

## 约束
上一轮范围方案已被用户“开始做吧”批准，不重复索要确认。git 操作只在 codex/remove-notion-publishing；main 的 dogfood-output 不动。

## 完成情况
实施、迁移、前后端全量检查、浏览器验证及容器构建均已完成，审阅问题已修复。详细证据见同目录 verification.md。
