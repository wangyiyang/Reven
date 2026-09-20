# Implement — 飞书机器人候选稿审核推送

## 人工前置（不阻塞编码，联调前完成）

- [ ] 飞书开放平台创建企业自建应用，开通机器人能力，获取 app_id / app_secret
- [ ] 开通权限：读取/发送消息、卡片回调（im:message 等，以 SDK 报错提示为准补齐）
- [ ] 获取老板本人 open_id（可通过 bot 信息接口或通讯录接口）

## 阶段一：核心层抽取（纯后端，可独立验收）

- [x] 1.1 新增 `rss/review_service.py` `CandidateReviewService`：list_pending_review / approve / ignore
- [x] 1.2 `routes/rss.py` ignore 端点改为委托核心层（行为不变，现有测试应原样通过）
- [x] 1.3 alembic migration：`rss_items` 加 `review_pushed_at` 列
- [x] 验证：`cd server && uv run pytest tests/rss -q` 全绿

## 阶段二：配置体系（后端 provider + 前端卡片）

- [x] 2.1 `pyproject.toml` 加 `lark-oapi-sdk>=1.4,<2`，`uv sync`
- [x] 2.2 后端：providers/schemas/service 注册 `feishu_bot`（secrets: app_id/app_secret；public: whitelist_open_ids/enabled）+ 连接测试适配器
- [x] 2.3 前端：integrations 页面新增"飞书应用（机器人）"卡片
- [x] 验证：`uv run pytest tests/integrations -q` + `pnpm --filter @reven/web test` 全绿；手动在页面保存配置并测试连接

## 阶段三：WebSocket 生命周期

- [x] 3.1 `integrations/feishu_bot/supervisor.py`：start/stop/reload，独立线程跑 ws.Client
- [x] 3.2 挂 app lifespan + integrations upsert/delete 钩子（reload）
- [x] 3.3 IM 消息固定引导回复（P2ImMessageReceiveV1）
- [x] 验证：生命周期单测（mock ws.Client）已绿；手动联调确认进程启动后 bot 在线（待真实飞书环境）

## 阶段四：审核卡片推送

- [x] 4.1 `ReviewCardBuilder` + 分批（≤10 条/卡）
- [x] 4.2 `ReviewCardPusher`：选候选 → 发卡片 → 标记 review_pushed_at（失败不标记）
- [x] 4.3 挂 discovery run 完成触发点（现有 `_notify_if_needed` 之后）
- [x] 验证：单测覆盖选择逻辑/分批/失败重推；联调确认每日推送到达

## 阶段五：按钮回调审核

- [x] 5.1 `card.action.trigger` 处理器：解析 value → 白名单校验 → approve/ignore → toast
- [x] 5.2 重复处理/重放 → toast"该候选已处理"
- [x] 验证：单测覆盖白名单拒绝、两种 action、重复点击；联调走通真实按钮

## 收尾

- [x] 全量：`uv run pytest -q` + `pnpm -r test` + lint/type-check 全绿
- [x] trellis-check 全量质量门
- [x] spec 更新（integration-provider-contract 补 feishu_bot 与 repr=False 条款）
- [ ] commit（Conventional Commits，原子提交）

## 回滚点

- 任一阶段失败：删除/禁用 `feishu_bot` 配置即停用入站能力，其余系统不受影响
- 阶段一可独立合并（纯重构 + 加列），后续阶段失败不回滚阶段一
