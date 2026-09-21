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
| [Agent (dsh) 集成契约](./agent-dsh-contract.md) | dsh 嵌入式子进程、MCP 工具通道、配置/部署/测试约定 | Active |
| [RSS 素材采纳契约](./rss-materials-contract.md) | 本地采纳、并发与飞书审核、RSS 基础设施 | Active |
| [Brand Publishing Contract](./brand-publishing-contract.md) | 品牌档案、素材与模板配置，稿件发布已退役 | Active |
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
