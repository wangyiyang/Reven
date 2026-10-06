# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [CI 与发版镜像构建契约](./ci-release-contract.md) | 日常 CI 跳过容器构建、发版 full 调用与回归验证 | Active |
| [HTTPS 与开源 Alpha 自托管契约](./open-source-self-host-contract.md) | Origin/CSRF/Cookie、独立 Compose、持久化与真实验收边界 | Active |
| [Agent 原生运行契约](./agent-runtime-contract.md) | LangChain/LangGraph、数据库配置/运行、事务账本、可信确认与恢复 | Active |
| [RSS 素材采纳契约](./rss-materials-contract.md) | 本地采纳、并发与飞书审核、RSS 基础设施 | Active |
| [集成 Provider 契约](./integration-provider-contract.md) | 配置、API、凭证与退役迁移的跨层一致性 | Active |
| [飞书应用机器人契约](./feishu-app-notification-contract.md) | 应用机器人通知、测试发送、RSS 审核、部署通知与机器人对话（私聊/群@） | Active |
| [Brand Publishing Contract](./brand-publishing-contract.md) | 品牌档案、素材与模板配置，稿件发布已退役 | Active |
| [CRM Aggregate Contract](./crm-contract.md) | CRM 领域输入、完整写操作、范围与事务约定 | Active |
| [Finance Summary Contract](./finance-summary-contract.md) | Cash-status semantics for the finance summary API and UI | Active |
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | To fill |
| [Error Handling](./error-handling.md) | Error types, handling strategies | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
