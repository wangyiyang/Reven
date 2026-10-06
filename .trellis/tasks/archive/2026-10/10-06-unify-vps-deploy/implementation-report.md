# 统一 VPS 部署验收记录（2026-10-06）

## 结论与发布范围

v0.7.2 已成功上线，前端与 API 通过 https://dev.wangyiyang.cc 同源访问。主线长期修复经 PR #211 正常合并；生产 tag 指向从 v0.7.1 制作且独立验证的补丁。上线数据库仍为 0024_rss_resilience，没有发布 main 的 0025/0026 或后续 CRM/人才库业务变更。

Supabase、COS、dsh 0.1.5rc1、单 worker 与数据卷保持原配置。原主工作区预先存在的 dogfood-output/ 未改动、未提交。没有创建生产业务测试数据，也没有重启其它 VPS 服务。

## 源码与发布身份

| 项目 | 实际结果 |
| --- | --- |
| 主线原基线 | origin/main 6166389772d7ea61cd562f0546ad577cb81bf275 |
| 主线提交 | 2658a131f735fa56bbfa05675a2ccfaed4270b2c 部署修复；cef6047bfa5e16b967793c7452d3d6634e2f67f9 任务记录；d413d3132a34a901f0fa8dc033bb529a25935334 许可包装与验证修复 |
| 主线 PR / 合并 | [#211](https://github.com/wangyiyang/Reven/pull/211)；dd2429cba82a0c543b7e4beb45e550cb45dd351b；2026-10-06T03:19:41Z |
| 生产原基线 | v0.7.1 / 2066c3c39823bf68b4539b8c25a022b55b274bc1 |
| 补丁提交 | de206fd37ce3768f2113eab6d2be583f64001b9e 缓存修复；d3d112a5679633a17f8527f73d784f82ef1697c7 部署修复；81fce80b6d679e09ef5577eb8a80bb6220e573f2 许可包装与验证修复 |
| 正式版本 | [v0.7.2](https://github.com/wangyiyang/Reven/releases/tag/v0.7.2)，tag 指向 81fce80b6d679e09ef5577eb8a80bb6220e573f2 |
| 发布流水线 | [37408786222](https://github.com/wangyiyang/Reven/actions/runs/37408786222)，全部 7 个任务成功，完成于 2026-10-06T03:32:30Z |
| 新镜像 | registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven@sha256:19f246c897f4b08952daeebe714ee3e96e74066bba42dc0b894873746cd69bba |
| 静态 release | 852dda787bd9224e569825c7801570886759d9ba8fe1a1b481bf3865db26850b |
| index SHA-256 | 6e79bea2482ab4cb8b65d75dc51ba0f587ed8028769ae893b68ccc2da173d740 |

发布镜像日志中的 v0.7.2 digest 与生产容器 Config.Image 完全相同；entrypoint 的 image release、current/.release 与 current 指向均一致。前端业务源码未变化，因此 index 哈希与 v0.7.1 相同；不能只凭 index 哈希证明新部署，实际镜像 digest 和静态 release 均已核对。

补丁相对 v0.7.1 的 server/src、server/migrations、web/src、依赖清单与锁文件均无差异，alembic heads 唯一为 0024_rss_resilience。没有修改 Dockerfile，没有把整个补丁分支合并回 main。

## 实际变更

- Caddy 恢复 SPA、独立 assets 路由，页面 no-cache，assets 一年 immutable；缺失 assets 与 /agent/* 返回 404，/api/* 独立反代。
- Caddy 以 ro 挂载原 reven-static 卷，应用仍可写；镜像已有前后端产物及配套 infra，保留迁移成功后原子切换 current 的入口。
- production Caddy/Compose 与 scripts/licenses/** 路径选择 backend 回归；container 仍 full-only，backend 加入许可收集器测试。
- 扩展既有隔离烟测，以真实 production Compose 为基底，复用独立 PostgreSQL/environment/depends_on；清空 env_file，使用本地测试镜像、随机项目和 loopback 8443。生产 site_common 保持原样，仅测试站点改为 localhost，显式信任测试 CA，失败后清理。
- 同步运行手册、Vercel 历史说明、README、CHANGELOG、第三方许可声明和部署规范；Vercel 仓库配置声明禁用 Git 自动部署。
- 原子提交计划于用户回复“行”后执行；后续完整 CI 暴露的许可包装问题按同一任务必要修复另作原子提交，未升级依赖或降低扫描门禁。

## 本地与完整 CI 证据

| 验证 | 结果 |
| --- | --- |
| 两条分支的部署相关 pytest + 许可收集器回归 | 各 41 passed，无 skip |
| ruff / format、strict mypy | 均通过；mypy 137 个文件 |
| node 语法、actionlint、git diff --check | 均通过 |
| 两条分支的前端类型检查与 Vite build | 均通过，保留原 large chunk 警告 |
| 假 Docker 部署脚本回归 | 两条分支均通过 |
| Trellis implement/check 上下文 | 各 4 项有效；全范围审阅问题已修正 |
| [主线 full CI 37407930825](https://github.com/wangyiyang/Reven/actions/runs/37407930825) | head=d413d31，5 个任务全部成功 |
| [实际补丁 full CI 37407941917](https://github.com/wangyiyang/Reven/actions/runs/37407941917) | head=81fce80，5 个任务全部成功；collector 6、backend 894、migration 10 项通过，后端覆盖率 89.16% |
| tag 正式发布的完整质量门禁 | head=81fce80，原生 Linux AMD64，5 个质量任务全部成功 |
| tag 镜像构建 / 扫描 / SBOM / ACR 与 GHCR 推送 / 部署 | image 与 deploy 任务成功，使用固定 digest |

本机为 linux/aarch64，未把本机容器或 ARM 仿真当作正式 AMD64 证据。完整 CI 真实执行了数据库与认证回归，没有以 fixture skip 冒充通过。tag 容器日志再次核实以下三个通过标记：

- Self-host HTTP, authentication, saved RSS materials, volumes and licenses passed.
- Self-host HTTPS passed with an explicitly trusted test CA and Secure session cookies.
- Production Caddy routes, image assets, read-only shared volume and same-origin HTTPS passed.

## 首轮扫描失败及修复边界

首轮主线 run 37406597651 与补丁 run 37406608589 的 Trivy 扫描失败；其它已通过阶段不能将这两次完整 CI 记为成功。失败来自 tinypool 1.1.1 的开发依赖 manifest 被原样复制进许可目录，在镜像内两处被 SBOM 登记为模块。

修复停止输出完整 package.json，保留 inventory 中真实名称、版本、许可、来源、证据与原 manifest_sha256；清理旧副本时仅删除内容与原 manifest 字节完全相同的文件，不同内容显式失败。LICENSE/COPYRIGHT/嵌套 NOTICE 原文与哈希保留，实际本地采集核对 383 个包、378 条证据。运行容器烟测检查两处许可 inventory 一致且证据哈希正确，并检查不存在完整 JS 包 manifest。

最终补丁 CI 的 SBOM 含 204 个组件，许可 manifest 组件为 0，tinypool runtime 组件为 0。Trivy 版本、CRITICAL 参数、既有 ignore-unfixed 行为、Dockerfile、安全门禁与依赖锁均未变化。

开发/构建工具 tinypool 漏洞没有通过依赖升级修复，后续升级仍需单独处理；不能宣称开发环境已无风险，也不能把 SBOM 当作嵌入式 dsh 程序的完整代码审计。细节见 research/license-inventory-scan.md。

## 生产验收与 A1–A8 映射

| 验收 | 实际证据 |
| --- | --- |
| A1 页面与深链接 | 可信公网 HTTPS 下 /、/login、/crm、/talents、/rss/candidates、/rss/sources、/rss/keywords 与 CRM 深路径均返回正确 index、text/html、no-cache；实际浏览器 CRM/人才库/RSS 列表页面打开与刷新均通过。 |
| A2 资源与边界 | 当次 index 引用 /assets/index-2OjcdsDJ.js 与 /assets/index-C0bdQV26.css；MIME、public/max-age=31536000/immutable、安全头均通过；缺失 assets 为 404 且非 SPA index。 |
| A3 镜像与卷 | 生产 image/current release 与 index 匹配；应用与 Caddy 均挂 compose_reven-static，Source 一致，应用 RW=true、Caddy RW=false；Caddy running，应用 healthy。 |
| A4 认证/API | health JSON 的 db/dsh/background_runner 均 ok；匿名 me/CRM/人才库/RSS 均 401；内部 /agent/mcp GET/POST 均 404。真实浏览器单次管理员登录成功，Cookie Secure、HttpOnly、SameSite=Lax、host-only、Path=/；CRM/人才库/RSS/sources/keywords 只读 API 均 200；浏览器运行错误 0；注销 204，之后 me=401，隔离浏览器关闭。 |
| A5 正式配置回归 | 两条分支及 tag 的原生 AMD64 full CI 均真实执行生产 Caddy 网关烟测；隔离数据库、显式可信 CA、随机项目与失败清理均通过。 |
| A6 Vercel 状态 | 平台只读复核 link=null，历史入口可信 HTTPS 200；没有 Git 自动发布。createDeployments 仍 enabled，不能声称已关闭平台开关；旧项目与 Origin 白名单保留。 |
| A7 补丁/数据库边界 | 补丁业务/迁移/依赖相对 v0.7.1 无差异；真实 DB 上线前后均 0024_rss_resilience，无 downgrade、无 0025/0026。 |
| A8 发布链 | 主线 #211 正常保护合并；tag v0.7.2 首次创建前 Git 与 ACR 均未占用；tag->81fce80->成功 release run->固定 digest->运行镜像对应。其它 VPS 服务未改动。 |

生产 CRM 与人才库当前没有现有记录，未验证真实记录详情页面；没有为此制造生产测试数据。CRM 深路径的 HTTP SPA fallback 与实际列表/RSS 深链接刷新已验证。没有执行模型对话、外部 RSS 真实模型流程或生产业务写入；dsh/background_runner 仅检查健康状态，真实认证及写入安全契约在隔离 CI 中验证。

## Vercel 与其它服务核查

旧入口 reven-web-nine.vercel.app 对应 reven-web / prj_2wDJKDopTmLq1kgscRH1RBK3o2zR；历史 deployment dpl_31YGd8pwoUqpV3oBZcJcDk1QBRyA 为 READY / production / source=cli / gitSource=null。项目 rootDirectory=null（默认 .）、Node 24.x、link=null、createDeployments=enabled。仓库禁用声明仅适用于将来实际读取 web/vercel.json 的集成，没有删除、重新部署或修改平台项目。

上线前后的 oll-portal、oll-cms、oll-server 的 container ID、image ID、StartedAt、PortBindings、health 全部逐项相同且 healthy，相关端口仍为 3000、28653、18080。Reven 沿用既有 80/443/3001，没有改其它服务。

## 回退与收尾

原健康镜像为 registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven@sha256:067d44f6d0698f61e7f2ee182d05b2b2b57a349d6a5fe0c472a940c600f390d7，与 v0.7.1 成功 run 37336544856 对应。恢复该 digest 及对应 infra 会回到 VPS API + Vercel 页面形态，VPS 根页面重新 404；没有 schema 变化，不需要数据库降级。本次发布没有失败，未实际执行生产回滚，故不把回滚恢复验收记为已完成。

首次访问 VPS 域需重新登录，旧 Vercel Cookie 不迁移。任务记录在独立 codex/unify-vps-deploy-record 分支从合并后的 main 更新，随后依 trellis-finish-work 归档与记录 journal；不重复提交产品变化，不把生产补丁分支合并回 main。原主工作区既有未跟踪文件继续保留。
