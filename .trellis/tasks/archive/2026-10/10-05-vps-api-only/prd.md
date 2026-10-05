# VPS 部署形态改为纯 API（前端只走 Vercel）

## Goal

dev.wangyiyang.cc 不再服务前端静态文件：infra/caddy/Caddyfile 去掉 file_server 只保留 /api 反代，compose 摘掉 caddy 静态卷，e2e 测试固化。自托管形态（infra/self-host）不动。

## 背景

- web 前端已部署 Vercel（reven-web-nine.vercel.app），用户决策：VPS 不再承担前端服务，前端唯一入口走 Vercel。
- 镜像仍构建 web 产物（自托管交付依赖），仅自有 VPS 的 Caddy 不再对外服务静态文件；`reven-static` 卷继续由 reven 容器写入但无人读取，留待第二期镜像 slim 化一并处理。
- 代价（已在 PRD 记录，用户知情）：失去 Vercel 故障时的兜底静态站。

## Requirements

- `infra/caddy/Caddyfile`：移除 `/assets/*` 与 SPA fallback 两个 handle 块（含 file_server/root/try_files）；保留安全响应头 snippet 与 `/api/*` 反代；非 /api 路径返回 404。两个站点块（HTTPS 主站、:3001 过渡入口）结构不变。
- `infra/compose/docker-compose.yml`：caddy 服务移除 `reven-static` 卷挂载。
- `server/tests/e2e/test_http_deployment.py`：补充断言固化"VPS Caddy 不再服务静态文件"（如无 file_server / try_files / /srv/reven 引用）。
- `CHANGELOG.md`：v0.7.1 条目补充本变更（基础设施）。
- 不动 `infra/self-host/`、不改镜像 Dockerfile（web 构建保留）。

## Acceptance Criteria

- [ ] Caddyfile 无 file_server/try_files，/api 反代保留，站点块不变。
- [ ] compose caddy 服务无 reven-static 挂载；reven 服务卷不变。
- [ ] e2e 测试覆盖新形态并通过；server 全量测试不回归。
- [ ] 自托管文件零改动（`git diff infra/self-host` 为空）。

## Notes

- 部署生效时机：随 v0.7.1 tag 的 release 流水线自动同步 infra 并 reload Caddy（deploy_reven.sh 的 sync_infra + reload_caddy 路径）。
