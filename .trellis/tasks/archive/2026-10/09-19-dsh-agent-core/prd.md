# 集成 DeepSeek Harness (dsh) 作为 Agent 核心（LLM 推理与通用工具层）

> 来源：GitHub issue #123。关联：#119（飞书机器人，本 issue 升级其智能层）、#120（Vercel 部署，本次正式拍板放弃 serverless 主部署形态）、#121（多租户，dsh 会话/凭证届时按租户隔离）。

## Goal

以 dsh（sdk profile，官方 Python SDK 嵌入式拉起）作为 Reven 的 Agent 核心，承载 LLM 推理与通用工具编排；以 RSS 关键词 CRUD 为首个工具集跑通自然语言端到端路径，为 #119 飞书机器人的智能层奠基。

## 已拍板决策（2026-09-19 grilling 结论）

| # | 决策 | 结论 |
|---|---|---|
| Q2 | DeepSeek 凭证来源 | 走前端集成页配置（复用 integrations 模式），不用环境变量 |
| Q3 | 交付形态 | 直接写生产模块 `server/src/reven/agent/`，不做一次性 PoC |
| Q4 | 自然语言入口 | `POST /agent/chat` 调试端点（鉴权），飞书接入留给 #119 |
| Q5 | 部署形态 | **正式拍板容器/VPS**；Vercel serverless 不再是主部署形态（比 issue 原文"集中处理时联合拍板"更激进，owner 已确认） |
| Q6 | 工具回调架构 | ~~进程内宿主工具~~ → **MCP streamable-http loopback（方案 B2）**：M0 spike 实测 sdk profile 无宿主工具协议，dsh-mcp-client patch insert 为官方路径，已实测端到端通过 |
| Q7 | 进程模型 | 单例嵌入式子进程，FastAPI lifespan 持有，同步 SDK 用 `to_thread` 包装；M0.4 实测多 session 真并发，不加全局锁 |
| Q8' | 配置抽象 | 通用 `agent-llm` 集成通道（provider/model/base_url + api_key），不写死 DeepSeek |
| Q9 | infra 落地物 | 本 PR 直接改 Dockerfile 与 compose |
| Q10 | #119 同步 | docs 落架构文档 + #119 评论链接，不改 issue 正文 |

默认决定（可否决）：模型默认 `deepseek-v4-flash` 可配置；`dsh_home` 默认数据目录下 `.dsh-runtime/`（不进 git、容器挂卷）；CI 只跑无 key 的拉起握手测试，真实会话为手动验收。

## Requirements

- R1 `reven.agent` 模块：dsh 单例生命周期封装（lifespan 启动/关闭、`HarnessClient`/`DeepSeekHarness` 包装、并发保护、未配置时优雅降级）。
- R2 `POST /agent/chat` 调试端点：鉴权后可用，输入自然语言返回 dsh 最终响应；session_id 可传入以延续会话。
- R3 `agent-llm` 集成配置：后端注册 provider（公开配置 `provider`/`model`/`base_url`，secret `api_key`，走 `encrypted_secret` + `reven_master_key` 既有加密模式）；前端 `PROVIDERS` 加一条声明复用现有卡片。
- R4 RSS 关键词 CRUD 封装为 dsh 工具集（create/list/update/delete）：FastAPI 进程内挂 MCP streamable-http 端点（loopback + 内部 token），经 `dsh-mcp-client` patch insert 注入 dsh，直连 `RssSettingsRepository`（M0.3 实测证伪 incoming-request 方案后的已定路线）。
- R5 部署落地：Dockerfile 支持 dsh runtime（SDK 依赖 + `DSH_HOME` 可写目录），compose 加 env/卷占位；文档记录容器/VPS 拍板结论及与 #120 的关系。
- R6 文档：`docs/` 落 agent 架构文档（含自然语言路径 vs 确定性卡片/指令路径的边界），#119 评论同步。

## 非目标（Out of Scope）

- 飞书 webhook/事件订阅/卡片协议（#119 范围）。
- 多租户会话与凭证隔离（#121 范围）。
- 多 provider 实际验证（schema 不堵死，但本 PR 只跑通 deepseek-official）。
- Vercel serverless 适配（已拍板放弃）。

## 约束

- 后端 Python 3.12、uv 管理依赖、mypy strict + ruff（line-length 120）、pytest 覆盖。
- 密钥类信息一律加密入库，禁止硬编码、禁止进 git。
- dsh SDK 为 0.1.x rc 版本，封装层需薄，隔离上游变动。
- GitHub Flow：本分支 `issue/gh-123-feat-deepseek-harness-dsh-agent-llm` 经 PR 合并回 main。

## Acceptance Criteria

- [ ] AC1（M1，CI 可跑）：无 API key 环境下，集成测试完成 dsh sdk profile 拉起 + initialize 握手 + 优雅关闭。
- [ ] AC2（M2，手动验收，需 key）：配置 `agent-llm` 后，`POST /agent/chat` 完成一次真实问答并返回结果。
- [ ] AC3（M3，手动验收，需 key）：自然语言指令（如"加一个正向关键词：AI Agent"）端到端跑通 RSS 关键词 CRUD，结果在既有 RSS 设置接口/页面可见。
- [ ] AC4：`agent-llm` 在前端集成页可配置，secret 加密入库且接口不回显明文。
- [ ] AC5：Dockerfile 构建通过，镜像内 dsh 可用；compose 含 `DSH_HOME` 卷与 env 占位。
- [ ] AC6：`docs/` agent 架构文档落地（含与 #119 的边界、部署形态拍板结论），#119 已评论同步。
- [ ] 质量门：ruff、mypy strict、pytest 全绿。
