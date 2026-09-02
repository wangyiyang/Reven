# PRD · #83 部署同步 infra 漂移

## Goal

确认发布流程已将仓库 `infra/` 作为不可变发布资产同步到 `/opt/reven/infra/`，并用验证证据关闭已由 PR #86 修复但仍开放的 #83。

## Confirmed Facts

- commit `672a408` 已将 `infra/` COPY 到镜像 `/opt/reven-release/infra/`。
- `scripts/deploy_reven.sh` 会导出并校验发布 infra，精确同步目标目录，健康检查后按需 reload Caddy，失败时恢复原配置。
- `scripts/test_deploy_reven.sh` 覆盖变更/未变更 Caddy、回滚、健康检查失败、reload 失败及资源清理。

## Requirements

- 运行现有部署集成测试与 CI 对应检查。
- 若测试通过且实现满足 #83，不重复实现；在 Issue 留下 commit/测试证据后关闭。
- 若测试失败，仅修复已证实的回归。

## Acceptance Criteria

- [x] 镜像内发布资产路径稳定为 `/opt/reven-release/infra/`。
- [x] 部署会同步 compose、Caddyfile、seccomp 等 infra 文件并清理陈旧文件。
- [x] Caddyfile 变化时 reload，不变化时跳过；失败回滚可验证。
- [x] `sh scripts/test_deploy_reven.sh` 通过，#83 关闭。

## Verification

- 当前 `main`：`75a0181`；PR #86 的修复提交：`672a408`。
- `dash -n scripts/deploy_reven.sh scripts/test_deploy_reven.sh scripts/testdata/fake_deploy_docker.sh` 通过。
- `sh scripts/test_deploy_reven.sh` 通过，覆盖精确同步、陈旧文件清理、Caddy 变化/未变化、rollback、健康检查失败、reload 失败与临时资源清理。
- `uv run pytest server/tests/security/test_deployment_automation.py -q`：3 项通过。
- `main` CI run `33511321077` 的 container job 成功，包含真实镜像构建、内嵌 infra 字节级比对与部署同步/恢复测试。
- GitHub Issue #83 已于 2026-09-02 关闭，关闭评论已附 PR、commit、本地测试与 CI 证据。

## Out of Scope

- 修改发布触发策略或执行一次生产部署。
