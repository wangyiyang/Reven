# Reven Vercel 清理记录（2026-10-06）

## 结论

已通过本地 Vercel CLI 50.11.0 删除 Reven 的旧项目、部署及默认域名，服务器中的旧 Vercel Origin 白名单也已移除并生效。当前前端/API 仍由 VPS 同源提供，生产镜像与数据库版本没有改变。本次按用户选择直接执行，未建立 Trellis 任务。

## 精确范围与结果

| 对象 | 清理前身份 | 删除后验证 |
| --- | --- | --- |
| 项目 | reven-web / prj_2wDJKDopTmLq1kgscRH1RBK3o2zR | 项目 API 404，团队项目清单中不存在 |
| 团队 | wangyiyangkk-outlookcoms-projects / team_1pMPmcnGSZbtuMvQ02NuxJQS | 仅删除上述项目 |
| 部署 | dpl_31YGd8pwoUqpV3oBZcJcDk1QBRyA | 部署 API 404 |
| 默认域名 | reven-web-nine.vercel.app | HTTPS 404 / DEPLOYMENT_NOT_FOUND |
| 项目别名 | reven-web-wangyiyangkk-outlookcoms-projects.vercel.app | HTTPS 404 / DEPLOYMENT_NOT_FOUND |
| 部署专属地址 | reven-5zpjr0llk-wangyiyangkk-outlookcoms-projects.vercel.app | HTTPS 410 / GONE |
| 域名与别名记录 | 1 个项目默认域名、2 个部署别名，无自定义域名 | 项目域名 API 404；团队 alias 全量分页清单中无 Reven 项目或这两条历史别名 |

删除前冻结的项目、部署、域名清单不含环境变量或凭据。删除命令明确指定团队：

```bash
vercel remove reven-web --scope wangyiyangkk-outlookcoms-projects --yes
```

CLI 返回 Removed 1 project。随后核对 API 与 URL 的真实状态，而不是仅以命令退出码判断完成。Vercel 的 410 表示部署地址已退役，本次没有把它误报为旧站仍可用。

同团队的 kiyo（prj_rbuzTgvCHkF3OkM1GwV7XYgsuWzs）和 lichun（prj_6rAHr8Y88CtsKeJUn4AUuHCJd8AK）仍存在、ID 和名称与删除前一致。本地 CLI 及其账户登录保留；仓库根目录和 web 下均没有 .vercel 本地关联目录，没有需要删除的本地关联文件。没有删除账户、其它项目、自定义域名或第三方存储。

## VPS 配置与复验

仅将 /opt/reven/.env 中的 REVEN_CSRF_ALLOWED_ORIGINS 从旧 Vercel Origin 置为空，保留其它字段、文件权限和属主；以原固定镜像对 reven 服务执行 no-deps/no-build 重建并等待健康，不重建 Caddy，也不清空数据卷。失败恢复分支未触发。

- 有效 public_base_url 仍为 https://dev.wangyiyang.cc，csrf_allowed_origins=[]。
- 镜像仍为 registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven@sha256:19f246c897f4b08952daeebe714ee3e96e74066bba42dc0b894873746cd69bba。
- 实际数据库 revision 仍为 0024_rss_resilience，未执行 0025/0026、未升级依赖或 dsh。
- VPS health 的 db/dsh/background_runner 均 ok；可信 HTTPS 页面与同源管理员登录成功。
- me、CRM、RSS 只读 API 均为 200；注销为 204，随后 me 为 401，隔离浏览器已关闭。
- 旧 Vercel Origin 携带 CSRF 头向登录接口发起请求，实际返回 403 / csrf_validation_failed。
- 没有创建生产业务数据，没有输出密码、Cookie、数据库连接串或其它秘密。

核对时 OLL 三项服务在独立的 oll Compose 项目中发生了后续更新（启动时间约 03:51 UTC），当前均 healthy，端口未变。本次仅操作 compose 项目的 reven 服务（启动于 03:49:40 UTC）；没有对 OLL 运行部署或恢复命令，不能用此前 VPS 发布会话的容器 ID 当作此次清理的新基线。

## 退役后的回滚边界

旧 Vercel 页面回退入口已不存在，禁止将原 v0.7.1 的纯 API 镜像回滚视为整站恢复：它会令 VPS 根页面返回 404，而且旧 Vercel 站点已经删除。若需保持完整站点，应使用包含 VPS 前端路由与静态卷挂载的兼容镜像，并按运行手册校验数据库兼容性。本次没有实际执行回滚。

仓库 web/vercel.json 与本文链接的历史部署说明仅作为历史对照及禁用 Git 自动部署声明，不表示平台上仍有 Reven 项目；现有 VPS 不依赖 Vercel 代理。未来创建 Vercel 项目属于新的部署决定，不能照搬旧回退假设。

主工作区已有的独立域名迁移任务与 dogfood-output/ 保留，本次没有实施域名迁移或改 DNS。历史版本说明和此前统一 VPS 验收快照保留，当前运维状态以本记录及运行手册为准。

相关官方依据：[CLI remove](https://vercel.com/docs/cli/remove)、[删除项目的关联范围](https://vercel.com/docs/projects/managing-projects#deleting-a-project)、[alias 清单接口](https://vercel.com/docs/rest-api/aliases/list-aliases)。
