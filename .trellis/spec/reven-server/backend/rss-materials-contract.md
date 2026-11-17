# RSS 素材采纳契约

## 数据与操作
- RSS 候选条目的唯一权威存储是飞书多维表格（Bitable）；PostgreSQL 不保存条目级候选数据（rss_items 表已删除，见迁移 0029）。
- 候选状态语义：管线写入初值 `candidate`；人工采纳为 `saved`、忽略为 `ignored`。不存在 pending 或其他状态。
- 采纳与忽略收敛在 BitableCandidateStore.set_status，先读后写：读到已是目标态 → 幂等返回原记录不重复写；读到其他非 candidate 状态（含飞书侧并发变更）→ 409 领域冲突，前端提示刷新。Bitable 无条件更新/事务，读与写之间的并发覆盖是设计容忍的固有限制，不做强制覆盖。
- 保存时间以 Bitable 记录「入库日期」字段为准；不存在 saved_at 或推送时间字段。
- 历史重筛能力已取消：筛选只发生在 run 内内存，filtered 分组不落任何存储。

## 管线与失败边界
- discovery 抓取 → 内存筛选（screening_service）→ BitableCandidateWriter 直写；只写 candidate。
- 写入防重三层（Bitable 无数据库级唯一约束，口径为「不产生明显重复」）：run 内 seen-set、按「去重键」字段分批 search 查重、稳定 client_token（`{run_id}:{sha256(dedupe_key)[:24]}`，飞书 64 字符上限内）；同一绑定表的写入经 PG advisory lock（key 含 binding id）串行化。
- 写前预检：九个固定字段齐全且「状态」单选已配置 candidate 选项；不满足时 run 失败并给出修复指引。
- Bitable 写入失败 = run 失败：不推进 source checkpoint、不发成功汇总；run 可整体重试，重试由查重 + client_token 兜底幂等。

## API 与交互
- GET /api/rss/candidates?status=candidate|saved|ignored 直查 Bitable（search 分页，page_token 游标透传）；POST /api/rss/candidates/{record_id}/confirm|ignore 返回 RssCandidateResponse（record_id 为标识）。
- record 不存在返回 404 RSS_CANDIDATE_NOT_FOUND；状态冲突返回 409 RSS_CANDIDATE_NOT_SAVABLE / RSS_CANDIDATE_NOT_IGNORABLE；绑定未配置或飞书不可用返回 503 RSS_CANDIDATES_BINDING_MISSING / RSS_CANDIDATES_UNAVAILABLE，不静默降级为空列表。
- Dashboard 候选/已保存计数与每日汇总「待审核共 N 条」均来自 Bitable search 计数（优先 total，缺失时翻页聚合）；汇总「候选 N 条」为 writer 当轮实际写入数。
- 关键词命中估计（estimate_hits）已随 PG 条目库退役移除，无 API/UI 入口。
- 不需 Notion/GitHub/微信配置，也不进行稿件同步或发布。

## 基础设施
- background.py 只运行 RSS，system_state 使用 rss_discovery 心跳。
- security/outbound.py 保存固定 IP 请求和 Host/SNI 逻辑；RSS 继续校验 HTTPS、地址、重定向和大小。
- notifications.py 提供飞书通知；汇总失败仍记录 RSS run，供后续重试。待审核计数与发送同属汇总失败域：计数失败（绑定缺失/飞书不可用）不标记已发送，随 run 重入重试。
- 迁移 0021 删除旧推送字段及 pushing/pushed 历史记录；不恢复历史资料。
- 迁移 0024 起 RssDiscoveryService 按源分段提交：单源事务包含 fetch+localize+processed_source_ids，
  中断后下轮 running run 跳过已提交源；整批 localize 失败按条目计数入 errors（对齐生产 25-35 条/天口径）；
  翻译失败超 rss_translation_alert_count（默认 10）或 rss_translation_alert_ratio（默认 0.3）触发
  Feishu 告警（每 run 一次，errors 中 translation_alert_sent 标记去重）；
  源连续 rss_source_max_consecutive_failures（默认 3）轮抓取失败自动 enabled=False 并落
  disabled_at/disabled_reason，同时在 errors 中写 source_governance 记录供人工复核。
- 迁移 0029 删除 rss_items 表及全部历史候选数据（不归档、不迁移，用户已确认不可逆）；downgrade 不可恢复，代码级回滚 = revert PR + 升级前的数据库备份。

## 验证
tests/rss/test_bitable_store.py、tests/rss/test_bitable_writer.py、tests/api/test_rss_candidates.py 验证幂等、409 冲突与失败边界；tests/migrations/test_drop_rss_items_migration.py 验证 0029 升级与不可降级。
