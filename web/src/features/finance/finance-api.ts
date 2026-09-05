import { apiRequest } from "@/lib/api"

export type FinanceEntryKind = "income" | "expense"

export type FinanceEntry = {
  id: string
  kind: FinanceEntryKind
  name: string
  amount_cents: number
  category: string | null
  occurred_on: string
  due_on: string | null
  recurrence: string | null
  source: string | null
  status: string
  notes: string | null
  created_at: string
  updated_at: string
}

export type FinanceSummary = {
  income_cents: number
  expense_cents: number
  net_cents: number
  receivable_cents: number
  payable_cents: number
}

export type FinanceEntryPayload = {
  kind: FinanceEntryKind
  name: string
  amount: number
  category: string | null
  occurred_on: string
  due_on: string | null
  recurrence: string | null
  source: string | null
  status: string
  notes: string | null
}

export type ListEntriesParams = {
  kind?: FinanceEntryKind
  statuses?: string[]
  month?: string
  category?: string
  query?: string
}

export function listEntries(params: ListEntriesParams = {}): Promise<FinanceEntry[]> {
  const search = new URLSearchParams()
  if (params.kind) search.set("kind", params.kind)
  if (params.statuses?.length) search.set("status", params.statuses.join(","))
  if (params.month) search.set("month", params.month)
  if (params.category?.trim()) search.set("category", params.category.trim())
  if (params.query?.trim()) search.set("query", params.query.trim())
  const suffix = search.size ? `?${search.toString()}` : ""
  return apiRequest<FinanceEntry[]>(`/finance/entries${suffix}`)
}

export function getSummary(month?: string): Promise<FinanceSummary> {
  const suffix = month ? `?month=${encodeURIComponent(month)}` : ""
  return apiRequest<FinanceSummary>(`/finance/summary${suffix}`)
}

export function createEntry(payload: FinanceEntryPayload): Promise<FinanceEntry> {
  return apiRequest<FinanceEntry>("/finance/entries", { method: "POST", body: JSON.stringify(payload) })
}

export function updateEntry(id: string, payload: FinanceEntryPayload): Promise<FinanceEntry> {
  return apiRequest<FinanceEntry>(`/finance/entries/${id}`, { method: "PUT", body: JSON.stringify(payload) })
}

export function deleteEntry(id: string): Promise<null> {
  return apiRequest<null>(`/finance/entries/${id}`, { method: "DELETE" })
}

export function confirmEntry(id: string, occurred_on: string): Promise<FinanceEntry> {
  return apiRequest<FinanceEntry>(`/finance/entries/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({ occurred_on }),
  })
}
