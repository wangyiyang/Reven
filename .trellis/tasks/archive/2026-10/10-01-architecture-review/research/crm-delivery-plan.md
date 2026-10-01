# Research: CRM 变更与飞书交付的最小实施方案

- Query: 用户已选择三项顺序落地；为前两项给出可执行 interface、迁移和最小回归方案，继续保持 planning，不修改产品代码。
- Scope: internal；复用 `hotspot-deepening.md` 的证据，仅补齐 CRM / 飞书实施所需事实。
- Date: 2026-10-01

## Findings

### 实施结论

1. **CRM**：领域拥有六个输入模型；`CrmService` 接收业务 ID 与这些已验证输入，内部查找、检查归属并完成变更。只修改写入口；已有列表、筛选、提醒、详情读路径继续使用 `CrmRepository`。
2. **飞书**：扩展已有 httpx 出站 module 支持引用 `message_id`，由 dispatcher 工作线程通过既有 `_bridge` 回主循环调用。删除 handlers 的 SDK 出站 client 与重复策略，不保留第二套生产 transport。
3. 可保持 REST/MCP/飞书外部契约；需要变更的是仓库内部 Python interface 与测试接线。无数据库迁移、无依赖变更、无跨领域通用 CRUD 或新取消机制。

### 补充的关键事实

- 当前 CRM 写调用方只有 `api/routes/crm.py`、`agent/tools_crm.py`；搜索未发现其他生产代码调用 `CrmService`。`.repository` 暴露的使用都在 MCP 的写前预检，不存在必须保留的外部 `.session` 读取。
- CRM 生产 sessionmaker 使用 `expire_on_commit=False`，见 `server/src/reven/db.py:24`；工具测试同样如此，`test_tools_crm.py:32`。既有业务结果返回 ORM 标量已是当前惯例，不必新建每个实体的 DTO。
- 现有 `FeishuBotApiClient` 只有 create message 发送，没有 reply 方法，见 `client.py:77-138`。
- **本地 SDK 精确证据**：`.venv/lib/python3.13/site-packages/lark_oapi/api/im/v1/model/reply_message_request.py:23-28` 为 POST `/open-apis/im/v1/messages/:message_id/reply`，支持 TENANT token；`:31-40` 设置路径和 body。
- reply body 的 `msg_type` 与 JSON 字符串 `content` 已由本地 SDK 描述（`reply_message_request_body.py:8-19`），与 create message 共用的两种消息表示相同。原 reply 未设置 `reply_in_thread` / `uuid`，新路径也不擅自增加。
- `uv.lock:989-990` 的 lark-oapi 锁定版本是 1.7.3；这是对本地协议源代码的读取，不是上游最新版声明。
- `ProviderClients.feishu_bot()` 每次读取凭证，返回的客户端复用同一个 AsyncClient，见 `provider_clients.py:59-66,107-115`；该 AsyncClient 必须始终在主循环使用。

### CRM：文件职责与 interface

#### 精确文件计划

| 新/改文件 | 最小职责 |
| --- | --- |
| 新 `server/src/reven/crm/inputs.py` | 从网页 schema 移入 CustomerCreate/Update、ContactCreate/Update、FollowUpCreate/Update 及字段约束、归一化；同一领域验证函数用于创建校验和更新合并后的行动日期配对 |
| 新 `server/src/reven/crm/errors.py` | 既有 InvalidActionPairError、ContactNotFoundError，以及新增 CustomerNotFoundError、FollowUpNotFoundError；独立固定类型即可，不加通用 error framework |
| 改 `server/src/reven/crm/service.py` | 已验证 input + ID 的完整变更；内部 `_session` / `_repository`、取实体、归属、事务提交；只保留业务操作和小型私有 helpers |
| 改 `server/src/reven/api/schemas/crm.py` | 保留三个 Response；显式重导出六个领域输入模型的原名称，保持路由导入与 OpenAPI 模型名；无重复校验 |
| 改 `server/src/reven/api/routes/crm.py` | 写路由直接传 ID + input 并转换固定领域错误；读路由及 `_customer` 读预检保持现状 |
| 改 `server/src/reven/agent/tools_crm.py` | MCP 写方法直接调用领域操作；仍拥有 MCP 参数形状、clear_* 翻译、中文 ToolError 与回复 |
| 新/改 CRM 工具分文件 | 改造后仍超过 500 行时按下文领域 adapter 拆分；不加只转发的总 facade |
| 新 `server/tests/crm/test_service.py` | 在同一 CRM interface 使用 PostgreSQL 验证完整变更、失败无副作用及部分更新规则 |
| 改现有 API / MCP 测试 | 维持传输/错误/文案契约，调整输入导入和领域 adapter 的测试接线 |

#### 具体业务 interface

以下选择保持现有实体返回；操作需要客户名时将“完成操作的客户 + 结果”作为同一次操作返回。无需调用方再次查客户作为写前置条件。

```python
class CrmService:
    def __init__(self, session: AsyncSession) -> None: ...

    async def create_customer(self, payload: CustomerCreate) -> Customer: ...
    async def update_customer(self, customer_id: UUID, payload: CustomerUpdate) -> Customer: ...
    async def delete_customer(self, customer_id: UUID) -> Customer: ...

    async def create_contact(
        self, customer_id: UUID, payload: ContactCreate
    ) -> tuple[Customer, Contact]: ...
    async def update_contact(
        self, customer_id: UUID, contact_id: UUID, payload: ContactUpdate
    ) -> Contact: ...
    async def delete_contact(self, customer_id: UUID, contact_id: UUID) -> Contact: ...

    async def create_follow_up(
        self, customer_id: UUID, payload: FollowUpCreate
    ) -> tuple[Customer, FollowUp]: ...
    async def update_follow_up(
        self, customer_id: UUID, follow_up_id: UUID, payload: FollowUpUpdate
    ) -> FollowUp: ...
    async def delete_follow_up(self, customer_id: UUID, follow_up_id: UUID) -> FollowUp: ...
```

- create_contact / create_follow_up 返回的 customer 仅供既有中文回复取得名称；REST adapter 只取第二个结果，JSON 仍为原 ContactResponse / FollowUpResponse。
- delete 返回已取到的实体供 MCP 保留删除前名称/日期/方式。读取其已加载标量，不访问 lazy relationship；REST 忽略结果，继续 204。若生产构造引入非 `expire_on_commit=False` 的 session，不在该任务支持这种新变体。
- 领域错误用 ID 作为异常参数即可；当前 adapter 已拥有相关 ID，无需带敏感 CRM 内容、HTTP 状态或 ToolError 进领域。
- 错误类从 `crm/errors.py` 直接导入；`service.py` 不再公开 repository / session。保留类型名和外部映射，内部导入路径可一并迁移。
- `api/schemas/crm.py` 使用显式 `CustomerCreate as CustomerCreate` 等重导出，避免 ruff 将兼容导入视为未使用；Response 的 `from_attributes=True` 不动。

#### 现有调用方与精确迁移

| 当前调用方 | 迁移后 |
| --- | --- |
| REST create_customer `routes/crm.py:58-59` | 直接传 CustomerCreate，不在 adapter model_dump |
| REST update/delete customer `:73-87` | 删除写前 `_customer`；传 customer_id；映射 CustomerNotFoundError 与 InvalidActionPairError |
| REST create_contact `:110-112` | 删除客户写前预检；取领域结果中的 contact |
| REST update/delete contact `:122-137` | 删除 repository 查找；传 customer_id/contact_id；映射 ContactNotFoundError |
| REST create_follow_up `:160-166` | 删除客户写前预检；取 follow_up；映射 CustomerNotFoundError / ContactNotFoundError |
| REST update/delete follow_up `:176-196` | 删除 repository 查找；传 customer_id/follow_up_id；映射 FollowUpNotFoundError / ContactNotFoundError / InvalidActionPairError |
| MCP create_customer `tools_crm.py:158-171` | 领域输入校验保留在入站转换，业务调用直接传模型 |
| MCP update/delete customer `:195-218` | 删除 `.repository` 访问；领域抛缺失错误；删除结果提供名称 |
| MCP create/update/delete contact `:260-314` | 传业务 ID，create 返回 customer/contact；缺失错误映射为原中文提示 |
| MCP create/update/delete follow_up `:362-429` | 传业务 ID；create 返回 customer/follow_up；删除结果提供原日期/方式 |
| CRM 列表/详情/联系人与历史列表/漏斗/到期客户 `tools_crm.py:113-146,224-234,320-329,433-474` | 保持读用 CrmRepository；仅共用领域输入导入或拆分接线所必需的变化 |
| `crm/follow_up_reminder.py:24-41` 与 REST 读路由 | 不重写 |

#### Partial-update 与错误策略

- 输入实例是已经验证的模型；service 不再次转换 dict 为模型，不复制 Pydantic 规则。
- 创建使用 `model_dump()`；更新只用 `model_dump(exclude_unset=True)`。字段未出现表示不改，显式 null / 归一化空字符串表示清空，不能改成 `exclude_none=True`。
- 行动/日期配对对更新必须使用**合并后状态**：按 `model_fields_set` 决定取提交字段还是数据库旧值，再使用同一个领域配对校验。仅修改日期时允许保留旧行动；仅清空行动且旧日期仍在时必须拒绝。
- 同一配对校验可在 `crm/inputs.py` 提供 `require_action_for_date(action, due_on)`，抛 `InvalidActionPairError(ValueError)` 并保持创建时的固定中文消息。创建 model_validator 会被 Pydantic 映射为 ValidationError；更新 adapter 继续用原 CRM_NEXT_ACTION_REQUIRED / ToolError 消息。
- `CustomerUpdate` / `ContactUpdate` / `FollowUpUpdate` 的必填字段显式 null 拒绝继续生效。
- MCP 的 `clear_next_follow_up_on`、`clear_contact` 和互斥校验继续是传输转换；转换应先收集**全部**更新字段，再判断无更新。当前 `update_follow_up` 在收集 contact_id 之前就可能由 `_collect_updates` 拒绝无字段（`:391-402`），因此只修改/清空联系人这一外部承诺应补回归；不得把“contact-only 更新”又变成空操作错误。
- 不把 MCP clear 开关加入领域模型或 REST JSON。
- 继续区分缺失客户、缺失/跨客户联系人、缺失/跨客户跟进；不存在与归属不匹配保持同一固定错误，避免泄漏别人的记录。

#### 事务与读用途

- service 从同一个 session 内查实体、验证并提交，写前 caller 不再取得 ORM。
- 创建跟进的联系人归属检查先于添加跟进；`set_as_current` 更新客户与添加历史仍一次提交，不 pop 修改原 input。
- 切主联系人仍先在同 session 清原 primary，再创建/更新；数据库既有 partial unique constraint 保留。
- 更新/删除历史不改客户当前计划；删联系人依赖现有 FK SET NULL，快照保留。
- 不增加 commits、嵌套 begin、行锁、全局锁；校验失败不提交。数据库异常继续显式传播，既有 session context 负责 rollback，不吞异常报告成功。
- read adapter 继续创建 CrmRepository，保留当前读查询性能与返回形状；service 私有 repository 不意味着所有读取必须经 service，也不增加一个只暴露 repository 的 getter。

#### MCP adapter 规模与拆分

原 `tools_crm.py` 为 586 行。领域输入移走与写前预检删除未必降到 500，因为输入模型原本在另一个文件，且新缺失错误映射会占行；不要假设自然达标。

最小有意义的拆分按完整领域 adapter 责任组织：

- `agent/tools_crm.py`：注册工具名称与实例装配，约 50–80 行；删除原聚合 CrmTools 及其纯转发 facade。
- `agent/tools_crm_customers.py`：CrmCustomerTools，客户 CRUD、聚合详情、漏斗、到期查询，约 220–300 行。
- `agent/tools_crm_contacts.py`：CrmContactTools，联系人 CRUD 与展示，约 130–180 行。
- `agent/tools_crm_follow_ups.py`：CrmFollowUpTools，跟进 CRUD、联系人解除/关联转换、展示，约 170–230 行。
- `agent/crm_tool_support.py`：真实共用 MCP 输入转换、参数类型、字段错误标签与固定错误映射，约 100–170 行；不承担 CRM 不变量，不实现通用 CRUD。客户详情需要的联系人/历史展示函数留在各自领域 adapter，可明确导入，不创建只有转发的 formatter module。

每个 adapter 都拥有完整输入、调用和中文输出，不按“类→实现类”拆同一概念。注册点明确装配三个实例；MCP 15 个工具名字、参数描述/默认值不改。已有测试由三个领域实例 fixture 使用，不保留为了旧 Python 测试而新增的 composite class。

若删改后的单文件已 <=500，允许不做上述拆分，避免不必要文件导航；实施检查以 AST 方法跨度 <=50、文件 <=500 为硬结果。过长方法优先缩短重复 Annotated 元数据排版或抽出具有业务含义的输入转换，不能为测试把行为拆成很多浅 module。

#### CRM 测试与最小回归

保留 `tests/api/test_crm.py` 和 `tests/agent/test_tools_crm.py` 的高价值外部契约测试，尤其 `test_crm.py:130-199`、`test_tools_crm.py:184-255`。拆分仅改 fixture/调用实例，不弱化断言。

在 `tests/crm/test_service.py` 的同一 interface 补最少四组数据库行为：

1. ID 不存在/跨客户联系人和跟进操作拒绝；无需 adapter 预检，数据库原记录未变。
2. 部分更新合并旧值：日期独立更新合法；清空行动而保留旧日期拒绝；同时清空日期合法；拒绝后旧数据保留。
3. 创建跟进与当前计划一次提交；错误联系人时不存在半条历史或半个当前计划；后续改历史不改当前。
4. 主联系人切换与删除联系人保留快照，沿完整领域操作检查 observable outcome。

MCP 最小增补：仅关联/解除 contact 更新（不夹带 summary）、clear_date 冲突、跨客户输入；协议已有 create/list/funnel 用例增一个 follow-up update 或拒绝用例，确认 register 接线仍正确。不添加三套完整 CRUD 测试；共享领域断言转移时 replace-don't-layer，adapter 仍验证 HTTP/MCP 错误形状与中文结果。

### 飞书：文件职责与 interface

#### 精确文件计划

| 新/改文件 | 最小职责 |
| --- | --- |
| 改 `integrations/feishu_bot/client.py` | reply message_id transport；唯一 card→text 交付实现；内部生成标题/正文或 Notification 的纯文本表示 |
| 保留 `integrations/feishu_bot/cards.py` | 现有卡片 2.0 构建，无新通用渲染抽象 |
| 改 `provider_clients.py` | 新 FeishuReplier 异步 adapter 复用现读凭证与共享 HTTP；FeishuNotifier 传结构化 Notification 给出站 module，不再拼 markdown/fallback |
| 改 `chat_dispatcher.py` | 注入异步 replier；daemon 里每次引用回复通过既有 bridge 回主循环；保留所有会话/命令策略 |
| 改 `handlers.py` | 只保留 route、事件处理器与 submit；删除 SDK reply client、reply_once / reply 闭包；submit 不再携带 reply |
| 改 `supervisor.py` | LarkWsConnection 调用 event handler 的构造参数去掉出站 app_id/app_secret；WS client 仍使用原凭证，bot_open_id/连接生命周期不变 |
| 改 `app.py` | 飞书装配拿已有 ProviderClients，创建 FeishuReplier 注入 dispatcher；不新建 AsyncClient |
| 改 `notify/notifier.py` / `notify/scheduler.py` | 删除 fallback_text 参数，仍拥有 chat→白名单渠道选择及每日认领/重试 |
| 改现有飞书测试 | 下述 reply 请求矩阵与 async replier 接线 |

#### 具体出站 interface

```python
class FeishuBotApiClient:
    async def send_markdown(self, open_id: str, markdown: str, *, title: str | None = None) -> None: ...
    async def send_markdown_to_chat(self, chat_id: str, markdown: str, *, title: str | None = None) -> None: ...
    async def send_markdown_to_recipients(
        self, recipients: tuple[str, ...], markdown: str, *, title: str | None = None
    ) -> None: ...
    async def reply_markdown(self, message_id: str, markdown: str, *, title: str | None = None) -> None: ...
    async def send_notification_to_recipients(
        self, recipients: tuple[str, ...], notification: Notification
    ) -> None: ...

AsyncMessageReplier = Callable[[str, str], Awaitable[None]]

class FeishuReplier:
    def __init__(self, clients: ProviderClients) -> None: ...
    async def __call__(self, message_id: str, text: str) -> None: ...

class FeishuChatDispatcher:
    def __init__(self, credentials, agent_service, *, reply: AsyncMessageReplier, ...): ...
    def submit(self, *, kind, message_id, chat_id, open_id, text) -> None: ...
```

- 对外调用方都没有 fallback_text；已有 send_text / send_text_to_recipients 保留给显式连接测试与其他纯文本用途。
- 一份私有 `_deliver` 接收已准备的卡片/文本表示与低层发送 callable，只有它实现“先 interactive、FeishuBotApiError 后再 text、text 失败传播”。这里是同一 httpx transport 的内部 seam，不是第二套策略或 public registry。
- create message 低层发送仍用 receive_id / receive_id_type；reply 低层发送只 POST `{MESSAGES_URL}/{quote(message_id, safe='')}/reply`，body 为 msg_type/content，没有 receive_id 或 receive_id_type。quote path 值避免任意外部 message_id 改 URL 结构。
- 原有 `_request` 提供 tenant token、response 上限与脱敏错误；reply 不再用 SDK 鉴权，错误码仍稳定脱敏。
- `send_notification_to_recipients` 是必要的结构化输入：Notification 已有 title/stage/summary/links，出站 module 拥有两种表示，保留当前卡片 markdown 和文本 `label：url`。不要让 ProviderClients adapter 拼两份正文，也不新造通用 markdown parser。
- 普通 Agent markdown 转 text 保留原正文（可以保留 Markdown 字符）并在 title 非空时前置标题；没有实现“把任意 Markdown 无损解析为纯文本”的需求。

#### 内容准备与两种降级

- Notification 的卡片标题/阶段/摘要/链接格式保持 `provider_clients.py:132-141` 的现有结果，但构建位置移到出站 module；`test_feishu_notification_contract.py:85-105` 的 label/URL 断言保持。
- CRM 提醒 title+markdown 自动获得标题+正文文本，修复 `scheduler.py:118-122` 当前未补标题的路径，用户得到更完整结果。
- **同目标 card→text**：出站 client 一处完成；网络错误、非零 code、HTTP 错误、非法响应都映射 FeishuBotApiError 后尝试文本；两次失败才向 caller 报错。
- **不同渠道 chat→白名单**：只在 FeishuProactiveNotifier，且必须等定向 chat 的 card/text 都失败后才执行。保留返回 channel=`chat`/`whitelist` 和目标缺失分类。
- 引用回复永远只回复同一 message_id，不允许失败后广播白名单；一位接收人失败不代表全部成功。
- 不增加重试表、消息 uuid、RSS 去重字段或 SDK outbound adapter。

#### SDK、daemon 与主循环的接线

```text
SDK 同步回调（连接循环）
  → route_message
  → submit(kind, message_id, chat_id, open_id, text)
  → 立即返回

dispatcher daemon
  → bridge 主循环：白名单预检
  → bridge 主循环：FeishuReplier → ProviderClients → HTTP 思考中回复
  → bridge 主循环：Agent 对话
  → bridge 主循环：FeishuReplier → ProviderClients → HTTP 最终/兜底回复
```

- `build_message_handler(chat_dispatch, bot_open_id)` 不再收 reply；`build_event_handler(*,bot_open_id,chat_dispatch)` 不再构造 SDK im client。SDK 只负责 WS 入站。
- daemon 不能直接跑/调用共享 AsyncClient，也不能建立每轮新 event loop；所有 outbound 协程通过 `run_coroutine_threadsafe` 调度到 bind_loop 的主循环。
- 使用既有 `_bridge` 的调度失败 close、结构化日志、异常收敛纪律，不复制 bridge。
- reply 的 `Awaitable[None]` 成功结果不能直接用 `_bridge` 的 None 判断，因为 None 也是失败哨兵。私有 `_send_reply` await 注入 replier 后明确返回 True；daemon 以 True 判断占位成功，只有成功才进入 Agent。
- reply bridge 可以使用现有对话 timeout 上限，实际每个 HTTP 请求仍由 ProviderClients 的 10 秒 timeout 控制；不新增可配置超时或取消模型。不要使用 10 秒白名单 precheck 超时截断可能需要 token/card/text 三次请求的交付流程。
- guide/unsupported/命令仍只有直接回复；自然语言仍先思考中，后最终；占位失败或发送桥失败放弃本轮。
- 不改 Agent `_chat` 的 120 秒超时和不取消语义，不改变会话键或本轮模型选择逻辑；第三项任务后续另行处理。

#### Enabled、白名单与凭证现读的位置

- 白名单仍在 dispatcher 的 `_is_allowed(open_id)`，每条入站消息主循环现读，且先于所有 guide/unsupported/command/thinking 外显回复；配置缺失/禁用/预检失败全部静默。
- FeishuReplier 每一次外显回复都进入 `clients.feishu_bot()`；该 context 当前读取 `credentials.feishu_bot()` 并据 enabled / 凭证可用性返回句柄或 None。None 抛固定 FeishuBotApiError，由 dispatcher 收敛；不使用启动期捕获的 secret，也不复制解密代码。
- replier 不做白名单广播，不再额外拒绝“空通知接收人”作为引用回复规则。发送目标是 message_id；发送者授权已由入站预检承担。只在下一条消息重新检查发送者，不引入当轮白名单变更后的取消规则。
- enabled/凭证在一轮进行中被关闭/替换，会在下一次回复现读时反映，无法发送则日志收敛；这是 ProviderClients 已有的现读规则，不能承诺旧连接捕获凭证继续交付。
- supervisor bot_open_id 获取、reload 和 WS 代际循环不在本改造顺带重写；不会为了 outbound 统一去改变配置热更新与群 @ 判定。
- app 装配的 `_build_feishu_bot_supervisor` 从 clients 取 credentials，并将 FeishuReplier(clients) 注入 dispatcher；不存在“只有凭证但没有共享 clients”的新半配置形态。

#### 旧 submit(reply=...) 测试迁移清单

| 测试位置 | 最小迁移 |
| --- | --- |
| `test_handlers.py:50-91` 及消息矩阵 | 移除 ReplyRecorder / submit reply 字段；DispatchRecorder 仍检查 kind/ids/text，事件 callback 不进行任何发送 |
| `test_handlers.py:285-289` | 新构造签名，保留只注册消息事件的断言 |
| `test_handlers.py:295-365` | 删除 SDK client 替身和重复 card/text 策略测试；等价行为迁到 HTTP client reply 请求测试，不保留绕过新 seam 的测试 |
| `test_chat_dispatcher.py:98-116` | ReplyRecorder 改异步 callable，在构造 dispatcher 时注入；submit 不收 reply；fail_on 抛错行为保留 |
| `test_model_commands.py:103-117` | 同上；指令、override、history 污染、严格错误断言不改 |
| `test_supervisor.py:66-88` | FakeChatDispatcher 的 submits 不携带 reply；bind_loop/起停/reload/bot_open_id 断言保留 |
| `test_app_lifespan.py:19-58` | 构造仍证明真实 dispatcher 被装配；补确认 replier 复用同一 ProviderClients 或用可观测 reply 请求证明接线 |
| `test_notifier.py` / `test_scheduler.py:37` | 删除 fallback_text 参数，FakeNotifier 继续记录原 title/markdown；渠道与调度测试语义保持 |

#### 飞书最小回归矩阵

在 `tests/integrations/feishu_bot/test_client.py` 以 HTTP 测试 adapter 验证一份交付策略，对 open_id/chat_id/reply 目标类型参数化请求形状：

1. reply 使用原 message_id 路径、Bearer token、interactive 卡片，没有 receive_id；成功只有一条。
2. card 非零 code 后同目标 text；文本自动保留标题和正文。reply 的两次请求都保留相同 message_id。
3. card transport 直接抛 httpx.ConnectError / ReadTimeout 后 text 成功；两次都失败则脱敏 FeishuBotApiError。
4. 目标是 chat 时，仅 card 失败且 text 成功不触发白名单；两者失败才从 chat→白名单。
5. RSS structured Notification 的文本保留 title/stage/summary/label：URL，保留现有 `test_feishu_notification_contract.py:85-105`，不改弱断言。
6. 一位接收人 card/text 都失败，继续尝试其他接收人并整体报部分失败；保持 `test_feishu_notification_contract.py:109-127`。

dispatcher 层沿注入 replier 只验证调度/业务策略，不再次测卡片细节：

- async replier 内 `get_running_loop()` 等于 bind_loop 的主循环；submit 快速返回，发送等待在 daemon。
- 任意白名单外 kind 零发送零 Agent；下一条消息能看到白名单修改。
- dead loop 失败无 coroutine 泄漏（`-W error::RuntimeWarning`）；思考中失败零 Agent，最终发送失败只日志。
- Agent 超时兜底、模型命令无 thinking / 无 Agent、配置禁用或凭证变化在下一次 reply context 现读。使用轻量 fake clients 或现有数据库 fixture，不触真实网络。

另补一个主动提醒到纯文本的跨 module 场景：CRM 场景/调度器→真 FeishuProactiveNotifier→MockTransport，card 失败后文本包含“CRM 待跟进提醒”及客户名/行动/到期信息。只补这条组合行为，不重跑所有 scheduler 时刻测试的网络版本。

### 执行规模、顺序与检查

- CRM 先迁移输入与完整变更，同时迁移两个写 adapter；预计 service 150–220 行、inputs 140–180 行、errors 20–35 行、REST routes <=200 行。工具分文件按上文规则，新增生产代码主要是少量领域查找 helper，其余多为迁移/删调用接线。
- 飞书预计 client 240–320 行、ProviderClients 增约 15–25 行异步 replier，同时删除原 Notification 双正文构造；handlers 删除约 35 行 SDK 出站；dispatcher 增约 15–30 行异步回复桥接；其他只改签名/装配。无新生产出站策略 module 或 transport hierarchy。
- 每个函数实际跨度 <=50、每个本次触及代码文件 <=500；用 AST 与文件行数检查，发现未达标按领域职责拆分而非加转发文件。
- 先 CRM 验证并稳定，再飞书；测试文件不跨阶段同时改相同 helper。父会话负责 PRD/design/implement/spec 与审批，研究代理只提供本文件。

最小针对性验证命令（均由后续 implement/check 执行，本研究未运行）：

```bash
uv run pytest server/tests/crm server/tests/api/test_crm.py server/tests/agent/test_tools_crm.py
uv run pytest server/tests/integrations/feishu_bot server/tests/notify server/tests/integration/test_feishu_notification_contract.py server/tests/test_provider_clients.py server/tests/test_background.py -W error::RuntimeWarning
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
```

上述 DB 用例需要 TEST_DATABASE_URL。最终 check 应按项目 CI/质量契约运行完整 server 相关范围，不把 skip 当通过。真实飞书发送不是必要自动测试步骤，不给用户发送测试消息。

### Related specs / references

- `.trellis/spec/reven-server/backend/crm-contract.md:36-79`：JSON、日期、归属、partial update 与事务行为。
- `.trellis/spec/reven-server/backend/feishu-app-notification-contract.md:22-31,54-67`：内容降级、立即返回、桥接与测试纪律。
- `.trellis/spec/reven-server/backend/agent-dsh-contract.md:13,19,22,30`：运行时已拍板行为不受本两项影响。
- `research/hotspot-deepening.md`：第一轮调用链、测试证据与 deletion test。
- 本地 `codebase-design/SKILL.md` / `DEEPENING.md`：module / interface / depth / seam / adapter / leverage / locality；interface 是测试面，replace-don't-layer。
- 外部协议只读本地安装 SDK 源码，无网络检索，无“当前上游新功能”推测。

## Caveats / Not Found

- 未编辑代码、spec、规划文件、锁文件，未执行 git 操作或测试。
- CRM 两种传输的外部行为可保持；内部 CrmService、工具 adapter 类与飞书 submit 的 Python interface 会迁移，没有为旧内部测试保留 facade 的必要。
- 只改/清空跟进联系人的 MCP 更新目前有代码级拒绝路径；本轮将其列为需要复现和回归的具体行为缺口，未声称测试已经失败。
- 普通 Markdown 的文本降级保留原正文，不承诺去除全部格式符；结构化 Notification 保持原 label：URL 等明确文本格式。
- reply 凭证改为 ProviderClients 每次现读，连接中途更换应用凭证可能使旧 message_id 不可回复，按固定失败收敛；不回落到旧 secret 或不同接收人。
- 飞书入站重复事件去重、pending 认领崩溃恢复、会话别名与多模型组合属于不同关注点，不顺带处理。
