# 飞书候选审核推送代码现状调查报告（issue #132 修复准备）

**结论先行**：消息轰炸的根因已确认——`list_pending_review()` 无 limit，返回**全部**未推送候选；`_send_batches()` 对「批次 × 接收人」双重循环逐张发卡，**没有任何限速/限量**。现有的「每日汇总」通知（`RssDiscoveryService._send_summary`）已经具备候选统计 + 工作台链接 + `notification_sent_at` 去重，是改造为汇总通知的天然复用点。

---

## 1. `CandidateReviewService.list_pending_review()`

- **实现**：`server/src/reven/rss/review_service.py:30-38`
- **逻辑**：`status == "candidate"` AND `review_pushed_at IS NULL`，按 `published_at DESC NULLS LAST` 排序，**无 LIMIT**（全量返回）：

```python
select(RssItem)
.where(RssItem.status == "candidate", RssItem.review_pushed_at.is_(None))
.order_by(RssItem.published_at.desc().nullslast())
```

- **调用方**：生产环境唯一调用者是 `ReviewCardPusher.push_pending_review()`（`server/src/reven/integrations/feishu_bot/review_pusher.py:62`，经由 `review_pusher.py:25` 的 `ReviewBoard` Protocol）。REST 路由不调用它（网页端候选列表走别的查询）。

## 2. `build_review_card_batches()`

- **位置**：`server/src/reven/integrations/feishu_bot/review_card.py:26-35`
- **批次大小**：`MAX_CANDIDATES_PER_CARD = 10`（`review_card.py:14`）；摘要截断 `SUMMARY_MAX_CHARS = 120`（:15）
- **卡片结构**（`_build_card`，`review_card.py:38-50`）：飞书 interactive card 经典 schema——`config.wide_screen_mode`、蓝色 header（单批标题「候选审核」，多批「候选审核 i/N」）、elements 中每条候选 = `hr` 分隔 + div 段落（加粗标题 zh 优先、摘要、来源、发布日期，:53-61）+ action 行（「采纳」primary /「忽略」danger 按钮，value 携带 `{"action": ..., "item_id": ...}`，:64-82）
- 返回 `ReviewCardBatch(card, item_ids)`（:18-23），`item_ids` 供发送成功后批量标记

## 3. `ReviewCardPusher._send_batches()` 与标记逻辑

- **位置**：`server/src/reven/integrations/feishu_bot/review_pusher.py:72-93`
- **发送循环**：外层 `for batch in build_review_card_batches(items)`，内层 `for open_id in recipients` 逐个 `send_review_card`（:80-83）。**无任何限速、无批次上限、无接收人上限**。异常粒度是「整批」：某批任一接收人失败 → 该批剩余接收人跳过、该批不标记、继续下一批（:84-91）
- **标记时机**：发送**之后**。`_mark_delivered`（:95-107）把所有成功批的 id 交给 `CandidateReviewService.mark_review_pushed()`（`review_service.py:67-72`），单事务 `UPDATE rss_items SET review_pushed_at=utc_now() WHERE id IN (...)`
- **失败重试**：运行时无重试；失败批不标记 → 下次 run 重推（模块 docstring，`review_pusher.py:3-5`）。注意精确语义（见第 5 节）：同日由 `RssDiscoveryJob._completed_date` 内存缓存挡住，实际为「次日重推」，但**进程重启后同日重入会立刻补推未标记候选**（spec 契约明确允许，见第 7 节）
- 任何环节失败只记脱敏日志（provider + 数量 + 异常类型），绝不向上抛

## 4. 现有「每日汇总」通知

- **实现**：`RssDiscoveryService._send_summary()`，`server/src/reven/rss/discovery.py:215-238`
- **触发**：不是独立定时任务——挂在每日 RSS run 末尾。`_notify_if_needed`（`discovery.py:202-213`）在 run 完成（`finished_at` 非空）时检查并发送；调度入口是 `RssScheduleTick`（`server/src/reven/rss/scheduler.py:23-27`，每天 06:00 Asia/Shanghai 后放行，`RUN_AT` 在 :11），由 `BackgroundRunner._loop` 按 `rss_scheduler_interval_seconds` 循环驱动（`server/src/reven/background.py:72-80`）
- **内容结构**（`discovery.py:216-225`）：**已具备候选统计和工作台入口**——

```python
Notification(
    "Reven RSS 每日汇总", "RSS 内容发现",
    f"抓取 {fetched} 条，新增 {new} 条，候选 {candidate} 条，异常 {failure} 个。",
    {"打开候选工作台": candidate_url},  # candidate_url = {public_base_url}/rss/candidates
)
```

  `candidate_url` 在 `server/src/reven/rss/factory.py:93` 和 :119 注入。投递实现 `FeishuNotifier.send`（`server/src/reven/provider_clients.py:128-134`）拼成纯文本经 `send_text_to_recipients` 发给全部白名单
- **去重**：`rss_discovery_runs.notification_sent_at`——发送前检查（`discovery.py:207`），成功后标记（:234-238），失败只记 `notification_error` 不标记（:229-233，允许重入时再试）。叠加两层：run 按日唯一（`run_date` unique，`models.py:47`）+ `RssDiscoveryJob._completed_date` 进程内同日缓存（`factory.py:79, 85-86, 140-146`）
- **接收人配置**：**数据库** `integrations` 表 provider=`feishu_bot` 行——`public_config.whitelist_open_ids` + `public_config.enabled`；`app_id`/`app_secret` 在 `encrypted_secret`（SecretBox 加密）。解析口 `IntegrationCredentials.feishu_bot()`（`server/src/reven/integrations/credentials.py:105-129`），白名单解析 `parse_whitelist`（`server/src/reven/integrations/feishu_bot/config.py:18-21`）。（另有 CI 部署通知走 env `FEISHU_APP_ID/FEISHU_APP_SECRET/FEISHU_NOTIFY_OPEN_IDS`，`scripts/notify_feishu_deploy.py`，与本业务无关）

## 5. RSS 发现 → 审核推送调用链

```
BackgroundRunner._loop  (background.py:72-80, 每 rss_scheduler_interval_seconds)
└─ RssDiscoveryTick → RssDiscoveryJob  (background.py:45 装配)
   └─ RssScheduleTick  (scheduler.py:23-27, 06:00 闸口)
      └─ RssDiscoveryJob.run  (factory.py:84-125)
         │  默认 pusher 在 factory.py:78 构造：
         │  ReviewCardPusher(clients.credentials, CandidateReviewService(factory))
         └─ RssDiscoveryService(..., review_pusher=...)  (factory.py:94 和 :120)
            └─ run() → _notify_if_needed  (discovery.py:202-213)
               └─ finally: _push_review_cards()  (discovery.py:212)
                  └─ pusher.push_pending_review()  (discovery.py:246)  ← 触发点
```

关键：推送在 `finally` 中执行——**汇总失败或汇总已发送都照样推**（`discovery.py:240-248` 吞错记日志）；同日完成的 run 被 `_completed_date` 缓存短路（`factory.py:85-86`），所以稳态是每天一次推送窗口。

## 6. 飞书通知测试文件

| 文件 | 覆盖 |
|---|---|
| `server/tests/integrations/feishu_bot/test_review_pusher.py`（264 行） | 配置缺失/禁用/空白名单/无候选跳过；推送+标记+不重复推（:175-193）；11 候选 × 2 接收人 = 2 批 × 2 = 4 次调用、批次 header（:197-209）；失败批不标记、后续批继续、按发布时间倒序验证重推集合（:212-224）；失败日志脱敏（:227-241）；标记失败只记日志（:255-264） |
| `server/tests/integrations/feishu_bot/test_review_card.py` | 卡片纯函数：分批、批次 header、中英文取舍、120 字截断、来源/日期行、按钮 value 协议 |
| `server/tests/rss/test_discovery.py:171-260` | 推送在汇总后触发；推送失败不影响 run 与汇总标记；汇总失败/已发送仍推卡片 |
| `server/tests/rss/test_review_service.py` | `list_pending_review` 过滤与排序、`mark_review_pushed`、approve/ignore |
| `server/tests/integrations/feishu_bot/test_client.py` | `FeishuBotApiClient` HTTP 层（respx mock）：token、发送、错误脱敏 |
| `test_review_callback.py` / `test_handlers.py` | 入站按钮回调（白名单、幂等 toast）——出方向无关 |
| `test_service.py` / `test_supervisor.py` / `test_app_lifespan.py` | 连接测试、WS 长连接生命周期 |
| `server/tests/e2e/test_rss_discovery_flow.py:91` | 端到端流中断言 `list_pending_review() == []` |

## 7. 相关文档

- `.trellis/spec/reven-server/backend/feishu-app-notification-contract.md` — **最权威的契约**。:13 定义 `ReviewCardPusher.push_pending_review()` 签名；:23-25 行为契约（汇总与审核推送独立尝试；保留同日完成缓存与次日重试节奏、重启同日重入允许；禁止部分成功记为整次成功）
- `docs/runbook.md:280-335` — §11 RSS 内容发现；:322-335「飞书应用机器人配置与 Webhook 退役」（白名单同时用于汇总、审核卡片和按钮授权；:332-333 写明现有重试语义）
- `docs/integrations.md:13, 30-38` — 飞书应用机器人用途与配置说明
- `.trellis/spec/reven-server/backend/rss-materials-contract.md:9` — `review_pushed_at` 语义（仅表示卡片已发送）
- `.trellis/tasks/09-19-conversational-ops/{prd,design,implement}.md` — #119 功能的原始设计（`design.md:36`：「卡片发送成功后标记 review_pushed_at；失败不标记，下次 run 重推」）

## 8. 数据库 review 相关字段

- `rss_items.review_pushed_at`（可空 DateTime tz）— migration `server/migrations/versions/0020_rss_item_review_pushed_at.py:17`；模型 `server/src/reven/rss/models.py:99`。同表还有 `saved_at`（`models.py:98`，migration 0021 引入）、`status`（candidate/saved/ignored，`models.py:84`）
- `rss_discovery_runs.notification_sent_at` / `notification_error` — migration `server/migrations/versions/0007_rss_discovery.py:35-36`；模型 `models.py:55-56`
- **没有**独立的「审核汇总已发送」字段或表。现有去重资产：run 粒度 = `notification_sent_at`；条目粒度 = `review_pushed_at`。若改为「汇总通知」方案，直接在 run 上复用/新增一列即可，无需新表

## 9. #119 功能引入的代码结构

- 引入提交：`044970d feat(server): 飞书机器人对话式运营入口——候选稿审核推送 + 应用配置页面 (#126)`（对应任务 `.trellis/tasks/09-19-conversational-ops/`）；后续 `4999bcd (#130)` 统一应用机器人通知并退役 Webhook、`d4c1a91 (#133/#141)` 重构出 `IntegrationCredentials`/`ProviderClients` seam
- 模块 `server/src/reven/integrations/feishu_bot/`：`client.py`（出站 API）、`config.py`（凭证类型+白名单）、`review_card.py`（卡片构建）、`review_pusher.py`（推送管道）、`review_callback.py` + `handlers.py`（入站按钮回调）、`service.py`（连接测试）、`supervisor.py`（WS 长连接）
- 核心层：`server/src/reven/rss/review_service.py`（飞书机器人、REST 路由、未来 MCP 共用）

## 10. 飞书发送基础设施与重试

- **封装**：`server/src/reven/integrations/feishu_bot/client.py` `FeishuBotApiClient`（纯 httpx，未用 lark SDK 做出站；SDK 仅用于入站 WS）。tenant token 缓存（:35-50，提前 60s 过期）；`send_review_card`（:63-64）/`send_text`（:60-61）/`send_text_to_recipients`（:66-77，逐接收人尽力发送、聚合报错）；统一 `_request_via`（:104-129）：timeout=10s、`trust_env=False`、响应上限 64KB、错误一律转成脱敏的 `FeishuBotApiError`（只带固定提示 + 数字 code，权限码 99991672/99991679 特判）
- **重试逻辑**：**HTTP 层零重试**。唯一的「重试」是业务层语义——失败批不标记 `review_pushed_at`，下次推送窗口（次日 run，或进程重启后的同日重入）随 `list_pending_review` 重新捞出重推；汇总通知同理靠 `notification_sent_at` 留空实现重入重试

---

**对 #132 修复的直接启示**：改为汇总通知时，(a) 候选统计数已可从 `RssRunSummary.candidate_count` 或 `list_pending_review()` 长度取得，工作台链接 `candidate_url` 已注入；(b) 接收人复用 `feishu_bot` 白名单，发送复用 `FeishuBotApiClient.send_text_to_recipients` 或 `send_review_card`（单张汇总卡）；(c) 去重可在 run 上加列或复用 `notification_sent_at` 语义，注意契约 `feishu-app-notification-contract.md:23-25` 规定的「汇总失败不阻止审核推送」「禁止部分成功记整次成功」两条红线需要同步修订。