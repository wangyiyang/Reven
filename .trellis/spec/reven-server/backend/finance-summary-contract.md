# Finance Summary Contract

## 1. Scope / Trigger

Use this contract whenever changing finance entries, the
`/api/finance/summary` endpoint, or the finance summary cards in the React
client. The summary is a cash-status view plus separate receivable and payable
amounts. It is not accrual accounting, a bank balance, a budget, or a runway
calculation.

## 2. Signatures

`GET /api/finance/summary` keeps this JSON shape:

```json
{
  "income_cents": 0,
  "expense_cents": 0,
  "net_cents": 0,
  "receivable_cents": 0,
  "payable_cents": 0
}
```

All values are integer cents. The endpoint accepts an optional `month=YYYY-MM`
query parameter. When `month` is present, the three cash fields
(`income_cents`, `expense_cents`, `net_cents`) count only entries whose
`occurred_on` falls inside that calendar month; `receivable_cents` and
`payable_cents` always remain all-time outstanding amounts regardless of
`month`. Without `month`, all five fields are all-time.

Since the finance workspace redesign (Issue #108), the React client renders
three monthly cash cards on `/finance/overview` plus a separate pending
section fed by `GET /api/finance/entries?status=应收,应付`:

| API field | UI label |
|---|---|
| `income_cents` (with `month`) | `本月实收` |
| `expense_cents` (with `month`) | `本月实付` |
| `net_cents` (with `month`) | `收支净额` |
| `receivable_cents` / `payable_cents` | not shown inside the cash cards; outstanding amounts live only in the pending section and `/finance/pending` |

`POST /api/finance/entries/{id}/confirm` settles an outstanding entry. Request
body: `{"occurred_on": "YYYY-MM-DD"}`. It is the only path that transitions
`应收→已收` or `应付→已付`, and it overwrites `occurred_on` with the actual
settlement date so the entry counts toward that date's month.

## 3. Contracts

Each field has one exact `kind + status` condition:

- `income_cents`: sum `kind=income,status=已收` only.
- `expense_cents`: sum `kind=expense,status=已付` only.
- `net_cents`: `income_cents - expense_cents`.
- `receivable_cents`: sum `kind=income,status=应收` only.
- `payable_cents`: sum `kind=expense,status=应付` only.

Entries with `status=已记录` are not known to be settled or outstanding and
must not contribute to any of the five fields, regardless of `kind`. Do not
infer a cash status, migrate those entries, or count receivables/payables again
inside the three cash cards.

The confirm endpoint enforces the settlement state machine:

| Condition | Expected behavior |
|---|---|
| Entry does not exist | 404 `FINANCE_ENTRY_NOT_FOUND` |
| `status` is `应收` or `应付` | Transition to `已收` / `已付`, overwrite `occurred_on` with the request date, return 200 with the entry |
| Any other `status` (including `已收`, `已付`, `已记录`) | 409 `FINANCE_ENTRY_ALREADY_SETTLED`; the stored entry stays unchanged |
| Missing or invalid `occurred_on` | 422 schema validation |

Confirming is a single-row update that never creates a new entry, so repeated
confirmations cannot double-count cash: the second call receives 409 and the
summary keeps reflecting exactly one settled row.

The page subtitle may describe cash receipts/payments and receivables/payables,
but it must not claim to provide runway until the data model has an actual cash
balance and a defined burn-rate period.

## 4. Validation & Error Matrix

| Condition | Expected behavior |
|---|---|
| No finance entries | Return all five fields as integer zeroes |
| `income + 已收` | Add only to `income_cents` and therefore `net_cents` |
| `expense + 已付` | Add only to `expense_cents` and subtract from `net_cents` |
| `income + 应收` | Add only to `receivable_cents` |
| `expense + 应付` | Add only to `payable_cents` |
| Either kind with `已记录` | Add to none of the five fields |
| Any other stored status or mismatched kind/status pair | Add to none of the five fields; the summary must not infer a cash state |

Existing authentication and CSRF behavior for finance routes remains in
force. The summary endpoint does not accept client-supplied calculation rules.

## 5. Good / Base / Bad Cases

- Good: `¥101.01 income + 已收` and `¥202.02 expense + 已付` produce
  `income_cents=10101`, `expense_cents=20202`, and `net_cents=-10101`.
- Base: an empty ledger returns the complete five-field object with zeroes.
- Good: `income + 应收` and `expense + 应付` appear only in their respective
  outstanding cards.
- Bad: summing every income and expense status into the first three fields;
  this overstates cash and double-counts outstanding amounts in the UI.
- Bad: treating `已记录` as settled because its `kind` is income or expense.

## 6. Tests Required

- Backend summary tests must create `已收`, `已付`, `应收`, `应付`, and both
  income and expense `已记录` entries in one scenario.
- Use distinct amounts so a wrong condition cannot pass through cancellation,
  then assert the complete JSON object rather than isolated fields.
- Keep an empty-summary assertion to preserve zero-value serialization.
- Summary tests must cover `month`: cross-month entries count only toward
  their own month, omitting `month` keeps all-time behavior, and an invalid
  `month` format returns 422.
- Confirm tests must cover: settling `应收`/`应付` into the actual settlement
  month (including a cross-month case), a repeated confirmation returning 409
  with unchanged data, `已收`/`已付`/`已记录` entries returning 409, a missing
  entry returning 404, and a missing body field returning 422.
- Frontend tests must assert the three monthly cash cards (`本月实收`,
  `本月实付`, `收支净额`) with their period label, and that outstanding
  amounts never appear inside the cash cards.
- Frontend tests must assert that the page does not advertise a runway metric.

## 7. Wrong vs Correct

### Wrong

```python
income = func.sum(
    case((FinanceEntry.kind == "income", FinanceEntry.amount_cents), else_=0)
)
```

This treats receivables and ambiguous `已记录` entries as received cash.

### Correct

```python
income_condition = and_(
    FinanceEntry.kind == "income",
    FinanceEntry.status == "已收",
)
income = func.sum(case((income_condition, FinanceEntry.amount_cents), else_=0))
```

Apply the equivalent exact status condition to paid expenses, receivables, and
payables, and derive net cash from the two settled-cash totals.
