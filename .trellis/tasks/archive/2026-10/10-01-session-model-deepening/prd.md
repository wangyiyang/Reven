# 会话模型身份深化

## Goal

让会话的模型选择、可用性与实际生效结果由同一个业务 module 解释，并可通过同一 interface 验证。

## Background

- 父任务：10-01-architecture-review；用户要求的第三项，CRM 与飞书消息交付依次通过验证后实施。
- 原接线：chat_dispatcher.py:205–254 与 runtime.py:94–98,137–192；AgentService 仅转发，REST 依赖目前按请求创建。
- 选择状态不能机械移进现有临时对象；运行中默认来自 startup 快照，保存配置变更需重启生效。

## Requirements

- R1：共享 Agent 业务入口集中模型选择与生效语义，同一进程的 REST / 飞书使用同一个实例；override 仍按外部 session_id 隔离并保存在内存。
- R2：飞书保留确定性命令、IM 会话映射与文案；runtime 保留池、懒启动、别名和 dsh 错误机制。
- R3：模型判断与展示以实际生效默认为准，现读注册表默认变化不清除正确 override 或假称新默认已生效。
- R4：指定模型未注册或不可用不得静默回落；保留配置重启生效、无 resume、重铸别名、启动降级与禁止全局锁。
- R5：业务结果用同一 interface 验证，复用真实 runtime 与 fake harness，避免只断言内部字典。

## Dependency / Order

10-01-feishu-delivery-deepening 必须先完成并通过验证。本项继续修改 dispatcher / app 装配，基于第二项结果迁移，避免恢复旧回复接线。

## Out of Scope

REST / 前端新增模型选择、配置热更新、状态持久化、上游 resume、全局锁、历史策略变更与上线部署。

## Acceptance Criteria

- [x] AC1 / R1：REST 与飞书装配同一 Agent 业务对象；会话选择在跨调用时保持，群内用户相互隔离。
- [x] AC2 / R2–R4：现有命令矩阵与 strict override 错误通过；运行中修改注册表默认不会改变生效默认或错误清空 override。
- [x] AC3 / R5：模型切换→实际 fake harness 身份→恢复默认→已存在会话重铸后继续的组合行为测试通过。
- [x] AC4 / R4–R5：runtime 池/关闭/别名回归通过，pytest、ruff、strict mypy 通过，无状态持久化或全局锁。

## Planning Status

具体设计见 design.md，执行与验收见 implement.md。用户已批准父任务整批方案；按 CRM → 飞书交付 → 会话模型的顺序实施和验收。

## 验收结果

2026-10-01 独立 trellis-check 与三项整体验收通过：787 passed / 0 skipped，coverage 90.30%；真实 dsh 握手、ruff、format、strict mypy、规模与锁保护通过。见 research/check-result.md 和父任务 research/final-validation.md。已完成工作提交，准备归档。
