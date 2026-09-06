# 执行计划：品牌与发布标准化

> 对应 `prd.md` + `design.md`。单一任务按阶段推进；每阶段收尾必须跑通验证命令并提交（Conventional Commits）。

## 验证命令基线

```bash
# 后端（仓库根目录，uv 管理）
uv run pytest                      # 全部后端测试
uv run ruff check .                # lint
uv run mypy                        # strict 类型检查（packages = reven）

# 前端 / 渲染器（pnpm）
pnpm --filter @reven/web test --run
pnpm --filter @reven/web lint
pnpm --filter @reven/renderer test   # 含 vite build
pnpm build                          # renderer + web 全量构建（最终回归）
```

基线确认：开始前先全量跑一遍，记录既有失败（若有），避免把存量问题当回归。

## 阶段 A：品牌领域基础（后端）

目标：`brand_versions` / `channel_template_versions` / `brand_assets` / `brand_import_runs` 四表 + 品牌 CRUD/版本发布 API + 素材上传可用。

- [x] A1 迁移 `0017_brand_foundation`：四张新表 + `publication_jobs` 增列（`brand_version_id`、`wechat_template_version_id`、`blog_template_version_id`、`brand_binding_key` 非空默认 `'legacy'` 回填存量）+ 唯一约束扩展为 `(article_id, content_hash, target_channels_hash, brand_binding_key)`。downgrade 可完整回滚。
- [x] A2 `server/src/reven/brand/models.py` + `repository.py`：draft/published/archived 流转；部分唯一索引（每 channel 一 published 一 draft；品牌同理）。
- [x] A3 `brand/service.py`：草稿编辑（基于 published 拷贝）、发布（新版本号、旧版归档）、素材上传（复用 `ContentAssetStore.archive()`，解析图片尺寸入库）。
- [x] A4 `api/routes/brand.py` + schemas：profile/assets/templates 全组端点（不含 import）。错误显式处理，未配置 COS 时上传显式报错。
- [x] A5 测试：版本流转、唯一约束、素材上传/停用、legacy 默认值迁移。
- [x] **验证点 A**：`uv run pytest && uv run ruff check . && uv run mypy` 全绿（688 passed）→ 提交 `feat(server): add brand domain foundation`（已提交，中文 commit）。

## 阶段 B：发布链路集成（后端 + renderer）

目标：品牌配置作为输入参数进入渲染/转换/校验/任务绑定，legacy 路径逐字节不变。

- [x] B1 renderer：`render.ts` 主题默认值抽参、`cli.ts` 输入协议加可选 `theme`；vitest 覆盖「不传 theme 输出不变」回归。`pnpm --filter @reven/renderer test`。
- [x] B2 `brand/application.py` 纯函数：`resolve_brand_config`、`apply_wechat_template`（文末模块追加 + 去重 + 提醒）、博客 frontmatter extras 计算。单测先行（含 dedup 三态：追加/跳过/不确定提醒）。
- [x] B3 `WechatRenderer.render(markdown, theme=None)` 透传 + Python 侧 theme 校验（颜色正则、长度上限）。
- [x] B4 链路接入：`WeChatPublisher`（渲染前应用模板、author/digest 取冻结配置）、`BlogConverter._frontmatter`（cover/og_image_url/author，封面图随文拷贝）、`ConfiguredWechatPreview`（当前配置实时预览 + 响应携带版本指纹）。
- [x] B5 任务绑定：`create_waiting` 调用处解析并冻结品牌/模板 FK + binding_key；新增 `POST /api/articles/{id}/jobs`（当前配置重新生成）与 `POST /api/articles/{id}/cover`（素材选封面）；retry 语义不变。
- [x] B6 校验扩展：`brand_asset_unreadable`(error)、`cover_aspect_ratio`/`footer_*`/`brand_not_configured`(warning)；署名来源切换（品牌优先，fallback 微信集成 author）。
- [x] **验证点 B**：后端三件套全绿 + renderer 测试绿；重点守护：legacy job（无品牌绑定）行为与输出不变的回归测试 （已达成：后端 714 passed / ruff / mypy 全绿；renderer 39 passed；pnpm build ✓。文末图片素材与正文同 staging 冻结、交付时续序占位符化）→ 提交 `feat(server,publishing): apply brand templates in delivery pipeline`。

## 阶段 C：前端设置页与稿件详情

目标：品牌资料可视化维护；高频操作（预览/校验/封面/版本追溯）进入稿件详情。

- [x] C1 `web/src/features/brand/`：`/brand` 设置页四区块（档案/素材/模板双渠道 Tab/导入占位），复用 integrations 页模式；app-shell 导航加「品牌与发布」。
- [x] C2 稿件详情：品牌区块（冻结版本 vs 当前版本）、校验警告带处理入口链接、预览指纹与「配置已更新请重新预览」提示。
- [x] C3 封面缺失时的素材选择对话框（选择/上传 → `POST /articles/{id}/cover`）。
- [x] C4 发布历史/任务详情展示品牌与模板版本（追溯视图）。
- [x] **验证点 C**：`pnpm --filter @reven/web test --run && pnpm --filter @reven/web lint && pnpm build` 全绿 （已达成：web 169 passed（+9 新增）+ 基线 10 个 app-shell 失败不变 / eslint clean / build ✓）→ 提交 `feat(web): brand settings and article brand context`。

## 阶段 D：Notion VI Hub 迁移

- [x] D1 `brand/migration.py`：拉取 VI Hub（page `67477fcdc2ce40c2ab93a52976f08318`）→ 章节启发式映射（品牌名/署名/handle/官网/tagline/简介 + 终端绿·碳黑·冷白色值槽位 + 图片按章节猜用途）→ draft 品牌 + 素材归档；规范类/未识别章节全部进 skipped 带原因。已有草稿不覆盖。
- [x] D2 `POST /api/brand/import/notion`（dry_run/execute）+ `GET /api/brand/import/runs`；幂等（同 page 已有成功 run → 返回既有记录；素材 sha256 去重）；迁移 0019 为 brand_import_runs 增加 error/finished_at。
- [x] D3 设置页接入导入入口与 report 展示（阶段 C 已预埋 ImportSection，本次核对契约一致：report 含 brand_name/计数/skipped 列表）。
- [x] D4 测试：解析器映射/空文档、dry-run 零写入、execute 幂等、已有草稿不覆盖、失败运行记录脱敏 error、API dry-run/execute/幂等/未配置集成 409（共 8 个新增）。
- [x] **验证点 D**：全量验证命令绿（后端 722 passed / ruff / mypy；web 169 passed + 基线 10 失败不变）→ 提交 `feat(server): Notion VI hub 品牌迁移`。

## 阶段 E：验收与收尾

- [ ] E1 代表性稿件端到端：代码级 AC 审计已完成（`notes-acceptance.md`，AC1–AC10 逐条映射测试证据）；**真实双渠道交付（博客 PR / 微信草稿 / 真实 VI Hub 导入）需部署环境凭据，列入部署环境复核清单**。
- [x] E2 AC11：实施前后代表性发布步骤对比已写入 `notes-acceptance.md`（≈6 步→≈2 步，重复录入 4 处→0 处）。
- [x] E3 全量回归：后端 722 passed / ruff / mypy 全绿；web 169 passed + 基线 10 失败不变；renderer 39 passed；`pnpm build` ✓。
- [x] E4 `trellis-update-spec`：`.trellis/spec/reven-server/backend/brand-publishing-contract.md`（版本模型/冻结与幂等/渠道产物不回写正文/文末素材冻结占位符/渲染器主题协议/迁移契约）。
- [ ] E5 提交剩余改动，推送分支并创建 PR（关联 #46）。

## 风险点与回滚

| 风险点 | 位置 | 缓解 |
|---|---|---|
| 唯一约束迁移破坏存量 job | A1 | 迁移先在测试库跑 downgrade/upgrade 双向；存量回填 `'legacy'` |
| renderer 协议变更影响线上渲染 | B1/B3 | 可选参数 + 字节级回归测试；renderer build 产物需同步部署 |
| 文末模块去重误伤正文 | B2 | 保守策略：不确定只提醒不改动；纯函数单测覆盖 |
| VI Hub 结构未知导致解析偏差 | D1 | 产出仅为 draft + skipped 报告，人工核对后启用 |

## 开始前检查

- [x] 基线验证命令全量跑通（记录既有失败）——基线结论：后端 pytest 381 passed / `ruff check server/` 全绿 / mypy 全绿；renderer 32 passed；web 160 passed + **10 failed（app-shell.test.tsx 移动端布局，存量失败，属 08-22-mobile-nav-layout 任务范围，本任务不动）**；web lint 全绿。存量 ruff 158 errors 全部在 .claude/.codex/.cursor/.trellis 工具目录，产品代码无问题。后续验证后端 lint 用 `uv run ruff check server/`。
- [x] 确认本环境子代理不可用，Phase 2 采用 inline 实现（主会话直接编辑，加载 `trellis-before-dev` 规范）
- [x] `implement.jsonl` / `check.jsonl` 已按平台要求处理（已填充真实 spec/research 条目）
