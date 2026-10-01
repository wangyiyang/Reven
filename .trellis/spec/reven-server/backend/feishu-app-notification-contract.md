# 飞书应用机器人契约（通知 + 对话）

## 1. 范围与触发

修改飞书配置、RSS 每日汇总通知、测试通知、部署通知或机器人对话（私聊/群聊@）时使用本契约。
用户已明确废弃 Webhook 群机器人，唯一业务 provider 为 `feishu_bot`。

## 2. 调用签名

- `PUT /api/integrations/feishu_bot`：`public_config` 包含 `whitelist_open_ids: string[]`、`enabled: boolean`；secret 包含 `app_id`、`app_secret`。
- `POST /api/integrations/feishu_bot/test -> IntegrationResponse`：显式发送测试消息。
- `reven.notifications.DeliveryNotifier.send(Notification)`：RSS 的统一通知口。
- `python3 scripts/notify_feishu_deploy.py`：Actions 部署通知，使用环境中的 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_NOTIFY_OPEN_IDS`。
- 对话入站（`integrations/feishu_bot/`）：`handlers.route_message(sender, message, bot_open_id) -> RouteDecision | None`（纯函数路由）；`chat_dispatcher.FeishuChatDispatcher.submit(*, kind, message_id, chat_id, open_id, text) -> None`（立即返回）；`client.FeishuBotApiClient.get_bot_open_id() -> str`（`/bot/v3/info`）。
- 模型指令：`parse_model_command(text) -> ModelCommand | None`，支持 `/model`、`/model list`、`/model current`、`/model use provider/model`；renderer 消费 `SessionModelState`，不接收含凭证的注册表条目。
- 对话会话：session_id = `feishu:{chat_id}:{open_id}`，传入 `AgentService.chat(message, session_id)`；群内每人独立会话。

### 统一 HTTP 交付入口

`FeishuBotApiClient` 提供：

```python
send_markdown(open_id: str, markdown: str, *, title: str | None = None) -> None
send_markdown_to_chat(chat_id: str, markdown: str, *, title: str | None = None) -> None
send_markdown_to_recipients(recipients: tuple[str, ...], markdown: str, *, title: str | None = None) -> None
reply_markdown(message_id: str, markdown: str, *, title: str | None = None) -> None
send_notification_to_recipients(recipients: tuple[str, ...], notification: Notification) -> None
```

入口内部调用同一个 `_deliver`，调用方不提供 `fallback_text`。
普通 markdown 的文本表示为非空标题加换行加原正文；结构化 `Notification`
由客户端生成卡片与文本，文本保留标题、阶段、摘要以及 `label：URL`。
既有 `send_text*` 保留给连接测试等明确文本调用。

引用回复使用 tenant token，发送
`POST /open-apis/im/v1/messages/{quote(message_id, safe="")}/reply`；
JSON 仅包含 `msg_type` 与 JSON 字符串 `content`，不提交 `receive_id`、
`receive_id_type`、`uuid` 或 `reply_in_thread`。

`provider_clients.FeishuReplier(clients)` 是异步 callable：
`await reply(message_id, text)` 成功返回 `None`。每次调用进入
`clients.feishu_bot()` 现读配置，复用 ProviderClients 的共享 HTTP 生命周期。
dispatcher 构造时注入这个 callable；SDK handlers 只负责入站路由，
不构造 SDK 出站 client 或消息发送闭包。

## 3. 行为契约

- RSS 每日汇总只读取应用配置，不依赖 Webhook。稿件发布、Notion 与 outbox 已由主线退役，不得恢复。
- `enabled` 控制应用机器人运行时通知与入站连接；显式发送测试由用户触发，可验证未启用配置。
- 白名单是「可使用机器人的用户」：既是主动通知接收人，也是唯一能与机器人对话的用户。Open ID 必须属于该应用；空白名单不能被当作发送成功。
- 通知与对话回复统一以 interactive 卡片（schema 2.0，`cards.build_markdown_card`）发送：标题入 header，阶段/摘要/链接等渲染在 markdown 正文；卡片发送失败必须降级为纯文本（标题、阶段、摘要、链接全部保留）保证可达，纯文本也失败才报错。每日汇总（含本次统计、待审核总数与候选工作台入口）是唯一候选相关主动通知，每位接收人每天最多一条；候选审核收敛到网页候选工作台，不存在任何审核卡片推送、补发或卡片按钮回调链路。只由飞书应用客户端负责出站 API 边界。
- 同目标交付与渠道选择分开：卡片遇业务码、HTTP、网络或响应格式错误时，在同一目标尝试文本；两种表示均失败才抛脱敏 `FeishuBotApiError`。引用回复绝不改投白名单。主动定向 chat 两种表示均失败后，`ProactiveNotifier` 才按已有流程尝试白名单。
- daemon 的所有引用回复都经已有 `_bridge` 调度到主循环；异步 `_send_reply` 成功返回 `True`，避免将 callable 的 `None` 成功值误认为 bridge 失败哨兵。占位回复成功后才执行 Agent，调度失败仍关闭未被 await 的协程。
- 对话路径白名单外用户**全静默**：私聊、群聊@、非文本消息一律不回，连「思考中…」占位回复也不发；白名单预检必须先于一切外显回复。
- 对话入站只经 lark-oapi WS 长连接。消息处理器在 SDK 连接事件循环上**同步执行**，SDK 的 ping 循环（间隔约 120s）跑在同一循环上——**处理器必须立即返回，严禁在处理器内阻塞等待 Agent 或任何慢 IO**，否则心跳超时掉线。等待一律挪到 daemon 工作线程；慢调用用 `bind_loop()` 绑定主循环 + `asyncio.run_coroutine_threadsafe` 桥接，`run_coroutine_threadsafe` 调度失败必须 `coro.close()`；一切异常收敛为兜底文案 + 脱敏日志，绝不向 SDK 抛。
- 群聊@判定只用 `mentions[*].id.open_id == bot open_id`（`name`/`mentioned_type` 不可靠，禁用）；mention 占位符用 `mentions[*].key` 从正文剥离。bot open_id 在 `supervisor.start()` 获取，失败降级为群聊忽略 + warning 日志，**私聊不受影响**（私聊无需 bot open_id）。
- 对话回复策略：先引用回复「思考中…」再引用回复最终结果（均按触发消息 message_id reply，卡片优先、失败降级纯文本）；非文本消息统一回「暂只支持文字提问」；剥离 mention 后空文本回引导文案。
- 飞书只拥有模型指令语法、IM 会话映射和渲染。选择/默认/可用性由共享 AgentService 的 `model_state`、`use_model`、`chat` 解释，不保存另一份 override 字典。回答落款使用本轮 `AgentTurn` 身份；执行期间切换不影响本轮落款。生效默认与已保存默认不同时，current/list 明确提示重启后生效；普通场景文案保持。
- 对话白名单每次现读 `credentials.feishu_bot()`（主循环内），配置页改白名单即时生效，不依赖连接重建。
- 单轮对话超时 120s（`_CHAT_TIMEOUT_SECONDS`，构造参可注入，测试传小值）；超时后 dsh 侧 `harness.run` 线程不取消、跑完为止——已知取舍，不引入取消机制。
- 连接测试包含 token、`/open-apis/bot/v3/info` 和真正发送消息。前端检查返回的 `connection_status`，不能只凭 HTTP 200 显示成功。
- 汇总去重只复用 `rss_discovery_runs.notification_sent_at` 与调度器同日完成缓存：发送失败不标记、随 run 重入重试；不新增去重表或字段，也不表示每次 scheduler tick 都重发。
- 禁止将任一接收人发送失败记为整条成功。RSS 保留已有发送状态及重试行为，多人部分成功后整次重试仍可能重复发送。
- 迁移 0022 接在主线 0021 后，精确删除 `integrations.provider = 'feishu'` 行，不删除其他集成或通知历史；降级不伪造旧凭证。
- API 列表过滤退役行，旧 provider 全部路径 404；CMS provider、卡片和类型校验一致。
- Actions 三项配置全空时跳过，部分配置时报错；以应用身份发给用户，UUID 在同一个 run/attempt/收件人/内容重试间保持稳定。
- 凭证、token、原始错误响应不得出现在日志或错误提示中；保留错误码与可执行的固定提示。

## 4. 验证与错误矩阵

| 条件 | 结果 |
| --- | --- |
| 未配置、禁用或不能解密 | 运行时不能报告发送成功；错误保持脱敏 |
| 没有接收人 | 明确提示配置接收人，不能只验证凭证后成功 |
| 缺少发送权限 | 测试失败并显示权限错误，前端不得出现成功 toast |
| 多人发送部分失败 | 整次通知失败，RSS 不标记汇总已发送 |
| 旧 `feishu` 数据行存在 | API 列表隐藏，专用路径 404 |
| Actions 三项配置全空/部分缺失 | 全空跳过；部分缺失退出非零 |
| Actions token 或消息 API 失败 | 退出非零，不输出 Secret/token/响应原文 |
| 对话超时或其他 AgentError | 用户收兜底文案「出了点问题，请稍后重试」；日志含 error_type + error_code，不含异常 message（可能回显 secret） |
| 指定模型不可用 `AgentModelUnavailableError` | 明确模型不可用提示，保留选择，不回落其他模型；提示显式恢复路径 |
| bot open_id 获取失败 | 群聊消息一律忽略 + warning；私聊正常 |
| 白名单外用户任何消息 | 零回复、零 dispatch，仅 debug 日志 |
| 「思考中…」占位发送失败 | 放弃本轮，不再发结果，避免时序错乱 |
| 卡片失败、同目标文本成功 | 整次交付成功；标题和正文必要内容保留 |
| 卡片和文本均失败 | 显式脱敏失败；不得提前切换目标或记录成功 |
| reply 失败 | 始终引用原 message_id，不转主动通知渠道 |

## 5. 正常、默认与错误案例

- 正常：只配置应用凭证和当前应用下的用户 Open ID，测试通知与 RSS 每日汇总均可发送。
- 默认：未配置 CI 通知 Secrets 的仓库仍可部署，通知步骤明确跳过。
- 错误：获取 tenant token 成功就显示“测试消息已发送”，会掩盖权限缺失。
- 错误：为汇总去重引入新表或新字段；去重只能复用 `notification_sent_at` 与同日完成缓存。
- 错误：在消息处理器里 `future.result(timeout=120)` 阻塞等 Agent——ping 循环同循环，心跳超时掉线。

## 6. 必须覆盖的测试

- provider 退役全部 API 路径与列表过滤，配置迁移只影响旧行，降级不重建假数据。
- 应用鉴权、有效消息请求、多收件人、空白名单、权限错误和密钥脱敏。
- RSS 汇总失败重入重试不重复投递、同日重跑不重复发送；1/100/1,000 条待审核候选下同一接收人仅收到一条汇总，且包含准确待审核总数与候选工作台入口。
- 前端无 Webhook 入口、类型化保存、重复点击保护、失败不报成功。
- CI 脚本解析环境与接收人、真实请求形状、API/网络错误、同一操作稳定 UUID。
- 对话路由矩阵：私聊 text/非文本、群聊无@/@他人/@bot 剥离/空文本引导、非 user sender、畸形 JSON；bot open_id 一律参数注入，测试零网络。
- HTTP 交付矩阵：open_id、chat_id、reply 的真实请求形状；卡片成功、业务失败、网络异常、HTTP/非法响应、文本再次失败与标题保留。策略只在 HTTP 客户端 seam 验证，SDK 不再复制出站策略测试。
- 组合回归：CRM 提醒 → 调度器 → 真实主动通知 adapter → MockTransport，卡片失败后文本仍含标题及客户信息；结构化通知降级保留阶段、摘要与链接。
- 模型指令：解析/用法/正常文案、default/override 落款、默认漂移提示与拒绝切换；业务组合在真实 AgentService/runtime seam 验证，不把状态机复制到飞书 stub。
- 对话桥接：`bind_loop(get_running_loop())` + `asyncio.to_thread(submit)`；dead loop 调度失败兜底且不泄漏协程（可加 `-W error::RuntimeWarning`）；超时注小值；AgentError 矩阵；非白名单零 reply；db 改白名单下一轮即时生效。

## 7. 错误与正确写法

```python
# 错误：仍要求旧 Webhook provider 才能完成应用通知。
integration = await repository.get_by_provider("feishu")

# 正确：唯一配置源为应用机器人，且需要校验 enabled、凭证与接收人。
integration = await repository.get_by_provider("feishu_bot")
```

```typescript
// 错误：HTTP 200 即显示已发送。
await requestIntegration(path, { method: "POST" })
return { message: "测试消息已发送" }

// 正确：业务状态失败必须显式进入错误路径。
const result = await requestIntegration(path, { method: "POST" })
if (result.connection_status !== "连接正常") throw new Error(result.last_error ?? "测试失败")
```

```python
# 错误：在 SDK 连接线程的处理器里阻塞等 Agent，ping 循环同循环会心跳掉线。
def on_message(data):
    future = asyncio.run_coroutine_threadsafe(agent.chat(text, session_id), main_loop)
    answer = future.result(timeout=120)  # 阻塞 120s，连接断开
    reply(data.event.message.message_id, answer)

# 正确：处理器只路由并 submit，立即返回；等待在 daemon 工作线程内完成。
def on_message(data):
    decision = route_message(data.event.sender, data.event.message, bot_open_id)
    if decision is not None:
        dispatcher.submit(kind=decision.kind, ...)  # 立即返回，reply 在构造时注入
```

```python
# 错误：调用方构造另一份降级正文，或 SDK handler 直接执行发送策略。
await bot.api.send_markdown(open_id, markdown, fallback_text=separate_text)

# 正确：交付 module 拥有内容表示和降级；调用方只提供业务消息。
await bot.api.send_notification_to_recipients(recipients, notification)
await replier(message_id, answer)
```
