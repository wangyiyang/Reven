import { Card, CardContent } from "@/components/ui/card"
import { formatMoney } from "@/features/finance/finance-utils"
import { cn } from "@/lib/utils"

import type { DashboardFinanceSummary } from "./dashboard-api"
import { CardLink } from "./card-link"

export function FinanceReceivableCard({ summary }: { summary: DashboardFinanceSummary | undefined }) {
  const hasOverdue = summary !== undefined && summary.overdue_receivable_count > 0
  return (
    <CardLink label="前往财务待收款" to="/finance/pending">
      <Card className="h-full">
        <CardContent className="p-4">
          <p className="text-xs text-[var(--muted)]">财务待收款</p>
          <p className="mt-2 text-lg font-semibold">
            {summary === undefined ? "—" : formatMoney(summary.receivable_cents)}
          </p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            {summary === undefined ? "读取中…" : `${summary.receivable_count} 笔待收`}
          </p>
          <p className={cn("mt-1 text-xs", hasOverdue ? "font-semibold text-[var(--danger)]" : "text-[var(--muted)]")}>
            {summary === undefined
              ? "逾期 —"
              : `逾期 ${formatMoney(summary.overdue_receivable_cents)} · ${summary.overdue_receivable_count} 笔`}
          </p>
        </CardContent>
      </Card>
    </CardLink>
  )
}
