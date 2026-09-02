# Implement · 处理全部开放 Bug Issues

## Preconditions

- [ ] 用户审批本 PRD/design/implement 最终摘要。
- [ ] 从 `main` 创建 `codex/fix-all-open-bug-issues`，保留用户的 `dogfood-output/`。
- [ ] 每个子任务在修改前通过 `task.py start` 激活；完成检查、提交、关闭 Issue 后归档。

## Execution Order

### 1. #83 · 验证已合入修复

- [ ] 运行 `sh scripts/test_deploy_reven.sh`。
- [ ] 核对 `672a408`、Dockerfile release infra 路径和 release 工作流。
- [ ] 测试通过则在 #83 留证据并关闭，不产生冗余代码提交。

### 2. #100 · 稿件分页规范化

- [ ] 先补非法页码、越界页码、筛选参数保留测试。
- [ ] 实现 URL replace 与末页归一，禁止误导空态闪现。
- [ ] 验证：`pnpm -C web exec vitest run src/features/articles/articles-page.test.tsx`。

### 3. #101 · CRM 详情排版

- [ ] 调整外层断点、日期列最小宽度、邮箱换行、标签 nowrap。
- [ ] 补结构/class 回归测试并在 1280px 浏览器视口截图检查。
- [ ] 验证：`pnpm -C web exec vitest run src/features/crm/customer-detail-page.test.tsx`。

### 4. #102 · 人才空态与标签状态

- [ ] 先写标签验证失败保持测试，确认当前行为是否已正确。
- [ ] 将桌面空态放入 `tbody` 跨 6 列，移动空态独立呈现。
- [ ] 只有测试证明标签仍丢失时才修改表单状态逻辑。
- [ ] 验证：`pnpm -C web exec vitest run src/features/talents/talents-page.test.tsx`。

### 5. #103 · 财务删除一致性

- [ ] 将现有“响应前移除”测试改为“响应前保留”。
- [ ] 删除乐观缓存写与回滚快照，成功后统一失效查询。
- [ ] 增加 3–4 条连续删除测试并验证 DELETE 请求集合。
- [ ] 验证：`pnpm -C web exec vitest run src/features/finance/finance-page.test.tsx`。

### 6. #104 · 财务现金口径

- [ ] 先补服务端多状态汇总测试。
- [ ] repository 仅汇总 `已收`/`已付`，保留应收/应付。
- [ ] 前端改卡名及副标题，删除“跑道”。
- [ ] 验证：`uv run --directory server pytest -q tests/api/test_finance.py` 与 finance 前端测试。

### 7. #105 · WCAG AA

- [ ] 更新主题语义 token、按钮/登录前景和固定 emerald 用色。
- [ ] 增加 token/共享组件回归断言。
- [ ] 浅/深主题审计 `/articles`、`/crm`，覆盖筛选、状态徽标与侧栏。
- [ ] 验证 axe-core color-contrast 无 serious/critical 违规。

## Integration Gate

- [ ] `sh scripts/test_deploy_reven.sh`
- [ ] `pnpm --filter @reven/web lint`
- [ ] `pnpm --filter @reven/web test --run`
- [ ] `pnpm --filter @reven/web build`
- [ ] `uv run --directory server pytest -q tests/api/test_finance.py`
- [ ] 浅色/深色浏览器回归：分页、CRM 1280px、人才验证、财务连续删除、axe 审计。
- [ ] 使用 `trellis-check` 完成最终全范围检查。
- [ ] 使用 `trellis-update-spec` 将最新 Notion 蓝灰可访问性契约写入 Brand VI spec。
- [ ] 每个 Issue 留下修复 commit/验证结果并关闭；重新查询开放 `bug` Issue 应为空。

## Commit Plan

- `fix(web): 规范化稿件列表越界页码 (#100)`
- `fix(web): 修正 CRM 详情页内容折行 (#101)`
- `fix(web): 修正人才库空态与表单状态 (#102)`
- `fix(web): 以服务端结果确认财务删除 (#103)`
- `fix(finance): 汇总仅统计实际收付 (#104)`
- `fix(web): 提升主题颜色对比度至 WCAG AA (#105)`
- Trellis 任务与 spec 状态随对应关注点提交，不混入无关改动。
