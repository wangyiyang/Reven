import { ArrowUpRight, Check, Rss, X } from "lucide-react"
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import type { RssCandidate } from "./types"
import { useRssCandidatesController } from "./use-rss-candidates-controller"

export function RssCandidatesPage() {
  const controller = useRssCandidatesController()
  const visible = controller.items
  const remaining = (controller.total ?? 0) - visible.length
  return (
    <main className="page-enter mx-auto w-full max-w-7xl px-5 py-10 sm:px-8 lg:px-12 lg:py-14">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-2xl font-semibold">RSS 候选工作台</h1>
        <p className="text-sm text-[var(--muted)]">待审 <span className="font-semibold text-[var(--ink)]">{controller.total ?? "—"}</span></p>
      </header>

      {controller.candidates.isLoading && <p aria-busy="true" className="text-sm text-[var(--muted)]">正在读取候选…</p>}
      {controller.candidates.isError && (
        <div className="border border-[var(--danger)] bg-[var(--faint)] p-5 text-sm text-[var(--danger)]" role="alert">
          <p>RSS 候选读取失败：{controller.candidates.error.message}</p>
          <Button className="mt-4" onClick={() => controller.candidates.refetch()} size="sm" variant="outline">重新读取</Button>
        </div>
      )}
      {controller.total === 0 && <EmptyQueue />}
      <ol className="grid gap-6">
        {visible.map((candidate, index) => (
          <CandidateCard
            busy={controller.busyId === candidate.id}
            candidate={candidate}
            index={index + 1}
            key={candidate.id}
            onConfirm={() => controller.confirm(candidate.id)}
            onIgnore={() => controller.ignore(candidate.id)}
          />
        ))}
      </ol>
      {controller.hasNextPage && (
        <div className="mt-6 flex justify-center">
          <Button
            disabled={controller.isFetchingNextPage}
            onClick={() => controller.fetchNextPage()}
            type="button"
            variant="outline"
          >
            {controller.isFetchingNextPage ? "正在加载…" : `加载更多（还剩 ${remaining} 条）`}
          </Button>
        </div>
      )}
    </main>
  )
}

function EmptyQueue() {
  return (
    <section className="grid min-h-72 place-items-center rounded-lg border border-dashed border-[var(--line)] bg-[var(--faint)] text-center">
      <div><Rss aria-hidden className="mx-auto text-[var(--muted)]" /><h2 className="mt-4 text-base font-semibold">候选队列已清空</h2><p className="mt-2 text-sm text-[var(--muted)]">下一次定时发现完成后，新候选会出现在这里。</p></div>
    </section>
  )
}

function CandidateCard(props: {
  candidate: RssCandidate
  index: number
  busy: boolean
  onConfirm: () => Promise<unknown>
  onIgnore: () => Promise<unknown>
}) {
  const { candidate } = props
  const [expanded, setExpanded] = useState(false)
  const summaryText = candidate.summary_zh || candidate.summary || "暂无摘要"
  const isLongSummary = summaryText.length > 240
  return (
    <li className="candidate-card grid overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--bg)] lg:grid-cols-[minmax(0,1fr)_20rem]">
      <article className="p-5 sm:p-7">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-[var(--muted)]">
          <span>#{String(props.index).padStart(2, "0")}</span>
          <span>{candidate.source_name}</span><span aria-hidden>·</span><time>{formatDate(candidate.published_at)}</time>
        </div>
        <h2 className="mt-4 text-lg font-semibold leading-tight">{candidate.title_zh}</h2>
        {candidate.title_zh !== candidate.title && <p className="mt-2 text-sm italic text-[var(--muted)]">{candidate.title}</p>}
        <p className={`mt-5 max-w-3xl text-sm leading-7${isLongSummary && !expanded ? " line-clamp-4" : ""}`}>{summaryText}</p>
        {isLongSummary && (
          <button
            className="mt-2 text-xs font-semibold text-[var(--signal)] hover:underline"
            onClick={() => setExpanded((value) => !value)}
            type="button"
          >{expanded ? "收起" : "展开全文"}</button>
        )}
        <div className="mt-6 flex flex-wrap gap-2">
          {candidate.positive_literal_matches.map((term) => <Badge className="text-[var(--signal)]" key={`positive-${term}`}>{term}</Badge>)}
          {candidate.negative_literal_matches.map((term) => <Badge className="text-[var(--danger)]" key={`negative-${term}`}>反向 · {term}</Badge>)}
          {candidate.positive_literal_matches.length + candidate.negative_literal_matches.length === 0 && <span className="text-xs text-[var(--muted)]">无字面命中</span>}
        </div>
        <p className="mt-5 rounded-r-md border-l-2 border-[var(--line)] bg-[var(--faint)] py-2 pr-3 pl-4 text-sm leading-6"><span className="font-semibold">入选依据：</span>{candidate.reason ?? "未提供"}</p>
      </article>
      <aside className="flex flex-col border-t border-[var(--line)] bg-[var(--faint)] p-5 lg:border-t-0 lg:border-l">
        <p className="text-xs text-[var(--muted)]">Signal report</p>
        <dl className="mt-4 grid grid-cols-3 gap-2 lg:grid-cols-1">
          <Score label="BM25" value={candidate.bm25_score} />
          <Score label="正向语义" value={candidate.positive_embedding_score} />
          <Score label="反向语义" value={candidate.negative_embedding_score} />
        </dl>
        <div className="mt-5 text-[11px] leading-5 text-[var(--muted)]">
          <p>向量：{candidate.embedding_status} · {candidate.embedding_model ?? "未启用"}</p>
          <p>模型复核：{candidate.model_status}</p>
          <p>规则：{candidate.rules_version ?? "—"}</p>
        </div>
        <div className="mt-auto grid gap-2 pt-6">
          {candidate.url && <a className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-[var(--line)] px-4 text-sm font-semibold text-[var(--ink)] hover:border-[var(--ink)] hover:no-underline" href={candidate.url} rel="noopener noreferrer" target="_blank">查看原文 <ArrowUpRight aria-hidden size={15} /></a>}
          <Button aria-label={`推送到 Notion ${candidate.title_zh}`} disabled={props.busy} onClick={() => void props.onConfirm()}><Check aria-hidden size={16} />推送到 Notion</Button>
          <Button aria-label={`忽略 ${candidate.title_zh}`} disabled={props.busy} onClick={() => void props.onIgnore()} variant="ghost"><X aria-hidden size={16} />忽略</Button>
        </div>
      </aside>
    </li>
  )
}

function Score({ label, value }: { label: string; value: number }) {
  return <div className="border-b border-[var(--line)] py-2"><dt className="text-xs text-[var(--muted)]">{label}</dt><dd className="mt-1 font-mono text-sm">{value.toFixed(3)}</dd></div>
}

function formatDate(value: string | null): string {
  if (!value) return "时间未知"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "时间未知" : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(date)
}
