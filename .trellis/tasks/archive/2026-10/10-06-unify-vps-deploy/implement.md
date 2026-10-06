# 实施与发布计划

状态：主线 PR #211 已合并，v0.7.2 已从独立生产补丁发布且完成真实验收。当前产品工作与上线门禁全部完成，按 Trellis finish-work 归档并记录会话；最终证据见 implementation-report.md。

## 1. 实施前门禁

- [x] 用户在最终规划摘要之后明确批准实施；随后才 task.py start。
- [x] 创建 codex/unify-vps-deploy 主线修复分支，基于 origin/main；保留当前任务文档和主工作区已有文件。
- [x] 实施/check 采用 Trellis 代理，提示词包含 Active task 与准确工作树路径；代理不提交、推送、部署，不改未分配文件。
- [x] 当前生产基线 v0.7.1 / 2066c3c 与 digest 067d44... 已由运行镜像及成功发布日志对应；发布前重新核对环境未被其它工作改变。

## 2. 主线修复

- [x] infra/caddy/Caddyfile：恢复 assets 与 SPA handle，补 /agent/* 404；保留 API、TLS/3001、安全头。
- [x] infra/compose/docker-compose.yml：恢复 Caddy 对 reven-static 的 ro 挂载；不动其它卷、限制和端口。
- [x] web/vercel.json：git.deploymentEnabled=false，保留旧 rewrite；已核对当前项目根目录默认 .、Node 24、无 Git 连接，旧入口 source=cli。该配置适用于后续以 web 为 root 的 Git 集成，不能代替平台实际状态核验。
- [x] server/tests/e2e/test_http_deployment.py：替换纯 API/无静态卷断言，覆盖新契约。
- [x] .github/workflows/ci.yml 与 security/test_deployment_automation.py：production infra 路径选择 backend 回归，container 仍 full-only。
- [x] scripts/self_host_smoke.py、self_host_http_smoke.py 与 security/test_self_host_smoke.py：复用现有隔离烟测增加真实生产路由、资源和只读挂载验证，补新阶段失败清理；每个新增函数不超过 50 行。
- [x] docs/runbook.md：统一为 VPS HTTPS 主入口，修正直接相关的旧 HTTP-only 描述，写明本次补丁发布及故障回到混合入口。
- [x] docs/vercel-deploy.md：保留历史指导并标明统一 VPS 的目标入口；记录旧项目无 Git 连接的实况，区分仓库配置和平台状态。实际上线完成前不宣称切换已经完成。
- [x] .trellis/spec/reven-server/backend/ci-release-contract.md、open-source-self-host-contract.md：同步生产 HTTPS/静态路由、backend filter 与实际验收边界。
- [x] README 如确有相关入口缺失，只补必要链接；CHANGELOG 记录补丁部署变化，不把 main 的未上线业务功能列入补丁。

## 3. 验证主线修复

本地聚焦检查：

```bash
uv run pytest server/tests/e2e/test_http_deployment.py server/tests/security/test_deployment_automation.py server/tests/security/test_self_host_smoke.py
uv run ruff check scripts/self_host_smoke.py scripts/self_host_http_smoke.py server/tests/e2e/test_http_deployment.py server/tests/security/test_deployment_automation.py server/tests/security/test_self_host_smoke.py
sh scripts/test_deploy_reven.sh
actionlint .github/workflows/ci.yml
pnpm --filter @reven/web build
```

- [x] 使用实际可用的 uv/pnpm 环境；依赖按 frozen 锁文件安装，不改 lock 文件。
- [x] Cookie/CSRF/auth 回归用专用已迁移测试数据库；不得以 fixture skip 当作通过，不指向生产库。
- [x] 向功能分支运行 full CI；等待终态与所有 required checks，核实真实生产路由烟测阶段执行。
- [x] check 代理完成主线全范围检查与补丁边界复核，主会话同步规范及任务记录；本地检查结果见 implementation-report.md。
- [x] 依 Trellis Phase 3.4 给出实际 dirty files 的原子提交计划，用户一次性确认后提交，不夹带 dogfood-output。
- [x] 主线 PR 创建后 attach_artifact，完成审阅/检查后合并；这一步本身不发布 main 应用。

## 4. 生产补丁分支

- [x] 用受管理的独立工作树从 v0.7.1 创建 codex/unify-vps-deploy-hotfix（用户已确认本次例外）。
- [x] 回移本任务经审阅的原 15 个部署/test/docs/spec 文件及随后必要的许可包装/验证修复；从 main 带入 release.yml 的两条 gha cache 配置修复，不摘取 #207 或其它业务 commit。
- [x] 不整文件覆盖业务代码，不 reset/revert main 已有业务变化。
- [x] 比较包含未提交工作区修改的补丁与 v0.7.1，以下命令无输出；提交后再次核对：

```bash
git diff v0.7.1 -- server/src server/migrations web/src pyproject.toml server/pyproject.toml uv.lock package.json web/package.json pnpm-lock.yaml pnpm-workspace.yaml
```

- [x] check 代理完整检查补丁全部 diff，仅出现获批的部署、验证、文档和缓存变化；alembic heads 确认为 0024_rss_resilience。
- [x] 实际补丁分支独立运行聚焦 pytest、ruff/format、mypy、actionlint、前端构建和假 Docker 部署脚本测试，全部通过。
- [x] 在实际补丁分支运行原生 Linux AMD64 full CI，不用 main 的检查冒充补丁证据。

## 5. 发布与真实验收

- [x] 发布前只读检查当前 DB revision=0024、镜像仍为已确认基线、Vercel 旧入口可用；记录健康镜像历史与其它 VPS 服务状态。
- [x] 新 semver tag 计划 v0.7.2，先检查 tag 与 ACR 版本均未占用；不重写既有 tag、不使用 latest 作为部署身份。
- [x] tag 指向经过验证的补丁 commit；沿现有 release workflow 完整 gate、构建、漏洞扫描、SBOM、镜像推送及按 digest 部署。服务器不 build，不私自替换 infra。
- [x] 等待 release/deploy 的真实终态；API health 与依赖检查均 ok，Caddy 正常。
- [x] HTTPS GET 首页/login/实际深链接，提取当次 index 的 JS/CSS，验收 MIME/缓存/缺失资源 404、安全头及 /agent/* 404。
- [x] 核对 HTTP index/release 与新镜像一致，Caddy 静态挂载 ro；DB revision 仍为 0024。
- [x] 用受控真实会话验证 VPS 同源登录与业务只读页面；秘密仅留在内存，输出只保留状态与验收结果，不创建业务数据。
- [x] 验证 Vercel 不再日常 Git 自动发布；保留旧站点/白名单回退能力，记录正式 VPS 入口与用户首次需重新登录。
- [x] 记录源码、tag、digest、run 链接、测试和线上证据。不能用 health=200 或 GitHub Release 页面代替全部验收。

## 6. 故障恢复与收尾

本次发布未失败，也未发现数据库已被其它上线推进，以下条件分支未触发，不能记作实际回滚验证：

- 若新入口失败，按原 v0.7.1 完整 digest 调用现有受限部署脚本；不执行 DB downgrade、不清空数据卷。未实际执行。
- 恢复后须验证原 API + Vercel 入口；该回滚不保留 VPS 前端。未实际执行恢复验收。
- 若上线前 DB 已被其它发布推进，停止此补丁上线。发布前核对仍为 0024，本次未触发停止条件。
- [x] 实际 CI、发布、digest、数据库、可信 HTTPS 与真实会话验收已记录；正式版本说明已发布。
- Trellis 归档、journal 与记录分支合并在收尾阶段执行；仅清理本任务不再需要的受管理工作树。

## 关键文件与回滚点

Caddy/Compose 必须与发布镜像匹配；生产补丁的迁移与业务源码必须保留 v0.7.1。既有部署脚本、Dockerfile、安全扫描和 secret 管理机制不需要功能修改。新增烟测只能作用于随机测试项目和隔离数据库；生产验收不运行会 TRUNCATE 的测试 fixture。
