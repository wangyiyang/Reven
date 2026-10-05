import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

import type { DashboardProjectItem, DashboardProjectSummary } from "./dashboard-api"
import { CardLink } from "./card-link"

export function ActiveProjectCard({ summary }: { summary: DashboardProjectSummary | undefined }) {
  return (
    <CardLink label="前往项目列表" to="/projects">
      <Card className="h-full">
        <CardContent className="p-4">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-xs text-[var(--muted)]">进行中项目</p>
            <p className="text-sm font-semibold">{summary?.active_count ?? "—"}</p>
          </div>
          {summary !== undefined && summary.items.length === 0 ? (
            <p className="mt-3 text-sm text-[var(--muted)]">暂无进行中项目。</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {(summary?.items ?? []).map((item) => (
                <ProjectRow item={item} key={item.id} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </CardLink>
  )
}

function ProjectRow({ item }: { item: DashboardProjectItem }) {
  return (
    <li className="flex items-baseline justify-between gap-2">
      <span className="min-w-0 truncate text-sm">{item.name}</span>
      <span className={cn("shrink-0 text-xs", item.overdue ? "font-semibold text-[var(--danger)]" : "text-[var(--muted)]")}>
        {item.due_on ?? "无到期日"}
      </span>
    </li>
  )
}
