# 统一 VPS 部署实施记录（2026-10-06）

## 结论与当前边界

主线修复与 v0.7.1 生产补丁已经实现并完成本地检查及审阅。当前尚未提交、推送、创建 PR、触发完整 CI 或上线；生产仍沿用此前镜像。本记录不会把本地检查当作完整 CI 或线上验收结果。

## 两条分支

| 分支 | 工作树与基线 | 实施内容 |
| --- | --- | --- |
| codex/unify-vps-deploy | /Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven；origin/main=6166389772d7ea61cd562f0546ad577cb81bf275 | 15 个部署、测试、文档与规范文件，加本任务规划及实施记录。 |
| codex/unify-vps-deploy-hotfix | /Users/wangyiyang/.codex/worktrees/unify-vps-hotfix/Reven；v0.7.1=2066c3c39823bf68b4539b8c25a022b55b274bc1 | 同样 15 个文件，另加 release.yml 两条缓存参数；没有复制任务目录。 |

原主工作区 /Users/wangyiyang/Documents/Github/Reven 的 dogfood-output/ 保持不变，不属于本任务。

## 实际部署变化

- 正式 Caddy 恢复 SPA 与独立 assets 路由，页面 no-cache，assets 一年 immutable；缺失 assets 与 /agent/* 返回 404；/api/* 独立反代。
- Caddy 以 ro 挂载原 reven-static 卷，使用同一镜像中的 web 产物；原迁移后原子切换 current 的入口保持不变。
- production Caddy/Compose 路径选择 backend 回归，container 仍 full-only。
- 扩展既有 self-host 烟测，在独立阶段以真实 production Compose 为基底，复用隔离 PostgreSQL/environment/depends_on，清空 env_file、指定本地镜像与 loopback 8443；生产 site_common 保持原样，测试 CA 显式信任。
- HTTP 检查镜像 index/release、深链接、实际 JS/CSS MIME/缓存、安全头、同源 Cookie/CSRF、只读共享卷以及阶段失败清理。
- 同步运行手册、历史 Vercel 部署说明、README、CHANGELOG 和两个部署规范。没有修改 Dockerfile、业务代码、依赖或数据库迁移。

## 本地检查与审阅结果

| 检查 | 主线修复 | 实际生产补丁 |
| --- | --- | --- |
| 3 个部署相关 pytest 文件 | 34 passed，无 skip | 34 passed，无 skip |
| ruff check / format check | 通过 | 通过 |
| strict mypy（server/src + 两个 smoke 脚本） | 137 个文件通过 | 137 个文件通过 |
| actionlint | ci.yml 通过 | ci.yml 与 release.yml 通过 |
| pnpm --filter @reven/web build | 通过 | 通过 |
| sh scripts/test_deploy_reven.sh（假 Docker） | 通过 | 通过 |
| git diff --check | 通过 | 通过 |
| Trellis context 清单 | implement/check 各 4 项有效 | 不复制任务目录 |
| 全范围 check 代理 | 发现的类型/文档问题已修正并复验 | 补丁边界只读复核通过 |

依赖安装均使用 frozen 锁文件与独立虚拟环境。现有 Vite 的大 chunk 警告没有阻断构建，也未扩大范围处理。

补丁相对 v0.7.1 的 server/src、server/migrations、web/src、7 个依赖清单/锁文件完全无差异；15 个回移文件与主线逐字节一致。唯一额外变化为 release.yml 的 registry cache 切换至 gha。alembic heads 返回 0024_rss_resilience，无 0025/0026。原 Dockerfile 的 runtime/CVE 修复保留。

本机 Docker 为 linux/aarch64，未运行正式原生 AMD64 容器烟测；数据库认证完整回归与真实 production HTTP 容器阶段须在两条实际分支的 full CI 补齐，不把 ARM 仿真或数据库 fixture skip 计为通过。

## Vercel 平台实况（只读 API）

- 历史入口 reven-web-nine.vercel.app 属于 reven-web 项目 prj_2wDJKDopTmLq1kgscRH1RBK3o2zR。
- deployment dpl_31YGd8pwoUqpV3oBZcJcDk1QBRyA 为 READY / production / source=cli，gitSource=null；alias 包含历史入口。
- 项目 rootDirectory=null（默认 .）、nodeVersion=24.x、link=null；gitProviderOptions.createDeployments=enabled。
- 当前无 Git 连接，因而没有日常持续 Git 自动发布，本次无需改平台。web/vercel.json 的 git.deploymentEnabled=false 是未来 root=web 且项目实际读取时的保护；不能声称当前平台开关已关闭。
- 保留历史项目/部署和现有 Origin 白名单，VPS 上线后再次核验。没有删除项目或重新发布 Vercel。

## 尚待完成

1. 按实际文件提交计划完成 Trellis Phase 3.4 的一次确认；随后提交、推送分支并创建/附属主线 PR。
2. 两条分支分别执行原生 Linux AMD64 full CI，确认数据库/认证与真实生产容器烟测实际执行且终态成功。
3. PR 检查与审阅通过后合并主线修复；生产 tag 只指向获验证的补丁提交，不发布 main 的业务迁移。
4. 发布前重新核对 v0.7.1 digest、数据库 0024、Vercel 回退可用，以及新 patch tag/ACR 版本未占用。
5. 沿现有 release workflow 发布和 digest 部署，完成可信 HTTPS 页面/资源、真实同源登录、只读业务页面、镜像/静态卷与数据库 revision 的线上验收。
6. 若失败，恢复原 v0.7.1 digest 与对应 infra，回到 API + Vercel 混合入口，不做数据库降级；实际恢复仍须核验。
7. 最终 Trellis 归档和 journal 在工作提交及发布验收后执行。
