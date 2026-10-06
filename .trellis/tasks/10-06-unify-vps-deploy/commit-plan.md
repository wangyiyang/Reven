# 原子提交计划（2026-10-06）

## 目的与当前状态

将已实现并审阅的统一 VPS 部署变更保存到两条分支。两条分支的本地聚焦检查均已通过；尚未执行提交、推送、PR、完整 CI 或生产发布。用户已批准实施，本次按 Trellis Phase 3.4 只请求对下面实际提交批次的一次确认。

## 拟提交批次（执行顺序）

### 1. 主线修复：fix(deploy): 恢复 VPS 前后端同源部署

分支 codex/unify-vps-deploy；包含配置、直接相关回归和规范/运行文档，15 个文件：

- [.github/workflows/ci.yml](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.github/workflows/ci.yml)
- [.trellis/spec/reven-server/backend/ci-release-contract.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/spec/reven-server/backend/ci-release-contract.md)
- [.trellis/spec/reven-server/backend/open-source-self-host-contract.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/spec/reven-server/backend/open-source-self-host-contract.md)
- [CHANGELOG.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/CHANGELOG.md)
- [README.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/README.md)
- [docs/runbook.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/docs/runbook.md)
- [docs/vercel-deploy.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/docs/vercel-deploy.md)
- [infra/caddy/Caddyfile](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/infra/caddy/Caddyfile)
- [infra/compose/docker-compose.yml](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/infra/compose/docker-compose.yml)
- [scripts/self_host_http_smoke.py](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/scripts/self_host_http_smoke.py)
- [scripts/self_host_smoke.py](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/scripts/self_host_smoke.py)
- [server/tests/e2e/test_http_deployment.py](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/server/tests/e2e/test_http_deployment.py)
- [server/tests/security/test_deployment_automation.py](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/server/tests/security/test_deployment_automation.py)
- [server/tests/security/test_self_host_smoke.py](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/server/tests/security/test_self_host_smoke.py)
- [web/vercel.json](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/web/vercel.json)

### 2. 生产补丁：fix(ci): 回移 GitHub Actions 构建缓存修复

分支 codex/unify-vps-deploy-hotfix；只带主线 #209 的两条缓存参数，1 个文件：

- [.github/workflows/release.yml](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/.github/workflows/release.yml)

### 3. 生产补丁：fix(deploy): 恢复 VPS 前后端同源部署

分支 codex/unify-vps-deploy-hotfix；与批次 1 的 15 个变更文件逐字节一致：

- [.github/workflows/ci.yml](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/.github/workflows/ci.yml)
- [.trellis/spec/reven-server/backend/ci-release-contract.md](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/.trellis/spec/reven-server/backend/ci-release-contract.md)
- [.trellis/spec/reven-server/backend/open-source-self-host-contract.md](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/.trellis/spec/reven-server/backend/open-source-self-host-contract.md)
- [CHANGELOG.md](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/CHANGELOG.md)
- [README.md](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/README.md)
- [docs/runbook.md](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/docs/runbook.md)
- [docs/vercel-deploy.md](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/docs/vercel-deploy.md)
- [infra/caddy/Caddyfile](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/infra/caddy/Caddyfile)
- [infra/compose/docker-compose.yml](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/infra/compose/docker-compose.yml)
- [scripts/self_host_http_smoke.py](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/scripts/self_host_http_smoke.py)
- [scripts/self_host_smoke.py](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/scripts/self_host_smoke.py)
- [server/tests/e2e/test_http_deployment.py](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/server/tests/e2e/test_http_deployment.py)
- [server/tests/security/test_deployment_automation.py](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/server/tests/security/test_deployment_automation.py)
- [server/tests/security/test_self_host_smoke.py](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/server/tests/security/test_self_host_smoke.py)
- [web/vercel.json](/Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven/web/vercel.json)

本分支业务源码、迁移、依赖清单及锁文件保持 v0.7.1，迁移 head=0024；不合并整条补丁分支回 main，不把本次 tag 指向 main。

### 4. 主线任务记录：chore(task): 记录统一 VPS 部署规划与实施验证

分支 codex/unify-vps-deploy；仅本任务目录内的 10 个文件：

- [prd.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/prd.md)
- [design.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/design.md)
- [implement.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/implement.md)
- [task.json](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/task.json)
- [implement.jsonl](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/implement.jsonl)
- [check.jsonl](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/check.jsonl)
- [research/deployment-context.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/research/deployment-context.md)
- [research/validation-plan.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/research/validation-plan.md)
- [implementation-report.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/implementation-report.md)
- [commit-plan.md](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/tasks/10-06-unify-vps-deploy/commit-plan.md)

归档与 journal 簿记由后续 finish-work 在工作提交之后执行，不夹入这些批次。

## 未识别或预先存在的文件

- 主线修复与补丁工作树：没有未识别 dirty files。
- 原主工作区的 [/Users/wangyiyang/Documents/Github/Reven/dogfood-output/](/Users/wangyiyang/Documents/Github/Reven/dogfood-output/) 是预先存在且与本任务无关的目录，明确排除，保持不变。

## 确认与后续

回复“行”或“ok”即可按上述批次执行提交。需要调整可直接指出；回复“我自己来”则由用户手动提交。

依据 [.trellis/workflow.md Phase 3.4](/Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven/.trellis/workflow.md:626)：“Present the plan once, ask for one-shot confirmation”。这是提交批次确认，实施门禁已经满足。本步骤不会推送；提交完成后按已批准发布范围继续分支 CI、PR 与上线验收。
