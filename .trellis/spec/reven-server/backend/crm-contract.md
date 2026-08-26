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

- Migration: upgrade from `0012_playbooks`, downgrade back to it, and upgrade
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
contact = await repository.get_contact(customer_id, contact_id)
if contact is None:
    return crm_contact_not_found()
```

The same ownership rule applies to follow-ups. The database foreign key is not
a substitute for route-level aggregate scoping.
