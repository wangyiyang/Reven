# Reven

Reven 是面向超级个体的个人经营工作台，聚合需要判断和处理的经营事项。

当前处于 **单用户、自托管 Alpha** 阶段。首次体验以 **RSS → 人工筛选 → Reven 本地素材库** 为目标；开源准备与尚未完成的发布验收见 [Issue #127](https://github.com/wangyiyang/Reven/issues/127)。

## 开始使用

按 [自托管指南](docs/self-hosting.md) 从源码构建 PostgreSQL 17、Reven 和 Caddy，无需维护者的私有镜像或云账号。

- 正式支持目标为 **Linux AMD64**；ARM64 和 Docker Desktop 尚未正式验证。
- 公网使用自己的域名和 Caddy 自动 HTTPS；本机体验提供仅绑定 loopback 的 HTTP 配置。
- 基础启动需要数据库密码、管理员密码与加密主密钥；RSS 采纳保存不要求外部集成账号。
- AI、飞书和品牌图片 COS 存储按需配置，见 [可选集成](docs/integrations.md)。

## 当前范围

- RSS：定时抓取、去重、翻译、分层筛选、人工审核及本地素材保存。
- 飞书：每日汇总通知、候选素材审核卡片与快捷采纳/忽略。
- 品牌：品牌档案、素材上传、版本及已有渠道模板配置管理。
- 经营：CRM、项目、财务、SOP、人才管理。
- Agent：基于 DeepSeek Harness 的运营工具入口。

稿件写作与发布流程暂未确定，当前版本已移除稿件管理、正文同步、发布预览、
博客自动发布、微信公众号草稿创建以及 Notion 集成。品牌模板仅保存配置，
当前没有内容发布执行链路。

## RSS 内容发现与素材保存

    RSS 源
      → 每日 06:00（Asia/Shanghai）抓取、去重和翻译
      → 关键词、BM25、Embedding 与模型筛选
      → 网页或飞书人工审核
      → 采纳后保存在 Reven 素材库

采纳只表示素材值得保留，不生成稿件。工作台“已保存素材”可查看原文、摘要与
筛选依据。网页和飞书使用同一采纳操作，重复采纳不会重复保存。

RSS 翻译在“集成设置”配置百度翻译或阿里翻译，按优先级故障切换；
均不可用时回退到 Qwen。Embedding、Agent、飞书配置独立管理。
无需 Notion、GitHub 或微信公众号凭据即可完成素材发现与采纳。

## 架构

- 前端：React、TypeScript、Vite、shadcn/ui、Tailwind CSS，使用 pnpm。
- 后端：Python、FastAPI、SQLAlchemy、Alembic，使用 uv。
- 数据库：PostgreSQL；品牌图片通过腾讯云 COS 存储。
- 部署：模块化单体、单个 Uvicorn worker、进程内 RSS 调度与嵌入式 dsh。
- 业务时间统一使用 Asia/Shanghai，数据库存储 UTC。
- 密钥通过环境变量或加密集成配置管理。

## Alpha 限制

- 单个管理员账号，无多用户权限或租户隔离。
- RSS 同一天最多执行一次；当天已空跑时新增来源可能要等次日 06:00，当前没有手动抓取入口。
- 未配置翻译服务时可能保留原文；未配置 Embedding 时采用字面与 BM25 筛选，并显示语义降级。安装成功不表示全部 AI 功能已启用。
- 数据库与配置仍可能演进，升级前须备份。尤其下述迁移 0021 不可降级。

## 本地验证

    uv sync --frozen --all-packages --python 3.12
    uv run ruff check server
    uv run ruff format --check server
    uv run mypy server/src
    pnpm install --frozen-lockfile
    pnpm test
    pnpm build

数据库测试需要独立 PostgreSQL 测试库：

    DATABASE_URL=<TEST_DATABASE_URL> uv run alembic -c server/migrations/alembic.ini upgrade head
    TEST_DATABASE_URL=<TEST_DATABASE_URL> uv run pytest server/tests

迁移测试会创建临时数据库以隔离不可逆迁移，因此测试账号需要 CREATEDB 权限。
不要把 TEST_DATABASE_URL 指向生产库。

## 升级说明

迁移 0021 删除稿件、快照、发布任务、Notion 导入记录及 Notion/GitHub/微信集成
配置；RSS 旧 pushing/pushed 记录也会删除，不迁移历史内容。
该迁移不可降级；不能仅切换旧镜像恢复已移除功能。

部署与验证见 [运行手册](docs/runbook.md)，Agent 架构见
[Agent 架构](docs/agent-architecture.md)，测试覆盖见 [测试地图](docs/ai-test-map.md)。
历史稿件设计保留在 docs/superpowers，已不代表当前产品范围。

## 文档与贡献

- [自托管、首次验收](docs/self-hosting.md)
- [备份、恢复与升级](docs/self-hosting-operations.md)
- [AI、COS 与飞书集成](docs/integrations.md)
- [贡献指南](CONTRIBUTING.md) · [安全问题反馈](SECURITY.md)

## 许可证

Reven 原创代码采用 [Apache-2.0](LICENSE)，版权持有人为 Wang Yiyang。第三方依赖和开发工具保留各自许可，其中 Trellis 工具模板为 AGPL。具体边界和分发声明见 [第三方声明](THIRD_PARTY_NOTICES.md)。
