# 执行计划：HTTP 单端口 3001 + 部署回滚加固

## 前置

- [ ] 从 `main` 拉新分支 `feat/http-single-port-3001`（当前 `feat/rss-settings-split` 与本任务无关）
- [ ] `task.py start` 后开工

## Step 1：端口迁移 —— 入口配置（commit 1 的一部分）

- [ ] `infra/caddy/Caddyfile`：站点地址改为 `http://dev.wangyiyang.cc:3001`
- [ ] `infra/compose/docker-compose.yml`：ports 改为 `["3001:3001"]`，删除 `cap_add` 整段
- [ ] 验证：`uv run pytest server/tests/e2e/test_http_deployment.py`（此时应红，Step 3 修）

## Step 2：端口迁移 —— 应用默认值

- [ ] `server/src/reven/config.py`、`server/src/reven/publishing/delivery_store.py`、`.env.example`、`scripts/smoke.sh` 默认值追加 `:3001`
- [ ] 验证：`uv run pytest server/tests/test_config.py -x`（此时应红，Step 3 修）；`bash -n scripts/smoke.sh`

## Step 3：端口迁移 —— 测试与文档（commit 1 收尾）

- [ ] `test_http_deployment.py`：更新两处断言 + 新增"无 cap_add"断言
- [ ] `test_config.py`、`api/conftest.py`、`test_csrf.py`、`test_auth.py`、`test_headers.py`、`articles/test_sync_api.py` 的 URL 夹具追加 `:3001`
- [ ] `docs/runbook.md`、`docs/ai-test-map.md` 更新入口 URL 与端口检查项
- [ ] 验证：`uv run pytest && uv run mypy && uv run ruff check server scripts && git diff --check`
- [ ] **Commit 1**：`feat(infra)!: Reven 入口迁移到 HTTP 单端口 3001`

## Step 4：回滚加固（commit 2）

- [ ] `scripts/deploy_reven.sh`：`reload_caddy` 拆为"在跑则 reload / 不在跑则 `up -d --no-deps --no-build caddy`"
- [ ] `scripts/test_deploy_reven.sh`：新增"reven 不健康 + Caddy 停止 + Caddyfile 变更"场景用例
- [ ] 验证：`bash scripts/test_deploy_reven.sh` 全绿
- [ ] **Commit 2**：`fix(infra): 回滚恢复不再假设 Caddy 容器在运行`

## Step 5：文档收尾（commit 3）

- [ ] `docs/runbook.md`：固化部署时同步 `.env` 的步骤与 3001 放行检查（本次事故教训）
- [ ] **Commit 3**：`docs: 部署手册补充端口迁移与 .env 同步步骤`

## Review Gate

- [ ] 全量验证命令通过：`uv run pytest`、`uv run mypy`、`uv run ruff check server scripts`、`bash scripts/test_deploy_reven.sh`
- [ ] `git diff main --stat` 核对改动面与 design.md 清单一致，无外溢
- [ ] 提 PR 回 `main`

## 发布 Checklist（人工，合并后）

- [ ] 服务器：`ss -lntp | grep 3001` 确认空闲；防火墙/安全组放行 3001
- [ ] 服务器：编辑 `/opt/reven/.env` → `PUBLIC_BASE_URL=http://dev.wangyiyang.cc:3001`
- [ ] 触发 release 部署，观察 reven healthy → Caddy reload
- [ ] `curl --fail http://dev.wangyiyang.cc:3001/api/health` 返回 ok；确认 80 不再监听

## 回滚点

- Step 1-3 出问题：`git checkout` 丢弃即可，无外部状态
- 发布后出问题：服务器 `DEPLOY_OPERATION=rollback /opt/reven/scripts/deploy_reven.sh`（注意降级态：Caddy 回 80，通知链接带 3001，见 design.md）
