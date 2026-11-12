# Agent DSH 运行契约

## 1. 范围与架构

本项目采用 DeepSeek Harness (DSH) 独立容器架构部署：
- 生产环境采用单镜像双容器（`reven` 主服务 + `agent` DSH Worker 服务）。
- `reven`（只读根文件系统，暴露 FastAPI Web / 飞书 Bot 网关 / FastMCP 工具端点 `:8000/agent/mcp`）。
- `agent`（可写根文件系统工作区 `/workspace`，运行 DSH Worker HTTP 进程 `:8001/internal/agent/*`）。
- 两容器共用 `AGENT_MCP_TOKEN`，缺省时由 `reven_master_key` 经 HMAC-SHA256 派生确定性 Token。
- DSH 工作区目录绑定至 `/workspace`（挂载宿主机 `/opt/reven/workspace`），运行时缓存与内部会话位于 `DSH_HOME=/data/dsh`（Docker 持久卷）。

## 2. 核心行为与工具策略

### 工具解禁与 Linux 原生能力
- 解禁工具：`tool-bash`、`tool-fs`、`tool-fs-search`、`tool-skill`、`tool-jobs`、`tool-subagent-*`。
- 禁用工具：仅禁用 Windows 专属 `tool-pwsh`。
- 人设注入：通过 `dsh.patch.yml` 将 `SOUL.md` 与 `AGENTS.md` 注入系统提示词，明确工作区助手定位，具备执行报表分析与文件处理的能力，写操作前进行业务确认。

### 飞书附件与报表自动化
- 飞书 Bot 支持接收 `file` 类型消息，从飞书 API 下载附件落盘至 `/workspace/downloads/`。
- 注入工作区分析提示词，指导 Agent 调用内置 Skill（如 `daily-triple-report-v2`、`full-inventory-check`）和 Python 数据科学栈（`pandas`、`openpyxl`）进行自动化处理。

## 3. 通信与退化处理

- `RemoteAgentWorkerClient` 实现 `AgentRuntimeProtocol`，通过 HTTP 调用 Worker 服务。
- Worker 启动失败或未配置时，透明退化并向用户返回明确提示，不影响主站与飞书基础功能。
