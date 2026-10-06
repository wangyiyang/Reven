# Research: Agent 运行时迁移的现有接入与事务边界

- Query: 现有 REST、AgentService/Runtime、37 个工具、飞书入口与部署测试如何迁移；可信确认、操作幂等和旧历史恢复需要改变哪些边界。
- Scope: internal；以当前代码与本地已安装 SDK 为准，不读取真实数据库、`.env`、凭证文件或真实会话正文。
- Date: 2026-10-06
- 阶段: 规划；本研究未修改产品代码、执行 Git 操作、启动任务或运行会产生数据变化的验证。

## Findings

### 结论

1. 可以保留 FastAPI、领域校验和现有工具能力，替换 DSH 调度与会话存储。真正需要调整的是可信调用上下文、模型选择持久化、工具提交边界和飞书消息交付，不只是 `harness.run()`。
2. 37 个工具中有 12 个读取、25 个写入、8 个删除。现有名称确认与提示词约束不能证明人工授权；独立图检查点也不能证明业务写入与操作记录原子提交。
3. 旧历史没有可核实的迁移样本：源码可识别 SDK 事件结构，但当前宿主未保存事件；本 checkout 无 `.dsh-runtime/` 或历史 spike 的 `poc/dsh-agent/`。不能承诺无损续接旧会话。

### 找到的文件

| 文件/目录 | 职责 |
| --- | --- |
| `server/src/reven/api/routes/agent.py`、`api/schemas/agent.py` | 对话 REST 与请求/响应约束 |
| `server/src/reven/agent/service.py`、`runtime.py`、`config.py`、`errors.py` | 共享业务入口、DSH 调用、配置映射、稳定错误 |
| `server/src/reven/integrations/credentials.py`、`service.py`、`api/schemas/integrations.py` | 密钥解析、模型注册/删除保护、公开配置 |
| `web/src/features/integrations/types.ts`、`agent-llm-models-editor.tsx` | 默认与附加模型配置表单 |
| `server/src/reven/agent/mcp_server.py`、`tools_*.py`、`*_tool_support.py` | 内部 MCP、37 工具及参数/错误转换 |
| `server/src/reven/crm/service.py`、`talents/service.py`、`rss/repository.py` | 实际业务事务与领域规则 |
| `server/src/reven/integrations/feishu_bot/{handlers,chat_dispatcher,commands,client,supervisor}.py` | 长连接路由、用户白名单、会话、模型指令、引用回复 |
| `server/src/reven/app.py`、`db.py`、`security/{auth,csrf}.py` | 组合根、连接池、认证与 CSRF |
| `server/src/reven/api/routes/health.py`、`infra/docker/`、两套 Compose | 健康状态、迁移启动、镜像与持久卷 |
| `server/tests/{agent,api,integrations/feishu_bot,migrations}/`、`agent_service_support.py` | 现有测试与 fake harness |
| `.venv/lib/python3.14/site-packages/deepseek_harness/{api,client}.py` | 本机 SDK 的参数/结果/事件实现，只读研究证据 |

### 1. REST 与可信调用上下文

- 唯一 Agent 对话路由是 `POST /api/agent/chat`；成功只返回 `{session_id,response}`；未配置为 `503 AGENT_NOT_CONFIGURED`，其他 `AgentError` 为 502，正文 `{code,message}`。证据：`server/src/reven/api/routes/agent.py:10`、`:13`、`:17`、`:21`、`:24`。
- 请求 `extra="forbid"`，`message` 1–8000 字符，外部 `session_id` 可空、1–128 字符；当前没有 `request_id`、run ID、人工确认、历史查询、操作查询或取消字段。证据：`server/src/reven/api/schemas/agent.py:6`、`:10`。
- 不传会话 ID 时 runtime 生成 UUID hex；既有别名重铸后 REST 返回内部活跃 ID。飞书则一直传外部固定 ID。迁移应明确外部 ID 到持久 thread 的映射，禁止把用户字符串直接当作已授权会话。证据：`server/src/reven/agent/runtime.py:196`、`:204`、`:211`。
- `/api/*` 走 Cookie 认证；AuthMiddleware 查到 `AuthSession` 后直接继续请求，没有把可信身份注入 route。现有 `AgentService.chat()` 也只收 message/session_id。应增加服务端调用上下文：REST 单管理员主体、飞书应用/发送者/会话、来源消息或请求 ID；主体不能由模型工具参数或请求 body 自报。证据：`server/src/reven/security/auth.py:49`、`:58`、`:75`；`server/src/reven/agent/service.py:69`。
- 新确认接口仍应在 `/api/agent/*`，沿用 Origin 与 `X-Reven-CSRF: 1`；飞书确认由已验证消息入口直接调用业务服务。不要把确认端点加入 MCP 的 CSRF 豁免。证据：`server/src/reven/security/csrf.py:25`、`:30`、`:37`；`server/src/reven/agent/mcp_server.py:24`。
- 最小兼容方案：旧 chat JSON 保持可用；通过新增明确 schema 或请求头提供可选幂等键，并增加受保护的确认/拒绝与运行/操作查询口。没有稳定客户端键的旧请求只能保证单次持久运行内防重放，不能承诺跨 HTTP 重试去重。会话 ID 或消息内容哈希都不是请求幂等键。

### 2. 共享服务、配置与模型生效语义

- 每个 app lifespan 创建一个 `AgentService`，REST 依赖与飞书 dispatcher 共用；无配置/启动失败也装配该实例，禁止在每请求重建。证据：`server/src/reven/app.py:255`、`:260`、`:262`；`server/src/reven/api/dependencies.py:18`。
- 模型 override 是进程内 `_overrides[external_session_id]`；`AgentTurn` 在调用前捕获本轮 model_ref/is_override，执行中切换只影响下一轮。应把选择移入数据库，同时保留当前轮身份快照。证据：`server/src/reven/agent/service.py:36`、`:58`、`:69`。
- 生效默认来自启动配置；已保存默认不同则显示 `pending_default_ref`。已启动默认即使从注册表消失仍被列为恢复选项。新运行时若改成下一轮配置热更新，是产品行为变更，必须同步 `/model` 文案、删除保护和测试。证据：`server/src/reven/agent/service.py:42`；`integrations/feishu_bot/commands.py:91`。
- 指定模型每轮现读可用性，即使 harness 在池中也检查 resolver；禁用/移除/失败不自动调用默认，并保留会话选择。启动失败仅日志降级，不阻断应用。证据：`server/src/reven/agent/runtime.py:119`、`:156`、`:163`；`service.py:74`。
- `agent-llm` 默认配置已存 integrations，并非全部未持久化：顶层 provider/model/base_url + 加密 api_key；附加 models[]、enabled 与 `model_key:<provider/model>` 独立密钥，未配置独立 key 则共用默认 key。解析/解密失败允许 env fallback，不能在 checkpoint/配置快照中放入密钥。证据：`server/src/reven/integrations/credentials.py:66`、`:176`、`:202`、`:323`。
- 当前模型删除保护从同步内存 `model_refs_in_use()` 读取；持久会话后需改为数据库查询，并定义哪些会话/运行算“使用中”，否则重启丢保护或旧会话永久阻止删模型。证据：`server/src/reven/api/routes/integrations.py:104`、`:188`；`server/src/reven/integrations/service.py:170`。
- 最少增加：会话与选择、每轮配置版本快照、稳定 run/inbound key、待确认与操作记录。版本快照记录模型 ref、非敏感端点/策略/提示词版本及凭证引用，不复制解密后的 Secret。

#### provider、模型别名与 Base URL 的实证范围

- 前端没有 Agent 模型 provider 选项枚举，均为文本输入。卡片默认 `deepseek-official`、`deepseek-v4-flash`；附加输入 placeholder 为 `deepseek-official`、`deepseek-v4-pro`。文案仅承诺“默认 DeepSeek，兼容 OpenAI 端点”。证据：`web/src/features/integrations/types.ts:129`；`agent-llm-models-editor.tsx:325`。
- 后端 provider/model 只是长度受限字符串；附加模型最多 16 个；ref 按 `provider/model` 拼接、按第一个 `/` 分段，模型部分允许继续含 `/`。代码没有模型别名到具体版本的转换。现有默认名称是传给上游的配置值，不能在迁移时擅自重命名。证据：`server/src/reven/api/schemas/integrations.py:73`、`:92`；`server/src/reven/integrations/providers.py:24`；`integrations/feishu_bot/commands.py:55`。
- 公开 `base_url` 可选且仅接受 HTTPS origin，禁止非根路径、非空query/fragment；因此 `https://host/v1` 并非当前合法配置。新适配器必须定义如何从 origin 推导实际 API base，不能把新 SDK 的完整 endpoint/path 要求原样塞回旧表单。证据：`server/src/reven/api/schemas/integrations.py:25`、`:84`、`:106`。
- 本地 SDK 0.1.5rc1 将 base_url/api_key 写入子进程的 `DEEPSEEK_BASE_URL`/`DEEPSEEK_API_KEY`，provider/model 透传 initialize。其随包说明明确：provider 需由当前 Cordis 组合注册，bundled 默认组合只注册 `deepseek-official`；其他 provider 需自定义组合的 `llm-pi-ai`。证据：`.venv/lib/python3.14/site-packages/deepseek_harness/api.py:70`、`:103`；`deepseek_harness_sdk-0.1.5rc1.dist-info/METADATA:76`。
- 本仓库 patch 仅插 MCP 插件与行为提示，没有插 `llm-pi-ai`；前端 mock 中保存 openai/siliconflow 条目成功，不证明这些 route 在真实 DSH 可运行。不能把 Anthropic/Azure/Bedrock 原生协议视为已验证兼容范围。证据：`server/src/reven/agent/dsh.patch.yml:5`；`web/src/features/integrations/agent-llm-models-editor.test.tsx:76`。
- 规划应先覆盖现有 `deepseek-official` 与明确验证的 OpenAI 兼容端点，建立显式 adapter 支持策略；其他 ref 明确返回不可用。未查真实配置，本报告不认定用户实际使用了任何附加 provider。

### 3. 工具注册、参数与领域兼容

注册事实：`mcp_server.py:54` 依次装配 RSS、CRM、人才；模型侧 DSH 名称是 `mcp__reven__<tool>`。仅这三个领域，没有财务、项目、品牌或 SOP 工具。计数来源是三个注册函数，不依赖过时 PRD。

| 工具组 | 完整名称形状（花括号表示分别注册） | 总数/读/写 |
| --- | --- | --- |
| RSS | `rss_keyword_{create,list,update,delete}` | 4 / 1 / 3 |
| 客户 | `crm_customer_{list,get,create,update,delete}` | 5 / 2 / 3 |
| 联系人 | `crm_contact_{list,create,update,delete}` | 4 / 1 / 3 |
| 跟进 | `crm_follow_up_{list,create,update,delete}` | 4 / 1 / 3 |
| CRM 统计 | `crm_lead_funnel`、`crm_due_follow_ups` | 2 / 2 / 0 |
| 人才主档 | `talent_{list,get,create,update,delete}`、`talent_import_profile` | 6 / 2 / 4 |
| 人才子项 | `talent_{interaction,experience,education}_{list,create,update,delete}` | 12 / 3 / 9 |

- 注册行：`server/src/reven/agent/tools_rss.py:47`、`tools_crm.py:16`、`tools_talents.py:18`。建议从一个显式目录生成 LangChain 与仍需保留的 MCP 注册；工具策略标注 read/write/危险类型，不靠工具名临时猜测。
- 现有 `Annotated`/UUID/date/Decimal/枚举默认值、字段描述及完整领域 Pydantic 校验必须保留。转换后务必实际检查生成 schema，避免把“会调用 Python 函数”误当作等价的模型参数校验。证据：`crm_tool_support.py:18`、`:78`；`tools_talents_talents.py:122`、`:152`。
- CRM/Talents 部分更新中 None 表示不修改，空字符串经 schema 清空，日期/费率有 clear 开关；RSS update 为全量更新。计划从最新跟进/互动派生，上海日期口径；子项变更必须校验父 ID 归属。证据：`crm_tool_support.py:60`、`talents_tool_support.py:84`、`tools_rss.py:90`、`tools_talents_interactions.py:104`；领域 spec。
- CRM/Talents 工具当前主要返回中文字符串，RSS 返回结构化 dict/list。操作凭据应在 ORM 结果转文案之前记录 typed 目标 ID、子项数量、实际变更/删除结果，不能从模型最终回答或中文文本解析“成功”。证据：`tools_crm_customers.py:105`、`:109`；`tools_talents_talents.py:153`、`:157`；`tools_rss.py:79`。
- MCP 当前只识别静态内部 Bearer，所有调用共用 `client_id=dsh-loopback`，没有用户、run、操作授权上下文。若新 Agent 改成进程内调用，旧 MCP 写口不能留成绕过审批/幂等的通路：要么退役挂载，要么同样进入受控 executor，并由可信上下文注入授权。证据：`mcp_server.py:27`、`:46`；`app.py:91`。

### 4. 可信确认与业务事务：必须改变的边界

#### 已有保护及缺口

- 7 个 CRM/Talents 删除工具要求 `confirm_customer_name` 或 `confirm_talent_name` 精确匹配当前名称；模型可以先 get 再自行填写，没有待确认表、用户身份或一次性授权校验。证据：`crm_tool_support.py:106`、`talents_tool_support.py:137`；`tools_crm_customers.py:134`、`tools_crm_contacts.py:102`、`tools_talents_talents.py:231`。
- 第 8 个删除是 RSS 关键词：函数只收 keyword_id，人工确认仅在 system prompt 中要求。停用/启用原行为无需确认。证据：`tools_rss.py:117`；`dsh.patch.yml:41`。
- CRM Service 自己 commit；Talents Service 同样；RSS 工具直接 commit。外层如果仅在工具前/后记操作状态，会出现“业务已提交、结果未记下、恢复后重复写”的窗口。证据：`server/src/reven/crm/service.py:37`、`:109`；`server/src/reven/talents/service.py:87`、`:188`；`tools_rss.py:76`、`:111`、`:123`。
- 人才画像导入在一个业务事务里完整校验、按姓名匹配并追加履历/院校，明确不去重；正常的第二次独立导入仍应保持现有语义。相同运行重放则必须复用第一次的记录，不能再追加。证据：`talents/service.py:153`、`:175`、`:179`；`tools_talents_talents.py:275`。

#### 最小必要机制（设计建议，尚未实现）

1. 入口持久认领 inbound/request key，唯一性按可信来源隔离；保存请求指纹，相同 key 不同内容明确拒绝。相同 key 的重试查原 run/结果，不再启动一轮新的模型推理。
2. 模型只能提出动作。服务端校验后的 intent 包含稳定 operation ID、run/tool-call 对应关系、工具/参数指纹、目标 ID 与确认时展示的目标快照、策略版本及发起身份；在执行前持久保存。不得以模型再次生成的新 call ID 代替原意图。
3. 危险动作先持久等待确认。REST 的受保护确认请求或飞书独立指令绑定 pending ID、发起身份和会话；执行时复查权限/白名单、参数与目标状态，变动则要求重新确认。模型不能读一个名称就自行批准。
4. 25 个写工具统一进入操作 executor。使用同一 `AsyncSession` 进行授权消费/操作认领、领域变更、结构化成功凭据和最终状态写入，一次 commit；重放已成功操作只返回原凭据。
5. 因现有工具内部开 session、Service 内部 commit，至少需要增加由 executor 注入 session/管理提交的 seam。复用原领域方法与校验，现有 REST 的业务提交行为保持；不能用数据库外层“套一下 checkpoint”代替这项修改。
6. 对断连/提交结果不明，查询 operation 行和业务凭据；禁止把超时直接认定为未执行，禁止自动重新做新写入。单个数据库事务若能查到成功凭据即可确认，缺少可核实证据才进入 unknown/reconciliation。
7. 图检查点与业务操作记录分工：图保存对话/执行位置，operation 表作为本地业务是否已提交的依据。恢复重放通过同一 executor 查凭据；避免用户等待确认或 LLM 网络调用期间长持业务数据库事务。
8. 同一持久 thread 的运行应按稳定状态防并发覆盖；不同会话继续并行，保留无全局锁约束。当前部署单 worker 也不能只依赖内存去重来跨重启恢复。证据：`infra/docker/entrypoint.sh:31`；`db.py:21`（业务连接池 size=5）。

RSS create/update 在提交后刷新 embedding，失败返回 pending；这属于第二阶段效果。成功凭据应区分“关键词已保存”与 embedding ready/pending，并使恢复可安全补刷新，不能重做 create。估计 hit_count 失败仍可为 null。证据：`tools_rss.py:76`、`:112`、`:126`、`:138`。应保留新条目从每日抓取起按语义生效的说明（`dsh.patch.yml:40`）。

### 5. 飞书会话、超时、白名单与模型指令

- 入站只注册 `im.message.receive_v1`：只收 user，私聊文字进入对话；群聊仅 bot open_id 被 @ 时进入，剥除 mention，空文本给引导；其他类型提示暂只支持文字。处理器必须立即 submit 返回，不能在 SDK 心跳循环阻塞。证据：`handlers.py:36`、`:93`、`:128`。
- 每消息一个 daemon 线程；白名单先经主循环现读，配置缺失/禁用/读取失败或非白名单时全静默，预检在任何外显回复之前。正常先引用“思考中…”再引用最终结果，占位失败则不执行。证据：`chat_dispatcher.py:110`、`:140`、`:158`、`:194`。
- `session_id=feishu:{chat_id}:{open_id}`，群内用户隔离；不应把整个 chat 当作一个持久 thread。message_id 目前只用于引用回复，没有传给 Agent，不存在持久 inbound 去重或同会话顺序控制。证据：`chat_dispatcher.py:200`、`:220`；`handlers.py:115`。
- `/model`、`/model list/current/use provider/model` 在 LLM 之前解析、不发占位、不进入对话历史；选择与当前轮身份交由共享 AgentService。保留语法和严格失败语义，新增确认指令应走同类可信分支。证据：`chat_dispatcher.py:150`、`:203`；`commands.py:30`。
- 飞书等待默认 120s，预检 10s；`future.result(timeout=...)` 超时后没有 cancel future。runtime 默认 180s，`to_thread` 的同步 SDK 调用也无法真正取消；还存在工具 MCP 的 30s 超时。超时后业务可能继续，原“请稍后重试”会诱导新写。证据：`chat_dispatcher.py:40`、`:166`；`runtime.py:79`、`:213`；`dsh.patch.yml:14`。
- 迁移应统一 run 的截止与结果状态，保留非阻塞接收；超时回复携带可查询/核实的 run 或 operation 标识。消息重复到达复用原 run，发送失败仅重试交付，不重做工具；自然语言“确认”不得由模型自行判断消费授权。
- 最小确认形态可用 `/confirm <pending_id>`、`/reject <pending_id>`，仍仅允许发起者/原会话且再次白名单校验。当前没有卡片按钮回调注册；做按钮会新增消息事件与认证链路，不能当作现有能力。证据：`handlers.py:128`。
- 出站必须继续经 `FeishuReplier`/共享 HTTP 客户端，引用原 message_id，interactive 失败同目标降级纯文本。不要把模型工具加入主动发信能力。现有 reply payload 没有稳定 uuid；应将“业务恰好一次”与“外部消息可能重复/未知交付”分开记录，不能虚报已送达。证据：`.trellis/spec/reven-server/backend/feishu-app-notification-contract.md:35`、`:40`、`:51`。

### 6. DSH 历史是否能恢复

- runtime 内部别名仅内存，遇旧 ID already exists 就重铸 `~r`，这不是恢复原历史；当前宿主也未把旧历史显式传给另一个模型实例。证据：`runtime.py:101`、`:196`；`service.py:36`。
- 本机已安装 SDK 的 `RunResult` 包含 session_id/final_response/finish_reason/events/notifications；事件收集来自 `session.event`，assistant 文本格式能从 `assistant/message` 的 content blocks 识别。但 Reven 只使用 session_id/final_response，没有保存事件，也未校验 finish_reason 后再认定业务成功。证据：`.venv/lib/python3.14/site-packages/deepseek_harness/api.py:40`、`:149`、`:183`、`:211`；`runtime.py:211`。
- 已归档初始 spike 计划证明当时运行过握手/MCP，不含保存的会话 JSONL 样本；其提及的 `poc/dsh-agent/` 当前不存在。本次只检索任务/docs/tests 的文件名及源码结构，没有读取生产卷或真实对话。
- `DSH_HOME` 仅说明 profile/会话日志所在卷；SDK 没有已用的历史读取/恢复接口。事件格式不能直接证明磁盘 JSONL 的包装、版本、排序、外部 ID 别名归并和消息完整性。
- 建议最低路径：新运行时从新持久 thread 开始，保留 dsh-data 只读备份作回滚/后续导入依据。若旧历史必须续接，应先取授权且脱敏的多轮/工具/重铸会话样本，确认日志 schema 与角色/工具消息配对，再单独验收导入；导入历史只能补内容，绝不能重放旧写工具或制造历史审批。

### 7. Docker、ENV、健康与 fixtures 的影响

- 当前锁定 SDK/runtime-bin 0.1.5rc1、FastMCP 4.0.5、MCP 2.2.0、SQLAlchemy 2.0.51、asyncpg 0.31.0、lark-oapi 1.7.3。锁内没有 LangChain/LangGraph/psycopg；新依赖按 Python >=3.12 和 Linux AMD64 镜像验证，具体新版本由另一框架研究决定。证据：`server/pyproject.toml:6`、`:12`；`uv.lock:514`、`:526`、`:597`。
- DSH 依赖、patch、MCP callback env、`DSH_HOME`、运行目录创建可在切换后退役；不要删除旧 named volume 的数据。FastMCP 若仅为 DSH 服务，是否保留须由工具公开边界决定，不能机械添加新 MCP client 绕回同一进程。
- 两套 Compose 都有 dsh-data 与可写 HOME；镜像 UID=10001、只读根、tmpfs、安全选项继续需要。去掉 DSH 后清理 HOME/卷绑定应谨慎，首轮回滚仍保留旧卷。证据：`infra/docker/Dockerfile:31`、`:55`；`infra/compose/docker-compose.yml:14`；`infra/self-host/docker-compose.yml:38`。
- Agent/checkpointer 生命周期进入 `app.py` 装配与清理；业务 `DATABASE_URL` 当前为 SQLAlchemy asyncpg URL。若 checkpointer 使用另一驱动/pool，必须显式转换驱动 URL并管理关闭，不在日志输出 URL、不把“同一个 PostgreSQL”误当成“同一个事务”。证据：`app.py:186`、`:229`；`db.py:21`；`infra/self-host/docker-compose.yml:34`。
- entrypoint 先在启动锁内 Alembic upgrade，再切静态发布，最后单 worker uvicorn。Agent ORM 表要入 migrations/env metadata；checkpoint 表须明确建立/升级的所有者与先后顺序，不能依赖首个用户请求临时建表。证据：`infra/docker/entrypoint.sh:12`、`:15`、`:31`；`server/migrations/env.py:8`、`:28`。
- 当前 `/api/health` 真实 `SELECT 1`，DB fail=503；checks.dsh 配置缺失 disabled、运行时不可用 degraded，整体仍200。checkpointer/Agent 就绪需新检查，LLM可达性不能用对象已创建冒充；checks.dsh 更名需同步监控/测试或明确过渡。Compose 只验 HTTP，所以健康200不能作为迁移功能验收。证据：`api/routes/health.py:25`、`:39`、`:58`；`infra/self-host/docker-compose.yml:66`。
- fixtures 当前显式 `Settings(...,_env_file=None,agent_api_key=None)`，不读取 shell/.env 配置；全局 conftest 主要管理隔离测试数据库，不含旧 spec 所称的全局 AGENT env 清洗。新增会话、run、审批、操作与checkpoint表后，更新两套清表策略并防 app 启动在无配置用例误联网络。证据：`server/tests/api/conftest.py:24`、`:77`；`server/tests/conftest.py:25`。
- 迁移 tests 每例创建独立空库；metadata 一致性测试、新 head/往返迁移要纳入 Agent 表与第三方 checkpoint schema 的分工。fake harness 应替换为能实际产出 tool calls/interrupt/恢复的 fake chat model；只验私有 dict 或转发参数不足。证据：`server/tests/migrations/conftest.py:24`；`server/tests/migrations/test_metadata_contract.py:13`；`server/tests/agent_service_support.py:35`。
- CI full 容器仍执行 `dsh --version`，部署安全测试也断言该项；应替换为新依赖导入、checkpoint初始化与持久恢复烟测。自托管 smoke 还有 `/data/dsh` sentinel，须与卷归档策略一起更新。证据：`.github/workflows/ci.yml:213`；`server/tests/security/test_deployment_automation.py:101`；`scripts/self_host_smoke.py:21`。

### 8. 产品兼容需要明确的决策

| 问题 | 推荐最小方案 | 需要接受的变化 |
| --- | --- | --- |
| 哪些操作必须人工确认 | 首轮至少覆盖8删除；25写均有操作记录 | 全写确认会增加交互，是否扩大危险集合需产品确定 |
| REST 与飞书确认方式 | 新REST确认/查询口；飞书明确指令绑定pending ID | 原API保持成功JSON，但新增交互/状态不能只靠自由文本 |
| 配置默认何时生效 | 明确选“启动快照”或“下一轮热更新”，当前轮始终固定 | 热更新要同步现有重启提示/模型删除语义 |
| 模型支持范围 | 保留公开字段与ref；仅对已验证协议提供adapter | 任意字符串保存成功不等于可执行；需明确错误而不静默改模型 |
| 重试与超时文案 | 持久run可核实状态，禁止提示未知写直接重做 | 可取消只表示阻止尚未提交的动作，不撤销已经commit的业务 |
| 旧历史 | 保留旧卷，先用新会话；导入需样本验证 | 当前不能承诺既有上下文无损继承 |
| 长期会话与记录保存 | 配置版本/历史/操作持久保存，设明确保存范围 | 模型删除“使用中”范围与旧会话清理需要一致规则 |

### 9. 最低必要验证清单

- [ ] REST 原路由、strict schema、成功 JSON、401/CSRF、503/502 与异常脱敏回归；新增审批/操作查询验证身份、作用域和篡改拒绝。
- [ ] 真实 AgentService + 新 runtime + fake chat model：实际选中模型、当前轮落款、恢复默认、禁用不fallback、配置版本、跨app/进程重启读回会话与模型选择。
- [ ] 37 工具目录/schema/字段描述与默认值；UUID、枚举、金额、月日期、clear字段、子项归属、派生计划/上海日期；保留既有CRM/Talents/RSS领域回归。
- [ ] 危险工具无法由模型确认字段/MCP裸调用绕过；待确认重启保留；拒绝、过期、错误主体/会话、参数变更、目标变更、重复确认都零额外写入。
- [ ] 重复REST key/飞书message_id/并发消息只认领一次；相同key不同内容拒绝；同会话顺序确定、不同会话并行。
- [ ] 故障注入：执行前崩溃、commit前回滚、commit后checkpoint前崩溃、commit响应丢失、恢复重放；查实际业务行数/子项数量和成功凭据，不能只查自然语言回复。
- [ ] `talent_import_profile` 相同operation恢复不追加；独立新导入仍按现有业务追加；RSS提交成功但embedding失败为pending，恢复只补刷新。
- [ ] 飞书SDK立即返回、白名单现读且零外显、群成员隔离、模型/确认指令绕开LLM、占位失败零执行、超时仍可查结果、交付失败不重做业务、卡片/文本同目标降级。
- [ ] 空库/升级/回退再升级、metadata/第三方表所有权、checkpointer初始化失败降级与关闭、fixtures清表；隔离测试库，不连接生产。
- [ ] `uv run ruff check server`、`uv run ruff format --check server`、`uv run mypy server/src`、`uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80`，以及独立 migrations 套件（现行 CI gate）。
- [ ] Linux AMD64 full 镜像：只读根/UID/卷权限、两套Compose、旧卷保留、空库启动、健康细项、新运行时持久恢复；真实模型用专用隔离数据验证工具调用、确认和结果，清楚区分fake模型/真实上游/部署证据。

### Related specs

- `.trellis/workflow.md`：保持规划，研究持久化；未经审阅不 start/实施。
- `.trellis/spec/reven-server/backend/agent-dsh-contract.md`：现有共享服务、严格模型、MCP、启动降级契约；迁移后需更新替代，不照搬DSH专属机制。
- `.trellis/spec/reven-server/backend/feishu-app-notification-contract.md`：非阻塞入站、白名单、引用交付、禁止恢复已退役RSS审核按钮链路。
- `.trellis/spec/reven-server/backend/{crm-contract,talents-contract,integration-provider-contract}.md`：领域归属、校验、事务、密钥seam和公开配置兼容。
- `.trellis/spec/reven-server/backend/{database-guidelines,quality-guidelines,open-source-self-host-contract,ci-release-contract}.md`：迁移、Settings单一组合根、自托管与质量入口。
- `.trellis/spec/reven-bot/backend/index.md`、`.trellis/spec/tool-contracts/backend/index.md`：仍为模板；实际Python机器人与工具位于reven-server，不据旧包名推断边界。

### External references / versions

- 本文件不重复框架选型/最新版调研；版本事实取 `uv.lock` 与本机SDK包代码/随包METADATA。SDK路由限制来自已提供的本地包文档，不是对所有上游版本的保证。
- DSH旧设计/执行计划仅是历史证据：`.trellis/tasks/archive/2026-10/09-19-dsh-agent-core/{design,implement}.md`；其中早期全局Lock、旧路由及跨provider设想与现码有差异，研究以上述源码为准。

## Caveats / Not Found

- 未读取真实配置、会话内容或生产卷；无法确定真实已配置provider、旧日志数量/格式/版本、外部ID归并及历史完整度。
- 未找到可用于导入验收的保存JSONL样本；本地SDK事件结构只证明解析潜力，不能证明无损迁移或DSH原会话可resume。
- 未运行测试、容器、网络请求或真实LLM调用；以上为代码事实和规划建议，不是实施成功或部署认证。
- LangGraph/检查点的新依赖版本、driver与初始化API由框架专项研究确认；当前代码中没有这些实现。
