# Talents MVP 技术设计

## 1. Architecture

```
web/src/features/talents/          server/src/reven/
  talents-page.tsx ──┐               api/routes/talents.py   ← HTTP 语义、错误码映射
  talent-detail-page ├─ apiRequest → api/schemas/talents.py  ← pydantic 校验、extra="forbid"
  talents-api.ts   ──┘               talents/service.py      ← 写路径编排、事务
                                     talents/repository.py   ← 查询/持久化，无 HTTP 语义
                                     talents/models.py       ← ORM + 枚举定义
                                     migrations/versions/0015_talents.py
```

边界职责与 CRM 完全一致：路由层不做业务校验，schema 层做字段/枚举校验，service 层做写路径事务与不变量，repository 只做 select/flush。读路径（GET 列表/详情）路由可直接调 repository，写路径一律走 service。

## 2. Data Model

### talents

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK, default uuid4 | |
| name | Text, NOT NULL | |
| organization | Text | |
| tags | JSONB, NOT NULL default '[]' | 字符串数组；迁移加 CheckConstraint 保证是数组（`jsonb_typeof = 'array'`） |
| capability | Text | 能力描述 |
| engagement_terms | Text | 合作条件 |
| availability | Text | 可用时间 |
| rate_amount | Numeric(12,2) | 费率数字，可空 |
| rate_unit | String(16) | 按小时/按天/按项目，CheckConstraint；可空 |
| rating | SmallInteger | 1–5，CheckConstraint；可空 |
| status | String(16), NOT NULL default '候选' | 候选/接洽中/已合作/搁置，CheckConstraint |
| notes | Text | |
| created_at / updated_at | DateTime(tz), utc_now / onupdate | |

索引：`ix_talents_status`（status）；tags 过滤规模小，顺序扫描即可，不上 GIN（几十到几百行）。

### talent_interactions

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| talent_id | UUID FK → talents.id ON DELETE CASCADE | |
| occurred_on | Date, NOT NULL | |
| channel | String(16), NOT NULL | 面谈/电话语音/微信/邮件，CheckConstraint |
| summary | Text | |
| next_action | Text | |
| next_due_on | Date | |
| created_at | DateTime(tz) | |

索引：`(talent_id, occurred_on)`、`(next_due_on)`，对齐旧设计与 CRM follow_ups。

两表迁移均 `ENABLE ROW LEVEL SECURITY`。

## 3. Business Invariants

1. 枚举值以中文文本存储；pydantic schema 校验为 422 第一道闸，DB CheckConstraint 为第二道闸。
2. `rating` 非空时必须 ∈ [1,5]（schema + CheckConstraint）。
3. `rate_amount` 与 `rate_unit` 必须同时为空或同时非空（schema 层 model_validator；DB 用 CHECK 双保险）。
4. PATCH 显式传 null 时，`name` / `status` / `occurred_on` / `channel` 等 NOT NULL 字段拒绝（422），对齐 CRM `_reject_explicit_null` 模式。
5. 跟进嵌套路由查询同时匹配 `talent_id` + `interaction_id`，防跨属访问（跨属返回 404）。
6. 追加/删除跟进仅刷新人才 `updated_at`，无状态流转；删除人才级联删除跟进（DB CASCADE）。
7. `due` 过滤基于该人才全部跟进的最早 `next_due_on`：overdue < today；today = today；upcoming > today；none = 无任何带 next_due_on 的跟进。today 按上海时区（对齐 CRM `datetime.now(SHANGHAI).date()`）。
8. 标签是自由文本数组，无词表约束；一致性由前端补全引导，后端不做去重/归一。

## 4. API Contract

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/talents?status=&due=&q=&tag=` | 列表，按 updated_at desc, id 排序；无分页 |
| POST | `/api/talents` | 201 创建 |
| GET | `/api/talents/{talent_id}` | 详情，404 `TALENT_NOT_FOUND` |
| PATCH | `/api/talents/{talent_id}` | 部分更新，422/404 |
| DELETE | `/api/talents/{talent_id}` | 204，级联删跟进 |
| GET | `/api/talents/{talent_id}/interactions` | 按 occurred_on desc, created_at desc, id desc |
| POST | `/api/talents/{talent_id}/interactions` | 201 |
| PATCH | `/api/talents/interactions/{interaction_id}` | 422/404 `TALENT_INTERACTION_NOT_FOUND` |
| DELETE | `/api/talents/interactions/{interaction_id}` | 204 |

错误格式统一 `{"code": "...", "message": "中文"}`。`q` 限长 1–200，ilike 转义 `\ % _`。`tag` 为精确匹配（`tags.contains([tag])`）。

## 5. Frontend Design

路由：`/talents`（列表）、`/talents/:talentId`（详情）。导航："人才库"，lucide 图标（如 `Users`），插入 `app-shell.tsx` navigation 数组并更新 `app-shell.test.tsx` label 列表。

文件边界（同构 `web/src/features/crm/`）：

```
features/talents/
  types.ts                  # 类型与中文枚举数组唯一所有者
  talents-api.ts            # 路径与序列化唯一所有者 + talentsKeys
  talents-page.tsx          # 列表页：工具条(status/due/tag/q) + 编辑器卡片 + 列表卡片
  talent-detail-page.tsx    # 详情页：摘要卡 + interactions-section
  talent-form.tsx / talent-form-model.ts
  use-talent-mutations.ts   # mutation + invalidate + toast
  talent-list.tsx           # 表格/卡片 + 逾期徽标
  interactions-section.tsx
  talents-page.test.tsx / talent-detail-page.test.tsx
```

UX 规则：
- 标签输入控件：自由输入 + 补全（候选来自当前列表数据 `flatMap(tags)` 去重）；展示为徽章
- 费率录入：数字 + 单位下拉（按小时/按天/按项目），两者同填同清（对应不变量 3）
- 评分录入：1–5 星或下拉；可清空
- 删除统一走 ConfirmDialog；样式只用 CSS 变量令牌；单文件 <500 行、单函数 <50 行
- date-utils 先查 `features/crm/date-utils.ts` 可否复用导出，不能则拷贝最小实现（不抽共享包，两处实现允许小重复）

## 6. Validation and Security

- 全部端点走既有 `AuthMiddleware` + `CsrfOriginMiddleware`，无新增公开面
- pydantic `extra="forbid"`；字符串字段 StringConstraints 限长（name ≤200，文本字段 ≤2000，tags 单标签 ≤50、总数 ≤20）
- 敏感信息（合作条件、费率）不写日志
- RLS 开启（迁移内），与现有表一致

## 7. Migration, Compatibility and Rollback

- `0015_talents.py`，`down_revision = "0014_merge_crm_and_integration"`（当前唯一 head，已用 `alembic heads` 核实）
- `env.py` 增加 `from reven.talents.models import Talent, TalentInteraction  # noqa: F401`
- 迁移只增不改；downgrade 按 talent_interactions → talents 顺序 drop
- 测试基建：两处 conftest TRUNCATE 清单加 `talent_interactions, talents`（子表在前）
- 回滚：web 端删路由/导航 + server 端 downgrade + 删模块目录即可，无数据耦合其他表

## 8. Risks and Deferred Decisions

- 标签分裂风险：仅前端补全引导，无强制归一；接受，规模可控
- 提醒机制缺失是刻意取舍；后续跨模块提醒任务立项时 talents 的 `next_due_on` 直接接入
- Notion 旧数据（备份脚本里约 8 人）如需进系统，将来用一次性脚本手工映射导入，模型不留 Notion 字段
- CRM 的 `crm-contract.md` 规范若与本文冲突，以规范为准并回写本文
