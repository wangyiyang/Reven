# Research: AgentService 装配与调用约束

- Query: AgentService 在 app.py 的创建/生命周期、chat() 签名与异常、跨线程调用姿势、supervisor 注入最小改动点、reload 热更新影响
- Scope: internal
- Date: 2026-09-27

## Findings

### 代码结构：三层关系

| 层 | 文件 | 说明 |
|---|---|---|
| `AgentService` | `server/src/reven/agent/service.py:6-17` | 薄封装，仅持有 `AgentRuntime`，`chat()` 直接委托 |
| `AgentRuntime` | `server/src/reven/agent/runtime.py:46-100` | 持有 `DeepSeekHarness` 单例，lifespan 管理 start/close |
| API 装配 | `server/src/reven/api/dependencies.py:13-26` | `get_agent_service(request)` 每请求 `AgentService(app.state.agent_runtime)` |

`AgentService`（service.py 全文）：

```python
class AgentService:
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def chat(self, message: str, session_id: str | None = None) -> tuple[str, str]:
        return await self._runtime.chat(message, session_id)
```

注意：`AgentService` **本身无状态、无资源**，真正单例的是 `AgentRuntime`。`api/dependencies.py:17-23` 每请求 new 一个 `AgentService(runtime)` 也印证了这一点。API 层还定义了鸭子类型协议 `AgentChatService`（`dependencies.py:13-14`）：`async def chat(message, session_id=None) -> tuple[str, str]`——飞书侧可直接复用该 Protocol 做注入类型，不必 import 具体类。

### chat() 签名、异常与耗时

签名：`chat(message: str, session_id: str | None = None) -> tuple[str, str]`，返回 `(session_id, final_response)`；`session_id` 缺省时 runtime 生成 `uuid4().hex`（`runtime.py:95`）。

异常（`server/src/reven/agent/errors.py`）：

| 异常 | code | 触发条件（runtime.py 行号） | API 映射 |
|---|---|---|---|
| `AgentNotConfiguredError` | `AGENT_NOT_CONFIGURED` | 未配置 API Key（`runtime.py:88-89`） | 503 |
| `AgentRuntimeError` | `AGENT_RUNTIME_UNAVAILABLE` | dsh 启动失败降级态（`runtime.py:90-91`） | 502 |
| `AgentRuntimeError` | `AGENT_RUNTIME_NOT_STARTED` | harness 未启动（`runtime.py:92-94`） | 502 |
| `AgentRuntimeError` | `AGENT_CHAT_FAILED` | `HarnessError` 包装（`runtime.py:98-99`） | 502 |

三者都继承 `AgentError(code, message)`（errors.py:4-10）。API 路由的映射参考 `api/routes/agent.py:14-22`。飞书侧只需 `except AgentError` 一族 → 兜底文案；`AgentNotConfiguredError` 可单独给「Agent 未配置」类提示。

耗时来源（典型一轮对话）：
1. `to_thread.run_sync(lambda: harness.run(message, session_id=...))`（`runtime.py:97`）——同步 dsh SDK 调用被丢进 anyio 线程池，**耗时主体是 LLM 推理 + MCP 工具往返，量级为秒~分钟**，这正是 120s 超时兜底的由来；
2. 线程切换本身开销可忽略。并发：`runtime.py:49-51` docstring 明确「M0.4 已实测单实例多线程并发 run()（独立 session_id）真并发，不加全局锁」——飞书多用户并发提问**不需要**额外串行化。

### 生命周期与 app.py 装配（现状）

`server/src/reven/app.py` `_lifespan`（app.py:180-245）：

```python
agent_runtime = await _build_agent_runtime(            # app.py:205-207
    clients.credentials if clients is not None else None, settings, mcp_context)
current_app.state.agent_runtime = agent_runtime        # app.py:208
feishu_bot_supervisor = _build_feishu_bot_supervisor(  # app.py:209-211
    current_app, factory, clients.credentials if clients is not None else None)
...
await agent_runtime.start()                            # app.py:222  ← 先拉起 dsh
if feishu_bot_supervisor is not None:
    await feishu_bot_supervisor.start()                # app.py:223-224  ← 后启动飞书连接
```

- `AgentRuntime` 创建：`app.py:98-106` `_build_agent_runtime()` → `AgentRuntime(config, mcp=mcp)`；`config=None` 时 `AgentRuntime(None)`（未配置降级态，chat 抛 `AgentNotConfiguredError`）。
- 启动顺序对飞书接入有利：**agent_runtime.start() 先于 supervisor.start()**，飞书连接建立时 Agent 已就绪（或已确定降级）。
- 关闭：`_cleanup_resources`（app.py:137-177）先 `feishu_bot_supervisor.stop()`（app.py:147-152）再 `agent_runtime.close()`（app.py:153-157）——先断消息入口再关 Agent，顺序正确，无需调整。

### 当前 supervisor 拿到的依赖与最小注入改动点

现状 `_build_feishu_bot_supervisor`（`app.py:124-134`）：

```python
def _build_feishu_bot_supervisor(current_app, factory, credentials) -> FeishuBotSupervisor | None:
    if factory is None or credentials is None:
        return None
    supervisor = FeishuBotSupervisor(credentials)                  # 只拿到 credentials
    current_app.state.feishu_bot_supervisor = supervisor
    return supervisor
```

`FeishuBotSupervisor.__init__`（`supervisor.py:44-55`）现只有 `credentials` + `connection_factory`；但 `start()` 已存主 loop（`supervisor.py:63` `self._main_loop = asyncio.get_running_loop()`），reload 线程也在用它（`supervisor.py:79-85`）。

**最小改动链**（对照 3c44e27^ 被删接线，一步到位）：

1. `app.py:205-211`：`_build_agent_runtime` 之后、`_build_feishu_bot_supervisor` 处，用 `agent_runtime` 构造 `AgentService(agent_runtime)`（或直接传 runtime，AgentService 薄到可省），new 一个 `FeishuChatDispatcher(credentials, agent_service)`，传给 `FeishuBotSupervisor(credentials, chat_dispatcher=...)`。注意顺序问题：supervisor 构造在 app.py:209，agent_runtime 局部变量在 app.py:205 已可用，天然满足。
2. `supervisor.py`：`__init__` 加 `chat_dispatcher` 参数（可复刻 3c44e27^ 的 `review_callback` 参数形态，Protocol 定义 `bind_loop()`）；`start()` 里 `self._main_loop = asyncio.get_running_loop()`（supervisor.py:63）之后加 `self._chat_dispatcher.bind_loop(self._main_loop)`；`_build_default_connection`（supervisor.py:57-59）把 dispatcher 透传给 `LarkWsConnection`。
3. `LarkWsConnection.__init__`（supervisor.py:147-166）：透传到 `build_event_handler(app_id, app_secret, chat_dispatch=...)`，handlers 闭包捕获 dispatcher。

### reload() 热更新时服务引用是否失效

**不会失效，分两层看：**

- **AgentService/AgentRuntime 引用**：`AgentRuntime` 实例在 lifespan 内**只创建一次**（app.py:205），`reload()`（supervisor.py:74-89）只重建 ws 连接（`_replace_connection`），不触碰 agent_runtime；dispatcher 闭包持有的是同一个 runtime 引用，**永远有效**。agent 配置热更新走的是「重启进程/重建 app」路径，不在 supervisor.reload 射程内。
- **白名单配置**：reload 后新连接重建 handler 闭包，若 dispatcher 每次回调现读 `credentials.feishu_bot()`（复刻 review_callback 的 `_execute` 模式），则白名单变更**即时生效**；若 handler 闭包捕获的是 `FeishuBotConfig.whitelist_open_ids` 快照，reload 后新闭包也会拿到新快照——两条路都对，但**现读模式更稳**（连接存续期间白名单变更不依赖 reload 触发）。

历史证据：3c44e27^ 版 supervisor 的 `review_callback` 注入+`bind_loop` 接线与上述完全同构，且 reload 路径（`_reload_in_thread` → `_replace_connection` → `_build_default_connection` 重新透传 `self._review_callback`）在当时测试覆盖下工作正常（`test_reload_replaces_connection_atomically`，现 test_supervisor.py:149-166 仍验证连接原子替换）。

### 从非主线程调 AgentService 的正确姿势

- **禁止**直接在 SDK 连接线程 `asyncio.run(service.chat(...))`：会新建事件循环跑协程，但 `AgentRuntime.chat` 内部 `to_thread.run_sync` 与 anyio 上下文绑定、且与 lifespan 管理的 harness 生命周期跨循环，属于未验证路径；更重要是会阻塞 SDK 循环（见 lark-oapi-event-structure-mention.md 的 ping 分析）。
- **正确姿势**：`asyncio.run_coroutine_threadsafe(coro, main_loop)` 桥到 FastAPI 主事件循环执行（复刻 review_callback 模式，见 review-callback-thread-bridge.md），主 loop 引用由 `supervisor.start()` 的 `bind_loop` 提供。
- `reply`（lark im_client，同步 HTTP）可从任意线程调用（现状 handlers.py:58-72 已在连接线程用）；多线程并发 reply 的 token 缓存竞态影响可忽略（见 lark-oapi 主题的 Caveats）。

## Caveats / Not Found

- `AgentService` 与 `AgentChatService` Protocol 重复定义（service.py 类 vs dependencies.py:13-14 Protocol）；飞书注入建议用 Protocol 类型注解，避免循环 import。
- `AgentRuntime` 未配置时 `configured` property（runtime.py:60-62）为 False 但 start() 是空操作——dispatcher 不必预检，chat 时自然抛 `AgentNotConfiguredError`。
- dsh 单轮对话本身**没有内置超时**（runtime.py:97 无 timeout 参数）；120s 超时只能在飞书侧 `future.result(timeout=120)` 实现，超时后 dsh 线程内的 `harness.run` 仍会继续跑完（线程泄漏上限：并发提问数 × 单轮时长），MVP 可接受但值得在 design 里注明。
- `AgentService.chat` 返回的 `session_id` 对飞书路径无用处（飞书侧自算 `feishu:{chat_id}:{user_id}` 并回传），忽略返回值第一项即可。
