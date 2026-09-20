# Reven Agent 架构（dsh 嵌入式 Agent 核心）

> 关联：GitHub issue #123（本层实现），#119（飞书机器人，消费本层服务），
> #120（Vercel 部署，在本层拍板结论上继续），#121（多租户，届时隔离会话与凭证）。

Reven 的 Agent 核心由 DeepSeek Harness（dsh，sdk profile）以**嵌入式子进程**
形态承载 LLM 推理与工具编排：FastAPI 进程在 lifespan 中拉起并持有唯一的 dsh
实例，工具调用经 MCP streamable-http loopback 回到本进程执行。**dsh 不是独立
部署的 sidecar 服务**——它没有自己的端口、容器或生命周期，全部由内嵌于
`reven.agent` 包的 `AgentRuntime` 管理。

## 1. 架构总览

```
┌─ 一个容器 / 一台 VPS（唯一部署单元）──────────────────────────────┐
│  FastAPI 进程（uvicorn，端口 8000）                                │
│   ├─ lifespan: AgentRuntime.start()/close()                       │
│   │    └─ 子进程: dsh（sdk profile，同步 SDK，stdio 通信，无端口）  │
│   ├─ POST /api/agent/chat → AgentService → AgentRuntime.chat()    │
│   │      （同步 SDK 调用经 anyio.to_thread 包装，不阻塞事件循环）    │
│   ├─ MCP streamable-http 端点 /agent/mcp（loopback + Bearer token）│
│   │      └─→ RssKeywordTools → RssSettingsRepository（既有 ORM 层）│
│   └─ dsh 子进程经 patch 注入的 dsh-mcp-client 回调上述 MCP 端点      │
│  配置来源: integrations 表 agent-llm（优先）/ AGENT_* env（fallback）│
└───────────────────────────────────────────────────────────────────┘
```

一次自然语言请求的完整链路：调用方 POST `/api/agent/chat` → `AgentService.chat()`
→ `AgentRuntime.chat()`（线程池执行同步 `harness.run(message, session_id=...)`）→
dsh 子进程调用 LLM 推理 → 模型决定调用工具时，经 patch 注入的
`@deepseek-ai/dsh-mcp-client` 以 streamable-http 回调本进程 `/agent/mcp` →
FastMCP 校验 Bearer token 后执行工具（直连 Repository）→ 结果回包给 dsh →
模型生成最终响应 → API 返回 `(session_id, response)`。

模块边界（`server/src/reven/agent/`，封装层刻意保持薄，隔离上游 0.1.x 变动）：

| 文件 | 职责 |
|---|---|
| `config.py` | `AgentConfig` 与 `resolve_agent_config()`：integrations 表优先、env fallback，未配置返回 None |
| `runtime.py` | `AgentRuntime`：持有 `DeepSeekHarness` 单例，start/close/chat，启动失败降级 |
| `service.py` | `AgentService`：API 层业务入口，薄封装 runtime |
| `mcp_server.py` | FastMCP streamable-http 子应用：工具注册、Bearer token 校验、挂载进 FastAPI |
| `tools_rss.py` | RSS 关键词 CRUD 工具集（首个工具集），直连 `RssSettingsRepository` |
| `dsh.patch.yml` | profile patch：insert mcp-client + disable 内建 coding 工具 |
| `errors.py` | 错误类型与稳定错误码（503 未配置 / 502 运行时不可用） |

关键决策记录：

- **工具机制走 MCP loopback（方案 B2）**。M0.3 实测证伪了宿主工具协议：sdk
  profile 的 JSON-RPC 仅 `initialize`/`session/prompt`/`shutdown` 三个方法，无
  宿主工具声明入口。工具来自 profile 插件组合，随仓库发布 `dsh.patch.yml` 用
  `- insert:` 语法插入官方 `@deepseek-ai/dsh-mcp-client`（已编译进 runtime
  二进制），transport 为 streamable-http。模型侧工具呈现为 `mcp__reven__rss_keyword_*`
  （serverName 命名空间）。
- **同步 SDK 不设全局锁**。M0.4 实测单实例多线程并发 `run()`（独立 session_id）
  真正并行成功；所有调用经 `anyio.to_thread.run_sync` 包装即可，不阻塞事件循环。
- **优雅降级是拍板行为**。未配置或启动失败时，应用照常启动、其余路由不受影响；
  仅 agent 端点返回明确错误码。

## 2. 配置指南

### 2.1 推荐路径：前端集成页

在集成页配置 **Agent LLM**（provider key 为 `agent-llm`）：

- 公开配置：`provider`（默认 `deepseek-official`）、`model`（默认
  `deepseek-v4-flash`）、`base_url`（可选，必须是 HTTPS origin，用于覆盖官方
  端点或接入兼容 OpenAI 的服务）。
- 密钥：`api_key`，经 `encrypted_secret` + `REVEN_MASTER_KEY` 既有模式加密入库，
  接口只回显掩码 hint，不回显明文。密钥类信息禁止硬编码、禁止进 git。
- 配置变更**需重启进程生效**：dsh 只在 lifespan 启动时读取一次配置，本版不做热
  更新（已知限制，见第 7 节）。

### 2.2 env fallback

integrations 表未配置时，回退读取应用 Settings（对应 env 变量）：

| Settings 字段 | env | 默认值 | 说明 |
|---|---|---|---|
| `agent_api_key` | `AGENT_API_KEY` | 无 | 未设置则 Agent 整体降级为未配置 |
| `agent_provider` | `AGENT_PROVIDER` | `deepseek-official` | LLM provider |
| `agent_model` | `AGENT_MODEL` | `deepseek-v4-flash` | 模型 |
| `agent_base_url` | `AGENT_BASE_URL` | 无 | 覆盖端点 |
| `dsh_home` | `DSH_HOME` | `.dsh-runtime`（本地，已 gitignore） | dsh 运行时数据目录 |
| `agent_mcp_token` | `AGENT_MCP_TOKEN` | 进程内随机生成 | MCP 端点 Bearer token |
| `agent_mcp_url` | `AGENT_MCP_URL` | `http://127.0.0.1:8000/agent/mcp` | dsh 回调本进程 MCP 端点的地址 |

**端口警告**：`AGENT_MCP_URL` 默认指向 `127.0.0.1:8000`。uvicorn 不以 8000 端口
监听时（非标准端口部署），**必须显式设置 `AGENT_MCP_URL`**，否则 dsh 回调不到
MCP 端点，工具调用全部失败。compose 标准部署端口即 8000，无需覆盖。

### 2.3 配置解析顺序与降级语义

`resolve_agent_config()` 先读 integrations 表：读取或解密失败只记日志并继续
fallback，绝不在 lifespan 阶段抛出。最终无可用 `api_key` 时 `AgentConfig` 为
None，`AgentRuntime.start()` 为空操作，`POST /api/agent/chat` 返回
`503 AGENT_NOT_CONFIGURED`。

## 3. 路径边界：与 #119 的分工

本层只负责**自然语言路径**：dsh 推理 + MCP 工具编排，入口为调试端点
`POST /api/agent/chat`（挂 `/api/*` 前缀下，自动获得全局会话鉴权——这是对
PRD 字面 `POST /agent/chat` 的安全必要修正）。`session_id` 可传入以延续会话，
缺省由服务端生成 UUID 并在响应中返回。

以下不属于本层，归 #119（飞书机器人）：

- 飞书 webhook、事件订阅、卡片协议；
- **确定性指令/卡片路径**（固定指令直调业务接口、不经 LLM 推理），自研实现；
- IM 侧的会话映射。未来飞书路径的 session_id 约定为
  `feishu:{chat_id}:{user_id}`，与本层 `AgentService.chat()` 复用同一服务层。

## 4. 部署形态拍板结论

**容器/VPS 是唯一主部署形态，Vercel serverless 已正式放弃**（2026-09-19 拍板，
owner 确认）。理由：dsh 需要在 FastAPI 进程内拉起子进程并持有可写的 `dsh_home`
目录，与 serverless 的执行模型直接冲突。#120 在此结论上继续，不再适配
serverless。

落地物：

- Dockerfile runtime 阶段：预建 `/data/dsh` 并 chown 给运行用户 `reven`，env
  注入 `DSH_HOME=/data/dsh`；`deepseek-harness-sdk`（锁版本 ≥0.1.5rc1,<0.2）
  随 uv 锁定进镜像，linux/x86_64 与 aarch64 wheel 已实查存在。
- compose：`dsh-data` 卷挂 `/data/dsh` 持久化 dsh 运行时数据（profile、会话
  日志）；`DSH_HOME` env 占位；`agent-llm` 的 api_key 走前端集成页配置，不经
  env 注入。
- 本地开发：`dsh_home` 默认 `.dsh-runtime/`（repo 下，已加入 `.gitignore`）。

## 5. 安全模型

- **`/agent/mcp` 独立 Bearer token 鉴权**。该端点不在 `/api/*` 前缀下，不经
  AuthMiddleware 会话拦截，由 FastMCP `StaticTokenVerifier` 独立校验。token
  缺省为进程内随机值（`secrets.token_hex(32)`，每次重启轮换），仅经 env 注入
  dsh 子进程：不进 git、不写日志；可用 `AGENT_MCP_TOKEN` 固定。默认回调地址
  为 `127.0.0.1` loopback，公网匿名不可用。
- **CSRF 豁免理由**：`CsrfOriginMiddleware` 对 `/agent/mcp` 显式豁免——该端点
  走 Bearer 头做机器对机器调用，不经浏览器 cookie 会话，无 CSRF 威胁模型。
- **`/api/agent/*` 走全局会话鉴权**：与其他业务 API 同一套 AuthMiddleware。
- **凭证不落盘**：MCP 地址与 token 由 `dsh.patch.yml` 中的 `!!js` 表达式在 dsh
  进程内读取 `REVEN_AGENT_MCP_URL` / `REVEN_AGENT_MCP_TOKEN`，两个变量由
  `AgentRuntime` 仅经子进程 env 注入。
- **内建 coding 工具已禁用**。sdk profile 默认携带 bash/fs 等 coding-agent
  工具，IM 机器人场景不应暴露 shell。`dsh.patch.yml` 按 id 禁用：
  `tool-bash`、`tool-pwsh`、`tool-fs`、`tool-fs-search`、`tool-skill`、
  `tool-subagent-control`、`tool-subagent-list-agents`、`tool-jobs`。
- **工具写语义与 API 一致**：`RssKeywordTools` 每次调用独立开库会话并提交；
  冲突错误（`RssSettingsConflictError`）映射为结构化工具错误（含错误码与
  下一步提示），让模型能向用户解释而非静默失败。

## 6. 运维要点

- **dsh_home 数据增长**：会话日志与 profile 落在 `dsh_home`（容器内
  `/data/dsh`，由 `dsh-data` 卷持久化）。本版无自动清理策略，后续迭代补充；
  期间需关注卷占用。
- **子进程崩溃行为**：启动失败时 `AgentRuntime` 标记不可用并记结构化日志，应用
  照常启动，`chat` 返回 `502 AGENT_RUNTIME_UNAVAILABLE`；会话执行中 SDK 抛
  `HarnessError` 时返回 `502 AGENT_CHAT_FAILED`。崩溃自动重启留待后续迭代，
  当前处置为重启进程。
- **并发**：多 session 并发已实测（M0.4，独立 session_id 真并行），无全局锁；
  同步 SDK 调用全部经线程池包装，不阻塞事件循环。
- **优雅关闭**：lifespan 退出时 `AgentRuntime.close()` 关闭子进程，幂等。

## 7. 已知限制与后续方向

| 事项 | 现状 | 方向 |
|---|---|---|
| 配置热更新 | 不支持，改配置需重启进程 | 后续迭代评估 |
| 崩溃自愈 | 502 + 日志，手动重启 | 自动拉起留后续迭代 |
| 会话日志清理 | 无策略，挂卷持久化 | 清理策略后续迭代 |
| 多租户隔离 | 全局单实例单凭证 | #121 按租户隔离会话与凭证 |
| 多 provider | schema 不堵死（provider/base_url 可配），但仅实测 `deepseek-official` | 需要时逐个验证 |
| 工具子代理 | `tool-subagent` 本体仍启用（其控制面 `tool-subagent-control` 已禁用） | 是否一并禁用待拍板 |
| 飞书接入 | 本层只提供 `/api/agent/chat` 与 `AgentService` | #119 接入同一服务层 |

## 8. 调试端点契约

```
POST /api/agent/chat        （全局会话鉴权）
请求: { "message": string(1..8000), "session_id": string(1..128, 可选) }
响应: { "session_id": string, "response": string }
错误: 503 AGENT_NOT_CONFIGURED（未配置 api_key）
      502 AGENT_RUNTIME_UNAVAILABLE / AGENT_RUNTIME_NOT_STARTED / AGENT_CHAT_FAILED
```

示例（手动验收路径）：配置 `agent-llm` 并重启后，发送"帮我加一个 RSS 正向关键
词：AI Agent"，模型将原生调用 `mcp__reven__rss_keyword_*` 工具完成落库，结果可
经既有 `GET /api/rss/keywords` 接口与设置页面确认。
