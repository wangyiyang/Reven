# 技术设计：自有服务器全栈与独立 DSH Agent 容器架构

## 1. 总体架构拓扑

```mermaid
flowchart TD
  subgraph Public["公网入口"]
    Browser["用户浏览器 / 移动端"]
    Feishu["飞书开放平台 (Webhook / 长连接)"]
  end

  subgraph Host["自有服务器宿主机 (Linux amd64, /opt/reven)"]
    WS[("/opt/reven/workspace\n• AGENTS.md / SOUL.md\n• skills/\n• memory/\n• downloads/")]
    
    subgraph Docker["Docker Compose 内部隔离网络"]
      Caddy["caddy:2.10.0-alpine\n80/443 入口反代 + TLS\n挂载静态文件卷 :ro"]
      
      Reven["reven 容器 (FastAPI 主站)\n• REST API (/api/*)\n• 飞书 WebSocket 入站\n• 定时调度 / RSS\n• MCP 端点 (/agent/mcp)\n• read_only: true"]
      
      Agent["agent 容器 (DSH 独立 Worker)\n• HTTP 服务 (8001)\n• DeepSeekHarness 子进程池\n• 原生 Bash / FS / Skill 执行\n• 读写挂载 /workspace :rw\n• 持久卷 /data/dsh :rw"]
      
      PG[("postgres:17-alpine\n• postgres-data 卷\n• 5432 内部端口")]
    end
  end

  Browser -->|HTTPS :443| Caddy
  Feishu -->|WSS 连接| Reven
  Caddy -->|内部 HTTP :8000| Reven
  Reven <-->|asyncpg :5432| PG
  Reven -->|内部 HTTP :8001 /internal/agent/*| Agent
  Agent -->|MCP streamable-http 回调\nhttp://reven:8000/agent/mcp| Reven
  Agent <-->|文件读写 / 脚本执行| WS
  Reven -->|飞书附件落盘| WS
```

## 2. DSH 运行引擎与同镜像 Worker 设计

### 2.1 同镜像双角色设计
为避免构建和维护两套 Dockerfile 与流水线，保持单镜像多模式：
- `reven` 主角色（默认 entrypoint）：执行 Alembic 迁移、静态文件切换、启动 Uvicorn `reven.app:app`（端口 8000）。
- `agent` Worker 角色（容器 `command: ["/app/.venv/bin/python", "-m", "reven.agent.worker"]`）：启动 Uvicorn 监听内部端口 8001，专门托管 `DeepSeekHarness` 生命周期与模型池。

### 2.2 内部通信协议 (Worker API)
Worker 在 8001 端口暴露受限内部端点（仅 Docker 内部网络互通，不对外映射）：
- `POST /internal/agent/chat`：
  - 请求：`{ "message": str, "session_id": str | null, "override_model_ref": str | null }`
  - 响应：`{ "session_id": str, "response": str, "actual_model_ref": str | null }`
- `GET /internal/agent/model_state?session_id=...`：
  - 响应：`{ "effective_model_ref": str | null, "override_model_ref": str | null, "default_model_ref": str | null }`
- `POST /internal/agent/use_model`：
  - 请求：`{ "session_id": str, "model_ref": str }`
  - 响应：`SessionModelState`
- `GET /internal/agent/health`：返回 Harness 运行状态。

### 2.3 双工调用模式兼容
在 `reven.agent.service` 中抽象 `AgentClient`：
- **RemoteWorkerAgentClient**：当配置了 `AGENT_WORKER_URL`（容器生产环境指向 `http://agent:8001`）时，通过内部 HTTP client 调用独立 Agent 容器。
- **InProcessAgentClient**：本地单机开发或单元测试未配置 Worker URL 时，直接在本进程通过 `AgentRuntime` 拉起 `DeepSeekHarness`，无需强制启动独立容器，保持极致开发体验。

## 3. 工作区与 DSH 工具配置设计

### 3.1 DSH Patch (`dsh.patch.yml`)
在保留 MCP 回调的前提下，恢复原生系统能力：
```yaml
- insert:
    - id: mcp-reven
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: reven
        transport: streamable-http
        url: !!js process.env.REVEN_AGENT_MCP_URL
        headers:
          Authorization: !!js '"Bearer " + process.env.REVEN_AGENT_MCP_TOKEN'
        toolCallTimeoutMs: 30000

# 仅禁用 Windows 专属 pwsh，全面开放 Linux 工具
- id: tool-pwsh
  disabled: true

# 注入融合人设指令与行为约束
- id: system-prompt
  config:
    personaPrefix: You are a coding agent powered by the {{model}} model.
    personaSuffix: |-
      Your working directory is {{cwd}}.
      你兼具工作区全能助理（小龙虾）与 Reven 业务副手的双重角色：
      1. 优先阅读工作区中的 AGENTS.md, SOUL.md 和 USER.md，遵循已建立的人设、记忆与习惯。
      2. 你可以直接运行 Linux Shell 命令、读写文件并加载 /workspace/skills 下的业务 Skill。
      3. 处理数据分析与报表时，充分利用 Python 脚本（已预装 pandas/openpyxl/requests）完成。
      4. 你可以通过 mcp__reven__* 工具调用 Reven 内部的 CRM、人才库和 RSS 业务。
      5. 涉及重要业务删除前（如 rss_keyword_delete / crm_delete_*），必须向用户复述并获得明确确认。
```

### 3.2 工作区挂载与依赖预装
- `cwd` 设置为 `/workspace`（绑定宿主机 `/opt/reven/workspace`）。
- `dsh_home` 设置为 `/data/dsh`（独立持久卷，存储 profile 与会话缓存）。
- 依赖层：在 `server/pyproject.toml` 的依赖项中恢复 `deepseek-harness-sdk`，并新增 `pandas>=2.2.0`, `openpyxl>=3.1.0`，使报表分析脚本能免配置运行。

## 4. 飞书文件接收与附件下载链路

### 4.1 消息路由升级
- 修改 `handlers.py` 的 `route_message`：
  - 允许 `message.message_type in ("text", "file")`。
  - 对于 `file` 类型的消息，提取其 `file_key` 和 `file_name`。
- 修改 `chat_dispatcher.py`：
  - 当收到文件消息时，利用现有的飞书集成凭证（`IntegrationCredentials.feishu()`）获取 `tenant_access_token`。
  - 调用飞书 OpenAPI 资源下载端点：`GET /open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=file`。
  - 安全写入 `/workspace/downloads/{file_name}`（自动处理重名防覆盖）。
  - 将提示语组合为：
    `[用户发送了文件，已下载至工作区: /workspace/downloads/{file_name}]\n{附加说明或要求}`。
  - 投递至 Agent，触发对应的报表 Skill（如 `daily-triple-report-v2`）。

## 5. 自有服务器全栈 Compose 设计

### 5.1 服务编排 (`infra/compose/docker-compose.yml`)
```yaml
services:
  postgres:
    image: postgres:17-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193
    restart: unless-stopped
    environment:
      POSTGRES_DB: reven
      POSTGRES_USER: reven
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Generate POSTGRES_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    mem_limit: 1g
    healthcheck:
      test: [CMD-SHELL, pg_isready -U reven -d reven]
      interval: 5s
      timeout: 3s
      retries: 20

  reven:
    image: ${REVEN_IMAGE}
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      agent:
        condition: service_healthy
    env_file:
      - ../../.env
    environment:
      DATABASE_URL: postgresql+asyncpg://reven:${POSTGRES_PASSWORD}@postgres:5432/reven
      AGENT_WORKER_URL: http://agent:8001
      WORKSPACE_ROOT: /workspace
    volumes:
      - reven-data:/data
      - reven-static:/srv/reven
      - /opt/reven/workspace/downloads:/workspace/downloads:rw
    read_only: true
    mem_limit: 1.5g
    cpus: 1.5

  agent:
    image: ${REVEN_IMAGE}
    restart: unless-stopped
    command: ["/app/.venv/bin/python", "-m", "reven.agent.worker"]
    env_file:
      - ../../.env
    environment:
      DSH_HOME: /data/dsh
      WORKSPACE_ROOT: /workspace
      REVEN_AGENT_MCP_URL: http://reven:8000/agent/mcp
    volumes:
      - /opt/reven/workspace:/workspace:rw
      - dsh-data:/data/dsh:rw
    mem_limit: 2g
    cpus: 2.0
    pids_limit: 512
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/internal/agent/health', timeout=3)"]
      interval: 10s
      timeout: 5s
      retries: 10

  caddy:
    image: caddy:2.10.0-alpine@sha256:ae4458638da8e1a91aafffb231c5f8778e964bca650c8a8cb23a7e8ac557aa3c
    restart: unless-stopped
    depends_on:
      reven:
        condition: service_healthy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ../caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - reven-static:/srv/reven:ro
      - caddy-data:/data
      - caddy-config:/config
```

## 6. 数据库迁移与依赖清理

1. **依赖精简**：
   - 移除 `langchain`, `langchain-core`, `langchain-deepseek`, `langchain-openai`, `langgraph`, `langgraph-checkpoint-postgres`, `psycopg`, `psycopg-binary`, `psycopg-pool`。
   - 恢复 `deepseek-harness-sdk>=0.1.5rc1,<0.2`。
   - 引入 `pandas>=2.2.0`, `openpyxl>=3.1.0`。
2. **Alembic 迁移**：
   - 删除 `server/migrations/versions/0028_agent_persistence.py`。
   - 最新 Head 回归 `0027_merge_heads.py`。
   - 彻底移除 `reven.agent.checkpoint` 及 PostgreSQL 专属 schema 创建逻辑。

## 7. 部署脚本升级 (`scripts/deploy_reven.sh`)
- `deploy_reven.sh` 需验证 `postgres`、`agent`、`reven`、`caddy` 四大服务的容器健康状态。
- 如果宿主机不存在 `/opt/reven/workspace`，自动创建并初始化基础权限，支持本地 workspace 同步。
