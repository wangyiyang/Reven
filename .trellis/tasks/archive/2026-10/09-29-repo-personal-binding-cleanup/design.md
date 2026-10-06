# 技术设计：仓库个人绑定清理

## 决策

- **新默认值取 `http://localhost:8080`**：与 `docs/self-hosting.md:68` 回环模式的浏览器 origin 严格一致（文档明确 127.0.0.1 与 localhost 是不同 origin，cookie/CSRF 会以 public_base_url 为准做比较），默认值的使命是"文档路径开箱即用"。
- **`.env.example` 占位格式**：保持各值的"形状"不变（origin、bucket 命名、`@sha256:<64hex>`），只替换个人部分，避免下游正则（如 deploy 脚本的 digest 校验）在模板层面失真；digest 保持全零占位（任何 registry 都拉不到，天然防误用）。
- **测试只改默认值断言**：`test_config.py` 的 autouse fixture 会清掉 env，因此 `:20` 断言的就是默认值，必须同步；其他测试把该域名当任意外部 origin 夹具，与默认值无关，不动（精准修改）。

## 允许清单（个人值可留存位置）

`docs/runbook.md`、`docs/superpowers/`、`docs/ai-test-map.md`、`docs/ai-test-reports/`（历史测试记录，域名经 runbook 已属公开信息，与 superpowers 同层待用户复查）、`infra/caddy/`、`infra/compose/`、`scripts/deploy_reven.sh`、`scripts/validate_reven_image.sh`、`scripts/test_deploy_reven.sh`、`.github/workflows/release.yml`、`.trellis/`（用户决策保留）、`server/tests/` 与 `web/src/**/*.test.tsx` 中的 origin/账号夹具（惰性样本数据，不构成环境绑定；test_e2e 对 infra/caddy 的断言属维护者链路耦合测试）。

增补说明（2026-09-29 复查）：

- `docs/self-hosting.md:16` 的 `github.com/wangyiyang/Reven` 是仓库本身地址，转公开后为正确指引，保留。
- `.github/workflows/ci.yml:187` 的 `registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven@sha256:<全零>` 仅用于在 CI 中驱动 `validate_reven_image.sh`/`test_deploy_reven.sh`（两者均为允许清单内的维护者链路脚本，其校验正则硬编码该 registry 形状）；digest 全零不可拉取，不面向外部读者，允许留存。若未来通用化部署脚本校验正则，该 CI 值同步替换。

## 验证方法

1. `git grep -n "dev.wangyiyang.cc" -- . ":(exclude)docs/runbook.md" ...`（按允许清单排除）应零命中。
2. `git check-ignore -v workspace/ .coverage sync-to-notion.sh`。
3. `uv run pytest server/tests/test_config.py server/tests/security -q`。
4. `bash -n scripts/smoke.sh` + `REVEN_BASE_URL=http://localhost:8080 REVEN_BASIC_AUTH_USER=u REVEN_BASIC_AUTH_PASSWORD=p bash scripts/smoke.sh`（预期连不上但应走到 curl 阶段，即参数解析不报错——以 `-n` 为准，避免误触真实请求）。
