# RSS 素材采纳契约

## 数据与操作
- RssItem 是内容发现及素材的单一记录，不复制成稿件或新素材表。
- candidate 可采纳为 saved 并写 saved_at；saved 再次采纳返回原记录且不改变保存时间。
- candidate 可忽略为 ignored；ignored 重复忽略幂等，其余状态不可忽略。
- 采纳与忽略共享 CandidateReviewService，以行锁事务保证并发决策不互相覆盖。
- 重筛必须在提交时重新确认状态，不能覆盖已保存或已忽略的人工决策。
- review_pushed_at 已废弃：飞书审核卡片推送链路已删除（候选通知收敛为每日汇总），字段仅为兼容历史数据保留、不再有写入方，也不是素材保存时间。

## API 与交互
- POST /api/rss/candidates/{id}/confirm 返回完整 RssCandidateResponse，网页候选工作台使用 CandidateReviewService。
- GET /api/rss/candidates?status=saved 返回本地素材；response 包含 saved_at，无 Notion 或外部推送字段。
- missing item 返回 404；非法状态返回 409 RSS_CANDIDATE_NOT_SAVABLE。
- 不需 Notion/GitHub/微信配置，也不进行稿件同步或发布。

## 基础设施
- background.py 只运行 RSS，system_state 使用 rss_discovery 心跳。
- security/outbound.py 保存固定 IP 请求和 Host/SNI 逻辑；RSS 继续校验 HTTPS、地址、重定向和大小。
- notifications.py 提供飞书通知；汇总失败仍记录 RSS run，供后续重试。
- 迁移 0021 删除旧推送字段及 pushing/pushed 历史记录；不恢复历史资料。
- 迁移 0024 起 RssDiscoveryService 按源分段提交：单源事务包含 fetch+localize+持久化+processed_source_ids，
  中断后下轮 running run 跳过已提交源；整批 localize 失败按条目计数入 errors（对齐生产 25-35 条/天口径）；
  翻译失败超 rss_translation_alert_count（默认 10）或 rss_translation_alert_ratio（默认 0.3）触发
  Feishu 告警（每 run 一次，errors 中 translation_alert_sent 标记去重）；
  源连续 rss_source_max_consecutive_failures（默认 3）轮抓取失败自动 enabled=False 并落
  disabled_at/disabled_reason，同时在 errors 中写 source_governance 记录供人工复核。

## 验证
tests/rss/test_review_service.py 与 tests/api/test_rss_candidates.py 验证幂等、并发和状态边界。
