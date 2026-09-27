# Research: 已删除的 review_callback.py 线程桥模式

- Query: 恢复 commit 3c44e27 删除的 review_callback.py，总结「SDK 连接线程同步 handler → FastAPI 主事件循环 async 服务」的桥接模式与可复刻骨架
- Scope: internal（git 历史）
- Date: 2026-09-27

## Findings

### 历史定位

- 删除提交：`3c44e27 chore(feishu): 清理不可达的审核卡片回调代码 (#146) (#149)`（2026-09-26），一次性删除 `review_callback.py`（142 行）+ `test_review_callback.py`（344 行），并把 supervisor/handlers/app.py 中的接线剥掉。
- 恢复命令：`git show 3c44e27^:server/src/reven/integrations/feishu_bot/review_callback.py`（本文件全部代码引自该版本）。
- 同一提交前版本的 supervisor/handlers/app.py 也可用 `git show 3c44e27^:<path>` 查看接线。

### 桥接核心：ReviewCallbackDispatcher（3c44e27^:review_callback.py:99-142）

当年模式四要素：

1. **构造时注入 async 服务 + credentials seam**（同步对象，可被任意线程持有）：

   ```python
   class ReviewCallbackDispatcher:
       def __init__(self, credentials: IntegrationCredentials,
                    executor: ReviewActionExecutor,          # async 核心服务（Protocol）
                    *, timeout_seconds: float = 10.0) -> None:
           self._credentials = credentials
           self._executor = executor
           self._timeout_seconds = timeout_seconds
           self._main_loop: asyncio.AbstractEventLoop | None = None
   ```

2. **`bind_loop()`：supervisor.start() 时绑定主事件循环**（进程生命周期内不变）：

   ```python
   def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
       self._main_loop = loop
   ```

3. **同步 `__call__` 内 `asyncio.run_coroutine_threadsafe` + `future.result(timeout)`**（SDK 线程视角是同步函数）：

   ```python
   def __call__(self, action, item_id, operator_open_id):
       loop = self._main_loop
       if loop is None:
           return TOAST_FAILED                       # 未绑定：兜底，不抛
       coro = self._execute(action, item_id, operator_open_id)
       try:
           future = asyncio.run_coroutine_threadsafe(coro, loop)
       except Exception:
           coro.close()                              # 关键：调度失败必须 close 未 await 的协程
           return TOAST_FAILED
       try:
           return future.result(timeout=self._timeout_seconds)
       except Exception:
           return TOAST_FAILED                       # 超时/服务异常统一兜底，绝不向 SDK 抛
   ```

4. **主循环内执行的 `_execute` 协程按需读最新配置**（白名单热更新不重启连接）：

   ```python
   async def _execute(self, action, item_id, operator_open_id):
       config = await self._credentials.feishu_bot()          # 每次回调读最新配置
       whitelist = config.whitelist_open_ids if config is not None else ()
       return await run_review_action(self._executor, whitelist, ...)
   ```

### 当年 supervisor / app.py 的接线（3c44e27^ 版）

- **supervisor 构造注入 + start 时绑 loop**（3c44e27^:supervisor.py）：

  ```python
  class FeishuBotSupervisor:
      def __init__(self, credentials, *, connection_factory=None,
                   review_callback: ReviewCallback | None = None):   # Protocol: bind_loop()
          self._review_callback = review_callback
          ...
      async def start(self) -> None:
          self._main_loop = asyncio.get_running_loop()
          if self._review_callback is not None:
              self._review_callback.bind_loop(self._main_loop)      # ← 主 loop 引用在此传递
          ...
      def _build_default_connection(self, credentials):
          return LarkWsConnection(credentials, review_callback=self._review_callback)
  ```

- **LarkWsConnection → build_event_handler(review_dispatch=...) → handlers 闭包**（3c44e27^:handlers.py:120-141）：`build_event_handler(app_id, app_secret, *, review_dispatch=None)`，非 None 时 `builder.register_p2_card_action_trigger(build_review_action_handler(review_dispatch))`。处理器内 `dispatch(action, item_id, open_id)` 同步调用并包 try/except（`handlers.py:88-105`），结果映射为 toast response。
- **app.py 装配点**（3c44e27^:app.py，`_build_feishu_bot_supervisor`）：

  ```python
  review_callback = ReviewCallbackDispatcher(credentials, CandidateReviewService(factory))
  supervisor = FeishuBotSupervisor(credentials, review_callback=review_callback)
  current_app.state.feishu_bot_supervisor = supervisor
  ```

### 纯逻辑与桥接分离：`run_review_action`（3c44e27^:review_callback.py:69-96）

白名单校验 + 核心层调用 + 错误映射全部放在一个**纯 async 函数**里，dispatcher 只负责桥接。错误纪律：

- `operator_open_id is None or not in whitelist` → 直接拒绝，不碰核心层；
- 领域错误按 status_code 映射幂等 toast（404/409 → 「已处理」）；
- 任何未知异常 → 记 `provider + type(exc).__name__` 脱敏日志，返回兜底 toast；
- 配置缺失/禁用 → 视为空白名单。

### 对本次需求的复刻骨架（飞书对话分发器）

> ⚠️ 一个关键差异必须改：当年 `future.result(timeout=10)` 的阻塞发生在 **SDK 连接事件循环** 内（`ws/client.py:341` 同步调 handler），10s 可忍；本次 Agent 超时 120s，而 SDK 的 ping 循环（`ws/client.py:177-191`，`_ping_interval=120`）跑在同一循环上——**在 handler 里阻塞 120s 会心跳超时掉线**。所以 handler 必须「立即返回」，把等待挪到独立工作线程。

```python
class FeishuChatDispatcher:
    """SDK 连接线程同步调用；把 chat 协程桥到主事件循环，工作线程内等待并回消息。"""

    def __init__(self, credentials: IntegrationCredentials,
                 agent_service: AgentChatService,                # Protocol: async chat(message, session_id)
                 *, timeout_seconds: float = 120.0) -> None:
        self._credentials = credentials
        self._agent = agent_service
        self._timeout = timeout_seconds
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:  # supervisor.start() 时调用
        self._main_loop = loop

    # handlers 同步调用；立即返回，不阻塞 SDK 循环
    def submit(self, *, reply: MessageReplier, message_id: str,
               chat_id: str, open_id: str, text: str) -> None:
        loop = self._main_loop
        if loop is None:
            return
        threading.Thread(target=self._run, args=(loop, reply, message_id, chat_id, open_id, text),
                         daemon=True, name="feishu-chat-worker").start()

    def _run(self, loop, reply, message_id, chat_id, open_id, text) -> None:
        try:
            reply(message_id, "思考中…")                       # 同步 HTTP，先回占位
        except Exception:
            return                                             # 占位都发不出就直接放弃
        coro = self._chat(chat_id, open_id, text)
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:
            coro.close()                                       # 防止协程泄漏 RuntimeWarning
            self._safe_reply(reply, message_id, "出了点问题，请稍后重试")
            return
        try:
            answer = future.result(timeout=self._timeout)      # 工作线程内等，最多 120s
        except Exception:
            self._safe_reply(reply, message_id, "出了点问题，请稍后重试")
            return
        self._safe_reply(reply, message_id, answer)

    async def _chat(self, chat_id: str, open_id: str, text: str) -> str:
        config = await self._credentials.feishu_bot()          # 主循环内读最新白名单
        if config is None or open_id not in config.whitelist_open_ids:
            raise _Forbidden                                   # 或返回哨兵，映射为静默忽略
        session_id = f"feishu:{chat_id}:{open_id}"
        _, response = await self._agent.chat(text, session_id)
        return response
```

复刻要点 checklist：
- [ ] 构造注入 `credentials` + async 服务实例；`bind_loop()` 由 supervisor.start() 调用（现状 `supervisor.py:63` 已存 `self._main_loop`，加一行 bind 即可）。
- [ ] `run_coroutine_threadsafe` 失败必须 `coro.close()`。
- [ ] 所有异常收敛为兜底文案/日志，绝不向 SDK 抛（handlers.py 现有纪律：`handlers.py:44-45`）。
- [ ] 白名单在主循环内每次现读（`credentials.feishu_bot()`），reload 热更新天然生效、不依赖 handler 闭包里的配置快照。
- [ ] 等待放独立 daemon 线程，handler 立即返回（与当年 10s 阻塞模式的最大差异）。
- [ ] `AgentService.chat` 的 `AgentNotConfiguredError`/`AgentRuntimeError` 在 `_chat` 里映射为兜底文案（见 agent-service-assembly.md）。

## Caveats / Not Found

- 当年 dispatcher 是**每个事件字段拆包**的 `__call__(action, item_id, open_id)` 协议；本次消息字段多（message_id/chat_id/open_id/text/reply 回调），建议如骨架改用 `submit(**kwargs)` 或 dataclass 上下文，避免 Protocol 签名爆炸。
- 当年工作线程等待模式没被采用过（10s 直接阻塞 SDK 循环），120s 必须改；骨架中的「思考中…先回」也意味着 reply 同步 HTTP 仍在 SDK 连接线程执行一次（耗时 <1s，可接受），或挪进工作线程亦可——两种都满足不阻塞原则，设计时择一并写清。
- git 历史中该文件仅此一个生命周期版本（b3aedff 引入 → 3c44e27 删除），无更多演进可参考。
