# 执行：CRM 客户跟进变更

前置：父任务整批方案获用户随后明确批准，按顺序启动本子任务；本项为第一项。

1. 从 main 建立 codex/architecture-deepening 工作分支，保护既有 uv.lock；确认独立测试库，先复现 contact-only 更新被当空操作的路径。
2. 迁移六个输入模型和固定领域错误；改 CrmService 为 input + ID 的完整写操作。
3. 同步 REST 与 MCP 写入口，删除旧预检；按改造后长度决定是否按完整领域 adapter 拆 tools_crm。
4. 在 CRM interface 增补真数据库行为，迁移必要 adapter 测试，删除重复/孤儿接线。
5. 委派 trellis-check 自查并修复范围内问题；回写 crm-contract，确认本项验收，再允许飞书子任务开始。

验证（仓库根；DATABASE_URL / TEST_DATABASE_URL 指向专用空测试库）：

```sh
uv run --frozen alembic -c server/migrations/alembic.ini upgrade head
uv run --frozen pytest server/tests/crm server/tests/api/test_crm.py server/tests/agent/test_tools_crm.py
uv run --frozen ruff check server
uv run --frozen ruff format --check server
uv run --frozen mypy server/src
```

核对本次函数 <=50 行、代码文件 <=500 行、MCP 工具名字/默认值和 REST JSON 未扩大；记录数据库用例没有因未配置而跳过。禁止改动 uv.lock、用户其他变更或提交 main。

提交关注点：refactor(server): 深化 CRM 客户跟进变更。具体提交文件在完成验证后核对，仅纳入本项拥有的变更。
