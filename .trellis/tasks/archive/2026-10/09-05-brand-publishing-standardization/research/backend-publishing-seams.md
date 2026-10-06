# 调研：后端发布链路现状（品牌集成接缝）

> 调研时间：2026-09-05，inline 调研（子代理在本环境不可用）。

## 发布编排骨干

- `publishing/orchestrator.py`：`PublicationOrchestrator` 逐渠道交付，`_channel_finished`（:150 附近）跳过已成功渠道（"已上线"/"草稿已生成"/"失败"）→ 现有重试幂等语义。
- 错误三分类：`TransientPublishError`（重抛）/ `BlockedPublishError`（阻塞）/ `PermanentPublishError`（失败），`error_fingerprint` 做去重指纹。
- `publishing/delivery_store.py`：`SqlAlchemyDeliveryStore` 租约隔离持久化，渠道结果写入 `job.blog_result` / `job.wechat_result` JSONB，并 enqueue 飞书通知。

## 任务模型与幂等锚点

- `jobs/models.py:14` `PublicationJob`：`article_id`、`snapshot_id`（FK content_snapshots, RESTRICT）、`content_hash`、`target_channels`/`target_channels_hash`、`source_markdown`、`snapshot_metadata` JSONB、`wechat_html`、状态列、lease 列、`blog_result`/`wechat_result`。
- 唯一约束 `uq_job_article_version_channels` = (article_id, content_hash, target_channels_hash) —— 品牌版本绑定需扩展此键（design 2.4）。
- 部分唯一索引 `uq_one_unfrozen_job_per_article`：content_hash IS NULL 且状态在 等待中/处理中/阻塞 时每稿件至多一个。
- `jobs/repository.py:43` `create_waiting(...)` 是 job 创建唯一入口；`compute_target_channels_hash` (:20) 是渠道哈希算法。
- `domain.py`：`TargetChannel`（个人博客/微信公众号）、`JobStatus`、`AutomationStatus`、`ChannelSelection`。

## 候选组装与校验

- `jobs/preparation_state.py:29` `candidate(...)` 组装 `PublicationCandidate`；`:69` **author 取自微信集成 `public_config.author`**（品牌默认署名要替换的来源，需保留 fallback）。
- `publishing/validation.py` `validate_candidate`：errors（阻塞）+ warnings（提醒）两级结构已存在；封面缺失 `cover_missing` 已是阻塞项。
- 微信限制常量：TITLE 64 / AUTHOR 16 / SUMMARY 120 / BODY 200k。

## 快照与素材表

- `content_sync/models.py`：`ContentSnapshot`（uq: article_id+source_last_edited_at+content_hash）、`SnapshotAsset`（ordinal/kind/embedded/storage_key/public_url/sha256/mime_type/byte_size，kind="封面" 表示封面）。
- `publishing/snapshot.py` `build_snapshot`：content_hash = markdown 规范化 + 图片 sha256 + 封面 sha256。
- `publishing/assets.py`：安全物化（SSRF pinned IP、10MB/文件、50MB/job、MIME 嗅探），`MaterializedAssets.final_view()`。

## 预览与渲染

- `publishing/wechat/preview.py` `ConfiguredWechatPreview.render_current(article_id)`：从当前快照实时渲染（`CurrentSnapshotGate.require`），替换 `reven-asset://sha256/...` 为 public_url 后送渲染器。
- `publishing/wechat/renderer.py` `WechatRenderer.render(markdown)`：子进程调 `renderer/dist/cli.mjs`（bwrap 沙箱、资源限额、4MB 输出上限）。输入协议 `{markdown}`，输出 `{ok, html}`。
- `publishing/wechat/publisher.py` `_Context`（title/author/digest/source_url 来自 job 元数据）；上传图片/封面有 operations_in_flight 幂等保护。

## 博客转换

- `publishing/blog/converter.py` `_frontmatter`：layout/title/date/categories/description/keywords + 一串 mermaid 开关；**当前无 cover/og 字段**。
- 博客模板（wangyiyang.github.io 本地克隆）已验证消费：
  - `page.cover` → `_includes/theme/post-header.html:33-36`（封面图渲染）
  - `page.og_image_url` → `_includes/header.html:87-88`（og:image）与 `_layouts/post.html:30-31`（JSON-LD image）
  - `page.description` → og:description；`keywords` → og:keywords；`site.author` 为站点级（_config.yml:60）

## API 现状

- `api/routes/articles.py`：list/detail/job detail/preview/wechat + portable-markdown + retry + cancel。`JobDetail`/`ChannelResult`/`_validation_items` 是详情与校验结果的出口。
- 迁移约定：`server/migrations/versions/` 数字序号 revision，分支用 merge migration（见 0016），upgrade/downgrade 成对。
