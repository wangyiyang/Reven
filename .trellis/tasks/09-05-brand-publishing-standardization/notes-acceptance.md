# 验收审计：AC1–AC11 对照（Issue #46）

> 审计时间：随阶段 E 收尾。本地环境无真实 Notion/COS/微信/博客凭据，
> 标注「部署环境复核」的条目需在部署环境以代表性稿件做最终确认；
> 其余条目均有自动化测试守护（722 passed / ruff / mypy / web 169 / renderer 39）。

## AC 逐条核验

| AC | 结论 | 证据 |
|---|---|---|
| AC1 品牌档案+双渠道默认模板配置后无需逐篇重复录入 | ✅ 测试守护 | `tests/api/test_brand.py`（档案/模板草稿→发布流转）；冻结测试 `tests/jobs/test_brand_freeze.py` 验证任务创建即绑定版本，后续交付不再录入署名/handle/文末信息 |
| AC2 修改启用默认署名后新发布应用更新，历史保持原版本 | ✅ 测试守护 | published 版本不可变（部分唯一索引+归档流转，`test_brand.py`）；`test_brand_freeze.py` 验证重试沿用冻结 FK；署名优先级 品牌>集成>Notion（`test_brand_delivery.py`） |
| AC3 代表性稿件套用微信排版/文末模块/博客品牌字段且不去重追加 | ✅ 测试守护 + 部署环境复核 | `tests/brand/test_application.py`（dedup 三态：追加/跳过/不确定提醒）；`test_converter_brand.py`（cover/og/author）；真实稿件渲染效果需部署环境目视确认 |
| AC4 博客封面与 OG 输出符合模板映射；微信草稿正确封面与排版 | ⚠️ 部署环境复核 | 博客模板消费点已在调研期验证（`_includes/theme/post-header.html` 消费 `page.cover`、`_includes/header.html`+`_layouts/post.html` 消费 `page.og_image_url`）；converter 测试验证字段写入。真实博客 PR 与微信草稿需部署环境确认 |
| AC5 预览与交付同一组内容和配置；变化后旧预览失效 | ✅ 测试守护 | 预览与交付共用 `apply_wechat_template`（同一纯函数+调用方传入 embedded_sha256 保证两种图片表示下去重一致）；预览响应携带版本指纹（`test_articles_brand.py`）；前端 BrandPanel 展示冻结 vs 当前版本漂移并提示重新生成（`brand-panel.test.tsx`） |
| AC6 必需封面缺失/素材不可读/渠道硬约束 → 阻塞+原因+处理入口 | ✅ 测试守护 | `cover_missing` 沿用既有阻塞；`brand_asset_unreadable` error（validation.py）；文末冻结文件缺失 → `BlockedPublishError`（`test_brand_delivery.py`）；校验项携带 field，前端映射设置页入口 |
| AC7 推荐性问题提醒后继续；主观审美不硬阻塞 | ✅ 测试守护 | `cover_aspect_ratio`/`footer_*`/`brand_not_configured` 均为 warning；style_notes 仅展示不校验（application.py 无相关 error 路径） |
| AC8 发布详情可追溯品牌/模板/素材版本；品牌升级后重试旧任务用原版本 | ✅ 测试守护 | JobDetail 暴露 `brand_binding_key`+`brand` 版本指纹；`metadata["footer_assets"]` 记录素材 sha256；retry 路径不重新解析品牌（冻结测试） |
| AC9 旧任务无品牌字段仍可查看和按原行为重试 | ✅ 测试守护 | `brand_binding_key` 非空默认 `'legacy'`（迁移 0017 回填）；`resolve_brand_config` 返回 None 时全链路 legacy；renderer 不传 theme 字节级回归（`render-theme.test.ts`） |
| AC10 Notion 迁移 dry-run/幂等/计数核对；草稿不自动生效 | ✅ 测试守护 | `tests/brand/test_migration.py`（dry-run 零写入、execute 幂等返回既有 run、已有草稿不覆盖、失败运行脱敏记录）+ `tests/api/test_brand_import.py`（dry-run/execute/幂等/未配置 409）；迁移仅产出 status=草稿 |
| AC11 实施前后代表性发布步骤对比 | 见下 | 基于流程盘点（真实计时需部署环境复核） |

## AC11 实施前后步骤对比（代表性稿件：博客+公众号双渠道）

### 实施前（每篇稿件）

1. 在 Notion 完成正文与封面。
2. 同步到 Reven，检查封面（缺失则手动找图）。
3. 微信侧：确认署名（取自微信集成配置，与品牌资料脱节，改动需进设置页改集成）。
4. 手动在正文末尾维护「欢迎关注+二维码」模块（逐篇复制粘贴，易重复或漏更）。
5. 微信预览目视检查排版（样式硬编码，改色需改代码）。
6. 博客侧：无封面/OG 字段输出，需发布后在博客仓库人工补 frontmatter。
7. 交付后无法追溯本次用了哪版署名/模板。

**人工处理步骤：≈6 步/篇，其中重复录入点 4 处（署名、handle、文末模块、博客品牌字段）。**

### 实施后（每篇稿件）

1. 在 Notion 完成正文与封面（不变）。
2. 同步到 Reven；封面缺失时从品牌素材库直接选择（一次性上传的素材）。
3. 创建发布任务即自动冻结当前品牌版本：微信排版主题、署名、文末模块自动套用；博客 cover/og_image_url/author 自动生成。
4. 预览与实际交付同一配置，校验问题分级展示并带处理入口。
5. 交付；发布详情可追溯品牌/模板/素材版本。

**人工处理步骤：≈2 步/篇（写稿+确认预览），重复录入点 0 处。**
品牌资料维护（改署名/换二维码/调色）为低频操作，集中在「品牌与发布」设置页，改一次对后续所有新发布生效。

## 部署环境复核清单（E1 收尾用）

- [ ] 真实 VI Hub 执行 dry-run → 核对 report 计数与 skipped → execute → 核对草稿内容后手动发布
- [ ] 代表性稿件双渠道交付：微信草稿确认排版/署名/文末模块；博客 PR 确认封面渲染与 og:image 输出
- [ ] 真实故障演练：停用文末素材 → 确认阻塞与处理入口；恢复后重新校验通过
