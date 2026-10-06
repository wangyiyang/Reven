# Research: LangChain / LangGraph 异步运行时与 PostgreSQL 接入契约

- Query: 为现有 37 个业务工具选择简单 Agent、数据库检查点、持久确认、配置快照及安全恢复的实际接入方式。
- Scope: mixed；当前仅规划，只写本文件；未安装依赖、运行模型、改产品代码或执行 Git 操作。
- Date: 2026-10-06

## Findings

### 结论与宿主边界

1. 可采用 `langchain.agents.create_agent`，返回的 LangGraph 图支持 `ainvoke`、`astream`、异步工具和 PostgreSQL 检查点，无须自行重建 Agent 循环。[固定版本 factory](https://github.com/langchain-ai/langchain/blob/langchain%3D%3D1.4.3/libs/langchain_v1/langchain/agents/factory.py)
2. 推荐直接将业务函数适配为 `StructuredTool`，以服务端可信上下文调用统一工具执行入口。MCP adapter 能复用协议，但无法跨 HTTP 共享 SQLAlchemy 事务，也不自动传递业务 actor。
3. 检查点与业务操作账本职责不同：前者保存图状态；后者证明业务提交，并防止图重放导致重复写。二者即使在同一个 PostgreSQL 库，也不是同一事务。[Saver 源码](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py)
4. 本任务不需要 Redis、Temporal 或新增持久队列。可采用“运行状态入库 → 进程执行 → 重启标 interrupted → 原用户明确恢复”；这不承诺后台任务自动调度、重试或持续运行。Checkpointer 本身不提供任务队列、同会话串行或身份认证。

### 内部文件与代码模式

| 文件 | 当前事实及研究用途 |
| --- | --- |
| `server/pyproject.toml:6` | Python ≥3.12；FastAPI ≥0.116、SQLAlchemy async、asyncpg、FastMCP ≥4 已存在。 |
| `uv.lock:514`、`:526`、`:597` | DSH runtime/SDK 锁定 0.1.5rc1；FastMCP 锁定 4.0.5。 |
| `server/src/reven/agent/runtime.py:27` | `_launch` 将 provider/model/base_url/api_key 传入 SDK；不是项目内的协议适配器。 |
| `server/src/reven/agent/config.py:71` | 指定模型每轮读取注册表；不可用返回 None，禁止默默切换默认。 |
| `server/src/reven/integrations/providers.py:24` | `provider/model` 是稳定 ref；provider 为字符串，不是经过验证的协议枚举。 |
| `server/src/reven/agent/mcp_server.py:46` | 工具是服务端 bound async 方法；MCP 静态 Bearer 只标识 dsh-loopback 客户端。 |
| `server/src/reven/agent/tools_crm.py:16`、`tools_talents.py:18`、`tools_rss.py:47` | 显式注册 15 CRM + 18 人才 + 4 RSS 工具，无须运行时反射发现。 |
| `server/src/reven/agent/crm_tool_support.py:18` | 参数已有 UUID/枚举/日期、Annotated/Field 描述与领域校验。 |
| `server/src/reven/agent/tools_crm_customers.py:105` | 每次调用新建 AsyncSession；调用完整业务 service。 |
| `server/src/reven/crm/service.py:26`、`:37`、`:109` | service 内部 commit；仅在外层写操作记录不能原子提交结果。 |
| `server/src/reven/agent/tools_rss.py:71`、`:76`、`:77` | RSS 先提交关键词，再刷新 embedding；后置动作失败须保留 pending 语义。 |
| `server/src/reven/db.py:21` | SQLAlchemy engine/session_factory 属于业务连接池；不是 psycopg checkpointer 池。 |

### 已核实的版本基线

以下是当日 PyPI 可见、非预发布的候选稳定版，不等同于已经完成全仓库依赖求解；实施时用 uv 生成并审查锁文件。

| 包 | 候选版本 | 一手版本来源 |
| --- | --- | --- |
| langchain | 1.4.3 | https://pypi.org/project/langchain/1.4.3/ |
| langgraph | 1.2.13 | https://pypi.org/project/langgraph/1.2.13/ |
| langchain-core | 1.6.6，传递依赖 | https://pypi.org/project/langchain-core/1.6.6/ |
| langchain-openai | 1.6.7 | https://pypi.org/project/langchain-openai/1.6.7/ |
| langchain-deepseek | 1.1.1 | https://pypi.org/project/langchain-deepseek/1.1.1/ |
| langgraph-checkpoint-postgres | 3.1.2 | https://pypi.org/project/langgraph-checkpoint-postgres/3.1.2/ |
| psycopg[binary] | 3.3.6 | https://pypi.org/project/psycopg/3.3.6/ |
| psycopg-pool | 3.3.3，若直接导入则声明 | https://pypi.org/project/psycopg-pool/3.3.3/ |
| langchain-mcp-adapters | 0.3.2，仅备选路线 | https://pypi.org/project/langchain-mcp-adapters/0.3.2/ |
| FastMCP | 现锁 4.0.5；最新 4.0.11 | https://pypi.org/project/fastmcp/4.0.11/ |

- 上述新增包 Python 下界均为 3.10，Python 3.12 满足声明条件；无须为迁移顺带升级已有 FastAPI/SQLAlchemy/asyncpg/FastMCP。
- `langchain==1.4.3` 要求 `langchain-core>=1.6.3,<2`、`langgraph>=1.2.11,<1.3`、Pydantic ≥2.7.4,<3。[版本源码](https://github.com/langchain-ai/langchain/blob/langchain%3D%3D1.4.3/libs/langchain_v1/pyproject.toml)
- `langchain-openai==1.6.7` 要求 core ≥1.6.6,<2、OpenAI SDK ≥2.45,<4；ChatDeepSeek 1.1.1 要求 openai 集成 ≥1.3.1,<2，声明范围相交。[OpenAI](https://github.com/langchain-ai/langchain/blob/langchain-openai%3D%3D1.6.7/libs/partners/openai/pyproject.toml)、[DeepSeek](https://github.com/langchain-ai/langchain/blob/master/libs/partners/deepseek/pyproject.toml)
- LangGraph 与 Postgres Saver 都要求 `langgraph-checkpoint>=4.1,<5`；Saver 要求 psycopg/psycopg-pool ≥3.2。不可照旧教程锁 checkpoint 2.x。[Graph](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/pyproject.toml)、[Saver](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/pyproject.toml)
- MCP adapter 0.3.2 要求 `langchain-core>=1.3.3,<2`、`mcp>=1.24,<2`；FastMCP 4 的实际 MCP 栈仍须单独核对，协议相容不能替代依赖求解。[adapter 声明](https://github.com/langchain-ai/langchain-mcp-adapters/blob/main/pyproject.toml)

### 异步 Agent 与工具契约

- `create_agent(model=BaseChatModel, tools=[BaseTool], system_prompt=..., middleware=..., context_schema=..., checkpointer=...)` 编译图；FastAPI 使用 `await graph.ainvoke(...)`，不再把整个 Agent 放入同步 SDK 线程。
- 固定版 factory 的异步模型节点调用 `await model_.ainvoke(messages)`，异步 middleware 应实现 `awrap_model_call` / `awrap_tool_call`，禁止在这些路径用同步数据库或同步模型请求。[factory](https://github.com/langchain-ai/langchain/blob/langchain%3D%3D1.4.3/libs/langchain_v1/langchain/agents/factory.py)、[middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)
- `StructuredTool.from_function(coroutine=bound_method, name=..., description=..., args_schema=...)` 支持原 bound async 函数、显式工具名及 Pydantic schema；原参数和领域验证继续复用。[StructuredTool 源码](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/tools/structured.py)
- `ToolRuntime` 可提供 `context`、`tool_call_id`、state/config/store；runtime 参数自动注入且不暴露给模型。actor、授权记录、run_id 必须来自服务端 context，不能让模型参数提供。[工具文档](https://docs.langchain.com/oss/python/langchain/tools)
- 工具执行可并行：ToolNode 异步路径使用 `asyncio.gather`。同会话串行不代表同轮工具串行。每个调用单独 AsyncSession；若按工具序列执行写操作，需明确限制并行策略并做 PoC，不能共用同一个 AsyncSession。[ToolNode](https://github.com/langchain-ai/langgraph/blob/main/libs/prebuilt/langgraph/prebuilt/tool_node.py)、[SQLAlchemy 并发限制](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-asyncsession-with-concurrent-tasks)
- 将原 FastMCP `ToolError` 在直接适配边界映射为受控工具错误；权限/账本冲突和未知执行结果不得吞成成功，也不能通过通用 retry middleware 自动重做写操作。

### 直接工具与 MCP adapter 的取舍

| 维度 | 直接 BaseTool / StructuredTool | MCP adapter |
| --- | --- | --- |
| 复用 | 复用函数、schema、业务 service；明确维护注册清单 | 复用当前 MCP 端点和工具清单 |
| actor | 通过服务端 ToolRuntime.context 或调用包装传递 | 必须新增可信身份传递及服务端校验；旧共享 token 不足 |
| 同事务账本 | 可在同一个 AsyncSession 参与真实业务事务 | 必须在 MCP 服务端实现；客户端外围记录不与业务原子提交 |
| 失败边界 | 函数调用/DB 提交边界直接可见 | 额外出现 HTTP 已执行但响应丢失的不确定窗口 |
| 依赖/生命周期 | 无新增 MCP client、会话、回环网络生命周期 | 新增 adapter、MCP client 和网络/协议兼容测试 |

推荐直接路线；MCP 若保留给外部调用，必须也进入同一授权/账本执行入口，否则形成绕过确认的写入口。仅装饰 37 个现有函数可用于能力 PoC，不能据此声称已满足同事务、actor 和幂等验收。

已核实备选 API：`MultiServerMCPClient({...})`、`await client.get_tools()`；工具名称默认不加 server 前缀，`tool_name_prefix=True` 使用下划线前缀，均不同于 DSH 的 `mcp__reven__...`。`client.session(...)` + `load_mcp_tools(session)` 可显式管理会话。自动创建的工具在无给定 session 时按调用建立会话；不要把 MCP session 当成业务会话或数据库事务。[client](https://github.com/langchain-ai/langchain-mcp-adapters/blob/main/langchain_mcp_adapters/client.py)、[tools](https://github.com/langchain-ai/langchain-mcp-adapters/blob/main/langchain_mcp_adapters/tools.py)

adapter 的 interceptor 可读取 runtime 并修改调用，但最终 actor 仍须在服务端认证。`isError=True` 可变为失败 ToolMessage；网络/会话异常仍会抛出，不能据此判断业务没执行。RSS 的 structuredContent 与原文本返回的表示差异也须回归。[官方 adapter README](https://pypi.org/project/langchain-mcp-adapters/0.3.2/)

### PostgreSQL Saver、DSN 与迁移

- 导入为 `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`；它接收 psycopg AsyncConnection 或 AsyncConnectionPool，不接收 SQLAlchemy AsyncSession、AsyncEngine 或 asyncpg pool。[aio](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/aio.py)
- `from_conn_string` 是 async context manager，内部设 `autocommit=True`、`row_factory=dict_row`、`prepare_threshold=0`。长生命周期应用建议在 FastAPI lifespan 持有独立 psycopg pool，退出时关闭。
- 自建 pool 用 `open=False` 后 `await pool.open()` / `await pool.wait()`；连接 kwargs 显式配置以上三项，避免在构造器里隐式异步开池。[psycopg pool](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)
- psycopg 接受 libpq DSN（`postgresql://...` 或 conninfo）。现有 `postgresql+asyncpg://...` 是 SQLAlchemy 方言 URL，不能原样传入；解析后构造普通 PG DSN，并逐项处理 ssl、编码和驱动专属 query 参数，不能无条件字符串替换。[conninfo](https://www.psycopg.org/psycopg3/docs/api/conninfo.html)
- `await saver.setup()` 会创建并升级自身表，读取 `checkpoint_migrations` 并依序执行内置 MIGRATIONS；基础表为 checkpoints/checkpoint_blobs/checkpoint_writes。它没有项目 Alembic revision，也未核实支持逆向迁移。[base](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/base.py)
- 规划应把 setup 纳入显式升级步骤，由单实例迁移进程执行；不要每个 worker 同时 setup，也不要手抄框架 DDL。业务 Agent 表仍走项目 Alembic。升级前备份；回滚业务运行时不等同于降级 checkpoint schema。
- `checkpoint_ns` 是图/子图命名空间，根图默认空字符串；它不是 PostgreSQL schema、租户权限或调度隔离。随意填非空顶层 namespace 可能使 get_state 按子图解析并报 Subgraph not found。[Pregel](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/pregel/main.py)
- 初版保持根 namespace 默认，thread_id 使用数据库拥有权明确的稳定会话 ID。若要 PG schema 隔离，固定连接 search_path，并在迁移/运行/备份中一致配置；这不是 saver 的 checkpoint_ns 参数。
- Saver 文档要求设置 `LANGGRAPH_STRICT_MSGPACK=true` 或显式允许的 msgpack 类型清单；自定义 state 保持可序列化且无密钥，不开启任意 pickle fallback。[Saver 发行说明](https://pypi.org/project/langgraph-checkpoint-postgres/3.1.2/)

### 人工确认与恢复的实际语义

- `HumanInTheLoopMiddleware(interrupt_on={name: {"allowed_decisions": ["approve", "reject"]}})` 在模型生成工具调用后、工具执行前 `interrupt`；同一批操作通过 action_requests/review_configs 给出，需要同数量且同顺序的 decisions。[固定版 HITL](https://github.com/langchain-ai/langchain/blob/langchain%3D%3D1.4.3/libs/langchain_v1/langchain/agents/middleware/human_in_the_loop.py)
- 未列入 interrupt_on 的工具默认自动批准；`True` 在 1.4.3 还允许 edit/respond。初版显式限制 approve/reject，不接受客户端更换工具、参数或合成工具结果；启动时校验全部危险操作均被策略覆盖。
- `result["__interrupt__"]` 表示已暂停；`await graph.aget_state(config)` 可读取持久 tasks/interrupts。使用同 thread_id：`await graph.ainvoke(Command(resume={"decisions": [...]}), config=..., context=...)`。[interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- 恢复会从被中断节点开头重跑，而不是恢复 Python 栈。因此，在 interrupt 前创建审批记录或其他副作用也必须幂等；不得先写业务再询问用户。
- 框架只验证决策类型/数量等，不认证批准人、不提供 CSRF、审批过期、单次消费或资源拥有权。REST 从已认证会话生成 actor；飞书从经校验的事件/交互身份生成 actor；两者都不能信任输入的 session_id、open_id 或 actor 字段。
- 宿主审批绑定 actor/session/run/interrupt/tool_call_id、工具名称、规范化参数 hash、目标实体及配置版本；在事务中原子记录决策。重放已消费的相同决策返回原状态，不重复执行；过期、拒绝、不同 actor 或参数不一致必须拒绝。
- 恢复后写入口再次校验批准记录和实际业务约束。逐字名称参数只能作为业务防误删检查，模型可以填写它，不能作为人类确认凭证。
- 若 HITL 政策/工具实现改变，旧审批不能无条件套用新图；加载原配置快照，无法兼容时明确阻止恢复并重新确认。

### 最小重启恢复方案及崩溃窗口

建议由宿主记录 run_id、actor、session、配置版本、请求去重键、当前状态和检查点关联；同会话仅允许一个进行中的 run。单进程 Alpha 可使用会话锁加数据库运行状态/唯一约束，遇到忙直接返回，不创建排队系统。

1. 正常新轮：提交 run/input 的业务记录，调用 `ainvoke` 追加带稳定 message_id 的用户消息；运行参数采用 `durability="sync"`，确保进入下一步前上一步检查点已持久化。默认 durability 是 async，不应沿用默认。[Pregel API](https://github.com/langchain-ai/langgraph/blob/main/libs/langgraph/langgraph/pregel/main.py)
2. 重启：确认旧进程已退出，旧 running 标 interrupted；待确认 run 保持 awaiting_confirmation。并发部署切换时不能简单把仍活跃的旧 worker 标中断，初版应明确单活进程部署约束。
3. 原用户请求恢复：先校验拥有权、运行状态、原配置及 `aget_state`；普通未完成图用 `ainvoke(None, 同 thread/config/context)`，HITL 用 `Command(resume=...)`。恢复不能重新追加原用户消息。
4. 安全检查点须能关联原 run、持久 AIMessage 与 tool_call_id；缺失或关联不明确则返回待核实。不能重新让模型生成同一写操作来“补恢复”；`checkpoint_id` 能定位快照，但任意旧快照回放会重放后续步骤。
5. 超时/取消：异步取消仅是协作请求。不能保证远端模型请求停止，更不能保证 DB commit 回滚。协程/执行者仍活跃时保持取消中并阻止同会话新执行；退出后从账本核实结果，不能把超时直接报“操作未发生”。

业务提交后的关键窗口：`业务 COMMIT → ToolMessage/checkpoint 写入`。即使 sync durability，这个窗口仍存在，必须使用应用账本：

- 以已持久工具调用生成稳定操作键（例如 run_id + tool_call_id）；绑定 actor、工具名、参数 hash。只有参数相同的同一操作可复用结果；仅用参数 hash 会误去重用户两次有意创建。
- 工具真正事务内先检查/锁定操作键，再校验审批、执行领域变更、持久结构化结果与 completed 状态，一次 commit；重复调用读取原结果并返回相同 ToolMessage，不重新 CRUD。
- 当前 service 自行 commit，因此必须改变真实事务 owner：可拆内部 flush 变更与公开完整事务包装，或加入明确事务参与点，使账本在真实 commit 前入库；保持 REST 原完整提交语义。外围先记 running、执行旧方法、再记 success 仍有两次提交窗口。
- 并发相同 key 用唯一约束/行锁协调；已完成的 delete 重放也返回原结果，不能因为实体已删除改报失败。
- 连接断开导致 COMMIT 结果未知：用新的连接查询操作键。完整同事务账本可区分已提交与已回滚；库不可达时待核实，禁止盲目重试。
- RSS 的 embedding 是提交后动作，关键词成功账本与 embedding_pending 分开表达；恢复不能因刷新失败再创建关键词。保留现有 refresher/调度补偿约定，不新增通用队列。

### Provider 覆盖范围与配置快照

- 已核实 Reven 只是透传 provider/model/base_url。官方 SDK 当前 README：provider 选择 Cordis 已注册路由，model 由该 adapter 解析；base_url/api_key 注入 DEEPSEEK_BASE_URL/DEEPSEEK_API_KEY；默认组合注册 deepseek-official。[SDK README](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)、[SDK API](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/src/deepseek_harness/api.py)
- **不能认定任意字符串 provider 自动注册成 OpenAI-compatible provider。** 当前上游 master 的 llm-deepseek 已使用 Messages-compatible 网关；项目锁定 0.1.5rc1，精确版本的运行时 provider 转换仍待读取对应 wheel/source，不能拿 master 或第三方插件推断旧配置兼容。[当前 adapter](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/llm/llm-deepseek/README.md)
- 推荐候选覆盖：deepseek-official → 经工具推理回传 PoC 验证的 `ChatDeepSeek`；经过确认的 OpenAI Chat Completions 标准端点 → `ChatOpenAI(base_url=..., model=...)`。第三方扩展或其他协议必须显式 adapter/protocol 映射；未知或不支持报模型不可用，保留原选择。
- ChatOpenAI 官方说明它只针对 OpenAI 标准，不保留第三方 reasoning_content/reasoning_details。[ChatOpenAI API 范围](https://docs.langchain.com/oss/python/integrations/chat/openai)
- DeepSeek 当前 thinking + tools 要求后续请求完整回传 reasoning_content；错误回传会 400。ChatDeepSeek 源码已确认保留响应字段，但其 `_get_request_payload` 与所继承 OpenAI 消息转换器未见重新注入该字段；不能据此宣称回传已经可用。实际请求、跨轮和检查点恢复是启用门槛，失败须补充明确的 Provider 适配。LangChain DeepSeek 页面仍有较旧 R1/V3 示例，不能当当前 V4 能力边界。[DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode/)、[ChatDeepSeek source](https://github.com/langchain-ai/langchain/blob/master/libs/partners/deepseek/langchain_deepseek/chat_models.py)、[OpenAI 转换器](https://github.com/langchain-ai/langchain/blob/master/libs/partners/openai/langchain_openai/chat_models/base.py)
- 每轮开始冻结 model_ref/provider/protocol/base_url、模型参数、prompt_version、tool_manifest_version、approval_policy_version、实现兼容版本；持久化快照只含非秘密配置和 credential reference。密钥、活对象、AsyncSession 不进入图 state/checkpoint metadata。
- 动态模型可用 awrap_model_call 的 `request.override(model=...)`；提示词可用 dynamic_prompt / system_message；工具可由请求 tools 过滤。初版无需按每个节点重新装配：以不可变 run context 读取这一轮快照，固定已注册工具集合。[自定义 middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)
- 配置保存影响下一轮；执行中切换模型不得改变本轮身份。恢复必须加载原 run 快照，同时重新验证现时 credential/启用状态及操作者权限；撤销后明确失败，不静默换默认。

### 相关规范

- `.trellis/workflow.md`：当前 planning；未 task.py start，无产品实施授权。
- `.trellis/tasks/10-06-agent-langgraph-migration/prd.md`：R1–R6；会话、确认、重复消息、超时与重启结果可核实。
- `.trellis/spec/reven-server/backend/agent-dsh-contract.md`：既有降级、模型身份/切换、MCP 认证、RSS 后置刷新及会话边界。
- `.trellis/spec/reven-server/backend/database-guidelines.md`：项目 Alembic 升级和空库迁移验证；框架 setup 要单独纳入升级流程。
- `.trellis/spec/tool-contracts/backend/`：现为占位，不能据此认定既有幂等/actor 契约已实现。

## Caveats / Not Found

尚未完成依赖安装、uv lock 求解、真实 PostgreSQL/模型运行，因此以下均是实施前 PoC 门槛：

1. Python 3.12 + 当前依赖全量求解、import、异步 create_agent、FastAPI lifespan 开关池；检查锁定依赖未无关升级。
2. 普通/带 SSL/特殊字符密码 DSN 转换，空库及重复 setup、升级 schema、根 namespace 的 aget_state。
3. 37 个工具 schema 与名称/参数/返回值等价；UUID、日期、枚举、Field description、bound self 不入模型 schema；写操作真实同事务账本。
4. 人工确认后重启再 approve/reject、多危险工具决策顺序、过期/错 actor/错会话/重复确认；未批准调用直接到工具或保留 MCP 入口均不能执行。
5. 强杀进程于“模型检查点前”“业务事务提交前”“commit 后/checkpoint 前”“checkpoint 后/run 状态前”；原用户恢复，各实体计数和账本结果一致，无重复消息/业务写入。
6. 并发请求、同批工具并行、手动恢复竞态及超时取消；验证同会话保护、独立 AsyncSession 和停止/未知状态，不能以一个 fake 单测声称取消已保证。
7. 已完成账本结果复用、delete 重放、COMMIT 回包丢失、新连接核实；恢复遇不到安全 checkpoint 时必须待核实。
8. DeepSeek V4 thinking + tool 多轮及 checkpoint 恢复的 reasoning_content 回传；至少一个真实已配置其他 Provider 的协议/参数/错误路径验证。
9. 读取锁定 DSH 0.1.5rc1 的 provider/base_url 真实行为；检查已有注册条目能否映射，确认未知协议处理方案；未验证前不宣称“全部现有 Provider 兼容”。

资料限制：部分 GitHub 固定版 raw tag 返回缓存未命中/404，Postgres Saver/Pregel/adapter 部分使用当日 main；版本号已与 PyPI/pyproject 交叉核对，但最终应对安装后的源码复核。当前网络沙箱禁止 shell 直接访问 PyPI JSON，本研究通过浏览器检索工具读取官方 PyPI/源码，未请求额外权限或安装依赖。
