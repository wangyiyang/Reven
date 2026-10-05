import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

import type { DashboardRssRun, DashboardRssSummary } from "./dashboard-api"
import { CardLink } from "./card-link"

export function RssCandidateCard({ summary }: { summary: DashboardRssSummary | undefined }) {
  return (
    <CardLink label="前往 RSS 待审核" to="/rss/candidates">
      <Card className="h-full">
        <CardContent className="p-4">
          <p className="text-xs text-[var(--muted)]">RSS 待审核</p>
          <p className="mt-2 text-lg font-semibold">{summary === undefined ? "—" : summary.candidate_count}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            {summary === undefined ? "读取中…" : `已保存素材 ${summary.saved_count}`}
          </p>
          <LatestRunStatus run={summary?.latest_run} />
        </CardContent>
      </Card>
    </CardLink>
  )
}

function LatestRunStatus({ run }: { run: DashboardRssRun | null | undefined }) {
  if (run === undefined) return <p className="mt-1 text-xs text-[var(--muted)]">最近抓取 —</p>
  if (run === null) return <p className="mt-1 text-xs text-[var(--muted)]">暂无抓取记录</p>
  const failed = run.failure_count > 0 || run.status === "partial"
  const running = run.status === "running" || run.status === "screening"
  return (
    <p className={cn("mt-1 flex items-center gap-1.5 text-xs", failed ? "font-semibold text-[var(--danger)]" : "text-[var(--muted)]")}>
      <span
        aria-hidden
        className={cn("inline-block h-2 w-2 rounded-full", failed ? "bg-[var(--danger)]" : "bg-[var(--signal)]")}
      />
      {failed
        ? `最近抓取：${run.failure_count} 条失败`
        : running
          ? "最近抓取：进行中"
          : "最近抓取：成功"}
      {run.finished_at ? ` · ${formatRunTime(run.finished_at)}` : ""}
    </p>
  )
}

function formatRunTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}
