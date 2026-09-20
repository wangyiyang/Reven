# Reven

Reven 是面向独立创作者的单用户、自托管内容运营工作台。它把 RSS 发现、人工筛选、Notion 写作与内容交付连接起来，让你集中处理需要判断的事项。

当前处于 **Alpha** 阶段。首次体验以 **RSS → 人工筛选 → Notion Inbox** 为验收范围；博客、公众号和 AI 按需接入。开源发布准备与尚未完成的验收见 [Issue #127](https://github.com/wangyiyang/Reven/issues/127)。

```text
RSS 订阅 → 每日发现与筛选 → 人工确认 → Notion Inbox
                                        ↓
                                   Notion 稿件库
                                        ↓
                              同步、校验与发布调度
                                ↙               ↘
                         博客 GitHub PR       微信公众号草稿
                                ↘               ↙
                                   飞书结果通知
```

Notion 是稿件正文的权威来源。公众号公开发布仍由你在微信平台确认；Reven 只创建草稿。

## 开始使用

按 [自托管指南](docs/self-hosting.md) 从源码构建，启动 PostgreSQL 17、Reven 和 Caddy。无需维护者的私有镜像、数据库或云账号。

- 正式支持目标为 **Linux AMD64**；ARM64 和 Docker Desktop 尚未正式验证。
- 公网入口使用自己的域名和 Caddy 自动 HTTPS；本机体验提供仅绑定 loopback 的 HTTP 配置。
- 启用 AppArmor 的 Docker 主机需按指南安装[随附的命名 profile](infra/self-host/apparmor/README.md)；验证基线为 Ubuntu 22.04 原生 AMD64。
- 启动基础服务只需数据库密码、管理员密码与加密主密钥；推送 Inbox 需要你自己的 Notion 集成。
- 首次 RSS 流程不需要腾讯云 COS；完整稿件同步及发布需要额外集成，见 [后续集成](docs/integrations.md)。

安装后先按指南完成首次登录、两个 Notion 数据源的字段初始化，再配置 RSS 源和正向关键词。

## Alpha 限制

- 单个管理员账号，无多用户权限或租户隔离。
- RSS 每天 `06:00 Asia/Shanghai` 调度，同一天最多执行一次。服务当天已空跑时，新增源可能要等次日；当前没有手动抓取入口。
- 未配置翻译服务时可能保留原文；未配置 Embedding 时按字面与 BM25 筛选并显示降级状态。安装成功不表示所有 AI 功能已启用。
- 博客与渲染器依赖 Linux 用户命名空间和 bubblewrap 沙箱，宿主不支持时会明确失败。
- 博客上线校验仍限定维护者站点，任意博客域名尚未支持；自己的 GitHub 仓库与 Token 不足以完成接入。
- 数据库与配置仍可能演进，升级前须备份；回滚应用不会自动回滚数据库。

## 文档与贡献

- [自托管、首次验收](docs/self-hosting.md)
- [备份、恢复与升级](docs/self-hosting-operations.md)
- [AI、COS、博客、公众号及通知集成](docs/integrations.md)
- [贡献指南](CONTRIBUTING.md) · [安全问题反馈](SECURITY.md)
- [维护者现有生产部署手册](docs/runbook.md)（ACR / 外部 PostgreSQL 路径）

应用采用 React / TypeScript / Vite 前端、Python / FastAPI 后端和标准 PostgreSQL。部署为模块化单体，业务时间统一为 `Asia/Shanghai`，数据库存储 UTC。

## 许可证

Reven 原创代码采用 [Apache-2.0](LICENSE)，版权持有人为 Wang Yiyang。
第三方代码、字体、依赖和开发工具保留各自许可；其中 Doocs 为 WTFPL v2，Trellis 工具模板为 AGPL。具体边界和分发声明见 [第三方声明](THIRD_PARTY_NOTICES.md)。
