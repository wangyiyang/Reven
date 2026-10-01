# 执行计划：三项依次深化

当前 planning。用户对本轮最终具体方案的随后明确确认，授权三个子任务按本计划依次进入实现；不重复逐项确认相同已批准范围。

## 准备与顺序

1. 核对当前用户现场及 uv.lock 基线，在 main 上建立 codex/architecture-deepening 功能分支；不得提交 main 或纳入未知改动。
2. 确认独立测试库；本机有 reven-test-pg / reven-test-pg-119 容器，但 shell 未设置 TEST_DATABASE_URL。使用专用空库，不复用其原数据，不打印凭证；执行已有迁移到 head。
3. 在用户批准后启动 10-01-crm-deepening，按其 implement.md 由 trellis-implement 实现、trellis-check 检查，完成领域契约回写。
4. 第1项通过后启动 10-01-feishu-delivery-deepening，实现与验证唯一 HTTP 交付、线程桥接和标题保留，回写飞书契约。
5. 第2项通过后启动 10-01-session-model-deepening，实现共享生命周期、模型状态/本轮身份和组合测试，回写 Agent / 飞书说明。
6. 父任务检查三项共用代码、错误与降级语义，执行最后一次完整后端质量门禁；准备原子提交、PR 和完成记录。

每次子代理派发从 Active task: <当前子任务路径> 开始，明确文件所有权、测试范围与不得覆盖前项/用户修改。context 已在各任务 implement.jsonl / check.jsonl 配齐；优先 native 注入，缺失时子代理按 manifest 加载。

## 验证门禁

各项 targeted pytest 见子任务 implement.md；完整门禁（已配置专用 DATABASE_URL / TEST_DATABASE_URL）：

```sh
uv run --frozen alembic -c server/migrations/alembic.ini upgrade head
uv run --frozen pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80
uv run --frozen ruff check server
uv run --frozen ruff format --check server
uv run --frozen mypy server/src
```

- 真数据库用例没有因环境缺失而 skip；使用真实测试库，不将 mock 当 PostgreSQL 行为证明。
- 真实 dsh 握手需单独确认环境和结果；不使用真实 LLM 网络调用作为验收，不发送真实飞书测试消息。
- 本次写入生产函数 <=50 行，代码文件 <=500 行；识别并拆分相关超长文件，不整理无关文件。
- 产品外部 schema / 错误码 / 工具名 / 语义和 uv.lock 保护有明确检查，CI 限制或未验证部分如实报告。

## 提交关注点与收尾

- refactor(server): 深化 CRM 客户跟进变更。
- refactor(server): 统一飞书消息交付。
- refactor(server): 集中会话模型身份。

实际提交文件在代码验证后按项目 Phase 3.4 核对。规范回写与对应工作一起交付；归档 / journal 收尾位于工作改动之后。最终 PR 汇总三项具体结果与实际验证，不合并或部署。

## 回滚点

每项独立验证后再前进；出现业务漂移先在当前子任务回退/修正，不用后项绕过问题。发现设计需改变外部契约时回到规划，具体说明变化后再审阅。
