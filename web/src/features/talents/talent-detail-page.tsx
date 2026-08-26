import { useQuery } from "@tanstack/react-query"
import { ArrowLeft } from "lucide-react"
import { Link, Navigate, useParams } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"

import { InteractionsSection } from "./interactions-section"
import { getTalent, talentsKeys } from "./talents-api"
import type { Talent } from "./types"

export function TalentDetailPage() {
  const { talentId } = useParams()
  if (!talentId) return <Navigate replace to="/talents" />
  return <TalentDetail talentId={talentId} />
}

function TalentDetail({ talentId }: { talentId: string }) {
  const talentQuery = useQuery({ queryKey: talentsKeys.talent(talentId), queryFn: () => getTalent(talentId) })
  if (talentQuery.isLoading) return <PageState message="正在加载人才…" />
  if (talentQuery.isError || !talentQuery.data) {
    return <PageState action={() => void talentQuery.refetch()} message="人才不存在或加载失败。" />
  }
  return (
    <main className="page-enter mx-auto w-full max-w-6xl space-y-6 px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <DetailHeading talent={talentQuery.data} />
      <TalentSummary talent={talentQuery.data} />
      <InteractionsSection talentId={talentId} />
    </main>
  )
}

function DetailHeading({ talent }: { talent: Talent }) {
  return (
    <div className="space-y-3">
      <Link className="inline-flex items-center gap-1 text-sm" to="/talents"><ArrowLeft aria-hidden size={15} />返回人才库</Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-[var(--ink)]">{talent.name}</h1>
        <Badge>{talent.status}</Badge>
        {talent.rating !== null ? <span className="text-sm text-[var(--muted)]">★ {talent.rating}/5</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-[var(--muted)]">{talent.organization ?? "未记录机构"}</p>
        {talent.tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}
      </div>
    </div>
  )
}

function SummaryItem({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <p className="text-xs text-[var(--muted)]">{label}</p>
      <p className="mt-1 whitespace-pre-wrap text-sm">{value ?? "未记录"}</p>
    </div>
  )
}

function TalentSummary({ talent }: { talent: Talent }) {
  const rate = talent.rate_amount !== null && talent.rate_unit !== null
    ? `¥${talent.rate_amount} ${talent.rate_unit}`
    : null
  return (
    <Card>
      <CardHeader><h2 className="text-lg font-medium text-[var(--ink)]">人才档案</h2></CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        <SummaryItem label="能力" value={talent.capability} />
        <SummaryItem label="可用时间" value={talent.availability} />
        <SummaryItem label="合作条件" value={talent.engagement_terms} />
        <SummaryItem label="费率" value={rate} />
        {talent.notes ? <div className="md:col-span-2"><SummaryItem label="备注" value={talent.notes} /></div> : null}
      </CardContent>
    </Card>
  )
}

function PageState({ message, action }: { message: string; action?: () => void }) {
  return (
    <main className="mx-auto flex min-h-[50vh] max-w-xl flex-col items-center justify-center gap-4 px-5 text-center">
      <p className="text-sm text-[var(--muted)]">{message}</p>
      <div className="flex gap-2"><Link className="inline-flex h-9 items-center rounded-md border border-[var(--line)] px-3 text-xs font-semibold text-[var(--ink)] hover:no-underline" to="/talents">返回人才库</Link>{action ? <Button onClick={action} size="sm" type="button">重新加载</Button> : null}</div>
    </main>
  )
}
