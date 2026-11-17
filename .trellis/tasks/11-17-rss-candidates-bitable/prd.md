# RSS 候选直写飞书多维表格

关联 Issue：GitHub #226（标题与正文将按本 PRD 重写，旧"单向投影"口径作废）

## Goal

RSS 候选条目的唯一权威存储改为飞书多维表格（Bitable）：发现管线筛选出的候选直接写入 Bitable，Web 候选工作台与 Dashboard 直接读写 Bitable，PostgreSQL 不再保存条目级候选数据。

## Background

- 现状：RSS 管线以 `rss_items` 表为权威源，发现去重、筛选输入、审核、统计全部读写 PG。
- 目标：候选数据归业务方在飞书中直接管理，应用本身只保留运维状态。
- 历史 `rss_items` 数据不需要保留：不归档、不迁移，表最终删除。

## Scope

### In scope

1. 通用飞书资源绑定：新增 `feishu_resource_bindings`（`resource_type + purpose + config JSONB`），首个用途 `bitable / rss_candidates`；每个 purpose 同时只有一个启用绑定。
2. 共享飞书 OpenAPI 基座：出站 API 统一走 `httpx` 共享 client（复用现有 token 缓存、脱敏错误、响应上限）；`lark-oapi` 仅保留在长连接 supervisor。
3. RSS 管线改造：发现 → 内存筛选 → 候选直写 Bitable；只写 `candidate`，`filtered` 不落任何存储，历史重筛能力取消。
4. 写入防重：PG advisory lock 串行化同表写入 + run 内 seen-set + 按去重键查询 + 稳定 `client_token`（降低重复风险，无数据库级唯一保证）。
5. 运行边界：Bitable 写入失败 = run 失败，不推进 source checkpoint、不发成功汇总，run 可重试。
6. Web 候选工作台改读写 Bitable：状态仅 `candidate / saved / ignored`；采纳/忽略先读后写，状态已变化返回 409 并让前端刷新。
7. Dashboard 基础统计改查 Bitable；移除关键词命中估计（estimate_hits）功能。
8. 管理端配置：在现有飞书集成卡片内加资源绑定管理 UI（不新增顶层页面），绑定测试为真实探针（字段校验 + 只读查询 + 创建记录 + 删除记录；不支持删除的外部同步表测试失败）。
9. 清理：删除 `rss_items` 表及相关代码/测试；更新数据架构文档、部署文档。
10. 重写 Issue #226 并新增评论说明口径变更。

### Out of scope

- 文档/知识库业务逻辑（资源绑定模型为此预留，但本任务不实现）。
- Agent 飞书工具。
- PG/Bitable 双写开关、灰度切换。
- 绑定切换时的旧 Bitable 数据迁移（切换只影响未来 run）。
- Bitable 表字段自定义映射（字段集固定，见 design.md）。

## Acceptance Criteria

- [ ] 配置 `bitable/rss_candidates` 绑定后，RSS run 产生的候选出现在目标 Bitable 表中，字段完整（标题、摘要、来源、发布时间、原文链接、状态、命中关键词、入库日期、去重键）。
- [ ] 同一文章重复出现（同 URL / GUID / title）时 Bitable 中不产生明显重复行（去重键查询 + client_token + 串行写入）。
- [ ] Bitable 写入失败时 run 标记失败、checkpoint 不推进、重试 run 能恢复写入。
- [ ] Web 候选工作台列表、采纳、忽略均直接读写 Bitable；并发审核冲突返回 409 且前端提示刷新。
- [ ] Dashboard 候选/已保存统计来自 Bitable；关键词命中估计入口已移除。
- [ ] 飞书集成卡片内可创建/查看/启停/测试绑定；测试探针覆盖字段校验、读、写、删。
- [ ] `rss_items` 表及相关模型、路由、测试全部删除；迁移在全新库与存量库上均可执行。
- [ ] `uv run ruff check server`、`uv run mypy server/src`、后端测试（coverage ≥ 80%）、`pnpm --filter @reven/web lint`、`pnpm --filter @reven/web test --run` 全部通过。
- [ ] Issue #226 标题/正文/验收标准已更新，并有评论声明覆盖旧口径。

## Notes

- 交付方式：一个 PR、多个原子 Commit，数据删除相关 Commit 放最后。
- 无数据库级唯一约束是 Bitable 的固有限制，验收以"不产生明显重复"为准。
