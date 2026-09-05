# 技术设计：品牌与发布标准化

> 对应 `prd.md`（Issue #46）。本文档确定存储结构、集成接缝、版本/幂等模型与迁移方案。

## 1. 架构总览

新增有界上下文 `server/src/reven/brand/`（品牌领域），接入现有发布链路而非改造其骨架：

```
┌────────────────────┐        ┌──────────────────────────────┐
│ brand/ (新增)       │        │ 现有链路（复用，不改骨架）      │
│  models.py         │        │  content_sync → snapshot      │
│  repository.py     │───────▶│  jobs/preparation_state       │
│  application.py    │ 解析    │  publishing/wechat|blog       │
│  (模板应用/纯函数)   │ 冻结    │  publishing/validation        │
│  migration.py      │        │  api/routes/articles.py       │
└────────────────────┘        └──────────────────────────────┘
         ▲
│ api/routes/brand.py  ←  web/src/features/brand/ (新增设置页)
```

**核心原则**：品牌/模板配置是发布时的**输入参数**，不是对正文或链路结构的修改。正文权威仍在 Notion/快照；模板产物（署名、文末模块、OG 字段）只存在于渠道交付物。

## 2. 数据模型（新迁移 0017）

### 2.1 `brand_versions` — 品牌档案（版本化）

| 列 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| version | int unique | 单调递增，从 1 开始 |
| status | String(16) | `draft` / `published` / `archived` |
| payload | JSONB | 见下方 schema |
| source | String(16) | `manual` / `notion_import` |
| published_at / created_at / updated_at | DateTime | |

约束：部分唯一索引保证**至多一条 `published`**、**至多一条 `draft`**。published 行不再原地修改（编辑 = 基于当前 published 生成 draft → 发布为新 version），archived 行只读保留（追溯依据）。

payload schema：
```json
{
  "brand_name": "翊行代码",
  "intro": "品牌简介",
  "default_author": "王翊仰",
  "handle": "wangyiyang",
  "website": "https://wangyiyang.cc",
  "tagline": "...",
  "colors": {"primary": "#00E676", "text": "#0A0A0A", "background": "#FAFAFA"},
  "fonts": {"body": "Inter, Noto Sans SC, ...", "mono": "JetBrains Mono, ..."},
  "style_notes": "简短表达风格说明（仅展示与人工参考，不参与强制校验）"
}
```

### 2.2 `channel_template_versions` — 渠道模板（版本化）

结构同上：`id / channel(blog|wechat) / version / status / payload / created_at / published_at`。约束：每 channel 至多一条 published、一条 draft（部分唯一索引）。

- **wechat payload**：`{ theme: {primary_color, font_family, font_size}, footer_modules: [{key, type: "text"|"image", content?, asset_id?, enabled}] }`
- **blog payload**：`{ author, cover_fallback_asset_id?, og_image_asset_id? }`（og_image 缺省时回落到封面）

### 2.3 `brand_assets` — 品牌素材库

| 列 | 说明 |
|---|---|
| id UUID PK | |
| purpose | `logo` / `avatar` / `qrcode` / `cover` / `other` |
| label / enabled | 用途说明、启用状态 |
| storage_key / public_url / sha256 / mime_type / byte_size | 复用 `ContentAssetStore.archive()`（腾讯云 COS），与快照素材同一存储 |
| width / height | 图片尺寸（上传时解析 PNG/JPEG 头，用于比例提醒校验） |
| source / source_ref | `upload` / `notion_import`，source_ref 记录来源（Notion block/URL） |

启用状态可切换；被模板或发布引用的素材**禁止删除**（首版不提供删除，仅停用）。

### 2.4 `publication_jobs` 扩展（绑定与幂等）

新增列：
- `brand_version_id` UUID FK → brand_versions.id **ON DELETE RESTRICT**，nullable
- `wechat_template_version_id` / `blog_template_version_id` UUID FK RESTRICT，nullable
- `brand_binding_key` String(64)，非空，默认 `'legacy'`（存量行迁移填充）

唯一约束由 `(article_id, content_hash, target_channels_hash)` 扩展为 `(article_id, content_hash, target_channels_hash, brand_binding_key)`：

| 操作 | 行为 |
|---|---|
| 重试原任务 | 同一 job，冻结配置不变（现有 `_channel_finished` 跳过成功渠道） |
| 使用新版重新生成 | 创建新 job（brand_binding_key 不同 → 不冲突），旧 job 保留为历史 |
| 无品牌配置（存量/未配置） | binding_key=`legacy`，行为与今天完全一致（AC9） |

`brand_binding_key` = 解析后品牌版本标识（如 `bv:{brand_version_id}`），任务创建时写入并冻结。

### 2.5 `brand_import_runs` — 迁移记录

`id / notion_page_id / dry_run / status / report JSONB / created_at`。report 含条目计数、素材计数、skipped 项及原因，满足 AC10 核对要求。

## 3. 品牌解析与模板应用（`brand/application.py`，纯函数为核心）

### 3.1 解析

`resolve_brand_config(session) -> ResolvedBrandConfig | None`：读取当前 published 品牌 + 两渠道 published 模板。**无 published 品牌时返回 None → 全链路回落 legacy 行为**（渲染器内置样式、署名取微信集成 `public_config.author`），这是 AC9 兼容路径的关键。

### 3.2 微信产物应用

纯函数 `apply_wechat_template(markdown, brand, template) -> (markdown', warnings)`：
- 在正文末尾追加启用的文末模块（text 直接追加；image/qrcode 引用品牌素材 URL）。
- **去重**：正文已含相同模块标识（模块文本指纹或素材 sha256/URL）→ 跳过并产生 warning `footer_already_present`；无法明确判断 → warning `footer_conflict_uncertain`（提醒级，不阻塞）。
- 应用点在**渲染前**：预览与交付共用此函数，天然一致（AC5）。不写回快照/正文。

### 3.3 渲染器主题参数化

`renderer/src/render.ts` 现有硬编码（`#00E676`、字体栈）改为**默认值**，`cli.ts` 输入协议扩展可选 `theme: {primaryColor, fontFamily, fontSize}`。Python `WechatRenderer.render(markdown, theme=None)` 透传；theme 值在 Python 侧先校验（颜色 `#RRGGBB` 正则、字体/字号长度上限）再进子进程。legacy 路径不传 theme → 输出与今天逐字节一致。

### 3.4 博客产物应用

`BlogConverter._frontmatter` 扩展（仅当 job 有品牌绑定）：
- `cover: <封面相对路径>` — 已验证博客模板 `_includes/theme/post-header.html:33-36` 消费 `page.cover`（封面图需随文章图片一起写入博客仓库，复用现有图片拷贝机制）。
- `og_image_url: <绝对 URL>` — 已验证 `_includes/header.html:87-88` 与 `_layouts/post.html:30-31` 消费 `page.og_image_url` 输出 `og:image` 与 JSON-LD。
- `author`（如模板配置）与既有 `description`/`keywords` 并存。

### 3.5 署名来源切换

`jobs/preparation_state.py:_integration_status` 的 author 目前取自微信集成 `public_config.author`（:69）。改为：品牌解析结果存在 → 用 `default_author`；否则保持现状。交付侧 `WeChatPublisher._Context.author` 从 job 冻结元数据读取。

## 4. 版本冻结与预览一致性

- **任务创建时**（`JobRepository.create_waiting` 调用处）解析当前 published 配置，写入三个 FK + binding_key —— 即冻结点。
- **交付时**通过 FK 读取模板 payload（published 版本不可变，FK 即冻结）。
- **预览**（`ConfiguredWechatPreview.render_current` + 新增博客预览数据端点）按**当前** published 配置实时计算，响应携带 `{content_hash, brand_version, template_versions}` 指纹；前端展示该指纹。配置变更后重新生成预览即新指纹 —— 旧预览明确失效（AC5）。
- 冻结任务的详情页展示冻结版本号；预览始终表达「现在发布会得到什么」。

## 5. 校验分级扩展（`publishing/validation.py`）

沿用现有 `errors`（阻塞）/ `warnings`（提醒）结构，新增：

| 级别 | code | 触发 |
|---|---|---|
| error | `brand_asset_unreadable` | 模板/文末模块引用的素材被停用或存储不可读 |
| warning | `cover_aspect_ratio` | 封面比例偏离渠道推荐值（微信首图 2.35:1；博客按模板） |
| warning | `footer_already_present` / `footer_conflict_uncertain` | 文末模块去重判断结果 |
| warning | `brand_not_configured` | 无 published 品牌（提示性质，legacy 路径正常发布） |

主观审美/文风**不进校验**（issue 明示）。校验结果的处理入口：每个 issue 携带 `field`，前端映射到对应设置页锚点。

## 6. Notion VI Hub 迁移（`brand/migration.py`）

- 入口：`POST /api/brand/import/notion {dry_run: bool}`（设置页触发；server 复用已配置的 Notion 集成凭据）。
- 拉取：`NotionClient.retrieve_page_markdown(67477fcdc2ce40c2ab93a52976f08318)` + `retrieve_page`；markdown 中图片经现有 `ContentMediaArchive`/`ContentAssetStore` 归档为 `brand_assets`（source=`notion_import`）。
- 解析：按章节标题映射候选字段（VI 核心→colors/fonts/logo；公众号规范→微信模板草案；博客规范→博客模板草案；Prompt Kit/AI 生图方法→**跳过并列入 report.skipped，注明复用 SOP 模块**）。无法映射的条目列入 skipped 并给原因。
- 产出：**status=draft 的品牌档案与模板**（待核对草稿），不自动成为 published（AC10）。
- 幂等：同 `notion_page_id` 已有成功 run 且存在对应 draft → 不重复创建，返回既有草稿与提示；素材按 sha256 去重。
- dry_run：只返回 report，不写任何业务表。
- Notion 源归档为 #41 流程的人工操作，不在本设计内。

## 7. API 与页面

### 7.1 新增 `api/routes/brand.py`

```
GET  /api/brand/profile                 → {published, draft}
PUT  /api/brand/profile/draft           → 创建/更新草稿（基于 published 拷贝）
POST /api/brand/profile/publish         → 草稿发布为新版本，旧 published → archived
GET  /api/brand/profile/versions        → 版本列表
GET  /api/brand/assets                  → 素材列表（purpose/enabled 过滤）
POST /api/brand/assets                  → 上传（multipart）或从 URL 归档
PATCH /api/brand/assets/{id}            → 改 label / enabled
GET  /api/brand/templates/{channel}     → {published, draft}
PUT  /api/brand/templates/{channel}/draft
POST /api/brand/templates/{channel}/publish
GET  /api/brand/templates/{channel}/versions
POST /api/brand/import/notion           → {dry_run}
GET  /api/brand/import/runs             → 迁移记录
```

稿件侧扩展（`api/routes/articles.py`）：
- `POST /api/articles/{id}/cover {asset_id}` — 封面缺失/替换时从品牌素材选择（下载归档素材→走现有物化流程进入封面槽位）。
- `POST /api/articles/{id}/jobs` — 用当前品牌配置创建新任务（「使用新版重新生成」入口；与 retry 语义分离）。
- `JobDetail` 增加 brand/template 版本字段与指纹。

### 7.2 前端 `web/src/features/brand/`

- `/brand` 路由 + app-shell 导航「品牌与发布」（图标 Palette 类），页面四区块：品牌档案 / 品牌素材 / 渠道模板（微信·博客 Tab）/ Notion 导入。模式复用 integrations 页（controller hook + card + 表单）。
- 稿件详情页：品牌区块（本次冻结版本/当前将用版本）、校验警告列表带处理入口链接、封面缺失时的素材选择对话框、预览指纹展示（「配置已更新，请重新预览」）。
- 工作台蓝灰主题不动（`.trellis/spec/web/frontend/brand-vi.md`），品牌色只影响渠道产物。

## 8. 兼容性、风险与回滚

| 项 | 说明 |
|---|---|
| 存量任务 | 新列 nullable + binding_key=`legacy`，查看/重试路径不变（AC9 有测试守护） |
| 渲染器 | 不传 theme 时输出逐字节不变（测试守护）；renderer 需重新 build 后被 server 使用 |
| 博客字段 | 仅在品牌绑定存在时写 `cover`/`og_image_url`；博客模板已验证消费这两字段 |
| 迁移幂等 | 唯一约束扩展依赖 `brand_binding_key` 非空默认值，迁移需回填存量行 |
| 回滚 | 新表全部可 DROP 回滚；job 新列可去；功能开关 = 无 published 品牌即 legacy，删除/归档品牌即整体回退旧行为 |
| 风险 | ① VI Hub 实际结构未知 → 解析器按章节启发式 + 完整 skipped 报告，人工核对兜底（issue 流程内建）；② 文末模块去重误判 → 保守策略：不确定即提醒不改动；③ COS 未配置时品牌素材不可用 → 上传接口显式报错并引导配置集成 |

## 9. 验证策略

- 后端：pytest（品牌解析纯函数、模板应用、版本发布流转、幂等约束、legacy 兼容、迁移 dry-run/重复执行）。
- 渲染器：vitest（theme 参数透传、默认值字节级回归）。
- 前端：vitest（设置页表单流转、详情页品牌区块与警告渲染）。
- 端到端：代表性稿件走 AC3/AC4 场景；实施前后步骤对比记录（AC11）写入任务 notes。
