# 技术设计：HTTP 单端口 3001 + 部署回滚加固

## 总体思路

两处独立改动，共享同一次发布：

1. **端口迁移**：把"80"这个特权/默认端口从配置、代码默认值、测试、文档中收敛为一个可辨识的自定义端口 3001。本质是配置值的机械迁移，无架构变化。
2. **回滚加固**：消除 `restore_previous_state` 中"Caddy 一定在运行"的隐式假设。

## 一、端口迁移

### 改动清单（按层分组）

**入口配置（2 处）**

| 文件 | 改动 |
|---|---|
| `infra/caddy/Caddyfile` | 站点地址 `http://dev.wangyiyang.cc` → `http://dev.wangyiyang.cc:3001` |
| `infra/compose/docker-compose.yml` | `ports: ["80:80"]` → `["3001:3001"]`；删除 `cap_add: NET_BIND_SERVICE`（非特权端口不再需要） |

**应用默认值（4 处）**

| 文件 | 改动 |
|---|---|
| `server/src/reven/config.py` | `public_base_url` 默认值追加 `:3001` |
| `server/src/reven/publishing/delivery_store.py` | 默认参数同步（飞书通知链接自动带端口，无其他改动） |
| `.env.example` | `PUBLIC_BASE_URL` 追加 `:3001` |
| `scripts/smoke.sh` | `REVEN_BASE_URL` 默认值追加 `:3001`（host:port 解析逻辑已支持，无需改） |

**测试（8 个文件）**

- `server/tests/e2e/test_http_deployment.py`：两处硬编码断言更新（Caddyfile 首行、compose ports），并补充"无 cap_add"断言
- `server/tests/test_config.py:14`：默认值断言追加 `:3001`
- `server/tests/api/conftest.py`、`test_csrf.py`、`test_auth.py`、`test_headers.py`、`articles/test_sync_api.py`：Origin 夹具统一改为带端口，与生产配置保持一致（这些测试只需自洽即可通过，但夹具应代表生产形态，避免误导）
- `test_csrf.py:61-62` 的负向用例（evil.example、https）不动

**文档（2 处）**

- `docs/runbook.md`：入口 URL、"公网 80 必须可达"→"公网 3001 必须可达"、验证命令、`.env` 同步步骤
- `docs/ai-test-map.md`：Web 入口 URL

### 兼容性论证（已核实）

- `config.py` 校验器只检查 scheme/hostname/userinfo/path/query/fragment，**不检查端口**，带端口 URL 可通过
- `csrf.py` 的 `_same_origin` 按 `(scheme, host, port)` 三元组对比，浏览器 Origin 头自动带端口，与带端口的 `public_base_url` 匹配，代码零改动
- 当前 main（fd0df57）镜像的校验器同样不检查端口 → 带端口的 `.env` 对本次发布前后的镜像均可启动，发布/回滚不会因配置值崩启动

### 发布形态（路径 B：一次性到位）

```
1. 合并 PR → CI 构建新镜像
2. 发布前先登服务器：ss -lntp 确认 3001 空闲；防火墙/安全组放行 3001
3. 编辑 /opt/reven/.env：PUBLIC_BASE_URL=http://dev.wangyiyang.cc:3001
4. 触发 release 部署
```

回滚形态：`DEPLOY_OPERATION=rollback` 回滚到前一健康镜像（fd0df57 时代，HTTP-only 80 端口）——服务可启动，但 Caddy 仍按旧 infra 监听 80，对外 URL 与 `.env` 中带端口的 `PUBLIC_BASE_URL` 不一致（通知链接带 3001 而服务在 80）。属可接受的降级态，runbook 中注明。

## 二、回滚加固

### 缺陷

`restore_previous_state` 只在 `caddy_changed=true` 时 `reload_caddy`，而 `reload_caddy` 用 `compose exec`——当失败模式是"reven 不健康"时，Caddy 因 `depends_on: service_healthy` 从未启动，`exec` 必然失败 → `restore_failed=1` → 报"automatic restoration was incomplete"。

### 设计

`reload_caddy` 拆为两步语义：**在跑则 reload，不在跑则以恢复后的旧 infra 尽力拉起**：

```sh
reload_caddy() {
  if compose ps --status running -q caddy | grep -q .; then
    compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  else
    # Caddy 未运行（典型：reven 健康检查失败）。用 --no-deps 绕过 depends_on，
    # 以恢复后的旧 Caddyfile 拉起；静态页可恢复访问，API 取决于 reven 状态。
    compose up -d --no-deps --no-build caddy
  fi
}
```

取舍说明：

- `--no-deps` 绕过 `depends_on`：restore 场景下 reven 可能仍不健康，等待健康检查会让恢复再次卡死；拉起 Caddy 至少恢复静态页伺服（Caddy 直读 `reven-static` volume），API 是否可用取决于 reven 容器自身状态——这是"尽力恢复"，完全恢复仍需人工决策是否回退镜像（脚本刻意不做，防止数据库已迁移）。
- 不改 `activate_target` 的正常路径语义；`reload_caddy` 在 activate 路径中 Caddy 必然在跑，行为不变。
- 测试：`scripts/test_deploy_reven.sh` 的 fake docker 增加 "caddy 停止 + Caddyfile 变更" 场景，断言恢复走 `up -d --no-deps` 而非 `exec`，且 restore 报告完整。

### 候选加固（超出本任务范围，review 时决定是否另立任务）

**pre-flight 配置校验**：`activate_target` 前用新镜像跑 `docker run --rm --env-file .env <image> python -c "from reven.config import get_settings; get_settings()"`，在重建容器前拦截".env 与镜像配置约束不匹配"的整类故障（本次事故的根因层）。成本是部署多几秒。建议另立任务评估（需确认 Dockerfile 无干扰性 ENTRYPOINT）。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 3001 被宿主机其他服务占用 | 发布前 `ss -lntp` 检查；runbook 固化为部署步骤 |
| 防火墙/安全组未放行 3001，部署后公网不可达 | 发布前检查项；失败时 rollback 可回 80 |
| 浏览器缓存的旧 HSTS 继续强制 HTTPS | #90 已接受，HTTP 无法清除；文档已说明需客户端手动清 |
| 部署后 `docker compose ps` 端口判断遗漏 | e2e 不变量测试锁定 compose ports |

## 验证总览

- `uv run pytest`（含更新后的 e2e 不变量、部署脚本新场景）
- `uv run mypy`、`uv run ruff check server scripts`
- `bash scripts/test_deploy_reven.sh`
- `bash -n scripts/smoke.sh`、`git diff --check`
- 发布后手动：`curl --fail http://dev.wangyiyang.cc:3001/api/health`、`curl -I http://dev.wangyiyang.cc:3001`、`! curl --connect-timeout 3 http://dev.wangyiyang.cc:80`
