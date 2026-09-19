# 技术设计：稿件状态筛选动态选项

## 总览

后端新增只读聚合接口 `GET /api/articles/status-facets`，前端 `ArticleFilters` 用 React Query 拉取该接口生成状态下拉选项，替换硬编码数组。

## 后端

### 接口契约

- `GET /api/articles/status-facets` → 200 `{"statuses": ["已发布", "撰写中", ...]}`
- 认证：挂 `articles_router`，由全局 `AuthMiddleware` 自动保护（未登录 401，与现有接口一致）。
- 响应模型：新增 `ArticleStatusFacets(BaseModel) { statuses: list[str] }`，放在 `api/schemas/articles.py`。
- 值来源：`Article.notion_status` 与 `Article.automation_status` 的去重并集，剔除空值，升序。
  - 两列均为 `String(32)` 非空且带索引（`articles/models.py`），无需空值过滤以外的防御。

### 查询实现

`ArticleQuery`（`articles/query.py`）新增 `status_facets()`：

```python
async def status_facets(self) -> list[str]:
    union = (
        select(Article.notion_status.label("status"))
        .union(select(Article.automation_status.label("status")))
        .subquery()
    )
    rows = await self.session.scalars(select(union.c.status).order_by(union.c.status))
    return list(rows)
```

- 用 SQL `UNION`（自带去重）拿到值集合，排序放在 Python 侧 `sorted()`：与数据库 collation 无关，行为确定、测试稳定。
- 不加缓存：表单数据量（当前 43 行，预期万级以内），两个索引列的 UNION 开销可忽略（YAGNI）。

### 测试

`server/tests/api/test_articles.py` 新增用例：
- 种子数据含重复/交叉的 notion_status 与 automation_status，断言返回去重并集且升序；
- 空表返回 `{"statuses": []}`；
- 未登录 401（沿用现有测试的认证夹具模式）。

## 前端

### 数据获取

`article-filters.tsx` 内新增查询：

```tsx
const facets = useQuery({
  queryKey: ["article-status-facets"],
  queryFn: async () => parseStatusFacets(await apiRequest<unknown>("/articles/status-facets")),
  staleTime: 60_000,
})
```

- `response-parsers.ts` 新增 `parseStatusFacets`：防御性校验 `statuses` 为字符串数组，非法项剔除（沿用项目 parse-unknown 风格）。
- `staleTime: 60s`：状态值域低频变化，避免每次进列表页都打一次。

### 选项组装

```tsx
const options = ["全部状态", ...facets.data ?? []]
// URL 当前值不在选项内时追加，保证 Select value 始终有匹配 item（Radix 无匹配时 SelectValue 显示空白）
if (values.status && !options.includes(values.status)) options.push(values.status)
```

- 接口 pending / error：`facets.data` 为空，下拉仅有"全部状态"（+ URL 当前值），列表查询不受影响。
- 选择"全部状态"仍映射为 `status: ""`（清空筛选），现有语义不变。
- 渠道下拉不动。

### 测试

`articles-page.test.tsx` 更新/新增：
- mock `GET /api/articles/status-facets` 返回自定义值域，断言下拉渲染这些选项且不含旧硬编码值；
- facets 接口 500 时页面列表仍正常渲染、下拉可显示 URL 当前 status 值。

## 影响与风险

- **兼容性**：纯增量。新接口不改变任何现有接口契约；前端只替换选项数据源，筛选语义不变。
- **性能**：两索引列 UNION DISTINCT，全表扫一遍字符串去重，43 行～万级数据量下为毫秒级。
- **风险**：若 Notion 侧状态名被用户改得很频繁，下拉选项会随之变化（这正是期望行为）；`staleTime` 窗口内新增状态可能延迟最多 60s 出现在选项中，可接受。
- **回滚**：`git revert` 本任务提交 + 重新部署旧镜像即可，无数据迁移。

## 部署（顺手）

合并后按 infra/ 现有流程重新构建镜像并部署 dev 环境，验收标准末条在线上验证。
