# CRM Aggregate Contract

## 1. Scope / Trigger

Use this contract whenever changing the single-owner B2B CRM across PostgreSQL,
FastAPI, or the React client. The aggregate contains customers, contacts, and
follow-up history. It intentionally does not include leads, opportunities,
projects, finance records, external reminders, or multi-tenant ownership.

## 2. Signatures

API prefix: `/api/crm`.

| Method | Path | Result |
|---|---|---|
| `GET` | `/customers` | `Customer[]` filtered by `query`, `status`, and `due` |
| `POST` | `/customers` | Create a customer |
| `GET/PUT/DELETE` | `/customers/{customer_id}` | Read, update, or delete one customer |
| `GET/POST` | `/customers/{customer_id}/contacts` | List or create contacts |
| `PUT/DELETE` | `/customers/{customer_id}/contacts/{contact_id}` | Update or delete an owned contact |
| `GET/POST` | `/customers/{customer_id}/follow-ups` | List or create follow-ups |
| `PUT/DELETE` | `/customers/{customer_id}/follow-ups/{follow_up_id}` | Update or delete owned history |

### 共享写操作入口

`CrmService(session)` 拥有 repository、实体查找、客户范围、业务规则与提交。
写入调用方只传 `UUID` 和 `reven.crm.inputs` 中的已校验输入：

```python
create_customer(payload: CustomerCreate) -> Customer
update_customer(customer_id: UUID, payload: CustomerUpdate) -> Customer
delete_customer(customer_id: UUID) -> Customer
create_contact(customer_id: UUID, payload: ContactCreate) -> tuple[Customer, Contact]
update_contact(customer_id: UUID, contact_id: UUID, payload: ContactUpdate) -> Contact
delete_contact(customer_id: UUID, contact_id: UUID) -> Contact
create_follow_up(customer_id: UUID, payload: FollowUpCreate) -> tuple[Customer, FollowUp]
update_follow_up(customer_id: UUID, follow_up_id: UUID, payload: FollowUpUpdate) -> FollowUp
delete_follow_up(customer_id: UUID, follow_up_id: UUID) -> FollowUp
```

创建子资源返回客户和资源，供 MCP 展示客户名称；REST 只序列化资源。
读操作继续使用 `CrmRepository`。不增加通用 CRUD interface。
`api.schemas.crm` 显式重导出六个输入类，保留外部请求 schema 名称；
响应类仍由 API 拥有，MCP 不依赖 API schema。

Database tables:

- `crm_customers(id UUID PK, name, status, source, notes, next_action, next_follow_up_on, timestamps)`
- `crm_contacts(id UUID PK, customer_id FK CASCADE, channels, is_primary, timestamps)`
- `crm_follow_ups(id UUID PK, customer_id FK CASCADE, contact_id FK SET NULL, contact_name_snapshot, history fields, timestamps)`

## 3. Contracts

Customer statuses are exactly `潜在客户`, `跟进中`, `合作客户`, `暂停跟进`,
and `已流失`. Follow-up kinds are exactly `电话`, `会议`, `微信`, `邮件`, and
`其他`.

`due` accepts `overdue`, `today`, `upcoming`, or `none`; comparisons use the
Asia/Shanghai calendar date. Any code or test that needs "today" must take it
from `reven.scheduling.SHANGHAI` (`datetime.now(SHANGHAI).date()`), never
`date.today()` — the latter follows the runner's local timezone and flakes in
CI during the UTC 16:00–24:00 window when Shanghai has already crossed
midnight but UTC has not. Search covers customer name/source/notes and
contact name/phone/email/WeChat through an `EXISTS` subquery so one customer is
never duplicated by multiple matching contacts.

All responses use UUID strings, ISO dates (`YYYY-MM-DD`), and ISO datetimes.
Optional text is trimmed and stored/returned as `null`, not an empty string.
The browser owns typed request serialization in `web/src/features/crm/crm-api.ts`.

`set_as_current` exists only on follow-up creation. When true, the new history
snapshot and the customer's current `next_action` / `next_follow_up_on` are
committed in one transaction. Updating or deleting history never rewrites the
customer's current action.

更新必须用 `model_dump(exclude_unset=True)` 区分未提交字段与显式 `null`。
更新行动/日期时，服务先合并数据库现值和提交值，再校验最终计划；不得以
`exclude_none=True` 丢弃清空请求。工具中的 `clear_*` 标志由 MCP adapter
转换成输入字段的显式 `None`，不进入领域服务。

## 4. Validation & Error Matrix

| Condition | Expected behavior |
|---|---|
| Unknown request field | FastAPI/Pydantic `422` |
| Empty required name or summary | `422` |
| Invalid status, follow-up kind, email, or field length | `422` |
| `next_follow_up_on` without a non-empty `next_action` | `422`; DB check constraint is the final guard |
| `set_as_current=true` without `next_action` | `422` |
| Missing customer | `404 / CRM_CUSTOMER_NOT_FOUND` |
| Contact ID outside the route customer | `404 / CRM_CONTACT_NOT_FOUND` |
| Follow-up ID outside the route customer | `404 / CRM_FOLLOW_UP_NOT_FOUND` |
| 服务找不到客户 | `CustomerNotFoundError`，REST 映射已有客户 404，MCP 保留中文提示 |
| 服务找不到客户范围内联系人 | `ContactNotFoundError`，REST 映射已有联系人 404 |
| 服务找不到客户范围内跟进 | `FollowUpNotFoundError`，REST 映射已有跟进 404 |
| 更新后的行动/日期组合非法 | `InvalidActionPairError`，REST `422 / CRM_NEXT_ACTION_REQUIRED` |
| 只提交 `contact_id` 或工具 `clear_contact=true` | 有效更新，关联或解除联系人并同步快照；不得判为空操作 |

CRM request payloads and contact channels must never be written to application
logs. Existing authentication and CSRF middleware protect every CRM route.

## 5. Good / Base / Bad Cases

- Good: create a follow-up with a contact, next action/date, and
  `set_as_current=true`; both history and current customer state advance.
- Base: create a customer with only a name; defaults to `潜在客户` with no
  follow-up plan.
- Bad: update a nested contact using another customer's path; return the scoped
  `404` without revealing that the contact exists elsewhere.
- Bad: delete a contact and cascade its follow-ups. Correct behavior is
  `contact_id = NULL` while retaining `contact_name_snapshot`.

## 6. Tests Required

- 共享服务真实 PostgreSQL：缺失与跨客户范围拒绝、主联系人唯一切换、
  联系人删除后历史快照保留、部分更新与显式清空、行动/日期合并校验、
  `set_as_current` 单次提交，以及历史修改不覆盖客户当前计划。
- MCP：仅修改/清空跟进联系人回归；REST/MCP 保留输入形状、序列化、错误映射。
  共享业务规则主要在服务 interface 验证，不在两个 adapter 再复制完整规则测试。

- Migration: upgrade from `0012_sops`, downgrade back to it, and upgrade
  to head; assert foreign keys, check constraints, and the partial unique index.
- API: customer CRUD; all five statuses; search; all due filters; invalid input;
  ownership rejection; one-primary-contact switching; history order;
  `set_as_current`; contact snapshot retention; customer cascade deletion.
- Frontend: typed request payloads; list loading/empty/error states; desktop and
  mobile representations; create/edit/delete confirmation; query filters;
  contact primary selection; history editing without `set_as_current`.
- Runtime: exercise the migrated API through the browser in desktop/mobile and
  light/dark modes; verify no whole-page horizontal overflow.

## 7. Wrong vs Correct

### Wrong

```python
# Fetching by child ID alone leaks or mutates another customer's resource.
contact = await session.get(Contact, contact_id)
```

### Correct

```python
try:
    contact = await CrmService(session).update_contact(customer_id, contact_id, payload)
except ContactNotFoundError:
    return crm_contact_not_found()
```

The same ownership rule applies to follow-ups. The database foreign key is not
a substitute for aggregate scoping in the shared service.
