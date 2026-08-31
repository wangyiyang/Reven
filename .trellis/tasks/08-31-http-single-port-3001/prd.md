# 入口切换 HTTP 单端口 3001 并加固部署回滚

## Goal

Reven 入口从 80 端口迁移到自定义单端口 3001（保持 HTTP-only），与宿主机"域名+端口"的多服务访问模式对齐；同时修复本次部署事故暴露的回滚脚本缺陷，避免同类故障重演。

## Background

- 部署目标是开发者本机，宿主机运行多个非 HTTPS 服务（如 3000 端口的博客），统一通过 `域名:端口` 访问。
- HSTS 按主机名生效、不区分端口：一旦某服务下发 HSTS，浏览器会把同域名**所有端口**强制升级为 HTTPS，打挂其他 HTTP 服务。这是 #90 切换 HTTP-only 并移除 HSTS 的根因；同理 80 端口也不应特殊对待。
- 2026-08-31 #90 部署失败：服务器 `.env` 的 `PUBLIC_BASE_URL` 未同步改为 `http`，新镜像启动时配置校验拒绝启动 → reven 不健康 → Caddy 因 `depends_on: service_healthy` 从未启动 → 站点宕机。自动回滚因 `reload_caddy` 假设 Caddy 容器在运行而不完整（`compose exec` 对停止的容器必然失败）。

## Requirements

1. **入口迁移 3001**：Caddy 监听、Compose 端口映射、应用默认值、测试夹具、文档统一从 80 迁移到 3001，对外入口为 `http://dev.wangyiyang.cc:3001`。
2. **保持 HTTP-only 不变量**：不引入 TLS、HSTS；现有安全响应头、缓存策略、SPA 回退行为不变。
3. **收紧权限**：迁移到非特权端口后，移除 Caddy 容器的 `cap_add: NET_BIND_SERVICE`。
4. **部署回滚加固**：`restore_previous_state` 在 Caddy 容器未运行的失败模式下也能尽力恢复（不能用 `compose exec` 假设容器在跑）。
5. **部署协调**：发布时必须同步更新服务器 `.env` 的 `PUBLIC_BASE_URL=http://dev.wangyiyang.cc:3001`（本次事故的直接教训），并在 runbook 中固化为部署步骤。

## Constraints

- 3001 不得与宿主机既有服务冲突（已知 3000 为博客）；部署前需在宿主机确认 `ss -lntp` 无 3001 占用。
- 路由器/防火墙/安全组需放行 3001，否则部署后公网不可达。
- 会话 Cookie 不按端口隔离，域名不变则已登录会话不受影响。
- 旧版本下发的 HSTS 可能仍被浏览器缓存，HTTP 无法清除；该风险 #90 已接受，本任务不扩大处理。
- 回滚兼容性：当前 main（fd0df57）的校验器只要求 `http` scheme、不检查端口，带端口 URL 对新旧镜像均可启动；HTTPS 时代的旧镜像不可回退（runbook 已有"不回退旧镜像"原则）。

## Acceptance Criteria

- [ ] `infra/caddy/Caddyfile` 站点地址为 `http://dev.wangyiyang.cc:3001`，无 `https://`、无 HSTS
- [ ] `infra/compose/docker-compose.yml` Caddy 仅映射 `3001:3001`，无 `cap_add`
- [ ] 应用默认值（`config.py`、`delivery_store.py`、`.env.example`、`scripts/smoke.sh`）均为 `http://dev.wangyiyang.cc:3001`
- [ ] `server/tests/e2e/test_http_deployment.py` 不变量断言更新为 3001 并通过
- [ ] `uv run pytest`、`uv run mypy`、`uv run ruff check server scripts`、`bash scripts/test_deploy_reven.sh` 全部通过
- [ ] 新增"reven 不健康且 Caddy 停止"场景的部署脚本测试，恢复路径不再因 `compose exec` 失败而报 incomplete
- [ ] `docs/runbook.md` 更新：入口 URL、公网 3001 可达性检查、部署时同步 `.env` 的步骤、3001 占用检查
- [ ] 部署后 `curl --fail http://dev.wangyiyang.cc:3001/api/health` 返回 `{"status":"ok"}`，且 80 端口不再监听

## Out of Scope

- 恢复 HTTPS 或任何 TLS 能力
- 部署脚本的 pre-flight 配置校验（作为 design.md 候选项，由 review 决定）
- 其他服务的端口规划

## Notes

- 实施分支从 `main` 新拉（GitHub Flow），与当前 `feat/rss-settings-split` 无关。
- 原子提交拆分：端口迁移、回滚加固、文档更新分开提交。
