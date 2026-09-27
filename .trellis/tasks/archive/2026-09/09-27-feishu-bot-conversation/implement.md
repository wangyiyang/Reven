# 飞书机器人接入 Agent 对话 · 实施计划

> 依据 `prd.md` + `design.md` + `research/`。顺序按「纯逻辑 → 桥接 → 装配 → 前端文案」自底向上，每步可独立验证。

## 前置

- [ ] 0.1 从 main 拉功能分支 `feat/feishu-bot-conversation`（GitHub Flow，禁止直接在 main 上改）
- [ ] 0.2 人工确认（用户）：飞书开放平台该应用事件订阅对群聊 @ 消息生效；不阻塞编码，但阻塞最终验收

## 实施步骤

### 1. `client.py`：bot open_id 获取

- [ ] 1.1 `FeishuBotApiClient` 新增 `async get_bot_open_id() -> str`，复用 `verify_bot()` 同一端点（`client.py:10` `BOT_INFO_URL`）与 tenant token 缓存，解析 `{"bot": {"open_id": ...}}`
- [ ] 1.2 `test_client.py` 补 respx 用例：正常解析 / 非 0 code 抛错（异常串不含 token）
- 验证：`uv run pytest server/tests/integrations/feishu_bot/test_client.py -q`

### 2. `chat_dispatcher.py`（新建）：线程桥 + 工作线程编排

- [ ] 2.1 模块常量：`_CHAT_TIMEOUT_SECONDS = 120.0`、预检超时 10s、四条文案（引导 / 思考中… / 兜底 / 暂只支持文字）
- [ ] 2.2 本地 `AgentChatService` Protocol（`async chat(message, session_id) -> tuple[str, str]`）
- [ ] 2.3 `FeishuChatDispatcher`：`bind_loop()` / `submit()`（立即返回，daemon 线程 `feishu-chat-worker`）/ 工作线程编排（预检桥 → 白名单静默 / 思考中 / chat 桥 120s → 结果或兜底）/ 主循环协程（白名单现读 `credentials.feishu_bot()`、session_id 拼接、AgentError 透传为兜底）
- [ ] 2.4 错误纪律：`run_coroutine_threadsafe` 失败 `coro.close()`；任何异常不向 SDK 抛；脱敏日志
- [ ] 2.5 新建 `test_chat_dispatcher.py`：复刻 `git show 3c44e27^:server/tests/integrations/feishu_bot/test_review_callback.py` 桥接范式（bind_loop + `asyncio.to_thread`、dead loop、超时注小值、AgentError 矩阵、非白名单零 reply、白名单 db 现读）
- 验证：`uv run pytest server/tests/integrations/feishu_bot/test_chat_dispatcher.py -q`

### 3. `handlers.py`：路由纯函数 + 处理器改造

- [ ] 3.1 `route_message(sender, message, bot_open_id)` 纯函数：按 design「消息路由」契约实现（user 过滤 / p2p / group mention 判定 / mention 占位符剥离 / 非 text / 畸形 JSON 兜底）
- [ ] 3.2 `build_event_handler()` 增加 `bot_open_id`、`chat_dispatch` 参数；处理器改为「路由 → submit → 立即返回」；删除固定引导文案逻辑
- [ ] 3.3 `test_handlers.py` 重写路由矩阵 8 用例（`bot_open_id` 参数注入，`ReplyRecorder` 范式保留）；更新 `test_handlers.py:110-114` 注册断言口径
- 验证：`uv run pytest server/tests/integrations/feishu_bot/test_handlers.py -q`

### 4. `supervisor.py`：注入与 bind_loop

- [ ] 4.1 `__init__` 增加 `chat_dispatcher` 参数；`start()` async 段 `get_bot_open_id()`（失败 → `None` + warning 日志，群聊降级忽略、私聊正常）并 `dispatcher.bind_loop(main_loop)`；`_build_default_connection` 透传 `bot_open_id` + dispatcher；reload 时 `bot_open_id is None` 则重试获取
- [ ] 4.2 `test_supervisor.py`：bind_loop 触发断言、reload 后新连接持同一 dispatcher、open_id 失败降级；更新 `test_supervisor.py:244-253` 断言口径
- [ ] 4.3 `test_app_lifespan.py`：FakeSupervisor 构造签名跟随
- 验证：`uv run pytest server/tests/integrations/feishu_bot/ -q`

### 5. `app.py`：装配

- [ ] 5.1 `_build_feishu_bot_supervisor()` 增加 `agent_runtime` 参数；构造 `AgentService(agent_runtime)` + `FeishuChatDispatcher(credentials, agent_service)` 传入 supervisor；lifespan 调用点（`app.py:209-211`）传入局部变量
- 验证：`uv run pytest server/tests/integrations/feishu_bot/test_app_lifespan.py -q`

### 6. web：白名单文案

- [ ] 6.1 `web/src/features/integrations/` 飞书应用卡片 whitelist 字段 label/帮助文案改为「可使用机器人的用户（每日通知接收 + 对话）」语义；无行为变更
- 验证：`cd web && pnpm lint && pnpm test`（按 web 现有脚本）

### 7. 全量验证（Review Gate）

- [ ] 7.1 `uv run ruff check server && uv run ruff format --check server`
- [ ] 7.2 `uv run mypy server/src`（strict）
- [ ] 7.3 `uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80 -m 'not dsh_runtime'`
- [ ] 7.4 web lint/test 全绿

### 8. 端到端验收（真实飞书，需用户配合）

- [ ] 8.1 私聊提问 → 思考中… → 答案；追问接上下文
- [ ] 8.2 群聊 @ 提问 / 不@ 无响应 / 两人上下文隔离；空@ → 引导文案
- [ ] 8.3 白名单外用户静默；图片 → 暂只支持文字
- [ ] 8.4 配置页改白名单保存后不重启即时生效；LLM 凭证配错 → 兜底文案 + 日志完整

## 回滚点

- 步骤 1-6 均为独立 commits 候选（原子提交）；任一步验证失败 → revert 该步 commit 重做工序
- 整体回滚 = revert 本任务全部 commits，机器人退回固定引导文案，无残留状态

## 备注

- 真实 ws 连接、真实 dsh 不进单测（沿用现有基座）；`-m 'not dsh_runtime'` 必须全绿
- 飞书平台侧若群聊事件不可达（前置 0.2 未过），代码仍应合并——群聊分支自然静默，私聊功能完整可用
