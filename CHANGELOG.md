# Changelog

## [v0.5.0] - 2026-09-30 · 开源 Alpha

首个公开发布。Reven 定位为**面向独立创作者的单用户、自托管内容运营工作台**：以 RSS 内容发现、人工筛选、本地素材库与飞书通知为核心场景。

### 安装

- **源码构建（默认）**：按[自托管指南](docs/self-hosting.md)，Linux AMD64 + Docker Compose ≥ 2.24.4，无需任何镜像仓库账号。
- **公开镜像**：`ghcr.io/wangyiyang/reven@sha256:<digest>`（digest 见 [GitHub Release](https://github.com/wangyiyang/Reven/releases)），与维护者生产发布为同一产物，经 Trivy CRITICAL 门禁扫描。镜像入口说明见自托管指南「镜像来源二」。
- 运维（升级/备份/恢复/回滚）见[运维指南](docs/self-hosting-operations.md)；集成能力与费用见[集成说明](docs/integrations.md)。

### 本版变更（自 v0.4.1）

- 开源发布准备：Apache-2.0 许可证与第三方声明、全历史凭据扫描复核（脱敏报告归档，无未处理真实凭据）、仓库个人绑定清理、GHCR 公开镜像通道。
- 安全契约：HTTPS 公网入口、CSRF 双重校验（Origin + `X-Reven-CSRF`）、会话 Cookie Secure 属性随协议切换；HTTP 仅限本机回环或安全隧道。
- 飞书消息改用 interactive 卡片渲染 markdown，失败自动降级纯文本。

### Alpha 已知限制

- 单用户、单管理员；不提供注册流程，请勿作为多租户服务暴露公网。
- RSS 发现任务每日 06:00（Asia/Shanghai）执行一次，首次安装次日才有候选；当前无手动抓取入口。
- 翻译/Embedding/Qwen 未配置时按字面与 BM25 保守筛选并显示降级状态，AI 能力不完整。
- 数据库迁移 0021 不可降级；回滚应用不会回滚数据库。升级前必须备份。
- 正式支持 Linux AMD64；ARM64 与 Docker Desktop 未验证。

## 历史版本（公开发布前）

| 版本 | 主要内容 |
| --- | --- |
| v0.4.1 | 飞书消息 interactive 卡片渲染 |
| v0.4.0 | 飞书机器人私聊/群聊@接入 Agent 对话 |
| v0.3.1 | 清理不可达的审核卡片回调 |
| v0.3.0 | 统一应用机器人通知，退役 Webhook |
| v0.2.0 | 集成 DeepSeek Harness (dsh) 作为 Agent 核心 |
| v0.1.0 | 首个内部版本 |
