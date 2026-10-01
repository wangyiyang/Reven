# 飞书消息交付深化

## Goal

让主动通知与引用回复共享同目标卡片→纯文本的交付规则，并保留完整内容和可观察失败。

## Background

- 父任务：10-01-architecture-review；用户要求的第二项，先完成并验证 CRM 子任务。
- 策略重复于 client.py:83–112 与 handlers.py:139–167；内容保留接线在 provider_clients.py:128–142 和 notify/scheduler.py:118–123。
- 静态审阅发现 SDK 直接异常路径与标题 fallback 差异，尚未声称生产缺陷已复现。

## Requirements

- R1：已有飞书出站 module 拥有卡片/文本内容、降级决策、脱敏失败；入站 handler 不直接执行出站策略。
- R2：卡片业务错误与网络异常都可在同一个目标降级到文本，文本保留标题与正文必要信息；文本再失败明确报错。
- R3：保留引用 message_id、目标类型、白名单预检、占位失败放弃、回复顺序、入站立即返回与 timeout 不取消。
- R4：定向会话失败后改投白名单仍属现有主动通知流程，不能作为引用回复的降级。
- R5：复用已有凭证与 HTTP 生命周期；不另建只有一个 adapter 的假想 seam。

## Dependency / Order

10-01-crm-deepening 的实现与验证先完成。本项与 CRM 无代码依赖，该顺序来自用户要求。

## Out of Scope

Webhook、审核卡片、outbox、队列、RSS 去重变更、新消息渠道与上线部署。

## Acceptance Criteria

- [x] AC1 / R1–R2：通知/引用回复使用同一策略；卡片成功、业务失败、网络异常、文本失败、标题/正文保留均有 interface 行为测试。
- [x] AC2 / R3：reply 的目标与引用不丢失；非白名单零回复，SDK handler 立即返回，占位失败放弃本轮，dead loop 不泄漏协程。
- [x] AC3 / R4：既有定向会话与白名单渠道测试通过，没有跨目标的引用回复兜底。
- [x] AC4 / R5：凭证测试和相关生命周期回归通过；pytest、ruff、strict mypy 通过，删除旧重复策略。

## Planning Status

具体设计见 design.md，执行与验收见 implement.md。用户已批准父任务整批方案；按 CRM → 飞书交付 → 会话模型的顺序实施和验收。

## 验收结果

2026-10-01 独立 trellis-check 通过：192 项专项测试和 39 项凭证/生命周期回归通过，0 skipped；ruff、format、strict mypy、规模和锁文件保护全部通过。见 research/check-result.md。已完成工作提交，准备归档；允许会话模型第三项开始。
