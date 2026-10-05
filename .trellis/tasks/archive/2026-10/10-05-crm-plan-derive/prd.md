# CRM 历史与计划派生化（#201 P1）

## Goal

删除 `Customer.next_*` 双写字段，跟进计划派生自最新跟进记录，消灭双写不一致；为后续与 talents 域统一到期语义打底（issue #201 P1）。

## Background

- 现状：`Customer.next_action / next_follow_up_on` 与最新 `FollowUp.next_*` 双写，靠 `set_as_current`（默认 false）手动同步，更新/删除跟进不回填客户 → 两处数据会脱节。
- 决策（已在 issue #201 锁定）：派生优于双写。计划的唯一权威来源 = 该客户 `occurred_on` 最新一条跟进记录上的 `next_action / next_due_on`。无存量数据，migration 可破坏性重建。
- 产品行为变更：新建客户时不再填「下一步行动 / 下次跟进日期」；创建后引导用户立刻记第一条跟进。

## Requirements

- R1 删除 `Customer.next_action` 与 `Customer.next_follow_up_on` 字段（ORM、migration、输入校验、API schema、agent 工具、web 表单/类型），含 DB 层配对 check 约束的清理。
- R2 删除 `set_as_current` 参数及 `CrmService.create_follow_up` 中的客户回写逻辑。
- R3 `FollowUp.next_follow_up_on` 全链路改名 `next_due_on`（ORM、migration、schemas、inputs、agent 工具、web 类型与组件、测试），与 talents 域命名对齐。
- R4 「下次跟进计划」改为派生读模型：取该客户 `occurred_on` 最新一条跟进（并列时 `created_at` 再 `id` 倒序）的 `next_action / next_due_on`。客户列表、客户详情、今日待跟进、到期提醒、dashboard due card 全部改用派生值；`due` 过滤（overdue/today/upcoming/none）语义不变、时区规则不变（Asia/Shanghai）。
- R5 新建客户表单移除计划字段；创建后给出「记第一条跟进」引导（web 空态/按钮 + agent 工具描述话术）。
- R6 跟进记录的配对校验保留：设 `next_due_on` 必须有非空 `next_action`（应用层校验 + DB check 约束）。
- R7 `.trellis/spec/reven-server/backend/crm-contract.md` 同步为新契约（Phase 3.3）。

## Non-Goals

- talents 域的任何改动（其 `min(next_due_on)` → 最新记录语义的统一在后续阶段处理）。
- 方式枚举合并（「会议」→「面谈」）留待 P3 前后处理，本期不动。
- `Contact`、客户状态机、搜索范围的任何变化。
- issue #201 的 P2/P3/P4（Talent 画像、agent 工具、搜索扩展）。

## Acceptance Criteria

- [ ] `crm_customers` 表无 `next_action` / `next_follow_up_on` 列及相关 check 约束；`crm_follow_ups.next_follow_up_on` 更名为 `next_due_on`；migration 可 upgrade 到 head、可 downgrade 回退。
- [ ] 创建/更新客户的 REST 与 MCP 入参不再接受计划字段；`Customer` 响应中的 `next_action / next_due_on` 为只读派生值（来自最新跟进，无跟进时为 null）。
- [ ] 创建跟进不再出现 `set_as_current`；记一条带计划的跟进后，客户级读路径（列表/详情/待跟进/提醒/dashboard）立即呈现该计划，无任何客户表写入。
- [ ] 更新/删除跟进后，派生计划随之变化（删除最新一条则回退到次新的计划或 null）。
- [ ] 新建客户表单无计划字段，存在「记第一条跟进」引导；agent 工具描述含同等引导。
- [ ] `next_due_on` 无 `next_action` 仍在 REST/MCP/DB 三层被拒。
- [ ] server 测试（api/agent/migration）与 web 测试全绿；lint、typecheck 通过。

## Notes

- 决策依据与四期全貌见 issue #201：https://github.com/wangyiyang/Reven/issues/201
