# Research: lark-oapi 事件结构与 mention 处理

- Query: P2ImMessageReceiveV1 事件模型、message.content/mentions 结构、群聊 @机器人 判定、reply API 形态
- Scope: internal（项目 .venv 内 lark-oapi 1.7.3 源码 + 项目现有代码）
- Date: 2026-09-27

## Findings

### SDK 版本与事件模型

- 安装版本：`lark_oapi/core/const.py:3` → `VERSION = "1.7.3"`；约束 `server/pyproject.toml:18` → `lark-oapi>=1.4,<2`。
- 事件分发入口：`EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(f)`（`lark_oapi/event/dispatcher_handler.py:2013-2022`），处理器签名 `Callable[[P2ImMessageReceiveV1], None]`，由 `P2ImMessageReceiveV1Processor.do()` **同步调用**（`lark_oapi/api/im/v1/processor.py:146-147` → `self.f(data)`）。
- 顶层结构（`lark_oapi/api/im/v1/model/p2_im_message_receive_v1.py`）：
  - `P2ImMessageReceiveV1.event` → `P2ImMessageReceiveV1Data`，字段 `sender: EventSender`、`message: EventMessage`。
  - `P2ImMessageReceiveV1` 继承 `EventContext`（`lark_oapi/event/context.py`），另有 `header: EventHeader`（含 `event_id`、`event_type`、`app_id` 等），本需求用不到。

### EventMessage 字段（`lark_oapi/api/im/v1/model/event_message.py:9-24`）

```python
class EventMessage:
    message_id: str | None
    root_id / parent_id / thread_id: str | None
    create_time / update_time: int | None
    chat_id: str | None
    chat_type: str | None        # "p2p" | "group"（字符串，非枚举类型）
    message_type: str | None     # "text" | "post" | "image" | "file" | "sticker" | ...（裸 str）
    content: str | None          # JSON 字符串，需 json.loads
    mentions: list[MentionEvent] | None
```

- `message_type`/`chat_type` 在 SDK 里都是 `Optional[str]`，**没有枚举类**；按飞书开放平台文档取值：`chat_type ∈ {"p2p","group"}`，`message_type` 文本消息为 `"text"`（其余 image/file/audio/media/sticker/post 等）。项目现有判定见 `handlers.py:37`（`message.chat_type != "p2p"`）。
- text 类型 `content` 结构：`{"text": "..."}`，**mention 以占位符形式内嵌**，如 `{"text":"@_user_1 你好"}`。测试里已有同款构造：`server/tests/integrations/feishu_bot/test_handlers.py:24` → `"content": '{"text":"hi"}'`。

### MentionEvent 字段（`lark_oapi/api/im/v1/model/mention_event.py:9-16`）

```python
class MentionEvent:
    key: str | None             # 正文中的占位符，如 "@_user_1"
    id: UserId | None           # UserId(user_id/open_id/union_id)，见 model/user_id.py:9-13
    mentioned_type: str | None  # 飞书侧取值如 "user"/"app"（SDK 未给枚举，勿依赖）
    name: str | None            # 被 @ 者显示名（可改，不可靠）
    tenant_key: str | None
```

`EventSender`（`model/event_sender.py:9-13`）：`sender_id: UserId`（含 `open_id`）、`sender_type: str`（`"user"` / `"app"` 等）、`tenant_key`。

### 群聊「机器人被 @」的可靠判定

**结论：用 `mentions[*].id.open_id == <机器人 open_id>` 判定；机器人 open_id 必须主动获取，SDK 事件本身不自报门户。**

机器人 open_id 的三个获取途径（按与本仓代码风格的契合度排序）：

1. **复用 SDK sync escape hatch（推荐）**：`build_event_handler`（`handlers.py:50-76`）里已构建 `im_client`，`lark_oapi.Client` 暴露公共方法 `request(BaseRequest)`（`lark_oapi/client.py:181-204`，内部 `verify()` 注入 tenant token + `Transport.execute` 同步请求）。可一次性同步 GET `/open-apis/bot/v3/info`，响应体 `bot.open_id` 即所求。骨架：

   ```python
   from lark_oapi.core.enum import AccessTokenType, HttpMethod
   from lark_oapi.core.model import BaseRequest

   req = BaseRequest()
   req.http_method = HttpMethod.GET
   req.uri = "/open-apis/bot/v3/info"
   req.token_types = {AccessTokenType.TENANT}
   resp = im_client.request(req)          # 同步；resp.raw.content 为原始字节
   open_id = json.loads(resp.raw.content)["bot"]["open_id"]
   ```

2. **SDK 自带 `lark_oapi/channel/bot_identity.py`**：`fetch_bot_identity(config) -> BotIdentity(open_id, ...)`，先打 `/bot/v3/info` 再回退 `application/v6`。**但它是 async 且只被 `lark_oapi.channel` 体系使用**，handlers 的同步构建上下文里用不上（除非在 supervisor.start() 的 async 段预先解析再传入）。
3. **扩展现有 `FeishuBotApiClient`**（`server/src/reven/integrations/feishu_bot/client.py`）：`verify_bot()`（client.py:52-58）已经 GET 同一 `BOT_INFO_URL`（client.py:10），**只是丢弃了 payload**。最小改动：新增 `async def get_bot_open_id() -> str`（或让 verify_bot 返回 open_id），在 `supervisor.start()` 的 async 段解析后随连接工厂注入 handler 闭包。注意响应是 `{"bot": {...}, "code": 0, ...}` 顶层结构（`bot_identity.py:117-140` 的 `_parse_data` 注释确认 `/bot/v3/info` 把 `bot` 放在顶层）。

⚠️ 不可用的判定法：
- 按 `mention.name` 匹配机器人名：显示名可改，不可靠。
- 按 `sender.sender_type`：那是消息发送者类型，不是 mention 类型。
- p2p 私聊**不需要** bot open_id（所有私聊用户消息都响应）。

### 剥离 mention 占位符取纯文本

正确做法（与飞书协议一致）：

```python
text = json.loads(message.content).get("text", "") if message.message_type == "text" else ""
for m in (message.mentions or []):
    if m.key:
        text = text.replace(m.key, " ")
text = text.strip()
```

- `mentions` 的 `key`（如 `@_user_1`）就是正文里的占位符，逐个替换掉再 strip。群聊场景剥离后为空 → 按 PRD 回引导文案。
- `json.loads` 失败/非 text 类型要兜底（PRD：非 text 统一回「暂只支持文字提问」）。

### reply API 形态与「两条引用回复」可行性

现有用法（`handlers.py:58-72`）：

```python
request = (ReplyMessageRequest.builder().message_id(message_id)
    .request_body(ReplyMessageRequestBody.builder()
        .msg_type("text").content(json.dumps({"text": text}, ensure_ascii=False)).build())
    .build())
response = im_client.im.v1.message.reply(request)   # sync，返回 ReplyMessageResponse
```

- `ReplyMessageResponse.data` → `ReplyMessageResponseBody`（`model/reply_message_response_body.py:9-27`），**含 `message_id: str`**（成功创建的新消息 ID）。→ 回复后可以拿到新 message_id。
- `ReplyMessageRequestBody` 字段（`model/reply_message_request_body.py:7-20`）：`content / msg_type / reply_in_thread / uuid`；`uuid` 可做幂等去重键（可选）。
- **结论**：PRD 的「先回思考中…再回最终结果」完全可行——两次 `im.v1.message.reply` 都用**触发消息的 message_id**（均成为该消息的引用回复）；第一条的返回 `data.message_id` 可留作未来「卡片局部更新」替换思考中消息之用，MVP 不需要。
- 注意 `reply()` 是**同步阻塞 HTTP**，在 SDK 连接线程里调用 OK（现状如此），但要控制次数与耗时。

## Caveats / Not Found

- `MentionEvent.mentioned_type` 的具体取值集合 SDK 未定义枚举，飞书文档侧常见为 `user`；判定机器人请只用 `id.open_id` 比对，勿用 `mentioned_type`/`name`。
- SDK 无 `bot.v3` 生成资源（`bot_identity.py` docstring 原话），只能 raw request 或走现有 httpx client。
- `im_client` 的 tenant token 有内部缓存（`core/token/manager.py`），多线程并发调用未加锁；现有代码已从连接线程调用 reply 无锁运行，风险可接受，但若新增「工作线程并发发消息」需留意 token 刷新竞态（影响面：偶发重复刷新，不致命）。
- 处理器在 SDK 连接事件循环上同步执行（`ws/client.py:341` → `_do_without_validation`），**严禁在处理器内阻塞等待 Agent 结果**——ping 循环（`ws/client.py:177-191`，间隔 120s）同循环运行，阻塞 120s 会心跳超时掉线。详见 review-callback-thread-bridge.md。
