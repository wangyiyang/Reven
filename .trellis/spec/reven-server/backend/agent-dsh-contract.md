# Agent DSH 契约已退役

2026-10-06 用户批准用 LangChain/LangGraph 与 PostgreSQL 替换 DSH。当前实现遵守 [原生运行契约](agent-runtime-contract.md)。旧 SDK 子进程、模型池、内存 override、alias 重铸、Workspace、120 秒兜底及 patch 指令不再是实现约束。

旧架构用于历史核对和旧镜像回滚，见 [DSH 架构快照](../../../../docs/history/agent-dsh-architecture-20261006.md) 和 Git 历史；现有 CRM/人才/RSS 领域规则继续生效。
