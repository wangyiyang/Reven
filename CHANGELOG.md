# Changelog

## [v0.7.1] - 2026-10-05

### 本版变更（自 v0.7.0）

**新功能**

- web 前端支持部署到 Vercel：新增 `web/vercel.json`（/api 优先代理 + SPA fallback）与部署文档 `docs/vercel-deploy.md`（#120 #200）。

**修复**

- CSRF Origin 校验新增白名单配置 `REVEN_CSRF_ALLOWED_ORIGINS`（逗号分隔、逐项归一化校验、默认空向后兼容）：前后端分域名部署（如前端在 Vercel）时浏览器写请求不再被 403 拒绝（#200）。

**基础设施**

- 生产镜像 runtime 基础镜像 digest 升级，并显式升级 `perl-base` 至 deb12u4，修复 3 个 CRITICAL CVE（CVE-2026-13221 / CVE-2026-42496 / CVE-2026-8376）。
- VPS 部署形态改为纯 API：Caddy 不再服务前端静态文件，前端唯一入口 Vercel；自托管形态（infra/self-host）不变（#120）。
- 修复 release 构建缓存导出无效配置（`image-manifest=true` 与 `oci-mediatypes=false` 互斥导致 buildcache 从未写入，历次构建全冷）；修复后后续 release 构建显著提速。

**数据库迁移**

- 无。

## [v0.7.0] - 2026-10-05

### 本版变更（自 v0.6.0）

**新功能**

- 工作台 Dashboard 首页：聚合端点 + 默认落地页（#198）。
- 统一抽屉组件重构：Notion 风视觉、滑入滑出动画与表单单列（#197）。
- talents 列表页去表单化：新建抽屉化、编辑收进详情页（#195）。

**基础设施**

- CI：Actions 升级到 node24 运行时并固定 ubuntu-24.04（#193）。

**数据库迁移**

- 无。

## [v0.6.0] - 2026-10-05

### 本版变更（自 v0.5.0）

**新功能**

- 多模型管理：模型注册表与集成页完整管理（增删改 / 设默认 / 启停 / 单模型测试），飞书 `/model` 指令切换会话模型（#166 #174）。
- CRM 人才库全量能力接入 Agent MCP 工具，Agent 可直接查询与维护人才库（#170）。
- 定时主动推送与 CRM 待跟进提醒（#172）。
- 各资源页面创建/编辑表单抽屉化，不再固定于页面顶部（#190）。

**安全与基础设施**

- 全站 TLS 化：Caddy 自动证书，发布 80/443，:3001 过渡保留（#175）。
- 安全批：限流 / 回显 / 删除防呆 / 日志脱敏（#181）。
- 容器 JSON 日志轮转上限（50m×3），防磁盘写满（#180）。
- 发布流水线修复：buildx 输出、注册表缓存与 ACR 媒体类型兼容（#164 - #168）。

**修复**

- 运行时可靠性批：健康检查 / 飞书 supervisor 与 harness 超时 / auth 写库 / 推送 claim（#184）。
- RSS 批：断点续跑 / 翻译告警 / 死源治理（#182）。
- 集成页数据丢失批（#183）。
- 平台侧栏菜单上对齐（#185）。
- dsh 会话重启 already exists 冲突自动重铸 session_id 重试（#162）。
- 生产 compose 同步 HOME 指向可写卷，修复 dsh 启动降级（#160）。

**架构**

- 深化 CRM、飞书交付与会话模型架构（#188）。

**数据库迁移**

- 0023 notification_logs、0024 rss_resilience：均为增量变更（新表与新列），不回滚历史数据；按[运维指南](docs/self-hosting-operations.md)升级前备份。

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
