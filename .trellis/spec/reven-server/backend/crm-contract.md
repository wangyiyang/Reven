# CRM Aggregate Contract

## 1. Scope / Trigger

Use this contract whenever changing the single-owner B2B CRM across PostgreSQL,
FastAPI, or the React client. The aggregate contains customers, contacts, and
follow-up history. It intentionally does not include leads, opportunities,
projects, finance records, external reminders, or multi-tenant ownership.

**客户的「当前跟进计划」是派生读模型，不是客户表字段**（0025 起）：唯一权威
来源是该客户最新一条跟进记录上的 `next_action / next_due_on`。任何写路径都
不得把计划回写到客户表；任何读路径都必须经 `CrmRepository` 的派生子查询取
值，不得自行 join/子查询另造语义。

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
`api.schemas.crm` 显式重导出六个输入类，保留外部请求 schema 名称；
响应类仍由 API 拥有，MCP 不依赖 API schema。

### 派生读入口（CrmRepository）

```python
@dataclass(frozen=True)
class CustomerPlan:
    customer: Customer
    next_action: str | None   # 最新一条跟进的 next_action，无跟进为 None
    next_due_on: date | None  # 最新一条跟进的 next_due_on，无跟进为 None

list_customers(*, status, due, query, today) -> list[CustomerPlan]
get_customer_plan(customer_id) -> CustomerPlan | None
list_due_follow_ups(*, today, limit) -> list[CustomerPlan]   # 派生 next_due_on <= today
count_due_follow_ups(*, today) -> tuple[int, int]            # (overdue, today) 客户数
```

「最新一条」的排序定义为 `occurred_on desc, created_at desc, id desc limit 1`，
由 `_latest_action_subquery / _latest_due_subquery` 两个相关标量子查询实现；
列表排序、`due` 过滤、待跟进、dashboard 计数、提醒全部共用这两个子查询。
dashboard 计数必须用 `count_due_follow_ups`（按客户计数），禁止 join
`FollowUp` 直数（一个客户多条历史会重复计数）。

Database tables:

- `crm_customers(id UUID PK, name, status, source, notes, timestamps)` — 无计划列
- `crm_contacts(id UUID PK, customer_id FK CASCADE, channels, is_primary, timestamps)`
- `crm_follow_ups(id UUID PK, customer_id FK CASCADE, contact_id FK SET NULL, contact_name_snapshot, kind, occurred_on, summary, next_action, next_due_on, timestamps)`

## 3. Contracts

Customer statuses are exactly `潜在客户`, `跟进中`, `合作客户`, `暂停跟进`,
and `已流失`. Follow-up kinds are exactly `电话`, `面谈`, `微信`, `邮件`, and
`其他`（0027 起 `会议` 并入 `面谈`，与 talents 互动方式统一为同一五值集合）.

`due` accepts `overdue`, `today`, `upcoming`, or `none`; comparisons use the
Asia/Shanghai calendar date and compare against the **derived** `next_due_on`
（`none` = 无跟进或最新跟进未定日期）。Any code or test that needs "today" must
take it from `reven.scheduling.SHANGHAI` (`datetime.now(SHANGHAI).date()`), never
`date.today()` — the latter follows the runner's local timezone and flakes in
CI during the UTC 16:00–24:00 window when Shanghai has already crossed
midnight but UTC has not. Search covers customer name/source/notes and
contact name/phone/email/WeChat through an `EXISTS` subquery so one customer is
never duplicated by multiple matching contacts.

All responses use UUID strings, ISO dates (`YYYY-MM-DD`), and ISO datetimes.
Optional text is trimmed and stored/returned as `null`, not an empty string.
The browser owns typed request serialization in `web/src/features/crm/crm-api.ts`.

**计划派生契约**：

- `CustomerResponse.next_action / next_due_on` 为只读派生值（来自最新一条跟进，
  无跟进时为 `null`）；路由经 `_customer_response` 组装注入，不得裸返 ORM。
- `POST/PUT /customers` 不接受计划字段（`extra="forbid"` → 422）；新建客户后
  引导记第一条跟进（web 空态按钮 + MCP `crm_customer_create` 话术）。
- 记一条带 `next_action / next_due_on` 的跟进后，客户级读路径（列表/详情/
  待跟进/提醒/dashboard）同事务立即可见该计划，无任何客户表写入。
- 更新/删除跟进后派生计划随之变化：删除最新一条则回退到次新跟进的计划，
  再删则归零。补录早于最新跟进的历史记录不改变当前计划，MCP 返回话术必须
  如实说明「客户当前计划不变」，不得无条件声称已生效。
- MCP 工具无 `set_as_current` / `clear_next_follow_up_on`；跟进更新的清除开关
  为 `clear_next_due_on`。

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
| `next_due_on` without a non-empty `next_action` | `422`; DB check constraint `ck_crm_follow_ups_follow_up_action` is the final guard |
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

- Good: create a follow-up with `next_action` and `next_due_on`; the customer's
  list/detail/due views immediately show that plan with zero writes to
  `crm_customers`.
- Base: create a customer with only a name; defaults to `潜在客户`, derived plan
  is `null`, UI/agent guide the user to record the first follow-up.
- Bad: backfill a follow-up older than the latest one; the current plan must
  stay with the latest record, and MCP output must not claim it changed.
- Bad: update a nested contact using another customer's path; return the scoped
  `404` without revealing that the contact exists elsewhere.
- Bad: delete a contact and cascade its follow-ups. Correct behavior is
  `contact_id = NULL` while retaining `contact_name_snapshot`.

## 6. Tests Required

- 共享服务真实 PostgreSQL：缺失与跨客户范围拒绝、主联系人唯一切换、
  联系人删除后历史快照保留、部分更新与显式清空、行动/日期合并校验、
  派生计划随最新跟进变化、删除最新跟进回退次新/归零、补录历史不改当前计划。
- MCP：仅修改/清空跟进联系人回归；REST/MCP 保留输入形状、序列化、错误映射。
  共享业务规则主要在服务 interface 验证，不在两个 adapter 再复制完整规则测试。
- Migration（0025）：upgrade 后 `crm_customers` 无计划列/约束、
  `crm_follow_ups.next_due_on` 存在且配对 check 保留（违例插入被拒）；
  downgrade 回退后再 upgrade 恢复；`FINAL_REVISION` 单 head 断言同步。
- API: customer CRUD; all five statuses; search; all due filters on derived
  values; invalid input; ownership rejection; one-primary-contact switching;
  history order; derived plan on list/detail; contact snapshot retention;
  customer cascade deletion.
- Frontend: typed request payloads（create/update customer 无计划字段、
  follow-up body 无 `set_as_current`）; list loading/empty/error states;
  first-follow-up guide; due card derived fields.
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

### Wrong

```python
# 另造「当前计划」语义：join 跟进历史直数到期客户（重复计数），
# 或试图读/写客户表上已不存在的计划列。
select(func.count()).select_from(Customer).join(FollowUp).where(FollowUp.next_due_on < today)
```

### Correct

```python
# 一切计划读写都走 repository 的统一派生子查询 / CustomerPlan。
overdue, due_today = await CrmRepository(session).count_due_follow_ups(today=today)
plans = await CrmRepository(session).list_due_follow_ups(today=today, limit=21)
```
