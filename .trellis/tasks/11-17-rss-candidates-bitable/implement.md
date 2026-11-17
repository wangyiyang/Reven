# 实施计划：RSS 候选直写飞书多维表格

一个 PR，五个原子 Commit，按序执行。每个 Commit 独立可编译、可测试。

## Commit 1：飞书 OpenAPI 基座 + 资源绑定后端

- 扩展 `integrations/feishu_bot/client.py` 为共享 OpenAPI client（或抽出共用模块），新增 Bitable 方法：list_fields / search / batch_create / batch_update / batch_delete。
- 新增 `feishu_resource_bindings` 模型 + 迁移 + 管理 API（list/create/update/enable/disable/delete/test）。
- 测试：client mock 单测、绑定 API 集成测试、test 探针各阶段失败分支。
- 验证：`uv run ruff check server && uv run mypy server/src && uv run pytest server/tests -k "feishu or binding"`

## Commit 2：资源绑定管理 UI

- 在飞书集成卡片内加绑定管理区（列表、创建/编辑表单、启停、删除、测试按钮与结果展示）。
- 类型定义更新（`web/src/features/integrations/types.ts`）。
- 验证：`pnpm --filter @reven/web lint && pnpm --filter @reven/web test --run`

## Commit 3：RSS 管线直写 Bitable

- discovery：删 `_save_if_new`，run 内抓取结果入内存。
- screening：输入改 run 内列表，输出 candidate/filtered。
- 新增 `BitableCandidateWriter`：seen-set → search 查重 → batch_create（client_token）→ advisory lock 包裹。
- run 失败边界：writer 失败不推进 checkpoint、不发成功汇总。
- 测试：去重三键优先级、写入失败重试边界、并发串行化。
- 验证：后端 lint + mypy + pytest。

## Commit 4：工作台与 Dashboard 改读 Bitable

- `BitableCandidateStore`：列表 search + 状态 update（先读后写，409 冲突）。
- rss 路由列表/审核端点切换到 store；Dashboard 统计切换；删除 estimate_hits 及入口。
- 前端数据层 hook 切换 + 409 提示刷新。
- 验证：后端 + 前端全套检查。

## Commit 5：删除 rss_items 与文档更新（最后）

- 迁移 drop table；删模型、review_service、旧端点、旧测试。
- 更新 docs/data-architecture.md、self-hosting 文档、rss-materials-contract spec。
- 全量验证命令：
  - `uv run ruff check server`
  - `uv run mypy server/src`
  - `uv run pytest server/tests --cov=reven --cov-fail-under=80`（pytest 环境不含 REVEN_MASTER_KEY，TEST_DATABASE_URL 指向 reven_test）
  - `pnpm --filter @reven/web lint`
  - `pnpm --filter @reven/web test --run`

## 前置动作

1. 更新 Issue #226 标题/正文/验收标准 + 新增口径变更评论。
2. `task.py start` 激活任务，从 main 拉分支 `feat/226-rss-bitable-authority`。
3. 编辑代码前加载 trellis-before-dev；实现派发 trellis-implement。

## 风险点

- Bitable search 可见时效无承诺：查重可能漏掉刚写入记录 → seen-set + client_token + advisory lock 三层缓解，验收标准为"不产生明显重复"。
- 绑定测试的创建/删除探针对外部同步表会失败 → 测试中明确报错阶段，文档注明。
- 删除 rss_items 不可逆 → 放最后一个 Commit，PR 描述醒目标注。
