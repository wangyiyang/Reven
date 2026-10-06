# 调研：前端 / 素材存储 / Notion 集成现状

> 调研时间：2026-09-05，inline 调研。

## 前端结构

- 路由：react-router-dom，`web/src/app.tsx` 集中式路由表；`AppShell` 包裹功能页。
- 导航：`web/src/components/app-shell.tsx:45` `navigation: NavEntry[]` 数组（NavLeaf/分组 children），新增「品牌与发布」入口挂这里。
- UI 体系：`web/src/components/ui/` 为 shadcn 风格组件（badge/button/card/dialog/input/label/select/separator/skeleton/table/tabs/textarea/tooltip）。
- 主题：`web/src/lib/theme.ts`（getTheme/toggleTheme），工作台蓝灰主题规范见 `.trellis/spec/web/frontend/brand-vi.md`（Active）——品牌色只进渠道产物，不动工作台主题。
- 稿件详情：`features/articles/article-detail-page.tsx` + `wechat-preview.tsx` / `publication-guidance.tsx` / `channel-timeline.tsx` / `article-status.tsx`；`response-parsers.ts` + `types.ts` 管 API 契约。
- 设置页参考模式：`features/integrations/`（page + controller hook `use-integrations-controller.ts` + card + api 封装）——品牌设置页照此模式。

## 素材存储

- `content_sync/media_archive.py`：`ContentAssetStore` Protocol（`archive(content, sha256, mime_type) -> ArchivedAsset`），`ContentMediaArchive` 编排下载+归档。
- `integrations/tencent_cos/store.py` `TencentCosAssetStore`：COS 实现，`archive`/`verify`/`verify_connection`；`build_tencent_cos_asset_store(settings)` 工厂。品牌素材直接复用此路径。
- 快照素材的 public_url 即 COS 地址（`SnapshotAsset.public_url`/`storage_key`）。

## Notion 集成能力

- `integrations/notion/client.py`：`retrieve_page(page_id)`、`retrieve_page_markdown(page_id)`、`query_data_source`、`create_page`、`update_page` 等 —— **拉取 VI Hub 页面可行**（markdown 内含图片 URL，可经 media_archive 归档）。
- `mapper.py`：面向稿件数据库的属性映射（title/status/select/cover 等），VI Hub 迁移不走此 mapper，需单独的章节解析。
- `integrations/repository.py` + `models.py`：`Integration` 单例-per-provider 配置模式（get_by_provider/save）——品牌档案不套用此模式（需要版本化），但 API 分层可参照。
- `sops/` 模块：`Sop` 模型 + repository（list/get/create/update/delete）——AI 生图/Prompt Kit SOP 已在此，品牌迁移只引用不搬迁。

## 封面流转现状

- Notion 页封面 → `mapper._read_cover` → `candidate.cover = assets.cover`（物化后）→ job `snapshot_metadata["cover"]`（service.py:430-437 含 original_url/path/sha256/mime/size）。
- `Article.cover_metadata` JSONB（articles/models.py:25）存封面展示信息。
- 品牌素材作封面的注入点：preparation 阶段若用户已选品牌素材封面，则替代 Notion 封面进入物化流程（下载 COS→本地 workspace，走 assets.py 安全下载）。
