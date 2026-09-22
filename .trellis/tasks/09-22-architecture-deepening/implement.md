# 执行计划：架构深化批次（GH #133-#137）

## 执行形态

- 5 个交付 = 5 个 feature 分支 + 5 个 PR，均从 main 拉出
- server 线顺序：PR-A（#134）→ PR-B（#133）→ PR-C（#135）；web 线：PR-D（#136）→ PR-E（#137）；两线可并行，但同一时刻只有一条线有在途 PR，避免 main 漂移冲突
- 每个 PR 内按"先建 seam、再迁调用方、后删旧测试"原子 commit 推进

## 验证命令

```bash
# server
uv run pytest                      # 全量（-m 'not dsh_runtime' 可排除 dsh 实测）
uv run ruff check server/src server/tests && uv run ruff format --check server/src server/tests
uv run mypy                        # strict，packages = ["reven"]

# web
pnpm --filter @reven/web test --run
pnpm --filter @reven/web lint
pnpm --filter @reven/web build     # tsc -b && vite build
```

## PR-A · #134 删除 connection-test 全局注册表（最小，先行）

- [ ] 分支 `refactor/134-explicit-connection-adapters`，先对齐 main（含 9b60c9c）
- [ ] `IntegrationService` 构造函数接收 `adapters` dict；routes 构建字面量映射
- [ ] 删除全局 dict、全部 `register_*_adapter()`、conftest 修复 fixture
- [ ] 验证：server 门禁全绿；grep 确认无 `register_` 残留
- [ ] PR 合并后关闭 #134

## PR-B · #133 IntegrationCredentials + ProviderClients（地基）

- [ ] 分支 `refactor/133-integration-credentials`
- [ ] 新增 `integrations/credentials.py`：SecretBox 唯一构造点 + typed credentials + log-and-degrade；seam 测试先行（解密失败降级 / hint 剥离 / env 兜底 / 密钥不回显）
- [ ] 逐个迁移调用方：`feishu_bot/config.py` → `translation` → `embedding` → `tencent_cos` → `agent/config.py`（每 provider 一个 commit，保持各自降级语义）
- [ ] 建 `ProviderClients`（lifespan），迁移并删除 3 个 `Configured*` adapter
- [ ] 删除被取代的 per-provider configuration 旧测试（replace-don't-layer）
- [ ] 验证：server 门禁全绿；`SecretBox.from_base64` 全仓仅 1 处；`Configured` class 为 0
- [ ] PR 合并后关闭 #133

## PR-C · #135 Settings 组合根

- [ ] 分支 `refactor/135-settings-composition-root`（依赖 PR-B 合并）
- [ ] `create_app(settings=None)` 唯一解析点；`SettingsDep` + 构造函数注入下推
- [ ] 删除 `_load_settings_or_none`、`cache_clear` ×3、`_scrub_agent_env`
- [ ] 验证：server 门禁全绿；`get_settings` 调用点 = 1
- [ ] PR 合并后关闭 #135

## PR-D · #136 useResourceList + ResponsiveList

- [ ] 分支 `refactor/136-resource-list-seam`
- [ ] 新增 `web/src/lib/use-resource-list.ts` + `responsive-list.tsx`；seam 测试先行（乐观删除回滚 / toast 归一化 / 双视口渲染）
- [ ] 逐页迁移：projects → sops → talents → crm → finance（每页一个 commit）
- [ ] `ErrorPanel` 提升到 `components/ui`
- [ ] 验证：web 门禁全绿；回滚逻辑全仓 1 份；`toast.error(error instanceof Error` 仅 seam 内
- [ ] PR 合并后关闭 #136

## PR-E · #137 routes.tsx + IntegrationCard

- [ ] 分支 `refactor/137-route-registry-card-controller`
- [ ] `routes.tsx` 注册表；App / AppShell 消费；组开关按 group id keyed + 持久化
- [ ] IntegrationCard 收拢为 2 props；删除 busyAction 字符串编码
- [ ] 验证：web 门禁全绿；新增页面 e2e 路径 = 一处数组项
- [ ] PR 合并后关闭 #137

## 评审门与回滚点

- 每个 PR：CI 绿 + 自查 diff 语义红线（降级 / 错误码 / 页面行为不变）后合并；发现语义漂移立即回滚该 PR 分支内最近 commit
- PR-B 是最大交付：若 seam 设计在迁移第 2 个 provider 时暴露缺陷，停在当前 commit 回到 design.md 修订，不强行推进
- 批次完成后：trellis-check 全量复核 → spec 更新（integration-provider-contract、directory-structure、hook-guidelines 等受影响条目）→ 归档任务
