# RSS 素材采纳契约

## 数据与操作
- RssItem 是内容发现及素材的单一记录，不复制成稿件或新素材表。
- candidate 可采纳为 saved 并写 saved_at；saved 再次采纳返回原记录且不改变保存时间。
- candidate 可忽略为 ignored；ignored 重复忽略幂等，其余状态不可忽略。
- 采纳与忽略共享 CandidateReviewService，以行锁事务保证并发决策不互相覆盖。
- 重筛必须在提交时重新确认状态，不能覆盖已保存或已忽略的人工决策。
- review_pushed_at 仅表示飞书审核卡片已发送，不是素材保存时间。

## API 与交互
- POST /api/rss/candidates/{id}/confirm 返回完整 RssCandidateResponse，网页与飞书共用领域服务。
- GET /api/rss/candidates?status=saved 返回本地素材；response 包含 saved_at，无 Notion 或外部推送字段。
- missing item 返回 404；非法状态返回 409 RSS_CANDIDATE_NOT_SAVABLE。
- 飞书保留允许用户校验、事件去重和重放处理；成功反馈为已保存素材。
- 不需 Notion/GitHub/微信配置，也不进行稿件同步或发布。

## 基础设施
- background.py 只运行 RSS，system_state 使用 rss_discovery 心跳。
- security/outbound.py 保存固定 IP 请求和 Host/SNI 逻辑；RSS 继续校验 HTTPS、地址、重定向和大小。
- notifications.py 提供飞书通知；汇总失败仍记录 RSS run，供后续重试。
- 迁移 0021 删除旧推送字段及 pushing/pushed 历史记录；不恢复历史资料。

## 验证
tests/rss/test_review_service.py 与 tests/api/test_rss_candidates.py 验证幂等、并发和状态边界；
tests/integrations/feishu_bot/test_review_callback.py 验证授权与真实领域服务接入。
