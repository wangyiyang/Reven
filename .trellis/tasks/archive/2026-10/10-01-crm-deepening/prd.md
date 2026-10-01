# CRM 客户跟进变更深化

## Goal

让 REST 与 MCP 使用同一个完整的 CRM 变更行为，减少调用方需要理解的实体查找、客户范围与事务知识。

## Background

- 父任务：10-01-architecture-review；用户选择全部三项，本项为第一项。
- 已确认接线：api/routes/crm.py:176–184 与 agent/tools_crm.py:403–414；既有业务规则在 crm/service.py:43–81。
- 现有两个入口正确完成范围查找，本项不宣称已有归属漏洞。

## Requirements

- R1：输入校验、实体缺失与客户范围判断由 CRM module 拥有，变更入口不要求调用方先查 ORM。
- R2：REST 与 MCP 保持请求/响应、工具名、错误码/中文提示和显式清空语义；读路径保持现有查询方式。
- R3：保留主联系人、历史快照、当前计划和一次事务提交语义，不泛化跨领域 CRUD。
- R4：移除因深化而失去用途的接线，函数不超过 50 行；被修改且超过 500 行的文件按真实职责分解。

## Out of Scope

新 CRM 功能、数据迁移、财务/项目通用 CRUD、前端改造与上线部署。

## Acceptance Criteria

- [x] AC1 / R1：两个入口不再重复取实体、判断缺失后传 ORM 给 mutator。
- [x] AC2 / R1–R3：共享 interface 的真数据库测试覆盖范围、缺失、主联系人、快照、部分更新、清空字段与历史/当前计划差异。
- [x] AC3 / R2：现有 REST 和 MCP adapter 的序列化、校验错误及请求形状测试通过。
- [x] AC4 / R4：相关 pytest、ruff check / format、strict mypy 通过，数据库用例没有因未配置而跳过；函数/文件长度已核对。

## Planning Status

具体设计见 design.md，执行与验收见 implement.md。用户已批准父任务整批方案；按 CRM → 飞书交付 → 会话模型的顺序实施和验收。

## 验收结果

2026-10-01 独立 trellis-check 通过：58 passed / 0 skipped；ruff、format、strict mypy、MCP/REST schema 兼容性及 500/50 行限制全部通过。见 research/check-result.md。已完成工作提交，准备归档；允许第二项开始。
