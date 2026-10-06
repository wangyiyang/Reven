# Agent 运行时迁移实施计划

## 前置门槛

- [x] 用户同意创建 Trellis 任务并进入规划。
- [x] 完成研究、PRD 收敛、设计自审以及真实上下文清单。
- [x] 用户在最新规划摘要后明确批准实施（2026-10-06：“开始实施”）。
- [x] `task.py start` 成功，状态变为 `in_progress`。
- [x] 基于 main 创建 `codex/agent-langgraph-migration` 分支；保留已有未跟踪目录。

未完成前四项时禁止编辑产品代码或分派 implement/check。规划任务文件可继续更新。

## 阶段 1：验证框架与模型协议

- [x] 读取最新锁文件、已安装依赖和 research；将选定稳定版本范围写入 server/pyproject.toml 并用 uv 更新锁（既有包版本与来源保持，新增 Agent 依赖显式官方索引）。
- [x] 验证 LangChain `create_agent`、真实 async PostgreSQL saver、HITL interrupt/resume 和跨 pool/graph 重建（23 项门槛测试；完整 app/进程恢复继续在阶段 4）。
- [x] 用确定性模型验证“记录跟进”“确认删除”两条最小工具循环（框架实际执行，业务效果为测试替身；真实领域写入在阶段 3 集成）。
- [x] 用 HTTP 协议替身验证 DeepSeek 推理字段、tool_call ID、消息顺序和模型错误；按 adapter 官方协议使用客户端。
- [ ] 在隔离测试数据下做真实模型工具 smoke（通过既有凭据 seam 读取安全配置，不人工回显密钥、不触碰生产业务）；未执行必须明确标未验证。
- [x] 原生框架与 HTTP 协议门槛通过后才迁移 37 个工具；真实上游模型未验证单独声明。

## 阶段 2：持久化基础

- [x] 新建配置版本、会话、运行、操作记录、确认记录 ORM/Repository 和增量 Alembic 迁移。
- [x] 声明唯一约束、参数哈希、owner 与状态迁移；空库和存量升级均验证。
- [x] 管理独立 async psycopg saver 池及专用 schema 初始化，关闭时完整释放。
- [x] 增补迁移 metadata/fixture TRUNCATE 清单，防止测试跨案例污染。
- [x] 配置从下一轮生效；每次运行记录 immutable revision，model override 入库。

## 阶段 3：可信工具与业务事务

- [x] 显式整理 37 个工具定义，复用业务函数，派生 LangChain 与 MCP adapter；保持输入 schema/业务语义。
- [x] 25 个写工具接入统一操作入口；actor/run/tool_call/approval 从可信宿主注入。
- [x] CRM/Talents 服务支持 Agent 外部事务；网页默认提交方式保持。
- [x] RSS 写入与操作结果同事务，embedding 刷新维持已保存/pending 的既有语义。
- [x] 8 个删除工具强制持久确认，并在写事务内再次验证/消费批准。
- [x] 覆盖客户跟进、人才履历/院校追加、人才画像导入、子对象归属和级联删除的回归。

## 阶段 4：执行核心与服务层

- [x] 用原生 async LangGraph 实现替换 DSH 子进程、模型池与 alias 重铸。
- [x] AgentService 连接新配置/会话/运行存储；保留本轮实际模型身份和明确模型不可用错误。
- [x] 接入 sync durability、稳定 graph thread、普通恢复与 HITL 恢复分支。
- [x] 同会话保护、去重、等待/执行期限、应用任务生命周期、重启状态扫描和显式恢复。
- [x] 操作已提交而 checkpoint 未保存时，重放读取旧结果，不重复执行业务 mutation。

## 阶段 5：REST 与飞书入口

- [x] REST chat 原字段/成功结构不变；从认证边界构造可信单管理员上下文，不接受客户端 actor。
- [x] 新增严格配置、运行查询、确认决策与显式恢复 API；沿用现有认证、CSRF、脱敏错误约定。
- [x] 飞书传入 message_id、chat_id、open_id；白名单检查在所有回复前。
- [x] 新增确定性的确认/取消、状态/恢复指令，复用原会话映射与引用回复。
- [x] 维持 SDK handler 快速返回，修复等待超时与任务状态不一致，不错误提示直接重试写入。
- [x] `/model` 文案与默认热生效、持久 override、本轮身份同步；新旧公开配置接口不含密钥。
- [x] 模型删除保护改为数据库中的非终止运行/待确认范围；闲置 override 保留并在缺失模型时明确报错。

## 阶段 6：部署、规范与交付

- [x] 移除 DSH SDK/runtime、patch、握手测试与无效 mypy/pytest 特例；只清理由本次迁移产生的孤儿代码。
- [x] Docker/Compose/ENV 示例去除活动 Workspace 依赖；保留旧数据归档与回滚说明，禁止删卷。
- [x] 更新 health 和所有 checks.dsh 消费者、容器 smoke、self-host 验收代码；站点健康与 Agent 就绪独立验证。
- [x] 同步 Agent/飞书/CRM/Talents spec、架构文档、README、测试地图及新增依赖许可声明。
- [x] 分派 trellis-check 独立核验，修复实际问题后复测相关失败项；本机首次全量及定向修复证据如实记录。
- [ ] 运行 Linux AMD64 full CI，核验完整当前集合、只读镜像、容器重建持久化及既有安全门禁。
- [ ] 汇总验证证据；原子提交并创建 PR，附加到本聊天；不自动合并或生产部署。

## 验证矩阵

| 用例 | 核心断言 | PRD |
| --- | --- | --- |
| 记录客户跟进 | 领域计划派生语义正确，ToolMessage 与事实一致 | AC1、AC2 |
| 删除客户 | 未批准零 mutation，正确原用户批准一次，级联说明与事实一致 | AC4 |
| 危险工具全覆盖 | 8 个删除工具均有执行端批准校验，MCP 不能绕过 | AC4 |
| 重复消息/键 | 同键附着原 run，不同输入冲突；不同消息可正常新增 | AC5 |
| 提交后中断 | 业务记录与操作账本同时存在，重放无第二条跟进/履历 | AC6 |
| 进程重建 | 历史、override、审批可读，running 状态转换可靠 | AC3、AC7 |
| 超时 | 停止等待不宣称未执行，可查询完成/中断/待核实状态 | AC7 |
| 并发 | 同会话写串行、跨会话并发、审批阻止抢跑 | AC8 |
| 模型配置 | 默认和 override、不可用错误、推理字段无丢失、无隐式回落 | AC3、AC9 |
| 数据库/容器 | 空库/存量升级、只读 rootfs、无 dsh 子进程、数据不丢失 | AC10 |

## 检查命令

所有数据库命令仅指向明确的测试库；先确认目标，不打印 DSN。依赖 workspace 根执行：

```bash
uv sync --frozen --all-packages --python 3.12
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
uv run pytest server/tests/agent server/tests/api/test_agent_chat.py server/tests/integrations/feishu_bot
uv run pytest server/tests/crm server/tests/rss server/tests/api/test_crm.py server/tests/api/test_talents.py
uv run pytest server/tests/migrations
uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80
uv run pytest scripts/licenses/test_collectors.py
pnpm --dir web lint
pnpm --dir web exec vitest run
pnpm --dir web build
```

迁移在 `server/migrations` 目录按现有 Alembic 方式执行；checkpoint schema 初始化使用新明确命令。容器验证与自托管 smoke 沿用 CI 命令，适配 runtime 就绪断言。实际验证时根据变更运行必需集合；相关检查通过后不无意义重复全量。

## 高风险文件与回滚点

- `agent/runtime.py`、`agent/service.py`、`app.py`：生命周期、默认模型、异常降级。
- `crm/service.py`、`talents/service.py`、25 个写工具：事务切分与操作结果原子性。
- `api/routes/agent.py`、`integrations/feishu_bot/chat_dispatcher.py`：可信身份、确认、去重与等待期限。
- `server/migrations`、test fixtures、saver setup：权限、测试隔离、schema 一致性。
- `infra/docker`、Compose、self-host、health 消费者：只读运行与升级兼容。

每阶段完成后保存验证证据与可审阅 diff；发现产品行为需要超出批准设计时回到规划。回滚保留新增表、旧卷及业务记录；不得通过 reset/删卷覆盖用户已有工作或数据。
