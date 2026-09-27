# Research: 现有测试与可测性

- Query: server/tests 下 feishu_bot 与 agent 的既有测试基座（mock 手法、事件构造、pytest 配置），新功能测试切入点
- Scope: internal
- Date: 2026-09-27

## Findings

### pytest 基座

- 配置在**仓库根** `pyproject.toml:37-43`：`testpaths=["server/tests"]`、`pythonpath=["server/src"]`、自定义 marker `dsh_runtime`（真实拉起 dsh 子进程的测试，可 `-m 'not dsh_runtime'` 排除）。
- 异步测试用 **anyio pytest 插件**（`anyio>=4,<5`，根 pyproject.toml:13），不是 pytest-asyncio：`server/tests/conftest.py:20-22` 定义 session 级 `anyio_backend() -> "asyncio"`，用例标 `@pytest.mark.anyio`。
- `db_session` fixture（conftest.py:25-46）：依赖 `TEST_DATABASE_URL` 真实 PG 库，每用例 TRUNCATE 全表；本地无库自动 skip，CI 强制要求（`pytest_sessionstart`）。
- 现网测试全部可跑通的事实基础：`pytest -m 'not dsh_runtime'` 无需外部凭证。

### feishu_bot 现有测试（`server/tests/integrations/feishu_bot/`）

| 文件 | 覆盖 | 关键手法 |
|---|---|---|
| `test_handlers.py`（114 行） | 引导回复处理器 + 分发器注册回归 | **直接用 dict 构造 SDK 事件**：`P2ImMessageReceiveV1({"event": {"sender": {...}, "message": {...}}})`（test_handlers.py:12-29），SDK `init()` 负责反序列化；reply 用 `ReplyRecorder` 假可调用（test_handlers.py:32-40）替代真实 im_client；`build_event_handler` 后断言 `handler._processorMap` 键（test_handlers.py:110-114） |
| `test_supervisor.py`（261 行） | start/stop/reload 全生命周期 | `connection_factory` 注入 `FakeConnection`（threading.Event 模拟阻塞 run/shutdown，test_supervisor.py:39-70）；真实 `IntegrationCredentials` + `db_session` 写 integrations 行（`_write_bot_config`，test_supervisor.py:82-95）；`SecretBox.from_base64` 加密假凭证；`_wait_until` 轮询异步断言（test_supervisor.py:73-79）；默认工厂用 `supervisor._build_default_connection(...)` 后翻 `connection._client._event_handler._processorMap` 私有字段断言注册（test_supervisor.py:244-253） |
| `test_app_lifespan.py`（65 行） | lifespan 起停接线 | `monkeypatch.setattr("reven.app.FeishuBotSupervisor", FakeSupervisor)`（test_app_lifespan.py:45）+ `TestClient(create_app(start_background_tasks=False, session_factory=factory, settings=settings))`；dummy PG URL（不真连，只建 engine） |
| `test_client.py` | FeishuBotApiClient HTTP 层 | **respx** mock httpx：token 端点 + 消息端点（test_client.py:10-16）；脱敏断言（异常串不含 secret/token） |
| `test_service.py` | 连接测试服务 | 构造 `FeishuBotApiClient` 走 respx / 无效凭证分支 |

**lark 事件 mock 范式**（直接可用于新用例）：

```python
P2ImMessageReceiveV1({
    "event": {
        "sender": {"sender_id": {"open_id": "ou_boss"}, "sender_type": "user", "tenant_key": "t"},
        "message": {
            "message_id": "om_1", "chat_id": "oc_1", "chat_type": "p2p",  # 或 "group"
            "message_type": "text", "content": '{"text":"hi"}', "create_time": 1,
            # 群聊 @机器人 用例加：
            "mentions": [{"key": "@_user_1", "id": {"open_id": "ou_bot"}, "name": "Reven"}],
        },
    }
})
```

群聊 mention 用例在现有文件里**没有先例**，但构造方式相同（dict 多给 `mentions` 键即可，`MentionEvent` 会被 `init()` 自动装配，见 lark-oapi-event-structure-mention.md）。

### agent 现有测试

| 文件 | 覆盖 | 关键手法 |
|---|---|---|
| `server/tests/agent/test_runtime.py`（144 行） | runtime 起停/降级/重试/MCP 注入 | `monkeypatch.setattr("reven.agent.runtime._launch", _fail_launch)` 模拟启动失败（test_runtime.py:63-66）；`_stub_harness` 用假类替换 `DeepSeekHarness`（test_runtime.py:98-112）；真实子进程用例标 `@pytest.mark.dsh_runtime`（test_runtime.py:20） |
| `server/tests/api/test_agent_chat.py`（106 行） | /api/agent/chat 路由 | **`_StubRuntime` 鸭子类型直接替换 `app.state.agent_runtime`**（test_agent_chat.py:13-25, 69, 79, 90）：`async def chat(message, session_id=None)` 记录调用、可设抛错；验证 503/502/200 与 session_id 透传 |
| `server/tests/agent/test_agent_config.py` 等 | 配置/MCP/工具 | 与本需求相关性低 |

**AgentService mock 范式**：飞书侧不需要 mock `AgentService` 类本身——按 `api/dependencies.py:13-14` 的 `AgentChatService` Protocol 写一个 `_StubAgentService`（记录 `(message, session_id)` 调用、可配置返回/抛 `AgentError` 子类）注入 dispatcher 即可，与 `_StubRuntime` 同构。

### 已删除但可复用的测试资产（git 历史）

`git show 3c44e27^:server/tests/integrations/feishu_bot/test_review_callback.py`（344 行）里有两组直接可搬的手法：

1. **桥接测试范式**（test_review_callback.py:233-296 区段）：
   - `dispatcher.bind_loop(asyncio.get_running_loop())` 后 `await asyncio.to_thread(dispatcher, ...)`——**在 worker 线程里调同步桥，主 loop 是当前测试 loop**，断言同步返回的兜底结果与 executor 调用记录；
   - 未 bind loop → 兜底（test_dispatcher_without_bound_loop...）；
   - **bind 一个已关闭的 loop**（`asyncio.new_event_loop(); dead_loop.close()`）模拟 `run_coroutine_threadsafe` 调度失败 → 兜底（test_dispatcher_bridge_failure...）。
2. **白名单/错误映射纯异步测试**：`run_review_action` 风格的纯函数用 `FakeExecutor`（记录调用 + 可设抛错）+ parametrize 错误类型矩阵；脱敏日志断言用 `caplog`（异常 message 不出现在日志里）。

### 新功能建议的测试文件与切入点

| 文件 | 动作 | 切入点建议 |
|---|---|---|
| `tests/integrations/feishu_bot/test_handlers.py` | **改** | ① 私聊 text → dispatch 收到 (chat_id, open_id, 正文)，且先 reply「思考中…」（ReplyRecorder 双调用断言）；② 群聊无 mention / mention 他人 → 忽略；③ 群聊 mention bot（`id.open_id` 匹配）→ 剥离 `@_user_1` 占位后正文正确；④ 剥离后为空 → 引导文案；⑤ 非 text（image 等）→ 「暂只支持文字提问」；⑥ 非白名单 open_id → 完全静默（不 reply 不 dispatch）；⑦ sender_type!=user → 忽略（现有回归保留）；⑧ content JSON 畸形 → 不崩。事件全用 dict 构造，bot open_id 作为 build 参数注入（免网络） |
| `tests/integrations/feishu_bot/test_chat_dispatcher.py` | **新** | 复刻 test_review_callback.py 桥接范式：`bind_loop(get_running_loop())` + `asyncio.to_thread` 调 submit；断言 `_StubAgentService.calls == [(text, "feishu:oc_1:ou_boss")]`；超时用 `timeout_seconds=0.05` + 慢假服务断言兜底回复；`AgentNotConfiguredError`/`AgentRuntimeError`/未知异常 → 兜底文案矩阵；bridge 失败（dead loop）→ 兜底且不泄漏协程；白名单现读：db 里改 whitelist 后下一次调用即生效 |
| `tests/integrations/feishu_bot/test_supervisor.py` | **改** | ① dispatcher 注入后 `start()` 触发 `bind_loop`（FakeDispatcher 记录 loop）；② reload 原子替换后新连接仍持有同一 dispatcher（事件序列断言同 test_supervisor.py:165 风格）；③ `_build_default_connection` 注册回归扩展：断言 `_processorMap` 内处理器闭包含 chat dispatch（或仅断言注册键不变） |
| `tests/integrations/feishu_bot/test_app_lifespan.py` | **改** | FakeSupervisor 构造签名跟随真实类变化（若加 `chat_dispatcher` 参数）；断言 lifespan 中 agent_runtime 先于 supervisor.start（可用 Fake 记录调用序） |
| `tests/integrations/feishu_bot/test_client.py` | **可选改** | 若选择扩展 `FeishuBotApiClient.get_bot_open_id()`：respx mock `BOT_INFO_URL` 返回 `{"bot": {"open_id": "ou_bot"}, "code": 0}` 断言解析 |
| `tests/api/test_integrations_feishu_bot.py` | 不改 | 配置页 API 不变（whitelist 语义扩展只改文案，无行为变更） |

### 可测性设计建议（写进 design.md 的理由）

1. **bot open_id 以参数注入 `build_event_handler`**（而非构建时联网获取），handler 单测零网络；联网获取的兜底逻辑放 dispatcher/connection 层单独测（可用 monkeypatch 替换获取函数）。
2. **dispatch 协议保持同步可调用 + reply 回调注入**（沿用现有 `MessageReplier` 模式），handler 测试继续用 ReplyRecorder，dispatcher 测试用 `_StubAgentService` + `asyncio.to_thread`，两层互不依赖真实 SDK/真实 dsh。
3. 纯逻辑（mention 剥离、白名单判定、错误→文案映射）抽成**纯函数**单测，对标当年 `run_review_action` 的测试形态。
4. 超时测试注入 `timeout_seconds` 参数（当年 dispatcher 就有 `timeout_seconds: float = _CALLBACK_TIMEOUT_SECONDS` 构造参，test 里传小值），避免测试真等 120s。

## Caveats / Not Found

- 现有测试**没有任何 lark ws 真实连接级测试**（LarkWsConnection 的 run/shutdown 私有 API 操作无覆盖，只经 connection_factory 替身规避）——新功能同样不应尝试真实连飞书。
- `test_handlers.py:110-114` 与 `test_supervisor.py:244-253` 都断言「只注册 im 处理器」，新增分发逻辑后这两个回归断言的口径需要同步更新（注册键不变，但闭包行为变了）。
- anyio 插件模式下 `asyncio.get_running_loop()` 在 `@pytest.mark.anyio` 用例里可用；worker 线程桥接测试必须在 anyio 用例内做（需要活的主 loop），纯同步用例无法测 bind_loop 路径。
