# Reven

Reven 是面向超级个体的个人经营工作台。

它的起点是内容发布：保留 Notion 作为写作与思考的主场，把稿件同步、发布校验、博客发布、微信公众号草稿和结果通知集中到一个工作台。长期而言，Reven 会逐步成为一个“待决策中心”——帮助你一眼看到哪些事情需要自己判断和处理，而不是试图成为一套重型 ERP。

## 当前 MVP

第一版打通内容发布闭环，并由 Reven 原生承担 RSS 内容发现：

```text
Notion 稿件库
  → Reven 同步、校验与调度
  → 个人博客自动发布
  → 微信公众号自动创建草稿
  → 飞书通知结果

RSS 源
  → 每日抓取、翻译与分层筛选
  → 候选工作台人工确认
  → Notion Inbox
  → 飞书每日汇总
```

Notion 仍是稿件正文的唯一权威来源。Reven 不替代 Notion 编辑器或 Notion AI；它只接管写稿后的发布流程。

### MVP 边界

- 稿件状态变为“待发布”后，Reven 按上海时间执行发布计划。
- 博客发布采用 GitHub Flow：创建 PR、等待 CI、合并并验证上线。
- 微信公众号仅自动创建草稿，公开发布仍由用户在公众号平台确认。
- 缺少封面或集成凭据无效时，发布会被明确阻止。
- 结果、阻塞与失败通过飞书机器人通知。

当前流程仍不包含自动公开发布、多用户权限或通用 ERP 功能。
仓库已提供腾讯云 COS 内容寻址资产存储基础，后续由原子内容同步流程接入各发布渠道。

## 产品方向

Reven 的长期方向不是堆叠模块，而是聚合个人需要做出的决策。

首页将逐步呈现各领域的待决策事项及数量，例如待筛选的内容候选、待推送的选题、待发布稿件和被阻塞的发布任务。各业务模块独立负责自身数据与操作，Dashboard 只做聚合；在需求稳定前，不预先设计万能任务或工作流系统。

## RSS 内容发现

Reven 原生执行 RSS 内容发现；生产切换与 OpenClaw 停用按运行手册完成：

```text
RSS 源
  → Reven 每日 06:00（Asia/Shanghai）抓取
  → 去重、翻译与多层筛选
  → 候选工作台供人工判断
  → 一键推送 Notion Inbox
  → 飞书汇总通知
```

每条 RSS item 是素材，而不是一篇待转换稿件。你在 Notion 的 Inbox 中可以组合多条素材、加入自己的思考并写成稿件；Inbox 与稿件库会通过多对多关联保留素材追溯关系。

相关实现议题：

- [以 Reven 一次性替换 OpenClaw 的 RSS 内容发现工作流](https://github.com/wangyiyang/Reven/issues/10)
- [在 Reven 维护 RSS 源、正向关键词与反向关键词](https://github.com/wangyiyang/Reven/issues/11)
- [Reven 定时抓取 RSS、去重并发送飞书汇总](https://github.com/wangyiyang/Reven/issues/12)
- [为 RSS item 增加翻译、规则、BM25、Embedding 与模型推荐筛选](https://github.com/wangyiyang/Reven/issues/13)
- [人工确认后将 RSS 候选推送到 Notion Inbox](https://github.com/wangyiyang/Reven/issues/14)
- [在 Notion 建立 Inbox 素材与稿件库的双向多对多关联](https://github.com/wangyiyang/Reven/issues/15)
- [接入 SiliconFlow BAAI/bge-m3 Embedding 服务](https://github.com/wangyiyang/Reven/issues/17)

## 架构原则

- 前端：React、TypeScript、Vite、shadcn/ui、Tailwind CSS。
- 后端：Python、FastAPI、SQLAlchemy、Alembic。
- 数据库：Supabase Postgres。
- 部署：一个统一部署的模块化单体；前后端代码分离，但不拆微服务、独立 Worker、Redis 或消息队列。
- 业务时间统一使用 `Asia/Shanghai`，数据库统一存储 UTC。
- 密钥通过环境变量或加密集成配置管理，绝不写入前端、代码仓库或日志。

## 开发状态

Reven 正在重建发布 MVP。详细的产品设计与实施计划见：

- [`docs/superpowers/specs/2026-07-29-editorial-publishing-mvp-design.md`](docs/superpowers/specs/2026-07-29-editorial-publishing-mvp-design.md)
- [`docs/superpowers/plans/2026-07-29-editorial-publishing-mvp.md`](docs/superpowers/plans/2026-07-29-editorial-publishing-mvp.md)
- [`docs/ai-test-map.md`](docs/ai-test-map.md)：AI 测试地图，覆盖全功能、全路径与安全红线。
