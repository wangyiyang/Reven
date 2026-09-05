import { useQuery } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { Link } from "react-router-dom"

import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

import { getSummary, listEntries, type FinanceEntry } from "./finance-api"
import { currentMonthShanghai, formatMonthLabel, formatMoney, groupPendingEntries } from "./finance-utils"

export function FinanceOverviewPage() {
  const month = currentMonthShanghai()
  const summaryQuery = useQuery({
    queryKey: ["finance", "summary", month],
    queryFn: () => getSummary(month),
  })
  const pendingQuery = useQuery({
    queryKey: ["finance", "entries", "pending-all"],
    queryFn: () => listEntries({ statuses: ["应收", "应付"] }),
  })
  const summary = summaryQuery.data
  const groups = groupPendingEntries(pendingQuery.data ?? [])

  return (
    <div className="space-y-6">
      <section aria-label="本月收支汇总" className="space-y-3">
        <div className="space-y-1">
          <h2 className="text-lg font-medium text-[var(--ink)]">本月收支</h2>
          <p className="text-xs text-[var(--muted)]">统计周期：本月（{formatMonthLabel(month)}），按实际收付日期计入。</p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 md:gap-4">
          <SummaryCard label="本月实收" value={summary?.income_cents} />
          <SummaryCard label="本月实付" value={summary?.expense_cents} />
          <SummaryCard label="收支净额" value={summary?.net_cents} />
        </div>
      </section>
      <section aria-label="待处理款项" className="space-y-3">
        <h2 className="text-lg font-medium text-[var(--ink)]">待处理款项</h2>
        <PendingDigest groups={groups} />
      </section>
    </div>
  )
}

function SummaryCard({ label, value }: { label: string; value: number | undefined }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-[var(--muted)]">{label}</p>
        <p className="mt-2 text-lg font-semibold text-[var(--ink)]">{value === undefined ? "—" : formatMoney(value)}</p>
      </CardContent>
    </Card>
  )
}

type PendingGroups = ReturnType<typeof groupPendingEntries>

function PendingDigest({ groups }: { groups: PendingGroups }) {
  const overdue = digestOf(groups.overdue)
  const upcoming = digestOf(groups.upcoming)
  if (overdue.count === 0 && upcoming.count === 0) {
    return <p className="text-sm text-[var(--muted)]">暂无待处理款项。</p>
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {overdue.count > 0 ? <DigestCard danger digest={overdue} group="overdue" label="已逾期" /> : null}
      {upcoming.count > 0 ? <DigestCard digest={upcoming} group="upcoming" label="近期到期（7 天内）" /> : null}
    </div>
  )
}

type DirectionDigest = {
  count: number
  total: number
  receivable: { count: number; total: number }
  payable: { count: number; total: number }
}

function digestOf(entries: FinanceEntry[]): DirectionDigest {
  const receivable = entries.filter((entry) => entry.kind === "income")
  const payable = entries.filter((entry) => entry.kind === "expense")
  return {
    count: entries.length,
    total: sumOf(entries),
    receivable: { count: receivable.length, total: sumOf(receivable) },
    payable: { count: payable.length, total: sumOf(payable) },
  }
}

function sumOf(entries: FinanceEntry[]): number {
  return entries.reduce((sum, entry) => sum + entry.amount_cents, 0)
}

function DigestCard({ group, label, digest, danger }: { group: string; label: string; digest: DirectionDigest; danger?: boolean }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className={cn("text-xs", danger ? "text-[var(--danger)]" : "text-[var(--muted)]")}>{label}</p>
        <p className="mt-2 text-lg font-semibold text-[var(--ink)]">{digest.count} 笔 · {formatMoney(digest.total)}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {digest.receivable.count > 0 ? (
            <DirectionLink to={`/finance/pending?tab=receivable&group=${group}`}>
              待收 {digest.receivable.count} 笔 · {formatMoney(digest.receivable.total)}
            </DirectionLink>
          ) : null}
          {digest.payable.count > 0 ? (
            <DirectionLink to={`/finance/pending?tab=payable&group=${group}`}>
              待付 {digest.payable.count} 笔 · {formatMoney(digest.payable.total)}
            </DirectionLink>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

function DirectionLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      className="rounded border border-[var(--line)] px-2 py-1 text-xs text-[var(--signal)] transition-colors hover:border-[var(--signal)]"
      to={to}
    >
      {children}
    </Link>
  )
}
