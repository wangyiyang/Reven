# 统一 VPS 部署现状与上线基线

日期：2026-10-06。所有生产动作均为只读核查，没有改配置、登录尝试或触发部署。

## 可复用的链路

- main：`6166389772d7ea61cd562f0546ad577cb81bf275`。
- Dockerfile 已构建 web、携带 API 和 `/opt/reven-release/infra`；现有 release workflow 构建统一镜像并用完整 ACR digest 部署。
- app entrypoint 先 `alembic upgrade head`，再原子更新静态 `current`；迁移失败不切换新版静态。
- 最新 runtime/perl CVE 修复与 GitHub Actions cache 修复必须保留；不整文件回退 Dockerfile 或 release.yml。
- 恢复生产静态卷与 Caddy 路由，可复用 self-host 的 API / agent-404 / assets / SPA 结构。

## 线上核查

| 项目 | 观察结果 |
| --- | --- |
| `https://dev.wangyiyang.cc/` | 404 |
| `https://dev.wangyiyang.cc/api/health` | 200 JSON；db/dsh/background_runner 均 ok |
| `https://reven-web-nine.vercel.app/` | 200 HTML |
| `.env` 的 PUBLIC_BASE_URL | `https://dev.wangyiyang.cc` |
| `.env` 的 REVEN_CSRF_ALLOWED_ORIGINS | `https://reven-web-nine.vercel.app` |
| 正在运行的 ACR digest | `sha256:067d44f6d0698f61e7f2ee182d05b2b2b57a349d6a5fe0c472a940c600f390d7` |
| 镜像 OCI version/revision 标签 | 未提供；不能单靠 digest 宣称对应某源码提交 |
| 只读 `SELECT version_num FROM alembic_version` | `0024_rss_resilience` |

公开入口与白名单核查仅读取三个指定非秘密配置。镜像核查只输出身份；数据库核查仅 SELECT alembic_version，没有业务数据输出或写入。

## 线上源码身份补充核查

2026-10-06 用户选择仅恢复统一部署后，继续只读核对发布身份：

- [成功 release run 37336544856](https://github.com/wangyiyang/Reven/actions/runs/37336544856) 的 event=push、head_branch=v0.7.1、head_sha=2066c3c39823bf68b4539b8c25a022b55b274bc1、conclusion=success。
- 从该 run 日志仅提取目标 digest，发现 sha256:067d44f6d0698f61e7f2ee182d05b2b2b57a349d6a5fe0c472a940c600f390d7，与上一轮 VPS 当前镜像一致。
- tag 的 release workflow 默认 checkout 事件源码，单镜像构建没有另一业务源码 ref；因此该发布 run 将线上镜像与 v0.7.1 / 2066c3c 对应。
- v0.7.1..main 的 release.yml 仅改两条缓存参数到 type=gha；可单独带入补丁，不引入业务变更。

## 版本与迁移风险

- GitHub 最新 tag 为 v0.7.1（`2066c3c39823bf68b4539b8c25a022b55b274bc1`）；GitHub Releases/latest 返回 v0.7.0，说明 Release 页面不能当作部署基线。
- `git diff v0.7.1 main --name-only -- server/migrations` 包含 env.py、0025_crm_plan_derive.py、0026_talent_profile.py；新增迁移来自 #207 / `a1bfc5c`。
- `0025_crm_plan_derive.upgrade` 删除 crm_customers 的 next_action / next_follow_up_on，跟进字段改名；downgrade 只重建空客户字段，不还原删除值。
- `0026_talent_profile` 新增人才联系方式、preferences 与履历/院校表。
- 现网只有 0024，直接部署 main 会自动执行以上迁移。统一部署本身不需要业务 schema 改动；该夹带变更需要用户决定上线范围。
- 部署脚本不会自动启动旧 app image 或降级数据库；旧镜像不能视作完成 0025 后的直接恢复方案。
- 用户已选择独立部署补丁，线上 digest 的发布 run/source 关联已如上核实；补丁基线固定为 v0.7.1。发布前仍重新核对线上状态，不能把旧核查当作并发发布后的现状。补丁分支例外已明确，主线修复仍走 main PR。

## Vercel 收拢

官方 Git Configuration 文档明确支持在 vercel.json 配置 `git.deploymentEnabled: false` 来关闭所有分支的 Git 自动部署。项目 root directory 据交接为 web，实施时再核对真实项目设置；保留已有 rewrite 和历史部署，不删除项目。

来源：[Vercel Git Configuration](https://vercel.com/docs/project-configuration/git-configuration#turning-off-all-automatic-deployments)，2026-10-06 查阅。

旧 Vercel 域的会话 Cookie 不会转移到 VPS 域，用户首次访问 VPS 需要重新登录。保持旧 Origin 白名单作为过渡，可用于上线故障时回到原混合入口；彻底移除旧入口不在当前已确认范围内。

## 实施候选范围

- infra/caddy/Caddyfile、infra/compose/docker-compose.yml。
- web/vercel.json。
- server/tests/e2e/test_http_deployment.py。
- .github/workflows/ci.yml、server/tests/security/test_deployment_automation.py。
- scripts/self_host_smoke.py、scripts/self_host_http_smoke.py、server/tests/security/test_self_host_smoke.py：仅扩展既有隔离烟测及失败清理回归，避免新增框架。
- docs/runbook.md、docs/vercel-deploy.md；README 如有必要仅补当前维护入口链接。
- .trellis/spec/reven-server/backend/ci-release-contract.md、open-source-self-host-contract.md：同步生产 HTTPS/静态路由与验证边界。
- CHANGELOG.md：在最终发布基线确认后记录此次部署变化。

上线范围已由用户选择选项 1 收敛，正式 design.md 与 implement.md 已写入；仍需用户在看到最终规划后批准实施。
