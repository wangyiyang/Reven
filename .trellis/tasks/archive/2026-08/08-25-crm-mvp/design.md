# Design · CRM 第一阶段 MVP

## 1. Architecture

CRM 作为现有模块化单体中的独立领域加入，不引入新服务或新状态管理框架。

```text
React 页面
  → typed crm-api
  → FastAPI /api/crm
  → CRM repository/service
  → PostgreSQL: crm_customers / crm_contacts / crm_follow_ups
```

边界职责：

| 层 | 职责 |
|---|---|
| 前端页面 | 表单状态、可访问交互、加载/空态/错误态、桌面/移动布局 |
| `crm-api.ts` | CRM 请求路径、请求/响应类型和序列化入口 |
| Pydantic schema | 所有外部输入的长度、枚举、邮箱和跨字段校验 |
| Route/service | 资源归属校验、事务边界、主要联系人切换、当前行动同步 |
| Repository | 查询、筛选、排序和持久化，不拥有 HTTP 语义 |
| PostgreSQL | 外键、级联/置空、索引和不可为空约束 |

## 2. Data Model

### `crm_customers`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | `uuid4` |
| `name` | varchar(200) | 必填，不做唯一约束 |
| `status` | varchar(32), index | 五种固定关系状态 |
| `source` | varchar(100), nullable | 客户来源 |
| `notes` | text, nullable | 客户备注 |
| `next_action` | text, nullable | 当前下一步行动 |
| `next_follow_up_on` | date, nullable, index | 当前跟进日期 |
| `created_at` / `updated_at` | timestamptz | 使用项目统一 UTC 时钟 |

### `crm_contacts`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 联系人 ID |
| `customer_id` | UUID FK, index | 客户删除时 `CASCADE` |
| `name` | varchar(200) | 必填 |
| `role` | varchar(100), nullable | 职位/角色 |
| `phone` / `email` / `wechat` | varchar | 可选联系方式 |
| `is_primary` | boolean | 主要联系人 |
| `notes` | text, nullable | 备注 |
| `created_at` / `updated_at` | timestamptz | 审计时间 |

同一客户最多一个 `is_primary=true`。数据库增加 PostgreSQL partial unique index，服务层在设置新主要联系人前先取消旧标记，以同时提供一致性和友好行为。

### `crm_follow_ups`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 跟进 ID |
| `customer_id` | UUID FK, index | 客户删除时 `CASCADE` |
| `contact_id` | UUID FK, nullable | 联系人删除时 `SET NULL` |
| `contact_name_snapshot` | varchar(200), nullable | 保留发生时联系人名称 |
| `kind` | varchar(24) | 电话/会议/微信/邮件/其他 |
| `occurred_on` | date, index | 跟进发生日期 |
| `summary` | text | 跟进内容，必填 |
| `next_action` | text, nullable | 当时约定的下一步快照 |
| `next_follow_up_on` | date, nullable | 当时约定日期快照 |
| `created_at` / `updated_at` | timestamptz | 同日记录的稳定排序依据 |

跟进按 `occurred_on DESC, created_at DESC` 排序。历史记录中的下一步是快照，不是客户当前行动的第二数据源。

## 3. Business Invariants

1. `next_follow_up_on` 非空时 `next_action` 必须非空；客户和跟进输入均执行该校验。
2. 嵌套联系人/跟进路由必须同时匹配 `customer_id` 和资源 ID，禁止跨客户读写。
3. 联系人设为主要联系人时，在同一事务内取消该客户原主要联系人。
4. 创建跟进请求使用仅存在于请求中的 `set_as_current` 布尔值：为真时把快照同步到客户当前行动；为假时只写历史。
5. 编辑或删除历史跟进不回滚客户当前行动，避免覆盖后来发生的业务状态。
6. 删除联系人将历史记录的 `contact_id` 置空，但通过 `contact_name_snapshot` 保留可读上下文。
7. 删除客户级联删除联系人与跟进；不存在的客户或越属资源统一返回稳定错误码。

## 4. API Contract

所有路径位于 `/api/crm`，错误统一为 `{ "code": string, "message": string }`。

| 方法与路径 | 行为 |
|---|---|
| `GET /customers` | 列表；支持 `query`、`status`、`due=overdue|today|upcoming|none` |
| `POST /customers` | 创建客户 |
| `GET /customers/{customer_id}` | 获取客户详情 |
| `PUT /customers/{customer_id}` | 全量编辑客户字段 |
| `DELETE /customers/{customer_id}` | 删除客户及其子资源 |
| `GET /customers/{customer_id}/contacts` | 联系人列表，主要联系人优先 |
| `POST /customers/{customer_id}/contacts` | 创建联系人 |
| `PUT /customers/{customer_id}/contacts/{contact_id}` | 编辑且校验归属 |
| `DELETE /customers/{customer_id}/contacts/{contact_id}` | 删除且保留历史快照 |
| `GET /customers/{customer_id}/follow-ups` | 跟进时间线 |
| `POST /customers/{customer_id}/follow-ups` | 创建跟进，可同步当前行动 |
| `PUT /customers/{customer_id}/follow-ups/{follow_up_id}` | 修正历史记录，不同步当前行动 |
| `DELETE /customers/{customer_id}/follow-ups/{follow_up_id}` | 删除历史记录，不同步当前行动 |

列表搜索覆盖客户名称、来源、备注及联系人姓名/电话/邮箱/微信。查询使用 `EXISTS`，避免联系人 join 导致客户重复。

## 5. Frontend Design

### 路由与页面

- `/crm`：客户列表、搜索/筛选、客户新增与编辑。
- `/crm/customers/:customerId`：客户摘要、联系人管理、跟进时间线和当前下一步行动。
- 主导航新增 `ContactRound` 图标的“CRM”项；移动端导航测试同步更新。

### 文件边界

```text
web/src/features/crm/
  types.ts
  crm-api.ts
  crm-page.tsx
  customer-detail-page.tsx
  contacts-section.tsx
  follow-ups-section.tsx
  crm-page.test.tsx
  customer-detail-page.test.tsx
```

- `types.ts` 是前端 CRM 响应与表单类型的唯一所有者。
- `crm-api.ts` 是路径和请求序列化的唯一所有者。
- 列表页与详情页只组合业务区块；联系人和跟进各自维护局部表单/Mutation。
- 不创建通用表单框架，不修改无关页面；如发现单文件或函数超限，按上述业务边界继续拆分。

### UX Rules

- 列表按已有跟进日期优先、日期升序、最近更新时间降序显示。
- 日期标记使用“逾期”“今天”“计划于 YYYY-MM-DD”等文字，颜色只作增强。
- 删除客户、联系人、跟进均使用现有 `ConfirmDialog`。
- 请求进行中禁用重复提交；错误使用现有 toast，页面级加载失败保留重试入口。
- 样式只使用现有 `--bg`、`--ink`、`--signal`、`--muted`、`--faint`、`--line`、`--danger` 令牌。

## 6. Validation and Security

- Pydantic create/update schema 设置 `extra="forbid"`；前端校验只改善体验，后端仍是最终边界。
- 可空字符串统一 trim 后归一化为 `null`；名称/内容执行必填和最大长度校验。
- 邮箱采用轻量格式校验，避免仅为一个字段增加新运行时依赖；电话/微信只限制长度，不臆测地区格式。
- 复用现有认证与 CSRF 中间件，不在 CRM 中记录请求 payload 或联系方式。
- 当前产品是单用户部署，本期不添加 `tenant_id`、负责人或权限表。

## 7. Migration, Compatibility and Rollback

- 新 Alembic revision 从当前 head `0012_playbooks` 向前新增三张表、外键和索引；`env.py` 导入 CRM models。
- 迁移只新增对象，不改写现有表与数据，可与现有 API 向后兼容。
- downgrade 按跟进 → 联系人 → 客户顺序删除；产品回滚可移除路由/导航后再执行 downgrade。
- 实施基于最新 `origin/main` 的隔离工作树，避免本地旧 `main` 和未提交文件污染变更。

## 8. Risks and Deferred Decisions

- 联系方式为个人数据：本期依赖现有登录、数据库访问边界和基础设施静态加密；多租户隔离、字段级加密和审计日志留待真实部署需求明确后处理。
- 全量列表没有分页：本期适合一人公司早期规模；数据量增长后再按真实阈值增加游标分页。
- 客户名称允许重复：避免误拦截同名公司；重复检测与合并属于后续数据治理能力。
- 站外提醒不在本期，因此“到期”只在用户打开 CRM 时可见。
