# Agent (dsh) 集成契约

> 来源：#123 / 任务 09-19-dsh-agent-core（2026-09-19，M0 spike 实测 + 端到端验收证据）。约定 `server/src/reven/agent/` 模块与 dsh 运行时的集成事实，改动该模块前必读。

## 架构事实（实测验证，勿重新调研）

- **dsh 是 FastAPI 进程持有的嵌入式子进程**（`deepseek-harness-sdk` 拉起 `dsh --profile sdk`，stdio NDJSON-RPC），不是独立部署的 sidecar 服务。生命周期挂 `app.py` `_lifespan`。
- **sdk profile 的 JSON-RPC 仅三个方法**：`initialize` / `session/prompt` / `shutdown`。不存在宿主注册自定义工具的协议入口；incoming-request 通道是用户提问/审批用途。
- **自定义工具唯一可行路径 = MCP**：profile patch 用 `- insert:` 语法插入 `@deepseek-ai/dsh-mcp-client`（已编译进 runtime 二进制，无需 pnpm）；平铺 `- id/name/config` 只能覆盖既有条目（否则报 `entry "<id>" not found`）。
  - 工具在模型侧名称为 `mcp__<serverName>__<tool>`。
  - patch 内运行时值用 `!!js process.env.X` 表达式，变量由 `AgentRuntime._launch` 注入子进程 env——凭证不落盘。
  - **patch 覆盖既有条目时 config 是整体替换语义**：如 `system-prompt` 只写 `personaSuffix` 会静默丢弃 sdk 原 `personaPrefix`，两键必须显式同列（09-28 关键词任务踩坑，test_dsh_patch 有组合断言）。
- **并发**：SDK 同步客户端（reader 线程 + waiters），单实例多线程 `run()`（独立 session_id）实测真并发，**不要加全局锁**；FastAPI 侧一律 `anyio.to_thread.run_sync` 包装。
- 内建 coding 工具（tool-bash/tool-pwsh/tool-fs/tool-fs-search/tool-skill/tool-subagent-control/tool-subagent-list-agents/tool-jobs）在 IM 场景用 patch `disabled: true` 关闭（`agent/dsh.patch.yml` 为准）。

## 模块契约

- `agent/config.py`：`resolve_agent_config()` 优先级 = integrations 表 `agent-llm`（SecretBox 解密）> env/Settings fallback；读取/解密失败记日志降级，不抛出。
- `agent/runtime.py`：启动失败**不抛出**——置不可用 + 结构化日志（fail-fast 已被拍板否决）；`chat` 在该状态抛 `AGENT_RUNTIME_UNAVAILABLE`（502）；未配置抛 `AgentNotConfiguredError`（503）。
- `agent/mcp_server.py`：MCP 端点挂 `/agent/mcp`（非 `/api/*`，避开 AuthMiddleware 会话拦截），Bearer token 鉴权（缺省进程内随机 `token_hex(32)`）；CSRF 中间件经 `exempt_prefixes` 豁免该前缀（机器端点无 CSRF 威胁模型）。
- `agent/service.py`：`chat(message, session_id)`；session_id 缺省生成 UUID hex 并随响应返回。
- **dsh 会话无 resume 语义**（SDK 仅 `session/prompt`）：进程重启后，磁盘上已存在的 session_id 再 prompt 报 `JsonRpcError: session "..." already exists`，该会话永久不可用（#161，2026-09-30 生产实测）。`AgentRuntime.chat` 的应对：进程内 `_session_aliases` 映射外部 id → 活跃 id，捕获 already exists 冲突后重铸 `~r` 后缀新 id、记别名、重试一次；别名不持久化，重启后首次冲突再次重铸（预期行为）。调用方（如飞书桥接）可以丢弃返回的 session_id——别名常驻 runtime 进程内。
- `agent/tools_rss.py`：关键词 MCP 工具写路径（create/update）成功后**必须触发 `RssEmbeddingRefresher.refresh()` 增量刷新**——无 embedding 的关键词在语义筛选中静默不生效（REST 侧靠 `/embeddings/rebuild`，MCP 侧曾无人触发，#153 修复）；refresh 失败返回成功但标 `embedding_status=pending`（词已入库，下轮兜底），不静默不抛出。
- 路由为 `/api/agent/chat`（非 PRD 字面的 `/agent/chat`）——挂 `/api/*` 下才能被 AuthMiddleware fail-closed 保护。

## 配置与部署

- `agent-llm` 集成：公开配置 `provider`（默认 deepseek-official）/`model`（默认 deepseek-v4-flash）/`base_url`（可选，HTTPS origin 校验），secret `api_key`（加密入库、响应只回 hint）。
- **`AGENT_MCP_URL` 默认 `http://127.0.0.1:8000/agent/mcp`；非 8000 端口部署必须显式设置**，否则 dsh 回调连不上（症状：模型"不知道有工具"，不报错）。
- 配置变更需重启进程生效（本版限制）。
- 容器：`DSH_HOME=/data/dsh`（compose `dsh-data` 卷）；镜像内 `dsh --version` 可用作部署冒烟。
- **`read_only` 根文件系统的容器必须将 `HOME` 指向可写卷**（compose 设 `HOME: /data/dsh`）：dsh 运行时（pkg 打包的 Node）boot 时要在 `$HOME/.cache/pkg/` 创建插件缓存目录，只读 `$HOME`（如镜像默认的 `/home/reven`）下 mkdir 失败，症状为启动日志报 `dsh 运行时启动失败（error_type=JsonRpcError）`、Agent 按降级不可用（2026-09-28 生产实测踩坑；`PKG_CACHE_PATH` env 经实测无效）。
- 测试：DB 套件与 dsh 子进程测试混跑时，`conftest.py` 必须隔离 `AGENT_*/DSH_HOME` env（否则开发者 shell 残留 env 会级联污染无关用例——M1 踩过的坑）。

## 关联

- 文档：`docs/agent-architecture.md`（面向维护者的完整版）
- issue：#123（本契约来源）、#119（飞书路径边界）、#120（部署形态）、#121（多租户隔离）
