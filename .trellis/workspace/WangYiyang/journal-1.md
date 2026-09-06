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
