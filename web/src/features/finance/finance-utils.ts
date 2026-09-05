import type { FinanceEntry, FinanceEntryKind } from "./finance-api"

export type EntryFormVariant = "income-settled" | "expense-settled" | "receivable" | "payable"

export type EntryVariantConfig = {
  title: string
  kind: FinanceEntryKind
  status: string
  settled: boolean
}

export const ENTRY_VARIANT_CONFIG: Record<EntryFormVariant, EntryVariantConfig> = {
  "income-settled": { title: "记收入", kind: "income", status: "已收", settled: true },
  "expense-settled": { title: "记支出", kind: "expense", status: "已付", settled: true },
  receivable: { title: "新增待收", kind: "income", status: "应收", settled: false },
  payable: { title: "新增待付", kind: "expense", status: "应付", settled: false },
}

export function variantForEntry(entry: FinanceEntry): EntryFormVariant {
  if (entry.status === "应收") return "receivable"
  if (entry.status === "应付") return "payable"
  return entry.kind === "income" ? "income-settled" : "expense-settled"
}

export function formatMoney(cents: number): string {
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(cents / 100)
}

const shanghaiDateFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
})

export function todayShanghai(): string {
  const parts = shanghaiDateFormatter.formatToParts(new Date())
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? ""
  return `${part("year")}-${part("month")}-${part("day")}`
}

export function currentMonthShanghai(): string {
  return todayShanghai().slice(0, 7)
}

export function formatMonthLabel(month: string): string {
  const [year, monthPart] = month.split("-")
  return `${year}年${Number(monthPart)}月`
}

export type PendingGroup = "overdue" | "upcoming" | "later" | "unscheduled"

export const PENDING_GROUP_LABELS: Record<PendingGroup, string> = {
  overdue: "已逾期",
  upcoming: "近期到期",
  later: "以后到期",
  unscheduled: "日期未定",
}

export function pendingGroup(entry: Pick<FinanceEntry, "due_on">, today: string): PendingGroup {
  if (!entry.due_on) return "unscheduled"
  if (entry.due_on < today) return "overdue"
  if (entry.due_on <= addDays(today, 7)) return "upcoming"
  return "later"
}

export function groupPendingEntries(
  entries: FinanceEntry[],
  today: string = todayShanghai(),
): Record<PendingGroup, FinanceEntry[]> {
  const groups: Record<PendingGroup, FinanceEntry[]> = { overdue: [], upcoming: [], later: [], unscheduled: [] }
  for (const entry of entries) {
    groups[pendingGroup(entry, today)].push(entry)
  }
  const byDueAsc = (a: FinanceEntry, b: FinanceEntry) => (a.due_on ?? "").localeCompare(b.due_on ?? "")
  groups.overdue.sort(byDueAsc)
  groups.upcoming.sort(byDueAsc)
  groups.later.sort(byDueAsc)
  groups.unscheduled.sort((a, b) => b.created_at.localeCompare(a.created_at))
  return groups
}

function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}
