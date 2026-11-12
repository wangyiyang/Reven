# 切换自有服务器部署与独立 DSH Agent 容器架构

## 目标与用户价值

为 Reven 打造完全自主可控的自有服务器全栈生产环境，并将 Agent 执行引擎迁回 DeepSeek Harness（DSH）以解耦的独立容器形态运行。解除受限只读 Web 容器对 Agent 原生系统能力的束缚，赋予其完整的 Workspace 操作、Linux 原生命令/文件/Skill 编排以及飞书报表附件处理能力，支持用户日常经营分析（如销售日报、库存盘点）开箱即用。

## 背景与决策依据

- 用户在综合架构考量后发起 `/grill-me` 需求对齐，并在 2026-11-12 完成全部分支决策确认。
- **基线与 LangGraph 处置**：彻底移除 `f7cbaf5` 引入的 LangGraph、`langgraph-checkpoint-postgres` 及 `0028_agent_persistence` 检查点层，以 `aec6669`（具备 37 个 CRM/人才/RSS 业务 MCP 工具的纯 DSH 实现）为基线演进。
- **同镜像双服务解耦**：
  - `reven` 主容器保持 `read_only: true` 严格安全边界，负责 Web API、飞书长连接网关、定时任务与 `/agent/mcp` 端点。
  - `agent` 独立容器运行 DSH Worker，拥有独立 `pids_limit` 并可写挂载宿主机 `/workspace` 与持久卷 `/data/dsh`。两者通过容器内网 HTTP + MCP 互相调用。
- **工作区与原生系统能力**：
  - 宿主机 `/opt/reven/workspace`（开发环境为 `./workspace`）作为 DSH 的工作目录（`cwd`）。
  - 在 `dsh.patch.yml` 中解禁 Linux 原生工具（`tool-bash`、`tool-fs`、`tool-fs-search`、`tool-skill`、`tool-subagent-control`、`tool-subagent-list-agents`、`tool-jobs`），仅保留禁用 Windows `tool-pwsh`。
  - DSH 原生加载 `/workspace/skills`，并在镜像中预装 `pandas`、`numpy`、`openpyxl`、`requests` 等报表与数据分析依赖。
  - 融合 `AGENTS.md` / `SOUL.md` / `USER.md` 的工作区助理人设与 Reven 业务工具行为约束。
- **飞书文件/附件支持**：
  - 飞书消息路由（`handlers.py` / `chat_dispatcher.py`）放开文件类型消息接收，集成飞书文件下载能力落盘到 `/workspace/downloads`，打通日常报表 Skill（如 `daily-triple-report-v2`）。
- **自有服务器部署**：
  - 目标主机为具备公网 80/443 的 Linux x86_64 (`amd64`) 自有服务器。
  - 生产 Compose 内置 `postgres:17-alpine`（`postgres-data` 卷），下线外部 Supabase 依赖，使用全新空库初始化（Alembic 自动建表）。
  - 升级 `scripts/deploy_reven.sh` 与 GitHub Actions 发布工作流，维持镜像构建与按 digest 部署交付。

## 范围与需求

| ID | 要求 | 可观察行为 |
| --- | --- | --- |
| R1 | 回退 LangGraph 并恢复 DSH 核心 | 移除 `langchain`/`langgraph` 运行时依赖与 `0028` 检查点迁移；恢复 `DeepSeekHarness` SDK 运行逻辑及 37 个业务 MCP 工具。 |
| R2 | 独立 Agent 容器化与网络互通 | Compose 中增加 `agent` 服务；`reven` 容器与 `agent` 容器通过内网 HTTP 协议交互（chat / model_state / use_model），MCP 端点维持 Bearer Token 验证回访。本地开发支持进程内直连或独立 Worker。 |
| R3 | Workspace 挂载与原生 Linux 工具 | `agent` 容器将宿主机工作区挂载到 `/workspace` 并设为 cwd；解禁 bash、fs、skill 等工具，支持读取与执行 workspace 下的 Python 脚本。 |
| R4 | Workspace Skills 与依赖环境 | 镜像内预装 Excel 与数据分析核心库；DSH 能自动发现并调用 `/workspace/skills` 下的业务 Skill；人设提示词融合 SOUL/AGENTS 规范。 |
| R5 | 飞书附件下载链路 | 飞书机器人接收到文件类型消息时不拦截，能够根据 `file_key` 和已配置的飞书集成凭据下载文件至 `/workspace/downloads`，并在对话上下文中传递本地文件路径。 |
| R6 | 自有服务器本地 Postgres 全栈 Compose | 升级 `infra/compose/docker-compose.yml`，增加本地 `postgres` 容器及卷声明，默认 DATABASE_URL 指向本地容器，并保持 Caddy HTTPS 反向代理。 |
| R7 | 自动化部署流水线与运维脚本更新 | 升级 `scripts/deploy_reven.sh`、`infra/docker/Dockerfile` 和相关运维手册，支持 postgres + agent + reven + caddy 四服务联启与健康检查。 |

## 交互与兼容约束

- REST API：`POST /api/agent/chat` 保持 `{ "message": str, "session_id": str? }` 请求与 `{ "session_id": str, "response": str }` 响应契约。
- 飞书对话：保持私聊与群聊 `@` 机制、白名单校验、`/model` 指令；增加文件类型消息的提示与下载落盘。
- 安全边界：`reven` Web 容器依然保持 `read_only: true`；仅 `agent` 容器开放 workspace 可写与 shell 执行权限。外部公网依然只能访问 Caddy（80/443），`reven` 与 `agent` 的内部端口均不向宿主机公网暴露。
- 数据库兼容性：生产直接初始化全新空库，Alembic 迁移至 `0027_merge_heads`（不包含 `0028`）。

## 验收条件

| ID | 对应需求 | 验收标准 |
| --- | --- | --- |
| AC1 | R1 | 移除 LangGraph 依赖，`server/tests/agent/` 和业务工具集单元测试全量通过，DSH 运行时接口恢复正常。 |
| AC2 | R2 | `agent` 服务能作为独立 Worker 启动，`reven` 容器能正常发起对话请求并经 MCP streamable-http 完成工具回调。 |
| AC3 | R3, R4 | 在 DSH 会话中触发 bash/fs/skill 工具能成功读取 `/workspace` 文件，执行 Python 报表脚本无缺失依赖报错。 |
| AC4 | R5 | 飞书发送 Excel 附件被正确保存至 `/workspace/downloads/`，Agent 收到包含文件路径的提示词并能触发分析。 |
| AC5 | R6 | `infra/compose/docker-compose.yml` 包含 postgres、reven、agent、caddy，一键 `docker compose up -d` 全栈 healthy。 |
| AC6 | R7 | `scripts/deploy_reven.sh` 与 Dockerfile 构建测试通过，健康检查能验证全栈状态。 |
| AC7 | 全部 | 代码风格与质量门禁（ruff format/check, mypy, pytest）全绿。 |

## 不纳入本次范围

- 多租户与多用户隔离系统（保持单管理员模式）。
- 在 Web 前端构建图形化工作区文件管理器。
- 历史 Supabase 存量旧数据迁移（已确认直接空库初始化）。
