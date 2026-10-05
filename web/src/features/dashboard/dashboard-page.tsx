import { useQuery } from "@tanstack/react-query"

import { ErrorPanel } from "@/components/ui/error-panel"

import { ActiveProjectCard } from "./active-project-card"
import { CrmDueCard } from "./crm-due-card"
import { fetchDashboardSummary } from "./dashboard-api"
import { FinanceReceivableCard } from "./finance-receivable-card"
import { IntegrationMissingBanner } from "./integration-missing-banner"
import { RssCandidateCard } from "./rss-candidate-card"

export function DashboardPage() {
  const summaryQuery = useQuery({ queryKey: ["dashboard", "summary"], queryFn: fetchDashboardSummary })
  const summary = summaryQuery.data

  return (
    <main className="page-enter mx-auto w-full max-w-5xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">工作台</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">聚合需要判断和处理的经营事项。</p>
      </header>
      {summaryQuery.isError && (
        <ErrorPanel
          message={summaryQuery.error.message}
          retry={() => void summaryQuery.refetch()}
          title="工作台数据读取失败"
        />
      )}
      {summary && <IntegrationMissingBanner summary={summary.integrations} />}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <FinanceReceivableCard summary={summary?.finance} />
        <RssCandidateCard summary={summary?.rss} />
        <CrmDueCard summary={summary?.crm} />
        <ActiveProjectCard summary={summary?.projects} />
      </div>
    </main>
  )
}
