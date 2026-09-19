# 技术设计：dsh 作为 Reven Agent 核心

## 总体架构（结论先行）

```
┌─ 一个容器 / 一台 VPS（唯一部署单元）──────────────────────────┐
│  FastAPI 进程（uvicorn）                                      │
│   ├─ lifespan: AgentRuntime.start()/close()                   │
│   │    └─ 子进程: dsh --profile sdk（stdio NDJSON-RPC，无端口） │
│   ├─ POST /agent/chat → AgentService → AgentRuntime.chat()    │
│   │                         ↑ 同步 SDK 经 anyio.to_thread 包装  │
│   ├─ MCP streamable-http 端点（loopback + 内部 token）          │
│   │    └─→ RssSettingsRepository（既有 ORM 层）                │
│   └─ dsh 子进程经 patch 注入的 dsh-mcp-client 回调上述端点       │
│  配置来源: IntegrationService("agent-llm") → provider/model/    │
│           base_url + api_key（encrypted_secret 解密后注入 env） │
└───────────────────────────────────────────────────────────────┘
```

核心决策：dsh 是 FastAPI 进程**持有并管理**的嵌入式子进程，不是独立部署的 sidecar 服务；工具调用走 **MCP streamable-http loopback**（dsh-mcp-client 插件回调 FastAPI 进程内的 MCP 端点），工具实现全留 Python 栈。

## 模块边界

新增 `server/src/reven/agent/` 包，职责拆分（每个文件 <500 行、函数 <50 行）：

| 文件 | 职责 | 依赖方向 |
|---|---|---|
| `config.py` | `AgentConfig`：从 IntegrationService 读 `agent-llm` 配置，映射为 SDK 参数；未配置返回 None | integrations → agent |
| `runtime.py` | `AgentRuntime`：持有 `DeepSeekHarness` 单例，start/close，asyncio.Lock 串行化，`to_thread` 包装同步调用 | agent 内部 |
| `mcp_server.py` | FastMCP streamable-http 端点：注册工具、内部 token 校验、挂载进 FastAPI | agent → rss |
| `tools_rss.py` | RSS 关键词工具集：参数 schema、执行（`RssSettingsRepository`）、结果序列化 | rss → agent |
| `dsh.patch.yml` | profile patch：insert mcp-client（指向 loopback MCP 端点）+ disable 内建 coding 工具 | 部署资产 |
| `service.py` | `AgentService`：`chat(message, session_id)` 业务入口，组装 dsh session | agent 内部 |
| `errors.py` | 错误类型：未配置 / runtime 不可用 / 工具执行失败，映射为明确 HTTP 错误 | agent 内部 |

API 层：`server/src/reven/api/routes/agent.py`（`POST /agent/chat`，复用既有鉴权依赖），在 `app.py` 注册路由并在 `_lifespan` 接入 `AgentRuntime`。

## 关键契约

### 1. dsh 生命周期

- 装配点：`app.py` 既有 `_lifespan`（partial 绑定），新增 `agent_runtime` 参数。
- 启动：`AgentRuntime.start()` → 读 `agent-llm` 配置 → 有配置则 `DeepSeekHarness(...)`（`dsh_home` 显式指定、`cwd` 为数据目录、`env` 注入 `DEEPSEEK_API_KEY`/`DEEPSEEK_BASE_URL`）并 `start()`；**无配置则跳过**，agent 端点返回 503 + 明确错误码（优雅降级，不影响其他路由）。
- 关闭：lifespan 退出时 `close()`，超时兜底用 SDK 的 `shutdown_timeout_seconds`。
- 配置热更新：本 PR 不做——配置变更需重启进程生效（写进文档）。

### 2. 并发模型

- SDK 为同步客户端（reader 线程 + waiters）；所有调用经 `anyio.to_thread.run_sync` 包装，不阻塞事件循环。
- **M0.4 已实测**：单实例多线程并发 `run()`（独立 session_id）真正并行成功，**无需全局锁**；不设串行化（YAGNI）。
- `session_id`：调用方可传，缺省由服务端生成 UUID 并在响应中返回，供后续延续会话。未来飞书路径映射为 `feishu:{chat_id}:{user_id}`。

### 3. 工具机制（M0.3 实测结论：MCP 方案 B2）

- **sdk profile 的 JSON-RPC 仅三个方法**（`initialize`/`session/prompt`/`shutdown`），无宿主工具声明入口；incoming-request 通道是用户提问/审批用途，不能注册工具。
- 工具来自 profile 插件组合：随仓库发布 `dsh.patch.yml`，用 `- insert:` 语法插入 `@deepseek-ai/dsh-mcp-client`（已编译进 runtime 二进制，无需 pnpm），`transport: streamable-http` 指向 FastAPI 进程内 MCP 端点（`http://127.0.0.1:<port>/agent/mcp`，带内部 token 头）。
- 同一份 patch 用 `disabled: true` 按 id 关掉 sdk profile 内建的 coding 工具（bash/fs/pwsh/subagent 等）——IM 机器人场景不需要也不应暴露 shell。
- 工具在模型侧呈现为 `mcp__reven__<tool>`（serverName 命名空间）。
- RSS 关键词工具集（首个工具集，对齐既有 Repository 签名）：
  - `rss_keyword_create(term, kind, enabled)` → `create_keyword`
  - `rss_keyword_list()` → `list_keywords`
  - `rss_keyword_update(keyword_id, ...)` → `update_keyword`
  - `rss_keyword_delete(keyword_id)` → `delete_keyword`
  - 冲突错误（`RssSettingsConflictError`）映射为结构化工具错误，让模型能向用户解释。

### 4. 配置与凭证

- provider key：`agent-llm`；`public_config` = `{ provider, model, base_url? }`，secret = `{ api_key }`。
- 后端：在 provider 注册表（`integrations/providers.py` 体系）注册 `agent-llm` + PUT 模型；前端 `web/src/features/integrations/types.ts` 的 `PROVIDERS` 加一条定义，复用通用卡片。
- 默认值：`provider=deepseek-official`、`model=deepseek-v4-flash`；dsh 多 provider 能力（openai/anthropic/azure/bedrock/openrouter）经 `provider`+`base_url` 字段保留扩展面，本 PR 不验证。
- `dsh_home`：默认 `<数据目录>/.dsh-runtime/`（本地即 repo 下，加 `.gitignore`；容器挂卷 `/data/dsh`）。

### 5. 部署形态（Q5/Q9）

- Dockerfile runtime 阶段：`deepseek-harness-sdk` 加入 `server/pyproject.toml` 依赖（uv 锁定，含 linux 二进制 wheel——**M0 需验证 linux/x86_64 wheel 存在**）；`mkdir /data/dsh && chown reven`；env 增加 `DSH_HOME=/data/dsh` 占位。
- compose：`/data/dsh` 卷挂载 + env 占位。
- 文档明确：Vercel serverless 不再是主部署形态（dsh 需可拉起进程），#120 在此结论上继续。

## 兼容性与风险

| 风险 | 缓解 |
|---|---|
| dsh SDK 0.1.x rc，上游变动 | 封装集中在 `runtime.py` 一处；版本在 uv.lock 锁死 |
| linux wheel 不存在或运行异常 | M0 spike 首要验证项；失败则上报阻塞，不强行推进 |
| 宿主工具协议不存在（M0.3 证伪） | 已切换 MCP 方案 B2 并实测端到端通过 |
| dsh 子进程崩溃 | SDK 有 `TransportClosedError`；首版返回 502 + 日志，自动重启留后续迭代 |
| 会话日志落盘增长 | `dsh_home` 挂卷；清理策略留后续迭代 |

## 回滚

- 配置层：删除 `agent-llm` 集成配置 → lifespan 不拉起 dsh，系统回到无 agent 状态。
- 代码层：PR 为纯新增（新包 + 新路由 + 注册表条目 + infra 增量），revert 即可。
