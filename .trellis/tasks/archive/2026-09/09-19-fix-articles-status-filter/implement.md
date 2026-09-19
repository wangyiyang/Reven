# 执行计划：稿件状态筛选动态选项

## 分支

- 从 `main` 拉出 `fix/articles-status-filter`，PR 合并回 main（GitHub Flow）。

## 步骤清单

### 1. 后端接口（server）

- [ ] `articles/query.py`：`ArticleQuery` 新增 `status_facets()`（SQL UNION DISTINCT + ORDER BY）
- [ ] `api/schemas/articles.py`：新增 `ArticleStatusFacets { statuses: list[str] }`
- [ ] `api/routes/articles.py`：新增 `GET /status-facets` 路由（放在 `/{article_id}` 之前避免路径冲突）
- [ ] `server/tests/api/test_articles.py`：去重并集/升序、空表、未登录 401 三个用例
- 验证：`cd server && uv run pytest tests/api/test_articles.py -q`

### 2. 前端接入（web）

- [ ] `response-parsers.ts`：新增 `parseStatusFacets`（防御性解析字符串数组）
- [ ] `article-filters.tsx`：useQuery 拉取 facets（staleTime 60s），动态组装选项；URL 当前 status 不在选项内时追加；失败退化仅"全部状态"
- [ ] `articles-page.test.tsx`：facets mock + 动态选项断言 + facets 失败兜底用例
- 验证：`cd web && pnpm test && pnpm lint && pnpm build`

### 3. Review gates

- [ ] `python3 ./.trellis/scripts/task.py validate`
- [ ] 全量测试：server `uv run pytest` + web `pnpm test`
- [ ] 契约核对：接口路径/响应结构与 `response-parsers` 解析一致
- 回滚点：任何一步失败 → 修正或 `git reset` 到 main，无副作用

### 4. 合并与部署

- [ ] 提交 PR，合并到 main
- [ ] 确认当前版本号（git tag），打下一个 patch tag 触发 release.yml 构建+部署（或 workflow_dispatch 指定版本）
- [ ] 线上验收：`/articles?status=已发布&page=1` 筛出 33 条；下拉选项包含真实状态值

## 验证命令汇总

```bash
cd server && uv run pytest
cd web && pnpm test && pnpm lint && pnpm build
```
