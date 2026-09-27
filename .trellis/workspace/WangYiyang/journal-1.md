# Journal - WangYiyang (Part 1)

> AI development session journal
> Started: 2026-08-12

---


## 2026-08-12 · 品牌 VI 重构（08-12-brand-vi-refactor）
- 分支 refactor/brand-vi，4 commit：资产+字体 / web 全面换肤+深色模式 / renderer 主题 / 质检修复
- 三色系统落地：--bg/--ink/--signal/--muted/--faint/--line + --danger 语义例外；字体 fontsource 本地打包（Inter/Noto Sans SC/JetBrains Mono）
- 深色模式 data-theme 驱动 + theme.ts（localStorage try/catch）；Logo {翊} master/mono-white 双版切换 + favicon
- renderer 微信预览：主色 #00E676、标题全碳黑、引用绿竖线、代码块深色+绿关键字；新增 render-brand.test.ts 回归锁
- 规范沉淀：.trellis/spec/web/frontend/brand-vi.md（令牌契约 + VI 铁律 + 链接/卡片/徽标口径）
- 验证：web lint/test(64)/build、renderer test(32) 全绿；走查截图存任务 assets/（后端未启动，数据页为空态，组件态由测试覆盖）


## Session 1: 完成全部开放 Bug Issues

**Date**: 2026-09-02
**Task**: 完成全部开放 Bug Issues
**Branch**: `codex/fix-all-open-bug-issues`

### Summary

关闭 #83、#100–#105，修复分页、CRM/人才布局与状态、财务一致性和现金口径、Notion 蓝灰主题 WCAG AA，并通过完整质量门禁。

### Main Changes

- 关闭 7 个开放 bug Issue，保留当前 Notion 蓝灰主题
- 按 Issue 拆分原子修复与 Trellis 归档提交

### Git Commits

| Hash | Message |
|------|---------|
| `7e5c9fc` | (see git log) |
| `c1a0377` | (see git log) |
| `3a9aa1e` | (see git log) |
| `633d8b5` | (see git log) |
| `c769c83` | (see git log) |
| `763c99a` | (see git log) |
| `05f38cd` | (see git log) |

### Testing

- [OK] Renderer 32/32；Web 170/170；Server 全量测试通过
- [OK] Ruff、Mypy、Web lint/build、部署脚本和浏览器 axe 审计通过

### Status

[OK] **Completed**

### Next Steps

- 审查并合并 GitHub PR

## Session 2: Playbooks 模块统一更名为 SOP（无兼容）

**Date**: 2026-09-05
**Task**: 09-05-refactor-playbooks-to-sop（Issue #107）
**Branch**: `issue/gh-107-refactor-playbooks-sop`

### Summary

按 grilling 共识全量重命名：代码库 playbook 命名清零，含数据库表与迁移改写；kind 值 sop → procedure（标签「程序」）使模块名独占 SOP；取消全部兼容要求（无历史数据）。Issue #107 验收标准已同步修订。

### Main Changes

- 迁移：改写 0012_playbooks → 0012_sops，同步 0013 两个迁移 down_revision 与 env.py 导入
- 后端：reven.sops（Sop/SopRepository）、/api/sops、SopKind=procedure
- 前端：features/sops、路由 /sops、导航与页面「SOP（标准作业流程）」、kind 标签「程序」
- 文档：ai-test-map 同步；database-guidelines 沉淀「改写历史迁移的牵连点清单」

### Git Commits

| Hash | Message |
|------|---------|
| `7ddc368` | refactor(server): playbooks 模块更名为 sops |
| `1304dc2` | refactor(web): playbooks 功能更名为 sops |
| `dd4042b` | docs: 同步 SOP 命名至测试地图与后端 spec |
| `4160f0b` | chore(task): 新增任务工件 |

### Testing

- [OK] 迁移链空库 → head 跑通；Server 678 passed（Docker postgres:17-alpine）
- [OK] Web 170 passed + tsc + eslint；Ruff + Mypy 通过
- [OK] OpenAPI 验证 /api/sops 注册、/api/playbooks 消失；源码 grep playbook 清零

### Known Issues（预存在，与本任务无关）

- 后端 5 个测试全量跑偶发失败、单独跑全绿（content_sync/publishing/actions，测试隔离问题）
- 本地 Node 26 下 app-shell 测试需 `NODE_OPTIONS=--localstorage-file`（CI Node 22 无此问题）

### Status

[OK] **Completed（待 PR）**

### Next Steps

- push 分支并开 PR 关联 #107；PR review 时可 dogfood /sops 页面


## Session 2: gh-108 财务工作区：三子页面拆分 + 抽屉录入 + 待收付流程打通

**Date**: 2026-09-06
**Task**: gh-108 财务工作区：三子页面拆分 + 抽屉录入 + 待收付流程打通
**Branch**: `issue/gh-108-feat-finance`

### Summary

Issue #108 全流程交付：后端 entries 筛选(status多值/month/category) + summary month 参数 + confirm 幂等结清接口（409 防重复）；前端三子页面（概览/流水/待收待付）+ radix 抽屉四入口 + 确认收付对话框；spec 契约同步 month/confirm。决策 D1：线上无历史数据，首版不做已记录待确认入口，AC9 改为口径保障+上线前 SQL 核查。质量：后端覆盖率 86.69%、finance 前端 21 测试全绿、trellis-check 无 blocker；修复 2 个 minor（摘要按方向拆分链接、status 参数遮蔽）。rebase 解决 #109 SOP 重命名冲突；测试容器重建迁移。PR #111 待审，发布前需 SQL 核查与双端走查。

### Git Commits

| Hash | Message |
|------|---------|
| `afb89d5` | (see git log) |
| `9c64247` | (see git log) |
| `bffb506` | (see git log) |
| `853ed10` | (see git log) |

### Status

[OK] **Completed**


## Session 3: Issue #115：仅发版构建容器镜像

**Date**: 2026-09-06
**Task**: Issue #115：仅发版构建容器镜像
**Branch**: `codex/gh-115-release-only-container`

### Summary

创建独立工作树并修复普通 PR/main 重复构建容器；发版 full 验证保留。

### Main Changes

- container 仅由 inputs.full 启用，移除废弃路径过滤与输出；同步运维说明和 CI 契约。

### Git Commits

| Hash | Message |
|------|---------|
| `4afe0c9` | (see git log) |

### Testing

- [OK] 回归先失败后通过；6 项部署契约通过，安全测试 27 通过/18 因数据库缺失跳过；ruff、format、mypy、actionlint 及独立审查通过。

### Status

[OK] **Completed**

### Next Steps

- 按 GitHub Flow 推送分支并创建关联 #115 的 PR，确认远端 CI 的 container 为 skipped；尚未推送或部署。

## 2026-09-19 稿件状态筛选值域脱节修复

- 排查 dev.wangyiyang.cc:3001 下拉脱节：前端硬编码状态选项与真实值域（已发布/撰写中/选题池/未开始）零交集
- 方案 A 落地：新增 GET /api/articles/status-facets（notion∪automation 去重），前端动态生成下拉选项
- PR #118 squash 合并，CI 全绿；补固化 spec：filter-facets-contract.md（开放式值域禁止硬编码选项）
- 发版 v0.1.3 触发 release.yml 自动部署（上次发版 9/1 failure 导致线上停留旧版）；线上验收 33 条已发布筛选通过
- 注意：deploy 走 production environment；本地后端 DB 测试需 TEST_DATABASE_URL（CI 有 Postgres 服务）

## 2026-09-19 集成 DeepSeek Harness 作为 Agent 核心（#123）

- grilling 两轮拍板 9 项决策（生产模块直写、/agent/chat 调试端点、容器/VPS 正式拍板、agent-llm 通用配置抽象等），Trellis 任务 09-19-dsh-agent-core 全程留痕
- M0 spike 关键结论（全部实测）：sdk profile JSON-RPC 仅 initialize/session/prompt/shutdown 三方法，**无宿主工具协议**；工具走官方 dsh-mcp-client + patch `insert:` 语法（平铺条目只能覆盖不能新增）；单实例多 session 真并发无需全局锁；linux manylinux wheel 存在
- 端到端验收（临时 key）：PUT agent-llm（api_key 加密入库）→ 重启 → POST /api/agent/chat "加一个正向关键词：AI Agent" → 模型原生调 mcp__reven__ 工具落库 → GET /api/rss/keywords 确认 ✅
- 踩坑：AGENT_MCP_URL 默认 8000 端口，非标端口必须显式设置（否则模型"不知道有工具"且不报错）；tests 混跑干扰根因 = 进程 env 泄漏（conftest 隔离修复）
- 交付：5 个原子提交 → PR #125；#119/#123 评论同步；spec 沉淀 agent-dsh-contract.md；docs/agent-architecture.md
- 临时 DeepSeek key 需吊销；正式 key 走集成页配置

### Status

[OK] **PR 已建待合并**（#125）；任务归档待合并后执行


## Session 4: 移除稿件发布与 Notion 集成

**Date**: 2026-09-21
**Task**: 移除稿件发布与 Notion 集成
**Package**: web
**Branch**: `codex/remove-notion-publishing`

### Summary

独立 worktree 完成稿件发布、Notion/GitHub/微信发布集成退役；RSS 采纳改为本地素材并保留飞书审核与品牌管理。新增 0021 清理迁移，简化构建部署和依赖，同步现行规范。后端 487 项通过、覆盖率 86.87%，前端 168 项通过，lint/typecheck/build、迁移一致性、桌面/移动浏览器和 Docker 构建及非 root 运行均通过。未部署生产。

### Git Commits

| Hash | Message |
|------|---------|
| `3e29860` | (see git log) |

### Status

[OK] **Completed**


## Session 5: PR #128 交付与收尾

**Date**: 2026-09-21
**Task**: PR #128 交付与收尾
**Package**: web
**Branch**: `codex/remove-notion-publishing`

### Summary

已将 codex/remove-notion-publishing 推送到 origin，并创建 PR #128：https://github.com/wangyiyang/Reven/pull/128，目标 main。任务 09-21-remove-notion-publishing 已归档，本地全套测试及构建验证结果已记录，收尾检查时工作区干净。GitHub CI 尚在运行；PR 尚未合并，未部署生产。

### Git Commits

| Hash | Message |
|------|---------|
| `3e29860` | (see git log) |

### Status

[OK] **Completed**


## Session 6: 架构深化批次（GH #133-#137）全部交付

**Date**: 2026-09-22
**Task**: 09-22-architecture-deepening
**Package**: web + reven-server
**Branch**: main（5 个 feature 分支各自 PR squash 合并）

### Summary

架构评审（improve-codebase-architecture）产出的 5 个 Issue 全部交付并关闭：#134 注册表拆除（PR #138）、#136 web CRUD seam（PR #139，净删 384 行）、#137 路由+卡片收拢（PR #140）、#133 凭证 seam + ProviderClients（PR #141，30 文件 +1440/-924）、#135 Settings 组合根（PR #142）。spec 回写 PR #143。实施经 trellis-implement × 6 波 + trellis-check × 5 轮独立复核；check 在 PR-B 抓住 1 处真实语义回归（master key 非法时启动崩溃 vs env 降级）并修复附回归测试。最终门禁：server 616 测试 + ruff + mypy strict 绿，web 200 测试 + lint + build 绿，全部 PR CI 通过后 squash 合并。

### Key Decisions

- ProviderClients 不可用 yield None（各调用方领域语义不同，typed 异常无法真正统一）；落顶层 provider_clients.py（避免 integrations→rss 层级倒置，实测消除一次循环导入）
- tencent_cos 纯 env 形态不进 IntegrationCredentials seam
- CSRF settings 缺失 500→403 fail-closed（生产不可达，更符合威胁模型）
- web 前端 spec 原为占位模板，本次仅回写本批次确立的约定，完整 bootstrap 留待后续

### Git Commits

| Hash | Message |
|------|---------|
| `3de29bb` | refactor(server): 删除 connection-test 全局 adapter 注册表 (#134) (#138) |
| `a251e56` | refactor(web): useResourceList + ResponsiveList (#136) (#139) |
| `c363aae` | refactor(web): routes.tsx + IntegrationCard (#137) (#140) |
| `d4c1a91` | refactor(server): IntegrationCredentials + ProviderClients (#133) (#141) |
| `02cb110` | refactor(server): Settings 组合根 (#135) (#142) |

### Status

[OK] **Completed**


## Session 6: fix(feishu): #132 候选审核推送收敛为每日汇总 + #131 关闭 + #146 清理 issue

**Date**: 2026-09-26
**Task**: fix(feishu): #132 候选审核推送收敛为每日汇总 + #131 关闭 + #146 清理 issue
**Package**: web
**Branch**: `main`

### Summary

两轮设计拷问敲定方案后实施：删除飞书候选审核全量卡片推送链路（review_card/review_pusher/ReviewBoard/list_pending_review/mark_review_pushed/send_review_card），每日汇总追加待审核总数统计，去重复用 notification_sent_at；回调链路保留，review_pushed_at 列保留并标注废弃；spec/runbook/integrations/README/web 文案同步。PR #145 squash 合并（CI 全绿），#131 关闭为 obsolete，新建 #146 跟踪卡片回调死代码清理。验证：server 597 tests + ruff + mypy strict 全绿，web 206 tests + eslint + tsc 全绿。

### Git Commits

| Hash | Message |
|------|---------|
| `f169da2` | (see git log) |

### Status

[OK] **Completed**


## Session 7: 飞书机器人接入 Agent 对话

**Date**: 2026-09-27
**Task**: 飞书机器人接入 Agent 对话
**Package**: web
**Branch**: `feat/feishu-bot-conversation`

### Summary

飞书机器人从固定文案应答升级为 Agent 对话入口：私聊+群聊@ 经线程桥（handler 立即返回 + daemon 工作线程）接入 AgentService，session=feishu:{chat_id}:{user_id}，两条引用回复，120s 兜底，白名单全静默。602 测试全绿，mypy strict 通过；真实凭证验证 get_bot_open_id 正确。契约已回写 spec。PR #150。

### Git Commits

| Hash | Message |
|------|---------|
| `f81d614` | (see git log) |
| `bc10810` | (see git log) |
| `3eda431` | (see git log) |

### Status

[OK] **Completed**
