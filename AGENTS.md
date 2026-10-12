<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

## Cloud Agent 本地运行

Cloud Agent 启动后会拉起 PostgreSQL 17、API（`127.0.0.1:8000`）和 Vite（`http://localhost:5173`）。浏览器访问 `http://localhost:5173`，Vite 把 `/api` 代理到后端。

- 工具链：Node `22.22.2` 在 `/usr/local/lib/node-v22.22.2`，pnpm `10.13.1`，uv `0.12.1`，Python `3.12`。若 `node -v` 低于 `22.22.2`，把该目录的 `bin` 放到 `PATH` 前面。
- 首次启动会在 `~/.config/reven/dev.env`（权限 `600`）生成数据库密码、`REVEN_MASTER_KEY` 和 `REVEN_ADMIN_PASSWORD`。登录密码只看这个文件，不要提交它，也不要重新生成主密钥，否则已保存的集成凭据无法解密。
- `TEST_DATABASE_URL` 指向可丢弃的 `reven_test`。测试会清空该库多张表，迁移测试还会创建临时库。不要把 `TEST_DATABASE_URL` 指到 `reven_dev` 或任何需要保留的库。跑 pytest 时不要把 `REVEN_MASTER_KEY` 留在进程环境里：`Settings.model_validate({})` 仍会读取环境变量，主密钥存在时 `test_lifespan_skips_supervisor_when_settings_unavailable` 无法模拟配置缺失。与 CI 一样，测试进程只设置指向 `reven_test` 的 `DATABASE_URL`、`TEST_DATABASE_URL` 和 `REVEN_ADMIN_PASSWORD`。
- API 与 Vite 分别在 tmux 会话 `reven-api`、`reven-web`。改完代码后重启对应会话即可；不要停掉 PostgreSQL 集群里别人的数据。
- 语言层检查命令见 [CONTRIBUTING.md](CONTRIBUTING.md)。AI、飞书和对象存储不在本地启动范围内。
