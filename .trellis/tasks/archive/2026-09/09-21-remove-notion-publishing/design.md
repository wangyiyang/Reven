# 技术设计

## 行为与跨层契约
- 稿件发布领域整体退役，RSS 采纳更新现有 rss_items，无新素材表。
- CandidateReviewService(factory).approve(id) -> RssItem：candidate -> saved，写 saved_at。
- saved 重复采纳返回原记录且不改 saved_at；ignore/approve 使用行锁或原子条件保证状态冲突正确。
- POST /api/rss/candidates/{id}/confirm 返回完整 RssCandidateResponse；GET /api/rss/candidates?status=saved 浏览素材。
- 响应移除 notion_page_id/notion_url/push_*，增加 saved_at；review_pushed_at 是飞书审核推送时间，保留。
- 飞书回调与 REST 共用 CandidateReviewService，移除 InboxPusher。
- /api/system/status 返回 database 与 rss_discovery，移除 notion_sync/scheduler。
- provider registry 移除 notion/github/wechat，旧名称按 unsupported 拒绝。

## 模块
- 删除 articles/content_sync/jobs/publishing 及 Notion/GitHub/微信适配器。
- 共用固定 IP 请求能力提取 security/outbound.py 供 RSS；共享通知与飞书 notifier 提取 notifications.py；background.py 仅运行 RSS。
- 品牌素材存储协议独立于 content_sync，品牌档案/模板管理保留，正文模板应用和 VI 导入移除。
- 保留既有 Alembic 链，以新增迁移删除退役表/列和配置；不迁移历史内容。只在隔离本地测试库运行。
- Web 删除稿件路由/导航，RSS 增加已保存素材视图，集成与系统解析遵循新契约。

## 风险与验证
防止误删 RSS 共用网络安全能力、品牌存储能力，确保没有旧后台任务、UI/API 状态差异。历史设计与任务记录保留，当前文档同步新范围。
