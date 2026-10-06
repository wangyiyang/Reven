# 站点域名迁移 dev.wangyiyang.cc → reven.wangyiyang.cc

## Goal

将生产站点域名从 `dev.wangyiyang.cc` 迁移到 `reven.wangyiyang.cc`（GitHub #213）。覆盖 Caddy 站点配置、Vercel 回退入口 API 代理、测试断言与占位 origin、现行文档与 spec 契约；DNS 与 VPS `.env` 为配套运维动作。

## Background

- 当前部署形态（#211 起）：前后端统一部署在 VPS，同一镜像发布 API 与 web；Caddy 服务静态文件（`/srv/reven/current`，SPA fallback）并反代 `/api/*`；Vercel 旧部署保留为故障回退入口。
- `deploy_reven.sh` 同步 `infra/` 并在 Caddyfile 变化时自动 reload Caddy；VPS `.env` 的 `PUBLIC_BASE_URL` 需手动同步。
- CSRF Origin 校验基于 `PUBLIC_BASE_URL`；会话 Cookie Secure 属性依赖 HTTPS origin。

## 已确认决策（2026-10-06 与会确认）

1. 老域名 `dev.wangyiyang.cc` 直接弃用、不留 301；新域名只开 HTTPS，**砍掉 `:3001` HTTP 过渡入口**（Caddyfile 注释本就标注其可下线）。
2. 测试占位 origin（`http://dev.wangyiyang.cc:3001`）统一改为 `https://reven.wangyiyang.cc`；CSRF 负例用例同步调整但保持负例语义（仿冒后缀 / scheme 不匹配）。
3. 历史文档（`docs/superpowers/*`、`docs/ai-test-reports/*`、`dogfood-output/*`、`CHANGELOG.md`、`.trellis/tasks/archive/*`）保持原样；活跃任务 `09-29-repo-personal-binding-cleanup` 的引用属其自身上下文，不动。

## Requirements

### 仓库内改动

1. `infra/caddy/Caddyfile`：HTTPS 站点块域名替换为 `reven.wangyiyang.cc`；删除 `http://dev.wangyiyang.cc:3001` 过渡站点块。
2. `web/vercel.json`：回退入口 rewrite destination 改为 `https://reven.wangyiyang.cc/api/$1`。
3. `server/tests/e2e/test_http_deployment.py`：Caddyfile 断言更新（新域名站点块存在、`:3001` 块不再存在）、vercel.json rewrite 断言更新。
4. `scripts/self_host_smoke.py`（约 214-216 行）：localhost 替换逻辑跟随新 Caddyfile（精确匹配串更新、`:3001` 块替换逻辑移除）。
5. `server/tests/security/test_self_host_smoke.py:121`：断言同步更新。
6. 测试占位 origin 统一为 `https://reven.wangyiyang.cc`：
   - `server/tests/api/conftest.py`（WRITE_HEADERS、public_base_url）
   - `server/tests/security/test_auth.py`、`test_csrf.py`、`test_headers.py`
   - `server/tests/agent/test_mcp_server.py`
   - `test_csrf.py` 负例保持语义：仿冒后缀改为 `https://reven.wangyiyang.cc.evil.example`，scheme 不匹配负例改为 `http://reven.wangyiyang.cc`
7. 现行文档域名引用更新：`docs/runbook.md`（含 `ssh kk@dev.wangyiyang.cc` → `ssh kk@reven.wangyiyang.cc`）、`docs/vercel-deploy.md`、`docs/ai-test-map.md`（Web 入口改为 `https://reven.wangyiyang.cc`）。
8. spec 契约更新（Phase 3.3）：`.trellis/spec/reven-server/backend/open-source-self-host-contract.md:139` 正式 origin 改为 `https://reven.wangyiyang.cc`。

### 运维侧动作（仓库外，按序执行）

1. DNS：`reven.wangyiyang.cc` A 记录指向 VPS（先生效，证书签发依赖 80/443 公网可达）。
2. VPS `.env`：`PUBLIC_BASE_URL=https://reven.wangyiyang.cc`。
3. 走标准 `deploy_reven.sh` 部署（自动同步 Caddyfile + reload；Caddy 自动签发证书）。
4. Vercel 回退入口：merge 后 push 自动重新部署生效。

## 影响与风险

- 证书签发依赖 DNS 已生效且 80/443 公网可达，否则 reload 后站点不可用；`deploy_reven.sh` 具备恢复上一状态的逻辑，可回滚。
- VPS `.env` 不同步会导致写请求 CSRF 403。
- 切换期间旧域名失效即站点不可达（单用户 Alpha 无外部用户，可接受）。

## Acceptance Criteria

仓库内（本任务交付边界）：

- [ ] `uv run pytest server/tests/e2e/test_http_deployment.py` 通过
- [ ] `uv run pytest server/tests/security/test_self_host_smoke.py server/tests/security/test_csrf.py server/tests/security/test_auth.py server/tests/security/test_headers.py server/tests/agent/test_mcp_server.py` 通过
- [ ] `python3 scripts/self_host_smoke.py`（或其既有本地验证入口）通过
- [ ] 现行文档与 Caddyfile / vercel.json / 测试 / spec 契约无 `dev.wangyiyang.cc` 残留（历史文档与归档任务除外）

运维验收（部署后人工执行，记录结果即可）：

- [ ] `curl -sS https://reven.wangyiyang.cc/api/health` 返回 200 且证书有效
- [ ] `https://reven.wangyiyang.cc` 直接返回前端页面，可登录并完成一次写操作（验证 Origin/CSRF 链路）
- [ ] Vercel 回退入口的 `/api/*` 代理指向新域名且可用
