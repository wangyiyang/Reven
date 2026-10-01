# 架构深化三项落地：CRM、飞书交付与会话模型

## Goal

按 CRM → 飞书消息交付 → 会话模型身份的顺序，消除重复的业务操作接线、消息降级规则和模型状态解释，提高 module 的 depth、locality、leverage 与可测试性。

## Background

- 用户先请求架构审视，并同意创建 Trellis 任务；报告阶段（原 R1–R6 / AC1–AC5）已完成，证据与验证保留于 research/。
- 用户现已选择三个候选全部依次处理，而非只深入一个候选。
- 审视基线为 main / 2a0fc6188ab2435d271c3933f5cc7f32ef9890e8；用户原有 uv.lock 改动不属于本任务。
- 完整原始证据：research/hotspot-deepening.md；HTML 报告：/Users/wangyiyang/.tmp/architecture-review-20261001-180511-950282.html。
- 09-22 已完成的凭证、Settings、连接测试、Web CRUD 与路由深化不重议。

## Requirements

- R1 / CRM：共享 module 拥有实体查找、客户范围、有效输入、变更规则与提交；REST / MCP 入口保留各自传输转换和错误表达。补覆盖 tools_crm.py:391–402 的仅关联/解除联系人的更新路径，先复现后修复。
- R2 / 飞书：消息交付规则只有一份，统一卡片与纯文本的内容保留、失败降级和脱敏错误；区分同目标表示降级与定向会话失败后的渠道选择。
- R3 / 会话：集中会话模型选择、可用性和实际生效模型的业务解释；飞书拥有指令语法与 IM 会话映射，runtime 拥有模型池、dsh 和别名重铸。
- R4 / 兼容：保持外部请求/响应、错误码、MCP 工具名、清空字段和事务语义；保留飞书白名单、占位顺序、入站立即返回和超时不取消。
- R5 / 运行时：配置默认模型仍需重启生效，会话 override 保持内存态，指定模型不可用不得静默回落；不新增全局锁或 resume 机制。
- R6 / 验证：按顺序实施和独立验收；共享规则在深化后的 interface 上验证，保留必要的 adapter 请求形状与错误映射测试，替换重复规则覆盖。
- R7 / 文档与交付：领域名称和已确认契约及时记录；GitHub Flow、Conventional Commits 与原子提交，不直接提交 main，不改动用户现场；本次修改函数不超过 50 行、相关代码文件不超过 500 行。

## Out of Scope

- 新业务功能、前端模型选择、配置热更新、会话状态持久化、数据库迁移或上线部署。
- 通用 CRUD、消息队列、新的配置注册抽象、无关代码整理或跨领域重构。
- 重议已完成深化、dsh 无 resume、启动失败降级、别名重铸和禁止全局锁等既定决定。

## Acceptance Criteria

- [x] AC1 / R1：REST 与 MCP 调用共同的完整 CRM 变更行为；客户范围、缺失、主联系人、快照、部分更新和当前计划规则均有可观察测试。
- [x] AC2 / R2：通知与引用回复共享交付策略；卡片业务错误/网络异常均可同目标降级，纯文本保留必要内容；两次失败明确报错且脱敏。
- [x] AC3 / R3–R5：同一业务 interface 验证切换模型→实际执行模型→恢复默认→会话重铸后继续；默认变更不产生展示/执行矛盾，生命周期正确。
- [x] AC4 / R4–R6：既有外部行为回归通过；CRM 真数据库用例不得因缺环境被视作成功，飞书入站/白名单/占位/超时覆盖保留。
- [x] AC5 / R6：相关测试、ruff 检查/格式、strict mypy 及后端整体验证通过，运行环境限制如实报告。
- [x] AC6 / R7：领域与契约资料更新；每项独立可审阅，交付可验证结果，原有 uv.lock 未被本任务修改。

## Task Map

1. 10-01-crm-deepening → R1：CRM。
2. 10-01-feishu-delivery-deepening → R2：飞书；第1项验收后开始。
3. 10-01-session-model-deepening → R3 / R5：会话；第2项验收后开始。

R4 / R6 / R7 为跨子任务验收，父任务负责集成检查与交付。

## Planning Status

三个子任务的需求、设计、执行计划及 implement/check context 已齐。具体决定包括 CRM input + ID、唯一 HTTP 出站、startup 共享 AgentService；完整研究分别在 research/crm-delivery-plan.md 与 research/session-plan.md。没有遗留用户产品决策。用户于 2026-10-01 明确回复“请你开始实施。”，整批方案已批准；第一项 CRM 已启动，后续子任务按验收结果依次启动。

## 整批验收结果

三个子任务已按指定顺序实施并独立验收。最终完整后端 787 passed / 0 skipped，coverage 90.30%，质量与500/50规模检查通过，真实dsh握手通过，原有uv.lock保留。详细记录见 research/final-validation.md；具体工作提交计划见 research/commit-plan.md。第3.4阶段整批提交方案已获用户确认，四个工作提交已完成；准备归档并记录会话，未推送。
