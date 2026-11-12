# 实施计划：自有服务器部署与独立 DSH Agent 容器架构

## 阶段划分与有序清单

### 阶段 1：清理 LangGraph 依赖并恢复 DSH 核心

- [ ] **1.1 依赖定义与锁文件清理**
  - 修改 `server/pyproject.toml`：移除 `langchain`, `langgraph`, `psycopg` 相关依赖；加回 `deepseek-harness-sdk`；引入 `pandas>=2.2.0`, `openpyxl>=3.1.0`。
  - 根目录 `pyproject.toml` 同步更新。
  - 执行 `uv lock` 与 `uv sync`。
- [ ] **1.2 数据库迁移清理**
  - 删除 `server/migrations/versions/0028_agent_persistence.py`。
  - 确认最新 Alembic head 为 `0027_merge_heads`。
- [ ] **1.3 DSH 运行时核心代码恢复**
  - 恢复并优化 `server/src/reven/agent/runtime.py`（基于 `aec6669` 的 `DeepSeekHarness` 实例池、超时重铸与降级逻辑）。
  - 恢复 `server/src/reven/agent/config.py` 与 `dsh.patch.yml`。
  - 移除 LangGraph 检查点与图构建代码（`checkpoint.py`, `graph.py` 等）。
  - 保留并确保全部 37 个 CRM、人才、RSS MCP 业务工具（`mcp_server.py`, `tools_*.py`）完全对齐。

### 阶段 2：独立 Agent Worker 与双模式通信解耦

- [ ] **2.1 实现 DSH Agent Worker 服务**
  - 新增 `server/src/reven/agent/worker.py`：微型 FastAPI 应用，监听 8001 端口，托管 `AgentRuntime` 生命周期。
  - 提供 `/internal/agent/chat`、`/internal/agent/model_state`、`/internal/agent/use_model`、`/internal/agent/health`。
- [ ] **2.2 客户端协议与双工模式抽象**
  - 在 `server/src/reven/agent/service.py` 中抽象 Worker Client：
    - `RemoteWorkerAgentClient`：当设置 `AGENT_WORKER_URL` 时，通过 HTTP 调用独立 Worker 容器。
    - `InProcessAgentClient`：未设置 Worker URL 时，直接在本进程复用 `AgentRuntime`（本地开发与单机测试无缝支持）。
  - 维持 `AgentService.chat()`、`model_state()`、`use_model()` 接口不变。

### 阶段 3：工作区挂载与原生 Linux 工具 / 人设融合

- [ ] **3.1 开放 DSH 原生工具**
  - 更新 `dsh.patch.yml`：解禁 `tool-bash`、`tool-fs`、`tool-fs-search`、`tool-skill`、`tool-jobs`、`tool-subagent-*`，仅禁用 Windows 专属 `tool-pwsh`。
- [ ] **3.2 工作区人设与行为提示词整合**
  - 在 `dsh.patch.yml` 的 `system-prompt` 中整合 `AGENTS.md` / `SOUL.md` 人设规范、Skill 使用指导及 Reven 业务确认规则。
  - 将 DSH 的 `cwd` 绑定为工作区目录（支持通过 `WORKSPACE_ROOT` 环境变量覆盖，默认 `/workspace` 或本地 `workspace/`）。

### 阶段 4：飞书文件接收与附件下载链路

- [ ] **4.1 消息路由支持文件类型**
  - 修改 `server/src/reven/integrations/feishu_bot/handlers.py`：允许 `message_type == "file"`，提取 `file_key` 和 `file_name`。
- [ ] **4.2 附件安全下载与上下文注入**
  - 在 `server/src/reven/integrations/feishu_bot/chat_dispatcher.py` 中实现基于飞书开放平台资源的下载逻辑，保存至工作区 `downloads/` 目录。
  - 包装用户 prompt 并转交 Agent，打通数据报表 Skill。

### 阶段 5：自有服务器全栈 Compose 与部署脚本改造

- [ ] **5.1 生产 Compose 全栈编排**
  - 更新 `infra/compose/docker-compose.yml`：
    - 增加 `postgres:17-alpine` 服务与 `postgres-data` 卷。
    - 增加 `agent` 独立 Worker 服务，声明 `command`、挂载工作区与 `dsh-data` 卷。
    - `reven` 主服务连接本地 `postgres` 与 `agent` Worker，保持 `read_only: true`。
- [ ] **5.2 容器入口与镜像清理**
  - 更新 `infra/docker/entrypoint.sh`：移除 `reven.agent.checkpoint` 调用。
  - 更新 `infra/docker/Dockerfile` 预装系统工具及 Python 报表依赖。
- [ ] **5.3 自动化部署脚本与文档升级**
  - 更新 `scripts/deploy_reven.sh`：健康检查验证全栈容器状态，自动准备工作区。
  - 更新 `docs/agent-architecture.md`、`docs/runbook.md`、`docs/self-hosting.md`。

### 阶段 6：全量门禁与测试回归

- [ ] **6.1 测试代码适配**
  - 移除旧的 `test_native_graph.py`、`test_persistence.py` 等 LangGraph 专属用例。
  - 恢复并更新 DSH 单元测试与 Worker 协议测试。
- [ ] **6.2 质量门禁验证**
  - 执行 `uv run ruff check` 与 `uv run ruff format --check`。
  - 执行 `uv run mypy server/src`。
  - 执行 `uv run pytest server/tests` 全量回归。
