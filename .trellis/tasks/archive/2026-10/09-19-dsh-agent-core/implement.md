# 执行计划：dsh Agent 核心集成

> 验证命令统一在 repo 根目录执行。质量门（每步必过）：`uv run ruff check server/ && uv run mypy && uv run pytest server/tests -q`。

## M0 — 技术验证 spike ✅（2026-09-19 完成，临时 key 实测）

- [x] 0.1 linux/x86_64 wheel：**通过**——`deepseek-harness-runtime-bin 0.1.5rc1` 有 `manylinux_2_28_x86_64`/`aarch64`（PyPI 实查）
- [x] 0.2 无 key 握手：**通过**——sdk profile 拉起 + initialize（serverInfo `deepseek-harness-sdk-runtime 0.0.1`）+ close
- [x] 0.3 工具协议：**结论 = 方案 A 证伪，走 B2（MCP）**
  - sdk profile 的 JSON-RPC 仅 `initialize`/`session/prompt`/`shutdown` 三方法，无宿主工具声明入口；incoming-request 通道是用户提问/审批用途
  - 工具来自 profile 插件组合；官方 `@deepseek-ai/dsh-mcp-client`（stdio / streamable-http）
  - patch overlay 用 `- insert:` 语法可新增插件条目（纯配置，无需 pnpm）；平铺 `- id/name/config` 只能覆盖既有条目（实测报错 `entry "mcp-reven" not found`）
  - 实测通过：patch insert 注入 mcp-client → 模型原生调用 `mcp__reven__reven_add` → loopback streamable-http → Python fastmcp 执行回包
  - 注意：`dsh plugin add` 对本插件无效（其无 `dsh.bundle` 层，仅装为普通依赖）；初次失败为 spike 脚本就绪检查竞态，非协议问题
- [x] 0.4 并发：**通过**——单实例 3 线程并发 `run()` 各带独立 session_id 全部并行成功（wall≈单轮耗时），**无需 asyncio.Lock 串行化**
- 附带发现：sdk profile 默认带 bash/fs 等 coding-agent 工具，IM 场景应用 patch `disabled: true` 按 id 关掉（设计已定）

## M1 — 依赖与骨架（对应 AC1）

- [ ] 1.1 `server/pyproject.toml` 加 `deepseek-harness-sdk`（锁版本），`uv lock` 更新
- [ ] 1.2 `reven/agent/`：errors.py、config.py、runtime.py（lifespan 封装、Lock、to_thread、未配置降级）
- [ ] 1.3 `app.py` `_lifespan` 接入 `AgentRuntime`
- [ ] 1.4 `.gitignore` 加 `.dsh-runtime/`
- [ ] 1.5 测试 `server/tests/agent/`：无 key 拉起握手 + 关闭 + 未配置降级（CI 可跑）
- 回滚点：删除 agent 包与 lifespan 接入即可

## M2 — `agent-llm` 集成配置（对应 AC4）

- [x] 2.1 后端：provider 注册表加 `agent-llm`（PUT 模型：provider/model/base_url + secret api_key）✅
- [x] 2.2 前端：PROVIDERS 加 `agent-llm` 定义 ✅
- [x] 2.3 测试：8 用例（默认值/加密/不回显/校验/连接测试），184 passed ✅
- 验证：后端 pytest + 前端 `pnpm --filter @reven/web test`（若触及）

## M3 — `/agent/chat` 调试端点（对应 AC2）

- [x] 3.1~3.4 全部完成 ✅：AgentService + `POST /api/agent/chat`（挂 /api/* 下自动获得 AuthMiddleware 保护，是对 PRD 字面 `POST /agent/chat` 的安全必要修正）+ 启动失败降级 503 + M1 测试干扰根因修复（conftest env 隔离），全量 761 passed
- [x] 手动验收（AC2，2026-09-19 临时 key 实测）：DB 配置 agent-llm → 重启 → POST /api/agent/chat 真实问答返回 200 ✅

## M4 — RSS 关键词 MCP 工具集（对应 AC3，M0.3 已定 B2 路线）

- [x] 4.1~4.3 全部完成 ✅：tools_rss.py（4 工具直连 Repository）+ mcp_server.py（FastMCP streamable-http 挂 `/agent/mcp`，Bearer token，CSRF 豁免最小化）+ dsh.patch.yml（insert + disable 8 个内建工具，`--dump-config` 实测）
- [x] 4.4 测试：15 个新用例，全量绿 ✅
- [x] 手动验收（AC3，2026-09-19 实测）："帮我加一个 RSS 正向关键词：AI Agent" → 模型原生调 mcp__reven__ 工具（list→create→复查）→ `GET /api/rss/keywords` 确认落库（positive/enabled）✅
- 验收中发现的坑：`AGENT_MCP_URL` 默认 8000 端口，非标准端口部署必须显式设置（M6 文档必须写明）

## M5 — 部署落地（对应 AC5）

- [x] 5.1 Dockerfile：runtime 阶段 `mkdir -p /data/jobs /data/dsh /srv/reven`（chown 经既有 `/data` 递归覆盖），env `DSH_HOME=/data/dsh`
- [x] 5.2 `infra/compose/docker-compose.yml`：`dsh-data:/data/dsh` 卷 + `DSH_HOME` env 占位（注释说明 api_key 走集成页）；端口 8000 与 `agent_mcp_url` 默认值一致，无需覆盖；`infra/test/` 仅 postgres，无需改动
- [x] 5.3 验证：本地 `docker build -f infra/docker/Dockerfile .` 全量构建通过；镜像内 `dsh --version`=0.1.5-rc.1、`/data/dsh` reven 可写；`docker compose config -q` 通过

## M6 — 文档与同步（对应 AC6）

- [ ] 6.1 `docs/agent-architecture.md`：架构图、配置方法、自然语言 vs 确定性路径边界、部署拍板结论、配置变更需重启的限制
- [ ] 6.2 issue #119 评论：链接本文档与架构结论
- [ ] 6.3 issue #123 评论：汇报验收结果（含手动验收证据）

## 收尾

- [ ] 全量质量门 + 前端测试通过
- [ ] 清理：确认 `poc/dsh-agent/` 未进 git（勘察遗留沙盒，仅本地保留）
- [ ] Conventional Commits 原子提交（feat(server)/feat(web)/chore(infra)/docs 分提），PR 描述按金字塔原理（目的/背景/改动点/影响与风险/验收结果）
