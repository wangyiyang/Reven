# Agent 原生运行、持久确认与恢复契约

## 1. 范围与触发

修改 Agent、业务工具、飞书/REST 调用链、模型选择或检查点部署时适用。2026-10-06 已批准用 LangChain `create_agent`/LangGraph + PostgreSQL 替换 DSH。仍为单管理员、单 Uvicorn worker 的模块化单体，不引入 Agent Server、任务队列或多租户。

## 2. 签名与存储

- `AgentActor(owner_id, channel)`：由认证边界/可信飞书事件构造。REST 为 `admin/rest`；飞书为 `feishu:{open_id}/feishu`，会话外部 ID 保持 `feishu:{chat_id}:{open_id}`。
- `AgentContext(owner_id, session_id: UUID, run_id: UUID)`：宿主工具上下文，不进模型 schema 或 checkpoint；调用 ID 来自 `ToolRuntime.tool_call_id`。
- `AgentRuntime` 拥有原生 graph、模型 HTTP clients、独立 `AgentCheckpoints` 池。服务拥有配置、override、run、去重、审批和任务生命周期。
- `build_agent_graph(model, tools, system_prompt, checkpointer, middleware, confirmation_tools)`：关键词参数，确认只允许 approve/reject。每次实际调用显式 `durability="sync"`。
- `AgentRepository(session)` 不 commit；`AgentStore` 使用短事务，模型等待期间不持有 SQLAlchemy Session。
- Reven ORM：agent_config_revisions、agent_sessions、agent_runs、agent_operations、agent_approvals。新增表沿用 RLS，Alembic 管理；框架表由固定版本 saver.setup 管理，不加入 Reven Base.metadata。
- 检查点 schema 固定 `reven_agent_checkpoints`，psycopg DSN 解析并映射 SSL，不盲目字符串替换 asyncpg URL；pool 的 autocommit、dict_row、prepare_threshold=0 保持。

| REST 接口 | 契约 |
| --- | --- |
| POST /api/agent/chat | 原 message、可选 session_id；成功仅 session_id/response；可选 Idempotency-Key |
| GET/PUT /api/agent/config | immutable 配置版本；prompt + tool_names，不允许动态代码或密钥 |
| GET /api/agent/config/revisions/{id} | 读取固定修订 |
| GET /api/agent/runs/{id} | 原用户查询状态、结果、操作及审批 |
| GET /api/agent/history?session_id=... | 原用户会话运行历史 |
| POST /api/agent/approvals/{id}/resolve | decision=approve/reject，原 session_id 必填 |
| POST /api/agent/runs/{id}/resume | 原用户显式恢复；可选 session_id 进一步限定 |

chat/resume 通过 `X-Agent-Run-ID` 提供可查询编号，保留旧成功 JSON。请求 extra=forbid，配置 prompt 1–32000 字符且非全空白，tool_names 不重复且属于 37 个已注册工具。

## 3. 核心行为

### 配置与身份

每个新 run 现读默认模型与配置版本，固定公开 provider/model/base_url、prompt、tool_names 和实际 model_ref；密钥只临时从 IntegrationCredentials 解密，不写 snapshot/graph/日志。默认配置变更下一新轮生效，override 入库。保留未知 override 并明确不可用，不能静默切默认。

恢复必须使用原 revision、模型与公开配置；当前模型失效、端点漂移、必要工具禁用或运行契约不兼容时明确拒绝。修改影响恢复的 schema/执行语义时评估并更新 runtime_contract，禁止用最新配置重新发起旧用户消息。

模型删除保护仅覆盖未终止 run 与待确认操作；历史或闲置 override 不永久占用。新 run 在实际 graph 接收输入前再次核实模型，配置删除竞争不得继续使用失效启动缓存。

默认模型和附加模型都受 run 引用保护。单 worker 的 model_update_guard 串行化短配置写入（agent-llm 保存、默认切换、密钥删除）与新 run 的现读模型/claim 提交；运行 claim 结束即释放，不持锁跨模型调用或工具等待，避免先查无占用、后删已被新 run 引用的模型。

### 事务与同批写序

37 工具共用显式 catalog 和输入 schema；25 写工具经 ToolExecutor，8 删除工具强制 HITL。schema 校验、补默认、JSON 序列化集中在 canonical_tool_arguments，建审批与实际执行用相同参数哈希，拒绝外部注入 runtime/owner/run。

每 call 独立 AsyncSession。写事务锁定 run、校验可信 owner/session，按 `(run_id,tool_call_id)` 查账本并验证工具/参数；已有 committed 返回历史结果，否则执行领域 mutation、写操作结果与结构化实体 ID、消费批准，一次 commit。不能先内部 commit 再补日志。

`CrmService(..., commit=False)` / `TalentsService(..., commit=False)` 参加 Agent 事务；网页默认 commit=True。画像导入同名更新不能替代账本幂等，重放不得追加第二批履历/院校。

ToolNode 会并行/独立调度每个调用。中间件按最新 AIMessage 的原序执行或重放当前调用前的写前缀，避免恢复时等待已经完成、不再调度的前序 task。失败必须绑定正确 call ID，不能把前序错误当作后序成功。读取可并行，不跨调用共享 Session。

RSS 写入和 pending 结果同 commit，embedding 为 postcommit 工作；失败沿用 pending/每日兜底，重放只能补刷，不能重建关键词。MCP 仍可查看 37 工具，但机器 Bearer 没有可信人类运行上下文，写操作拒绝，不能绕过审批。

### 持久批准

暂停建立审批，绑定 run/call、原 owner/session、工具、规范化 args_hash 和实际目标 target_hash。target_summary 展示名称/ID/级联数量与影响；内部指纹不放进用户话术。批准参数里的逐字名称仅用于目标校验。

批准/拒绝在服务端幂等处理，不能覆盖已决策记录。多工具待办按 position 与当前 interrupt 对齐，收齐对应决策再 Command(resume=...)。执行端同事务锁定目标与相关子项，检查快照未漂移再消费批准；错用户、错会话、错参数、目标变化都零额外 mutation。

飞书 `确认 UUID` / `取消 UUID` / `状态 UUID` / `恢复 UUID` 确定性解析，不经 LLM。所有分支先现读白名单，原 chat/open_id 限定访问；SDK submit 立即返回，引用回复保持原 message_id。

### 生命周期与恢复

同会话未终止运行阻止新轮；跨会话并行。message_id/Idempotency-Key 去重，同键同输入附着原run，包括首轮未提供session_id的重发；同键不同输入/显式不同会话409，不做语义去重。

应用持有 background tasks，停止等待不取消执行；接口等待预算要小于外层桥预算，返回编号/真实状态，不能误报未执行并让用户盲目重试。执行期限、关闭和重启中断单独处理。

Feishu chat/确认/恢复都显式传自身等待预算，不能在确认/恢复时沿用可能大于桥预算的 REST 默认。Service 关闭先禁止新 admission，再收敛 claim/decision→launch 短窗口和已持有执行任务；跨关闭窗口已 claim 的 run 标 interrupted/AGENT_SERVICE_CLOSING 并保留原编号，不能把晚到任务从 tasks 容器清掉后任其继续写入。

启动把遗留 queued/running 转为 interrupted。普通中断用 ainvoke(None)，HITL 用匹配 Command；核对 checkpoint metadata、pending task、原 run/revision 与账本。缺少安全恢复依据标 needs_reconciliation，不重跑整轮。graph 已接收输入后的失败不能简单标 failed 后让新运行抢跑未完成图。

health 的 checks 为 db/agent/checkpointer/background_runner；db 失败维持 503，Agent 或 checkpoint 降级保持 200 并显式 degraded。无模型但检查点正常时 agent=disabled、checkpointer=ok，HTTP 200 不能替代工具与恢复验收。

## 4. 验证与错误矩阵

| 条件 | 结果 |
| --- | --- |
| 未配置模型 | AGENT_NOT_CONFIGURED / 503，站点可降级 |
| checkpoint 连接/版本不可用 | AGENT_RUNTIME_UNAVAILABLE，明确降级，不建表掩盖问题 |
| 指定模型失效 | AGENT_MODEL_UNAVAILABLE，无默认回落、无上游异常原文 |
| 错 owner/session | 403/404，不泄露他人 run/审批 |
| 相同去重键不同输入 | AGENT_REQUEST_CONFLICT / 409 |
| 会话仍busy | AGENT_SESSION_BUSY / 409，给原运行编号 |
| 批准内容/目标漂移 | 固定冲突错误，零额外删除 |
| checkpoint 或待恢复输入不对齐 | needs_reconciliation，不从头调用 |
| 等待超时 | 返回原run编号/实际状态，执行由应用持有 |

## 5. 正常、默认与错误案例

- 正常：跟进与账本同提交 → checkpoint前崩溃 → 原用户恢复 → 同call返回原结果，只有一条跟进。
- 默认：没有模型凭据时经营网页/RSS仍按既有契约工作，Agent明确未配置。
- 错误：模型填写confirm_name即删除；新session重试整个旧run；把HTTP 200当作工具已写入。

## 6. 必需测试

- HTTP 协议替身验证 DeepSeek reasoning_content 多轮回传、tool_call ID、消息顺序、未知协议失败。ChatDeepSeek 原生保存响应不等于正确回传请求。
- 真实 PostgreSQL 新pool/graph、独立进程/应用重建、稳定历史/override/审批；sync durability 和普通/人工恢复分开。
- 37 schema、25写事务、8删除审批、目标漂移、归属、重复与取消；CRM派生计划、人才画像追加、RSS pending保持。
- 注入 COMMIT 后/checkpoint 前中断；仅恢复后序tool task无死锁；同session串行/独立session并行。
- Auth/CSRF、Feishu零网络白名单/确定性指令/message_id去重、等待与执行期限。
- 0028 空库/存量升级、metadata、只读镜像/原生工具/checkpoint/容器重建；未知反序列化类型拒绝、密钥不落state。

## 7. 部署与错误写法

显式执行 `alembic upgrade head` 后 `python -m reven.agent.checkpoint`；命令只读环境 DATABASE_URL，失败脱敏。entrypoint 在静态版本切换前初始化，用户请求中不调用setup。JsonPlusSerializer显式严格模块名单、pickle_fallback=False。

```python
# 错误：领域内部已提交，账本失败时业务无法回滚。
await CrmService(session).create_follow_up(customer_id, payload)
session.add(operation)

# 正确：同一外部事务拥有业务与结果。
async with session.begin():
    await CrmService(session, commit=False).create_follow_up(customer_id, payload)
    session.add(operation)
```

新Compose不挂载DSH_HOME/旧卷，不依赖可写HOME。旧DSH卷、镜像、Compose保留归档；新会话不自动导入旧历史。回滚保留新增表与业务记录，不运行破坏性downgrade/删卷。证据与运行手册见 docs/agent-architecture.md 及任务 research/implementation-evidence.md。
