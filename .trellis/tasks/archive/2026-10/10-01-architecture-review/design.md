# 总体设计：架构深化三项顺序落地

## 结论

以已有业务 module 为落点，按 CRM → 飞书消息交付 → 会话模型身份顺序深化。三个独立子任务拥有实现与验证，父任务负责需求来源、顺序、跨项兼容和最终集成检查。

## 子任务映射

| 顺序 | 子任务 | 父需求 | 具体落点 |
| --- | --- | --- | --- |
| 1 | 10-01-crm-deepening | R1 / R4 / R6 | CrmService 拥有 input + ID 的完整变更，REST / MCP 只转换传输 |
| 2 | 10-01-feishu-delivery-deepening | R2 / R4 / R6 | FeishuBotApiClient 拥有唯一交付策略，复用 HTTP reply，删除 SDK 出站 |
| 3 | 10-01-session-model-deepening | R3 / R4 / R5 / R6 | AgentService 拥有选择和生效模型，startup 共享给 REST / 飞书 |

R7 由父任务贯穿执行；具体文件、interface、测试和回滚在各子任务 design.md / implement.md。

## 关键决定与契约

### CRM

六个现有输入模型迁到 crm/inputs.py，网页 schema 显式重导出保持外部名字；CrmService 接收已验证输入及业务 ID，自行完成客户范围、缺失与事务。读路径不重写，返回 ORM 标量沿现有 expire_on_commit=False，不新造 DTO 或通用 CRUD。

MCP 收齐 contact_id / clear_contact 等字段后再判断空更新，先写复现与回归；部分更新的行动日期校验使用提交字段与旧值合并后的状态。变更后 tools_crm.py 若仍超 500 行，按完整领域 adapter 拆分，避免纯转发文件。

### 飞书

已有 HTTP 客户端增加 message_id reply，共用鉴权/错误与唯一卡片→文本策略；本地 lark SDK 源码确认协议形状，无新依赖。调用方不再传 fallback_text，结构化 Notification 两种表示由出站拥有；普通 markdown 保留正文并前置标题，不做通用 Markdown 解析。

入站 SDK callback 只 route / submit，dispatcher daemon 通过既有 bridge 回主循环发送。白名单在外显前预检；每次回复现读凭证，reply 成功用 True 与 bridge 失败 None 区分。引用回复仅同目标降级；主动通知的 chat→白名单仍由原渠道 module 拥有。

### 会话

现有 AgentService 深化为 model_state / use_model / chat，提供去凭证不可变状态和本轮结果；startup 单例由 REST / 飞书共享。override 按外部 session_id 存主循环内存，runtime 继续掌握池、resolver 与重铸，不加全局锁或持久化。

生效默认取 runtime 启动快照；注册表 is_default 表示已保存配置。两者不同时补重启提示；切换到已保存但尚未生效默认仍属 override，恢复使用实际默认。执行开始时捕获模型，执行中再切换不会改变本轮落款；strict override 失败不回落。

## 顺序与依赖

CRM 先通过；飞书没有 CRM 代码依赖，顺序来自用户要求。会话必须基于飞书迁移后的 dispatcher / app 接线处理，不能恢复第二项已删除的出站行为。执行顺序在子任务文档中明确，不把任务树当作依赖系统。

## 验证与交付

- 每项独立相关测试与 trellis-check；最后完整后端 pytest / coverage、ruff check / format、strict mypy，真实 dsh 握手单独记录。
- 测试使用独立空 PostgreSQL 库；已有 test fixtures 会 TRUNCATE，不能指向用户数据或与其他任务共用。
- 使用 uv run --frozen，保持原 uv.lock；基线 SHA256 为 9a16e44a1a009b119257576de69ce5c9a6b91c115259d4fa29028068d26587d7。
- 当前 checkout 可复用，在 main 上创建 codex/architecture-deepening 功能分支后修改产品代码；不直接提交 main。若现场变化使其不适合，使用 app 管理的隔离 worktree，并迁移本任务资料。
- 一个功能分支中按三项原子改动组织，不上线、不合并 main。最终通过 PR 交付；提交/推送按项目结束阶段实际变更和已获授权处理，不把本次规划当作完成结果。

## 风险与回滚

风险集中在 CRM 错误/部分更新/事务、飞书循环所有权/占位、会话默认快照/共享生命周期。对应测试在子任务中已具名；无产品决策遗留。

没有依赖或数据库迁移。每项可单独回滚工作改动；共享文件按顺序审阅，父任务检查前两项行为未被第三项覆盖。无需新增 ADR，决定已有明确契约与低成本回滚。
