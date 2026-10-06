# 仓库个人绑定清理

> 父任务：09-29-open-source-alpha-release（Issue #127 子任务 #2）。

## Goal

清除仓库中面向外部读者的个人环境绑定（代码默认值、根模板、冒烟脚本、.gitignore 缺口），使陌生用户照抄默认值也不会连到维护者环境。

## Background

- 差距清单（HEAD 核查）：`server/src/reven/config.py:18` 默认 `http://dev.wangyiyang.cc:3001`；根 `.env.example` 含个人域名/个人 COS bucket/私有 ACR 镜像；`scripts/smoke.sh:4` 默认同域名；`.gitignore` 未排除 `workspace/`、`.coverage`、`sync-to-notion.sh`（仅靠"未跟踪"隔离，有误 `git add -A` 风险）。
- 维护者生产链路（`infra/caddy/`、`infra/compose/`、`deploy_reven.sh`、`validate_reven_image.sh`、`test_deploy_reven.sh`、`docs/runbook.md`、`.github/workflows/release.yml`）按父任务 R3 **保留个人值**，不在本任务范围。
- **用户决策（2026-09-29）：`.trellis` 内容保留在仓库中**，本任务不处理 `.trellis` 的本机路径与 journal。

## Requirements

1. `.gitignore` 增加：`workspace/`、`.coverage`、`sync-to-notion.sh`。
2. `config.py` `public_base_url` 默认值改为 `http://localhost:8080`（与 `docs/self-hosting.md` 回环模式 origin 一致），同步更新 `server/tests/test_config.py:20` 的默认值断言。其余测试中将该域名用作任意 origin 夹具的（CSRF/headers/conftest 等）不动。
3. 根 `.env.example` 通用化：`PUBLIC_BASE_URL`、`COS_BUCKET`、`COS_PUBLIC_BASE_URL` 改为中性占位（保留 `ap-beijing` 地域示例值）；`REVEN_IMAGE` 去除个人命名空间，保留 sha256 digest 占位格式并加注释说明生产用 digest。
4. `scripts/smoke.sh` 默认 `BASE_URL` 改为 `http://localhost:8080`（`REVEN_BASE_URL` 覆盖机制不变）。
5. 保留不动（明确范围外）：`.trellis/`、`docs/runbook.md`、`docs/superpowers/`（历史设计稿含个人域名，另行与用户确认去留）、维护者生产链路与 `release.yml`。

## Acceptance Criteria

- [ ] `git grep dev.wangyiyang.cc` 在"允许清单"外零命中
- [ ] `git check-ignore workspace/ .coverage sync-to-notion.sh` 全部命中
- [ ] `server/tests/test_config.py` 更新后通过；`bash -n scripts/smoke.sh` 语法通过
- [ ] 改动以 PR 合入 main（GitHub Flow，不直接提交 main）

## Out of Scope

- `.trellis` 内容（用户决策保留）
- GHCR 公开镜像流程（子任务 #3）
- `docs/superpowers/` 与 `docs/runbook.md` 的个人域名（维护者文档分层，待用户复查）
