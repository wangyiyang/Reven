# Design — 飞书机器人候选稿审核推送

## 分层

```
┌─ 协议适配层（新增，integrations/feishu_bot/）─────────────
│  FeishuBotSupervisor   ws.Client 生命周期（start/stop/reload）
│  事件处理器            card.action.trigger 回调、IM 帮助回复
│  ReviewCardBuilder     候选稿交互卡片构建
│  ReviewCardPusher      每日审核卡片推送管道
├─ 核心层（领域操作，与飞书 SDK 零耦合）────────────────────
│  CandidateReviewService（新增，rss/）
│    list_pending_review() / approve(item_id) / ignore(item_id)
│  RssInboxService（现有，confirm→pushing→pushed→Notion）
├─ 配置层（现有体系扩展）──────────────────────────────────
│  integrations provider: feishu_bot（secrets + public_config）
│  连接测试适配器、前端 integrations 页面新卡片
└─ 触发点（现有）──────────────────────────────────────────
   discovery._notify_if_needed：run 完成后挂审核卡片推送
```

## 关键设计

### 1. 核心层抽取

- 新增 `rss/review_service.py` `CandidateReviewService`：
  - `list_pending_review()` → `status=candidate AND review_pushed_at IS NULL`
  - `approve(item_id, operator)` → 委托现有 `RssInboxService.push`（状态机防护已有）
  - `ignore(item_id, operator)` → 现 `api/routes/rss.py` 中 ignore 逻辑**下沉**到此（路由层改为委托，行为不变）
- 领域错误沿用现有 `InboxPushError` 风格；bot 适配层捕获后映射为 toast 文案。

### 2. 推送选择与新列

- `RssItem` 新增 `review_pushed_at: datetime | None`（alembic migration）。
- 推送集合 = 全部 `candidate` 且未推送过（含历史积压，不仅本次 run 新增）。
- 卡片发送成功后标记 `review_pushed_at`；失败不标记，下次 run 重推。
- 幂等：按钮回调时 `status != candidate` → toast"该候选已处理"，不报错（飞书重试/重复点击天然被状态机拦截）。

### 3. 卡片与按钮协议

- 一条候选一个卡片段落：标题（title_zh 优先）、摘要截断、来源、发布时间 +「采纳」「忽略」按钮。
- 按钮 `value = {"action": "approve"|"ignore", "item_id": "<uuid>"}`；回调解析后调核心层。
- 每卡最多 10 条候选，超出分批多卡（避免单卡超长）。
- 现有 webhook 每日汇总通知**不动**，审核卡片是独立新增通道。

### 4. WebSocket 生命周期（FeishuBotSupervisor）

- `lark_oapi.ws.Client(app_id, app_secret, event_handler=...)`，`start()` 阻塞 → 独立线程运行，SDK 内建重连。
- 挂 FastAPI lifespan：启动时读 DB 配置，有凭证且 enabled → 起线程；关闭时 stop。
- 热更新：integrations upsert/delete `feishu_bot` 时调用 `supervisor.reload()`（原子替换：停旧连新，单进程单连接）。
- 事件处理器内需要 async DB 操作 → `asyncio.run_coroutine_threadsafe` 桥回主事件循环。
- 注册事件：`card.action.trigger`（审核按钮）；`P2ImMessageReceiveV1` 仅回固定引导文案（"请在每日推送卡片上完成审核"），不做指令系统。
- 安全：白名单 open_id 校验（写操作硬门槛）；长连接由 SDK 凭证认证，不配 encrypt key。

### 5. 配置 provider: feishu_bot

- secrets：`app_id`、`app_secret`；public_config：`whitelist_open_ids: list[str]`、`enabled: bool`。
- 连接测试适配器：调 `tenant_access_token` 接口验证凭证 + 拉 bot 信息。
- 前端：integrations 页面新增卡片，复用现有 definition/controller/card 组件体系。
- 依赖：`server/pyproject.toml` 增加 `lark-oapi-sdk>=1.4,<2`。

### 6. 按钮回调的耗时

- 采纳路径同步执行（推 Notion 通常 <3s，满足飞书回调时限），toast 反馈成功/失败。
- 若联调发现超时，再降级为"先 ack + 后台任务"——初版不做（YAGNI）。

## 影响面

- server：新增 `integrations/feishu_bot/` 子系统、`rss/review_service.py`；改动 `routes/rss.py`（ignore 下沉）、discovery 通知挂载、integrations providers/schemas、app lifespan；alembic migration 一列。
- web：integrations 页面一张新卡片 + 类型/api 扩展。
- 现有 REST API、Web UI 其余页面、webhook 出站通知：不变。

## 风险与回滚

- 需真实飞书环境联调（应用创建、权限、open_id）——列为实施计划人工步骤。
- SDK 线程与 asyncio 桥接是新代码路径，生命周期用 mock ws.Client 单测覆盖。
- 回滚：`feishu_bot` 配置删除/禁用即停用全部入站能力；`review_pushed_at` 列可留空无害。
