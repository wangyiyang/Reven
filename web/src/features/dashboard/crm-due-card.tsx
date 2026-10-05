import { Link } from "react-router-dom"

import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

import type { DashboardCrmDueItem, DashboardCrmSummary } from "./dashboard-api"

/**
 * CRM 待跟进清单卡：清单项需跳到客户详情（a 嵌套 a 非法），
 * 故卡片不整卡套链接，标题行的"查看全部"承担 /crm 跳转。
 */
export function CrmDueCard({ summary }: { summary: DashboardCrmSummary | undefined }) {
  const overdueCount = summary?.overdue_count
  return (
    <Card className="h-full">
      <CardContent className="p-4">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-xs text-[var(--muted)]">CRM 待跟进</p>
          <Link aria-label="前往 CRM" className="text-xs" to="/crm">
            查看全部
          </Link>
        </div>
        <p className="mt-2 text-sm">
          <span className={cn(overdueCount !== undefined && overdueCount > 0 ? "font-semibold text-[var(--danger)]" : "text-[var(--muted)]")}>
            逾期 {overdueCount ?? "—"}
          </span>
          <span className="text-[var(--muted)]"> / 今日 {summary?.today_count ?? "—"}</span>
        </p>
        {summary !== undefined && summary.due_items.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--muted)]">暂无待跟进客户。</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {(summary?.due_items ?? []).map((item) => (
              <DueItemRow item={item} key={item.customer_id} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function DueItemRow({ item }: { item: DashboardCrmDueItem }) {
  const overdue = item.overdue_days > 0
  return (
    <li>
      <Link
        aria-label={`查看客户 ${item.name}`}
        className="-mx-1 flex items-baseline justify-between gap-2 rounded px-1 text-[var(--ink)] no-underline hover:bg-[var(--faint)] hover:no-underline"
        to={`/crm/customers/${item.customer_id}`}
      >
        <span className="min-w-0 truncate text-sm">{item.name}</span>
        <span className={cn("shrink-0 text-xs", overdue ? "font-semibold text-[var(--danger)]" : "text-[var(--muted)]")}>
          {overdue ? `逾期 ${item.overdue_days} 天 · ` : ""}
          {item.next_follow_up_on}
        </span>
      </Link>
    </li>
  )
}
