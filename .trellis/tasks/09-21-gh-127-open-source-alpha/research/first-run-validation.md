# 首次 RSS 验收与执行环境

日期：2026-09-21。只读检查，不读取真实凭据、不触发外部写入。

## 首次使用流程的真实约束

1. Notion 配置页面的 `data_source_id` 为必填，`inbox_data_source_id` 可选（`server/src/reven/api/schemas/integrations.py:50`）；Quick Start 要说明同时建立稿件库和 Inbox、向集成授权。不能在文档中假设 UI 允许只填 Inbox。
2. “初始化字段”会修改稿件库和 Inbox（`server/src/reven/integrations/notion/service.py:67`），测试只能使用指定的专用空间。
3. RSS 推送 Inbox 仅调用 `ConfiguredRssInboxPusher` 和 `RssInboxService`，不依赖 COS；完整稿件同步的 COS 要求不应强加给首次 RSS 路径。
4. 缺少翻译或 Qwen 凭据时，RSS 保留原文并记录运行错误；缺少 Embedding 时会按字面/BM25 保守筛选，标记 degraded。相关逻辑位于 `rss/discovery.py`、`rss/factory.py`、`rss/screening_service.py`。文档必须明确降级状态，不能将其描述为全部 AI 功能正常。
5. 必须配置能产生正向命中的关键词，空关键词不能保证出现候选（`rss/screening.py:_base_decision`）。
6. `rss/scheduler.py` 在上海时间 06:00 后调度；`rss/discovery.py` 创建当日唯一运行，已结束运行不再重新抓取。无来源启动也可能耗用当天运行。新增来源后可能需等待下一自然日 06:00，当前 API 无手动抓取入口。
7. `server/tests/e2e/test_rss_discovery_flow.py` 已验证发现、人工确认、Notion 推送和幂等，但使用 Fake Feed/Localizer/Embedder/Notion，不能当作真实 Notion 验收证据。

## 验证分层

- 单元/API：配置校验、HTTPS Cookie、CSRF、未登录保护、RSS 降级行为。
- 隔离数据库集成：单独测试 PostgreSQL、迁移、RSS 发现到推送幂等；禁止使用生产数据库，测试 fixture 会 TRUNCATE 多张表。
- 部署：独立 Compose project 与空卷，验证非 root、健康检查、静态资源、HTTPS、持久化和升级回滚。
- 真实外部集成：指定测试 RSS 与 Notion 测试数据源，记录字段初始化、候选出现、确认、页面结果及重复确认不重复创建；凭据不进日志。

## 当前工作区环境

- 新 worktree 未安装 `.venv` 或 `node_modules`；后续使用 `uv sync --frozen --all-packages` 和 `pnpm install --frozen-lockfile`。
- 可用：Docker、uv、pnpm、node；尚未发现 gitleaks、trufflehog、actionlint、shellcheck 可执行文件。
- 当前 Docker daemon 为 `linux/aarch64`。本机检查只能作为辅助证据，正式 Linux AMD64 需要对应 runner/主机上的实际构建和运行证据。
- 未读取真实 `.env`，未连接任何生产数据库或外部测试目标。
- GitHub 私密漏洞反馈状态查询返回 404，尚不能确认入口已启用；公开前应核对可用性，SECURITY 文档不能把未验证的入口写成已启用。

## 方案边界

本次不增加 RSS 重跑功能，先在 Quick Start 和 Alpha 限制中清楚说明调度等待。源码构建作为首版独立安装路径，不要求先公开维护者镜像；现有 ACR 发布通道继续单独维护。正式 Linux AMD64 验证与真实 Notion 验收不能以本机 ARM64 或 Fake 测试冒充。
