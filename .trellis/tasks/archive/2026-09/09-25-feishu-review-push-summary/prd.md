# fix(feishu): 候选审核全量推送改每日汇总通知 (#132)

来源：https://github.com/wangyiyang/Reven/issues/132 （经两轮设计拷问与用户达成共识，2026-09-25）

## Goal

收敛飞书候选相关的主动推送：停止「候选审核 n/m」全量卡片推送，候选通知收敛为现有每日汇总中的统计与「打开候选工作台」入口。每位接收人每天最多一条候选相关主动通知。候选数据与审核状态完整保留，工作台审核路径不受影响。

## 背景与根因（已确认）

- `CandidateReviewService.list_pending_review()`（`server/src/reven/rss/review_service.py:30-38`）查询全部 `status=candidate` 且 `review_pushed_at IS NULL` 的候选，无上限、含历史积压。
- `build_review_card_batches()`（`server/src/reven/rss/../integrations/feishu_bot/review_card.py:26-35`）每 10 条一张卡片。
- `ReviewCardPusher._send_batches()`（`server/src/reven/integrations/feishu_bot/review_pusher.py:72-93`）对「批次 × 接收人」双重循环逐张发送，无任何限量。1,000 条积压 = 100 张卡片/接收人。
- 触发点在 `server/src/reven/rss/discovery.py` 的 `_push_review_cards()`，挂在每日 RSS run 末尾的 `finally` 中。

## Requirements（已决策）

### 删除 — 推送链路
1. 删除 `server/src/reven/integrations/feishu_bot/review_card.py`、`review_pusher.py` 整文件。
2. 删除 `discovery.py` 中 `_push_review_cards()` 及其调用；`factory.py` 中 `ReviewCardPusher` 装配与 `ReviewBoard` protocol。
3. 删除 `CandidateReviewService.list_pending_review()` / `mark_review_pushed()`（无生产调用方；REST 路由不使用）。
4. 删除测试 `server/tests/integrations/feishu_bot/test_review_pusher.py`、`test_review_card.py`，改写 `test_discovery.py` 与 `server/tests/e2e/test_rss_discovery_flow.py` 中推送相关断言。

### 修改 — 每日汇总增强（`discovery.py` `_send_summary`）
5. 汇总文案双口径：保留「抓取/新增/候选/异常」统计，追加「待审核共 N 条」（`count(status=candidate)`，含积压）；保留「打开候选工作台」入口；保持纯文本形态（`send_text_to_recipients`）。
6. 去重完全复用现有机制：`rss_discovery_runs.notification_sent_at` + `run_date` 唯一约束 + `RssDiscoveryJob._completed_date` 进程内缓存。不新增去重表/字段/机制。

### 保留不动
7. 入站回调链路（`review_callback.py`、`handlers.py`、WS `supervisor.py`）不删不改——#131 在 PR 中说明「不再发送审核卡片，审核收敛到工作台」后关闭为 obsolete。
8. `rss_items.review_pushed_at` DB 字段保留（不做 DROP COLUMN 破坏性迁移）；spec 中语义标注废弃。

### 文档 / spec 同步
9. `.trellis/spec/reven-server/backend/feishu-app-notification-contract.md`：删除审核推送契约条款（含「汇总失败不阻止审核推送」「部分成功」条款），改写为「每日汇总为唯一候选主动通知」。
10. `.trellis/spec/reven-server/backend/rss-materials-contract.md`：`review_pushed_at` 标注废弃。
11. `docs/runbook.md` §11、`docs/integrations.md`：通知行为说明更新。

### 测试
12. 新增/改写测试断言：1 / 100 / 1,000 条候选场景下同一接收人同一天仅收到 1 条汇总；重复运行与失败重试不重复发送；任何场景零审核卡片发送。

## Acceptance Criteria

- [ ] 1、100、1,000 条待审核候选场景，同一接收人同一天的候选相关主动通知均最多一条（测试断言发送次数 ≤ 1）。
- [ ] 汇总提供准确的双口径候选统计（本次新增 + 待审核总数）和可用的工作台入口，不再出现「候选审核 n/m」卡片。
- [ ] 首次启用、重新启用和大量历史积压不会触发集中补发（推送链路不存在）。
- [ ] 重复运行和发送重试不会让已成功接收的用户重复收到同一汇总。
- [ ] 全部候选仍可在工作台查看和处理，采纳、忽略及已有审核状态不受影响（候选数据与状态零改动）。
- [ ] 大批量、积压与重试场景的消息数量验证测试齐备；文档与 spec 同步更新。
- [ ] server 测试套件全绿，lint / type-check 通过。

## Out of Scope

- 入站卡片回调修复（#131 关闭为 obsolete，不在本任务改代码）。
- 汇总消息升级为 interactive 卡片（保持纯文本）。
- `review_pushed_at` 列的 DB 迁移删除。

## Notes

- 代码现状调查结论见本任务 `research/code-survey.md`（如需要可由实施时补齐；关键路径与行号已在上文列出）。
- 分支：`fix/feishu-review-push-summary`，从 `main` 拉出，单 PR 收尾，PR 描述 `Closes #132` 并说明 #131 处置。
