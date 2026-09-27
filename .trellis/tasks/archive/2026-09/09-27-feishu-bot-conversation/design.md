# 飞书机器人接入 Agent 对话 · 技术设计

> 依据：本目录 `prd.md`（需求共识）+ `research/` 四份调研。核心模式复刻自 commit `3c44e27^` 被删的 `review_callback.py` 线程桥，但有一处关键偏离（见「关键取舍」第 1 条）。

## 数据流

```
飞书 ──WS 长连接──> lark-oapi SDK 连接线程
  └─ handlers.py 消息处理器（同步、零网络、零阻塞）
       └─ route_message() 纯函数路由判定
            ├─ 忽略（非 user / 群聊未@ / bot open_id 未知时的群消息）
            └─ dispatcher.submit(kind, message_id, chat_id, open_id, text, reply)
                 │  ← handler 到此立即返回，SDK 循环不受任何影响
                 ▼
       chat_dispatcher.py 工作线程（daemon，每条消息一个）
            1. bridge A：run_coroutine_threadsafe(_is_allowed(open_id)) → 主循环读白名单
               非白名单 → 静默 return（任何消息都不回）
            2. kind=guide       → reply(引导文案)
               kind=unsupported → reply(暂只支持文字提问)
               kind=chat        → reply(思考中…)
            3. bridge B：run_coroutine_threadsafe(_chat(text, session_id), timeout=120s)
               → 主循环 AgentService.chat()
            4. reply(答案) / 异常·超时 → reply(兜底文案)
```

**为什么需要两座桥**：白名单校验必须先于「思考中…」（PRD：白名单外直接忽略，连占位消息都不发），而白名单读取是 async（credentials seam 走 db）；Agent 对话是另一座慢桥（120s）。两座桥都在工作线程内等待，SDK 连接线程全程零阻塞。

## 模块边界与改动点

| 文件 | 动作 | 职责 |
|---|---|---|
| `integrations/feishu_bot/chat_dispatcher.py` | **新建** | `FeishuChatDispatcher`：`bind_loop()` + `submit()`（立即返回）+ 工作线程编排 + 主循环协程（白名单现读、Agent 调用）。本地定义 `AgentChatService` Protocol（鸭子类型，不 import api 层，避免跨层依赖） |
| `integrations/feishu_bot/handlers.py` | 改 | 新增 `route_message(sender, message, bot_open_id) -> RouteDecision | None` 纯函数（mention 判定、占位符剥离、非文本分类）；`build_event_handler()` 增加 `bot_open_id`、`chat_dispatch` 参数；删除固定引导文案逻辑 |
| `integrations/feishu_bot/supervisor.py` | 改 | `__init__` 增加 `chat_dispatcher` 参数；`start()` 内获取 bot open_id（失败降级见下）并 `dispatcher.bind_loop(main_loop)`；`_build_default_connection` 透传两者 |
| `integrations/feishu_bot/client.py` | 改 | `verify_bot()` 已 GET `/open-apis/bot/v3/info` 但丢弃 payload → 新增 `async get_bot_open_id() -> str`，复用同一端点与 token 缓存 |
| `app.py` | 改 | `_build_feishu_bot_supervisor()` 增加 `agent_runtime` 参数（lifespan 局部变量 `app.py:205` 天然可用），构造 `AgentService(agent_runtime)` → `FeishuChatDispatcher(credentials, agent_service)` → 传入 supervisor。启动顺序（runtime 先于 supervisor）与关闭顺序现状已正确，不动 |
| `web/src/features/integrations/` | 改 | 白名单字段文案：「通知接收人」→「可使用机器人的用户（接收通知 + 对话）」类表述，仅文案 |

智能（LLM、记忆、工具）全部在 `AgentService`/`AgentRuntime`，本任务零改动；飞书侧只做渠道适配。

## 关键契约

### 消息路由（`route_message` 纯函数）

输入 `(sender, message, bot_open_id)`，按序判定：

1. `sender.sender_type != "user"` → `None`（防自循环，现状保留）
2. `chat_type == "p2p"`：`message_type == "text"` → `chat(剥离后文本)`；其他类型 → `unsupported`
3. `chat_type == "group"`：`bot_open_id` 为 `None` 或 `mentions` 中无 `id.open_id == bot_open_id` → `None`；被 @ 后：非 text → `unsupported`；text 剥离所有 `mention.key` 占位符（`text.replace(key, " ")` + strip）后为空 → `guide`，否则 → `chat(文本)`
4. `json.loads(content)` 畸形 → 按非 text 处理为 `unsupported`（不崩）

判定机器人被 @ **只用 `mentions[*].id.open_id` 比对**；`name`/`mentioned_type` 不可靠，禁用（research 1）。

### bot open_id 获取与降级

- `supervisor.start()` 的 async 段调 `FeishuBotApiClient.get_bot_open_id()`，成功后存 `self._bot_open_id` 并随连接工厂注入 handler 闭包；`reload()` 重建连接时若仍为 `None` 则重试。
- **降级**：获取失败 → `bot_open_id=None`，群聊消息一律忽略并记 warning 日志；**私聊不受影响**（私聊不需要 bot open_id）。

### dispatch 协议

- `submit(*, kind, reply, message_id, chat_id, open_id, text) -> None`：**必须立即返回**；`reply` 为同步可调用（现有 `MessageReplier` 模式），`kind ∈ {"chat","guide","unsupported"}`。
- 白名单在**主循环内每次现读** `credentials.feishu_bot()`（复刻当年 `_execute` 模式），配置页改白名单即时生效，不依赖 reload。
- session_id = `f"feishu:{chat_id}:{open_id}"`；`AgentService.chat` 返回的 session_id 忽略。
- 超时：模块常量 `_CHAT_TIMEOUT_SECONDS = 120.0`，构造参可注入（测试传小值）。预检桥超时 10s。
- 文案常量：引导文案 / 「思考中…」/ 「出了点问题，请稍后重试」/ 「暂只支持文字提问」，集中在 dispatcher 模块顶部。

### 错误纪律（沿用 handlers.py 现有纪律 + 当年模式）

- 一切异常收敛为兜底文案/日志，**绝不向 SDK 抛**。
- `run_coroutine_threadsafe` 调度失败必须 `coro.close()`，防协程泄漏。
- `except AgentError`（`AgentNotConfiguredError`/`AgentRuntimeError` 一族）与超时、未知异常统一 → 兜底文案；日志记 `type(exc).__name__` + 脱敏 message，不含 secret/token。
- 占位「思考中…」发送失败 → 直接放弃本轮（不再尝试发结果，避免时序错乱），记日志。

## 关键取舍

1. **handler 必须立即返回，等待挪到 daemon 工作线程**（与当年 review_callback 阻塞 10s 模式的最大偏离）：lark-oapi SDK 的 ping 循环（间隔 120s）与消息处理器跑在同一连接事件循环上（`.venv/lark_oapi/ws/client.py:177-191,341`），在 handler 里等 120s 会心跳超时掉线。代价：每条消息一个线程，白名单规模小，可接受。
2. **两次 HTTP reply 都在工作线程**（含「思考中…」）：SDK 连接线程零网络调用，比当年模式更干净；`reply()` 同步 HTTP <1s，在工作线程无约束。
3. **120s 超时后 dsh 侧 `harness.run` 线程不会真正取消**（dsh 无内置超时，research 3）：超时后用户收到兜底文案，后台线程跑完为止。并发提问多时线程堆积上限 = 并发数 × 单轮时长，MVP 接受，不引入取消机制。
4. **超时时间硬编码 120s**，不做配置项（YAGNI）；测试通过构造参注入小值。
5. **AgentService 薄壳直接用**：不为其再包抽象；注入类型用本地 Protocol（`async chat(message, session_id) -> tuple[str,str]`），与 `api/dependencies.py` 的 `AgentChatService` 同形。
6. **非白名单全静默**（含群聊@、非文本）：满足 PRD「直接忽略」，也避免机器人被陌生人触发任何外显行为。

## 兼容性

- 配置模型零变更：`FeishuBotConfig` 字段不动，`whitelist_open_ids` 仅语义扩展（集成页文案同步）；无 db migration。
- 出站通知通路（`FeishuNotifier` 每日汇总、`client.send_text`）不触碰。
- `supervisor.reload()` 原子替换语义不变；dispatcher 持有的 `AgentRuntime` 引用在 lifespan 内恒定，reload 不失效（research 3 验证）。
- 被替换的行为：私聊固定引导文案删除——这是 PRD 明确要求的功能替换，非回归。
- 两处既有测试断言「只注册 im 处理器」（`test_handlers.py:110-114`、`test_supervisor.py:244-253`）注册键不变、口径需跟随闭包行为更新。

## 发布与回滚

- 纯增量变更，无配置/数据迁移；随常规镜像发布，单副本约束不变（WS 长连接现状即单进程）。
- **人工前置**：确认飞书开放平台上该应用的事件订阅对群聊消息生效（机器人入群 + 群聊 @ 消息可达）；私聊对话无新增平台配置。
- 回滚 = revert 本任务 commits：机器人退回固定引导文案行为，无残留状态。

## 测试设计（详见 research/feishu-bot-testing.md）

- `test_handlers.py`（改）：dict 构造事件覆盖路由矩阵 8 用例（私聊 text、群聊无@/ @他人忽略、@bot 剥离、空文本 guide、非 text、非 user、畸形 JSON）；`bot_open_id` 作参数注入，零网络。
- `test_chat_dispatcher.py`（新）：复刻 `3c44e27^:test_review_callback.py` 桥接范式——`bind_loop(get_running_loop())` + `asyncio.to_thread(submit)`；`_StubAgentService` 记录 `(text, "feishu:oc_1:ou_boss")`；超时注 `timeout_seconds=0.05`；`AgentError` 矩阵 → 兜底；dead loop → 调度失败兜底且不泄漏协程；白名单现读（db 改白名单即时生效）；非白名单全静默（零 reply）。
- `test_supervisor.py` / `test_app_lifespan.py`（改）：构造签名跟随；`start()` 触发 `bind_loop`；reload 后新连接持有同一 dispatcher；bot open_id 获取失败降级（群忽略、私聊正常）。
- `test_client.py`（改）：`get_bot_open_id()` respx mock `BOT_INFO_URL`。
- 全程不建真实 ws 连接、不依赖真实 dsh（`-m 'not dsh_runtime'` 可跑）。
