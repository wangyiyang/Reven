# 稿件状态筛选值域脱节修复（动态状态选项）

## Goal

稿件列表页（/articles）的状态下拉选项改为由后端真实数据动态生成，消除"下拉可选状态"与"稿件实际状态"之间的脱节，使用户能按真实存在的状态筛选稿件。

## Background

线上排查（2026-09-19，dev.wangyiyang.cc:3001）确认：前端 `article-filters.tsx` 硬编码了 7 个状态选项（待发布/等待中/处理中/阻塞/失败/已完成/已交付），而数据库 43 篇稿件的实际状态值域为 notion_status ∈ {已发布, 撰写中, 选题池}、automation_status ∈ {未开始}，二者零交集。后果：

- 用户选任何状态都返回 0 条（"没有匹配稿件"）；
- 真实存在的状态（已发布/撰写中/选题池/未开始）在下拉里选不到；
- 后端 `status` 过滤（notion_status OR automation_status 精确匹配）本身工作正常，问题纯在前端值域。

## Requirements

- 后端提供稿件状态值域聚合能力：返回全部稿件 `notion_status` 与 `automation_status` 的去重并集。
- 前端稿件列表页状态下拉的选项使用该聚合结果动态生成，保留"全部状态"作为清空筛选的选项。
- 保持现有筛选语义不变：`status` 查询参数仍按 `notion_status OR automation_status` 精确匹配过滤；不拆分筛选维度。
- 聚合接口失败时，下拉退化为仅"全部状态"，不影响列表正常使用。
- URL 中的 `status` 值即使不在当前选项集合内，下拉也应能显示该值（不显示空白）。
- 渠道下拉维持硬编码不变（渠道值域由后端枚举 `TargetChannel` 控制，不脱节）。

## Out of Scope

- 不改动 `status` 过滤的 OR 语义，不拆分 notion_status / automation_status 两个筛选维度。
- 不改动 article-status.tsx 的状态展示（badge 着色）逻辑。
- 不在本任务内处理"automation_status 全为未开始"的数据治理问题。

## Acceptance Criteria

- [ ] `GET /api/articles/status-facets` 返回 200，body 为 `{"statuses": [...]}`，内容等于数据库中 notion_status ∪ automation_status 的去重集合（升序），空表返回空数组。
- [ ] 接口需要登录认证（未登录返回 401）。
- [ ] 前端状态下拉选项 = ["全部状态", ...聚合结果]，不再硬编码状态值。
- [ ] 选择一个真实状态（如"已发布"）后列表正确过滤且 URL 同步 `status` 参数；选择"全部状态"清除筛选。
- [ ] URL 直接带合法 `status` 参数进入页面时，下拉显示该值。
- [ ] 聚合接口失败时下拉仍可打开，仅显示"全部状态"（及 URL 当前值），列表查询不受影响。
- [ ] 后端新增接口测试；前端相关测试通过；`pnpm lint` / `pytest` 全绿。
- [ ] 修复合并后重新部署 dev 环境，线上 `/articles?status=已发布&page=1` 可筛出 33 条稿件。
